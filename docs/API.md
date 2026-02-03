# API Reference - Agent Citas

Referencia de la API del agente especializado en citas y reuniones.

## Descripción General

El agente se comunica mediante **MCP (Model Context Protocol)** sobre HTTP. Expone una única herramienta que maneja toda la lógica de conversación y citas de forma autónoma.

**Protocolo**: MCP
**Transporte**: HTTP
**Puerto**: 8003 (configurable)
**Endpoint base**: `http://localhost:8003`

## Endpoint Principal

### Tool: `chat`

Procesa mensajes del usuario y gestiona el flujo completo de citas/reuniones.

El agente internamente usa dos herramientas propias:
- `check_availability` - Consulta horarios disponibles
- `create_booking` - Crea citas/eventos con validación

**El orquestador NO llama directamente a estas herramientas**, solo usa `chat`.

---

## Request

### Formato MCP

```json
{
  "tool": "chat",
  "arguments": {
    "message": "Quiero agendar una cita para mañana a las 2pm",
    "session_id": "user-12345-abc",
    "context": {
      "config": {
        "id_empresa": 123,
        "personalidad": "amable y profesional",
        "duracion_cita_minutos": 60,
        "slots": 60,
        "agendar_usuario": 1,
        "id_usuario": 1,
        "correo_usuario": "vendedor@empresa.com",
        "agendar_sucursal": 0
      }
    }
  }
}
```

### Parámetros

| Parámetro | Tipo | Requerido | Default | Descripción |
|-----------|------|-----------|---------|-------------|
| `message` | string | ✅ Sí | - | Mensaje del usuario que quiere agendar una cita |
| `session_id` | string | ✅ Sí | - | ID único de sesión para memoria conversacional |
| `context` | object | ✅ Sí | - | Contexto de configuración |

#### Parámetros de `context.config`

| Parámetro | Tipo | Requerido | Default | Descripción |
|-----------|------|-----------|---------|-------------|
| `id_empresa` | integer | ✅ Sí | - | ID de la empresa en el sistema |
| `personalidad` | string | ❌ No | `"amable, profesional y eficiente"` | Personalidad del agente |
| `duracion_cita_minutos` | integer | ❌ No | `60` | Duración de la cita en minutos |
| `slots` | integer | ❌ No | `60` | Cantidad de slots disponibles |
| `agendar_usuario` | boolean/integer | ❌ No | `1` | Flag para agendar por usuario (true=1, false=0) |
| `id_usuario` | integer | ❌ No | `1` | ID del vendedor/usuario en el sistema |
| `correo_usuario` | string | ❌ No | `""` | Email del vendedor (para invitaciones de calendario) |
| `agendar_sucursal` | integer | ❌ No | `0` | Flag para agendar por sucursal (0=no, 1=sí) |

**Nota importante:** El orquestador no envía `id_prospecto`. El agente usa `session_id` como identificador del prospecto internamente.

---

## Response

### Formato MCP

```json
{
  "result": "¡Perfecto! Para confirmar tu cita necesito algunos datos. ¿Cuál es tu nombre completo?"
}
```

### Estructura

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `result` | string | Respuesta del agente en lenguaje natural |

El agente mantiene el contexto de la conversación usando `session_id`, por lo que las respuestas son contextuales.

---

## Ejemplos de Uso

### Ejemplo 1: Inicio de conversación

**Request:**
```json
{
  "tool": "chat",
  "arguments": {
    "message": "Hola, quiero agendar una cita",
    "session_id": "sess-001",
    "context": {
      "config": {
        "id_empresa": 123
      }
    }
  }
}
```

**Response:**
```json
{
  "result": "¡Hola! Estaré encantado de ayudarte con tu cita. ¿Qué tipo de reunión te gustaría agendar?"
}
```

---

### Ejemplo 2: Usuario da información completa

**Request:**
```json
{
  "tool": "chat",
  "arguments": {
    "message": "Necesito corte de cabello para mañana a las 3pm, soy Juan Pérez, mi teléfono es 987654321",
    "session_id": "sess-002",
    "context": {
      "config": {
        "id_empresa": 123,
        "personalidad": "amigable y rápido"
      }
    }
  }
}
```

**Response:**
```json
{
  "result": "Evento agregado correctamente\n\n**Detalles:**\n• Servicio: Corte de cabello\n• Fecha: 2026-01-29\n• Hora: 03:00 PM\n• Nombre: Juan Pérez\n\nLa reunión será por videollamada. Enlace: https://meet.google.com/xxx-xxxx-xxx\n\n¡Te esperamos!"
}
```

---

### Ejemplo 3: Consulta de disponibilidad

**Request:**
```json
{
  "tool": "chat",
  "arguments": {
    "message": "¿Tienen horarios disponibles el viernes?",
    "session_id": "sess-003",
    "context": {
      "config": {
        "id_empresa": 123
      }
    }
  }
}
```

**Response:**
```json
{
  "result": "Horarios disponibles:\n• Viernes: 09:00 AM - 06:00 PM\n\n¿A qué hora te gustaría agendar?"
}
```

