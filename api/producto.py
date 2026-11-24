"""Servicio REST autenticado para la revisión y el agente de FinNorte."""
from __future__ import annotations

import ast
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints, field_validator
from pydantic_core import PydanticCustomError
from starlette.exceptions import HTTPException

from api import auth, motor
from src.finnorte import agente_servicio, herramientas, validador

ArchivoCatalogo = Literal["limites.py", "tokens.py", "importacion.py", "referencia.py", "variable.py", "ausente.py"]


class ErrorServicio(Exception):
    def __init__(self, status: int, detalle: str):
        super().__init__(detalle)
        self.status = status


class LimiteSolicitudes:
    def __init__(self, maximo: int):
        self.maximo = maximo
        self.ventanas: dict[str, deque[float]] = {}
        self.candado = Lock()
        self.proxima_limpieza = 0.0

    def contar(self, usuario: str) -> None:
        ahora = time.monotonic()
        with self.candado:
            if ahora >= self.proxima_limpieza:
                self.ventanas = {u: v for u, v in self.ventanas.items() if v[-1] > ahora - 60}
                self.proxima_limpieza = ahora + 60
            ventana = self.ventanas.setdefault(usuario, deque())
            while ventana and ventana[0] <= ahora - 60:
                ventana.popleft()
            if len(ventana) >= self.maximo:
                raise ErrorServicio(429, "Límite de solicitudes por minuto alcanzado.")
            ventana.append(ahora)


class Credenciales(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Annotated[str, StringConstraints(strict=True, min_length=3, max_length=254)]
    contrasena: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]


class EntradaRevisor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=30_000)]

    @field_validator("codigo")
    @classmethod
    def validar_python(cls, valor: str) -> str:
        if not valor.strip():
            raise PydanticCustomError("codigo_vacio", "El código está vacío.")
        try:
            ast.parse(valor)
        except SyntaxError as exc:
            raise PydanticCustomError("codigo_sintaxis", "Sintaxis Python inválida en la línea {linea}.",
                                      {"linea": exc.lineno or 1}) from None
        except (ValueError, RecursionError):
            raise PydanticCustomError("codigo_profundidad", "El código excede la complejidad que puedo analizar.") from None
        return valor


class EntradaAgente(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tarea: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=360)]
    ruta: ArchivoCatalogo
    version: Literal[1, 2] = 2


class Confirmacion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aprobar: StrictBool


def _herramientas(ruta: str) -> list[herramientas.Herramienta]:
    return [herramientas.herramienta_linter(ruta)]


def problema(status: int, detalle: str, headers: dict | None = None) -> JSONResponse:
    encabezados = dict(headers or {})
    if status == 401:
        encabezados.setdefault("WWW-Authenticate", "Bearer")
    return JSONResponse(status_code=status, media_type="application/problem+json", headers=encabezados, content={
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detalle,
        "trace_id": uuid4().hex,
    })


def detalle_validacion(error: RequestValidationError) -> str:
    reglas = {
        "missing": "campo obligatorio",
        "string_type": "debe ser texto",
        "string_too_short": "el texto es demasiado corto",
        "string_too_long": "excede la longitud permitida",
        "codigo_vacio": "el código está vacío",
        "codigo_profundidad": "el código excede la profundidad que puedo analizar",
        "json_invalid": "JSON inválido",
        "extra_forbidden": "contiene campos adicionales no permitidos",
    }
    mensajes = []
    for problema_entrada in error.errors():
        ubicacion = problema_entrada["loc"]
        clave = ubicacion[1] if len(ubicacion) > 1 else "cuerpo"
        campo = clave if clave in ("codigo", "email", "contrasena", "tarea", "ruta", "archivo", "aprobar", "version") else "cuerpo"
        tipo = problema_entrada["type"]
        mensaje = reglas.get(tipo, "formato inválido")
        if tipo == "codigo_sintaxis":
            mensaje = f"sintaxis Python inválida en la línea {problema_entrada['ctx']['linea']}"
        mensajes.append(f"{campo}: {mensaje}")
    return ". ".join(dict.fromkeys(mensajes)) + "."


bearer = HTTPBearer(auto_error=False)


