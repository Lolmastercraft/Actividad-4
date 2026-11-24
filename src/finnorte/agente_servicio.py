"""Solicitudes del agente con confirmación de un solo uso y eventos JSONL."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from api import motor

from . import herramientas, validador as controles

VIGENCIA_PENDIENTE_S = 10 * 60
MAX_PENDIENTES = 128


@dataclass(frozen=True)
class Pendiente:
    usuario: str
    ruta: str
    vence: float
    contenido: bytes | None


class AgenteServicio:
    def __init__(self, trazas: Path | None = None):
        self.pendientes: dict[str, Pendiente] = {}
        self.candado = Lock()
        self.trazas = trazas or Path(os.getenv("A4_TRAZAS", str(motor.RAIZ / "bitacora/trazas_a4.jsonl")))

    def registrar(self, **datos) -> None:
        evento = {"ts": datetime.now(timezone.utc).isoformat(), **datos}
        with self.candado:
            self.trazas.parent.mkdir(parents=True, exist_ok=True)
            with self.trazas.open("a", encoding="utf-8") as salida:
                salida.write(json.dumps(evento, ensure_ascii=False) + "\n")

    def iniciar(self, tarea: str, usuario: str, ruta: str, catalogo: list, *,
                ejecutor=herramientas.ejecutar_agente, validador=controles.validar_plan,
                version: int = 2, proponer=herramientas.proveedor_configurado) -> dict:
        propuestas = []

        def confirmar(herramienta, args):
            propuestas.append((herramienta.nombre, args))
            return None

        resultado = ejecutor(tarea, catalogo, confirmar=confirmar, ruta=ruta, version=version, proponer=proponer)
        revision = controles.veredicto(validador(resultado, propuestas, ruta))
        pendientes = []
        if revision["ok"]:
            contenido = None
            try:
                contenido = herramientas.leer_caso(ruta)
            except (herramientas.ErrorHerramienta, motor.MotorNoDisponible):
                # Un archivo ausente puede producir la falla controlada tras la aprobación.
                pass
            huella = hashlib.sha256(contenido).hexdigest() if contenido is not None else None
            id_ = uuid4().hex
            ahora = time.monotonic()
            with self.candado:
                self.pendientes = {clave: p for clave, p in self.pendientes.items() if p.vence > ahora}
                if len(self.pendientes) >= MAX_PENDIENTES:
                    raise herramientas.ErrorHerramienta("Hay demasiadas acciones pendientes.")
                self.pendientes[id_] = Pendiente(usuario, ruta, ahora + VIGENCIA_PENDIENTE_S, contenido)
            pendientes = [{"id": id_, "herramienta": "correr_linter", "argumentos": {"ruta": ruta},
                           "sha256": huella, "expira_en_s": VIGENCIA_PENDIENTE_S}]
        pasos = [{"n": p.n, **p.propuesta, "estado": p.estado, "resultado": p.resultado} for p in resultado.pasos]
        self.registrar(tipo="propuesta", archivo=ruta, version=version,
                       estados=[p["estado"] for p in pasos], validacion=revision["estado"])
        return {"respuesta": resultado.respuesta, "fuentes": [], "terminado": resultado.terminado,
                "pasos": pasos, "validador": revision, "pendientes": pendientes}

    def resolver(self, id_: str, usuario: str, aprobar: bool) -> dict:
        with self.candado:
            pendiente = self.pendientes.get(id_)
            if pendiente is None or pendiente.usuario != usuario:
                raise KeyError(id_)
            self.pendientes.pop(id_)
        ruta = pendiente.ruta
        estado = "rechazada"
        revision = controles.veredicto([])
        resultado = None
        if pendiente.vence <= time.monotonic():
            estado = "expirada"
            revision = controles.veredicto(["La autorización expiró."])
        elif aprobar:
            try:
                if pendiente.contenido is None:
                    raise herramientas.ErrorHerramienta("El archivo seleccionado no estaba disponible al solicitar la autorización.")
                herramienta = herramientas.herramienta_linter(ruta, contenido=pendiente.contenido)
                resultado = herramienta.funcion(ruta=ruta)
                revision = controles.validar_linter(resultado, ruta, len(pendiente.contenido.splitlines()))
                estado = "ejecutada" if revision["ok"] else "resultado_rechazado"
                if not revision["ok"]:
                    resultado = None
            except herramientas.ErrorHerramienta as exc:
                estado = "error_herramienta"
                revision = controles.veredicto([str(exc)])
        self.registrar(tipo="decision", archivo=ruta, estado=estado, validacion=revision["estado"])
        return {"estado": estado, "herramienta": "correr_linter", "argumentos": {"ruta": ruta},
                "resultado": resultado, "validador": revision, "fuentes": []}
