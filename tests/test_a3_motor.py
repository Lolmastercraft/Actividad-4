import json
import runpy
from pathlib import Path

import pytest

from api.motor import REVISION, cargar_motor
from api import motor


@pytest.mark.parametrize(("nombre", "estado", "total"), [
    ("limites.py", "sin_hallazgos", 0),
    ("tokens.py", "con_hallazgos", 1),
])
@pytest.mark.motor_local
def test_endpoint_ejecuta_motor_del_equipo(cliente, bearer, monkeypatch, evidencia, nombre, estado, total):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("EMB_PROVIDER", "hash")
    variante, llm = cargar_motor()
    raiz = Path(variante.RAIZ)
    codigo = (raiz / "datos" / "v2-revisor" / "codigo" / nombre).read_text(encoding="utf-8")
    respuestas_para = runpy.run_path(str(raiz / "guia" / "demo_revisor.py"))["respuestas_para"]
    respuestas = respuestas_para(nombre, codigo)
    # El esquema del Avance 1 valida la cita también en el caso preparado del equipo.
    for etapa in ("Eres revisor técnico", "Eres redactor técnico"):
        for hallazgo in respuestas[etapa]["hallazgos"]:
            hallazgo["fuente"] = "sec-09#0"
    llamadas = []

    def responder(_prompt, sistema):
        marca = next(marca for marca in respuestas if marca in sistema)
        llamadas.append(marca)
        return json.dumps(respuestas[marca], ensure_ascii=False)

    monkeypatch.setattr(llm.fake, "responder", responder)
    respuesta = cliente.post("/v1/v2-revisor", json={"codigo": codigo}, headers=bearer)
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["demo"] is True and not datos["abstuvo"]
    assert llamadas == list(respuestas)
    artefacto = datos["artefacto"]
    dictamen = artefacto["dictamen"]
    assert dictamen["estado"] == estado and dictamen["total_hallazgos"] == total
    if total:
        assert artefacto["hallazgos"][0]["regla"] == "SEC-09"
        assert any(cita.lower().startswith("sec-09#") for cita in datos["fuentes"])
        assert "yaml.safe_load" in artefacto["codigo_corregido"]
    else:
        assert artefacto["codigo_corregido"] == codigo
    evidencia(nombre.removesuffix(".py"), {
        "status": respuesta.status_code, "entrada": nombre, "revision": REVISION,
        "proveedor": "fake con respuestas de prueba del equipo", "etapas": len(llamadas),
        "estado": estado, "total_hallazgos": total, "fuentes": datos["fuentes"],
        "reglas": [hallazgo["regla"] for hallazgo in artefacto["hallazgos"]],
    })


@pytest.mark.motor_local
def test_motor_fake_sin_fixture_devuelve_abstencion(cliente, bearer, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("EMB_PROVIDER", "hash")
    variante, llm = cargar_motor()
    monkeypatch.setattr(llm.fake, "responder", None)
    codigo = (Path(variante.RAIZ) / "datos/v2-revisor/codigo/limites.py").read_text(encoding="utf-8")
    respuesta = cliente.post("/v1/v2-revisor", json={"codigo": codigo}, headers=bearer)
    assert respuesta.status_code == 200
    assert respuesta.json()["abstuvo"] and not respuesta.json()["artefacto"]


def test_contrato_del_endpoint_sin_checkout(cliente, bearer, monkeypatch):
    codigo = "x = 1\n"
    entradas = []

    def registrar(origen):
        entradas.append(origen)
        return {"respuesta": "resultado de prueba"}

    monkeypatch.setattr(motor, "revisar", registrar)
    respuesta = cliente.post("/v1/v2-revisor", json={"codigo": codigo}, headers=bearer)
    assert respuesta.status_code == 200 and respuesta.json() == {"respuesta": "resultado de prueba"}
    assert entradas == [codigo]