def usuario_actual(request: Request, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if cred is None:
        raise ErrorServicio(401, "Se requiere un token Bearer.")
    usuario = auth.validar_token(cred.credentials)
    request.app.state.limite.contar(usuario)
    return usuario


def crear_app(ruta_db: str | None = None, maximo: int | None = None, *,
              trazas_a4: Path | None = None, proponer=herramientas.proveedor_configurado) -> FastAPI:
    @asynccontextmanager
    async def lifespan(servicio: FastAPI):
        ruta = ruta_db or os.getenv("AUTH_DB", str(motor.RAIZ / "bitacora" / "usuarios.db"))
        if ruta != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        servicio.state.auth = auth.Autenticador(ruta)
        servicio.state.limite = LimiteSolicitudes(max(1, maximo if maximo is not None else int(os.getenv("API_LIMITE", "30"))))
        servicio.state.agente = agente_servicio.AgenteServicio(trazas_a4)
        try:
            yield
        finally:
            servicio.state.auth.db.close()

    servicio = FastAPI(title="FinNorte · Actividad 4", lifespan=lifespan)

    @servicio.exception_handler(auth.ErrorAuth)
    @servicio.exception_handler(ErrorServicio)
    async def manejar_error(_request: Request, error: auth.ErrorAuth | ErrorServicio):
        return problema(error.status, str(error))

    @servicio.exception_handler(RequestValidationError)
    async def manejar_validacion(_request: Request, error: RequestValidationError):
        return problema(422, detalle_validacion(error))

    @servicio.exception_handler(HTTPException)
    async def manejar_http(_request: Request, error: HTTPException):
        return problema(error.status_code, HTTPStatus(error.status_code).phrase, error.headers)

    @servicio.exception_handler(Exception)
    async def manejar_inesperado(_request: Request, _error: Exception):
        return problema(500, "El servicio no pudo procesar la solicitud.")

    @servicio.get("/salud")
    def salud():
        return {"estado": "ok", "variante": "v2-revisor"}

    @servicio.post("/auth/registro", status_code=201)
    def registro(datos: Credenciales, request: Request):
        request.app.state.auth.registrar(datos.email, datos.contrasena)
        return {"mensaje": "Registro exitoso"}

    @servicio.post("/auth/login")
    def login(datos: Credenciales, request: Request):
        token = request.app.state.auth.login(datos.email, datos.contrasena)
        return {"token": token, "tipo": "Bearer", "expira_en_s": auth.VIGENCIA_S}

    @servicio.post("/v1/v2-revisor")
    def ejecutar_revisor(entrada: EntradaRevisor, request: Request,
                         _usuario: Annotated[str, Depends(usuario_actual)], archivo: ArchivoCatalogo | None = None):
        try:
            if archivo is not None:
                original = herramientas.leer_caso(archivo).decode("utf-8")
                if original.splitlines() != entrada.codigo.splitlines():
                    raise ErrorServicio(422, "El contenido no coincide con el archivo del catálogo.")
            salida = motor.revisar(entrada.codigo)
            # Se conserva el contrato de los adaptadores de A3 que no entregan artefacto.
            if "artefacto" not in salida:
                return salida
            variante, _ = motor.cargar_motor()
            fragmentos = {f.id for f in variante.indice().fragmentos}
            revision = validador.validar_revision(salida, entrada.codigo, archivo, fragmentos)
            request.app.state.agente.registrar(tipo="revision", archivo=archivo, validacion=revision["estado"])
            if not revision["ok"]:
                salida = {**salida, "abstuvo": True, "artefacto": {}, "fuentes": [], "errores_citas": [],
                          "respuesta": "No pude verificar el dictamen. Se requiere revisión humana."}
            return {**salida, "validador": revision}
        except motor.MotorNoDisponible as exc:
            raise ErrorServicio(503, "El motor de revisión no está disponible.") from exc
        except herramientas.ErrorHerramienta as exc:
            raise ErrorServicio(422, str(exc)) from exc

    @servicio.get("/v1/agente/casos")
    def casos(_usuario: Annotated[str, Depends(usuario_actual)]):
        return {"archivos": herramientas.CASOS, "prueba_de_falla": "ausente.py"}

    @servicio.get("/v1/agente/casos/{archivo}")
    def leer_caso(archivo: ArchivoCatalogo, _usuario: Annotated[str, Depends(usuario_actual)]):
        try:
            return {"archivo": archivo, "codigo": herramientas.leer_caso(archivo).decode("utf-8")}
        except herramientas.ErrorHerramienta as exc:
            raise ErrorServicio(404, str(exc)) from exc
        except motor.MotorNoDisponible as exc:
            raise ErrorServicio(503, "El motor de revisión no está disponible.") from exc

    @servicio.post("/v1/agente")
    def agente(datos: EntradaAgente, request: Request, usuario: Annotated[str, Depends(usuario_actual)]):
        try:
            return request.app.state.agente.iniciar(
                datos.tarea, usuario, datos.ruta, _herramientas(datos.ruta),
                ejecutor=herramientas.ejecutar_agente, validador=validador.validar_plan,
                version=datos.version, proponer=proponer,
            )
        except herramientas.ErrorHerramienta as exc:
            raise ErrorServicio(503, str(exc)) from exc

    @servicio.post("/v1/agente/confirmar/{id_}")
    def confirmar(id_: str, datos: Confirmacion, request: Request, usuario: Annotated[str, Depends(usuario_actual)]):
        try:
            return request.app.state.agente.resolver(id_, usuario, datos.aprobar)
        except KeyError:
            raise ErrorServicio(404, "No existe una acción pendiente para este usuario.") from None

    return servicio


app = crear_app()
