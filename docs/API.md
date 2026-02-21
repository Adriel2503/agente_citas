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
| `message` | string | ✅ Sí | Mensaje del usuario. Puede contener URLs de imágenes (Vision) |
| `session_id` | **integer** | ✅ Sí | ID de sesión numérico. Usado como `thread_id` del checkpointer y como `id_prospecto` |
| `context` | object | ❌ No | Contexto de configuración del bot. Si se omite, se usa `{}` |

##### Campos de `context.config`

| Campo | Tipo | Requerido | Default | Descripción |
|-------|------|-----------|---------|-------------|
| `id_empresa` | integer | ✅ Sí | — | ID de la empresa. Determina horarios, contexto y catálogo |
| `usuario_id` | integer | ❌ No | `1` | ID del vendedor para CREAR_EVENTO en ws_calendario |
| `correo_usuario` | string | ❌ No | `""` | Email del vendedor (incluido en invitación de Google Calendar) |
| `personalidad` | string | ❌ No | `"amable, profesional y eficiente"` | Tono del agente |
| `nombre_bot` | string | ❌ No | `"Asistente"` | Nombre con el que el agente se presenta |
| `frase_saludo` | string | ❌ No | `"¡Hola! ¿En qué puedo ayudarte?"` | Saludo inicial |
| `frase_des` | string | ❌ No | `"¡Gracias por contactarnos!"` | Frase de despedida |
| `frase_no_sabe` | string | ❌ No | `"No tengo esa información a mano..."` | Frase cuando el agente no sabe algo |
| `duracion_cita_minutos` | integer | ❌ No | `60` | Duración de la cita (afecta validación de horario y CREAR_EVENTO) |
| `slots` | integer | ❌ No | `60` | Slots de disponibilidad para CONSULTAR_DISPONIBILIDAD y SUGERIR_HORARIOS |
| `agendar_usuario` | boolean/integer | ❌ No | `1` | `1` = asignar vendedor automáticamente al crear evento |
| `agendar_sucursal` | boolean/integer | ❌ No | `0` | `1` = agendar por sucursal |

> **Nota:** El campo se llama `usuario_id` (no `id_usuario`). El `session_id` del request se usa internamente como `id_prospecto` al crear el evento.

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

```json
{
  "reply": "¡Perfecto! Mañana a las 2:00 PM está disponible. Para confirmar, necesito tu nombre completo y correo."
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `reply` | string | Respuesta del agente en lenguaje natural |

> El agente siempre retorna HTTP 200, incluso en casos de error. Los errores de configuración o timeout se devuelven como texto en el campo `reply`.

---

### `GET /health` — Health check

```http
GET /health
```

```json
{
  "status": "ok",
  "agent": "citas",
  "version": "2.0.0"
}
```

---

### `GET /metrics` — Métricas Prometheus

```http
GET /metrics
```

Devuelve métricas en formato Prometheus text. Ver sección [Métricas](#métricas) para detalle.

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
  "reply": "¡Hola! Soy Mara. ¿Para qué fecha te gustaría la reunión?"
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
  "reply": "Mañana a las 3:00 PM está disponible. Para confirmar la reunión, necesito tu nombre completo y correo electrónico."
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
  "reply": "Evento agregado correctamente.\n\n*Detalles:*\n• Fecha: 2026-02-22\n• Hora: 3:00 PM\n• Nombre: Juan Pérez\n\nLa reunión será por videollamada. Enlace: https://meet.google.com/abc-defg-hij\n\n¡Te esperamos!"
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
  "reply": "Horarios disponibles para hoy:\n\n1. Hoy a las 10:00 AM\n2. Hoy a las 11:00 AM\n3. Hoy a las 03:00 PM\n\n¿Cuál te viene mejor?"
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
  "reply": "El 2026-02-27 a las 4:00 PM está disponible. ¿Confirmamos la cita? Necesito tu nombre completo y correo."
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
  "reply": "Encontré 1 resultado para 'consultoría estratégica':\n\n*Consultoría Estratégica*\n- Precio: S/. 350.00 por sesión\n- Categoría: Consultoría\n- Descripción: Sesión personalizada de 60 min para definir objetivos...\n\n¿Te gustaría agendar una sesión?"
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
  "reply": "¡Hola! Soy Alex, tu asistente de citas. ¿Para qué fecha y hora te gustaría agendar tu reunión?"
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
  "reply": "Error de configuración: Context missing required keys in config: ['id_empresa']"
}
```

---

### Error: Mensaje vacío

**Causa:** `message` es vacío o solo contiene espacios.

