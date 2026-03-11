# Agent Citas — MaravIA

Agente conversacional de IA especializado en la gestión de citas y reuniones comerciales. Actúa como un **closer digital 24/7** que guía a prospectos de WhatsApp hasta confirmar una reunión de venta, integrando validación real de horarios, creación de eventos en Google Calendar y soporte multiempresa.

**Versión:** `2.5.0` — FastAPI HTTP + LangChain 1.2+ API moderna
**Modelo:** `gpt-4o-mini` (configurable vía `OPENAI_MODEL`)
**Puerto:** `8002`

---

## Tabla de contenidos

1. [Visión general](#1-visión-general)
2. [Arquitectura del sistema](#2-arquitectura-del-sistema)
3. [Ciclo de vida de un request](#3-ciclo-de-vida-de-un-request)
4. [El agente LangGraph](#4-el-agente-langgraph)
5. [Tools del agente](#5-tools-del-agente)
6. [Validación de horarios (ScheduleValidator)](#6-validación-de-horarios-schedulevalidator)
7. [Construcción del system prompt](#7-construcción-del-system-prompt)
8. [Estrategia de caché](#8-estrategia-de-caché)
9. [Circuit breakers](#9-circuit-breakers)
10. [Modelo de concurrencia](#10-modelo-de-concurrencia)
11. [Observabilidad](#11-observabilidad)
12. [API Reference](#12-api-reference)
13. [Variables de entorno](#13-variables-de-entorno)
14. [Integraciones externas (APIs MaravIA)](#14-integraciones-externas-apis-maravia)
15. [Estructura del proyecto](#15-estructura-del-proyecto)
16. [Stack tecnológico](#16-stack-tecnológico)
17. [Inicio rápido](#17-inicio-rápido)
18. [Limitaciones conocidas](#18-limitaciones-conocidas)
19. [Mejoras pendientes](#19-mejoras-pendientes)

---

## 1. Visión general

El agente de citas forma parte de la plataforma **MaravIA**, un sistema multi-tenant de IA conversacional para empresas. La plataforma enruta mensajes de WhatsApp (vía N8N) a través de un **gateway Go** que los clasifica por `modalidad` y los deriva al agente especializado correspondiente.

```
WhatsApp → N8N → Gateway Go → agent_citas (POST /api/chat)
```

### Responsabilidades del agente

- Mantener una conversación natural con el prospecto para agendar una reunión.
- Consultar disponibilidad real de horarios (por empresa y usuario/sucursal).
- Validar que la fecha/hora solicitada esté dentro del horario de atención de la empresa.
- Crear el evento en `ws_calendario.php` con integración opcional a Google Calendar / Meet.
- Responder preguntas sobre productos y servicios del catálogo de la empresa.
- Recordar el historial de la conversación de forma automática (memoria por sesión).

### Alcance de este servicio

El agente **no** modifica ni cancela citas (operación no implementada). No gestiona pagos ni datos personales más allá de nombre y email para la invitación al evento.

---

## 2. Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GATEWAY Go (puerto 8080)                     │
│  Recibe JSON de N8N, enruta por modalidad="citas" → POST /api/chat  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ {message, session_id, context.config}
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI — main.py (puerto 8002)                  │
│                                                                     │
│  POST /api/chat ──► asyncio.wait_for(process_cita_message, 120s)    │
│  GET  /health   ──► verifica API key + estado de circuit breakers   │
│  GET  /metrics  ──► Prometheus exposition format                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   agent/agent.py — process_cita_message()           │
│                                                                     │
│  1. Session lock (asyncio.Lock por session_id)                      │
│  2. Validate context → config_data (setdefault personalidad)        │
│  3. _get_agent(config) ← TTLCache por id_empresa                    │
│     └─ si miss: build_citas_system_prompt() [asyncio.gather x4]     │
│  4. agent.ainvoke(messages, thread_id=session_id, context=ctx)      │
└────────┬───────────────────────────────────────────┬────────────────┘
         │ InMemorySaver (LangGraph checkpointer)    │ AgentContext
         │ thread_id = str(session_id)               │ (inyectado a tools)
         ▼                                           ▼
┌─────────────────────┐          ┌────────────────────────────────────┐
│   LLM gpt-4o-mini   │          │           TOOLS (function calling) │
│   (LangChain 1.2+)  │◄────────►│                                    │
│   response_format=  │          │ check_availability(date, time?)    │
│   CitaStructured    │          │   └─ ScheduleValidator             │
│   Response          │          │       ├─ _fetch_horario() [API]    │
└─────────────────────┘          │       └─ SUGERIR_HORARIOS /        │
                                 │          CONSULTAR_DISPONIBILIDAD  │
                                 │                                    │
                                 │ create_booking(date, time,         │
                                 │   customer_name, customer_contact) │
                                 │   ├─ validate_booking_data()       │
                                 │   ├─ ScheduleValidator.validate()  │
                                 │   │   (12 pasos)                   │
                                 │   └─ confirm_booking()             │
                                 │       └─ ws_calendario (CREAR_EVT) │
                                 │                                    │
                                 │ search_productos_servicios(query)  │
                                 │   └─ buscar_productos_servicios()  │
                                 │       └─ ws_informacion_ia         │
                                 └────────────────────────────────────┘

APIs externas (httpx async, retries, circuit breaker):
  ws_informacion_ia.php      → OBTENER_HORARIO_REUNIONES
                               OBTENER_CONTEXTO_NEGOCIO
                               BUSCAR_PRODUCTOS_SERVICIOS
  ws_agendar_reunion.php     → SUGERIR_HORARIOS
                               CONSULTAR_DISPONIBILIDAD
  ws_calendario.php          → CREAR_EVENTO
  ws_preguntas_frecuentes.php → (sin codOpe, by id_chatbot)
```

---

## 3. Ciclo de vida de un request

### Paso 1 — Recepción HTTP

`FastAPI` recibe `POST /api/chat` con el body validado por Pydantic:

```json
{
  "message": "Quiero agendar para el viernes a las 3pm",
  "session_id": 5191234567890,
  "context": {
    "config": {
      "id_empresa": 42,
      "usuario_id": 7,
      "correo_usuario": "vendedor@empresa.com",
      "personalidad": "amable y directa",
      "duracion_cita_minutos": 60,
      "slots": 60,
      "agendar_usuario": 1,
      "agendar_sucursal": 0
    }
  }
}
```

El `session_id` es el número de WhatsApp del prospecto (`5191234567890`), único y permanente por contacto.

### Paso 2 — Validación y preparación de contexto

```
FastAPI → process_cita_message()
  ├─ Valida que context.config contenga id_empresa (requerido)
  ├─ Aplica default de personalidad en config_data (setdefault) y construye AgentContext
  └─ AgentContext (dataclass) se inyecta a las tools:
       id_empresa, usuario_id, correo_usuario, id_prospecto=session_id,
       duracion_cita_minutos, slots, agendar_usuario, agendar_sucursal
```

### Paso 3 — Session lock

Antes de tocar el checkpointer (InMemorySaver), se adquiere un `asyncio.Lock` keyed por `session_id`. Esto garantiza que si el mismo usuario envía dos mensajes en rápida sucesión (doble-clic, reintento), el segundo espera a que termine el primero. Evita condiciones de carrera sobre el mismo `thread_id` en LangGraph.

### Paso 4 — Obtención del agente compilado (TTLCache)

```python
cache_key = (id_empresa,)
agent = _agent_cache[cache_key]  # O lo crea si no existe
```

Si es un **cache miss** (primera request de esa empresa, o TTL expirado):
1. Se adquiere otro lock por `cache_key` (para evitar thundering herd entre múltiples sesiones de la misma empresa que llegan simultáneamente).
2. Se llama `build_citas_system_prompt()` que hace **4 llamadas HTTP en paralelo** (ver §7).
3. Se inicializa el modelo LLM con `init_chat_model()`.
4. Se compila el grafo LangGraph con `create_agent()`.
5. Se guarda en `_agent_cache` con TTL de `AGENT_CACHE_TTL_MINUTES` (default 60 min).

### Paso 5 — Invocación del agente

```python
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": message_content}]},
    config={"configurable": {"thread_id": str(session_id)}},
    context=agent_context,  # inyectado a todas las tools vía ToolRuntime
)
```

El agente LangGraph maneja el loop interno: LLM → (opcional) tool call → LLM → respuesta final.

### Paso 6 — Respuesta estructurada

El agente usa `response_format=CitaStructuredResponse`:
```python
class CitaStructuredResponse(BaseModel):
    reply: str       # Texto de respuesta al usuario
    url: str | None  # Enlace Google Meet (si aplica)
```

La respuesta se retorna como `{"reply": "...", "url": null}` al gateway Go.

---

## 4. El agente LangGraph

### Creación con LangChain 1.2+ API moderna

```python
agent = create_agent(
    model=model,                          # init_chat_model("openai:gpt-4o-mini")
    tools=AGENT_TOOLS,                    # [check_availability, create_booking, search_...]
    system_prompt=system_prompt,          # Template Jinja2 renderizado
    checkpointer=_checkpointer,           # InMemorySaver (→ AsyncRedisSaver en roadmap)
    response_format=CitaStructuredResponse,  # Structured output: reply + url
    middleware=[_message_window],         # Ventana de mensajes (trim_messages, no destructivo)
)
```

### Memoria conversacional

LangGraph usa `thread_id = str(session_id)` como identificador de conversación. Cada mensaje nuevo se acumula en el checkpointer junto con el historial anterior.

**Ventana de mensajes:** El middleware `_message_window` (vía `wrap_model_call` + `trim_messages`) limita a `MAX_MESSAGES_HISTORY` (default 20) los mensajes que ve el LLM en cada llamada. El checkpointer conserva el historial completo — solo se recorta lo que se envía al modelo.

**Limitación actual:** `InMemorySaver` no tiene TTL. Las conversaciones crecen indefinidamente en RAM. Ver §18.

### Runtime context injection (LangChain 1.2+ ToolRuntime)

Las tools reciben el `AgentContext` vía `ToolRuntime`:

```python
@tool
async def check_availability(date: str, time: Optional[str] = None, runtime: ToolRuntime = None) -> str:
    ctx = runtime.context  # AgentContext con id_empresa, slots, agendar_usuario, etc.
    id_empresa = ctx.id_empresa
```

Esto permite que las tools sean stateless (sin globals), testables en aislamiento, y que el mismo agente compilado sirva a múltiples empresas con configuraciones distintas en cada llamada.

### Soporte multimodal (Vision)

Si el mensaje del usuario contiene URLs de imágenes (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`), `_build_content()` las convierte a bloques `image_url` de OpenAI Vision. El LLM puede ver las imágenes. Límite: 10 imágenes por mensaje.

```
"Mira este catálogo https://cdn.empresa.com/producto.jpg, ¿cuánto cuesta?"
→ [{"type": "text", "text": "Mira este catálogo ..."}, {"type": "image_url", "image_url": {"url": "..."}}]
```

---

## 5. Tools del agente

Las tools son el puente entre el LLM y los sistemas externos. El LLM decide autónomamente cuándo y cuáles invocar basándose en el estado de la conversación.

Definidas en `tool/tools.py`. Exportadas como `AGENT_TOOLS = [check_availability, create_booking, search_productos_servicios]`.

### Tabla resumen: origen de cada parámetro

> **🤖 IA** = el LLM decide el valor basándose en la conversación.
> **🔧 Gateway** = viene de `context.config` enviado por el gateway Go (originado en N8N).
> **⚙️ Runtime** = inyectado automáticamente por LangChain vía `ToolRuntime` (el LLM no lo ve).

| Tool | Parámetro | Tipo | Origen | Ejemplo |
|------|-----------|------|--------|---------|
| `check_availability` | `date` | `str` | 🤖 IA | `"2026-02-28"` |
| | `time` | `str \| None` | 🤖 IA | `"3:00 PM"` o `None` |
| | `runtime.context` | `AgentContext` | ⚙️ Runtime | (inyectado) |
| `create_booking` | `date` | `str` | 🤖 IA | `"2026-02-28"` |
| | `time` | `str` | 🤖 IA | `"3:00 PM"` |
| | `customer_name` | `str` | 🤖 IA | `"Juan Pérez"` |
| | `customer_contact` | `str` | 🤖 IA | `"juan@ejemplo.com"` |
| | `runtime.context` | `AgentContext` | ⚙️ Runtime | (inyectado) |
| `search_productos_servicios` | `busqueda` | `str` | 🤖 IA | `"NovaX"` |
| | `runtime.context` | `AgentContext` | ⚙️ Runtime | (inyectado) |

### `AgentContext` — datos del gateway inyectados a todas las tools

```python
@dataclass
class AgentContext:
    id_empresa: int              # 🔧 Gateway (requerido)
    duracion_cita_minutos: int   # 🔧 Gateway (default: 60)
    slots: int                   # 🔧 Gateway (default: 60)
    agendar_usuario: int         # 🔧 Gateway (default: 1) — 1=asignar vendedor
    usuario_id: int              # 🔧 Gateway (default: 1) — ID del vendedor
    correo_usuario: str          # 🔧 Gateway (default: "") — email del vendedor
    agendar_sucursal: int        # 🔧 Gateway (default: 0)
    id_prospecto: int            # = session_id (número WhatsApp)
    session_id: int              # = session_id del request
```

Cada tool accede al contexto así:
```python
@tool
async def check_availability(date: str, time: str | None = None, runtime: ToolRuntime = None) -> str:
    ctx = runtime.context  # → AgentContext
    id_empresa = ctx.id_empresa
```

---

### `check_availability(date, time?)`

**Cuándo lo usa el LLM:** El cliente pregunta por disponibilidad sin haber dado todos los datos para agendar, o quiere verificar si un horario específico está libre.

**Parámetros que decide la IA:**

| Parámetro | Formato | Obligatorio | Cómo lo obtiene el LLM |
|-----------|---------|-------------|------------------------|
| `date` | `YYYY-MM-DD` | ✅ | Traduce "mañana", "el viernes", "15 de marzo" a ISO usando `fecha_iso` del prompt |
| `time` | `HH:MM AM/PM` | ❌ | Extrae de "a las 3pm" → `"3:00 PM"`. Si no hay hora, pasa `None` |

**Parámetros que saca del contexto (gateway):**

| Parámetro del contexto | Para qué se usa |
|------------------------|-----------------|
| `id_empresa` | Identificar la empresa en la API |
| `duracion_cita_minutos` | Calcular `fecha_fin` en CONSULTAR_DISPONIBILIDAD |
| `slots` | Pasar a la API (configuración de slots de la empresa) |
| `agendar_usuario` | Pasar a la API (filtrar por vendedor o no) |
| `agendar_sucursal` | Pasar a la API (filtrar por sucursal o no) |

**Lógica interna:**

```
Si viene time (hora concreta):
  └─ CONSULTAR_DISPONIBILIDAD → ¿está libre ese slot exacto?
      ├─ Sí → "El {fecha} a las {hora} está disponible. ¿Confirmamos?"
      └─ No → "Ese horario no está disponible. ¿Te sugiero otros?"

Si NO viene time (solo fecha o pregunta general):
  ├─ Si la fecha es hoy o mañana → SUGERIR_HORARIOS (devuelve slots reales con disponibilidad)
  ├─ Si la fecha es otro día → "Indica una hora y la verifico" (SUGERIR_HORARIOS solo cubre hoy/mañana)
  └─ Fallback si API falla → "Indica una fecha y hora y la verifico"
```

**APIs que llama (payloads exactos):**

**Caso 1 — Con hora → `CONSULTAR_DISPONIBILIDAD`:**
```json
{
  "codOpe": "CONSULTAR_DISPONIBILIDAD",
  "id_empresa": 42,
  "fecha_inicio": "2026-02-28 15:00:00",
  "fecha_fin": "2026-02-28 16:00:00",
  "slots": 60,
  "agendar_usuario": 1,
  "agendar_sucursal": 0
}
```
→ Respuesta: `{"success": true, "disponible": true}` o `{"success": true, "disponible": false}`

**Caso 2 — Sin hora → `SUGERIR_HORARIOS`:**
```json
{
  "codOpe": "SUGERIR_HORARIOS",
  "id_empresa": 42,
  "duracion_minutos": 60,
  "slots": 60,
  "agendar_usuario": 1,
  "agendar_sucursal": 0
}
```
→ Respuesta:
```json
{
  "success": true,
  "mensaje": "Horarios disponibles encontrados",
  "total": 5,
  "sugerencias": [
    {"dia": "hoy", "hora_legible": "3:00 PM", "disponible": true, "fecha_inicio": "2026-02-26 15:00:00"},
    {"dia": "mañana", "hora_legible": "10:00 AM", "disponible": true, "fecha_inicio": "2026-02-27 10:00:00"}
  ]
}
```

**Endpoint:** `ws_agendar_reunion.php` (`API_AGENDAR_REUNION_URL`)
**Circuit breaker:** `agendar_reunion_cb` (keyed by `id_empresa`)

---

### `create_booking(date, time, customer_name, customer_contact)`

**Cuándo lo usa el LLM:** Tiene los 4 datos requeridos: fecha, hora, nombre completo y email del cliente.

**Parámetros que decide la IA:**

| Parámetro | Formato | Validación | Cómo lo obtiene el LLM |
|-----------|---------|------------|------------------------|
| `date` | `YYYY-MM-DD` | Pydantic: no pasado, formato ISO | De la conversación previa con el cliente |
| `time` | `HH:MM AM/PM` | Pydantic: formato 12h o 24h | De la conversación previa con el cliente |
| `customer_name` | `str` | ≥2 chars, sin números, sin caracteres peligrosos | El cliente dice "Soy Juan Pérez" |
| `customer_contact` | `email` | Regex RFC 5322 simplificado | El cliente da su email |

**Parámetros que saca del contexto (gateway):**

| Parámetro del contexto | Campo en payload CREAR_EVENTO | Cómo llega |
|------------------------|-------------------------------|------------|
| `usuario_id` | `usuario_id` | `context.config.usuario_id` del gateway |
| `session_id` | `id_prospecto` | `session_id` del request (nro WhatsApp) |
| `correo_usuario` | `correo_usuario` | `context.config.correo_usuario` del gateway |
| `agendar_usuario` | `agendar_usuario` | `context.config.agendar_usuario` del gateway |
| `duracion_cita_minutos` | Cálculo de `fecha_fin` | `context.config.duracion_cita_minutos` del gateway |

**Parámetros calculados por el código (ni IA ni gateway):**

| Campo en payload | Cómo se calcula |
|-----------------|-----------------|
| `titulo` | `f"Reunion para el usuario: {customer_name}"` — construido por código, no por LLM |
| `fecha_inicio` | `date + _parse_time_to_24h(time)` → `"2026-02-28 15:00:00"` |
| `fecha_fin` | `fecha_inicio + duracion_cita_minutos` → `"2026-02-28 16:00:00"` |
| `correo_cliente` | `customer_contact` (viene de la IA, pasa directo) |

**Pipeline de 3 fases:**

```
Fase 1 — Validación de datos (Pydantic + regex en tool/validation.py)
  ├─ date: formato YYYY-MM-DD, no en el pasado
  ├─ time: HH:MM AM/PM o HH:MM 24h
  ├─ customer_name: ≥2 chars, sin números, solo letras/espacios/acentos
  └─ customer_contact: email válido (RFC 5322 simplificado)

Fase 2 — Validación de horario (ScheduleValidator.validate, 12 pasos)
  ├─ Parsea fecha y hora
  ├─ Verifica que no sea en el pasado (zona horaria Lima/TIMEZONE)
  ├─ Obtiene horario de la empresa (get_horario, TTLCache)
  ├─ Verifica que ese día de la semana tenga atención
  ├─ Verifica rango de horario del día (ej: 09:00-18:00)
  ├─ Verifica que la cita + duración no exceda el cierre
  ├─ Verifica horarios bloqueados (bloqueos específicos)
  └─ CONSULTAR_DISPONIBILIDAD → ¿está libre ese slot?

Fase 3 — Creación del evento (confirm_booking → ws_calendario.php)
  └─ CREAR_EVENTO
      ├─ Éxito + Google Meet link → respuesta con enlace
      ├─ Éxito sin Meet → "Cita confirmada. Te contactaremos con detalles"
      └─ Fallo → mensaje de error del API
```

**Payload exacto enviado a `CREAR_EVENTO`:**

```json
{
  "codOpe": "CREAR_EVENTO",
  "usuario_id": 7,
  "id_prospecto": 5191234567890,
  "titulo": "Reunion para el usuario: Juan Pérez",
  "fecha_inicio": "2026-02-28 15:00:00",
  "fecha_fin": "2026-02-28 16:00:00",
  "correo_cliente": "juan@ejemplo.com",
  "correo_usuario": "vendedor@empresa.com",
  "agendar_usuario": 1
}
```

→ Respuesta exitosa:
```json
{
  "success": true,
  "message": "Evento agregado correctamente",
  "google_meet_link": "https://meet.google.com/abc-defg-hij",
  "google_calendar_synced": true
}
```

→ Respuesta sin Google Calendar:
```json
{
  "success": true,
  "message": "Evento agregado correctamente",
  "google_calendar_synced": false
}
```

**Endpoint:** `ws_calendario.php` (`API_CALENDAR_URL`)
**Circuit breaker:** `calendario_cb` (key fija `"global"`)

**Nota de diseño:** El campo `titulo` lo construye el código, no el LLM. Esto evita que el LLM inyecte texto arbitrario en el calendario de la empresa. `confirm_booking` usa `client.post()` directo (sin retry) porque CREAR_EVENTO no es idempotente — un retry podría duplicar el evento.

---

### `search_productos_servicios(busqueda)`

**Cuándo lo usa el LLM:** El cliente pregunta por precio, descripción o detalles de un producto/servicio específico que no está en el system prompt.

El system prompt ya incluye la **lista de nombres** de productos y servicios (cargada al crear el agente). Esta tool se usa para búsqueda en profundidad cuando el cliente quiere detalles específicos.

**Parámetros que decide la IA:**

| Parámetro | Formato | Cómo lo obtiene el LLM |
|-----------|---------|------------------------|
| `busqueda` | `str` (texto libre) | El cliente dice "¿cuánto cuesta NovaX?" → `"NovaX"` |

**Parámetros que saca del contexto (gateway):**

| Parámetro del contexto | Para qué se usa |
|------------------------|-----------------|
| `id_empresa` | Filtrar productos/servicios por empresa |

**Payload exacto enviado a `BUSCAR_PRODUCTOS_SERVICIOS_CITAS`:**

```json
{
  "codOpe": "BUSCAR_PRODUCTOS_SERVICIOS_CITAS",
  "id_empresa": 42,
  "busqueda": "NovaX",
  "limite": 10
}
```

→ Respuesta:
```json
{
  "success": true,
  "productos": [
    {
      "nombre": "NovaX Pro",
      "precio_unitario": 99.90,
      "nombre_categoria": "Software",
      "descripcion": "<p>Plataforma de gestión...</p>",
      "nombre_tipo_producto": "Producto",
      "nombre_unidad": "licencia"
    }
  ]
}
```

**Formato de respuesta al LLM** (generado por `format_productos_para_respuesta`):
```
### NovaX Pro
- Precio: S/. 99.90 por licencia
- Categoría: Software
- Descripción: Plataforma de gestión...
```

Para servicios (`nombre_tipo_producto: "Servicio"`), el formato omite la unidad:
```
### Consultoría Empresarial
- Precio: S/. 250.00
- Categoría: Asesoría
- Descripción: Sesión de consultoría personalizada...
```

**Endpoint:** `ws_informacion_ia.php` (`API_INFORMACION_URL`)
**Circuit breaker:** `informacion_cb` (keyed by `id_empresa`)
**Cache:** TTLCache 15 min por `(id_empresa, busqueda.lower())` — máx 2000 entradas

---

## 6. Validación de horarios (ScheduleValidator)

`ScheduleValidator.validate()` implementa un pipeline de **12 verificaciones secuenciales**. La validación se interrumpe en el primer fallo y devuelve un mensaje de error legible para el LLM.

| Paso | Verificación | Fuente de datos |
|------|-------------|-----------------|
| 1 | Parseo de fecha (`YYYY-MM-DD`) | Entrada del LLM |
| 2 | Parseo de hora (`HH:MM AM/PM` o `HH:MM`) | Entrada del LLM |
| 3 | Combinar fecha + hora en `datetime` | — |
| 4 | ¿La fecha/hora ya pasó? (zona horaria `TIMEZONE`) | `datetime.now(ZoneInfo)` |
| 5 | Obtener horario de la empresa | `_fetch_horario()` (directo a API, sin cache) |
| 6 | ¿Hay horario para ese día de la semana? | `horario_reuniones[reunion_lunes]` etc. |
| 7 | ¿El día está marcado como cerrado/no disponible? | `"NO DISPONIBLE"`, `"CERRADO"`, etc. |
| 8 | Parsear rango de horario del día (`"09:00-18:00"`) | `horario_reuniones` |
| 9 | ¿La hora está dentro del horario de inicio? | Comparación `datetime.time` |
| 10 | ¿La hora está dentro del horario de cierre? | Comparación `datetime.time` |
| 11 | ¿La cita + duración excede el cierre? | `hora_cita + duracion_minutos <= hora_cierre` |
| 12 | ¿El slot está bloqueado? + CONSULTAR_DISPONIBILIDAD | `horarios_bloqueados` + `ws_agendar_reunion` |

**Degradación graceful:** Si la API de disponibilidad (paso 12) falla por timeout o error HTTP, el validador retorna `valid=True`. La cita se crea igualmente. Esto prioriza la conversión sobre la consistencia perfecta; un doble-booking es mejor que perder un prospecto.

---

## 7. Construcción del system prompt

El system prompt es la "personalidad" del agente para cada empresa. Se construye **una sola vez** al crear el agente y se cachea con el TTL del agente (`AGENT_CACHE_TTL_MINUTES`, default 60 min).

### `build_citas_system_prompt()` — 4 fetches en paralelo

```python
results = await asyncio.gather(
    fetch_horario_reuniones(id_empresa),          # Horario semana (sin cache propio, cacheado en agente)
    fetch_nombres_productos_servicios(id_empresa), # Lista de nombres de productos/servicios (cache 1h)
    fetch_contexto_negocio(id_empresa),            # Descripción, misión, valores, contexto (cache 1h)
    fetch_preguntas_frecuentes(id_chatbot),        # FAQs (Pregunta/Respuesta) (cache 1h)
    return_exceptions=True,
)
```

`return_exceptions=True` garantiza que si una de las 4 fuentes falla, las demás igualmente se inyectan al prompt. El agente puede funcionar parcialmente sin FAQs o sin productos.

### Variables inyectadas al template Jinja2 (`citas_system.j2`)

| Variable | Contenido |
|----------|-----------|
| `personalidad` | Tono del agente (ej: "amable y directa") |
| `fecha_completa` | `"22 de febrero de 2026 es domingo"` |
| `fecha_iso` | `"2026-02-22"` (para que el LLM calcule fechas relativas) |
| `hora_actual` | `"10:30 AM"` (zona horaria `TIMEZONE`) |
| `horario_atencion` | Horario de la empresa formateado por día |
| `lista_productos_servicios` | Nombres de productos y servicios (para que el LLM sepa qué existe) |
| `contexto_negocio` | Descripción de la empresa, misión, servicios principales |
| `preguntas_frecuentes` | FAQs en formato `Pregunta: / Respuesta:` |

---

## 8. Estrategia de caché

El agente usa **2 caches TTL** independientes. Horarios, contexto de negocio y FAQs no tienen cache propio — se obtienen de la API al construir el agente y quedan cacheados dentro del agente compilado.

| Caché | Módulo | Clave | Maxsize | TTL | Propósito |
|-------|--------|-------|---------|-----|-----------|
| `_agent_cache` | `agent/agent.py` | `(id_empresa,)` | 500 | `AGENT_CACHE_TTL_MINUTES` (60 min) | Agente compilado (grafo LangGraph + system prompt con horarios, contexto, FAQs) |
| `_busqueda_cache` | `busqueda_productos.py` | `(id_empresa, busqueda)` | 2000 | `SEARCH_CACHE_TTL_MINUTES` (15 min) | Resultados de búsqueda de productos/servicios |

### Por qué el ScheduleValidator no usa el cache del agente

El system prompt incluye el horario de atención (cacheado 60 min). Pero `ScheduleValidator.validate()` llama directamente a `_fetch_horario()` (sin cache, directo a la API) para cada validación de cita. Esto garantiza que la validación final antes de crear el evento siempre use datos frescos, independientemente del TTL del agente.

### Thundering herd prevention

Todos los caches con fetch HTTP usan el mismo patrón:

```python
# 1. Fast path (sin await)
if key in _cache:
    return _cache[key]

# 2. Slow path: serializar por key
lock = _fetch_locks.setdefault(key, asyncio.Lock())
async with lock:
    # 3. Double-check: otra coroutine pudo haberlo llenado mientras esperábamos
    if key in _cache:
        return _cache[key]
    try:
        data = await fetch_from_api(key)
        _cache[key] = data
    finally:
        # 4. Liberar el lock del dict para no acumular locks huérfanos
        _fetch_locks.pop(key, None)
```

**Por qué `finally` y no `except`:** Si el fetch falla, se elimina el lock igualmente. Las coroutines que ya capturaron la referencia local al lock siguen funcionando (Python reference counting mantiene el objeto vivo).

**Por qué `lock.locked()` en vez de `await lock.acquire()`:** La limpieza de locks obsoletos (`_cleanup_stale_agent_locks`) usa `lock.locked()` (síncrono, sin overhead de coroutine). Es seguro en asyncio porque el event loop es single-threaded: no puede haber cambio de estado del lock entre la verificación y la eliminación.

---

## 9. Circuit breakers

El patrón circuit breaker evita cascadas de error cuando una API externa cae. Implementado en `infra/circuit_breaker.py` con `TTLCache` para auto-reset.

### Estados

```
CLOSED (normal) → [threshold TransportErrors] → OPEN (fallo rápido)
OPEN → [reset_ttl segundos sin llamadas] → CLOSED (auto-reset por TTL)
```

### Cuatro singletons

| Singleton | API protegida | Clave | Quién lo usa |
|-----------|--------------|-------|--------------|
| `informacion_cb` | `ws_informacion_ia.php` | `id_empresa` | `prompt_data/` (contexto_negocio, horario_reuniones, productos_servicios_citas), `busqueda_productos` |
| `preguntas_cb` | `ws_preguntas_frecuentes.php` | `id_chatbot` | `prompt_data/preguntas_frecuentes` |
| `calendario_cb` | `ws_calendario.php` | `"global"` | `scheduling/booking` |
| `agendar_reunion_cb` | `ws_agendar_reunion.php` | `id_empresa` | `scheduling/schedule_validator`, `scheduling/schedule_recommender` (CONSULTAR_DISPONIBILIDAD, SUGERIR_HORARIOS) |

`calendario_cb` usa clave fija `"global"` porque `ws_calendario.php` es un servicio compartido de la plataforma MaravIA — si cae, cae para todas las empresas.

### Qué abre el circuit y qué no

| Evento | Abre circuit | Razón |
|--------|-------------|-------|
| `httpx.TransportError` (timeout de red, conexión rechazada) | ✅ Sí | El servidor es inalcanzable |
| `httpx.TimeoutException` (timeout de lectura/escritura) | ✅ Sí | El servidor no responde |
| `httpx.HTTPStatusError` (4xx, 5xx) | ❌ No | El servidor está up, respondió con error |
| `{"success": false}` en el body | ❌ No | Lógica de negocio, no fallo de infraestructura |

### Reporte en `/health`

```python
if informacion_cb.any_open():       issues.append("informacion_api_degraded")
if preguntas_cb.any_open():         issues.append("preguntas_api_degraded")
if calendario_cb.any_open():        issues.append("calendario_api_degraded")
if agendar_reunion_cb.any_open():   issues.append("agendar_reunion_api_degraded")
```

Con cualquier issue activo, `/health` devuelve `HTTP 503` en lugar de `200`.

---

## 10. Modelo de concurrencia

El agente es **single-process, single-thread asyncio**. Todo el paralelismo es cooperativo (coroutines), no preemptivo (threads).

### Locks de sesión (`_session_locks`)

```python
lock = _session_locks.setdefault(session_id, asyncio.Lock())
async with lock:
    # Procesar mensaje del usuario
```

**Propósito:** Serializar mensajes concurrentes del mismo usuario. Si el mismo WhatsApp envía dos mensajes antes de recibir respuesta, el segundo espera a que el checkpointer termine de escribir el primero.

**Limpieza:** Cuando `_session_locks` supera `AGENT_CACHE_MAXSIZE` entradas (default 500), `_cleanup_stale_session_locks()` elimina locks de sesiones que no están actualmente adquiridas (`not lock.locked()`). Evita crecimiento indefinido en sistemas multiempresa con muchos contactos.

### Locks de cache de agentes (`_agent_cache_locks`)

Misma estrategia para evitar que múltiples sesiones de la misma empresa construyan el agente simultáneamente (thundering herd en el primer request de cada empresa).

**Limpieza:** Umbral de `AGENT_CACHE_MAXSIZE × 1.5` entradas (default 750). Se eliminan locks cuyo agente ya expiró del cache.

### Paralelismo en `build_citas_system_prompt`

Las 4 fuentes de datos del system prompt se cargan en paralelo con `asyncio.gather`. El tiempo de carga es el máximo de los 4 (no la suma), lo que reduce la latencia del primer request de cada empresa de ~4s a ~1s.

---

## 11. Observabilidad

### Métricas Prometheus (`GET /metrics`)

| Métrica | Tipo | Labels | Descripción |
|---------|------|--------|-------------|
| `agent_citas_chat_requests_total` | Counter | `empresa_id` | Mensajes recibidos (label de baja cardinalidad: empresa, no sesión) |
| `agent_citas_chat_errors_total` | Counter | `error_type` | Errores por tipo (`context_error`, `agent_creation_error`, etc.) |
| `agent_citas_booking_attempts_total` | Counter | — | Intentos de llamar a `create_booking` |
| `agent_citas_booking_success_total` | Counter | — | Citas creadas exitosamente |
| `agent_citas_booking_failed_total` | Counter | `reason` | Fallos (`invalid_datetime`, `circuit_open`, `timeout`, `http_4xx`, etc.) |
| `agent_citas_tool_calls_total` | Counter | `tool_name` | Llamadas a cada tool |
| `agent_citas_tool_errors_total` | Counter | `tool_name`, `error_type` | Errores por tool |
| `agent_citas_api_calls_total` | Counter | `endpoint`, `status` | Llamadas a APIs externas |
| `agent_citas_chat_response_duration_seconds` | Histogram | `status` | Latencia total request→response (buckets: 0.1s–90s) |
| `agent_citas_llm_call_duration_seconds` | Histogram | `status` | Latencia llamada al LLM (buckets: 0.5s–90s) |
| `agent_citas_tool_execution_duration_seconds` | Histogram | `tool_name` | Latencia de cada tool (buckets: 0.1s–10s) |
| `agent_citas_api_call_duration_seconds` | Histogram | `endpoint` | Latencia de APIs externas (buckets: 0.1s–10s) |
| `agent_citas_cache_entries` | Gauge | `cache_type` | Entradas actuales por tipo de cache |
| `agent_citas_info` | Info | — | Versión, modelo, tipo de agente |

### Logging

Configurado en `logger.py`. Por defecto `INFO`. En `DEBUG` se loguean los payloads completos enviados y recibidos por cada API (útil para debugging de integraciones).

```bash
LOG_LEVEL=DEBUG python -m citas.main
```

Niveles de logs relevantes:

| Prefijo | Módulo | Ejemplos |
|---------|--------|---------|
| `[HTTP]` | `main.py` | Request recibido, respuesta generada, timeouts |
| `[AGENT]` | `agent/agent.py` | Cache hit/miss, creación de agente, invocación |
| `[TOOL]` | `tool/tools.py` | Tool invocada, validaciones, resultados |
| `[BOOKING]` | `scheduling/booking.py` | Evento creado, errores de calendario |
| `[SCHEDULE]` | `scheduling/schedule_validator.py` | Validaciones de horario |
| `[RECOMMENDATION]` | `scheduling/schedule_recommender.py` | Sugerencias de horarios |
| `[CB:nombre]` | `infra/circuit_breaker.py` | Estado del circuit breaker (open/closed) |

---

## 12. API Reference

### `POST /api/chat`

Procesa un mensaje del cliente y devuelve la respuesta del agente.

**Request:**

```json
{
  "message": "string (1–4096 chars, requerido)",
  "session_id": "integer (≥0, requerido)",
  "context": {
    "config": {
      "id_empresa": "integer (requerido)",
      "usuario_id": "integer (opcional, default: None — requerido para crear cita)",
      "correo_usuario": "string (opcional, default: None — requerido para crear cita)",
      "personalidad": "string (opcional, default: 'amable, profesional y eficiente')",
      "duracion_cita_minutos": "integer (opcional, default: 60)",
      "slots": "integer (opcional, default: 60)",
      "agendar_usuario": "bool|int (opcional, default: 1)",
      "agendar_sucursal": "bool|int (opcional, default: 0)",
      "id_chatbot": "integer (opcional, para FAQs)"
    }
  }
}
```

**Response 200:**
```json
{
  "reply": "¡Perfecto, María! Tu cita está confirmada para el viernes 28 de febrero a las 3:00 PM...",
  "url": null
}
```

`url` es solo para `archivo_saludo` en el primer mensaje de la conversación. Los enlaces de Google Meet van en el texto de `reply`. Siempre presente en el JSON.

**Response 200 (error de negocio):**

Los errores de configuración o de timeout también devuelven HTTP 200 con un `reply` descriptivo. El gateway Go no necesita manejar errores HTTP del agente.

**Timeout:** El endpoint tiene un timeout global de `CHAT_TIMEOUT` segundos (default 120). Si se supera, devuelve un reply informando al usuario.

---

### `GET /health`

Verifica el estado del servicio y sus dependencias.

**Response 200 (todo OK):**
```json
{
  "status": "ok",
  "agent": "citas",
  "version": "2.5.0",
  "issues": []
}
```

**Response 503 (degradado):**
```json
{
  "status": "degraded",
  "agent": "citas",
  "version": "2.5.0",
  "issues": ["informacion_api_degraded", "calendario_api_degraded"]
}
```

Issues posibles:
- `openai_api_key_missing` — `OPENAI_API_KEY` no está configurada
- `informacion_api_degraded` — circuit breaker de `ws_informacion_ia` abierto
- `preguntas_api_degraded` — circuit breaker de `ws_preguntas_frecuentes` abierto
- `calendario_api_degraded` — circuit breaker de `ws_calendario` abierto
- `agendar_reunion_api_degraded` — circuit breaker de `ws_agendar_reunion` abierto

**Importante:** El endpoint **no hace llamadas HTTP** a las APIs externas. Usa únicamente el estado en memoria del circuit breaker. Latencia < 1ms.

---

### `GET /metrics`

Métricas Prometheus en formato text/plain. Diseñado para ser scrapeado por Prometheus/Grafana.

---

## 13. Variables de entorno

| Variable | Requerida | Default | Validación | Descripción |
|----------|-----------|---------|-----------|-------------|
| `OPENAI_API_KEY` | ✅ | — | — | API Key de OpenAI |
| `OPENAI_MODEL` | ❌ | `gpt-4o-mini` | string | Modelo de OpenAI |
| `OPENAI_TEMPERATURE` | ❌ | `0.5` | 0.0–2.0 | Temperatura del LLM |
| `OPENAI_TIMEOUT` | ❌ | `60` | 1–300 seg | Timeout para llamadas al LLM |
| `MAX_TOKENS` | ❌ | `2048` | 1–128000 | Máximo de tokens por respuesta |
| `SERVER_HOST` | ❌ | `0.0.0.0` | — | Host del servidor uvicorn |
| `SERVER_PORT` | ❌ | `8002` | 1–65535 | Puerto del servidor |
| `CHAT_TIMEOUT` | ❌ | `120` | 30–300 seg | Timeout total por request |
| `API_TIMEOUT` | ❌ | `10` | 1–120 seg | Timeout para APIs externas (httpx read timeout) |
| `HTTP_RETRY_ATTEMPTS` | ❌ | `3` | 1–10 | Reintentos ante fallo de red |
| `HTTP_RETRY_WAIT_MIN` | ❌ | `1` | 0–30 seg | Espera mínima entre reintentos (backoff exponencial) |
| `HTTP_RETRY_WAIT_MAX` | ❌ | `4` | 1–60 seg | Espera máxima entre reintentos (backoff exponencial) |
| `HTTP_MAX_CONNECTIONS` | ❌ | `50` | 10–500 | Conexiones TCP simultáneas del pool httpx |
| `HTTP_MAX_KEEPALIVE` | ❌ | `20` | 5–200 | Conexiones TCP en espera (keep-alive) |
| `AGENT_CACHE_TTL_MINUTES` | ❌ | `60` | 5–1440 min | TTL del agente compilado (system prompt) |
| `AGENT_CACHE_MAXSIZE` | ❌ | `500` | 10–5000 | Máximo de agentes cacheados (por id_empresa) |
| `SEARCH_CACHE_TTL_MINUTES` | ❌ | `15` | 1–60 min | TTL del cache de búsqueda de productos |
| `SEARCH_CACHE_MAXSIZE` | ❌ | `2000` | 10–10000 | Máximo de entradas en cache de búsqueda |
| `MAX_MESSAGES_HISTORY` | ❌ | `20` | 4–200 | Ventana de mensajes enviados al LLM |
| `CB_THRESHOLD` | ❌ | `3` | 1–20 | Errores de red consecutivos para abrir el circuit breaker |
| `CB_RESET_TTL` | ❌ | `300` | 60–3600 seg | Tiempo de auto-reset del circuit breaker |
| `CB_MAX_KEYS` | ❌ | `500` | 50–10000 | Máximo de keys (empresas) rastreadas por circuit breaker |
| `LOG_LEVEL` | ❌ | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL | Nivel de logging |
| `LOG_FILE` | ❌ | `""` | path | Archivo de log (vacío = solo stdout) |
| `TIMEZONE` | ❌ | `America/Lima` | zoneinfo key | Zona horaria para fechas en prompts y validaciones |
| `REDIS_URL` | ❌ | `""` | URL redis:// | URL de Redis (pendiente de integración) |
| `API_CALENDAR_URL` | ❌ | `https://api.maravia.pe/.../ws_calendario.php` | URL | Endpoint para CREAR_EVENTO |
| `API_AGENDAR_REUNION_URL` | ❌ | `https://api.maravia.pe/.../ws_agendar_reunion.php` | URL | Endpoint para SUGERIR_HORARIOS y CONSULTAR_DISPONIBILIDAD |
| `API_INFORMACION_URL` | ❌ | `https://api.maravia.pe/.../ws_informacion_ia.php` | URL | Endpoint para horarios, contexto, productos |
| `API_PREGUNTAS_FRECUENTES_URL` | ❌ | `https://api.maravia.pe/.../ws_preguntas_frecuentes.php` | URL | Endpoint para FAQs |

Todas las variables son leídas en `config/config.py` con validación de tipos y fallback al default si el valor es inválido (no lanza excepciones).

> **Guía detallada de configuración:** Para entender qué hace cada variable, cuándo cambiarla y ejemplos de escenarios, ver [`docs/CONFIGURACION.md`](docs/CONFIGURACION.md).

---

## 14. Integraciones externas (APIs MaravIA)

Todas las APIs externas son PHP endpoints de MaravIA. Se comunican vía POST JSON con un campo `codOpe` que identifica la operación. Cada operación tiene su circuit breaker y patrón de resiliencia.

### Resumen de operaciones

| Endpoint PHP | `codOpe` | Módulo que lo llama | CB | Cuándo se ejecuta |
|-------------|----------|--------------------|----|-------------------|
| `ws_informacion_ia.php` | `OBTENER_HORARIO_REUNIONES` | `prompt_data/horario_reuniones.py`, `scheduling/schedule_validator.py` | `informacion_cb` | Cache miss al crear agente o validar cita |
| | `OBTENER_CONTEXTO_NEGOCIO` | `prompt_data/contexto_negocio.py` | `informacion_cb` | Cache miss al crear agente |
| | `OBTENER_PRODUCTOS_CITAS` | `prompt_data/productos_servicios_citas.py` | `informacion_cb` | Cache miss al crear agente |
| | `OBTENER_SERVICIOS_CITAS` | `prompt_data/productos_servicios_citas.py` | `informacion_cb` | Cache miss al crear agente |
| | `BUSCAR_PRODUCTOS_SERVICIOS_CITAS` | `busqueda_productos.py` | `informacion_cb` | Tool `search_productos_servicios` |
| `ws_agendar_reunion.php` | `SUGERIR_HORARIOS` | `scheduling/schedule_recommender.py` | `agendar_reunion_cb` | Tool `check_availability` sin hora |
| | `CONSULTAR_DISPONIBILIDAD` | `scheduling/availability_client.py` | `agendar_reunion_cb` | Tool `check_availability` con hora; o paso 12 de `create_booking` |
| `ws_calendario.php` | `CREAR_EVENTO` | `scheduling/booking.py` | `calendario_cb` | Tool `create_booking` (fase 3) |
| `ws_preguntas_frecuentes.php` | _(sin codOpe)_ | `prompt_data/preguntas_frecuentes.py` | `preguntas_cb` | Cache miss al crear agente |

---

### `ws_informacion_ia.php` — datos de la empresa

Fuente de verdad de datos de la empresa. Protegida por `informacion_cb` keyed por `id_empresa`.

#### `OBTENER_HORARIO_REUNIONES`

```json
// Request
{"codOpe": "OBTENER_HORARIO_REUNIONES", "id_empresa": 42}

// Response
{
  "success": true,
  "horario_reuniones": {
    "reunion_lunes": "09:00-18:00",
    "reunion_martes": "09:00-18:00",
    "reunion_miercoles": "09:00-18:00",
    "reunion_jueves": "09:00-18:00",
    "reunion_viernes": "09:00-17:00",
    "reunion_sabado": "NO DISPONIBLE",
    "reunion_domingo": null,
    "horarios_bloqueados": ""
  }
}
```

**Uso:** Sistema prompt (formateado como lista por día) + `ScheduleValidator.validate()` (pasos 5-11).
**Cache:** Sin cache propio — se obtiene al construir el agente (cacheado por `AGENT_CACHE_TTL_MINUTES`, 60 min). El `ScheduleValidator` llama directo a la API.

#### `OBTENER_CONTEXTO_NEGOCIO`

```json
// Request
{"codOpe": "OBTENER_CONTEXTO_NEGOCIO", "id_empresa": 42}

// Response
{"success": true, "contexto_negocio": "Somos una empresa dedicada a..."}
```

**Uso:** Inyectado en el system prompt (sección "Información del negocio").
**Cache:** Sin cache propio — se obtiene al construir el agente (cacheado por `AGENT_CACHE_TTL_MINUTES`, 60 min).

#### `OBTENER_PRODUCTOS_CITAS` / `OBTENER_SERVICIOS_CITAS`

```json
// Request (productos)
{"codOpe": "OBTENER_PRODUCTOS_CITAS", "id_empresa": 42}

// Request (servicios)
{"codOpe": "OBTENER_SERVICIOS_CITAS", "id_empresa": 42}

// Response (ambos)
{
  "success": true,
  "productos": [{"nombre": "NovaX Pro"}, {"nombre": "ProductoY"}]
}
```

**Uso:** Solo los **nombres** se inyectan al system prompt (`"Productos: NovaX Pro, ProductoY"`). El LLM sabe qué existe; para detalles usa la tool `search_productos_servicios`.
**Llamadas:** 2 en paralelo (`asyncio.gather`) al crear agente. Máx 10 productos + 10 servicios.

#### `BUSCAR_PRODUCTOS_SERVICIOS_CITAS`

```json
// Request
{"codOpe": "BUSCAR_PRODUCTOS_SERVICIOS_CITAS", "id_empresa": 42, "busqueda": "NovaX", "limite": 10}

// Response
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

**Uso:** Invocada por la tool `search_productos_servicios` en tiempo real.
**Cache:** `_busqueda_cache` — TTL 15 min por `(id_empresa, busqueda.lower())`, máx 2000 entradas.

---

### `ws_agendar_reunion.php` — disponibilidad de agenda

Gestión de disponibilidad. Protegida por `agendar_reunion_cb` keyed por `id_empresa`.

#### `SUGERIR_HORARIOS`

```json
// Request
{
  "codOpe": "SUGERIR_HORARIOS",
  "id_empresa": 42,
  "duracion_minutos": 60,
  "slots": 60,
  "agendar_usuario": 1,
  "agendar_sucursal": 0
}

// Response
{
  "success": true,
  "mensaje": "Horarios disponibles encontrados",
  "total": 5,
  "sugerencias": [
    {"dia": "hoy", "hora_legible": "3:00 PM", "disponible": true, "fecha_inicio": "2026-02-26 15:00:00"},
    {"dia": "mañana", "hora_legible": "10:00 AM", "disponible": true, "fecha_inicio": "2026-02-27 10:00:00"}
  ]
}
```

**Limitación:** Solo devuelve slots para **hoy y mañana**. Para otras fechas se usa `CONSULTAR_DISPONIBILIDAD` con hora específica.

#### `CONSULTAR_DISPONIBILIDAD`

```json
// Request
{
  "codOpe": "CONSULTAR_DISPONIBILIDAD",
  "id_empresa": 42,
  "fecha_inicio": "2026-02-28 15:00:00",
  "fecha_fin": "2026-02-28 16:00:00",
  "slots": 60,
  "agendar_usuario": 1,
  "agendar_sucursal": 0
}

// Response
{"success": true, "disponible": true}
```

**Degradación graceful:** Si falla por timeout, error HTTP o circuit abierto, el validador retorna `available: true`. La cita se crea igualmente. Prioriza conversión sobre consistencia perfecta; un posible doble-booking es preferible a perder un prospecto.

---

### `ws_calendario.php` — creación de eventos

Creación de eventos. Protegida por `calendario_cb` con clave global.

#### `CREAR_EVENTO`

```json
// Request
{
  "codOpe": "CREAR_EVENTO",
  "usuario_id": 7,
  "id_prospecto": 5191234567890,
  "titulo": "Reunion para el usuario: Juan Pérez",
  "fecha_inicio": "2026-02-28 15:00:00",
  "fecha_fin": "2026-02-28 16:00:00",
  "correo_cliente": "juan@ejemplo.com",
  "correo_usuario": "vendedor@empresa.com",
  "agendar_usuario": 1
}

// Response (con Google Calendar)
{
  "success": true,
  "message": "Evento agregado correctamente",
  "google_meet_link": "https://meet.google.com/abc-defg-hij",
  "google_calendar_synced": true
}

// Response (sin Google Calendar)
{
  "success": true,
  "message": "Evento agregado correctamente",
  "google_calendar_synced": false
}
```

**Importante:** `CREAR_EVENTO` usa `client.post()` directo (sin `post_with_logging` / retry) porque **no es idempotente** — un retry podría duplicar el evento en el calendario.

| Campo del payload | Origen | Descripción |
|-------------------|--------|-------------|
| `usuario_id` | 🔧 Gateway (`config.usuario_id`) | ID del vendedor que registra la cita |
| `id_prospecto` | ⚙️ Runtime (`session_id`) | Número de WhatsApp del cliente |
| `titulo` | 🔒 Código (hardcoded) | `"Reunion para el usuario: {nombre}"` — no editable por LLM |
| `fecha_inicio` | 🔢 Calculado | `date + _parse_time_to_24h(time)` |
| `fecha_fin` | 🔢 Calculado | `fecha_inicio + duracion_cita_minutos` |
| `correo_cliente` | 🤖 IA (`customer_contact`) | Email del cliente (extraído de la conversación) |
| `correo_usuario` | 🔧 Gateway (`config.correo_usuario`) | Email del vendedor (para invitación) |
| `agendar_usuario` | 🔧 Gateway (`config.agendar_usuario`) | 1=asignar vendedor automáticamente |

---

### `ws_preguntas_frecuentes.php` — FAQs del chatbot

FAQs del chatbot. Protegida por `preguntas_cb` keyed por `id_chatbot`.

```json
// Request (sin codOpe)
{"id_chatbot": 15}

// Response
{
  "success": true,
  "preguntas_frecuentes": [
    {"pregunta": "¿Qué es NovaX?", "respuesta": "Es una plataforma de gestión..."},
    {"pregunta": "¿Cuál es el horario de atención?", "respuesta": "De lunes a viernes de 9am a 6pm"}
  ]
}
```

**Formato inyectado al prompt:**
```
Pregunta: ¿Qué es NovaX?
Respuesta: Es una plataforma de gestión...

Pregunta: ¿Cuál es el horario de atención?
Respuesta: De lunes a viernes de 9am a 6pm
```

**Cache:** Sin cache propio — se obtiene al construir el agente (cacheado por `AGENT_CACHE_TTL_MINUTES`, 60 min).

---

### `post_with_logging` — cliente HTTP compartido

Todas las llamadas de **lectura** usan `post_with_logging()` de `infra/http_client.py`:
- Cliente `httpx.AsyncClient` singleton compartido entre todos los requests (connection pool reusado).
- Reintentos con backoff exponencial (tenacity): `HTTP_RETRY_ATTEMPTS` veces (default 3), espera entre `HTTP_RETRY_WAIT_MIN` y `HTTP_RETRY_WAIT_MAX` segundos.
- Solo reintenta ante `httpx.TransportError` (errores de red). Los errores HTTP (4xx, 5xx) **no** se reintentan.
- `CREAR_EVENTO` **no** usa `post_with_logging` (riesgo de duplicados).

**Configuración del cliente:**
```python
httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=API_TIMEOUT, write=5.0, pool=2.0),
    limits=httpx.Limits(
        max_connections=HTTP_MAX_CONNECTIONS,       # default 50
        max_keepalive_connections=HTTP_MAX_KEEPALIVE, # default 20
        keepalive_expiry=30.0,
    ),
)
```

### Cadena de resiliencia completa

```
Tool llamada por LLM
  └─ buscar_productos_servicios(id_empresa, busqueda)
      ├─ 1. Cache hit? → return inmediato
      ├─ 2. Circuit breaker abierto? → error rápido sin tocar la red
      ├─ 3. Anti-thundering herd: asyncio.Lock por cache_key
      └─ 4. resilient_call()
            ├─ CB check (redundante, por si cambió entre 2 y 4)
            └─ post_with_logging()  ← tenacity: 3 intentos, backoff exponencial
                  └─ httpx.AsyncClient.post()
                        ├─ Éxito → CB reset, cache write, return
                        ├─ TransportError → CB record_failure, tenacity retry
                        └─ HTTPStatusError → no afecta CB, propaga error
```

---

## 15. Estructura del proyecto

```
agent_citas/
├── src/citas/
│   ├── main.py                        # FastAPI app: /api/chat, /health, /metrics
│   ├── logger.py                      # Logging centralizado
│   ├── metrics.py                     # Definición de métricas Prometheus + context managers
│   ├── __init__.py
│   │
│   ├── agent/                         # Orquestación del agente LangGraph
│   │   ├── agent.py                   # Core: TTLCache, session locks, middleware ventana, process_cita_message()
│   │   ├── content.py                 # CitaStructuredResponse (Pydantic) + _build_content (multimodal)
│   │   ├── context.py                 # AgentContext (dataclass) + _validate_context + _prepare_agent_context
│   │   ├── __init__.py
│   │   └── prompts/                   # System prompt del agente
│   │       ├── __init__.py            # build_citas_system_prompt() — asyncio.gather x4 + Jinja2
│   │       └── citas_system.j2        # Template del system prompt
│   │
│   ├── tool/                          # Tools del agente (@tool LangChain)
│   │   ├── tools.py                   # check_availability, create_booking, search_productos_servicios
│   │   ├── validation.py              # Validadores Pydantic + regex para datos de booking
│   │   └── __init__.py
│   │
│   ├── services/                      # Lógica de negocio
│   │   ├── __init__.py                # Re-exports de todos los subdirectorios (compatibilidad)
│   │   ├── busqueda_productos.py      # buscar_productos_servicios() para tool (TTLCache 15min)
│   │   │
│   │   ├── prompt_data/               # Fetchers de datos para el system prompt (sin cache propio)
│   │   │   ├── contexto_negocio.py    # fetch_contexto_negocio() — descripción del negocio
│   │   │   ├── horario_reuniones.py   # fetch_horario_reuniones() + format para prompt
│   │   │   ├── preguntas_frecuentes.py # fetch_preguntas_frecuentes() — FAQs por id_chatbot
│   │   │   ├── productos_servicios_citas.py # fetch nombres productos/servicios para prompt
│   │   │   └── __init__.py
│   │   │
│   │   └── scheduling/                # Lógica de agendamiento
│   │       ├── schedule_validator.py  # ScheduleValidator: pipeline de 12 validaciones
│   │       ├── schedule_recommender.py # ScheduleRecommender: SUGERIR_HORARIOS + check slot
│   │       ├── availability_client.py # check_slot_availability (infra compartida validator/recommender)
│   │       ├── booking.py             # confirm_booking() → ws_calendario (CREAR_EVENTO)
│   │       ├── time_parser.py         # Utilidades puras de parsing de tiempo (sin I/O)
│   │       └── __init__.py
│   │
│   ├── infra/                         # Infraestructura HTTP transversal
│   │   ├── circuit_breaker.py         # CircuitBreaker: informacion_cb, preguntas_cb, calendario_cb, agendar_reunion_cb
│   │   ├── http_client.py             # httpx.AsyncClient singleton + post_with_logging (tenacity retry)
│   │   ├── _resilience.py             # resilient_call() — wrapper CB + retry
│   │   └── __init__.py
│   │
│   └── config/
│       ├── config.py                  # Variables de entorno con validación de tipos
│       └── __init__.py
│
├── pyproject.toml                     # hatchling build, deps pinneadas
├── Dockerfile                         # python:3.12-slim + uv
├── run.py                             # Entry point dev local
├── .env.example
└── README.md
```

### Grafo de dependencias

Módulos organizados por nivel de abstracción — cada nivel solo importa del nivel inferior.

```
config/config.py                          (nivel 0 — sin dependencias internas)
   ↑
   ├── logger.py                           (nivel 1)
   ├── metrics.py                          (nivel 1)
   └── config/__init__.py                  (nivel 1 — re-exporta variables)
            ↑
            ├── tool/validation.py                        (nivel 2)
            ├── infra/http_client.py                      (nivel 2 — tenacity retry)
            ├── infra/circuit_breaker.py                   (nivel 2 — 4 CB singletons)
            │       ↑
            │   infra/_resilience.py                       (nivel 2.5 — resilient_call)
            │       ↑
            │   ┌───┴──────────────────────────────────────────┐
            │   ├── services/prompt_data/contexto_negocio.py   │
            │   ├── services/prompt_data/horario_reuniones.py  │
            │   ├── services/prompt_data/preguntas_frecuentes.py│
            │   ├── services/prompt_data/productos_servicios.py│
            │   ├── services/scheduling/schedule_validator.py  │
            │   ├── services/scheduling/schedule_recommender.py│
            │   ├── services/scheduling/availability_client.py │
            │   ├── services/scheduling/booking.py             │
            │   └── services/busqueda_productos.py             │
            │                           (nivel 3)              │
            └──────────────────────────────────────────────────┘
                            ↑
                    tool/tools.py            (nivel 4)
                            ↑
                    agent/prompts/           (nivel 4, paralelo)
                            ↑
                    agent/agent.py           (nivel 5)
                            ↑
                    main.py                  (nivel 6)
                            ↑
                    Gateway Go (externo)
```

### Patrones de diseño

| Patrón | Dónde | Propósito |
|--------|-------|-----------|
| **Factory + Cache** | `agent/agent.py` (`_get_agent`) | Agente compilado por empresa, evita recreación |
| **Double-Checked Locking** | `agent/agent.py`, `busqueda_productos.py` | Serializar primera creación sin bloquear hot path |
| **Singleton** | `infra/http_client.py`, `agent/agent.py` (`_model`) | Connection pool y modelo LLM compartidos |
| **Circuit Breaker** | `infra/circuit_breaker.py` (4 CBs) | Protege ante APIs inestables, auto-reset por TTL |
| **Resilient Call** | `infra/_resilience.py` | Wrapper: CB check → execute → record success/failure |
| **Retry + Backoff** | `infra/http_client.py` (tenacity) | Configurable: intentos, espera min/max |
| **Runtime Context Injection** | `tool/tools.py` (LangChain 1.2+) | AgentContext inyectado en tools sin parámetros explícitos |
| **Graceful Degradation** | `scheduling/schedule_validator.py`, `tool/tools.py` | Si falla API no crítica, continúa con fallback |
| **Strategy** (validación) | `tool/tools.py` (`create_booking`) | 3 capas secuenciales independientes |
| **Observer** | `metrics.py` | Context managers trackean sin modificar lógica de negocio |
| **Template Method** | `agent/prompts/citas_system.j2` | Estructura del prompt fija, variables inyectadas |

---

## 16. Stack tecnológico

Todas las dependencias están pinneadas en [`pyproject.toml`](pyproject.toml) con comentarios por categoría. El proyecto usa `hatchling` como build backend y `uv` como package manager (local y Docker).

| Componente | Librería | Versión | Rol |
|------------|----------|---------|-----|
| Web framework | `fastapi` + `uvicorn[standard]` | 0.135.1 / 0.41.0 | Servidor HTTP ASGI |
| Validación | `pydantic` v2 | 2.12.5 | Modelos de request/response y datos de booking |
| LLM agent | `langchain` + `langchain-core` | 1.2.10 / 1.2.17 | `create_agent`, `@tool`, `ToolRuntime`, `trim_messages`, `wrap_model_call` |
| LLM provider | `langchain-openai` | 1.1.10 | `init_chat_model("openai:gpt-4o-mini")` |
| Grafos de agente | `langgraph` + `langgraph-checkpoint` | 1.0.10 / 4.0.1 | Checkpointer (InMemorySaver), flujo de mensajes |
| OpenAI SDK | `openai` | 2.26.0 | Error types (`AuthenticationError`, `RateLimitError`, etc.) |
| HTTP client | `httpx` | 0.28.1 | Llamadas async a APIs externas |
| Retry | `tenacity` | 9.1.4 | Backoff exponencial en `post_with_logging` |
| Templates | `jinja2` | 3.1.6 | System prompt con variables dinámicas |
| Métricas | `prometheus-client` | 0.24.1 | Exposición de métricas en `/metrics` |
| Cache en memoria | `cachetools` | 7.0.3 | `TTLCache` para agentes, horarios, contexto, búsquedas |
| Variables de entorno | `python-dotenv` | 1.2.2 | Carga de `.env` |
| Zona horaria | `zoneinfo` (stdlib) | Python 3.12+ | `America/Lima` y otras TZs |
| Build | `hatchling` | — | Build backend (`pyproject.toml`) |
| Package manager | `uv` | latest | Instalación rápida (local y Docker) |

---

## 17. Inicio rápido

### Requisitos

- Python 3.12+
- `uv` ([instalación](https://docs.astral.sh/uv/getting-started/installation/))
- `OPENAI_API_KEY` válida
- Acceso a red hacia `api.maravia.pe` (APIs externas)

### Instalación

```bash
# 1. Crear y activar entorno virtual
uv venv venv_agent_citas
source venv_agent_citas/bin/activate   # Linux/Mac
# venv_agent_citas\Scripts\activate    # Windows

# 2. Instalar paquete y dependencias
uv pip install .

# 3. Configurar variables de entorno
cp .env.example .env
# Editar .env con OPENAI_API_KEY y URLs de APIs si son distintas al default
```

### Ejecutar

```bash
# Producción
python -m citas.main

# DEBUG (logs detallados con payloads de APIs)
LOG_LEVEL=DEBUG python -m citas.main
```

El servidor estará en `http://localhost:8002`.

### Verificar

```bash
# Health check
curl http://localhost:8002/health

# Test del agente (requiere API real)
curl -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hola, quiero agendar una reunión",
    "session_id": 1,
    "context": {"config": {"id_empresa": 1}}
  }'
```

---

## 18. Limitaciones conocidas

### 🔴 Memoria ilimitada (`InMemorySaver`)

**Qué pasa:** `InMemorySaver` almacena el historial completo de cada conversación en RAM, sin TTL ni límite de tamaño. Los `session_id` de WhatsApp son permanentes; nunca se expiran. En un sistema multiempresa con 50–200 empresas y múltiples contactos activos, el proceso crece hasta que Docker lo mata por OOM.

**Impacto adicional:** Si el container se reinicia (deploy, crash), toda la memoria conversacional se pierde. Los usuarios experimentan el agente "olvidando" la conversación.

**Solución pendiente:** Migrar a `AsyncRedisSaver` (Redis ya existe en Easypanel como `memori_agentes`) con TTL de 24 horas. Ver `docs/PENDIENTES.md`.

---

### 🔴 Sin autenticación en `/api/chat`

**Qué pasa:** El endpoint no valida quién hace la llamada. Cualquier proceso con acceso de red al puerto 8002 puede invocar al agente. En Easypanel los servicios son internos (no expuestos a internet), pero es una superficie de ataque si la red interna se compromete.

**Solución pendiente:** Header `X-Internal-Token` validado como FastAPI Dependency. Ver `docs/PENDIENTES.md`.

---

### 🟡 Sin modificación ni cancelación de citas

**Qué pasa:** El agente no tiene tools para editar o cancelar eventos ya creados. Si un cliente quiere cambiar su cita, el agente responde que lo derivará a un asesor.

**Causa:** Requiere implementar `ws_calendario.php` operaciones `MODIFICAR_EVENTO` / `CANCELAR_EVENTO` y el diseño conversacional para reconfirmar datos.

---

### 🟡 `SUGERIR_HORARIOS` solo cubre hoy y mañana

**Qué pasa:** La API `SUGERIR_HORARIOS` solo devuelve slots para hoy y mañana. Si el cliente pregunta por disponibilidad del jueves próximo, el agente no puede mostrar slots específicos — le pide que indique una hora y la verifica manualmente con `CONSULTAR_DISPONIBILIDAD`.

**Causa:** Limitación de la API externa, no del agente.

---

### 🟢 Sin streaming

**Qué pasa:** El agente genera la respuesta completa antes de enviarla. El TTFT (Time To First Token) desde la perspectiva del usuario de WhatsApp es igual al tiempo total de respuesta, típicamente 3–8 segundos.

**Causa:** Requiere `StreamingResponse` en FastAPI + `astream_events` en LangGraph + soporte en el gateway Go para consumir SSE y retransmitir a N8N.

---

### 🟢 Sin tests automatizados

El proyecto no cuenta con suite de tests. Las áreas críticas a cubrir son:
- `ScheduleValidator.validate()` — los 12 pasos con fechas/horas edge cases
- `booking._parse_time_to_24h()` y `_build_fecha_inicio_fin()` — conversiones de tiempo
- `CircuitBreaker` — transiciones de estado y auto-reset
- `_validate_context()` y `_prepare_agent_context()` — manejo de config incompleta

---

## 19. Mejoras pendientes

El detalle completo con código de implementación está en [`docs/PENDIENTES.md`](docs/PENDIENTES.md).

### Resumen por prioridad

```
🔴 ANTES DE PRODUCCIÓN CON CARGA REAL:
   1. InMemorySaver → AsyncRedisSaver (TTL 24h)
      - langgraph-checkpoint-redis
      - REDIS_URL=redis://memori_agentes:6379 (ya existe en Easypanel)
      - Archivos: agent/agent.py, pyproject.toml

   2. Auth X-Internal-Token en /api/chat
      - FastAPI Depends + nuevo env var INTERNAL_API_TOKEN
      - También actualizar gateway Go

✅ IMPLEMENTADOS:
   - Ventana de mensajes (wrap_model_call + trim_messages, max=20)
   - Middleware no destructivo: checkpointer intacto, compatible con Redis

🟢 DIFERIDAS:
   - Tests unitarios (pytest + pytest-asyncio)
   - Streaming SSE — descartado (canal WhatsApp, respuesta siempre completa)
```

---

## Licencia

Propiedad de MaravIA Team. Todos los derechos reservados.

## Soporte

Para problemas técnicos, contactar al equipo de desarrollo de MaravIA o revisar los logs con `LOG_LEVEL=DEBUG`.
