# Agent Citas — MaravIA

Agente conversacional de IA especializado en la gestión de citas y reuniones comerciales. Actúa como un **closer digital 24/7** que guía a prospectos de WhatsApp hasta confirmar una reunión de venta, integrando validación real de horarios, creación de eventos en Google Calendar y soporte multiempresa.

**Versión:** `2.0.0` — FastAPI HTTP + LangChain 1.2+ API moderna
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
│                        GATEWAY Go (puerto 8080)                      │
│  Recibe JSON de N8N, enruta por modalidad="citas" → POST /api/chat  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ {message, session_id, context.config}
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI — main.py (puerto 8002)                   │
│                                                                     │
│  POST /api/chat ──► asyncio.wait_for(process_cita_message, 120s)   │
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
│  3. _get_agent(config) ← TTLCache por id_empresa                   │
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
│   Response          │          │       ├─ get_horario() [cache]      │
└─────────────────────┘          │       └─ SUGERIR_HORARIOS /        │
                                 │          CONSULTAR_DISPONIBILIDAD   │
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
)
```

### Memoria conversacional

LangGraph usa `thread_id = str(session_id)` como identificador de conversación. Cada mensaje nuevo se acumula en el checkpointer junto con el historial anterior. El LLM recibe todos los mensajes previos en cada llamada, lo que le permite mantener contexto de citas ya discutidas, nombre del cliente, etc.

**Limitación actual:** `InMemorySaver` no tiene TTL ni límite de mensajes. Las conversaciones crecen indefinidamente en RAM. Ver §18 y §19.

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

### `check_availability(date, time?)`

**Cuándo lo usa el LLM:** El cliente pregunta por disponibilidad sin haber dado todos los datos para agendar, o quiere verificar si un horario específico está libre.

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

**APIs que llama:**
- `ws_agendar_reunion.php` con `codOpe: "SUGERIR_HORARIOS"` — devuelve hasta N slots disponibles para hoy y mañana.
- `ws_agendar_reunion.php` con `codOpe: "CONSULTAR_DISPONIBILIDAD"` — verifica un slot concreto.

### `create_booking(date, time, customer_name, customer_contact)`

**Cuándo lo usa el LLM:** Tiene los 4 datos requeridos: fecha, hora, nombre completo y email del cliente.

**Pipeline de 3 fases:**

```
Fase 1 — Validación de datos (Pydantic + regex)
  ├─ date: formato YYYY-MM-DD
  ├─ time: HH:MM AM/PM o HH:MM 24h
  ├─ customer_name: no vacío, sin caracteres peligrosos
  └─ customer_contact: email válido

Fase 2 — Validación de horario (ScheduleValidator.validate, 12 pasos)
  ├─ Parsea fecha y hora
  ├─ Verifica que no sea en el pasado (zona horaria Lima/TIMEZONE)
  ├─ Obtiene horario de la empresa (get_horario, TTLCache)
  ├─ Verifica que ese día de la semana tenga atención
  ├─ Verifica rango de horario del día (ej: 09:00-18:00)
  ├─ Verifica que la cita + duración no exceda el cierre
  ├─ Verifica horarios bloqueados (bloqueos específicos)
  └─ CONSULTAR_DISPONIBILIDAD → ¿está libre ese slot?

Fase 3 — Creación del evento (confirm_booking)
  └─ ws_calendario.php CREAR_EVENTO
      ├─ Éxito + Google Meet link → respuesta con enlace
      ├─ Éxito sin Meet → "Cita confirmada. Te contactaremos con detalles"
      └─ Fallo → mensaje de error del API
