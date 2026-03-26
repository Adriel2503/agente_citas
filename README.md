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
                                │ {message, session_id, id_empresa, api_key, config}
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI — main.py (puerto 8002)                  │
│                                                                     │
│  POST /api/chat ──► asyncio.wait_for(process_cita_message, 120s)    │
│  GET  /health   ──► verifica estado de circuit breakers             │
│  GET  /metrics  ──► Prometheus exposition format                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   agent/agent.py — process_cita_message()           │
│                                                                     │
│  1. Session lock (asyncio.Lock por session_id)                      │
│  2. Validate context → config_data (setdefault personalidad)        │
│  3. _get_agent(id_empresa, api_key, config) ← TTLCache              │
│     └─ cache key: (id_empresa, sha256(api_key)[:12])                │
│     └─ si miss: build_citas_system_prompt() [asyncio.gather x4]     │
│  4. agent.ainvoke(messages, thread_id=session_id, context=ctx)      │
└────────┬───────────────────────────────────────────┬────────────────┘
         │ Checkpointer (AsyncRedisSaver / fallback   │ AgentContext
         │   InMemorySaver) thread_id=session_id     │
         │                                           │ (inyectado a tools)
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
  "id_empresa": 42,
  "api_key": "sk-...",
  "config": {
    "usuario_id": 7,
    "correo_usuario": "vendedor@empresa.com",
    "personalidad": "amable y directa",
    "duracion_cita_minutos": 60,
    "slots": 60,
    "agendar_usuario": 1,
    "agendar_sucursal": 0
  }
}
```

`session_id` es el número de WhatsApp del prospecto (`5191234567890`), único y permanente por contacto. `id_empresa` y `api_key` son top-level (el gateway siempre los envía). `config` es opcional (CitasConfig con Pydantic, `extra="ignore"`).

### Paso 2 — Preparación de contexto

```
FastAPI → process_cita_message(message, session_id, id_empresa, api_key, config)
  ├─ id_empresa y api_key validados por Pydantic en ChatRequest (requeridos)
  ├─ config: CitasConfig con validators (bool→int, strip, defaults)
  └─ _prepare_agent_context() construye AgentContext (dataclass) inyectado a tools:
       id_empresa, usuario_id, correo_usuario, session_id,
       duracion_cita_minutos, slots, agendar_usuario, agendar_sucursal
```

### Paso 3 — Session lock

Antes de tocar el checkpointer, se adquiere un `asyncio.Lock` keyed por `session_id`. Esto garantiza que si el mismo usuario envía dos mensajes en rápida sucesión (doble-clic, reintento), el segundo espera a que termine el primero. Evita condiciones de carrera sobre el mismo `thread_id` en LangGraph.

### Paso 4 — Obtención del agente compilado (TTLCache)

```python
key_hash = sha256(api_key)[:12]
cache_key = (id_empresa, key_hash)
agent = get_cached_agent(cache_key)  # O lo crea si no existe
```

Si es un **cache miss** (primera request de esa empresa, TTL expirado, o cambio de api_key):
1. Se adquiere un lock por `cache_key` (para evitar thundering herd entre múltiples sesiones de la misma empresa que llegan simultáneamente).
2. Se llama `build_citas_system_prompt()` que hace **4 llamadas HTTP en paralelo** (ver §7).
3. Se crea el modelo LLM per-tenant con `get_model(api_key)` → `init_chat_model()`.
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
    model=get_model(api_key),             # init_chat_model("openai:gpt-4o-mini", api_key=...)
    tools=AGENT_TOOLS,                    # [check_availability, create_booking, search_...]
    system_prompt=system_prompt,          # Template Jinja2 renderizado
    checkpointer=get_checkpointer(),      # AsyncRedisSaver (con TTL) / fallback InMemorySaver
    response_format=CitaStructuredResponse,  # Structured output: reply + url
    middleware=[message_window],          # Ventana de mensajes (trim_messages, no destructivo)
)
```

### Memoria conversacional

