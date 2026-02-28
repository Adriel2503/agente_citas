# Arquitectura — Agent Citas v2.1.0

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
11. [Limitaciones Conocidas](#limitaciones-conocidas)
12. [Resiliencia](#resiliencia)

---

## Visión General

**Agent Citas** es un microservicio asíncrono de IA que automatiza la gestión de citas y reuniones comerciales. Funciona como un **closer digital 24/7** que guía prospectos hasta confirmar una reunión de venta.

| Atributo | Valor |
|----------|-------|
| Versión | 2.1.0 |
| Lenguaje | Python 3.12 (Dockerfile) |
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
| Retry | tenacity | `>=8.2.0` | Retry con backoff exponencial |
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
│  │          │  │   ├── fetch_contexto_negocio  │  contexto +│   │
│  │          │  │   └── fetch_preguntas_frecuentes FAQs   │    │
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
│  │              post_with_retry → post_with_logging          │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                             │                                    │
│  ┌──────────────────────────┴───────────────────────────────┐  │
│  │              circuit_breaker.py + _resilience.py           │  │
│  │  informacion_cb │ preguntas_cb │ calendario_cb │ agendar_cb│  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                  APIs EXTERNAS MaravIA                           │
│                                                                  │
│  ws_informacion_ia.php  [CB: informacion_cb, key=id_empresa]    │
│  ├─ OBTENER_HORARIO_REUNIONES       (horario_cache, prompt)     │
│  ├─ OBTENER_CONTEXTO_NEGOCIO        (contexto_negocio, prompt)  │
│  ├─ OBTENER_NOMBRES_PRODUCTOS_SERV. (productos_servicios, prompt)│
│  └─ BUSCAR_PRODUCTOS_SERVICIOS_CITAS (busqueda_productos, tool) │
│                                                                  │
│  ws_preguntas_frecuentes.php  [CB: preguntas_cb, key=id_chatbot]│
│  └─ FAQs por id_chatbot     (preguntas_frecuentes, prompt)      │
│                                                                  │
│  ws_agendar_reunion.php  [CB: agendar_reunion_cb, key=id_empresa]│
│  ├─ CONSULTAR_DISPONIBILIDAD  (schedule_validator._check_avail.)│
│  └─ SUGERIR_HORARIOS          (schedule_validator.recommendation)│
│                                                                  │
│  ws_calendario.php  [CB: calendario_cb, key="global"]           │
│  └─ CREAR_EVENTO              (booking.confirm_booking)         │
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
    message: str = Field(..., min_length=1, max_length=4096)
    session_id: int          # int ≥ 0 (unificado con gateway)
    context: dict[str, Any] | None = None  # context.config.id_empresa requerido

class ChatResponse(BaseModel):
    reply: str
    url: str | None = None   # Google Meet link, imagen de saludo, o null
```

**Manejo de errores en el endpoint (todos retornan HTTP 200 excepto CancelledError):**
- `asyncio.TimeoutError` → mensaje de timeout (`CHAT_TIMEOUT`, default 120s)
- `ValueError` → error de configuración (falta `id_empresa`)
- `asyncio.CancelledError` → re-raise (no se contabiliza en métricas)
- `Exception` → error genérico

**Métricas por request:** `citas_http_requests_total{status}` (success/timeout/error) y `citas_http_duration_seconds`.

**Lifespan:** Cierra el cliente HTTP compartido (`close_http_client()`) al apagar el servidor.

---

### `agent/agent.py` — Lógica Central del Agente

Módulo más complejo. Gestiona el ciclo de vida del agente LangChain, la memoria por sesión y la concurrencia multiempresa.

#### Componentes globales

```python
_checkpointer = InMemorySaver()      # Memoria global por thread_id (pendiente Redis)
_model = None                         # LLM singleton compartido por todas las empresas

# Cache de agentes compilados por id_empresa
# TTL = AGENT_CACHE_TTL_MINUTES * 60 (default 60 min, INDEPENDIENTE del cache de horarios)
_agent_cache: TTLCache = TTLCache(maxsize=AGENT_CACHE_MAXSIZE, ttl=AGENT_CACHE_TTL_MINUTES*60)

# Locks para evitar thundering herd al crear agentes (1 lock por cache_key)
# Se eliminan con pop() en finally después de cada creación
_agent_cache_locks: dict[tuple, asyncio.Lock] = {}
_LOCKS_CLEANUP_THRESHOLD = 750  # Red de seguridad (nunca se activa con < 50 empresas)

# Locks para serializar requests concurrentes del mismo usuario (doble-click)
_session_locks: dict[int, asyncio.Lock] = {}
_SESSION_LOCKS_CLEANUP_THRESHOLD = 500  # Se activa cuando hay muchas sesiones acumuladas
```

**Modelo LLM:** `_model` es un singleton inicializado con `init_chat_model()` en la primera llamada. Es síncrono y compartido por todas las empresas (la config viene de variables de entorno globales, no por empresa).

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

1. **Fast path**: busca en `_agent_cache` por `(id_empresa,)` → retorna directo si hit
2. **Slow path** (double-checked locking):
   - Adquiere `asyncio.Lock` por `cache_key` (evita thundering herd)
   - Double-check tras adquirir el lock
   - `_get_model()` → singleton LLM
   - `build_citas_system_prompt(config)` → async (4 fetches en paralelo)
   - `create_agent(model, tools, system_prompt, checkpointer, response_format)`
   - Guarda en `_agent_cache`
   - `finally: pop()` elimina el lock (solo sirve durante la creación)

**TTL desacoplado:** El cache del agente (`AGENT_CACHE_TTL_MINUTES`, default 60 min) es **independiente** del cache de horarios (`SCHEDULE_CACHE_TTL_MINUTES`, default 5 min). El prompt (contexto, FAQs, nombres de productos) cambia raramente → TTL largo. La validación de horarios usa `horario_cache` directamente en cada tool call, siempre fresca.

**response_format:** `CitaStructuredResponse(reply: str, url: str | None)` — el agente siempre retorna JSON estructurado con los dos campos.

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
1. Validar message (no vacío) → ("No recibí tu mensaje...", None)
2. Validar session_id ≥ 0 → raise ValueError
3. Registrar métrica: chat_requests_total{empresa_id}
4. Adquirir asyncio.Lock por session_id (serializa doble-click)
5. _validate_context(context) → requiere context.config.id_empresa
6. config_data.setdefault("personalidad", "amable, profesional y eficiente")
7. _get_agent(config_data)    → agente desde cache o nuevo
8. _prepare_agent_context()   → construir AgentContext con valores del gateway
9. agent.ainvoke(
       messages=[{role: "user", content: _build_content(message)}],
       config={configurable: {thread_id: str(session_id)}},
       context=agent_context
   )
10. Extraer structured_response (CitaStructuredResponse) → (reply, url)
    Fallback: último mensaje de result["messages"] → (reply, None)
11. Retornar tupla (reply, url)
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

**Fallback**: Si falla la API, retorna: `"No pude obtener sugerencias ahora. Indica una fecha y hora que prefieras y la verifico."`

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

**Responsabilidades:** validar fecha/hora contra horario de la empresa, consultar disponibilidad en tiempo real, generar sugerencias.

**No tiene cache propio** — usa `horario_cache.py` (TTLCache compartido) para obtener horarios.

#### `validate(fecha_str, hora_str)` — 12 validaciones secuenciales

1. Parsear fecha (`%Y-%m-%d`)
2. Parsear hora (soporta `%I:%M %p`, `%I:%M%p`, `%H:%M`)
3. Combinar fecha+hora en datetime
4. Verificar que no sea en el pasado (zona `America/Lima`)
5. `get_horario(id_empresa)` — obtiene horario desde `horario_cache.py`
6. Verificar campo del día (`reunion_lunes` … `reunion_domingo`)
7. Verificar que el día no esté marcado como cerrado (`"NO DISPONIBLE"`, `"CERRADO"`, etc.)
8. Parsear rango de horario del día (`"09:00-18:00"`)
9. Hora ≥ hora_inicio (antes de apertura)
10. Hora < hora_fin (después de cierre)
11. hora + duración ≤ hora_fin (cita no excede cierre)
12. `_check_availability()` → `CONSULTAR_DISPONIBILIDAD` via `resilient_call` + `agendar_reunion_cb`

**Graceful degradation:** si falla obtener horario o disponibilidad, se permite la cita (no bloquea el flujo). El circuit breaker `agendar_reunion_cb` protege `ws_agendar_reunion.php`.

#### `recommendation(fecha_solicitada?, hora_solicitada?)` — Sugerencias

| Entradas | Comportamiento |
|----------|----------------|
| fecha + hora | `CONSULTAR_DISPONIBILIDAD` para ese slot exacto |
| fecha != hoy/mañana (sin hora) | Retorna: "Para esa fecha indica una hora que prefieras y la verifico" |
| fecha = hoy o mañana (sin hora) | `SUGERIR_HORARIOS` via `ws_agendar_reunion.php` |
| Error/fallback | "No pude obtener sugerencias ahora. Indica una fecha y hora..." |

---

### `services/horario_cache.py` — Cache Compartido de Horarios

TTLCache compartido para `OBTENER_HORARIO_REUNIONES`. Usado por `schedule_validator` (validación) y `horario_reuniones` (prompt).

```python
_horario_cache: TTLCache = TTLCache(maxsize=256, ttl=SCHEDULE_CACHE_TTL_MINUTES * 60)
_fetch_locks: dict[int, asyncio.Lock] = {}  # 1 lock por id_empresa
```

`get_horario(id_empresa)` implementa double-checked locking async:
1. Cache hit → retorna directo (sin lock)
2. Cache miss → `asyncio.Lock` por id_empresa
3. Double-check dentro del lock
4. `resilient_call` → `post_with_logging` → `ws_informacion_ia.php`
5. `finally: _fetch_locks.pop()` — limpia lock después de cada fetch

Usa `informacion_cb` (circuit breaker compartido con contexto_negocio y productos).

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

### `services/circuit_breaker.py` — Circuit Breakers

Define la clase `CircuitBreaker` y 4 singletons de módulo. Estados: CLOSED → OPEN → (TTL expiry) → CLOSED.

```python
class CircuitBreaker:
    def __init__(self, name, threshold=3, reset_ttl=300):
        self._failures: TTLCache = TTLCache(maxsize=500, ttl=reset_ttl)
```

| Método | Propósito |
|--------|-----------|
| `is_open(key)` | True si fallos ≥ threshold para esa key |
| `record_failure(key)` | Incrementa contador (solo llamar ante `TransportError`) |
| `record_success(key)` | Resetea contador (circuit cierra) |
| `any_open()` | True si alguna key está abierta (usado por `/health`) |

---

### `services/_resilience.py` — Wrapper de Resiliencia

Función `resilient_call(coro_factory, cb, circuit_key, service_name)`:
- CB abierto → `RuntimeError` inmediato
- Éxito → `cb.record_success()`
- `httpx.TransportError` → `cb.record_failure()` + re-raise
- Otros errores → re-raise sin afectar CB

Usado por: `horario_cache`, `contexto_negocio`, `preguntas_frecuentes`, `busqueda_productos`, `schedule_validator`.

---

### `services/contexto_negocio.py` — Contexto de Negocio

Fetch de la descripción del negocio para inyectar en el system prompt. Mismo patrón anti-thundering herd que `horario_cache.py`:

```python
_contexto_cache: TTLCache = TTLCache(maxsize=500, ttl=3600)   # 1 hora por id_empresa
_fetch_locks: dict[Any, asyncio.Lock] = {}                     # 1 lock por id_empresa
```

| Capa | Implementación |
|------|---------------|
| Cache TTL | `TTLCache(maxsize=500, ttl=3600)` — 1 hora |
| Anti-thundering herd | `asyncio.Lock` por id_empresa, double-checked locking, `pop()` en finally |
| Fast reject | `informacion_cb.is_open(id_empresa)` antes de adquirir lock |
| Circuit breaker | `informacion_cb` compartido (vía `resilient_call`) |
| Retry con backoff | `post_with_logging` → `post_with_retry` (tenacity, configurable) |

Flujo: cache hit → fast reject CB → lock → double-check → `resilient_call(post_with_logging(...), cb=informacion_cb)` → cachear → `pop()` lock.

---

### `services/horario_reuniones.py` — Horario para Prompt

Formatea el horario de reuniones para el system prompt. **No tiene cache propio** — delega a `horario_cache.get_horario(id_empresa)` que gestiona TTLCache + fetch.

```python
async def fetch_horario_reuniones(id_empresa) -> str:
    horario = await get_horario(id_empresa)  # horario_cache.py
    return format_horario_for_system_prompt(horario)
```

Genera texto como:
```
- Lunes: 09:00 - 18:00
- Martes: 09:00 - 18:00
- Sábado: 09:00 - 13:00
- Domingo: Cerrado
```

---

### `services/preguntas_frecuentes.py` — FAQs para Prompt

Fetch de preguntas frecuentes desde `ws_preguntas_frecuentes.php`. Mismo patrón que `contexto_negocio.py`:

```python
_preguntas_cache: TTLCache = TTLCache(maxsize=500, ttl=3600)   # 1 hora por id_chatbot
_fetch_locks: dict[Any, asyncio.Lock] = {}                     # 1 lock por id_chatbot
```

**Nota:** Usa `id_chatbot` (no `id_empresa`) como clave de cache y CB (`preguntas_cb`).

Formatea la respuesta como pares `Pregunta:/Respuesta:` para que el LLM entienda el formato y adapte respuestas similares.

---

### `services/busqueda_productos.py` — Búsqueda de Catálogo

Implementa `BUSCAR_PRODUCTOS_SERVICIOS_CITAS` con cache más agresivo:

```python
_busqueda_cache: TTLCache = TTLCache(maxsize=2000, ttl=900)    # 15 min por (id_empresa, término)
_busqueda_locks: dict[tuple, asyncio.Lock] = {}                 # 1 lock por cache_key
```

Procesamiento de respuesta:
- Limpia HTML de descripciones (`re.sub(r"<[^>]+>", ...)`)
- Trunca descripciones a 120 chars
- Formatea precios (`S/. X,XXX.XX`)
- Diferencia productos (precio/unidad) de servicios (precio/sesión)
- Máximo 10 resultados por búsqueda (`MAX_RESULTADOS`)

Usa `informacion_cb` (mismo que horario, contexto, productos). Métricas: `SEARCH_CACHE` (hit/miss/circuit_open).

---

### `services/productos_servicios_citas.py` — Lista para Prompt

Obtiene `OBTENER_NOMBRES_PRODUCTOS_SERVICIOS` para el system prompt (lista de nombres sin detalle). Permite que el agente responda preguntas generales ("¿qué ofrecen?") sin llamar a la tool.

---

### `services/http_client.py` — Cliente HTTP Compartido

Singleton `httpx.AsyncClient` con lazy initialization, timeouts granulares y connection pool compartido:

```python
_client = httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=5.0,                     # Conexión TCP
        read=app_config.API_TIMEOUT,     # Lectura de respuesta (default 30s)
        write=5.0,                       # Escritura del body
        pool=2.0,                        # Espera en el pool
    ),
    limits=httpx.Limits(
        max_connections=50,              # Total de conexiones concurrentes
        max_keepalive_connections=20,    # Conexiones keep-alive
        keepalive_expiry=30.0,          # Expiración keep-alive (segundos)
    ),
    headers={"Content-Type": "application/json", "Accept": "application/json"},
)
```

**Funciones exportadas:**

| Función | Propósito | Retry | Uso |
|---------|-----------|-------|-----|
| `get_client()` | Singleton lazy del AsyncClient | — | Acceso directo (booking.py) |
| `post_with_retry(url, json)` | POST con retry automático (tenacity) | Sí: `HTTP_RETRY_ATTEMPTS` intentos, backoff exponencial `HTTP_RETRY_WAIT_MIN`–`HTTP_RETRY_WAIT_MAX` | Solo operaciones de LECTURA idempotentes |
| `post_with_logging(url, payload)` | Wrapper sobre `post_with_retry` con logging DEBUG | Sí (hereda) | Servicios vía `resilient_call()` |
| `close_http_client()` | Cierra el cliente. Llamado en lifespan de FastAPI | — | `main.py` teardown |

**Retry (tenacity):** solo reintenta `httpx.TransportError` (timeouts, connection errors). **No** reintenta `httpx.HTTPStatusError` (respuestas 4xx/5xx).

**ADVERTENCIA:** `post_with_retry`/`post_with_logging` **no** deben usarse para operaciones de escritura (ej. `CREAR_EVENTO`) por riesgo de duplicados si el servidor recibió la request pero la respuesta timeouteó. Para escrituras usar `client.post()` directamente.

---

### `prompts/__init__.py` — Builder del System Prompt

`build_citas_system_prompt(config, history)` es **async** porque lanza **4 fetches** en paralelo:

```python
results = await asyncio.gather(
    fetch_horario_reuniones(id_empresa),
    fetch_nombres_productos_servicios(id_empresa),
    fetch_contexto_negocio(id_empresa),
    fetch_preguntas_frecuentes(id_chatbot),   # keyed por id_chatbot, no id_empresa
    return_exceptions=True,     # no propaga excepciones individuales
)
```

Cada fetch que falla retorna un valor por defecto (graceful degradation): `"No hay horario cargado."`, `([], [])`, `None`, `""`.

Variables inyectadas en el template Jinja2:

| Variable | Fuente |
|----------|--------|
| `personalidad` | `context.config.personalidad` (default: "amable, profesional y eficiente") |
| `nombre_bot` | `context.config.nombre_bot` |
| `frase_saludo`, `frase_des`, `frase_no_sabe` | `context.config.*` |
| `archivo_saludo` | `context.config.archivo_saludo` (URL de imagen/video de saludo) |
| `fecha_completa`, `fecha_iso`, `hora_actual` | `datetime.now(America/Lima)` |
| `horario_atencion` | `fetch_horario_reuniones(id_empresa)` |
| `nombres_productos`, `nombres_servicios` | `fetch_nombres_productos_servicios(id_empresa)` |
| `lista_productos_servicios` | `format_nombres_para_prompt(productos, servicios)` |
| `contexto_negocio` | `fetch_contexto_negocio(id_empresa)` |
| `preguntas_frecuentes` | `fetch_preguntas_frecuentes(id_chatbot)` |
| `history`, `has_history` | `history` del parámetro |

---

### `prompts/citas_system.j2` — Template del Agente

Estructura del system prompt (Jinja2):

1. **Identidad** — nombre, personalidad, frases predefinidas (saludo, despedida, no sabe, frustración)
2. **Respuesta: campos reply y url** — instrucciones para `CitaStructuredResponse`. Si hay `archivo_saludo`, usarla como `url` solo en el primer mensaje
3. **Información del negocio** — `contexto_negocio` (condicional `{% if contexto_negocio %}`)
4. **Preguntas frecuentes** — `preguntas_frecuentes` (condicional `{% if preguntas_frecuentes %}`). Formato Pregunta:/Respuesta: para que el LLM adapte respuestas similares
5. **Reglas globales** — no inventar datos, una pregunta a la vez, formato WhatsApp (asterisco simple, no Markdown)
6. **Formato WhatsApp** — símbolos completos: negrita `*`, cursiva `_`, tachado `~`, viñetas, numeradas, monoespaciado, citas
7. **Contexto temporal** — fecha actual Peru, horario de atención, lista de productos/servicios
8. **Lógica de disponibilidad** — 3 casos: solo fecha / fecha+hora / pregunta explícita
9. **Documentación de las 3 tools** — cuándo y cómo llamar cada una, con regla AM/PM obligatorio
10. **Historial** (condicional `{% if has_history %}`)
11. **Flujo de trabajo** — pasos 1-7 ordenados
12. **Casos especiales** — modificar/cancelar, info insuficiente
13. **Ejemplo de conversación completa**

---

### `validation.py` — Validadores Pydantic

Un solo modelo `BookingData` con `@field_validator` por campo:

```python
class BookingData(BaseModel):
    date: str             # @field_validator → _check_date
    time: str             # @field_validator → _check_time
    customer_name: str    # @field_validator → _check_name
    customer_contact: str # @field_validator → _check_email
