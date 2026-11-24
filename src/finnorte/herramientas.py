"""Ejecutor de propuestas estructuradas y herramienta de análisis estático."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator

from api import motor

CASOS_EQUIPO = ("limites.py", "tokens.py")
CASOS_PROPIOS = ("importacion.py", "referencia.py", "variable.py")
CASOS = (*CASOS_EQUIPO, *CASOS_PROPIOS)
RUTAS = (*CASOS, "ausente.py")
MAX_BYTES = 30_000
TIEMPO_RUFF = 8
PATRON_RUFF = re.compile(r"(?:(?:E9|F)[0-9]{2,3}|invalid-syntax)")


class ErrorHerramienta(RuntimeError):
    """Error controlado sin exponer rutas del sistema ni código fuente."""


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    esquema: dict
    funcion: Callable
    sensible: bool = False


@dataclass
class Paso:
    n: int
    propuesta: dict
    estado: str = ""
    resultado: dict | None = None


@dataclass
class ResultadoAgente:
    respuesta: str
    fuentes: list[str] = field(default_factory=list)
    pasos: list[Paso] = field(default_factory=list)
    terminado: bool = True


def leer_caso(ruta: str) -> bytes:
    if ruta not in RUTAS:
        raise ErrorHerramienta("El archivo no pertenece al catálogo autorizado.")
    base = motor.RAIZ / "datos/a4"
    if ruta in CASOS_EQUIPO:
        variante, _ = motor.cargar_motor()
        base = Path(variante.RAIZ) / "datos/v2-revisor/codigo"
    try:
        archivo = (base / ruta).resolve(strict=True)
        if archivo.parent != base.resolve() or not archivo.is_file():
            raise ErrorHerramienta("El archivo está fuera del catálogo autorizado.")
        with archivo.open("rb") as entrada:
            codigo = entrada.read(MAX_BYTES + 1)
    except OSError:
        raise ErrorHerramienta("El archivo seleccionado no está disponible.") from None
    if len(codigo) > MAX_BYTES:
        raise ErrorHerramienta("El archivo supera el límite de 30 000 bytes.")
    return codigo


def correr_linter(ruta: str, *, contenido: bytes | None = None) -> dict:
    """Entrega a Ruff los bytes autorizados por stdin. El archivo nunca se importa."""
    if ruta not in RUTAS:
        raise ErrorHerramienta("El archivo no pertenece al catálogo autorizado.")
    codigo = leer_caso(ruta) if contenido is None else contenido
    if len(codigo) > MAX_BYTES:
        raise ErrorHerramienta("El archivo supera el límite de 30 000 bytes.")
    try:
        proceso = subprocess.run(
            [sys.executable, "-I", "-m", "ruff", "check", "--isolated", "--no-cache",
             "--select", "E9,F", "--output-format", "json", "--stdin-filename", ruta, "-"],
            input=codigo, capture_output=True, timeout=TIEMPO_RUFF, cwd=motor.RAIZ, check=False,
        )
    except subprocess.TimeoutExpired:
        raise ErrorHerramienta("Ruff superó el límite de 8 segundos.") from None
    except OSError:
        raise ErrorHerramienta("No pude iniciar Ruff.") from None
    if proceso.returncode not in (0, 1):
        raise ErrorHerramienta("Ruff no pudo analizar el archivo.")
    try:
        diagnosticos = json.loads(proceso.stdout)
        avisos = [{"codigo": d["code"], "linea": d["location"]["row"]} for d in diagnosticos]
        if any(not PATRON_RUFF.fullmatch(a["codigo"]) or type(a["linea"]) is not int for a in avisos):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ErrorHerramienta("Ruff devolvió un formato inesperado.") from None
    return {"archivo": ruta, "analizador": "Ruff", "avisos": avisos}


def herramienta_linter(ruta: str, *, contenido: bytes | None = None) -> Herramienta:
    esquema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["ruta"],
        "additionalProperties": False,
        "properties": {"ruta": {"type": "string", "enum": [ruta]}},
    }
    return Herramienta("correr_linter", "Analiza un archivo Python autorizado con Ruff",
                       esquema, partial(correr_linter, contenido=contenido), sensible=True)


def proveedor_configurado(prompt: str, contexto: dict) -> dict:
    if os.getenv("LLM_PROVIDER", "gemini" if os.getenv("GEMINI_API_KEY") else "fake") == "fake":
        if contexto["ruta"] and not contexto["pasos"]:
            return {"accion": "usar", "herramienta": "correr_linter", "argumentos": {"ruta": contexto["ruta"]}}
        return {"accion": "responder"}
    _, llm = motor.cargar_motor()
    try:
        respuesta = llm.generar(json.dumps(contexto, ensure_ascii=False), prompt, json=True,
                                temperatura=0, etiqueta="a4/agente", registrar=False)
    except llm.LLMError:
        raise ErrorHerramienta("El proveedor del agente no está disponible.") from None
    return respuesta.datos


def ejecutar_agente(tarea: str, herramientas: list[Herramienta],
                    confirmar: Callable[[Herramienta, dict], bool | None] | None = None,
                    max_pasos: int = 4, *, ruta: str = "", version: int = 2,
                    proponer: Callable[[str, dict], dict] = proveedor_configurado) -> ResultadoAgente:
    """Valida cada propuesta y registra los estados sin devolver texto libre del modelo."""
    if version not in (1, 2) or type(max_pasos) is not int or max_pasos < 1:
        raise ValueError("Configuración del agente inválida.")
    prompt = (motor.RAIZ / "prompts" / f"a4_agente.v{version}.md").read_text(encoding="utf-8")
    catalogo = {h.nombre: h for h in herramientas}
    validadores = {nombre: Draft202012Validator(h.esquema) for nombre, h in catalogo.items()}
    datos = [{"nombre": h.nombre, "esquema": h.esquema, "sensible": h.sensible} for h in herramientas]
    pasos: list[Paso] = []
    vistas: set[str] = set()
    for numero in range(1, min(max_pasos, 6) + 1):
        contexto = {"tarea": tarea, "ruta": ruta, "herramientas": datos,
                    "pasos": [paso.estado for paso in pasos]}
        try:
            propuesta = proponer(prompt, contexto)
        except (ErrorHerramienta, motor.MotorNoDisponible):
            pasos.append(Paso(numero, {}, "error_proveedor"))
            return ResultadoAgente("El proveedor no pudo generar una propuesta.", pasos=pasos, terminado=False)
        if propuesta == {"accion": "responder"}:
            if version == 2 and ruta and not any(p.estado == "ejecutada" for p in pasos):
                pasos.append(Paso(numero, {}, "omision"))
                continue
            pasos.append(Paso(numero, {"accion": "responder"}, "respuesta"))
            return ResultadoAgente("La solicitud terminó.", pasos=pasos)
        nombre = propuesta.get("herramienta") if isinstance(propuesta, dict) else None
        args = propuesta.get("argumentos") if isinstance(propuesta, dict) else None
        if (not isinstance(nombre, str) or nombre not in catalogo
                or propuesta.get("accion") != "usar"
                or set(propuesta) != {"accion", "herramienta", "argumentos"}
                or not validadores[nombre].is_valid(args)):
            pasos.append(Paso(numero, {}, "invalida"))
            if version == 1:
                break
            continue
        paso = Paso(numero, {"accion": "usar", "herramienta": nombre, "argumentos": dict(args)})
        pasos.append(paso)
        firma = json.dumps([nombre, args], sort_keys=True)
        if firma in vistas:
            paso.estado = "repetida"
            break
        vistas.add(firma)
        herramienta = catalogo[nombre]
        if herramienta.sensible:
            decision = confirmar(herramienta, dict(args)) if confirmar else False
            if decision is not True:
                paso.estado = "pendiente" if decision is None else "rechazada"
                texto = "El análisis espera tu autorización." if decision is None else "Se rechazó el análisis."
                return ResultadoAgente(texto, pasos=pasos)
        try:
            paso.resultado = herramienta.funcion(**args)
            paso.estado = "ejecutada"
        except ErrorHerramienta as exc:
            paso.resultado = {"error": str(exc)}
            paso.estado = "error_herramienta"
            return ResultadoAgente("La herramienta no pudo completar el análisis.", pasos=pasos, terminado=False)
    return ResultadoAgente("El agente se detuvo sin completar la solicitud.", pasos=pasos, terminado=False)
