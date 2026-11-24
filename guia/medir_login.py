"""Mide el camino exitoso de cada login con cuenta ficticia y configuración precargada."""
import argparse
import json
import os
import platform
import secrets
import statistics
import timeit
from contextlib import ExitStack
from pathlib import Path

from a3 import login_eficiencia, login_mantenible, login_original, login_seguridad
from api.auth import ITERACIONES, hash_contrasena, verificar_contrasena


def medir(operaciones):
    rondas = 10
    claves = list(operaciones)
    muestras = {nombre: [] for nombre in claves}
    for ronda in range(rondas):
        rotacion = ronda % len(claves)
        for nombre in claves[rotacion:] + claves[:rotacion]:
            llamada, cantidad = operaciones[nombre]
            elapsed = timeit.Timer(llamada).timeit(number=cantidad)
            muestras[nombre].append(elapsed * 1000 / cantidad)
    return {nombre: {"mediana_ms": statistics.median(valores), "min_ms": min(valores),
                     "max_ms": max(valores), "muestras": rondas, "intentos_por_muestra": operaciones[nombre][1]}
            for nombre, valores in muestras.items()}


def main(destino):
    correo, clave = "medicion@example.com", "clave-ficticia-para-medicion"
    os.environ.setdefault("TOKEN_SECRET", secrets.token_hex(32))
    huella = hash_contrasena(clave)
    auxiliar = hash_contrasena("huella-auxiliar-ficticia")
    usuarios = {correo: huella}

    class Repositorio:
        def buscar_hash(self, cuenta):
            return usuarios.get(cuenta)

    with ExitStack() as preparados:
        preparados.enter_context(login_seguridad.configurar(login_seguridad.LoginSeguro(usuarios, auxiliar)))
        preparados.enter_context(login_eficiencia.configurar(usuarios, auxiliar))
        preparados.enter_context(login_mantenible.configurar(login_mantenible.ServicioLogin(Repositorio(), auxiliar)))
        versiones = {nombre: modulo.login for nombre, modulo in (
            ("seguridad", login_seguridad), ("eficiencia", login_eficiencia), ("mantenible", login_mantenible),
        )}
        for login in versiones.values():
            assert login(correo, clave).aprobado
        assert login_original.login("admin", "1234") == "access granted"
        operaciones = {nombre: (lambda funcion=login: funcion(correo, clave), 5)
                       for nombre, login in versiones.items()}
        operaciones["original"] = (lambda: login_original.login("admin", "1234"), 100_000)
        operaciones["PBKDF2"] = (lambda: verificar_contrasena(clave, huella), 5)
        lecturas = medir(operaciones)

    datos = {"python": platform.python_version(), "sistema": platform.system(), "iteraciones_pbkdf2": ITERACIONES,
             "caso": "Login exitoso con configuración y hashes precargados", "resultados": lecturas}
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(datos, ensure_ascii=False, indent=2)
    destino.write_text(texto + "\n", encoding="utf-8")
    print(texto)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("salida", type=Path)
    main(parser.parse_args().salida)
