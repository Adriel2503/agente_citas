# Arquitectura — Agent Citas v2.0.0

Documentación técnica del microservicio de gestión de citas comerciales.

---

## Tabla de Contenidos

1. [Visión General](#visión-general)
2. [Stack Tecnológico](#stack-tecnológico)
3. [Diagrama de Arquitectura](#diagrama-de-arquitectura)
4. [Módulos](#módulos)
5. [Patrones de Concurrencia y Cache](#patrones-de-concurrencia-y-cache)
6. [APIs Externas (MaravIA)](#apis-externas-maravia)
7. [Herramientas del LLM](#herramientas-del-llm)
8. [Flujo de Datos Completo](#flujo-de-datos-completo)
9. [Patrones de Diseño](#patrones-de-diseño)
10. [Grafo de Dependencias](#grafo-de-dependencias)

---

## Visión General

**Agent Citas** es un microservicio asíncrono de IA que automatiza la gestión de citas y reuniones comerciales. Funciona como un **closer digital 24/7** que guía prospectos hasta confirmar una reunión de venta.

| Atributo | Valor |
|----------|-------|
| Versión | 2.0.0 |
| Lenguaje | Python 3.10+ |
| Protocolo | HTTP (FastAPI, puerto 8002) |
| LLM | GPT-4o-mini (configurable) |
| Memoria | InMemorySaver (LangGraph) por session_id |
| Multiempresa | Sí — agente cacheado por id_empresa |
| Multimodal | Sí — soporta imágenes vía OpenAI Vision |

---

## Stack Tecnológico

| Capa | Librería | Versión mínima | Rol |
|------|----------|----------------|-----|
| Web | FastAPI + Uvicorn | `>=0.110.0` | Servidor HTTP ASGI |
| Validación | Pydantic v2 | `>=2.6.0` | Modelos y validación de datos |
| LLM Framework | LangChain | `>=1.2.0` | Agente con function calling |
| Memoria/Grafos | LangGraph + InMemorySaver | `>=0.2.0` | Checkpointer por thread_id |
| LLM Provider | langchain-openai | `>=0.3.0` | Integración OpenAI |
| HTTP Client | httpx | `>=0.27.0` | Cliente async compartido (pool) |
| Templates | Jinja2 | `>=3.1.3` | System prompt dinámico |
| Métricas | prometheus-client | `>=0.19.0` | Observabilidad |
| Cache TTL | cachetools | `>=5.3.0` | TTLCache para agentes y contexto |
| Env | python-dotenv | `>=1.0.0` | Variables de entorno |
| Fechas naturales | dateparser | `>=1.2.0` | Parsing de fechas |

---

## Diagrama de Arquitectura

```
┌──────────────────────────────────────────────────────────────────┐
│                     GATEWAY GO (externo)                         │
│                   POST /api/chat                                 │
│        {message, session_id: int, context.config.*}              │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTP
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│          AGENT CITAS — FastAPI (puerto 8002)                     │
│                                                                  │
│  main.py                                                         │
│  ├─ POST /api/chat  ──► process_cita_message()                  │
│  ├─ GET  /health                                                 │
│  └─ GET  /metrics   ──► Prometheus                              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  agent/agent.py                                         │    │
│  │                                                         │    │
│  │  asyncio.Lock por session_id (serializa concurrencia)  │    │
│  │                  │                                      │    │
│  │          _validate_context()                            │    │
│  │                  │                                      │    │
│  │          _get_agent()  ── TTLCache(id_empresa, pers.)  │    │
│  │          ┌───────┴──────────────────────────┐          │    │
│  │          │  Si cache miss (asyncio.Lock):   │          │    │
│  │          │  ┌── init_chat_model(GPT-4o-mini)│          │    │
│  │          │  ├── build_citas_system_prompt() │──►asyncio.gather:│
│  │          │  │   ├── fetch_horario_reuniones │  horario +│    │
│  │          │  │   ├── fetch_nombres_prod_serv │  productos+│   │
│  │          │  │   └── fetch_contexto_negocio  │  contexto │    │
│  │          │  └── create_agent(model, tools,  │          │    │
│  │          │       checkpointer=InMemorySaver)│          │    │
│  │          └───────────────────────────────────          │    │
│  │                                                         │    │
│  │          agent.ainvoke(messages, config, context)      │    │
│  │          thread_id = str(session_id)                   │    │
│  └──────────────────────────┬──────────────────────────────┘    │
│                             │  function calling (LangGraph)     │
│           ┌─────────────────┼──────────────────┐               │
│           ▼                 ▼                  ▼               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │check_avail.  │  │create_booking│  │search_productos      │  │
│  │(date, time?) │  │(date, time,  │  │_servicios            │  │
│  │              │  │ name, email) │  │(busqueda, limite?)   │  │
│  │ScheduleValid.│  │ 3 capas:     │  │                      │  │
│  │.recommendation│  │ 1.Pydantic  │  │buscar_productos      │  │
│  │ o .validate  │  │ 2.Schedule   │  │_servicios()          │  │
│  └──────┬───────┘  │   Validator  │  └──────────┬───────────┘  │
│         │          │ 3.CREAR_     │             │              │
│         │          │   EVENTO     │             │              │
│         │          └──────┬───────┘             │              │
│         │                 │                     │              │
│  ┌──────┴─────────────────┴─────────────────────┴───────────┐  │
│  │              http_client.py (singleton AsyncClient)       │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                  APIs EXTERNAS MaravIA                           │
│                                                                  │
│  ws_informacion_ia.php                                           │
│  ├─ OBTENER_HORARIO_REUNIONES       (schedule_validator, prompt) │
│  ├─ OBTENER_CONTEXTO_NEGOCIO        (contexto_negocio, prompt)   │
│  ├─ OBTENER_NOMBRES_PRODUCTOS_SERV. (productos_servicios, prompt)│
│  └─ BUSCAR_PRODUCTOS_SERVICIOS_CITAS (busqueda_productos, tool)  │
│                                                                  │
│  ws_agendar_reunion.php                                          │
│  ├─ CONSULTAR_DISPONIBILIDAD  (schedule_validator._check_avail.) │
│  └─ SUGERIR_HORARIOS          (schedule_validator.recommendation)│
│                                                                  │
│  ws_calendario.php                                               │
│  └─ CREAR_EVENTO              (booking.confirm_booking)          │
└──────────────────────────────────────────────────────────────────┘
```

---

## Módulos

### `main.py` — Servidor FastAPI

Punto de entrada del sistema. Inicializa el servidor, configura logging/métricas y expone los endpoints.

**Endpoints:**

| Método | Path | Descripción |
|--------|------|-------------|
| `POST` | `/api/chat` | Endpoint principal, recibe mensaje y devuelve respuesta |
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Métricas Prometheus |

**Request body (`/api/chat`):**
```python
class ChatRequest(BaseModel):
    message: str
    session_id: int          # int (unificado con gateway)
    context: Dict | None     # context.config.id_empresa requerido
```

**Manejo de errores en el endpoint:**
- `asyncio.TimeoutError` → mensaje de timeout (`CHAT_TIMEOUT`, default 120s)
- `ValueError` → error de configuración (falta `id_empresa`)
- `Exception` → error genérico

**Lifespan:** Cierra el cliente HTTP compartido (`close_http_client()`) al apagar el servidor.

---

### `agent/agent.py` — Lógica Central del Agente

Módulo más complejo. Gestiona el ciclo de vida del agente LangChain, la memoria por sesión y la concurrencia multiempresa.

#### Componentes globales

```python
_checkpointer = InMemorySaver()      # Memoria global por thread_id

# Cache de agentes por id_empresa — TTL = SCHEDULE_CACHE_TTL_MINUTES * 60
_agent_cache: TTLCache = TTLCache(maxsize=100, ttl=...)

# Locks para evitar thundering herd al crear agentes (1 lock por cache_key)
_agent_cache_locks: Dict[Tuple, asyncio.Lock] = {}

# Locks para serializar requests concurrentes del mismo usuario
_session_locks: Dict[int, asyncio.Lock] = {}
```

#### `AgentContext` (dataclass)

Contexto runtime inyectado automáticamente en las tools de LangChain:

| Campo | Tipo | Default | Origen |
|-------|------|---------|--------|
| `id_empresa` | int | — | `context.config.id_empresa` (requerido) |
| `session_id` | int | 0 | `session_id` del request |
| `id_prospecto` | int | 0 | igual a `session_id` |
| `duracion_cita_minutos` | int | 60 | `context.config.duracion_cita_minutos` |
| `slots` | int | 60 | `context.config.slots` |
| `agendar_usuario` | int | 1 | `context.config.agendar_usuario` (bool→int) |
| `agendar_sucursal` | int | 0 | `context.config.agendar_sucursal` (bool→int) |
| `usuario_id` | int | 1 | `context.config.usuario_id` |
| `correo_usuario` | str | `""` | `context.config.correo_usuario` |

#### `_get_agent(config)` — Factory con cache

1. **Fast path**: busca en `_agent_cache` por `id_empresa` → retorna directo si hit
2. **Slow path** (double-checked locking):
   - Adquiere `asyncio.Lock` por `cache_key` (evita thundering herd)
   - Double-check tras adquirir el lock
   - Crea agente: `init_chat_model` → `build_citas_system_prompt` → `create_agent`
   - Guarda en `_agent_cache`

El TTL del agente en cache está acoplado a `SCHEDULE_CACHE_TTL_MINUTES` para que el prompt se refresque cuando expiran los datos de horario/contexto.

#### `_build_content(message)` — Soporte Vision

Detecta URLs de imágenes en el mensaje (`.jpg`, `.png`, `.gif`, `.webp`) via regex. Si hay imágenes:
- Extrae el texto y convierte las URLs a bloques `image_url` de OpenAI Vision
- Límite: 10 imágenes por mensaje

```python
# Caso solo texto → str
"Quiero una cita"

# Caso texto + imagen → List[dict]
[{"type": "text", "text": "Mira esto"}, {"type": "image_url", "image_url": {"url": "..."}}]
```

#### `process_cita_message(message, session_id, context)` — Función principal

```
1. Validar message (no vacío)
2. Registrar métrica: chat_requests_total{empresa_id}
3. Adquirir asyncio.Lock por session_id
4. _validate_context(context)  →  requiere context.config.id_empresa
5. config_data.setdefault("personalidad", "...") en agent.py
6. _get_agent(config_data)     →  agente desde cache o nuevo
7. _prepare_agent_context()    →  construir AgentContext
8. agent.ainvoke(
       messages=[{role: "user", content: _build_content(message)}],
       config={configurable: {thread_id: str(session_id)}},
       context=agent_context
   )
9. Extraer último mensaje de result["messages"]
10. Retornar respuesta
```

---

### `tool/tools.py` — Herramientas del LLM

Las 3 tools que el LLM puede invocar via function calling. El runtime context (`AgentContext`) se inyecta automáticamente por LangChain 1.2+.

#### `check_availability(date, time?, runtime)`

Consulta horarios disponibles. El parámetro `time` cambia el comportamiento:

| `time` | Operación | API llamada |
|--------|-----------|-------------|
| Omitido | `SUGERIR_HORARIOS` (hoy/mañana) | `ws_agendar_reunion.php` |
| Presente | `CONSULTAR_DISPONIBILIDAD` (slot exacto) | `ws_agendar_reunion.php` |

Si la fecha solicitada no es hoy ni mañana, retorna mensaje para que el usuario indique la hora.

**Fallback**: Si falla cualquier API, retorna horarios genéricos (09:00, 10:00, 11:00, 14:00, 15:00, 16:00).

#### `create_booking(date, time, customer_name, customer_contact, runtime)`

Crea la cita con **3 capas de validación secuenciales**:

```
Capa 1: validate_booking_data()  →  Pydantic
        ├─ ContactInfo: email válido (RFC 5322 simplificado, solo email, no teléfono)
        ├─ CustomerName: sin números, 2-100 chars, capitalizado
        └─ BookingDateTime: YYYY-MM-DD, HH:MM AM/PM, no pasado (zona Peru)

Capa 2: ScheduleValidator.validate()  →  12 checks de horario
        ├─ Formato de fecha y hora
        ├─ Fecha no en el pasado
        ├─ Obtener horario (OBTENER_HORARIO_REUNIONES, con cache TTL)
        ├─ Día tiene atención (no "NO DISPONIBLE"/"CERRADO")
        ├─ Hora dentro del rango del día
        ├─ Cita + duración no excede cierre
        ├─ Hora no bloqueada
        └─ CONSULTAR_DISPONIBILIDAD (disponible real en agenda)

Capa 3: confirm_booking()  →  CREAR_EVENTO en ws_calendario.php
        └─ Devuelve: message, google_meet_link (si aplica), google_calendar_synced
```

**Respuesta exitosa incluye:** mensaje de la API + detalles (fecha, hora, nombre) + enlace Meet si existe.

#### `search_productos_servicios(busqueda, limite?, runtime)`

Busca en el catálogo por nombre o descripción. Usa `BUSCAR_PRODUCTOS_SERVICIOS_CITAS`. Devuelve formato estructurado (nombre, precio/unidad, categoría, descripción sin HTML).

El LLM solo usa esta tool cuando el cliente pregunta por un producto/servicio **específico** (precio, descripción). Para preguntas generales ("¿qué tienen?") el agente responde con la lista del system prompt.

---

### `services/schedule_validator.py` — Validador de Horarios

**Responsabilidades:** obtener horario de reuniones con cache, validar fecha/hora, consultar disponibilidad en tiempo real.

#### Cache de horarios

```python
_SCHEDULE_CACHE: Dict[int, Tuple[Dict, datetime]] = {}  # id_empresa → (schedule, timestamp)
_CACHE_LOCK = threading.Lock()                           # thread-safe para acceso al dict
_fetch_locks: Dict[int, asyncio.Lock] = {}              # 1 lock por empresa (thundering herd)
```

`_fetch_schedule()` implementa **double-checked locking** async:
1. Fast path sin lock: `_get_cached_schedule(id_empresa)` — retorna si hit y no expirado
2. Cache miss: adquiere `asyncio.Lock` por `id_empresa`
3. Double-check dentro del lock (otra coroutine pudo haber llenado el cache)
4. Fetch real a `OBTENER_HORARIO_REUNIONES` solo si sigue siendo miss

#### `validate(fecha_str, hora_str)` — 12 validaciones

1. Parsear fecha (`%Y-%m-%d`)
2. Parsear hora (soporta `HH:MM AM/PM`, `HH:MM%p`, `HH:MM`)
3. Combinar fecha+hora y verificar que no sea en el pasado
4. `_fetch_schedule()` con cache
5. Verificar campo del día (`reunion_lunes` … `reunion_domingo`)
6. Verificar que el día no esté marcado como cerrado
7. Parsear rango de horario del día (`"09:00-18:00"`)
8. Hora ≥ hora_inicio
9. Hora < hora_fin
10. hora + duración ≤ hora_fin (cita no excede cierre)
11. `_is_time_blocked()` — verifica bloqueos (JSON array o CSV)
12. `_check_availability()` — `CONSULTAR_DISPONIBILIDAD` en tiempo real

**Graceful degradation:** si falla obtener horario o disponibilidad, se permite la cita (no bloquea el flujo).

#### `recommendation(fecha_solicitada?, hora_solicitada?)` — Sugerencias

| Entradas | Comportamiento |
|----------|----------------|
| fecha + hora | `CONSULTAR_DISPONIBILIDAD` para ese slot exacto |
| fecha != hoy/mañana | retorna mensaje pidiendo hora preferida |
| fecha = hoy o mañana (sin hora) | `SUGERIR_HORARIOS` |
| Sin parámetros | `SUGERIR_HORARIOS` |

---

### `services/booking.py` — Creación de Eventos

Llama a `ws_calendario.php` (operación `CREAR_EVENTO`).

**Payload enviado:**
```json
{
  "codOpe": "CREAR_EVENTO",
  "usuario_id": 7,
  "id_prospecto": 12345,
  "titulo": "Reunion para el usuario: Juan Pérez",
  "fecha_inicio": "2026-02-21 14:00:00",
  "fecha_fin": "2026-02-21 15:00:00",
  "correo_cliente": "juan@ejemplo.com",
  "correo_usuario": "vendedor@empresa.com",
  "agendar_usuario": 1
}
```

**Respuesta procesada:**
- `google_meet_link` — incluido si la empresa tiene Google Calendar configurado
- `google_calendar_synced` — bool; si `False`, informa al cliente que se contactará con detalles
- Errores mapeados a categorías para métricas: `timeout`, `http_4xx/5xx`, `connection_error`, `unknown_error`

---

### `services/contexto_negocio.py` — Contexto de Negocio

Fetch de la descripción del negocio para inyectar en el system prompt. Implementa el mismo patrón de resiliencia que el orquestador:

| Capa | Implementación |
|------|---------------|
| Cache TTL | `TTLCache(maxsize=500, ttl=3600)` — 1 hora |
| Circuit breaker | `TTLCache(maxsize=500, ttl=300)` — si ≥3 fallos, abre 5 min |
| Retry con backoff | 2 intentos, backoff exponencial (1s, 2s) |

El circuit breaker solo se incrementa en fallos por excepción de red/timeout, **no** cuando la API responde `success: false`.

---

### `services/horario_reuniones.py` — Horario para Prompt

Fetch de `OBTENER_HORARIO_REUNIONES` formateado para el system prompt. Sin cache propio (el cache lo maneja `ScheduleValidator`). Genera texto como:
```
- Lunes: 09:00 - 18:00
- Martes: 09:00 - 18:00
- Sábado: 09:00 - 13:00
- Domingo: Cerrado
```

---

### `services/busqueda_productos.py` — Búsqueda de Catálogo

Implementa `BUSCAR_PRODUCTOS_SERVICIOS_CITAS`. Procesa la respuesta:
- Limpia HTML de descripciones (`re.sub(r"<[^>]+>", ...)`)
- Trunca descripciones a 120 chars
- Formatea precios (`S/. X,XXX.XX`)
- Diferencia productos (precio/unidad) de servicios (precio/sesión)

---

### `services/productos_servicios_citas.py` — Lista para Prompt

Obtiene `OBTENER_NOMBRES_PRODUCTOS_SERVICIOS` para el system prompt (lista de nombres sin detalle). Permite que el agente responda preguntas generales ("¿qué ofrecen?") sin llamar a la tool.

---

### `services/http_client.py` — Cliente HTTP Compartido

Singleton `httpx.AsyncClient` con lazy initialization y connection pool compartido entre todos los servicios:

```python
_client: Optional[httpx.AsyncClient] = None

def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=app_config.API_TIMEOUT,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    return _client
```

Se cierra limpiamente en el lifespan de FastAPI (`close_http_client()`).

---

### `prompts/__init__.py` — Builder del System Prompt

`build_citas_system_prompt(config, history)` es **async** porque lanza 3 fetches en paralelo:

```python
results = await asyncio.gather(
    fetch_horario_reuniones(id_empresa),
    fetch_nombres_productos_servicios(id_empresa),
    fetch_contexto_negocio(id_empresa),
    return_exceptions=True,     # no propaga excepciones individuales
)
```

Variables inyectadas en el template Jinja2:

| Variable | Fuente |
|----------|--------|
| `personalidad` | `context.config.personalidad` (default: "amable, profesional y eficiente") |
| `nombre_bot` | `context.config.nombre_bot` |
| `frase_saludo`, `frase_des`, `frase_no_sabe` | `context.config.*` |
| `fecha_completa`, `fecha_iso`, `hora_actual` | `datetime.now(America/Lima)` |
| `horario_atencion` | `fetch_horario_reuniones()` |
| `lista_productos_servicios` | `fetch_nombres_productos_servicios()` |
| `contexto_negocio` | `fetch_contexto_negocio()` |
| `history`, `has_history` | `history` del parámetro |

---

### `prompts/citas_system.j2` — Template del Agente

Estructura del system prompt:

1. **Identidad** — nombre, personalidad, frases predefinidas
2. **Información del negocio** — `contexto_negocio` (condicional, si existe)
3. **Reglas globales** — no inventar datos, una pregunta a la vez, formato WhatsApp (asterisco simple, no Markdown)
4. **Contexto temporal** — fecha actual Peru, horario de atención, lista de productos/servicios
5. **Lógica de disponibilidad** — 3 casos: solo fecha / fecha+hora / pregunta explícita
6. **Documentación de las 3 tools** — cuándo y cómo llamar cada una
7. **Historial** (condicional `{% if has_history %}`)
8. **Flujo de trabajo** — pasos 1-7 ordenados
9. **Casos especiales** — modificar/cancelar, info insuficiente
10. **Ejemplo de conversación completa**

---

### `validation.py` — Validadores Pydantic

| Modelo | Valida | Notas |
|--------|--------|-------|
| `ContactInfo` | email | Solo email (no teléfono). RFC 5322 simplificado. Normaliza a lowercase |
| `CustomerName` | nombre | Sin números, solo letras/espacios/guiones/apóstrofes. `title()` |
| `BookingDateTime` | fecha + hora | Fecha no en pasado (timezone Peru). Soporta `%I:%M %p`, `%I:%M%p`, `%H:%M` |
| `BookingData` | cita completa | `@model_validator` que compone los 3 validadores anteriores |

Función pública: `validate_booking_data(date, time, customer_name, customer_contact) → (bool, str|None)`

---

### `metrics.py` — Métricas Prometheus

Prefijo de todas las métricas: `agent_citas_*`

**Contadores:**

| Métrica | Labels | Descripción |
|---------|--------|-------------|
| `chat_requests_total` | `empresa_id` | Mensajes recibidos |
| `chat_errors_total` | `error_type` | Errores de procesamiento |
| `booking_attempts_total` | — | Intentos de crear cita |
| `booking_success_total` | — | Citas creadas exitosamente |
| `booking_failed_total` | `reason` | Citas fallidas (timeout, http_4xx, connection_error, ...) |
| `tool_calls_total` | `tool_name` | Invocaciones de tools |
| `tool_errors_total` | `tool_name`, `error_type` | Errores en tools |
| `api_calls_total` | `endpoint`, `status` | Llamadas a APIs externas |

**Histogramas:**

| Métrica | Labels | Buckets |
|---------|--------|---------|
| `chat_response_duration_seconds` | — | 0.1, 0.5, 1, 2, 5, 10, 30, 60, 90 |
| `llm_call_duration_seconds` | — | 0.5, 1, 2, 5, 10, 20, 30, 60, 90 |
| `tool_execution_duration_seconds` | `tool_name` | 0.1, 0.5, 1, 2, 5, 10 |
| `api_call_duration_seconds` | `endpoint` | 0.1, 0.5, 1, 2, 5, 10 |

**Gauge e Info:**

| Métrica | Labels | Descripción |
|---------|--------|-------------|
| `cache_entries` | `cache_type` | Entradas actuales en cache de horarios |
| `agent_citas_info` | — | version, model, agent_type |

**Context managers** para tracking automático: `track_chat_response()`, `track_llm_call()`, `track_tool_execution(tool_name)`, `track_api_call(endpoint)`.

---

### `config/config.py` — Configuración

Carga `.env` buscando hacia arriba en el árbol de directorios (hasta 6 niveles). Usa helpers con validación de tipo y rango: `_get_str`, `_get_int`, `_get_float`, `_get_log_level`. Si un valor es inválido o fuera de rango, usa el default.

---

### `logger.py` — Logging Centralizado

`setup_logging(level, log_file)` configura handlers (stdout siempre, archivo si `LOG_FILE` está configurado) y silencia loggers ruidosos (`httpx`, `httpcore`, `openai`, `langchain`).

Formato de log:
```
2026-02-21 14:32:01 - citas.agent.agent - INFO - [agent.py:376] - [AGENT] Invocando agent - Session: 12345
```

---

## Patrones de Concurrencia y Cache

### Thundering Herd — doble protección

El sistema protege dos recursos críticos con el mismo patrón (double-checked locking async):

| Recurso | Lock | Umbral de limpieza |
|---------|------|--------------------|
| Agente compilado por `id_empresa` | `_agent_cache_locks` | 150 locks |
| Horario de reuniones por `id_empresa` | `_fetch_locks` | 500 locks |

Algoritmo:
```
1. Fast path: ¿está en cache? → retornar (sin lock, atómico en asyncio)
2. Slow path: adquirir asyncio.Lock por clave
3. Double-check dentro del lock (otra coroutine pudo haber llenado el cache)
4. Fetch/creación real solo si sigue siendo miss
5. Guardar en cache y liberar lock
```

### Serialización de sesiones

Cada `session_id` tiene su propio `asyncio.Lock` en `_session_locks`. Garantiza que dos mensajes del mismo usuario (doble-click, reintento rápido) no ejecuten `agent.ainvoke` en paralelo sobre el mismo `thread_id` del `InMemorySaver`.

Limpieza periódica de locks huérfanos cuando se supera el umbral (500 sesiones).

### Mapa completo de cachés

| Cache | Implementación | Clave | TTL | Tamaño máx |
|-------|---------------|-------|-----|------------|
| Agente compilado | `TTLCache` (cachetools) | `id_empresa` | `SCHEDULE_CACHE_TTL_MINUTES * 60` | 100 |
| Horario de reuniones | Dict + threading.Lock | `id_empresa` | `SCHEDULE_CACHE_TTL_MINUTES` min | ilimitado |
| Contexto de negocio | `TTLCache` (cachetools) | `id_empresa` | 3600s (1h) | 500 |
| Circuit breaker contexto | `TTLCache` (cachetools) | `id_empresa` | 300s (5 min, auto-reset) | 500 |

El TTL del agente y el del horario están acoplados: cuando el horario expira, el agente también, garantizando que el próximo mensaje reciba un prompt con datos frescos.

---

## APIs Externas (MaravIA)

### `ws_informacion_ia.php`

| Operación | Llamado desde | Propósito |
|-----------|--------------|-----------|
| `OBTENER_HORARIO_REUNIONES` | `schedule_validator._fetch_schedule()` + `horario_reuniones.fetch_horario_reuniones()` | Horario de atención de la empresa |
| `OBTENER_CONTEXTO_NEGOCIO` | `contexto_negocio.fetch_contexto_negocio()` | Descripción del negocio para el prompt |
| `OBTENER_NOMBRES_PRODUCTOS_SERVICIOS` | `productos_servicios_citas.fetch_nombres_productos_servicios()` | Lista de productos/servicios para el prompt |
| `BUSCAR_PRODUCTOS_SERVICIOS_CITAS` | `busqueda_productos.buscar_productos_servicios()` | Búsqueda específica desde la tool |

### `ws_agendar_reunion.php`

| Operación | Llamado desde | Propósito |
|-----------|--------------|-----------|
| `SUGERIR_HORARIOS` | `schedule_validator.recommendation()` | Sugerencias para hoy/mañana |
| `CONSULTAR_DISPONIBILIDAD` | `schedule_validator._check_availability()` | Verificar si un slot específico está libre |

**Payload CONSULTAR_DISPONIBILIDAD:**
```json
{
  "codOpe": "CONSULTAR_DISPONIBILIDAD",
  "id_empresa": 123,
  "fecha_inicio": "2026-02-21 14:00:00",
  "fecha_fin": "2026-02-21 15:00:00",
  "slots": 60,
  "agendar_usuario": 1,
  "agendar_sucursal": 0
}
```

### `ws_calendario.php`

| Operación | Llamado desde | Propósito |
|-----------|--------------|-----------|
| `CREAR_EVENTO` | `booking.confirm_booking()` | Crear evento en Google Calendar |

**Respuesta CREAR_EVENTO puede incluir:**
- `google_meet_link` — enlace de videollamada (si la empresa tiene GCal configurado)
- `google_calendar_synced` — bool
- `google_calendar_error` — mensaje si falló la sincronización con GCal

---

## Herramientas del LLM

### Cuándo usa cada tool (según el system prompt)

```
Cliente pregunta:
├─ "¿tienen horarios para mañana?"
│   └─ check_availability(date="mañana-iso")         [sin time → SUGERIR_HORARIOS]
│
├─ "¿el viernes a las 3pm están libres?"
│   └─ check_availability(date="viernes-iso", time="3:00 PM")  [CONSULTAR_DISPONIBILIDAD]
│
├─ "el 15 de marzo" (solo fecha)
│   └─ NO llama tool → pregunta "¿a qué hora te vendría bien?"
│      Cuando el cliente responde con hora:
│      └─ check_availability(date="2026-03-15", time="hora")
│
├─ "¿cuánto cuesta el servicio X?" (pregunta específica)
│   └─ search_productos_servicios(busqueda="servicio X")
│
├─ "¿qué servicios tienen?" (pregunta general)
│   └─ NO llama tool → responde con la lista del system prompt
│
└─ Tiene: fecha, hora, nombre, email
    └─ create_booking(date, time, customer_name, customer_contact)
        [solo cuando tiene los 4 datos; pide confirmación antes]
```

### Regla de formato de hora

El system prompt instruye explícitamente: `time` **siempre** con AM/PM (ej. `"3:00 PM"`, `"10:30 AM"`). Sin AM/PM el sistema interpreta la hora como madrugada.

---

## Flujo de Datos Completo

### Caso A: Primera consulta de disponibilidad

```
Gateway → POST /api/chat
  message: "¿Tienen citas para mañana a las 2pm?"
  session_id: 12345
  context.config: {id_empresa: 100, usuario_id: 7, correo_usuario: "v@emp.com"}

main.chat()
  └─ asyncio.wait_for(process_cita_message(), timeout=120s)

process_cita_message()
  ├─ chat_requests_total{empresa_id=100}.inc()
  ├─ [asyncio.Lock session 12345]
  ├─ _validate_context()  →  id_empresa=100 ✓
  ├─ config_data.setdefault("personalidad", "amable, profesional y eficiente")
  │
  ├─ _get_agent(config)
  │   ├─ TTLCache miss → [asyncio.Lock cache_key=(100,)]
  │   │   ├─ init_chat_model("openai:gpt-4o-mini", temp=0.5, max_tokens=2048, timeout=60s)
  │   │   └─ build_citas_system_prompt(config)
  │   │       └─ asyncio.gather(
  │   │             fetch_horario_reuniones(100),          ─► OBTENER_HORARIO_REUNIONES
  │   │             fetch_nombres_productos_servicios(100), ─► OBTENER_NOMBRES_PROD_SERV
  │   │             fetch_contexto_negocio(100)             ─► OBTENER_CONTEXTO_NEGOCIO
  │   │          )
  │   │       └─ render citas_system.j2 con variables
  │   └─ create_agent(model, AGENT_TOOLS, system_prompt, checkpointer=InMemorySaver)
  │      └─ guardado en TTLCache[(100,"amable...")]
  │
  ├─ _prepare_agent_context()
  │   └─ AgentContext(id_empresa=100, session_id=12345, id_prospecto=12345,
  │                    usuario_id=7, correo_usuario="v@emp.com", ...)
  │
  └─ agent.ainvoke(
         messages=[{role:"user", content:"¿Tienen citas para mañana a las 2pm?"}],
         config={configurable:{thread_id:"12345"}},
         context=AgentContext(...)
     )
     │
     [GPT-4o-mini analiza con function calling]
     │
     └─ check_availability(date="2026-02-22", time="2:00 PM", runtime)
         ├─ ctx = runtime.context  →  id_empresa=100, duracion=60, slots=60
         ├─ ScheduleValidator(id_empresa=100, ...)
         └─ recommendation(fecha_solicitada="2026-02-22", hora_solicitada="2:00 PM")
             └─ _check_availability("2026-02-22", "2:00 PM")
                 └─ POST ws_agendar_reunion.php (CONSULTAR_DISPONIBILIDAD)
                     payload: {fecha_inicio:"2026-02-22 14:00:00", fecha_fin:"2026-02-22 15:00:00", ...}
                     response: {"success":true, "disponible":true}
                 └─ return {"text": "El 2026-02-22 a las 2:00 PM está disponible. ¿Confirmamos la cita?"}

     [LLM genera respuesta natural]
     "¡Perfecto! Mañana a las 2:00 PM está disponible.
      Para confirmar, necesito tu nombre completo y correo."

response → {"reply": "¡Perfecto! Mañana a las 2:00 PM está disponible..."}
```

### Caso B: Crear cita (sesión con memoria)

```
Gateway → POST /api/chat  (mismo session_id=12345, segundo mensaje)
  message: "Juan Pérez, juan@email.com"

process_cita_message()
  ├─ _get_agent()  →  TTLCache HIT (mismo (100,"amable..."))
  └─ agent.ainvoke(
         messages=[{role:"user", content:"Juan Pérez, juan@email.com"}],
         config={configurable:{thread_id:"12345"}}   ← InMemorySaver recuerda turno anterior
     )
     │
     [GPT-4o-mini ve en historial: fecha=2026-02-22, hora=2:00 PM ya acordados]
     │
     └─ create_booking(date="2026-02-22", time="2:00 PM",
                       customer_name="Juan Pérez", customer_contact="juan@email.com",
                       runtime)
         │
         ├─ [Capa 1] validate_booking_data()
         │   ├─ ContactInfo("juan@email.com")  →  email válido ✓
         │   ├─ CustomerName("Juan Pérez")  →  capitalizado ✓
         │   └─ BookingDateTime("2026-02-22","2:00 PM")  →  futuro ✓
         │
         ├─ [Capa 2] ScheduleValidator.validate("2026-02-22","2:00 PM")
         │   ├─ _fetch_schedule(100)  →  cache HIT (ya cargado en Caso A)
         │   ├─ Sábado → reunion_sabado = "09:00-13:00"
         │   ├─ 14:00 >= 09:00 ✓  |  14:00 < 13:00 ✗
         │   └─ return {"valid":False, "error":"La hora seleccionada es después del horario..."}
         │
         └─ return "La hora seleccionada es después del horario de atención.
                    El horario del sábado es de 09:00 AM a 01:00 PM.
                    Por favor elige una hora más temprana."

     [LLM propone alternativa al usuario]
```

### Caso C: Imagen en el mensaje

```
message: "¿Pueden hacer esto? https://ejemplo.com/diseno.jpg lo quiero para el viernes"

_build_content(message)
  └─ URLs detectadas: ["https://ejemplo.com/diseno.jpg"]
     texto: "¿Pueden hacer esto? lo quiero para el viernes"
     return [
       {"type":"text", "text":"¿Pueden hacer esto? lo quiero para el viernes"},
       {"type":"image_url", "image_url":{"url":"https://ejemplo.com/diseno.jpg"}}
     ]

→ agent.ainvoke recibe bloque multimodal
→ GPT-4o-mini analiza imagen + texto con Vision
```

---

## Patrones de Diseño

| Patrón | Dónde | Propósito |
|--------|-------|-----------|
| **Factory + Cache** | `agent._get_agent()` | Agente compilado por empresa, evita recreación |
| **Double-Checked Locking** | `_get_agent()` + `_fetch_schedule()` | Serializar primera creación sin bloquear hot path |
| **Singleton** | `http_client.get_client()` | Connection pool compartido entre servicios |
| **Circuit Breaker** | `contexto_negocio.py` | Protege ante API de contexto inestable |
| **Retry + Backoff** | `contexto_negocio.py` | 2 reintentos con espera exponencial |
| **Runtime Context Injection** | `tools.py` (LangChain 1.2+) | AgentContext inyectado en tools sin parámetros explícitos |
| **Graceful Degradation** | `schedule_validator.py`, `tools.py` | Si falla API no crítica, continúa el flujo |
| **Strategy** (validación) | `tools.create_booking()` | 3 capas secuenciales independientes |
| **Observer** | `metrics.py` | Context managers trackean sin modificar lógica de negocio |
| **Template Method** | `citas_system.j2` | Estructura del prompt fija, variables inyectadas |
| **Repository** | `schedule_validator._fetch_schedule()` | Cache transparente al consumidor |

---

## Grafo de Dependencias

```
config/config.py           (nivel 0 — sin dependencias internas)
   ↑
   ├── logger.py            (nivel 1)
   ├── metrics.py           (nivel 1)
   └── config/models.py     (nivel 1)
            ↑
            ├── validation.py              (nivel 2)
            ├── services/http_client.py    (nivel 2)
            │       ↑
            │   ┌───┴─────────────────────────────────────────┐
            │   ├── services/schedule_validator.py            │
            │   ├── services/booking.py                       │
            │   ├── services/horario_reuniones.py             │
            │   ├── services/busqueda_productos.py            │
            │   ├── services/contexto_negocio.py              │
            │   └── services/productos_servicios_citas.py     │
            │                           (nivel 3)             │
            └─────────────────────────────────────────────────┘
                            ↑
                    tool/tools.py          (nivel 4)
                            ↑
                    prompts/__init__.py    (nivel 4, paralelo)
                            ↑
                    agent/agent.py         (nivel 5)
                            ↑
                    main.py                (nivel 6)
                            ↑
                    Gateway Go (externo)
```

**Total de módulos propios:** 16 archivos Python en `src/citas/` (excluyendo `__init__.py` vacíos y `.j2`).

---

## Limitaciones Conocidas

| Limitación | Impacto | Solución recomendada |
|------------|---------|---------------------|
| `InMemorySaver` volátil | Memoria se pierde al reiniciar o en multi-instancia | Migrar a `PostgresSaver` o `RedisSaver` (LangGraph) |
| Sin rate limiting | Riesgo en producción pública | Agregar middleware FastAPI o proxy (nginx) |
| Sin tests automatizados | Regresiones difíciles de detectar | Pytest + httpx.AsyncClient |
| Locks en memoria | No funciona en multi-proceso | Migrar a Redis distributed lock |
| Horario cache sin persistencia | Cold start hace fetch siempre | Precalentar cache en startup |

---

**Versión del documento:** 2.0.0
**Última actualización:** 2026-02-21
