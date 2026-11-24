from dataclasses import dataclass

from api.auth import MENSAJE_CREDENCIALES


@dataclass(frozen=True)
class ResultadoLogin:
    aprobado: bool
    mensaje: str
    token: str | None = None


ACEPTADO = ResultadoLogin(True, "Acceso concedido")
DENEGADO = ResultadoLogin(False, MENSAJE_CREDENCIALES)
