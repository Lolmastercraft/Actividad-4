"""Recorre la interfaz real, captura sus pantallas y produce una demo de 120 s."""
from __future__ import annotations

import argparse
import os
import re
import secrets
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright

API = "http://127.0.0.1:8000"
INTERFAZ = "http://127.0.0.1:8501"
FUENTES = Path("/usr/share/fonts/truetype/dejavu")


def esperar(url):
    for _ in range(80):
        try:
            if httpx.get(url, timeout=1, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.25)
    raise RuntimeError(f"No respondió el servicio local {url}")


def capturas(pagina, directo: Path, cuenta: dict, gemini: bool):
    fichas = []

    def tomar(titulo, texto, segundos):
        imagen = directo / f"pantalla-{len(fichas) + 1:02}.png"
        pagina.screenshot(path=imagen, animations="disabled")
        fichas.append((imagen, titulo, texto, segundos))

    pagina.goto(INTERFAZ)
    expect(pagina.get_by_text("Inicia sesión para revisar un archivo", exact=False)).to_be_visible()
    tomar("01 · Acceso", "Revisor FinNorte. La persona inicia sesión para obtener el token que la interfaz usa al llamar la API.", 12)
    pagina.get_by_label("Correo", exact=True).fill(cuenta["email"])
    pagina.get_by_label("Contraseña", exact=True).fill(cuenta["contrasena"])
    pagina.get_by_role("button", name="Entrar", exact=True).click()
    expect(pagina.get_by_text("Dictamen", exact=True)).to_be_visible()

    def seleccionar(archivo):
        pagina.get_by_role("combobox").click()
        pagina.get_by_role("option", name=archivo, exact=True).click()

    seleccionar("tokens.py" if gemini else "limites.py")
    expect(pagina.locator("[data-testid='stCode']")).to_be_visible()
    pagina.get_by_role("button", name="Revisar código").click()
    expect(pagina.get_by_text("Validador local", exact=False).first).to_be_visible(timeout=180_000)
    if gemini:
        expect(pagina.get_by_text("Validador local · verificado", exact=True)).to_be_visible()
        expect(pagina.get_by_text(re.compile(r"sec-(?:0[1-9]|10)#[0-9]+")).first).to_be_visible()
        texto = "Gemini revisó tokens.py. El validador local comprobó las líneas y las citas que muestra el panel."
    else:
        texto = "El proveedor simulado se abstuvo. La interfaz muestra el estado de revisión humana."
    tomar("02 · Revisión autenticada", texto, 16)
    pagina.get_by_text("Agente", exact=True).click()
    expect(pagina.get_by_text("Análisis estático", exact=True)).to_be_visible()

    def elegir(archivo):
        seleccionar(archivo)
        pagina.get_by_role("button", name="Solicitar análisis", exact=True).click()
        expect(pagina.get_by_text("Acción pendiente de autorización", exact=True)).to_be_visible(timeout=180_000)

    def abrir_bitacora():
        detalle = pagina.locator("details").filter(has_text="Bitácora de esta solicitud")
        if detalle.get_attribute("open") is None:
            pagina.get_by_text("Bitácora de esta solicitud", exact=True).click()

    elegir("importacion.py")
    tomar("03 · Confirmación", "La propuesta muestra la operación, la ruta exacta y la huella de los bytes. Ruff todavía no se ejecuta.", 18)
    pagina.get_by_role("button", name="Autorizar análisis", exact=True).click()
    expect(pagina.get_by_text("F401", exact=True)).to_be_visible(timeout=25_000)
    tomar("04 · Resultado validado", "Después de la aprobación, Ruff analiza los bytes autorizados. El resultado indica F401 en la línea 1.", 16)
    elegir("variable.py")
    pagina.get_by_role("button", name="Rechazar análisis", exact=True).click()
    expect(pagina.get_by_text("rechazada", exact=False).first).to_be_visible()
    abrir_bitacora()
    expect(pagina.get_by_text("rechazada", exact=False).first).to_be_visible()
    tomar("05 · Confirmación rechazada", "La decisión queda como rechazada. El agente no ejecuta Ruff ni muestra un resultado de análisis.", 20)
    elegir("ausente.py")
    pagina.get_by_role("button", name="Autorizar análisis", exact=True).click()
    expect(pagina.get_by_text("El archivo seleccionado no estaba disponible", exact=False)).to_be_visible()
    tomar("06 · Falla controlada", "Una entrada de prueba representa un archivo ausente. La interfaz muestra el error y la validación rechazada.", 22)
    abrir_bitacora()
    expect(pagina.get_by_text("error_herramienta", exact=False).first).to_be_visible()
    tomar("07 · Bitácora", "La traza conserva la propuesta y la decisión. El estado y el resultado del validador se distinguen en la interfaz.", 16)
    return fichas


