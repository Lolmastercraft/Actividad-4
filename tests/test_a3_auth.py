import sqlite3

import pytest

from api import motor
from api.auth import (Autenticador, ITERACIONES, MENSAJE_CREDENCIALES, VIGENCIA_S, emitir_token,
                      identificador_intento, verificar_contrasena)


RUTA = "/v1/v2-revisor"
CODIGO = {"codigo": "x = 1\n"}


def problema(respuesta, estado):
    assert respuesta.status_code == estado
    assert respuesta.headers["content-type"].split(";")[0] == "application/problem+json"
    salida = respuesta.json()
    assert {"type", "title", "status", "detail", "trace_id"} <= salida.keys()
    assert salida["status"] == estado and salida["trace_id"]
    return salida


def test_oficial_login_exitoso(cliente, cuenta, evidencia):
    respuesta = cliente.post("/auth/login", json=cuenta)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["tipo"] == "Bearer" and 0 < cuerpo["expira_en_s"] <= 900
    assert cuerpo["token"]
    evidencia("login-exitoso", {"status": respuesta.status_code, "tipo": cuerpo["tipo"], "expira_en_s": cuerpo["expira_en_s"]})


def test_oficial_contrasena_incorrecta(cliente, cuenta, evidencia):
    error = problema(cliente.post("/auth/login", json={**cuenta, "contrasena": "incorrecta"}), 401)
    assert error["detail"] == MENSAJE_CREDENCIALES
    evidencia("401-contrasena", error)


def test_oficial_usuario_inexistente(cliente, cuenta, evidencia):
    error = problema(cliente.post("/auth/login", json={**cuenta, "email": "otro@example.com"}), 401)
    assert error["detail"] == MENSAJE_CREDENCIALES
    evidencia("401-inexistente", error)


def test_token_expirado(cliente, cuenta, evidencia):
    import time
    vencido = emitir_token(cuenta["email"], ahora=time.time() - VIGENCIA_S)
    error = problema(cliente.post(RUTA, json=CODIGO, headers={"Authorization": f"Bearer {vencido}"}), 401)
    assert error["detail"] == "Token expirado"
    evidencia("401-expirado", error)


def test_token_alterado(cliente, bearer, evidencia):
    original = bearer["Authorization"]
    payload, firma = original.rsplit(".", 1)
    reemplazo = "A" if firma[0] != "A" else "B"
    error = problema(cliente.post(RUTA, json=CODIGO, headers={"Authorization": f"{payload}.{reemplazo}{firma[1:]}"}), 401)
    assert error["detail"] == "Token inválido"
    evidencia("401-alterado", error)


def test_bloqueo_al_sexto_intento(cliente, cuenta, evidencia):
    for _ in range(5):
        problema(cliente.post("/auth/login", json={**cuenta, "contrasena": "incorrecta"}), 401)
    error = problema(cliente.post("/auth/login", json=cuenta), 429)
    evidencia("429-bloqueo", error)


@pytest.mark.parametrize("entrada,detalle", [
    ({"codigo": "def ("}, "codigo: sintaxis Python inválida en la línea 1."),
    ({"codigo": "\n "}, "codigo: el código está vacío."),
    ({"codigo": 1}, "codigo: debe ser texto."),
    ({"codigo": "x = 1", "archivo": "local.py"}, "cuerpo: contiene campos adicionales no permitidos."),
], ids=["sintaxis", "vacio", "tipo", "campo-extra"])
def test_codigo_invalido_y_campos_extra(cliente, bearer, evidencia, entrada, detalle):
    error = problema(cliente.post(RUTA, json=entrada, headers=bearer), 422)
    assert error["detail"] == detalle
    if entrada == {"codigo": "def ("}:
        evidencia("422-entrada", error)


def test_endpoint_sin_token(cliente, evidencia):
    error = problema(cliente.post(RUTA, json=CODIGO), 401)
    evidencia("401-sin-token", error)


def test_limite_por_usuario(cliente, bearer, monkeypatch, evidencia):
    monkeypatch.setattr(motor, "revisar", lambda _codigo: {"respuesta": "prueba de cuota"})
    for _ in range(3):
        assert cliente.post(RUTA, json=CODIGO, headers=bearer).status_code == 200
    error = problema(cliente.post(RUTA, json=CODIGO, headers=bearer), 429)
    assert "solicitudes" in error["detail"]
    evidencia("429-limite", error)


def test_motor_indisponible_devuelve_error_publico(cliente, bearer, monkeypatch):
    def indisponible(_codigo):
        raise motor.MotorNoDisponible("detalle interno de prueba")

    monkeypatch.setattr(motor, "revisar", indisponible)
    error = problema(cliente.post(RUTA, json=CODIGO, headers=bearer), 503)
    assert error["detail"] == "El motor de revisión no está disponible."


def test_sqlite_guarda_hash_con_sal_y_bitacora_minima(cliente, cuenta):
    otra = {**cuenta, "email": "distinto@example.com"}
    assert cliente.post("/auth/registro", json=otra).status_code == 201
    assert cliente.post("/auth/login", json=cuenta).status_code == 200
    db = cliente.app.state.auth.db
    hashes = [fila[0] for fila in db.execute("SELECT hash FROM usuarios").fetchall()]
    assert all(x.startswith(f"pbkdf2${ITERACIONES}$") for x in hashes)
    assert len({x.split("$")[2] for x in hashes}) == 2
    assert all(verificar_contrasena(cuenta["contrasena"], x) for x in hashes)
    assert {fila[1] for fila in db.execute("PRAGMA table_info(intentos)")} == {"usuario_id", "ts", "ok"}
    eventos = db.execute("SELECT usuario_id, ok FROM intentos").fetchall()
    assert eventos == [(identificador_intento(cuenta["email"]), 1)]
    assert cuenta["email"] not in eventos[0][0] and len(eventos[0][0]) == 64


def test_migracion_conserva_fallos_y_sustituye_correos(tmp_path, monkeypatch):
    import secrets
    monkeypatch.setenv("TOKEN_SECRET", secrets.token_hex(32))
    ruta = tmp_path / "anterior.db"
    usuario = "migracion@example.com"
    conexion = sqlite3.connect(ruta)
    with conexion:
        conexion.execute("CREATE TABLE intentos (email TEXT, ts REAL, ok INTEGER)")
        conexion.execute("CREATE INDEX intentos_email_ts ON intentos (email, ts)")
        conexion.executemany("INSERT INTO intentos VALUES (?, ?, 0)", ((usuario, float(t)) for t in range(11, 16)))
    conexion.close()
    auth = Autenticador(str(ruta))
    try:
        eventos = auth.db.execute("SELECT usuario_id, ts, ok FROM intentos ORDER BY rowid").fetchall()
        assert eventos == [(identificador_intento(usuario), float(t), 0) for t in range(11, 16)]
        assert not auth.db.execute("SELECT * FROM sqlite_master WHERE name='intentos_anteriores'").fetchall()
        from api.auth import ErrorAuth
        with pytest.raises(ErrorAuth) as fallo:
            auth.login(usuario.upper(), "ficticia", ahora=16)
        assert fallo.value.status == 429
    finally:
        auth.db.close()
