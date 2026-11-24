"""Ejecuta los dos casos mediante ASGI y guarda un resumen real sin respuestas crudas."""
import argparse
import importlib.metadata
import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from api.motor import RAIZ, REVISION, cargar_motor
from api.producto import crear_app


def ejecutar(salida: Path):
    load_dotenv(RAIZ / ".env", override=False)
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("Configura GEMINI_API_KEY en el entorno antes de ejecutar este comando")
    os.environ["LLM_PROVIDER"] = "gemini"
    os.environ["EMB_PROVIDER"] = "gemini"
    if not os.getenv("TOKEN_SECRET"):
        os.environ["TOKEN_SECRET"] = secrets.token_hex(32)
    variante, _ = cargar_motor()
    from finnorte.config import config

    configuracion = config()
    casos = []
    with TestClient(crear_app(":memory:")) as cliente:
        cuenta = {"email": "gemini-a3@example.com", "contrasena": secrets.token_urlsafe(18)}
        cliente.post("/auth/registro", json=cuenta).raise_for_status()
        login = cliente.post("/auth/login", json=cuenta)
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        for nombre in ("limites.py", "tokens.py"):
            codigo = (Path(variante.RAIZ) / "datos/v2-revisor/codigo" / nombre).read_text(encoding="utf-8")
            respuesta = cliente.post("/v1/v2-revisor", json={"codigo": codigo}, headers=headers)
            cuerpo = respuesta.json()
            dictamen = cuerpo.get("artefacto", {}).get("dictamen", {})
            casos.append({
                "archivo": nombre,
                "http": respuesta.status_code,
                "abstuvo": cuerpo.get("abstuvo"),
                "demo": cuerpo.get("demo"),
                "estado": dictamen.get("estado"),
                "total_hallazgos": dictamen.get("total_hallazgos"),
                "reglas": [h["regla"] for h in dictamen.get("hallazgos", [])],
                "fuentes": cuerpo.get("fuentes", []),
                "errores_de_validacion": len(cuerpo.get("errores_citas", [])),
            })
    datos = {"revision": REVISION, "proveedor": configuracion.llm_proveedor, "modelo": configuracion.llm_modelo,
             "embeddings": configuracion.emb_proveedor, "fastapi": importlib.metadata.version("fastapi"), "casos": casos}
    salida.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(datos, ensure_ascii=False, indent=2)
    salida.write_text(texto + "\n", encoding="utf-8")
    print(texto)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("salida", type=Path)
    ejecutar(parser.parse_args().salida)