```

**Parámetros enviados a `CREAR_EVENTO`:**

| Campo | Origen |
|-------|--------|
| `usuario_id` | `context.config.usuario_id` (identificador del vendedor en N8N) |
| `id_prospecto` | `session_id` (número de WhatsApp del cliente) |
| `titulo` | Fijo: `"Reunion para el usuario: {nombre_completo}"` |
| `fecha_inicio` | Calculado: `fecha + hora` en `YYYY-MM-DD HH:MM:SS` |
| `fecha_fin` | `fecha_inicio + duracion_cita_minutos` |
| `correo_cliente` | `customer_contact` (email dado por el cliente) |
| `correo_usuario` | `context.config.correo_usuario` (email del vendedor, para invitación) |
| `agendar_usuario` | `context.config.agendar_usuario` (bandera de asignación automática) |

**Nota de diseño:** El campo `titulo` lo construye el código, no el LLM. Esto evita que el LLM inyecte texto arbitrario en el calendario de la empresa.

### `search_productos_servicios(busqueda)`

**Cuándo lo usa el LLM:** El cliente pregunta por precio, descripción o detalles de un producto/servicio específico que no está en el system prompt.

El system prompt ya incluye la **lista de nombres** de productos y servicios (cargada al crear el agente). Esta tool se usa para búsqueda en profundidad cuando el cliente quiere detalles específicos.

**Comportamiento:** Llama a `ws_informacion_ia.php` con `codOpe: "BUSCAR_PRODUCTOS_SERVICIOS"` y devuelve hasta 10 resultados formateados (nombre, precio, categoría, descripción).

---

## 6. Validación de horarios (ScheduleValidator)

`ScheduleValidator.validate()` implementa un pipeline de **12 verificaciones secuenciales**. La validación se interrumpe en el primer fallo y devuelve un mensaje de error legible para el LLM.

| Paso | Verificación | Fuente de datos |
|------|-------------|-----------------|
| 1 | Parseo de fecha (`YYYY-MM-DD`) | Entrada del LLM |
| 2 | Parseo de hora (`HH:MM AM/PM` o `HH:MM`) | Entrada del LLM |
| 3 | Combinar fecha + hora en `datetime` | — |
| 4 | ¿La fecha/hora ya pasó? (zona horaria `TIMEZONE`) | `datetime.now(ZoneInfo)` |
| 5 | Obtener horario de la empresa | `get_horario()` (TTLCache) |
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
    fetch_horario_reuniones(id_empresa),          # Horario semana (cache TTL SCHEDULE_CACHE_TTL_MINUTES)
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

El agente usa **4 capas de caché** independientes, con TTLs distintos según la frecuencia de cambio de cada dato.

| Caché | Módulo | Clave | TTL | Propósito |
|-------|--------|-------|-----|-----------|
| `_agent_cache` | `agent.py` | `id_empresa` | `AGENT_CACHE_TTL_MINUTES` (60 min) | Agente compilado (grafo LangGraph + system prompt) |
| `_horario_cache` | `horario_cache.py` | `id_empresa` | `SCHEDULE_CACHE_TTL_MINUTES` (5 min) | Horario de reuniones por empresa |
| `_contexto_cache` | `contexto_negocio.py` | `id_empresa` | 1 hora | Descripción y contexto de la empresa |
| `_preguntas_cache` | `preguntas_frecuentes.py` | `id_chatbot` | 1 hora | FAQs del chatbot |

### Por qué dos TTLs distintos para agente y horario

El system prompt incluye el horario de atención. Si `SCHEDULE_CACHE_TTL_MINUTES = 5 min` y `AGENT_CACHE_TTL_MINUTES = 60 min`, el agente compilado usaría el horario viejo durante 60 min aunque el horario del negocio haya cambiado.

**Solución:** `ScheduleValidator.validate()` llama directamente a `get_horario()` (TTLCache de 5 min), sin pasar por el system prompt. Esto garantiza que la validación final antes de crear el evento siempre use datos frescos, independientemente del TTL del agente.

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

El patrón circuit breaker evita cascadas de error cuando una API externa cae. Implementado en `services/circuit_breaker.py` con `TTLCache` para auto-reset.

### Estados

```
CLOSED (normal) → [threshold TransportErrors] → OPEN (fallo rápido)
OPEN → [reset_ttl segundos sin llamadas] → CLOSED (auto-reset por TTL)
```

### Tres singletons

| Singleton | API protegida | Clave | Quién lo usa |
|-----------|--------------|-------|--------------|
| `informacion_cb` | `ws_informacion_ia.php` | `id_empresa` | `horario_cache`, `contexto_negocio`, `productos_servicios_citas`, `busqueda_productos` |
| `preguntas_cb` | `ws_preguntas_frecuentes.php` | `id_chatbot` | `preguntas_frecuentes` |
| `calendario_cb` | `ws_calendario.php` | `"global"` | `booking` |

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
if informacion_cb.any_open():  issues.append("informacion_api_degraded")
if preguntas_cb.any_open():    issues.append("preguntas_api_degraded")
if calendario_cb.any_open():   issues.append("calendario_api_degraded")
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

**Limpieza:** Cuando `_session_locks` supera 500 entradas, `_cleanup_stale_session_locks()` elimina locks de sesiones que no están actualmente adquiridas (`not lock.locked()`). Evita crecimiento indefinido en sistemas multiempresa con muchos contactos.

### Locks de cache de agentes (`_agent_cache_locks`)

Misma estrategia para evitar que múltiples sesiones de la misma empresa construyan el agente simultáneamente (thundering herd en el primer request de cada empresa).

**Limpieza:** Umbral de 150 entradas (1.5× el maxsize del TTLCache de 100 agentes).

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
| `[AGENT]` | `agent.py` | Cache hit/miss, creación de agente, invocación |
| `[TOOL]` | `tools.py` | Tool invocada, validaciones, resultados |
| `[BOOKING]` | `booking.py` | Evento creado, errores de calendario |
| `[AVAILABILITY]` | `schedule_validator.py` | Consultas de disponibilidad |
| `[HORARIO_CACHE]` | `horario_cache.py` | Cache hit/miss, fetches |
| `[CB:nombre]` | `circuit_breaker.py` | Estado del circuit breaker |
| `[create_booking]` | `tools.py` | Log detallado de las 3 APIs del flujo de reserva |

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
      "usuario_id": "integer (opcional, default: 1)",
      "correo_usuario": "string (opcional, default: '')",
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
  "url": "https://meet.google.com/abc-defg-hij"
}
```

