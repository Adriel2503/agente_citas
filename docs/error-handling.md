# Error Handling — Agent Citas

## Contrato de respuesta

El agente **siempre** devuelve un `reply` con texto al gateway. Ningún error interno deja el campo vacío o nulo.

---

## Casos manejados internamente

### 1. Reply vacío del LLM

| Caso | Log | Mensaje al usuario |
|---|---|---|
| `reply` es `None` | `[AGENT] structured.reply es None` | "No recibí respuesta del asistente, por favor intenta nuevamente." |
| `reply` es `""` | `[AGENT] structured.reply es string vacío` | "El asistente envió una respuesta vacía, por favor intenta nuevamente." |

### 2. Respuesta fuera de formato estructurado

El LLM no respondió con `CitaStructuredResponse` — se cae al fallback de `last_message.content`.

| Caso | Log | Mensaje al usuario |
|---|---|---|
| JSON inválido o ausente | `[AGENT] Respuesta fuera de formato estructurado` | Usa `last_message.content` si tiene texto |
| `last_message.content` vacío | `[AGENT] last_message.content vacío` | "El asistente respondió en un formato inesperado, por favor intenta nuevamente." |

### 3. Errores de la API de OpenAI

| Excepción | HTTP | Log | Mensaje al usuario |
|---|---|---|---|
| `AuthenticationError` | 401 | `[AGENT][OpenAI-401] API key inválida` | "No puedo procesar tu mensaje, la clave de acceso al servicio no es válida." |
| `RateLimitError` | 429 | `[AGENT][OpenAI-429] Rate limit alcanzado` | "Estoy recibiendo demasiadas solicitudes, por favor intenta en unos segundos." |
| `InternalServerError` | 5xx | `[AGENT][OpenAI-5xx] Error interno OpenAI` | "El servicio de inteligencia artificial está presentando problemas, por favor intenta nuevamente." |
| `APIConnectionError` | N/A | `[AGENT][OpenAI-conn] Error de conexión` | "No pude conectarme al servicio de inteligencia artificial, por favor intenta nuevamente." |
| `BadRequestError` | 400 | `[AGENT][OpenAI-400] Bad request` | "Tu mensaje no pudo ser procesado por el servicio, ¿puedes reformularlo?" |

### 4. Error genérico

Cualquier excepción no contemplada anteriormente.

| Log | Mensaje al usuario |
|---|---|
| `[AGENT] Error inesperado (<tipo>)` | "Disculpa, tuve un problema al procesar tu mensaje. ¿Podrías intentar nuevamente?" |

---

## Caso fuera del agente — servidor caído

Si el servidor FastAPI no responde (crash, OOM, reinicio), el gateway **no recibe nada**. En ese caso:

- No hay HTTP 200
- La conexión se cierra o da timeout
- El gateway debe manejar este caso por su cuenta (retry, mensaje de error propio, etc.)

Este escenario es ajeno al agente — ocurre a nivel de infraestructura.