```

| Validador | Campo | Reglas |
|-----------|-------|--------|
| `_check_email` | `customer_contact` | RFC 5322 simplificado (regex), max 254 chars, normaliza a lowercase |
| `_check_name` | `customer_name` | Sin números, solo letras/espacios/guiones/apóstrofes, min 2 chars, `title()` |
| `_check_date` | `date` | Formato `%Y-%m-%d`, no en el pasado (timezone `America/Lima`) |
| `_check_time` | `time` | Soporta `%I:%M %p`, `%I:%M%p`, `%H:%M`. Normaliza a uppercase |

**Funciones públicas:**
- `validate_booking_data(date, time, customer_name, customer_contact) → (bool, str|None)` — valida cita completa
- `validate_date_format(date) → (bool, str|None)` — solo formato YYYY-MM-DD (sin verificar pasado)

---

### `metrics.py` — Métricas Prometheus

Dos prefijos: `agent_citas_*` (métricas de negocio) y `citas_*` (métricas HTTP/infraestructura).

**Contadores:**

| Métrica | Prefijo | Labels | Descripción |
|---------|---------|--------|-------------|
| `chat_requests_total` | `agent_citas_` | `empresa_id` | Mensajes recibidos |
| `chat_errors_total` | `agent_citas_` | `error_type` | Errores de procesamiento |
| `booking_attempts_total` | `agent_citas_` | — | Intentos de crear cita |
| `booking_success_total` | `agent_citas_` | — | Citas creadas exitosamente |
| `booking_failed_total` | `agent_citas_` | `reason` | Citas fallidas (timeout, http_4xx, connection_error, ...) |
| `tool_calls_total` | `agent_citas_` | `tool_name` | Invocaciones de tools |
| `tool_errors_total` | `agent_citas_` | `tool_name`, `error_type` | Errores en tools |
| `api_calls_total` | `agent_citas_` | `endpoint`, `status` | Llamadas a APIs externas |
| `http_requests_total` | `citas_` | `status` (success/timeout/error) | Requests al endpoint /api/chat |
| `agent_cache_total` | `citas_` | `result` (hit/miss) | Hits y misses del cache de agente |
| `search_cache_total` | `citas_` | `result` (hit/miss/circuit_open) | Cache de búsqueda de productos |

**Histogramas:**

| Métrica | Prefijo | Labels | Buckets |
|---------|---------|--------|---------|
| `http_duration_seconds` | `citas_` | — | 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 90, 120 |
| `chat_response_duration_seconds` | `agent_citas_` | `status` (success/error) | 0.1, 0.5, 1, 2, 5, 10, 30, 60, 90 |
| `llm_call_duration_seconds` | `agent_citas_` | `status` (success/error) | 0.5, 1, 2, 5, 10, 20, 30, 60, 90 |
| `tool_execution_duration_seconds` | `agent_citas_` | `tool_name` | 0.1, 0.5, 1, 2, 5, 10, 20, 30 |
| `api_call_duration_seconds` | `agent_citas_` | `endpoint` | 0.1, 0.25, 0.5, 1, 2.5, 5, 10 |

**Gauge e Info:**

| Métrica | Labels | Descripción |
|---------|--------|-------------|
| `agent_citas_cache_entries` | `cache_type` | Entradas actuales en cache |
| `agent_citas_info` | — | version, model, agent_type |

**Context managers** para tracking automático (decoran lógica de negocio sin modificarla):
- `track_chat_response()` — duración + status (success/error)
- `track_llm_call()` — duración + status del LLM
- `track_tool_execution(tool_name)` — duración + error_type si falla
- `track_api_call(endpoint)` — duración + status de APIs externas

**Funciones helper:** `record_booking_attempt()`, `record_booking_success()`, `record_booking_failure(reason)`, `record_chat_error(error_type)`, `update_cache_stats(cache_type, count)`, `initialize_agent_info(model, version)`.

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

### Thundering Herd — anti-stampede en 5 recursos

El sistema protege 5 recursos con el mismo patrón (double-checked locking async + `pop()` en finally):

| Recurso | Lock dict | Ubicación | Clave |
|---------|-----------|-----------|-------|
| Agente compilado | `_agent_cache_locks` | `agent.py` | `(id_empresa,)` |
| Horario de reuniones | `_fetch_locks` | `horario_cache.py` | `id_empresa` |
| Contexto de negocio | `_fetch_locks` | `contexto_negocio.py` | `id_empresa` |
| Preguntas frecuentes | `_fetch_locks` | `preguntas_frecuentes.py` | `id_chatbot` |
| Búsqueda de productos | `_busqueda_locks` | `busqueda_productos.py` | `(id_empresa, término)` |

Algoritmo (idéntico en los 5):
```
1. Fast path: ¿está en cache? → retornar (sin lock, atómico en asyncio)
2. [Opcional] Fast reject: ¿circuit breaker abierto? → fallback sin red
3. Slow path: adquirir asyncio.Lock por clave
4. Double-check dentro del lock (otra coroutine pudo haber llenado el cache)
5. Fetch/creación real solo si sigue siendo miss
6. Guardar en cache
7. finally: pop() elimina el lock (solo sirve durante la creación)
```

Los locks se eliminan con `pop()` en `finally` inmediatamente después de cada fetch/creación. Esto significa que **nunca se acumulan** en operación normal (< 50 empresas). Los umbrales de limpieza en `agent.py` (750 para agent locks, 500 para session locks) son redes de seguridad que nunca se activan en la práctica.

### Serialización de sesiones

Cada `session_id` tiene su propio `asyncio.Lock` en `_session_locks`. Garantiza que dos mensajes del mismo usuario (doble-click, reintento rápido) no ejecuten `agent.ainvoke` en paralelo sobre el mismo `thread_id` del `InMemorySaver`.

Limpieza periódica de locks huérfanos cuando `_session_locks` supera 500 entradas.

### Mapa completo de cachés

| Cache | Implementación | Clave | TTL | Tamaño máx |
|-------|---------------|-------|-----|------------|
| Agente compilado | `TTLCache` (cachetools) | `(id_empresa,)` | `AGENT_CACHE_TTL_MINUTES * 60` (default 60 min) | `AGENT_CACHE_MAXSIZE` (500) |
| Horario de reuniones | `TTLCache` (cachetools) | `id_empresa` | `SCHEDULE_CACHE_TTL_MINUTES * 60` (default 5 min) | 256 |
| Contexto de negocio | `TTLCache` (cachetools) | `id_empresa` | 3600s (1 hora) | 500 |
| Preguntas frecuentes | `TTLCache` (cachetools) | `id_chatbot` | 3600s (1 hora) | 500 |
| Búsqueda de productos | `TTLCache` (cachetools) | `(id_empresa, término)` | 900s (15 min) | 2000 |
| Circuit breakers (x4) | `TTLCache` (cachetools) | ver CB | `CB_RESET_TTL` (default 300s) | 500 |

**TTL desacoplados:** El cache del agente (`AGENT_CACHE_TTL_MINUTES`, default 60 min) es **independiente** del cache de horarios (`SCHEDULE_CACHE_TTL_MINUTES`, default 5 min). El prompt (contexto, FAQs, nombres) cambia raramente → TTL largo. La validación de horarios usa `horario_cache` en cada tool call → siempre fresca.

---

## APIs Externas (MaravIA)

### `ws_informacion_ia.php` — CB: `informacion_cb` (key: `id_empresa`)

| Operación | Llamado desde | Propósito |
|-----------|--------------|-----------|
| `OBTENER_HORARIO_REUNIONES` | `horario_cache.get_horario()` → usado por `schedule_validator` y `horario_reuniones` | Horario de atención de la empresa |
| `OBTENER_CONTEXTO_NEGOCIO` | `contexto_negocio.fetch_contexto_negocio()` | Descripción del negocio para el prompt |
| `OBTENER_NOMBRES_PRODUCTOS_SERVICIOS` | `productos_servicios_citas.fetch_nombres_productos_servicios()` | Lista de productos/servicios para el prompt |
| `BUSCAR_PRODUCTOS_SERVICIOS_CITAS` | `busqueda_productos.buscar_productos_servicios()` | Búsqueda específica desde la tool |

### `ws_preguntas_frecuentes.php` — CB: `preguntas_cb` (key: `id_chatbot`)

| Operación | Llamado desde | Propósito |
|-----------|--------------|-----------|
| FAQs por `id_chatbot` | `preguntas_frecuentes.fetch_preguntas_frecuentes()` | Preguntas frecuentes para el prompt |

**Payload:** `{"id_chatbot": 456}` — **Nota:** usa `id_chatbot` (no `id_empresa`).

**Respuesta:** `{"success": true, "preguntas_frecuentes": [{"pregunta": "...", "respuesta": "..."}]}`.

### `ws_agendar_reunion.php` — CB: `agendar_reunion_cb` (key: `id_empresa`)

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

### `ws_calendario.php` — CB: `calendario_cb` (key: `"global"`)

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
  │   │             fetch_contexto_negocio(100),            ─► OBTENER_CONTEXTO_NEGOCIO
  │   │             fetch_preguntas_frecuentes(id_chatbot)  ─► FAQs
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
| **Double-Checked Locking** | `_get_agent()`, `horario_cache`, `contexto_negocio`, `preguntas_frecuentes`, `busqueda_productos` | Serializar primera creación sin bloquear hot path |
| **Singleton** | `http_client.get_client()`, `_model` (LLM) | Connection pool y modelo compartidos |
| **Circuit Breaker** | `circuit_breaker.py` — 4 CBs: `informacion_cb`, `preguntas_cb`, `calendario_cb`, `agendar_reunion_cb` | Protege ante APIs inestables, auto-reset por TTL |
| **Resilient Call** | `_resilience.py` → todos los servicios con CB | Wrapper: CB check → execute → record success/failure |
| **Retry + Backoff** | `http_client.post_with_retry()` (tenacity) | Configurable: `HTTP_RETRY_ATTEMPTS`, `HTTP_RETRY_WAIT_MIN/MAX` |
| **Runtime Context Injection** | `tools.py` (LangChain 1.2+) | AgentContext inyectado en tools sin parámetros explícitos |
| **Graceful Degradation** | `schedule_validator.py`, `tools.py`, `prompts/__init__.py` | Si falla API no crítica, continúa con fallback |
| **Strategy** (validación) | `tools.create_booking()` | 3 capas secuenciales independientes |
| **Observer** | `metrics.py` | Context managers trackean sin modificar lógica de negocio |
| **Template Method** | `citas_system.j2` | Estructura del prompt fija, variables inyectadas |
| **Repository** | `horario_cache.get_horario()` | Cache transparente al consumidor |

---

## Grafo de Dependencias

```
config/config.py                        (nivel 0 — sin dependencias internas)
   ↑
   ├── logger.py                         (nivel 1)
   ├── metrics.py                        (nivel 1)
   └── config/__init__.py                (nivel 1 — re-exporta variables)
            ↑
            ├── validation.py                          (nivel 2)
            ├── services/http_client.py                (nivel 2 — tenacity retry)
            ├── services/circuit_breaker.py             (nivel 2 — 4 CB singletons)
            │       ↑
            │   services/_resilience.py                 (nivel 2.5 — resilient_call)
            │       ↑
            │   ┌───┴─────────────────────────────────────────┐
            │   ├── services/horario_cache.py                 │
            │   ├── services/horario_reuniones.py             │
            │   ├── services/schedule_validator.py            │
            │   ├── services/booking.py                       │
            │   ├── services/busqueda_productos.py            │
            │   ├── services/contexto_negocio.py              │
            │   ├── services/preguntas_frecuentes.py          │
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