LangGraph usa `thread_id = str(session_id)` como identificador de conversación. Cada mensaje nuevo se acumula en el checkpointer junto con el historial anterior.

**Ventana de mensajes:** El middleware `_message_window` (vía `wrap_model_call` + `trim_messages`) limita a `MAX_MESSAGES_HISTORY` (default 20) los mensajes que ve el LLM en cada llamada. El checkpointer conserva el historial completo — solo se recorta lo que se envía al modelo.

**Checkpointer:** El agente soporta `AsyncRedisSaver` (con TTL configurable vía `REDIS_CHECKPOINT_TTL_HOURS`, default 24h) con fallback automático a `InMemorySaver` si Redis no está disponible. La inicialización ocurre en `init_checkpointer()` durante el lifespan de FastAPI.

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

3 tools via function calling: `check_availability`, `create_booking`, `search_productos_servicios`. El LLM decide autónomamente cuáles invocar. Los datos del gateway (empresa, vendedor, slots) se inyectan via `AgentContext` a través de `ToolRuntime` — las tools son stateless y testables en aislamiento.

## 6. Validación de horarios (ScheduleValidator)

`ScheduleValidator.validate()` implementa un pipeline de **12 verificaciones secuenciales** (parseo de fecha/hora, horario de empresa, horarios bloqueados, disponibilidad real via API). Prioriza conversión sobre consistencia — si la API falla, permite la cita igualmente.

## 7. Construcción del system prompt

Se construye una vez al crear el agente con **4 fetches en paralelo** (`asyncio.gather`): horarios, productos, contexto de negocio y FAQs. Se renderiza via template Jinja2 (`citas_system.j2`) y queda cacheado con el agente (TTL 60 min).

## 8. Estrategia de caché

2 caches TTL independientes: agentes compilados (60 min, key = `id_empresa + key_hash`) y búsqueda de productos (15 min). Anti-thundering herd con `asyncio.Lock` + double-check por cache key.

## 9. Circuit breakers

4 circuit breakers independientes (uno por API externa). Solo `httpx.TransportError` abre el circuit (3 fallos consecutivos). Auto-reset via `TTLCache` después de 5 min. Estado reportado en `/health`.

## 10. Modelo de concurrencia

Single-process, single-thread asyncio. Locks por `session_id` (serializar mensajes del mismo usuario) y por `cache_key` (evitar thundering herd al crear agentes). Limpieza automática de locks huérfanos.

Para el detalle completo de todas estas secciones (payloads, código, tablas de parámetros, patrones de resiliencia), ver [`docs/design/INTERNALS.md`](docs/design/INTERNALS.md).

---

## 11. Observabilidad

### Métricas Prometheus (`GET /metrics`)

El agente expone 21 métricas (contadores, histogramas, gauges, info) con prefijo `citas_`. Incluye 10 tipos de error OpenAI mapeados, métricas de booking, tools, caches y tokens por empresa.

Para el inventario completo, labels, valores y consultas PromQL, ver [`docs/METRICS.md`](docs/METRICS.md).

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
| `[TOOL]` | `tools/tools.py` | Tool invocada, validaciones, resultados |
| `[BOOKING]` | `scheduling/booking.py` | Evento creado, errores de calendario |
| `[SCHEDULE]` | `scheduling/schedule_validator.py` | Validaciones de horario |
| `[RECOMMENDATION]` | `scheduling/schedule_recommender.py` | Sugerencias de horarios |
| `[CB:nombre]` | `infra/circuit_breaker.py` | Estado del circuit breaker (open/closed) |

---

