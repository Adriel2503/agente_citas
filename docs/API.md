# API Reference — Agent Citas v2.0.0

Referencia completa de la API HTTP del agente especializado en citas y reuniones comerciales.

---

## Descripción General

El agente expone una API REST sobre FastAPI. El gateway Go llama directamente al endpoint `/api/chat`.

| Atributo | Valor |
|----------|-------|
| Protocolo | HTTP REST |
| Puerto | `8002` (configurable via `SERVER_PORT`) |
| Content-Type | `application/json` |
| Endpoint base | `http://localhost:8002` |

---

## Endpoints

### `POST /api/chat` — Endpoint principal

Procesa mensajes del usuario y gestiona el flujo completo de citas. El agente decide de forma autónoma qué herramientas usar en cada turno.

**Herramientas internas del LLM** (el gateway no las llama directamente):
- `check_availability` — consulta horarios disponibles
- `create_booking` — crea la cita con validación multicapa
- `search_productos_servicios` — busca productos/servicios del catálogo

---

#### Request

```http
POST /api/chat
Content-Type: application/json
```

```json
{
  "message": "Quiero agendar una reunión para mañana a las 2pm",
  "session_id": 12345,
  "context": {
    "config": {
      "id_empresa": 123,
      "usuario_id": 7,
      "correo_usuario": "vendedor@empresa.com",
      "personalidad": "amable y profesional",
      "duracion_cita_minutos": 60,
      "slots": 60,
      "agendar_usuario": 1,
      "agendar_sucursal": 0
    }
  }
}
```

##### Campos del body

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `message` | string | ✅ Sí | Mensaje del usuario (1–4096 chars). Puede contener URLs de imágenes (Vision) |
| `session_id` | **integer** | ✅ Sí | ID de sesión numérico (≥ 0). Usado como `thread_id` del checkpointer y como `id_prospecto` |
| `context` | object | ❌ No | Contexto de configuración del bot. Si se omite, se usa `{}` |

##### Campos de `context.config`

| Campo | Tipo | Requerido | Default | Uso | Descripción |
|-------|------|-----------|---------|-----|-------------|
| `id_empresa` | integer | ✅ Sí | — | Tools + Prompt | ID de la empresa. Determina horarios, contexto y catálogo |
| `usuario_id` | integer | ❌ No | `1` | CREAR_EVENTO | ID del vendedor (campo `usuario_id` en payload del calendario) |
| `correo_usuario` | string | ❌ No | `""` | CREAR_EVENTO | Email del vendedor (invitación Google Calendar) |
| `personalidad` | string | ❌ No | `"amable, profesional y eficiente"` | Prompt | Tono/personalidad del agente |
| `nombre_bot` | string | ❌ No | `"Asistente"` | Prompt | Nombre con el que el agente se presenta |
| `frase_saludo` | string | ❌ No | `"¡Hola! ¿En qué puedo ayudarte?"` | Prompt | Saludo inicial |
| `frase_des` | string | ❌ No | `"¡Gracias por contactarnos!"` | Prompt | Frase de despedida |
| `frase_no_sabe` | string | ❌ No | `"No tengo esa información a mano; te puedo ayudar a agendar una reunión para que te lo confirmen."` | Prompt | Frase cuando el agente no sabe algo |
| `archivo_saludo` | string | ❌ No | `""` | Prompt + `url` | URL de imagen/video de saludo. Se envía en `url` del primer mensaje |
| `id_chatbot` | integer | ❌ No | — | Prompt | ID del chatbot para cargar FAQs desde `ws_preguntas_frecuentes.php` |
| `duracion_cita_minutos` | integer | ❌ No | `60` | Tools | Duración de la cita en minutos (validación de horario + cálculo de `fecha_fin`) |
| `slots` | integer | ❌ No | `60` | Tools | Slots de disponibilidad para CONSULTAR_DISPONIBILIDAD y SUGERIR_HORARIOS |
| `agendar_usuario` | boolean/integer | ❌ No | `1` | Tools | `1` = asignar vendedor automáticamente al crear evento |
| `agendar_sucursal` | boolean/integer | ❌ No | `0` | Tools | `1` = agendar por sucursal |

> **Notas:**
> - El campo se llama `usuario_id` (no `id_usuario`).
> - El `session_id` del request se usa internamente como `id_prospecto` al crear el evento.
> - Los campos marcados "Prompt" se inyectan en el system prompt al crear el agente (cacheado por `id_empresa`, TTL 60 min).
> - Los campos marcados "Tools" se inyectan en tiempo real a cada tool via `AgentContext` (sin cache).

##### Flujo de los campos de config

```
context.config del gateway
    │
    ├─► Prompt (cacheado 60 min por id_empresa):
    │     personalidad, nombre_bot, frase_saludo, frase_des,
    │     frase_no_sabe, archivo_saludo, id_chatbot
    │
    └─► AgentContext (inyectado en cada tool call):
          id_empresa, usuario_id, correo_usuario,
          duracion_cita_minutos, slots, agendar_usuario,
          agendar_sucursal, id_prospecto (=session_id)
```

##### Soporte de imágenes (Vision)