`url` es `null` cuando no hay Google Meet link. Siempre presente en el JSON.

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
  "issues": ["informacion_api_degraded", "calendario_api_degraded"]
}
```

Issues posibles:
- `openai_api_key_missing` — `OPENAI_API_KEY` no está configurada
- `informacion_api_degraded` — circuit breaker de `ws_informacion_ia` abierto
- `preguntas_api_degraded` — circuit breaker de `ws_preguntas_frecuentes` abierto
- `calendario_api_degraded` — circuit breaker de `ws_calendario` abierto

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
| `API_TIMEOUT` | ❌ | `10` | 1–120 seg | Timeout para APIs externas (httpx) |
| `HTTP_RETRY_ATTEMPTS` | ❌ | `3` | 1–10 | Reintentos ante fallo de red |
| `HTTP_RETRY_WAIT_MIN` | ❌ | `1` | 0–30 seg | Espera mínima entre reintentos |
| `HTTP_RETRY_WAIT_MAX` | ❌ | `4` | 1–60 seg | Espera máxima entre reintentos |
| `SCHEDULE_CACHE_TTL_MINUTES` | ❌ | `5` | 1–1440 min | TTL del cache de horarios de reunión |
| `AGENT_CACHE_TTL_MINUTES` | ❌ | `60` | 5–1440 min | TTL del agente compilado (system prompt) |
| `LOG_LEVEL` | ❌ | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL | Nivel de logging |
| `LOG_FILE` | ❌ | `""` | path | Archivo de log (vacío = solo stdout) |
| `TIMEZONE` | ❌ | `America/Lima` | zoneinfo key | Zona horaria para fechas en prompts y validaciones |
| `REDIS_URL` | ❌ | `""` | URL redis:// | URL de Redis (pendiente de integración) |
| `API_CALENDAR_URL` | ❌ | `https://api.maravia.pe/.../ws_calendario.php` | URL | Endpoint para CREAR_EVENTO |
| `API_AGENDAR_REUNION_URL` | ❌ | `https://api.maravia.pe/.../ws_agendar_reunion.php` | URL | Endpoint para SUGERIR_HORARIOS y CONSULTAR_DISPONIBILIDAD |
| `API_INFORMACION_URL` | ❌ | `https://api.maravia.pe/.../ws_informacion_ia.php` | URL | Endpoint para horarios, contexto, productos |
| `API_PREGUNTAS_FRECUENTES_URL` | ❌ | `https://api.maravia.pe/.../ws_preguntas_frecuentes.php` | URL | Endpoint para FAQs |

Todas las variables son leídas en `config/config.py` con validación de tipos y fallback al default si el valor es inválido (no lanza excepciones).

---

## 14. Integraciones externas (APIs MaravIA)

### `ws_informacion_ia.php`

Fuente de verdad de datos de la empresa. Protegida por `informacion_cb` keyed por `id_empresa`.

