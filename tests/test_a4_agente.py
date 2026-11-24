import json
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api.producto import crear_app
from src.finnorte import herramientas as h
from src.finnorte import validador as v


def propuesta(ruta="importacion.py"):
    return {"accion": "usar", "herramienta": "correr_linter", "argumentos": {"ruta": ruta}}


def _herramienta(funcion):
    return h.Herramienta("correr_linter", "Prueba", h.herramienta_linter("importacion.py").esquema,
                         funcion, sensible=True)


@pytest.mark.parametrize(("decision", "estado"), [(False, "rechazada"), (None, "pendiente")])
def test_decision_negativa_o_pendiente_no_llama_herramienta(decision, estado):
    def prohibida(**_):
        pytest.fail("El ejecutor invocó una operación sin autorización.")

    salida = h.ejecutar_agente("Analiza la muestra", [_herramienta(prohibida)],
                                confirmar=lambda *_: decision, proponer=lambda *_: propuesta())
    assert [p.estado for p in salida.pasos] == [estado]


@pytest.mark.parametrize("invalida", [
    propuesta("variable.py"),
    {**propuesta(), "confirmado": True},
    {**propuesta(), "argumentos": {"ruta": "importacion.py", "opcion": True}},
    {**propuesta(), "herramienta": []},
    {"accion": "usar", "herramienta": "inventada", "argumentos": {}},
])
def test_esquema_impide_inyectar_herramienta_o_argumentos(invalida):
    confirmaciones = []
    salida = h.ejecutar_agente("Analiza la muestra", [_herramienta(lambda **_: pytest.fail())],
                                confirmar=lambda *_: confirmaciones.append(True), max_pasos=2,
                                proponer=lambda *_: invalida)
    assert [p.estado for p in salida.pasos] == ["invalida", "invalida"]
    assert not salida.terminado and not confirmaciones


def test_repeticion_ejecuta_una_vez_y_respeta_el_tope():
    llamadas = []
    salida = h.ejecutar_agente("Analiza la muestra", [_herramienta(lambda **args: llamadas.append(args) or {})],
                                confirmar=lambda *_: True, max_pasos=99, proponer=lambda *_: propuesta())
    assert [p.estado for p in salida.pasos] == ["ejecutada", "repetida"]
    assert len(llamadas) == 1 and not salida.terminado


def test_rescata_formato_invalido_y_omision():
    for primera in (propuesta("variable.py"), {"accion": "responder"}):
        respuestas = iter([primera, propuesta()])
        salida = h.ejecutar_agente("Revisar", [_herramienta(lambda **_: pytest.fail())],
                                    confirmar=lambda *_: None, ruta="importacion.py",
                                    proponer=lambda *_: next(respuestas))
        assert salida.pasos[-1].estado == "pendiente"
        assert len(salida.pasos) == 2