**Total de módulos propios:** 19 archivos Python en `src/citas/` (excluyendo `__init__.py` vacíos y `.j2`).

---

## Limitaciones Conocidas

| Limitación | Impacto | Solución recomendada | Prioridad |
|------------|---------|---------------------|-----------|
| `InMemorySaver` volátil | Memoria se pierde al reiniciar o en multi-instancia | Migrar a `AsyncRedisSaver` (langgraph-checkpoint-redis) TTL 24h | 🔴 Crítico |
| Sin auth en `/api/chat` | Cualquiera puede llamar al endpoint | Agregar `X-Internal-Token` header + validar en Go gateway | 🔴 Crítico |
| Sin `trim_messages` | Historial crece sin límite → tokens excesivos | `trim_messages(max_tokens=20)` en `create_agent()` | 🟡 Medio |
| Sin rate limiting | Riesgo en producción pública | Agregar middleware FastAPI o proxy (nginx) | 🟡 Medio |
| Sin tests automatizados | Regresiones difíciles de detectar | Pytest + httpx.AsyncClient + mocks | 🟢 Bajo |
| Locks en memoria | No funciona en multi-proceso | Migrar a Redis distributed lock (si se escala horizontalmente) | 🟢 Bajo |
| Caches sin persistencia | Cold start hace fetch siempre | Precalentar caches en startup (o aceptar latencia en primer request) | 🟢 Bajo |

