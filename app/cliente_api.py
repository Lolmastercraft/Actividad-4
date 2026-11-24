"""Interfaz de revisión que consume la API con el token de la sesión."""
from __future__ import annotations

import os
from collections.abc import Callable

import httpx
import streamlit as st

API_URL = os.getenv("A4_API_URL", "http://127.0.0.1:8000").rstrip("/")


st.set_page_config(page_title="Revisor FinNorte", layout="wide", page_icon="🔎")
st.markdown("""
<style>
.block-container {max-width: 1080px; padding: 2.8rem 3rem;}
[data-testid="stSidebar"] {border-right: 1px solid #dbe5e4;}
.a4-title {border-top: 4px solid #168478; padding: 1rem 0 .6rem;}
.a4-title p {font-size: 1rem; color: #526a71; margin: .2rem 0 1rem;}
.a4-title h1 {padding: 0; font-size: clamp(2rem, 4vw, 3rem); letter-spacing: -.04em;}
</style>
""", unsafe_allow_html=True)


class ErrorAPI(RuntimeError):
    def __init__(self, detalle, estado=None):
        super().__init__(detalle)
        self.estado = estado


def llamar(metodo: str, ruta: str, cuerpo: dict | None = None, *, protegido: bool = True) -> dict:
    token = st.session_state.get("token")
    headers = {"Authorization": f"Bearer {token}"} if protegido and token else {}
    try:
        with httpx.Client(timeout=httpx.Timeout(180, connect=4), trust_env=False) as cliente:
            respuesta = cliente.request(metodo, API_URL + ruta, json=cuerpo, headers=headers)
    except httpx.HTTPError:
        raise ErrorAPI("No pude conectar con el servicio. Verifica que la API esté disponible.") from None
    try:
        datos = respuesta.json()
    except ValueError:
        raise ErrorAPI("El servicio devolvió una respuesta ilegible.", respuesta.status_code) from None
    if not respuesta.is_success:
        raise ErrorAPI(datos.get("detail", "No pude completar la solicitud."), respuesta.status_code)
    return datos


def cargar(accion: Callable[[], dict], mensaje: str) -> dict | None:
    try:
        with st.spinner(mensaje):
            return accion()
    except ErrorAPI as exc:
        st.error(str(exc))
        if exc.estado == 401:
            st.session_state.pop("token", None)
            st.warning("Inicia sesión de nuevo para continuar.")
        return None


def mostrar_validacion(datos: dict) -> None:
    resultado = datos.get("validador") or {}
    if resultado.get("ok"):
        st.success("Validador local · verificado")
    else:
        st.warning("Validador local · " + resultado.get("estado", "sin dictamen"))
    for error in resultado.get("hallazgos", []):
        st.text(error)


def mostrar_fuentes(datos: dict) -> None:
    fuentes = datos.get("fuentes", [])
    st.caption("Fuentes consultadas")
    if fuentes:
        st.text(" · ".join(fuentes))
    else:
        st.caption("Esta respuesta no cita fragmentos del corpus.")


with st.sidebar:
    st.header("Sesión")
    if not st.session_state.get("token"):
        with st.form("acceso", clear_on_submit=True):
            correo = st.text_input("Correo")
            clave = st.text_input("Contraseña", type="password")
            ingreso, registro = st.columns(2)
            entrar = ingreso.form_submit_button("Entrar", type="primary")
            registrar = registro.form_submit_button("Crear cuenta")
        if entrar or registrar:
            ruta_auth = "/auth/login" if entrar else "/auth/registro"
            respuesta = cargar(lambda: llamar("POST", ruta_auth, {"email": correo, "contrasena": clave},
                                               protegido=False), "Verificando credenciales")
            if respuesta and entrar:
                st.session_state["token"] = respuesta["token"]
                st.rerun()
            elif respuesta:
                st.success("Cuenta creada. Ya puedes entrar.")
    elif st.button("Cerrar sesión"):
        st.session_state.clear()
        st.rerun()

st.markdown('<div class="a4-title"><h1>Revisor FinNorte</h1>'
            '<p>Revisa código Python y verifica los resultados antes de actuar.</p></div>',
            unsafe_allow_html=True)
if not st.session_state.get("token"):
    st.info("Inicia sesión para revisar un archivo o solicitar un análisis estático.")
    st.stop()

if "casos" not in st.session_state:
    catalogo = cargar(lambda: llamar("GET", "/v1/agente/casos"), "Cargando el catálogo")
    if not catalogo:
        st.stop()
    st.session_state["casos"] = catalogo
catalogo = st.session_state["casos"]
modo = st.radio("Modo", ["Mi variante", "Agente"], horizontal=True)
entrada, panel = st.columns([1, 1.2], gap="large")

