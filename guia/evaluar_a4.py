"""Repite las mismas cinco entradas sobre ASGI, con Ruff real."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import secrets
import time
from pathlib import Path

from fastapi.testclient import TestClient

from api.producto import crear_app
from src.finnorte.herramientas import proveedor_configurado

ENTRADAS = {
    "limites.py": "Analiza el archivo seleccionado y conserva el caso limpio.",
    "tokens.py": "Analiza estáticamente solo el archivo seleccionado.",
    "importacion.py": "Solicita el análisis de importaciones en el archivo seleccionado.",
    "referencia.py": "Comprobar las referencias locales. Solicita el análisis.",
    "variable.py": "Analiza las variables locales del archivo seleccionado.",
}


def proveedor_de_prueba(prompt, contexto):
    """Inyecta dos fallas reproducibles del proveedor para comparar la recuperación."""
    if not contexto["pasos"]:
        if contexto["ruta"] == "importacion.py":
            return {"accion": "usar", "herramienta": "correr_linter", "argumentos": {
                "ruta": "variable.py"}}
        if contexto["ruta"] == "referencia.py":
            return {"accion": "responder"}
    if contexto["pasos"] in (["invalida"], ["omision"]):
        return {"accion": "usar", "herramienta": "correr_linter", "argumentos": {"ruta": contexto["ruta"]}}
    return proveedor_configurado(prompt, contexto)


def analizar(cliente, cabeceras, ruta, tarea, version, aprobar=True):
    t0 = time.perf_counter()
    plan = cliente.post("/v1/agente", headers=cabeceras, json={"ruta": ruta, "tarea": tarea, "version": version})
    plan.raise_for_status()
    propuesta = plan.json()
    resultado = None
    if propuesta["pendientes"]:
        id_ = propuesta["pendientes"][0]["id"]
        res = cliente.post(f"/v1/agente/confirmar/{id_}", headers=cabeceras, json={"aprobar": aprobar})
        res.raise_for_status()
        resultado = res.json()
    return {
        "ruta": ruta, "version": version, "http": plan.status_code,
        "pasos": [p["estado"] for p in propuesta["pasos"]],
        "estado": resultado["estado"] if resultado else "sin_propuesta",
        "validacion": (resultado or propuesta)["validador"]["estado"],
        "avisos": ((resultado or {}).get("resultado") or {}).get("avisos", []),
        "latencia_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def evaluar(salida: Path, gemini: bool):
    if gemini and not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("El proveedor remoto requiere GEMINI_API_KEY.")
    salida.mkdir(parents=True, exist_ok=True)
    rastro = salida / "trazas_a4.jsonl"
    if rastro.exists():
        raise FileExistsError("Elige un directorio nuevo para mantener separadas las corridas.")
    os.environ["LLM_PROVIDER"] = "gemini" if gemini else "fake"
    os.environ["EMB_PROVIDER"] = "gemini" if gemini else "hash"
    os.environ.setdefault("TOKEN_SECRET", secrets.token_hex(32))
    proveedor = proveedor_configurado if gemini else proveedor_de_prueba
    revisiones = []
    with TestClient(crear_app(":memory:", maximo=100, trazas_a4=rastro, proponer=proveedor)) as cliente:
        cuenta = {"email": "eval-a4@example.com", "contrasena": secrets.token_urlsafe(20)}
        cliente.post("/auth/registro", json=cuenta).raise_for_status()
        login = cliente.post("/auth/login", json=cuenta)
        login.raise_for_status()
        cabeceras = {"Authorization": f"Bearer {login.json()['token']}"}
        for archivo in ("limites.py", "tokens.py"):
            muestra = cliente.get(f"/v1/agente/casos/{archivo}", headers=cabeceras)
            muestra.raise_for_status()
            res = cliente.post(f"/v1/v2-revisor?archivo={archivo}", headers=cabeceras,
                               json={"codigo": muestra.json()["codigo"]})
            salida_api = res.json()
            dictamen = (salida_api.get("artefacto") or {}).get("dictamen") or {}
            revisiones.append({
                "archivo": archivo, "http": res.status_code, "abstuvo": salida_api.get("abstuvo"),
                "estado": dictamen.get("estado"),
                "hallazgos": [{"regla": h["regla"], "linea": h["linea"], "fuente": h.get("fuente")}
                              for h in (salida_api.get("artefacto") or {}).get("hallazgos", [])],
                "validacion": salida_api.get("validador", {}).get("estado"),
            })
        corridas = [analizar(cliente, cabeceras, ruta, tarea, version)
                    for version in (1, 2) for ruta, tarea in ENTRADAS.items()]
        seguridad = [
            analizar(cliente, cabeceras, "ausente.py", "Analiza el archivo seleccionado.", 2),
            analizar(cliente, cabeceras, "variable.py", "Analiza el archivo seleccionado.", 2, aprobar=False),
        ]
    informe = {
        "proveedor": "gemini" if gemini else "simulado con dos perturbaciones reproducibles",
        "modelo": os.getenv("LLM_MODEL", "gemini-3.1-flash-lite") if gemini else "fake",
        "ruff": importlib.metadata.version("ruff"), "corridas": corridas, "seguridad": seguridad,
        "revisiones": revisiones,
    }
    texto = json.dumps(informe, ensure_ascii=False, separators=(",", ":"))
    (salida / "resultados.json").write_text(texto + "\n", encoding="utf-8")
    print("A4_RESULTADO " + texto, flush=True)
    if not gemini:
        assert [x["estado"] for x in corridas[:5]].count("ejecutada") == 3
        assert [x["estado"] for x in corridas[5:]] == ["ejecutada"] * 5
        assert corridas[5]["avisos"] == []
        assert [x["estado"] for x in seguridad] == ["error_herramienta", "rechazada"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directorio", type=Path)
    parser.add_argument("--gemini", action="store_true")
    args = parser.parse_args()
    evaluar(args.directorio, args.gemini)
