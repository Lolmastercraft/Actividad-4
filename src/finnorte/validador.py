"""Control local de procedencia y de consistencia del artefacto."""
from __future__ import annotations

import re

from .herramientas import PATRON_RUFF, ResultadoAgente

REGLA = re.compile(r"SEC-(?:0[1-9]|10)")
FUENTE = re.compile(r"sec-(?:0[1-9]|10)#[0-9]+")


def veredicto(errores: list[str], *, abstencion: bool = False) -> dict:
    return {"ok": not errores and not abstencion, "estado": (
        "abstencion" if abstencion else "rechazado" if errores else "verificado"),
        "hallazgos": errores}


def validar_revision(salida: dict, codigo: str, archivo: str | None, fragmentos: set[str]) -> dict:
    if salida.get("abstuvo"):
        return veredicto(["El motor solicitó revisión humana."], abstencion=True)
    artefacto = salida.get("artefacto") or {}
    hallazgos = artefacto.get("hallazgos")
    dictamen = artefacto.get("dictamen")
    if not isinstance(hallazgos, list) or not isinstance(dictamen, dict):
        return veredicto(["Falta el dictamen del revisor."])
    fuentes = salida.get("fuentes") or []
    recuperados = salida.get("recuperados") or []
    if any(not isinstance(f, str) or not FUENTE.fullmatch(f) or f not in fragmentos
           for f in [*fuentes, *recuperados]):
        return veredicto(["Se incluyó una fuente ajena al corpus autorizado."])
    errores = []
    if salida.get("errores_citas"):
        errores.append("El motor reportó errores de citación.")
    cantidad = len(hallazgos)
    esperado = "con_hallazgos" if cantidad else "sin_hallazgos"
    if dictamen.get("estado") != esperado or dictamen.get("total_hallazgos") != cantidad:
        errores.append("El total o el estado del dictamen no coincide con los hallazgos.")
    if archivo == "limites.py" and cantidad:
        errores.append("El caso de control limites.py debe tener cero hallazgos.")
    originales = set()
    lineas = codigo.splitlines()
    for n, dato in enumerate(hallazgos, 1):
        if not isinstance(dato, dict):
            errores.append(f"El hallazgo {n} no es un objeto.")
            continue
        regla, linea, cita = (dato.get(campo) for campo in ("regla", "linea", "fuente"))
        if (not isinstance(regla, str) or not REGLA.fullmatch(regla)
                or not isinstance(cita, str) or cita not in fuentes or cita not in recuperados
                or cita.split("#")[0] != regla.lower()):
            errores.append(f"La regla y la fuente del hallazgo {n} no coinciden con lo recuperado.")
        if type(linea) is not int or not 1 <= linea <= len(lineas) or not lineas[linea - 1].strip():
            errores.append(f"El hallazgo {n} no apunta a una línea existente con contenido.")
        elif isinstance(regla, str) and isinstance(dato.get("id"), str):
            originales.add((dato["id"], regla, linea))
    cierre = dictamen.get("hallazgos")
    if (not isinstance(cierre, list) or len(cierre) != cantidad
            or any(not isinstance(h, dict) or not isinstance(h.get("id"), str)
                   or not isinstance(h.get("regla"), str) or type(h.get("linea")) is not int for h in cierre)
            or {(h["id"], h["regla"], h["linea"]) for h in cierre} != originales):
        errores.append("El dictamen agregó, omitió o cambió un hallazgo respaldado.")
    return veredicto(errores)


def validar_linter(resultado: dict, ruta: str, total_lineas: int) -> dict:
    errores = []
    if resultado.get("archivo") != ruta or resultado.get("analizador") != "Ruff":
        errores.append("Los metadatos del resultado no coinciden con la herramienta aprobada.")
    avisos = resultado.get("avisos")
    if not isinstance(avisos, list) or any(
        not isinstance(a, dict) or not isinstance(a.get("codigo"), str)
        or not PATRON_RUFF.fullmatch(a["codigo"]) or type(a.get("linea")) is not int
        or not 1 <= a["linea"] <= total_lineas for a in avisos
    ):
        errores.append("Hay un diagnóstico fuera del archivo analizado o ajeno al catálogo de Ruff.")
    if ruta == "limites.py" and avisos:
        errores.append("El caso de control limites.py debe quedar sin avisos.")
    return veredicto(errores)


def validar_plan(resultado: ResultadoAgente, propuestas: list[tuple[str, dict]], ruta: str) -> list[str]:
    if resultado.fuentes:
        return ["El agente propuso fuentes fuera de las observaciones disponibles."]
    if propuestas != [("correr_linter", {"ruta": ruta})]:
        return ["Falta una propuesta de análisis para el archivo seleccionado."]
    return []