def video(directorio: Path, fichas):
    titulo = ImageFont.truetype(str(FUENTES / "DejaVuSans-Bold.ttf"), 30)
    contenido = ImageFont.truetype(str(FUENTES / "DejaVuSans.ttf"), 23)
    lista = []
    for indice, (ruta, nombre, texto, segundos) in enumerate(fichas):
        lienzo = Image.new("RGB", (1440, 1024), "#173037")
        captura = Image.open(ruta).convert("RGB")
        captura.thumbnail((1400, 882))
        lienzo.paste(captura, ((1440 - captura.width) // 2, 14))
        draw = ImageDraw.Draw(lienzo)
        draw.text((35, 902), nombre, fill="#def8ec", font=titulo)
        draw.multiline_text((35, 946), "\n".join(textwrap.wrap(texto, width=104)),
                            fill="white", font=contenido, spacing=5)
        cuadro = directorio / f"cuadro-{indice:02}.png"
        lienzo.save(cuadro)
        lista.extend([f"file '{cuadro.name}'", f"duration {segundos}"])
    lista.append(f"file '{cuadro.name}'")
    (directorio / "lista.txt").write_text("\n".join(lista) + "\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "1",
                    "-i", "lista.txt", "-t", "120", "-vf", "fps=24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "Actividad_4_Demo.mp4"], check=True, cwd=directorio)


def grabar(directorio: Path, gemini: bool):
    if gemini and not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("Configura GEMINI_API_KEY para grabar con Gemini.")
    directorio = directorio.resolve()
    directorio.mkdir(parents=True, exist_ok=True)
    entorno = {**os.environ, "TOKEN_SECRET": secrets.token_hex(32),
               "AUTH_DB": str(directorio / "demo.db"), "A4_TRAZAS": str(directorio / "trazas_demo.jsonl"),
               "API_LIMITE": "90", "LLM_PROVIDER": "gemini" if gemini else "fake",
               "EMB_PROVIDER": "gemini" if gemini else "hash"}
    cuenta = {"email": "demo-a4@example.com", "contrasena": secrets.token_urlsafe(20)}
    comandos = [
        [sys.executable, "-m", "uvicorn", "api.producto:app", "--host", "127.0.0.1", "--port", "8000"],
        [sys.executable, "-m", "streamlit", "run", "app/cliente_api.py", "--server.headless", "true",
         "--server.address", "127.0.0.1", "--server.port", "8501", "--theme.base", "light",
         "--browser.gatherUsageStats", "false"],
    ]
    with (directorio / "servicios.log").open("wb") as log:
        procesos = [subprocess.Popen(cmd, env=entorno, stdout=log, stderr=subprocess.STDOUT) for cmd in comandos]
        try:
            esperar(API + "/salud")
            esperar(INTERFAZ + "/_stcore/health")
            httpx.post(API + "/auth/registro", json=cuenta, trust_env=False).raise_for_status()
            with sync_playwright() as playwright:
                navegador = playwright.chromium.launch()
                try:
                    pagina = navegador.new_page(viewport={"width": 1440, "height": 900})
                    fichas = capturas(pagina, directorio, cuenta, gemini)
                finally:
                    navegador.close()
            video(directorio, fichas)
        finally:
            for proceso in procesos:
                proceso.terminate()
            for proceso in procesos:
                proceso.wait(timeout=20)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directorio", type=Path)
    parser.add_argument("--gemini", action="store_true")
    args = parser.parse_args()
    grabar(args.directorio, args.gemini)