**Response:**
```json
{
  "reply": "No recibí tu mensaje. ¿Podrías repetirlo?"
}
```

---

### Error: Timeout

**Causa:** El procesamiento superó `CHAT_TIMEOUT` (default 120s).

**Response:**
```json
{
  "reply": "La solicitud tardó más de 120s. Por favor, intenta de nuevo."
}
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

### Error interno del agente

**Causa:** Fallo inesperado en el procesamiento.

**Response:**
```json
{
  "reply": "Error procesando mensaje: <detalle>. Por favor intenta nuevamente."
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

### Métricas principales

```prometheus
# Total de mensajes recibidos por empresa
agent_citas_chat_requests_total{empresa_id="123"} 150

# Citas exitosas
agent_citas_booking_success_total 42

# Citas fallidas por motivo
agent_citas_booking_failed_total{reason="timeout"} 2
agent_citas_booking_failed_total{reason="api_error"} 1
agent_citas_booking_failed_total{reason="invalid_datetime"} 3

# Llamadas a tools
agent_citas_tool_calls_total{tool_name="check_availability"} 98
agent_citas_tool_calls_total{tool_name="create_booking"} 45
agent_citas_tool_calls_total{tool_name="search_productos_servicios"} 27

# Latencia total de respuesta (segundos)
agent_citas_chat_response_duration_seconds_bucket{le="1.0"} 50
agent_citas_chat_response_duration_seconds_bucket{le="5.0"} 130
agent_citas_chat_response_duration_seconds_bucket{le="10.0"} 148

# Latencia de llamadas al LLM
agent_citas_llm_call_duration_seconds_bucket{le="5.0"} 120

# Entradas en cache de horarios
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
) -> str:
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
        return response.json()["reply"]
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
    Reply string `json:"reply"`
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

## Comportamiento del Agente

### Lógica de disponibilidad

El agente aplica estas reglas de forma autónoma:

| Mensaje del usuario | Acción del agente |
|--------------------|--------------------|
| Solo fecha (`"el viernes"`) | Pregunta la hora. No llama ninguna tool |
| Fecha + hora (`"viernes a las 3pm"`) | Llama `check_availability(date, time)` → verifica slot exacto |
| Pregunta explícita de horarios (`"¿qué horarios tienen hoy?"`) | Llama `check_availability(date)` sin `time` → sugiere horarios disponibles |
| Pregunta general de productos (`"¿qué servicios ofrecen?"`) | Responde con la lista del system prompt |
| Pregunta específica (`"¿cuánto cuesta X?"`) | Llama `search_productos_servicios(busqueda)` |
| Tiene fecha + hora + nombre + email | Pide confirmación, luego llama `create_booking` |

### Formato de respuesta (WhatsApp)

El system prompt instruye al agente a usar formato compatible con WhatsApp:
- Negrita: `*texto*` (un solo asterisco)
- URLs: solo la URL, sin formato Markdown `[texto](url)`
- Sin encabezados `##`, sin guiones de lista

### Memoria conversacional

La memoria es automática via `InMemorySaver` de LangGraph. El agente recuerda **toda la conversación** del mismo `session_id` sin necesidad de enviar historial. Si el servidor se reinicia, la memoria se pierde.

### Timeout por capas

| Capa | Timeout | Variable |
|------|---------|----------|
| Request total | 120s | `CHAT_TIMEOUT` |
| Llamada al LLM | 60s | `OPENAI_TIMEOUT` |
| APIs externas MaravIA | 10s | `API_TIMEOUT` |

---

## Notas Importantes

1. **`session_id` es entero** — no string. Debe coincidir con el ID de sesión del orquestador.

2. **`customer_contact` solo acepta email** — la validación rechaza teléfonos. El agente pedirá el correo si el usuario proporciona un número.

3. **Google Meet es real** — el enlace de videollamada proviene de `ws_calendario.php` (CREAR_EVENTO). El agente no lo inventa.

4. **Sin historial manual** — no es necesario (ni posible) enviar historial en el request. La memoria es automática por `session_id`.

5. **Multiempresa** — el agente carga horarios, catálogo y contexto de negocio por `id_empresa`. Cada empresa puede tener configuración diferente.

6. **Modificar/cancelar citas** — no implementado. El agente responde: *"Te contactaremos para gestionarlo."*

---

## Próximos Pasos

- [ARCHITECTURE.md](ARCHITECTURE.md) — cómo funciona internamente el agente
- [DEPLOYMENT.md](DEPLOYMENT.md) — guía de despliegue en producción