Ver `docs/PENDIENTES.md` para el plan detallado de cada item.

---

## Resiliencia

### Circuit Breakers

4 instancias de `CircuitBreaker` (circuit_breaker.py), todas con la misma configuración:

| CB | API protegida | Clave | Servicios que lo usan |
|----|---------------|-------|-----------------------|
| `informacion_cb` | `ws_informacion_ia.php` | `id_empresa` | horario_cache, contexto_negocio, productos_servicios_citas, busqueda_productos |
| `preguntas_cb` | `ws_preguntas_frecuentes.php` | `id_chatbot` | preguntas_frecuentes |
| `calendario_cb` | `ws_calendario.php` | `"global"` | booking |
| `agendar_reunion_cb` | `ws_agendar_reunion.php` | `id_empresa` | schedule_validator |

**Configuración:** `CB_THRESHOLD` (default 3 fallos) y `CB_RESET_TTL` (default 300s = 5 min). Auto-reset via TTLCache expiry.

**Solo `httpx.TransportError`** (fallos de red/timeout reales) abre el circuit. Respuestas `success: false` de la API **no** afectan el CB.

**`/health` endpoint:** retorna HTTP 503 si `any_open()` es True en cualquiera de los 4 CBs.

### Wrapper `resilient_call()` (_resilience.py)

```
1. CB abierto? → RuntimeError (sin tocar la red)
2. Ejecutar coroutine
3. Éxito → record_success (resetea contador)
4. TransportError → record_failure (incrementa contador) + re-raise
5. Otros errores → re-raise (CB no afectado)
```

---

**Versión del documento:** 2.1.0
**Última actualización:** 2026-02-26