| `codOpe` | Cuándo | Payload | Respuesta clave |
|----------|--------|---------|-----------------|
| `OBTENER_HORARIO_REUNIONES` | Al crear el agente o validar cita (TTLCache miss) | `{id_empresa}` | `horario_reuniones` (dict de días) |
| `OBTENER_CONTEXTO_NEGOCIO` | Al crear el agente (TTLCache miss) | `{id_empresa}` | Texto descriptivo de la empresa |
| `BUSCAR_PRODUCTOS_SERVICIOS` | Tool `search_productos_servicios` (sin cache, real-time) | `{id_empresa, busqueda, limite}` | Lista de productos/servicios |

### `ws_agendar_reunion.php`

Gestión de disponibilidad de agenda. Sin circuit breaker propio (comparte `informacion_cb` via reintentos).

| `codOpe` | Cuándo | Payload |
|----------|--------|---------|
| `SUGERIR_HORARIOS` | `check_availability` sin hora específica | `{id_empresa, duracion_minutos, slots, agendar_usuario, agendar_sucursal}` |
| `CONSULTAR_DISPONIBILIDAD` | `check_availability` con hora O `create_booking` (paso 12 de validación) | `{id_empresa, fecha_inicio, fecha_fin, slots, agendar_usuario, agendar_sucursal}` |

**Degradación graceful:** Si `CONSULTAR_DISPONIBILIDAD` falla, el validador asume disponible. La cita se crea; un posible doble-booking es preferible a perder la conversión.

### `ws_calendario.php`

Creación de eventos. Protegida por `calendario_cb` con clave global.

| `codOpe` | Cuándo | Resultado |
|----------|--------|-----------|
| `CREAR_EVENTO` | `create_booking` (fase 3) | `{success, message, google_meet_link?, google_calendar_synced}` |

Si la empresa tiene Google Calendar configurado, la respuesta incluye `google_meet_link` con la URL de la videollamada. El agente la entrega al usuario en el reply.

### `ws_preguntas_frecuentes.php`

FAQs del chatbot. Protegida por `preguntas_cb` keyed por `id_chatbot`.

Recibe `{id_chatbot}` sin `codOpe`. Retorna lista de `{pregunta, respuesta}` que se formatea como `Pregunta: / Respuesta:` para inyectar en el system prompt.

### `post_with_retry` — cliente HTTP compartido

Todas las llamadas de lectura usan `post_with_retry()` de `http_client.py`:
- Cliente `httpx.AsyncClient` singleton compartido entre todos los requests (sin overhead de conexión TCP).
- Reintentos con backoff exponencial: `HTTP_RETRY_ATTEMPTS` veces (default 3), espera entre `HTTP_RETRY_WAIT_MIN` y `HTTP_RETRY_WAIT_MAX` segundos.
- Solo reintenta ante `httpx.TransportError` (errores de red). Los errores HTTP (4xx, 5xx) no se reintentan.

---

## 15. Estructura del proyecto

```
agent_citas/
├── src/citas/
│   ├── main.py                        # FastAPI app: /api/chat, /health, /metrics
│   ├── logger.py                      # Logging centralizado (JSON estructurado o texto)
│   ├── metrics.py                     # Definición de métricas Prometheus + context managers
│   ├── validation.py                  # Validadores Pydantic + regex para datos de booking
│   ├── __init__.py
│   │
│   ├── agent/
│   │   ├── agent.py                   # Core: TTLCache de agentes, session locks, process_cita_message()
│   │   └── __init__.py
│   │
│   ├── tool/
│   │   ├── tools.py                   # check_availability, create_booking, search_productos_servicios
│   │   └── __init__.py
│   │
│   ├── services/
│   │   ├── horario_cache.py           # TTLCache compartido de OBTENER_HORARIO_REUNIONES (fuente única)
│   │   ├── schedule_validator.py      # ScheduleValidator: pipeline de 12 validaciones
│   │   ├── booking.py                 # confirm_booking() → ws_calendario (CREAR_EVENTO)
│   │   ├── contexto_negocio.py        # fetch_contexto_negocio() con TTLCache + fetch lock
│   │   ├── preguntas_frecuentes.py    # fetch_preguntas_frecuentes() con TTLCache + fetch lock
│   │   ├── horario_reuniones.py       # fetch_horario_reuniones() para system prompt (usa horario_cache)
│   │   ├── productos_servicios_citas.py  # fetch_nombres_productos_servicios() para system prompt
│   │   ├── busqueda_productos.py      # buscar_productos_servicios() para tool (sin cache)
│   │   ├── circuit_breaker.py         # CircuitBreaker: informacion_cb, preguntas_cb, calendario_cb
│   │   ├── http_client.py             # httpx.AsyncClient singleton + post_with_retry
│   │   └── __init__.py
│   │
│   ├── config/
│   │   ├── config.py                  # Variables de entorno con validación de tipos
│   │   └── __init__.py
│   │
│   └── prompts/
│       ├── __init__.py                # build_citas_system_prompt() — asyncio.gather x4 + Jinja2
│       └── citas_system.j2            # Template del system prompt
│
├── docs/
│   ├── PENDIENTES.md                  # Roadmap técnico (Redis, auth, trim_messages)
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── DEPLOYMENT.md
│   └── analisis_tecnico.md
│
├── requirements.txt
├── .env.example
└── README.md
```

