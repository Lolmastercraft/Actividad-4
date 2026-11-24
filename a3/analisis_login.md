# Análisis comparativo del login oficial

Mi veredicto sobre la propuesta de IA es **incompleta**. Me sirvió para iniciar el diseño, pero quedaron pendientes el contrato HTTP, el alcance de la simulación y una medición real de eficiencia. Verifiqué las afirmaciones con `tests/test_a3_*.py` y un programa de medición aparte.

| Problema | Explicación técnica | Impacto | Tipo de mejora | Versión y evidencia |
|---|---|---|---|---|
| Credenciales en el archivo. | Encontré literales usados para decidir el acceso. | Una copia del archivo divulga el acceso de ejemplo. | SEC-01 e ing-02. | Reemplacé los literales con hashes de una dependencia. Probé la persistencia PBKDF2 con sal. |
| Comparación directa de contraseña. | Se usa igualdad de cadenas y un camino corto para usuarios inexistentes. | El tratamiento de credenciales carece de una derivación resistente. | SEC-06. | Verifico un hash con `compare_digest` y uso una huella auxiliar si falta la cuenta. |
| Respuestas distintas al fallar. | Cada rama produce una cadena pública propia. | Se puede distinguir si el problema es la cuenta o la contraseña. | Seguridad e ing-07. | Unifiqué la denegación y probé dos errores 401 con el mismo detalle. |
| Sesión y bloqueo ausentes. | La función retorna una cadena y no mantiene el estado de los intentos. | No hay contención ni trazabilidad. | A3 y SEC-03. | Añadí firma y bloqueo local en seguridad. En la API registré un identificador HMAC y probé la migración. |
| Mensajes con convenciones distintas. | El espacio final en `user not found ` forma parte del valor devuelto. | El cliente queda acoplado a una cadena exacta. | SEC-10. | Usé un resultado inmutable y probé la versión mantenible con dependencias inyectadas. |

## Qué cambié y por qué

- **Seguridad.** Implementé una política de bloqueo propia, con una ventana temporal y una clave HMAC por cuenta. Conservo la verificación auxiliar y emito un token tras una autenticación correcta. Así puedo probar esta versión por sí misma. La API sigue aplicando la persistencia y los controles del laboratorio mediante `Autenticador`.
- **Eficiencia.** Precargué las huellas y la configuración para evitar reconstruirlas o consultar SQLite por intento. Mantuve una derivación completa. Mido el tiempo y uso el espía exclusivamente para contar búsquedas.
- **Mantenibilidad.** Separé el contrato para buscar huellas de la política de login e inyecté el verificador. Esto me permite sustituir almacenamiento y comprobación por implementaciones controladas al probar.

Mantuve `login(user, password)` en los cuatro módulos. En las versiones nuevas uso un contexto de `configurar(...)` para proporcionar dependencias fuera de cada llamada.

## Cinco criterios comparados

| Criterio | Original | Seguridad | Eficiencia | Mantenible |
|---|---|---|---|---|
| Credenciales | Literales | Mapa de hashes PBKDF2 con sal | Diccionario de hashes precargados | Repositorio de hashes inyectado |
| Resultado inválido | Identifica la causa | Mensaje uniforme y bloqueo temporal | Mensaje uniforme | Mensaje uniforme |
| Sesión y seguimiento | Sin sesión | Token y bloqueo local con HMAC | Resultado local | Resultado local |
| Acceso a datos | Una cuenta fija | Mapa y ventana de fallos | Un `get` por intento, medido | Una consulta por interfaz |
| Facilidad de cambio y prueba | Comparaciones y textos acoplados | Política separada de los almacenes | Núcleo de función pequeño | Almacenamiento y verificación intercambiables |

Usé las versiones comparativas como ejercicios del núcleo de verificación. Para HTTP mantuve el servicio persistente de `api/auth.py`.

## Tiempos por login

Medí el recorrido exitoso en Windows con Python 3.12.13. Precargué las huellas, calenté las llamadas e hice diez rondas intercaladas de cinco intentos por versión protegida. Para el original usé 100,000 intentos por ronda por su menor duración. Estos son los resultados de la corrida local:

| Versión | Mediana por llamada | Mínimo–máximo por ronda |
|---|---:|---:|
| Seguridad | 82.57 ms | 51.74–106.94 ms |
| Eficiencia | 83.46 ms | 50.10–111.18 ms |
| Mantenible | 83.83 ms | 50.19–109.47 ms |
| Original | 0.091 µs | 0.057–0.121 µs |
| Solo PBKDF2 con verificación | 83.86 ms | 51.15–108.47 ms |

La versión de eficiencia reduce el trabajo de acceso a datos en este diseño. Con la variación medida, los tiempos no permiten afirmar que sea más rápida que las otras versiones protegidas. La derivación PBKDF2 de 200,000 iteraciones domina el tiempo y su costo es deliberado para encarecer las adivinaciones de contraseña. El original compara dos literales y hace mucho menos trabajo. Conservé la prueba del espía como medición de accesos y medí el tiempo aparte con `guia/medir_login.py`.
