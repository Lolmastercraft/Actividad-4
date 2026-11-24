"""Consulta una vista precargada de hashes con un solo acceso por intento."""
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from a3.resultado import ACEPTADO, DENEGADO, ResultadoLogin
from api.auth import verificar_contrasena


_configuracion: ContextVar[tuple[Mapping[str, str], str]] = ContextVar("login_eficiente")


@contextmanager
def configurar(usuarios: Mapping[str, str], hash_auxiliar: str):
    """Recibe una vista ya cargada y una huella auxiliar calculada fuera del login."""
    anterior = _configuracion.set((usuarios, hash_auxiliar))
    try:
        yield
    finally:
        _configuracion.reset(anterior)


def login(user: str, password: str) -> ResultadoLogin:
    usuarios, hash_auxiliar = _configuracion.get()
    guardado = usuarios.get(user.strip().lower())
    coincide = verificar_contrasena(password, guardado if guardado is not None else hash_auxiliar)
    return ACEPTADO if guardado is not None and coincide else DENEGADO
