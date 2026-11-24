import json
import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.producto import crear_app


CUENTA = {"email": "estudiante@example.com", "contrasena": "clave-de-prueba-A3"}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("TOKEN_SECRET", secrets.token_hex(32))
    with TestClient(crear_app(":memory:", maximo=3)) as http:
        yield http


@pytest.fixture
def cuenta(cliente):
    assert cliente.post("/auth/registro", json=CUENTA).status_code == 201
    return dict(CUENTA)


@pytest.fixture
def bearer(cliente, cuenta):
    respuesta = cliente.post("/auth/login", json=cuenta)
    assert respuesta.status_code == 200
    return {"Authorization": f"Bearer {respuesta.json()['token']}"}


@pytest.fixture
def evidencia():
    def guardar(nombre, datos):
        destino = os.getenv("A3_EVIDENCIAS")
        if destino:
            carpeta = Path(destino)
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / f"{nombre}.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return guardar
