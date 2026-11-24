"""Implementación comparativa enfocada en la política de seguridad."""
import time
from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock

from a3.resultado import ACEPTADO, DENEGADO, ResultadoLogin
from api.auth import MAX_FALLOS, VENTANA_FALLOS_S, emitir_token, identificador_intento, verificar_contrasena


class LoginSeguro:
    def __init__(self, usuarios: Mapping[str, str], huella_auxiliar: str):
        self.usuarios = usuarios
        self.huella_auxiliar = huella_auxiliar
        self.fallos: dict[str, deque[float]] = {}
        self.candado = Lock()

    def autenticar(self, cuenta: str, clave: str) -> ResultadoLogin:
        cuenta = cuenta.strip().lower()
        usuario_id = identificador_intento(cuenta)
        ahora = time.monotonic()
        with self.candado:
            historial = self.fallos.get(usuario_id, deque(maxlen=MAX_FALLOS))
            while historial and historial[0] <= ahora - VENTANA_FALLOS_S:
                historial.popleft()
            if len(historial) == MAX_FALLOS:
                return ResultadoLogin(False, "Bloqueo temporal por intentos fallidos")
            guardado = self.usuarios.get(cuenta)
            coincide = verificar_contrasena(clave, guardado if guardado is not None else self.huella_auxiliar)
            if guardado is None or not coincide:
                historial.append(ahora)
                self.fallos[usuario_id] = historial
                return DENEGADO
            self.fallos.pop(usuario_id, None)
        return ResultadoLogin(True, ACEPTADO.mensaje, emitir_token(cuenta))


_servicio: ContextVar[LoginSeguro] = ContextVar("login_seguro")


@contextmanager
def configurar(servicio: LoginSeguro):
    anterior = _servicio.set(servicio)
    try:
        yield
    finally:
        _servicio.reset(anterior)


def login(user: str, password: str) -> ResultadoLogin:
    return _servicio.get().autenticar(user, password)