Si `message` contiene URLs de imágenes (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`), el agente las procesa automáticamente vía OpenAI Vision. Máximo 10 imágenes por mensaje.

```json
{
  "message": "¿Pueden replicar este diseño? https://ejemplo.com/foto.jpg Para el viernes",
  "session_id": 12345,
  "context": {"config": {"id_empresa": 123}}
}
```

---

#### Response

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

**Respuesta normal:**
```json
{
  "reply": "¡Perfecto! Mañana a las 2:00 PM está disponible. Para confirmar, necesito tu nombre completo y correo.",
  "url": null
}
```

**Respuesta con Google Meet (después de crear cita):**
```json
{
  "reply": "¡Tu cita está confirmada! ...",
  "url": "https://meet.google.com/abc-defg-hij"
}
```

**Respuesta con imagen de saludo (primer mensaje + `archivo_saludo` configurado):**
```json
{
  "reply": "¡Hola! Soy Mara. ¿En qué puedo ayudarte?",
  "url": "https://cdn.empresa.com/saludo.jpg"
}
```

| Campo | Tipo | Siempre presente | Descripción |
|-------|------|-----------------|-------------|
| `reply` | string | ✅ Sí | Respuesta del agente en lenguaje natural (formato WhatsApp) |
| `url` | string \| null | ✅ Sí | URL de adjunto: Google Meet link, imagen de saludo, o `null` |

> **Importante:** El agente **siempre retorna HTTP 200**, incluso en casos de error. Los errores de configuración o timeout se devuelven como texto en el campo `reply`. El gateway Go no necesita manejar errores HTTP del agente.

---

### `GET /health` — Health check

Verifica el estado del servicio y sus dependencias. **No hace llamadas HTTP** a las APIs externas; usa el estado en memoria de los circuit breakers (latencia < 1ms).

```http
GET /health
```

**Response 200 (todo OK):**
```json
{
  "status": "ok",
  "agent": "citas",
  "version": "2.0.0",
  "issues": []
}
```

**Response 503 (degradado):**
```json
{
  "status": "degraded",
  "agent": "citas",
  "version": "2.0.0",
  "issues": ["openai_api_key_missing", "calendario_api_degraded"]
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `status` | string | `"ok"` o `"degraded"` |
| `agent` | string | Siempre `"citas"` |
| `version` | string | Versión del agente (`"2.0.0"`) |
| `issues` | string[] | Lista de problemas detectados (vacía si todo OK) |

**Issues posibles:**

| Issue | Causa | Impacto |
|-------|-------|---------|
| `openai_api_key_missing` | `OPENAI_API_KEY` no configurada | El agente no puede procesar mensajes |
| `informacion_api_degraded` | CB de `ws_informacion_ia.php` abierto | No se puede cargar horarios, contexto ni productos |
| `preguntas_api_degraded` | CB de `ws_preguntas_frecuentes.php` abierto | No se cargan FAQs al prompt |
| `calendario_api_degraded` | CB de `ws_calendario.php` abierto | No se pueden crear eventos/citas |
| `agendar_reunion_api_degraded` | CB de `ws_agendar_reunion.php` abierto | No se puede verificar disponibilidad |

---

### `GET /metrics` — Métricas Prometheus

```http
GET /metrics
```

Devuelve métricas en formato Prometheus text/plain. Diseñado para scraping por Prometheus/Grafana. Ver sección [Métricas](#métricas) para detalle.

---

## Ejemplos de Uso

### Ejemplo 1: Primera consulta (inicio de conversación)

**Request:**
```json
{
  "message": "Hola, quiero agendar una reunión",
  "session_id": 1001,
  "context": {
    "config": {
      "id_empresa": 123,
      "nombre_bot": "Mara",
      "personalidad": "amable y profesional"
    }
  }
}
```

**Response:**
```json
{
  "reply": "¡Hola! Soy Mara. ¿Para qué fecha te gustaría la reunión?",
  "url": null
}
```

---

### Ejemplo 2: Usuario da fecha y hora

**Request** (misma sesión, siguiente turno):
```json
{
  "message": "Para mañana a las 3pm",
  "session_id": 1001,
  "context": {
    "config": {
      "id_empresa": 123
    }
  }
}
```

**Response** (agente verificó disponibilidad vía `check_availability`):
```json
{
  "reply": "Mañana a las 3:00 PM está disponible. Para confirmar la reunión, necesito tu nombre completo y correo electrónico.",
  "url": null
}
```

---

### Ejemplo 3: Usuario completa los datos → cita creada

**Request:**
```json
{
  "message": "Juan Pérez, juan.perez@email.com",
  "session_id": 1001,
  "context": {
    "config": {
      "id_empresa": 123,
      "usuario_id": 7,
      "correo_usuario": "vendedor@empresa.com"
    }
  }
}
```

**Response** (agente confirmó con usuario y llamó `create_booking`):
```json
{
  "reply": "Evento agregado correctamente.\n\n*Detalles:*\n• Fecha: 2026-02-28\n• Hora: 3:00 PM\n• Nombre: Juan Pérez\n\nLa reunión será por videollamada. Enlace: https://meet.google.com/abc-defg-hij\n\n¡Te esperamos!",
  "url": "https://meet.google.com/abc-defg-hij"
}
```

> **Nota:** El enlace de Google Meet es real, devuelto por `ws_calendario.php`. El LLM no lo inventa.

---

### Ejemplo 4: Consulta de horarios disponibles (hoy/mañana)

**Request:**
```json
{
  "message": "¿Qué horarios tienen disponibles para hoy?",
  "session_id": 1002,
  "context": {
    "config": {
      "id_empresa": 123
    }
  }
}
```

**Response** (agente llamó `check_availability` sin `time` → SUGERIR_HORARIOS):
```json
{
  "reply": "Horarios disponibles para hoy:\n\n1. Hoy a las 10:00 AM\n2. Hoy a las 11:00 AM\n3. Hoy a las 03:00 PM\n\n¿Cuál te viene mejor?",
  "url": null
}
```

---

### Ejemplo 5: Consulta de slot específico

**Request:**
```json
{
  "message": "¿El viernes a las 4pm tienen disponibilidad?",
  "session_id": 1003,
  "context": {
    "config": {
      "id_empresa": 123
    }
  }
}
```

**Response** (agente llamó `check_availability(date, time="4:00 PM")` → CONSULTAR_DISPONIBILIDAD):
```json
{
  "reply": "El 2026-02-27 a las 4:00 PM está disponible. ¿Confirmamos la cita? Necesito tu nombre completo y correo.",
  "url": null
}
```

---

### Ejemplo 6: Consulta de producto/servicio específico

**Request:**
```json
{
  "message": "¿Cuánto cuesta el servicio de consultoría estratégica?",
  "session_id": 1004,
  "context": {
    "config": {
      "id_empresa": 123
    }
  }
}
```

**Response** (agente llamó `search_productos_servicios`):
```json
{
  "reply": "Encontré 1 resultado para 'consultoría estratégica':\n\n*Consultoría Estratégica*\n- Precio: S/. 350.00 por sesión\n- Categoría: Consultoría\n- Descripción: Sesión personalizada de 60 min para definir objetivos...\n\n¿Te gustaría agendar una sesión?",
  "url": null
}
```

---

### Ejemplo 7: Configuración completa (empresa con todas las opciones)

**Request:**
```json
{
  "message": "Buenos días",
  "session_id": 9999,
  "context": {
    "config": {
      "id_empresa": 456,
      "usuario_id": 12,
      "correo_usuario": "asesor@miempresa.com",
      "personalidad": "entusiasta y directo",
      "nombre_bot": "Alex",
      "frase_saludo": "¡Hola! Soy Alex, tu asistente de citas.",
      "frase_des": "¡Hasta pronto! Fue un placer atenderte.",
      "frase_no_sabe": "No tengo esa información, pero puedo conectarte con un asesor.",
      "duracion_cita_minutos": 45,
      "slots": 30,
      "agendar_usuario": 1,
      "agendar_sucursal": 0
    }
  }
}
```

**Response:**
```json
{
  "reply": "¡Hola! Soy Alex, tu asistente de citas. ¿Para qué fecha y hora te gustaría agendar tu reunión?",
  "url": null
}
```

---

## Errores

El agente siempre responde con HTTP 200. Los errores se comunican en texto dentro del campo `reply`.

### Error: `id_empresa` faltante

**Causa:** No se envió `context.config.id_empresa` o su valor es `null`.

**Response:**
```json
{
  "reply": "Error de configuración: Context missing required keys in config: ['id_empresa']",
  "url": null
}
```

---

### Error: Mensaje vacío

**Causa:** `message` es vacío o solo contiene espacios.

**Response:**
```json
{
  "reply": "No recibí tu mensaje. ¿Podrías repetirlo?",
  "url": null
}
```

---

### Error: `session_id` inválido

**Causa:** `session_id` es negativo o `null`.

**Response:** HTTP 500 (excepción no capturada como HTTP 200):
```
ValueError: session_id es requerido (entero no negativo)
```

> **Nota:** Este es el único caso donde el agente **no** retorna HTTP 200. Un `session_id` inválido indica un bug en el gateway.

---

### Error: Timeout

**Causa:** El procesamiento superó `CHAT_TIMEOUT` (default 120s).

**Response:**
```json
{
  "reply": "La solicitud tardó más de 120s. Por favor, intenta de nuevo.",
  "url": null
}
```

---

### Error: Fallo al crear agente

**Causa:** Error al inicializar el modelo LLM o construir el system prompt (ej. `OPENAI_API_KEY` inválida).

**Response:**
```json
{
  "reply": "Disculpa, tuve un problema de configuración. ¿Podrías intentar nuevamente?",
  "url": null
}
```

---

### Error: Fallo al ejecutar agente

**Causa:** Error inesperado durante `agent.ainvoke()` (ej. OpenAI rate limit, error de red).

**Response:**
```json
{
  "reply": "Disculpa, tuve un problema al procesar tu mensaje. ¿Podrías intentar nuevamente?",
  "url": null
}
```

---

### Error: Circuit breaker abierto (calendario)

**Causa:** `ws_calendario.php` acumuló 3+ errores de transporte consecutivos. El agente no intenta la llamada HTTP.

**Respuesta del agente** (dentro de `create_booking`):
```
El servicio de calendario no está disponible en este momento. Por favor intenta en unos minutos.
```

---

### Error: Email inválido (validación de cita)

**Causa:** El usuario proporcionó un email con formato incorrecto al intentar crear la cita.

> **Importante:** El agente solo acepta **email** como contacto del cliente (no teléfono). El sistema valida formato RFC 5322 simplificado.

**Respuesta del agente** (en lenguaje natural):
```
Datos inválidos: Contacto inválido: El contacto debe ser un email válido (ejemplo: nombre@dominio.com). Recibido: 987654321

Por favor verifica la información.
```

---

### Error: Horario fuera de rango

**Causa:** La hora solicitada está fuera del horario de atención de la empresa.

**Respuesta del agente:**
```
La hora seleccionada es después del horario de atención.
El horario del sábado es de 09:00 AM a 01:00 PM.
Por favor elige una hora más temprana.

Por favor elige otra fecha u hora.
```

---

### Error: Slot ocupado

**Causa:** El horario ya tiene una cita confirmada (`CONSULTAR_DISPONIBILIDAD` retorna `disponible: false`).

**Respuesta del agente:**
```
El horario seleccionado ya está ocupado. Por favor elige otra hora o fecha.

Por favor elige otra fecha u hora.
```

---

### Error: Día sin atención

**Causa:** La empresa no tiene atención el día seleccionado (campo `reunion_domingo: "NO DISPONIBLE"`).

**Respuesta del agente:**
```
No hay atención el día domingo. Por favor elige otro día.

Por favor elige otra fecha u hora.
```

---

### Error: Fecha/hora en el pasado

**Causa:** La fecha y hora solicitada ya pasó (comparada en zona horaria `America/Lima`).

**Respuesta del agente:**
```
La fecha y hora seleccionada ya pasó. Por favor elige una fecha y hora futura.

Por favor elige otra fecha u hora.
```

---

### Error: Cita excede horario de cierre

**Causa:** La cita de N minutos terminaría después del cierre (ej. cita de 60 min a las 5:30 PM, cierre a las 6:00 PM).

**Respuesta del agente:**
```
La cita de 60 minutos excedería el horario de atención (cierre: 06:00 PM). El horario del viernes es de 09:00 AM a 06:00 PM. Por favor elige una hora más temprana.

Por favor elige otra fecha u hora.
```

---

### Error: Horario bloqueado

**Causa:** La hora cae en un bloque reservado por la empresa (campo `horarios_bloqueados` en el horario).

**Respuesta del agente:**
```
El horario seleccionado está bloqueado. Por favor elige otra hora.

Por favor elige otra fecha u hora.
```

---

### Error interno del agente

**Causa:** Fallo inesperado en el procesamiento.

**Response:**
```json
{
  "reply": "Error procesando mensaje: <detalle>. Por favor intenta nuevamente.",
  "url": null
}
```

---

## Validaciones de Datos del Cliente

Cuando el agente recoge los datos para crear la cita, valida:

### Email del cliente (`customer_contact`)

- Formato RFC 5322 simplificado: `nombre@dominio.tld`
- Máximo 254 caracteres
- Se normaliza a **lowercase**
- **Solo email** — no se acepta teléfono

| Entrada | Resultado |
|---------|-----------|
| `juan@empresa.com` | ✅ válido → `juan@empresa.com` |
| `Juan@EMPRESA.COM` | ✅ válido → `juan@empresa.com` |
| `987654321` | ❌ inválido — no es email |
| `usuario@` | ❌ inválido — dominio faltante |

### Nombre del cliente (`customer_name`)

- 2 a 100 caracteres
- Sin números
- Solo letras (incluye acentos y ñ), espacios, guiones, apóstrofes
- Se capitaliza automáticamente (`title()`)

| Entrada | Resultado |
|---------|-----------|
| `juan pérez` | ✅ → `Juan Pérez` |
| `O'Brien` | ✅ → `O'Brien` |
| `Juan123` | ❌ — contiene números |
| `A` | ❌ — demasiado corto |

### Fecha (`date`)

- Formato: `YYYY-MM-DD`
- No puede ser fecha pasada (comparada en zona horaria `America/Lima`)

### Hora (`time`)

- Formatos aceptados: `HH:MM AM/PM`, `HH:MM%p`, `HH:MM` (24h)
- Ejemplos válidos: `"3:00 PM"`, `"10:30 AM"`, `"14:30"`
- **Siempre debe incluir AM/PM** cuando el LLM llama las tools (regla del system prompt)

---

## Métricas

### Endpoint

```
GET http://localhost:8002/metrics
```

### Contadores

```prometheus
# ── Conversaciones ──
agent_citas_chat_requests_total{empresa_id="123"} 150
agent_citas_chat_errors_total{error_type="context_error"} 2
agent_citas_chat_errors_total{error_type="agent_creation_error"} 0
agent_citas_chat_errors_total{error_type="agent_execution_error"} 1

# ── Citas ──
agent_citas_booking_attempts_total 50
agent_citas_booking_success_total 42
agent_citas_booking_failed_total{reason="timeout"} 2
agent_citas_booking_failed_total{reason="api_error"} 1
agent_citas_booking_failed_total{reason="invalid_datetime"} 3
agent_citas_booking_failed_total{reason="circuit_open"} 0
agent_citas_booking_failed_total{reason="connection_error"} 1
agent_citas_booking_failed_total{reason="http_500"} 0

# ── Tools ──
agent_citas_tool_calls_total{tool_name="check_availability"} 98
agent_citas_tool_calls_total{tool_name="create_booking"} 45
agent_citas_tool_calls_total{tool_name="search_productos_servicios"} 27
agent_citas_tool_errors_total{tool_name="create_booking",error_type="TimeoutError"} 1

# ── APIs externas ──
agent_citas_api_calls_total{endpoint="consultar_disponibilidad",status="success"} 90
agent_citas_api_calls_total{endpoint="sugerir_horarios",status="success"} 30
agent_citas_api_calls_total{endpoint="crear_evento",status="success"} 42
agent_citas_api_calls_total{endpoint="crear_evento",status="error_TimeoutException"} 2

# ── HTTP layer (/api/chat) ──
citas_http_requests_total{status="success"} 145
citas_http_requests_total{status="timeout"} 3
citas_http_requests_total{status="error"} 2

# ── Caches ──
citas_agent_cache_total{result="hit"} 1200
citas_agent_cache_total{result="miss"} 15
citas_search_cache_total{result="hit"} 50
citas_search_cache_total{result="miss"} 20
citas_search_cache_total{result="circuit_open"} 0
```

### Histogramas (latencia)

```prometheus
# Latencia total del endpoint /api/chat
citas_http_duration_seconds_bucket{le="0.25"} 5
citas_http_duration_seconds_bucket{le="1.0"} 20
citas_http_duration_seconds_bucket{le="5.0"} 100
citas_http_duration_seconds_bucket{le="10.0"} 140
citas_http_duration_seconds_bucket{le="120.0"} 150

# Latencia de respuesta del chat (dentro del agente)
agent_citas_chat_response_duration_seconds_bucket{status="success",le="5.0"} 130
agent_citas_chat_response_duration_seconds_bucket{status="error",le="5.0"} 2

# Latencia de ejecución de tools
agent_citas_tool_execution_duration_seconds_bucket{tool_name="check_availability",le="5.0"} 90
agent_citas_tool_execution_duration_seconds_bucket{tool_name="create_booking",le="10.0"} 44
agent_citas_tool_execution_duration_seconds_bucket{tool_name="search_productos_servicios",le="5.0"} 25

# Latencia de llamadas a APIs externas
agent_citas_api_call_duration_seconds_bucket{endpoint="consultar_disponibilidad",le="2.5"} 85
agent_citas_api_call_duration_seconds_bucket{endpoint="crear_evento",le="5.0"} 40

# Latencia de llamadas al LLM
agent_citas_llm_call_duration_seconds_bucket{status="success",le="5.0"} 120
agent_citas_llm_call_duration_seconds_bucket{status="error",le="5.0"} 2
```

### Gauges y Info

```prometheus
# Entradas actuales en caches
agent_citas_cache_entries{cache_type="schedule"} 8

# Información del agente
agent_citas_info{agent_type="citas",model="gpt-4o-mini",version="2.0.0"} 1
```

---

## Integración

### Python (httpx async)

```python
import httpx

async def chat_citas(
    mensaje: str,
    session_id: int,
    id_empresa: int,
    usuario_id: int = 1,
    correo_usuario: str = ""
) -> tuple[str, str | None]:
    """Retorna (reply, url). url es None cuando no hay adjunto."""
    async with httpx.AsyncClient(timeout=130) as client:
        response = await client.post(
            "http://localhost:8002/api/chat",
            json={
                "message": mensaje,
                "session_id": session_id,
                "context": {
                    "config": {
                        "id_empresa": id_empresa,
                        "usuario_id": usuario_id,
                        "correo_usuario": correo_usuario,
                    }
                }
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["reply"], data.get("url")
```

### Go

```go
package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "net/http"
)

type ChatRequest struct {
    Message   string                 `json:"message"`
    SessionID int                    `json:"session_id"`
    Context   map[string]interface{} `json:"context"`
}

type ChatResponse struct {
    Reply string  `json:"reply"`
    URL   *string `json:"url"`
}

func chatCitas(mensaje string, sessionID int, idEmpresa int) (string, error) {
    body, _ := json.Marshal(ChatRequest{
        Message:   mensaje,
        SessionID: sessionID,
        Context: map[string]interface{}{
            "config": map[string]interface{}{
                "id_empresa": idEmpresa,
            },
        },
    })

    resp, err := http.Post(
        "http://localhost:8002/api/chat",
        "application/json",
        bytes.NewBuffer(body),
    )
    if err != nil {
        return "", err
    }
    defer resp.Body.Close()

    var result ChatResponse
    json.NewDecoder(resp.Body).Decode(&result)
    return result.Reply, nil
}
```

### curl

```bash
curl -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Quiero una cita para mañana a las 10am",
    "session_id": 12345,
    "context": {
      "config": {
        "id_empresa": 123,
        "usuario_id": 1
      }
    }
  }'
```

---

## Tools internas del agente — Referencia detallada

Las tools son funciones internas que el LLM invoca vía function calling. **El gateway no las llama directamente** — solo envía mensajes a `/api/chat` y el agente decide autónomamente qué tools usar.

### Origen de cada parámetro

> **🤖 IA** = el LLM decide el valor basándose en la conversación.
> **🔧 Gateway** = viene de `context.config` del request, inyectado vía `AgentContext`.
> **🔢 Código** = calculado por el código Python (ni IA ni gateway).

---

### `check_availability(date, time?)`

**Descripción LLM:** *"Consulta horarios disponibles para una cita/reunión y fecha (y opcionalmente hora)."*

| Parámetro | Tipo | Requerido | Origen | Ejemplo |
|-----------|------|-----------|--------|---------|
| `date` | `str` | ✅ | 🤖 IA | `"2026-02-28"` |
| `time` | `str \| None` | ❌ | 🤖 IA | `"3:00 PM"` o `None` |

**Datos del contexto que usa internamente:**

| Campo `AgentContext` | Origen | Usado en |
|---------------------|--------|----------|
| `id_empresa` | 🔧 Gateway | Payload de ambas APIs |
| `duracion_cita_minutos` | 🔧 Gateway (default 60) | Cálculo de `fecha_fin` en CONSULTAR_DISPONIBILIDAD |
| `slots` | 🔧 Gateway (default 60) | Payload de ambas APIs |
| `agendar_usuario` | 🔧 Gateway (default 1) | Payload de ambas APIs |
| `agendar_sucursal` | 🔧 Gateway (default 0) | Payload de ambas APIs |

**Caso 1 — Con hora → `ws_agendar_reunion.php` (`CONSULTAR_DISPONIBILIDAD`):**
```json
// Payload enviado
{
  "codOpe": "CONSULTAR_DISPONIBILIDAD",
  "id_empresa": 42,                        // 🔧 Gateway
  "fecha_inicio": "2026-02-28 15:00:00",   // 🔢 Código (date + time → datetime)
  "fecha_fin": "2026-02-28 16:00:00",      // 🔢 Código (fecha_inicio + duracion_cita_minutos)
  "slots": 60,                              // 🔧 Gateway
  "agendar_usuario": 1,                     // 🔧 Gateway
  "agendar_sucursal": 0                     // 🔧 Gateway
}

// Respuesta
{"success": true, "disponible": true}
```

**Caso 2 — Sin hora → `ws_agendar_reunion.php` (`SUGERIR_HORARIOS`):**
```json
// Payload enviado
{
  "codOpe": "SUGERIR_HORARIOS",
  "id_empresa": 42,                // 🔧 Gateway
  "duracion_minutos": 60,          // 🔧 Gateway
  "slots": 60,                     // 🔧 Gateway
  "agendar_usuario": 1,            // 🔧 Gateway
  "agendar_sucursal": 0            // 🔧 Gateway
}

// Respuesta
{
  "success": true,
  "mensaje": "Horarios disponibles encontrados",
  "total": 3,
  "sugerencias": [
    {"dia": "hoy", "hora_legible": "3:00 PM", "disponible": true, "fecha_inicio": "2026-02-26 15:00:00"},
    {"dia": "mañana", "hora_legible": "10:00 AM", "disponible": true, "fecha_inicio": "2026-02-27 10:00:00"}
  ]
}
```

**Texto que recibe el LLM** (generado por `ScheduleValidator.recommendation()`):

- Con hora disponible: `"El 2026-02-28 a las 3:00 PM está disponible. ¿Confirmamos la cita?"`
- Con hora ocupada: `"El horario seleccionado ya está ocupado. ¿Te gustaría que te sugiera otros horarios?"`
- Sin hora (sugerencias): `"Horarios disponibles encontrados\n\n1. Hoy a las 3:00 PM\n2. Mañana a las 10:00 AM"`
- Fecha no hoy/mañana: `"Para esa fecha indica una hora que prefieras y la verifico."`
- Error/fallback: `"No pude consultar disponibilidad ahora. Indica una fecha y hora y la verifico."`

---

### `create_booking(date, time, customer_name, customer_contact)`

**Descripción LLM:** *"Crea una nueva cita (evento en calendario) con validación y confirmación real."*

| Parámetro | Tipo | Requerido | Origen | Validación | Ejemplo |
|-----------|------|-----------|--------|------------|---------|
| `date` | `str` | ✅ | 🤖 IA | `YYYY-MM-DD`, no en el pasado | `"2026-02-28"` |
| `time` | `str` | ✅ | 🤖 IA | `HH:MM AM/PM` (obligatorio AM/PM) | `"3:00 PM"` |
| `customer_name` | `str` | ✅ | 🤖 IA | ≥2 chars, sin números, solo letras/acentos | `"Juan Pérez"` |
| `customer_contact` | `str` | ✅ | 🤖 IA | Email RFC 5322 simplificado | `"juan@ejemplo.com"` |

**Datos del contexto que usa internamente:**

| Campo `AgentContext` | Origen | Campo en payload `CREAR_EVENTO` |
|---------------------|--------|--------------------------------|
| `usuario_id` | 🔧 Gateway (default 1) | `usuario_id` |
| `id_prospecto` (= session_id) | ⚙️ Runtime | `id_prospecto` |
| `correo_usuario` | 🔧 Gateway (default "") | `correo_usuario` |
| `agendar_usuario` | 🔧 Gateway (default 1) | `agendar_usuario` |
| `duracion_cita_minutos` | 🔧 Gateway (default 60) | Cálculo de `fecha_fin` |
| `slots` | 🔧 Gateway (default 60) | Validación (CONSULTAR_DISPONIBILIDAD) |
| `agendar_sucursal` | 🔧 Gateway (default 0) | Validación (CONSULTAR_DISPONIBILIDAD) |

**Pipeline de 3 fases:**

```
Fase 1 — Validación Pydantic (validation.py)
  ├─ date: YYYY-MM-DD, no pasado
  ├─ time: HH:MM AM/PM o HH:MM
  ├─ customer_name: ≥2 chars, sin números, sin chars peligrosos → title()
  └─ customer_contact: email válido → lowercase

Fase 2 — ScheduleValidator.validate() (12 pasos)
  ├─ 1. Parsear fecha        ├─ 7. ¿Día cerrado?
  ├─ 2. Parsear hora          ├─ 8. Parsear rango horario
  ├─ 3. Combinar datetime     ├─ 9. ¿Antes de apertura?
  ├─ 4. ¿En el pasado?        ├─ 10. ¿Después de cierre?
  ├─ 5. Obtener horario (cache)├─ 11. ¿Cita excede cierre?
  ├─ 6. ¿Hay horario ese día? └─ 12. CONSULTAR_DISPONIBILIDAD

Fase 3 — confirm_booking() → ws_calendario.php (CREAR_EVENTO)
```

**Payload exacto enviado a `CREAR_EVENTO`:**
```json
{
  "codOpe": "CREAR_EVENTO",
  "usuario_id": 7,                                  // 🔧 Gateway
  "id_prospecto": 5191234567890,                     // ⚙️ Runtime (= session_id)
  "titulo": "Reunion para el usuario: Juan Pérez",   // 🔢 Código (hardcoded template)
  "fecha_inicio": "2026-02-28 15:00:00",             // 🔢 Código (date + parse_time_to_24h)
  "fecha_fin": "2026-02-28 16:00:00",                // 🔢 Código (fecha_inicio + duracion)
  "correo_cliente": "juan@ejemplo.com",              // 🤖 IA (customer_contact)
  "correo_usuario": "vendedor@empresa.com",          // 🔧 Gateway
  "agendar_usuario": 1                               // 🔧 Gateway
}
```

**Respuestas posibles de `ws_calendario.php`:**
```json
// Éxito con Google Meet
{
  "success": true,
  "message": "Evento agregado correctamente",
  "google_meet_link": "https://meet.google.com/abc-defg-hij",
  "google_calendar_synced": true
}

// Éxito sin Google Calendar
{
  "success": true,
  "message": "Evento agregado correctamente",
  "google_calendar_synced": false
}

// Error
{
  "success": false,
  "message": "Error al crear el evento"
}
```

**Texto que recibe el LLM:**

- Éxito con Meet: `"Evento agregado correctamente.\n\nDetalles:\n• Fecha: 2026-02-28\n• Hora: 3:00 PM\n• Nombre: Juan Pérez\n\nLa reunión será por videollamada. Enlace: https://meet.google.com/abc-defg-hij\n\n¡Te esperamos!"`
- Éxito sin Meet: `"...Tu cita está confirmada. No se pudo generar el enlace de videollamada; te contactaremos con los detalles.\n\n¡Te esperamos!"`
- Validación fallida: `"La hora seleccionada es después del horario de atención. El horario del viernes es de 09:00 AM a 05:00 PM.\n\nPor favor elige otra fecha u hora."`
- Error API: `"No se pudo confirmar la cita\n\nPor favor intenta nuevamente."`

**Nota de seguridad:** El campo `titulo` lo construye el código (`f"Reunion para el usuario: {nombre}"`), no el LLM. `confirm_booking` usa `client.post()` directo (sin `post_with_retry`) porque `CREAR_EVENTO` no es idempotente.

---

### `search_productos_servicios(busqueda)`

**Descripción LLM:** *"Busca productos y servicios del catálogo por nombre o descripción."*

| Parámetro | Tipo | Requerido | Origen | Ejemplo |
|-----------|------|-----------|--------|---------|
| `busqueda` | `str` | ✅ | 🤖 IA | `"NovaX"` |

**Datos del contexto que usa internamente:**

| Campo `AgentContext` | Origen | Usado en |
|---------------------|--------|----------|
| `id_empresa` | 🔧 Gateway | Payload de la API + cache key |

**Payload enviado a `ws_informacion_ia.php`:**
```json
{
  "codOpe": "BUSCAR_PRODUCTOS_SERVICIOS_CITAS",
  "id_empresa": 42,       // 🔧 Gateway
  "busqueda": "NovaX",    // 🤖 IA
  "limite": 10            // 🔢 Código (constante MAX_RESULTADOS)
}
```

**Respuesta de la API:**
```json
{
  "success": true,
  "productos": [
    {
      "nombre": "NovaX Pro",
      "precio_unitario": 99.90,
      "nombre_categoria": "Software",
      "descripcion": "<p>Plataforma de gestión empresarial</p>",
      "nombre_tipo_producto": "Producto",
      "nombre_unidad": "licencia"
    }
  ]
}
```

**Texto que recibe el LLM** (generado por `format_productos_para_respuesta`):

Para productos:
```
### NovaX Pro
- Precio: S/. 99.90 por licencia
- Categoría: Software
- Descripción: Plataforma de gestión empresarial
```

Para servicios (`nombre_tipo_producto: "Servicio"`):
```
### Consultoría Empresarial
- Precio: S/. 250.00
- Categoría: Asesoría
- Descripción: Sesión de consultoría personalizada
```

**Cache:** TTLCache 15 min por `(id_empresa, busqueda.lower())`. Anti-thundering herd con `asyncio.Lock` por cache key.

---

## Comportamiento del Agente

### Lógica de disponibilidad

El agente aplica estas reglas de forma autónoma:

| Mensaje del usuario | Acción del agente |
|--------------------|--------------------|
| Solo fecha (`"el viernes"`) | Pregunta la hora. No llama ninguna tool |
| Fecha + hora (`"viernes a las 3pm"`) | Llama `check_availability(date, time)` → verifica slot exacto |
| Pregunta explícita de horarios (`"¿qué horarios tienen hoy?"`) | Llama `check_availability(date)` sin `time` → sugiere horarios (**solo hoy/mañana**; otras fechas pide hora) |
| Pregunta general de productos (`"¿qué servicios ofrecen?"`) | Responde con la lista del system prompt |
| Pregunta específica (`"¿cuánto cuesta X?"`) | Llama `search_productos_servicios(busqueda)` |
| Tiene fecha + hora + nombre + email | Pide confirmación, luego llama `create_booking` |

### Formato de respuesta (WhatsApp)

El system prompt instruye al agente a usar formato compatible con WhatsApp:
- Negrita: `*texto*`
- Cursiva: `_texto_`
- Tachado: `~texto~`
- Viñetas: línea que empiece con `*` o `-` y espacio
- Numeradas: `1.` y espacio
- Monoespaciado: `` ```código``` ``
- Cita: `>` al inicio de la línea
- URLs: solo la URL, sin formato Markdown `[texto](url)`
- Sin encabezados `##`
- Máximo 3-4 oraciones por respuesta

### Memoria conversacional

La memoria es automática via `InMemorySaver` de LangGraph. El agente recuerda **toda la conversación** del mismo `session_id` sin necesidad de enviar historial. Si el servidor se reinicia, la memoria se pierde.

### Timeout por capas

| Capa | Timeout | Variable |
|------|---------|----------|
| Request total | 120s | `CHAT_TIMEOUT` |
| Llamada al LLM | 60s | `OPENAI_TIMEOUT` |
| APIs externas MaravIA | 10s | `API_TIMEOUT` |

---

## Resiliencia

### Circuit Breakers

El agente usa 4 circuit breakers independientes. Cuando una API acumula 3 errores de transporte consecutivos (`httpx.TransportError`), el circuit se abre y las llamadas se rechazan inmediatamente sin tocar la red. Se auto-resetea tras 300 segundos (configurable via `CB_RESET_TTL`).

| Circuit Breaker | API protegida | Key | Servicios que lo usan |
|----------------|--------------|-----|----------------------|
| `informacion_cb` | `ws_informacion_ia.php` | `id_empresa` | horario_cache, contexto_negocio, productos, búsqueda |
| `preguntas_cb` | `ws_preguntas_frecuentes.php` | `id_chatbot` | preguntas_frecuentes |
| `calendario_cb` | `ws_calendario.php` | `"global"` | booking (CREAR_EVENTO) |
| `agendar_reunion_cb` | `ws_agendar_reunion.php` | `id_empresa` | schedule_validator (CONSULTAR_DISPONIBILIDAD, SUGERIR_HORARIOS) |

> **Importante:** Solo `httpx.TransportError` (fallos de red reales) abren el circuit. Las respuestas `success: false` de la API **no** abren el circuit — el servidor está respondiendo, solo retorna error de negocio.

### Retry con backoff exponencial

Las llamadas de lectura (`post_with_logging`) usan tenacity con retry automático:

| Parámetro | Default | Variable |
|-----------|---------|----------|
| Intentos máximos | 3 | `HTTP_RETRY_ATTEMPTS` |
| Espera mínima | 1s | `HTTP_RETRY_WAIT_MIN` |
| Espera máxima | 4s | `HTTP_RETRY_WAIT_MAX` |

Solo se reintenta ante `httpx.TransportError`. `CREAR_EVENTO` **no** usa retry (no es idempotente).

### Graceful degradation

Si una API falla, el agente no se cae — degrada funcionalidad:

| Fallo | Comportamiento |
|-------|---------------|
| Horarios no disponibles | Permite la cita sin validar horario |
| Contexto de negocio falla | Prompt sin contexto; agente funciona |
| FAQs fallan | Prompt sin FAQs; agente funciona |
| CONSULTAR_DISPONIBILIDAD falla | Asume disponible (graceful degradation) |
| SUGERIR_HORARIOS falla | Responde: "Indica fecha y hora que prefieras y la verifico" |
| CREAR_EVENTO falla | Reporta error al usuario |

### Caches

| Cache | TTL | Key | Maxsize | Anti-thundering herd |
|-------|-----|-----|---------|---------------------|
| Agente (grafo compilado) | 60 min | `(id_empresa,)` | 500 | `asyncio.Lock` + double-check |
| Horarios | 5 min | `id_empresa` | 256 | `asyncio.Lock` + double-check |
| Contexto negocio | 60 min | `id_empresa` | 256 | `asyncio.Lock` + double-check |
| FAQs | 60 min | `id_chatbot` | 256 | `asyncio.Lock` + double-check |
| Búsqueda productos | 15 min | `(id_empresa, busqueda)` | 2000 | `asyncio.Lock` + double-check |
| Checkpointer (sesiones) | ∞ (sin TTL) | `session_id` | ∞ | Session lock |

> **Nota:** El checkpointer `InMemorySaver` no tiene TTL ni límite. La memoria se pierde si el servidor se reinicia. Pendiente migrar a `AsyncRedisSaver` con TTL 24h (ver [PENDIENTES.md](PENDIENTES.md#c1--inmemorysaver-sin-ttl-memory-leak)).

---

## Concurrencia

El agente es **async single-thread** (asyncio). Múltiples requests se procesan concurrentemente, pero con locks en dos puntos:

### Lock por sesión (`session_id`)

Serializa requests del mismo usuario (ej. doble-click en WhatsApp). Diferentes usuarios nunca se bloquean entre sí.

### Lock por empresa (creación de agente)

Cuando el cache del agente expira (cada 60 min), el primer request de esa empresa crea el agente (~2s). Requests concurrentes de la misma empresa esperan y usan el cache. Requests de otras empresas no se bloquean.

### Límites del HTTP client

| Parámetro | Valor |
|-----------|-------|
| Max conexiones | 50 |
| Max keepalive | 20 |
| Keepalive expiry | 30s |
| Connect timeout | 5s |
| Read timeout | `API_TIMEOUT` (10s) |

---

## Variables de Entorno

### OpenAI

| Variable | Default | Descripción |
|----------|---------|-------------|
| `OPENAI_API_KEY` | `""` | API key de OpenAI (requerida) |
| `OPENAI_MODEL` | `"gpt-4o-mini"` | Modelo a usar |
| `OPENAI_TEMPERATURE` | `0.5` | Temperatura (0.0–2.0) |

### Servidor

| Variable | Default | Descripción |
|----------|---------|-------------|
| `SERVER_HOST` | `"0.0.0.0"` | Host de escucha |
| `SERVER_PORT` | `8002` | Puerto (1–65535) |

### Timeouts

| Variable | Default | Rango | Descripción |
|----------|---------|-------|-------------|
| `CHAT_TIMEOUT` | `120` | 30–300 | Timeout total del request (segundos) |
| `OPENAI_TIMEOUT` | `60` | 1–300 | Timeout de llamada al LLM |
| `API_TIMEOUT` | `10` | 1–120 | Timeout de APIs externas MaravIA |
| `MAX_TOKENS` | `2048` | 1–128000 | Max tokens de respuesta del LLM |

### Retry HTTP

| Variable | Default | Descripción |
|----------|---------|-------------|
| `HTTP_RETRY_ATTEMPTS` | `3` | Intentos máximos (1–10) |
| `HTTP_RETRY_WAIT_MIN` | `1` | Espera mínima en segundos (0–30) |
| `HTTP_RETRY_WAIT_MAX` | `4` | Espera máxima en segundos (1–60) |

### Circuit Breaker

| Variable | Default | Descripción |
|----------|---------|-------------|
| `CB_THRESHOLD` | `3` | Fallos para abrir circuit (1–20) |
| `CB_RESET_TTL` | `300` | Segundos para auto-reset (60–3600) |

### Cache

| Variable | Default | Descripción |
|----------|---------|-------------|
| `SCHEDULE_CACHE_TTL_MINUTES` | `5` | TTL del cache de horarios (1–1440) |
| `AGENT_CACHE_TTL_MINUTES` | `60` | TTL del cache de agentes (5–1440) |
| `AGENT_CACHE_MAXSIZE` | `500` | Max agentes cacheados (10–5000) |

### APIs MaravIA

| Variable | Default |
|----------|---------|
| `API_CALENDAR_URL` | `https://api.maravia.pe/servicio/ws_calendario.php` |
| `API_AGENDAR_REUNION_URL` | `https://api.maravia.pe/servicio/ws_agendar_reunion.php` |
| `API_INFORMACION_URL` | `https://api.maravia.pe/servicio/ws_informacion_ia.php` |
| `API_PREGUNTAS_FRECUENTES_URL` | `https://api.maravia.pe/servicio/n8n/ws_preguntas_frecuentes.php` |

### Otros

| Variable | Default | Descripción |
|----------|---------|-------------|
| `TIMEZONE` | `"America/Lima"` | Zona horaria para fechas y validaciones |
| `LOG_LEVEL` | `"INFO"` | Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `LOG_FILE` | `""` | Ruta de archivo de log (vacío = solo stdout) |
| `REDIS_URL` | `""` | URL de Redis (pendiente para AsyncRedisSaver) |

---

## Notas Importantes

1. **`session_id` es entero** — no string. Debe coincidir con el ID de sesión del orquestador.

2. **`customer_contact` solo acepta email** — la validación rechaza teléfonos. El agente pedirá el correo si el usuario proporciona un número.

3. **Google Meet es real** — el enlace de videollamada proviene de `ws_calendario.php` (CREAR_EVENTO). El agente no lo inventa.

4. **Sin historial manual** — no es necesario (ni posible) enviar historial en el request. La memoria es automática por `session_id`.

5. **Multiempresa** — el agente carga horarios, catálogo y contexto de negocio por `id_empresa`. Cada empresa puede tener configuración diferente.

6. **Modificar/cancelar citas** — no implementado. El agente responde: *"Te contactaremos para gestionarlo."*

7. **SUGERIR_HORARIOS solo funciona para hoy y mañana** — la API `ws_agendar_reunion.php` solo devuelve sugerencias para estos dos días. Para otras fechas, el agente pide al usuario que indique una hora y la verifica con CONSULTAR_DISPONIBILIDAD.

8. **Imágenes (Vision)** — el agente detecta URLs de imágenes (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`) en el mensaje y las procesa vía OpenAI Vision. Máximo 10 imágenes por mensaje.

---

## Próximos Pasos

- [ARCHITECTURE.md](ARCHITECTURE.md) — cómo funciona internamente el agente
- [DEPLOYMENT.md](DEPLOYMENT.md) — guía de despliegue en producción
