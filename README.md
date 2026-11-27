# Actividad 4 · Revisor FinNorte

Luis Alfonso Juárez Amaro · LSCA2318 · Variante `v2-revisor`

[Etiqueta a4-lolmastercraft-r2](https://github.com/Lolmastercraft/Actividad-4/tree/a4-lolmastercraft-r2) ·
[Informe PDF](https://github.com/Lolmastercraft/Actividad-4/releases/download/a4-lolmastercraft-r2/Actividad_4_Informe.pdf)

La interfaz usa la autenticación heredada de la A3 para llamar a `POST /v1/v2-revisor`
y al agente de la A4. El agente propone un análisis estático de un archivo del catálogo.
La persona ve la operación y los argumentos antes de aceptar o rechazar.

## Puesta en marcha

Desde la raíz, con Python 3.12 y Git:

```text
python -m pip install -r requirements.txt
python -m guia.preparar_motor --descargar
python -c "import secrets; print(secrets.token_hex(32))"
```

Copia `.env.example` a `.env` y escribe el valor generado en `TOKEN_SECRET`. Con
`LLM_PROVIDER=fake` el agente propone el linter de forma determinista. El revisor
semántico de la A3 puede abstenerse en ese modo. Para la revisión real configura
`LLM_PROVIDER=gemini`, `EMB_PROVIDER=gemini` y `GEMINI_API_KEY` en ese archivo.

Terminal 1:

```text
python -m uvicorn api.producto:app --host 127.0.0.1 --port 8000 --env-file .env
```

Terminal 2:

```text
python -m streamlit run app/cliente_api.py --server.address 127.0.0.1 --server.port 8501
```

Abre [la interfaz local](http://127.0.0.1:8501). Crea una cuenta de prueba e inicia sesión.

- **Mi variante** acepta código Python y muestra el dictamen, las fuentes y el control de líneas y citas.
- **Agente** usa el catálogo de cinco archivos. Prueba `importacion.py` para observar
  F401, rechaza `variable.py` para verificar que el análisis se omite, o autoriza
  `ausente.py` para ver la falla controlada.

La API conserva los bytes aprobados durante un máximo de 10 minutos en el proceso
activo. Usa una sola instancia de Uvicorn para el prototipo. El linter opera por
entrada estándar, sin importar el programa ni guardar cambios al archivo, con hasta
30 000 bytes y 8 segundos. Su salida reporta códigos Ruff. El dictamen SEC corresponde
a la revisión semántica con el corpus del Avance 1.

## Verificación

```text
python -m pytest -q
python -m guia.evaluar_a4 evidencias/medicion
python -m guia.evaluar_a4 --gemini evidencias/gemini
```

La medición local inyecta dos respuestas controladas del proveedor y corre Ruff real.
La medición con `--gemini` requiere la clave en el entorno y se guarda en otro directorio.
Cada medición conserva los estados, tiempos, decisión de validación y diagnósticos
de las cinco entradas, además de los dos escenarios de seguridad. El workflow de
GitHub guarda la demo de 120 s y la evidencia de sus pasos.

La salida de la evaluación controlada quedó en [docs/resultados_a4.json](docs/resultados_a4.json).

En GitHub Actions, el secreto `GEMINI_API_KEY` habilita una evaluación separada y
una captura de `tokens.py` que exige un dictamen verificado y al menos una fuente
visible. La demo de prueba local muestra explícitamente la abstención.

Para publicar una revisión con el informe y la demo actualizados, ejecuta el
workflow sobre la rama de trabajo con el campo `etiqueta_revision`, por ejemplo
`a4-lolmastercraft-r2`. Los pushes normales siguen verificándose y la entrega
original conserva su etiqueta y sus archivos.
