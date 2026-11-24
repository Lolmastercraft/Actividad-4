"""Conexión al motor original del Avance 1 instalado junto al servicio."""
import importlib
import hashlib
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
REVISION = "6c1835b1a556240382c3d678ecec6bf0af6f5948"


class MotorNoDisponible(RuntimeError):
    """Falta el motor esperado o su proveedor temporalmente no está disponible."""


def verificar_snapshot(carpeta: Path) -> None:
    """Verifica el conjunto de archivos aprobado para la instalación local."""
    manifiesto = json.loads((RAIZ / "guia" / "motor_manifest.json").read_text(encoding="utf-8"))
    if manifiesto["revision"] != REVISION:
        raise MotorNoDisponible("Manifiesto de motor inesperado")
    for nombre, sha in manifiesto["sha256"].items():
        archivo = carpeta / nombre
        if not archivo.is_file() or hashlib.sha256(archivo.read_bytes()).hexdigest() != sha:
            raise MotorNoDisponible(f"El motor local no pasa la verificación: {nombre}")


@lru_cache(maxsize=1)
def cargar_motor():
    carpeta = Path(os.getenv("FINNORTE_MOTOR", str(RAIZ / ".motor"))).resolve()
    origen = carpeta / "src" / "finnorte" / "variante.py"
    try:
        if (carpeta / "REVISION").read_text(encoding="ascii").strip() != REVISION or not origen.is_file():
            raise MotorNoDisponible("Revisión de motor inesperada")
        verificar_snapshot(carpeta)
        os.environ.setdefault("FINNORTE_DIR_TRAZAS", str(RAIZ / "bitacora" / "motor"))
        sys.path.insert(0, str(carpeta / "src"))
        variante = importlib.import_module("finnorte.variante")
        if Path(variante.__file__).resolve() != origen or variante.VARIANTE != "v2-revisor":
            raise MotorNoDisponible("El módulo cargado no corresponde a v2-revisor")
        proveedor = importlib.import_module("finnorte.llm")
    except (OSError, ImportError) as exc:
        raise MotorNoDisponible("Ejecuta python -m guia.preparar_motor") from exc
    return variante, proveedor


def revisar(codigo: str) -> dict:
    variante, proveedor = cargar_motor()
    try:
        return variante.sistema({"codigo": codigo})
    except proveedor.LLMError as exc:
        raise MotorNoDisponible("Proveedor no disponible") from exc