## 12. API Reference

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/chat` | POST | Procesa mensaje del usuario → respuesta del agente (`{reply, url}`) |
| `/health` | GET | Health check con estado de circuit breakers (200 OK / 503 degraded) |
| `/metrics` | GET | Métricas Prometheus (text/plain) |

Todos los errores del agente devuelven HTTP 200 con un mensaje amigable de derivación a asesor. El gateway Go no necesita manejar errores HTTP.

Para la referencia completa (request/response schemas, campos de config, ejemplos, payloads de tools, validaciones), ver [`docs/API.md`](docs/API.md).

---

## 13. Variables de entorno

No hay variables obligatorias — `api_key` viene per-request desde el gateway. Todos los parámetros tienen defaults funcionales. 32 variables configurables en `config/config.py` con validación de tipos y rangos.

Para la referencia completa (qué hace cada variable, cuándo cambiarla, rangos, ejemplos por escenario), ver [`docs/CONFIGURACION.md`](docs/CONFIGURACION.md).

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

Para los payloads exactos de cada operación (request/response JSON), ver [`docs/API.md`](docs/API.md) sección "Tools internas del agente".

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
│   │   ├── agent.py                   # Core: _get_agent(), process_cita_message(), _OPENAI_ERRORS
│   │   ├── content.py                 # CitaStructuredResponse (Pydantic) + _build_content (multimodal)
│   │   ├── context.py                 # AgentContext (dataclass) + _prepare_agent_context
│   │   ├── __init__.py
│   │   ├── runtime/                   # Runtime del agente — NO TOCAR entre agentes
│   │   │   ├── __init__.py            # Re-exports de _cache, _llm, middleware
│   │   │   ├── _cache.py             # TTLCache + asyncio locks + cleanup
│   │   │   ├── _llm.py              # get_model(api_key) + get_checkpointer() + init/close_checkpointer()
│   │   │   └── middleware.py          # @wrap_model_call message_window (trim_messages)
│   │   └── prompts/                   # System prompt del agente
│   │       ├── __init__.py            # build_citas_system_prompt() — asyncio.gather x4 + Jinja2
│   │       └── citas_system.j2        # Template del system prompt
│   │
│   ├── tools/                         # Tools del agente (@tool LangChain)
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
│   │   │   ├── funciones_especiales.py # fetch_funciones_especiales() — instrucciones por empresa
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
│       ├── circuit_breakers.py        # 4 CB singletons + get_health_issues() para /health
│       └── __init__.py                # Re-exports de config + circuit_breakers
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
            ├── tools/validation.py                       (nivel 2)
            ├── infra/http_client.py                      (nivel 2 — tenacity retry)
            ├── infra/circuit_breaker.py                   (nivel 2 — 4 CB singletons)
            │       ↑
            │   infra/_resilience.py                       (nivel 2.5 — resilient_call)
            │       ↑
            │   ┌───┴──────────────────────────────────────────┐
            │   ├── services/prompt_data/contexto_negocio.py   │
            │   ├── services/prompt_data/funciones_especiales.py│
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
                    tools/tools.py           (nivel 4)
                            ↑
                    agent/prompts/           (nivel 4, paralelo)
                    agent/runtime/           (nivel 4, _cache + _llm + middleware)
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
| **Factory + Cache** | `agent/agent.py` (`_get_agent`) | Agente compilado por (empresa, api_key), evita recreación |
| **Double-Checked Locking** | `agent/agent.py`, `busqueda_productos.py` | Serializar primera creación sin bloquear hot path |
| **Singleton** | `infra/http_client.py`, `agent/runtime/_llm.py` (`_checkpointer`) | Connection pool y checkpointer compartidos |
| **Per-tenant Factory** | `agent/runtime/_llm.py` (`get_model`) | Modelo LLM por tenant (api_key), creado solo en cache miss |
| **Circuit Breaker** | `infra/circuit_breaker.py` (4 CBs) | Protege ante APIs inestables, auto-reset por TTL |
| **Resilient Call** | `infra/_resilience.py` | Wrapper: CB check → execute → record success/failure |
| **Retry + Backoff** | `infra/http_client.py` (tenacity) | Configurable: intentos, espera min/max |
| **Runtime Context Injection** | `tools/tools.py` (LangChain 1.2+) | AgentContext inyectado en tools sin parámetros explícitos |
| **Graceful Degradation** | `scheduling/schedule_validator.py`, `tools/tools.py` | Si falla API no crítica, continúa con fallback |
| **Strategy** (validación) | `tools/tools.py` (`create_booking`) | 3 capas secuenciales independientes |
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
| Grafos de agente | `langgraph` + `langgraph-checkpoint` + `langgraph-checkpoint-redis` | 1.0.10 / 4.0.1 / ≥0.4.0 | Checkpointer (AsyncRedisSaver / InMemorySaver), flujo de mensajes |
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
- Acceso a red hacia `api.maravia.pe` (APIs externas)

### Instalación

**Opción A — Con lockfile (recomendado para producción y CI)**

Usa `uv.lock` para instalar versiones exactas de todas las dependencias. Garantiza que todos los entornos (local, Docker, CI) tengan las mismas versiones. Crea el `.venv` automáticamente.

```bash
uv sync
```

**Opción B — Sin lockfile (desarrollo rápido o sin uv.lock)**

Instala las dependencias desde `pyproject.toml` sin fijar versiones transitivas. Útil si estás experimentando con versiones nuevas o si el `uv.lock` no está disponible.

```bash
uv venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate       # Windows
uv pip install .
```

**Configurar variables de entorno (ambas opciones):**

```bash
cp .env.example .env
# Editar .env si es necesario (api_key viene per-request desde el gateway)
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

