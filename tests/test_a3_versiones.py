import inspect

from a3 import login_eficiencia, login_mantenible, login_original, login_seguridad
from api.auth import hash_contrasena, validar_token


def test_original_distingue_usuario_inexistente_y_clave():
    assert login_original.login("admin", "clave-ficticia") != login_original.login("otro", "clave-ficticia")


def test_version_seguridad_emite_token_y_deniega(monkeypatch):
    import secrets
    monkeypatch.setenv("TOKEN_SECRET", secrets.token_hex(32))
    cuentas = {"demo@example.com": hash_contrasena("ejemplo-de-prueba")}
    servicio = login_seguridad.LoginSeguro(cuentas, hash_contrasena("alternativa-ficticia"))
    with login_seguridad.configurar(servicio):
        salida = login_seguridad.login("demo@example.com", "ejemplo-de-prueba")
        assert salida.aprobado and validar_token(salida.token) == "demo@example.com"
        for _ in range(5):
            assert not login_seguridad.login("demo@example.com", "incorrecta").aprobado
        assert "Bloqueo" in login_seguridad.login("demo@example.com", "ejemplo-de-prueba").mensaje
    assert all("@" not in clave for clave in servicio.fallos)


def test_eficiencia_hace_una_consulta_para_cada_cuenta():
    class Medicion(dict):
        accesos = 0

        def get(self, clave):
            self.accesos += 1
            return super().get(clave)

    cuentas = Medicion({"demo@example.com": hash_contrasena("ejemplo-de-prueba")})
    auxiliar = hash_contrasena("frase-auxiliar-de-prueba")
    with login_eficiencia.configurar(cuentas, auxiliar):
        assert login_eficiencia.login(" Demo@example.com ", "ejemplo-de-prueba").aprobado
        assert cuentas.accesos == 1
        assert not login_eficiencia.login("otro@example.com", "frase-auxiliar-de-prueba").aprobado
    assert cuentas.accesos == 2


def test_mantenible_admite_repositorio_y_verificador_inyectados():
    class Repositorio:
        def buscar_hash(self, clave):
            return "hash-de-prueba" if clave == "demo@example.com" else None

    recibidos = []

    def verificar(_clave, huella):
        recibidos.append(huella)
        return True

    servicio = login_mantenible.ServicioLogin(Repositorio(), "hash-auxiliar", verificar)
    with login_mantenible.configurar(servicio):
        assert login_mantenible.login("demo@example.com", "ficticia").aprobado
        assert not login_mantenible.login("otro@example.com", "ficticia").aprobado
    assert recibidos == ["hash-de-prueba", "hash-auxiliar"]


def test_las_cuatro_versiones_conservan_la_firma_publica():
    for version in (login_original, login_seguridad, login_eficiencia, login_mantenible):
        assert list(inspect.signature(version.login).parameters) == ["user", "password"]