@pytest.fixture
def autenticado(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TOKEN_SECRET", secrets.token_hex(32))
    rastro = tmp_path / "trazas.jsonl"
    with TestClient(crear_app(":memory:", maximo=60, trazas_a4=rastro)) as cliente:
        cuenta = {"email": "prueba-a4@example.com", "contrasena": "temporal-a4-2026"}
        assert cliente.post("/auth/registro", json=cuenta).status_code == 201
        cred = cliente.post("/auth/login", json=cuenta).json()
        yield cliente, {"Authorization": f"Bearer {cred['token']}"}, rastro


def test_api_confirma_solo_usuario_y_solo_una_vez(autenticado, monkeypatch):
    cliente, headers, rastro = autenticado
    llamadas = []

    def registrar(ruta, *, contenido=None):
        llamadas.append((ruta, contenido))
        return {"archivo": ruta, "analizador": "Ruff", "avisos": [{"codigo": "F401", "linea": 1}]}

    monkeypatch.setattr(h, "correr_linter", registrar)
    cuerpos = {"tarea": "Revisa el código", "ruta": "importacion.py"}
    assert cliente.post("/v1/agente", json=cuerpos).status_code == 401
    res = cliente.post("/v1/agente", json=cuerpos, headers=headers).json()
    pendiente = res["pendientes"][0]
    assert pendiente["argumentos"] == {"ruta": "importacion.py"}
    assert res["validador"]["ok"] and pendiente["sha256"] and not llamadas
    url = f"/v1/agente/confirmar/{pendiente['id']}"
    otra = {"email": "otra-a4@example.com", "contrasena": "temporal-a4-otra"}
    cliente.post("/auth/registro", json=otra).raise_for_status()
    token = cliente.post("/auth/login", json=otra).json()["token"]
    assert cliente.post(url, json={"aprobar": True}, headers={"Authorization": f"Bearer {token}"}).status_code == 404
    assert cliente.post(url, json={"aprobar": "true"}, headers=headers).status_code == 422
    with ThreadPoolExecutor(max_workers=2) as pool:
        estados = list(pool.map(lambda _: cliente.post(url, json={"aprobar": True}, headers=headers).status_code, range(2)))
    assert sorted(estados) == [200, 404]
    assert len(llamadas) == 1 and llamadas[0][0] == "importacion.py"
    assert llamadas[0][1] == h.leer_caso("importacion.py")
    contenido = rastro.read_text(encoding="utf-8")
    assert "example.com" not in contenido and "Revisa el código" not in contenido
    assert [json.loads(linea)["tipo"] for linea in contenido.splitlines()] == ["propuesta", "decision"]


def test_api_rechazo_y_falla_controlada(autenticado, monkeypatch):
    cliente, headers, _ = autenticado

    def prohibida(*_, **__):
        pytest.fail("La herramienta no se debe invocar en estos dos escenarios.")

    monkeypatch.setattr(h, "correr_linter", prohibida)
    for ruta, aprobar, estado in (("importacion.py", False, "rechazada"), ("ausente.py", True, "error_herramienta")):
        plan = cliente.post("/v1/agente", json={"tarea": "Analiza", "ruta": ruta}, headers=headers)
        assert plan.status_code == 200
        pendiente = plan.json()["pendientes"][0]
        res = cliente.post(f"/v1/agente/confirmar/{pendiente['id']}", json={"aprobar": aprobar}, headers=headers)
        assert res.status_code == 200 and res.json()["estado"] == estado and res.json()["resultado"] is None
    invalidada = cliente.post("/v1/agente", json={"tarea": "Analiza", "ruta": "../fuera.py"}, headers=headers)
    assert invalidada.status_code == 422 and invalidada.headers["Content-Type"].startswith("application/problem+json")


def test_snapshot_no_depende_de_cambios_al_archivo(autenticado, monkeypatch):
    cliente, headers, _ = autenticado
    version = b"x = 1\n"
    monkeypatch.setattr(h, "leer_caso", lambda _: version)
    plan = cliente.post("/v1/agente", json={"tarea": "Analiza", "ruta": "importacion.py"}, headers=headers).json()
    version = b"x = 2\n"

    def analizar(ruta, *, contenido):
        assert contenido == b"x = 1\n"
        return {"archivo": ruta, "analizador": "Ruff", "avisos": []}

    monkeypatch.setattr(h, "correr_linter", analizar)
    res = cliente.post(f"/v1/agente/confirmar/{plan['pendientes'][0]['id']}",
                       json={"aprobar": True}, headers=headers).json()
    assert res["estado"] == "ejecutada"


def _dictamen(regla="SEC-09", linea=1, fuente="sec-09#0"):
    dato = {"id": "H1", "regla": regla, "linea": linea, "fuente": fuente}
    return {"abstuvo": False, "fuentes": [fuente], "recuperados": [fuente],
            "artefacto": {"hallazgos": [dato], "dictamen": {
                "estado": "con_hallazgos", "total_hallazgos": 1, "hallazgos": [dato]}}}


def test_validador_regla_fuente_linea_y_control_limpio():
    corpus = {"sec-09#0", "sec-06#0"}
    assert v.validar_revision(_dictamen(), "x = 1", "tokens.py", corpus)["ok"]
    for salida in (_dictamen(linea=2), _dictamen(fuente="sec-06#0"), _dictamen(fuente="sec-09#999")):
        assert not v.validar_revision(salida, "x = 1", "tokens.py", corpus)["ok"]
    assert not v.validar_revision(_dictamen(), "x = 1", "limites.py", corpus)["ok"]
    limpio = {"fuentes": [], "recuperados": [], "artefacto": {"hallazgos": [], "dictamen": {
        "estado": "sin_hallazgos", "total_hallazgos": 0, "hallazgos": []}}}
    assert v.validar_revision(limpio, "x = 1", "limites.py", corpus)["ok"]
    assert v.validar_revision({"abstuvo": True}, "x = 1", "limites.py", corpus)["estado"] == "abstencion"


@pytest.mark.ruff_local
def test_ruff_real_lee_sin_ejecutar_codigo(tmp_path):
    marca = tmp_path / "no-debe-existir"
    codigo = f"open({str(marca)!r}, 'w').close()\n".encode("utf-8")
    assert h.correr_linter("importacion.py", contenido=codigo)["avisos"] == []
    assert not marca.exists()
    assert h.correr_linter("importacion.py")["avisos"] == [{"codigo": "F401", "linea": 1}]