if modo == "Mi variante":
    with entrada:
        st.subheader("Código Python")
        archivo = st.selectbox("Entrada", ["Código propio", *catalogo["archivos"]])
        if archivo == "Código propio":
            codigo = st.text_area("Pega el código", height=216, max_chars=30_000)
        else:
            if st.session_state.get("muestra", {}).get("archivo") != archivo:
                muestra = cargar(lambda: llamar("GET", f"/v1/agente/casos/{archivo}"), "Cargando el archivo")
                if muestra:
                    st.session_state["muestra"] = muestra
            muestra = st.session_state.get("muestra", {})
            codigo = muestra.get("codigo", "") if muestra.get("archivo") == archivo else ""
            st.code(codigo, language="python", line_numbers=True, height=216)
        if st.button("Revisar código", type="primary"):
            if codigo.strip():
                ruta_revision = "/v1/v2-revisor" if archivo == "Código propio" else f"/v1/v2-revisor?archivo={archivo}"
                revision = cargar(
                    lambda: llamar("POST", ruta_revision, {"codigo": codigo}), "Revisando código y verificando citas")
                st.session_state["revision"] = (archivo, revision) if revision else None
            else:
                st.warning("Escribe el código o selecciona un archivo del catálogo.")
    with panel:
        st.subheader("Dictamen")
        guardada = st.session_state.get("revision")
        if guardada:
            etiqueta, revision = guardada
            st.caption(etiqueta)
            mostrar_validacion(revision)
            hallazgos = (revision.get("artefacto") or {}).get("hallazgos", [])
            if revision.get("validador", {}).get("ok"):
                if hallazgos:
                    st.dataframe([{"Regla": h["regla"], "Línea": h["linea"], "Fuente": h["fuente"]}
                                  for h in hallazgos], hide_index=True)
                else:
                    st.write("Sin hallazgos.")
            mostrar_fuentes(revision)
            if revision.get("demo"):
                st.caption("Ejecución de prueba con configuración local.")
        else:
            st.caption("El dictamen aparecerá aquí después de la revisión.")
else:
    with entrada:
        st.subheader("Análisis estático")
        archivo = st.selectbox("Archivo autorizado", [*catalogo["archivos"], catalogo["prueba_de_falla"]])
        tarea = st.text_area("Instrucción para el agente", "Analiza el archivo seleccionado con Ruff.", max_chars=360)
        if st.button("Solicitar análisis", type="primary", disabled=not tarea.strip()):
            st.session_state["decision"] = None
            st.session_state["propuesta"] = cargar(lambda: llamar("POST", "/v1/agente", {"ruta": archivo, "tarea": tarea}),
                                                    "Preparando la solicitud del agente")
    with panel:
        st.subheader("Resultado del agente")
        propuesta = st.session_state.get("propuesta")
        decision = st.session_state.get("decision")
        if propuesta:
            pendientes = propuesta.get("pendientes", [])
            if pendientes and decision is None:
                pendiente = pendientes[0]
                st.warning("Acción pendiente de autorización")
                st.json({"herramienta": pendiente["herramienta"], "argumentos": pendiente["argumentos"],
                         "sha256": pendiente["sha256"]}, expanded=True)
                aprobar, rechazar = st.columns(2)
                aceptar = aprobar.button("Autorizar análisis", type="primary", key="aprobar")
                negar = rechazar.button("Rechazar análisis", key="rechazar")
                if aceptar or negar:
                    ruta = f"/v1/agente/confirmar/{pendiente['id']}"
                    estado = cargar(lambda: llamar("POST", ruta, {"aprobar": aceptar}), "Procesando la decisión")
                    if estado:
                        st.session_state["decision"] = estado
                        st.rerun()
            if decision:
                estado = decision["estado"]
                st.markdown(f"**Estado** · {estado.replace('_', ' ')}")
                if decision.get("resultado"):
                    avisos = decision["resultado"]["avisos"]
                    if avisos:
                        st.table([{"Código": a["codigo"], "Línea": a["linea"]} for a in avisos])
                    else:
                        st.write("Ruff completó el análisis sin avisos.")
                mostrar_validacion(decision)
                mostrar_fuentes(decision)
            else:
                mostrar_validacion(propuesta)
                mostrar_fuentes(propuesta)
            with st.expander("Bitácora de esta solicitud"):
                st.json(propuesta["pasos"])
                if decision:
                    st.json({"estado": decision["estado"], "archivo": decision["argumentos"]["ruta"]})
        else:
            st.caption("Aquí podrás autorizar la propuesta y consultar su resultado.")