# Test del agente (requiere api_key válida)
curl -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hola, quiero agendar una reunión",
    "session_id": 1,
    "id_empresa": 1,
    "api_key": "sk-..."
  }'
```

---

## 18. Limitaciones conocidas

### ✅ Memoria conversacional (AsyncRedisSaver implementado)

**Resuelto:** El agente soporta `AsyncRedisSaver` con TTL configurable (`REDIS_CHECKPOINT_TTL_HOURS`, default 24h) y fallback automático a `InMemorySaver`. La inicialización ocurre en `init_checkpointer()` durante el lifespan.

**Sin Redis configurado** (`REDIS_URL` vacío): usa `InMemorySaver` — el historial se pierde al reiniciar el container y crece en RAM sin límite. Configurar `REDIS_URL` en Easypanel resuelve ambos problemas.

---

### ✅ Autenticación en `/api/chat` (implementada, desactivable)

Header `X-Internal-Token` validado como FastAPI Dependency. Si `INTERNAL_API_TOKEN` está vacío, auth desactivada (no rompe nada). Para activar: configurar el token en el `.env` del agente y en el gateway Go simultáneamente.

---

### 🟡 Sin modificación ni cancelación de citas

**Qué pasa:** El agente no tiene tools para editar o cancelar eventos ya creados. Si un cliente quiere cambiar su cita, el agente responde que lo derivará a un asesor.

**Causa:** Requiere implementar `ws_calendario.php` operaciones `MODIFICAR_EVENTO` / `CANCELAR_EVENTO` y el diseño conversacional para reconfirmar datos.

---

### 🟡 `SUGERIR_HORARIOS` solo cubre hoy y mañana

**Qué pasa:** La API `SUGERIR_HORARIOS` solo devuelve slots para hoy y mañana. Si el cliente pregunta por disponibilidad del jueves próximo, el agente no puede mostrar slots específicos — le pide que indique una hora y la verifica manualmente con `CONSULTAR_DISPONIBILIDAD`.

**Causa:** Limitación de la API externa, no del agente.

---

### 🟡 Tests en desarrollo

Existe estructura de tests (`test/unit/` y `test/integration/`) con archivos stub. Pendiente: completar cobertura e instalar deps dev (`uv sync --group dev`).

---

## 19. Mejoras pendientes

Ver [`docs/PENDIENTES.md`](docs/PENDIENTES.md) para el detalle completo.

```
Pendiente:
  📋 B1 — slots en CREAR_EVENTO (requiere backend PHP)
  📋 Tests unitarios
  📋 Activar auth — configurar INTERNAL_API_TOKEN en Easypanel + gateway Go
```

---

## Licencia

Propiedad de MaravIA Team. Todos los derechos reservados.

## Soporte

Para problemas técnicos, contactar al equipo de desarrollo de MaravIA o revisar los logs con `LOG_LEVEL=DEBUG`.