---

## 16. Stack tecnológico

| Componente | Librería | Versión mínima | Rol |
|------------|----------|----------------|-----|
| Web framework | `fastapi` + `uvicorn` | `>=0.110.0` | Servidor HTTP ASGI |
| Validación | `pydantic` v2 | `>=2.6.0` | Modelos de request/response y config |
| LLM agent | `langchain` | `>=1.2.0` | `create_agent`, `@tool`, `ToolRuntime` |
| Grafos de agente | `langgraph` | `>=0.2.0` | Checkpointer, flujo de mensajes |
| Memoria | `langgraph` `InMemorySaver` | — | Estado conversacional por `thread_id` |
| LLM provider | `langchain-openai` | `>=0.3.0` | `init_chat_model("openai:gpt-4o-mini")` |
| HTTP client | `httpx` | `>=0.27.0` | Llamadas async a APIs externas |
| Templates | `jinja2` | `>=3.1.3` | System prompt con variables dinámicas |
| Métricas | `prometheus-client` | `>=0.19.0` | Exposición de métricas en `/metrics` |
| Cache en memoria | `cachetools` | `>=5.3.0` | `TTLCache` para agentes, horarios, contexto |
| Parseo de fechas | `dateparser` | `>=1.2.0` | Fechas naturales en validación |
| Variables de entorno | `python-dotenv` | `>=1.0.0` | Carga de `.env` |
| Zona horaria | `zoneinfo` (stdlib) | Python 3.9+ | `America/Lima` y otras TZs |

---

## 17. Inicio rápido

### Requisitos

- Python 3.10+
- `OPENAI_API_KEY` válida
- Acceso a red hacia `api.maravia.pe` (APIs externas)

### Instalación

```bash
# 1. Crear y activar entorno virtual
python -m venv venv_agent_citas
source venv_agent_citas/bin/activate   # Linux/Mac
# venv_agent_citas\Scripts\activate    # Windows

# 2. Instalar dependencias
pip install -r requirements.txt

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

### 🟡 Sin límite de ventana de mensajes

**Qué pasa:** El LLM recibe el historial completo en cada llamada. Una conversación de 50 turnos consume 50× más tokens del prompt que una de 1 turno, aumentando costo y latencia.

**Solución disponible ahora** (sin Redis): `trim_messages(max_tokens=20)` en `create_agent()`. Ver `docs/PENDIENTES.md`.

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
      - Archivos: agent/agent.py, requirements.txt

   2. Auth X-Internal-Token en /api/chat
      - FastAPI Depends + nuevo env var INTERNAL_API_TOKEN
      - También actualizar gateway Go

🟡 MEJORAS IMPORTANTES:
   3. Límite de ventana de mensajes (trim_messages, max=20 turnos)
      - Se puede hacer AHORA, sin Redis
      - 1 archivo, 10 minutos: agent/agent.py

🟢 DIFERIDAS:
   4. Tests unitarios (pytest + pytest-asyncio)
   5. Streaming SSE (TTFT real)
```

---

## Licencia

Propiedad de MaravIA Team. Todos los derechos reservados.

## Soporte

Para problemas técnicos, contactar al equipo de desarrollo de MaravIA o revisar los logs con `LOG_LEVEL=DEBUG`.