---

### Ejemplo 4: Flujo conversacional (múltiples mensajes)

**Request 1:**
```json
{
  "message": "Quiero agendar una cita",
  "session_id": "sess-004",
  "context": {"config": {"id_empresa": 123}}
}
```

**Response 1:**
```json
{"result": "¿Qué tipo de reunión te gustaría agendar?"}
```

**Request 2 (misma sesión):**
```json
{
  "message": "Manicure",
  "session_id": "sess-004",
  "context": {"config": {"id_empresa": 123}}
}
```

**Response 2:**
```json
{"result": "Perfecto, manicure. ¿Para qué fecha necesitas la cita?"}
```

**Request 3 (misma sesión):**
```json
{
  "message": "Para el sábado a las 10am",
  "session_id": "sess-004",
  "context": {"config": {"id_empresa": 123}}
}
```

**Response 3:**
```json
{"result": "Genial. Para confirmar, necesito tu nombre y teléfono o email."}
```

---

## Errores

### Error: Context inválido

**Causa:** No se envió `id_empresa` o `session_id`

**Response:**
```json
{
  "result": "Error de configuración: Context missing required keys in config: ['id_empresa']"
}
```

**Solución:** Asegurarse de enviar `context.config.id_empresa`

---

### Error: Mensaje vacío

**Causa:** `message` está vacío o solo contiene espacios

**Response:**
```json
{
  "result": "No recibí tu mensaje. ¿Podrías repetirlo?"
}
```

**Solución:** Enviar un mensaje con contenido

---

### Error: Datos de cita inválidos

**Causa:** El usuario proporcionó datos que no cumplen validaciones (email inválido, teléfono mal formateado, fecha pasada, etc.)

**Response:**
```json
{
  "result": "Datos inválidos: Contacto debe ser un email válido o un teléfono peruano válido (9XXXXXXXX). Recibido: 123\n\nPor favor verifica la información."
}
```

**Solución:** El agente pedirá nuevamente los datos correctos

---

### Error: Horario no disponible

**Causa:** El horario seleccionado ya está ocupado o está fuera del rango de atención

**Response:**
```json
{
  "result": "La hora seleccionada es después del horario de atención. El horario del lunes es de 09:00 AM a 06:00 PM.\n\nPor favor elige otra fecha u hora."
}
```

**Solución:** El agente sugerirá horarios alternativos

---

## Métricas

### Endpoint de métricas

```
GET http://localhost:8003/metrics
```

**Formato:** Prometheus

**Métricas principales:**

```prometheus
# Total de mensajes recibidos
agent_reservas_chat_requests_total{session_id="sess-001"} 5

# Citas exitosas
agent_reservas_booking_success_total 42

# Citas fallidas
agent_reservas_booking_failed_total{reason="validation_error"} 3

# Latencia de respuesta (percentiles)
agent_reservas_chat_response_duration_seconds_bucket{le="1.0"} 150
agent_reservas_chat_response_duration_seconds_bucket{le="5.0"} 280
```

Ver todas las métricas disponibles en el endpoint `/metrics`.

---

## Notas Importantes

1. **Session ID único**: Cada usuario debe tener un `session_id` único para mantener contexto de conversación.

2. **Memoria automática**: El agente recuerda la conversación usando `session_id`. No es necesario enviar historial manualmente.

3. **Validación multicapa**: El agente valida automáticamente:
   - Formato de datos (Pydantic)
   - Horarios disponibles (contra API)
   - Disponibilidad real (slots ocupados)

4. **Confirmación**: La confirmación y el enlace de Google Meet vienen de la API externa (`ws_calendario.php` con `CREAR_EVENTO`). NO son inventados por el LLM.

5. **Personalidad configurable**: Se puede ajustar por empresa enviando `context.config.personalidad`.

6. **Timeout**: Las llamadas al agente tienen timeout de 90s (OpenAI) + 10s (APIs externas).

---

## Integración

### Python

```python
import httpx

async def agendar_cita(mensaje: str, session_id: str, id_empresa: int):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8003/tools/call",
            json={
                "tool": "chat",
                "arguments": {
                    "message": mensaje,
                    "session_id": session_id,
                    "context": {
                        "config": {
                            "id_empresa": id_empresa
                        }
                    }
                }
            }
        )
        data = response.json()
        return data["result"]
```

### JavaScript

```javascript
async function agendarCita(mensaje, sessionId, idEmpresa) {
  const response = await fetch('http://localhost:8003/tools/call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tool: 'chat',
      arguments: {
        message: mensaje,
        session_id: sessionId,
        context: {
          config: {
            id_empresa: idEmpresa
          }
        }
      }
    })
  });

  const data = await response.json();
  return data.result;
}
```

---

## Próximos Pasos

- Ver [ARCHITECTURE.md](ARCHITECTURE.md) para entender cómo funciona internamente
- Ver [DEPLOYMENT.md](DEPLOYMENT.md) para desplegar el agente
