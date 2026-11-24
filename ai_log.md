# Bitácora de IA · Actividad 3

**24 de noviembre de 2026 · ChatGPT.** Diseño, análisis y pruebas de una API autenticada para `v2-revisor`.

## Solicitud de diseño y borrador evaluado

> Diseña el servicio de la Actividad 3 aprovechando `api/auth.py` del Laboratorio 3. Propón rutas, modelo de entrada, estados HTTP, control de sesión y límites para conectar `v2-revisor` al motor original. Analiza el `login()` de la consigna. Plantea tres mejoras verificables con énfasis en seguridad, eficiencia y mantenibilidad, y pruebas con casos positivos y negativos.

**Respuesta de diseño evaluada.** Revisé un borrador que proponía reutilizar registro y token, conservar inicialmente la ruta genérica del kit, aceptar código y comprobar la sesión. Para el `login()` proponía concentrar los controles en la versión segura, precargar un diccionario de hashes e inyectar dependencias. El esquema inicial de pruebas cubría éxito, contraseña incorrecta, usuario inexistente y un token inválido. Mi veredicto fue **incompleta**.

| Decisión | Hallazgo y criterio | Verificación |
|---|---|---|
| Aceptado | Reutilizar PBKDF2 con sal y `compare_digest`. **SEC-06** orienta la revisión criptográfica. | Pruebas de persistencia, login y firma. |
| Modificado | La ruta genérica dejaba ambiguo qué motor se ejecutaba y el modelo JSON carecía de límites. **SEC-04** orienta la validación de entrada. | Ruta fija `v2-revisor`, cuerpo estricto y dos casos con el motor del equipo. |
| Modificado | La propuesta inicial enumeraba estados HTTP y dejaba pendiente el formato de error. **ing-07** especifica `problem+json`. | Las pruebas comprueban contenido, estado y `trace_id`, además del resultado. |
| Modificado | Detecté un choque con **SEC-03** porque la primera bitácora guardaba el correo completo. **ing-02** guía el manejo de secretos. | Sustituí el correo por un HMAC con propósito separado. Probé el esquema nuevo, el bloqueo y la migración de intentos. |
| Rechazado | Usar una ruta con respuestas de demostración como evidencia de integración. | La prueba hace la petición HTTP y observa cuatro llamadas en el motor fijado. Las respuestas del proveedor están simuladas y se declaran como tales. |
| Rechazado | Comprobar el token inválido con una sola prueba genérica. Un error 401 podría ocultar una clase de falla distinta. | Casos separados para ausencia, expiración y alteración de firma, más bloqueo, entrada inválida y cuota. |

Medí tiempos de las cuatro versiones y de PBKDF2. Conservé el espía como comprobación del número de búsquedas, y traté la mediana de tiempo como una medición distinta. También mantuve el trabajo criptográfico para una cuenta inexistente. Las pruebas automatizadas usan cuentas ficticias y un secreto generado por sesión.
# Actividad 4 · Registro de diseño y evaluación

| Uso que hice de la IA | Qué observé | Decisión y verificación |
|---|---|---|
| Pedí un contrato para proponer el análisis de una muestra con Ruff. | Una propuesta puede incluir un archivo distinto o campos que simulan una aprobación. | Conservé el JSON y apliqué un esquema cerrado con la única ruta seleccionada. Probé ambos desvíos con propuestas controladas. |
| Pedí un flujo para confirmar desde una interfaz web. | Resolver el análisis en la misma petición puede ejecutar antes del clic. | Separé propuesta y decisión. Fijé los bytes y su huella al crear la propuesta, y probé dueño, reutilización y concurrencia. |
| Probé qué ocurre si el proveedor cierra el turno antes de proponer. | El flujo v1 puede terminar con una omisión a pesar de que hay un archivo seleccionado. | En v2 detecté el cierre prematuro y di una oportunidad acotada de corregir; repetí las mismas entradas. |
| Pedí una salida entendible del linter y del revisor. | Los códigos de Ruff y las reglas SEC describen controles distintos. | Mostré el resultado determinista de Ruff por un lado y las citas SEC verificadas por el otro. |

Usé dos versiones registradas en `prompts/`. En la corrida controlada inyecté
una ruta distinta y una respuesta prematura para reproducir dos fallas concretas.
El análisis estático y las decisiones de la API se ejecutan realmente en esas
pruebas. La corrida opcional con Gemini guarda sus propios resultados.

---

