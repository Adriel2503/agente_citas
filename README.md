# Agent Citas - MaravIA

Agente de IA conversacional especializado en gestión de citas y reuniones comerciales. Funciona como un **closer digital 24/7** que guía a prospectos hasta confirmar una reunión de venta.

## Características

- **FastAPI HTTP** — expone `POST /api/chat` compatible con el gateway Go
- **LangChain 1.2+ API moderna** — agente con `create_agent` + `InMemorySaver`
- **Vision (multimodal)** — soporta imágenes en mensajes vía OpenAI Vision
- **3 tools internas del LLM** — `check_availability`, `create_booking`, `search_productos_servicios`
- **Validación multicapa de horarios** — horario de empresa → bloqueos → disponibilidad real (CONSULTAR_DISPONIBILIDAD)
- **Contexto de negocio dinámico** — cargado desde la API (OBTENER_CONTEXTO_NEGOCIO) con cache TTL 1h + circuit breaker
- **Cache con TTL** — agente compilado por empresa (TTLCache), horarios de reunión por empresa
- **Antipatrón thundering herd** — double-checked locking con `asyncio.Lock` por empresa/sesión
- **Serialización de sesiones** — un lock por `session_id` para evitar condiciones de carrera en el checkpointer
- **Memoria conversacional automática** — `InMemorySaver` de LangGraph, por `thread_id = session_id`
- **Observabilidad completa** — Prometheus metrics (`/metrics`) + logging JSON centralizado
- **Soporte multiempresa** — agente cacheado por `(id_empresa, personalidad)`, hasta 100 empresas simultáneas
- **Google Calendar / Meet** — al crear evento devuelve enlace Meet si la empresa lo tiene configurado

## Versión

**v2.0.0** — FastAPI HTTP + LangChain 1.2+ API Moderna

## Requisitos Previos

- Python 3.10 o superior
- OpenAI API Key
- Acceso a APIs MaravIA (`ws_calendario`, `ws_agendar_reunion`, `ws_informacion_ia`)

## Inicio Rápido

### 1. Clonar e instalar

```bash
# Clonar repositorio
git clone <repository-url>
cd agent_citas

# Crear entorno virtual
python -m venv venv_agent_citas

# Activar entorno virtual
# Windows:
venv_agent_citas\Scripts\activate
# Linux/Mac:
source venv_agent_citas/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
# Copiar archivo de ejemplo
cp .env.example .env

# Editar .env con tus credenciales
# IMPORTANTE: Agregar tu OPENAI_API_KEY
```

### 3. Ejecutar servidor

```bash
python -m citas.main
```

El servidor estará disponible en `http://localhost:8002`

## Variables de Entorno

| Variable | Requerido | Default | Descripción |
|----------|-----------|---------|-------------|
| `OPENAI_API_KEY` | ✅ Sí | — | API Key de OpenAI |
| `OPENAI_MODEL` | ❌ No | `gpt-4o-mini` | Modelo de OpenAI a usar |
| `OPENAI_TEMPERATURE` | ❌ No | `0.5` | Temperatura del modelo (0.0–2.0) |
| `OPENAI_TIMEOUT` | ❌ No | `60` | Timeout para llamadas al LLM (segundos) |
| `MAX_TOKENS` | ❌ No | `2048` | Máximo de tokens por respuesta |
| `SERVER_HOST` | ❌ No | `0.0.0.0` | Host del servidor |
| `SERVER_PORT` | ❌ No | `8002` | Puerto del servidor |
| `CHAT_TIMEOUT` | ❌ No | `120` | Timeout total por request de chat (segundos) |
| `LOG_LEVEL` | ❌ No | `INFO` | Nivel de logging (`DEBUG\|INFO\|WARNING\|ERROR`) |
| `LOG_FILE` | ❌ No | `""` | Archivo de log (vacío = solo stdout) |
| `API_TIMEOUT` | ❌ No | `10` | Timeout para APIs externas (segundos) |
| `SCHEDULE_CACHE_TTL_MINUTES` | ❌ No | `5` | TTL del cache de horarios y del agente compilado |
| `TIMEZONE` | ❌ No | `America/Lima` | Zona horaria para fechas/horas en prompts |
| `API_CALENDAR_URL` | ❌ No | `https://api.maravia.pe/.../ws_calendario.php` | URL API calendario (CREAR_EVENTO) |
| `API_AGENDAR_REUNION_URL` | ❌ No | `https://api.maravia.pe/.../ws_agendar_reunion.php` | URL API disponibilidad (CONSULTAR_DISPONIBILIDAD, SUGERIR_HORARIOS) |
| `API_INFORMACION_URL` | ❌ No | `https://api.maravia.pe/.../ws_informacion_ia.php` | URL API información (OBTENER_HORARIO_REUNIONES, OBTENER_CONTEXTO_NEGOCIO) |

## Uso — API HTTP

El agente expone un endpoint HTTP compatible con el gateway Go.

### `POST /api/chat`

**Body:**
```json
{
  "message": "Quiero agendar una cita para mañana a las 2pm",
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

**Parámetros de `context.config`:**

| Campo | Tipo | Requerido | Default | Descripción |
|-------|------|-----------|---------|-------------|
| `id_empresa` | int | ✅ Sí | — | ID de la empresa |
| `usuario_id` | int | ❌ No | `1` | ID del vendedor (para CREAR_EVENTO) |
| `correo_usuario` | str | ❌ No | `""` | Email del vendedor (para invitación Meet) |
| `personalidad` | str | ❌ No | `"amable, profesional y eficiente"` | Tono del agente |
| `duracion_cita_minutos` | int | ❌ No | `60` | Duración de la cita en minutos |
| `slots` | int | ❌ No | `60` | Slots de calendario disponibles |
| `agendar_usuario` | bool/int | ❌ No | `1` | `1` = asignar vendedor automáticamente |
| `agendar_sucursal` | bool/int | ❌ No | `0` | `1` = agendar por sucursal |

**Response:**
```json
{
  "reply": "¡Hola! Mañana a las 2:00 PM está disponible. ¿Me confirmas tu nombre completo y correo?"
}
```

### `GET /health`

```json
{"status": "ok", "agent": "citas", "version": "2.0.0"}
```

### `GET /metrics`

Métricas Prometheus en formato text.

## Arquitectura

```
Gateway Go  ──POST /api/chat──►  FastAPI (puerto 8002)
                                        │
                                process_cita_message()
                                        │
                              ┌─────────▼─────────┐
                              │  LangChain Agent   │
                              │  (GPT-4o-mini)     │
                              │  InMemorySaver     │
                              └────────┬───────────┘
                                       │  function calling
                     ┌─────────────────┼──────────────────┐
                     ▼                 ▼                  ▼
           check_availability   create_booking   search_productos
                     │                 │              servicios
                     │         ┌───────┴──────┐          │
                     │         │  3 capas:    │     ws_informacion_ia
                     ▼         │  1. Pydantic │     (OBTENER_CONTEXTO
            ScheduleValidator  │  2. Schedule │      _NEGOCIO)
                     │         │     Validator│
         ┌───────────┴──┐      │  3. CREAR_  │
         ▼              ▼      │     EVENTO  │
   OBTENER_HORARIO  CONSULTAR_ └─────────────┘
   _REUNIONES       DISPONIBILI
   SUGERIR_HORARIOS DAD
```

**Flujo por request:**
1. Gateway envía `message` (string o con URLs de imágenes), `session_id` (int), `context.config`
2. Se serializa por `session_id` (asyncio.Lock) para evitar condiciones de carrera en el checkpointer
3. El agente se obtiene desde TTLCache por `(id_empresa, personalidad)`; si no existe, se crea (incluye fetch de horario + contexto de negocio en paralelo)
4. LangGraph invoca al LLM con memoria automática (`thread_id = str(session_id)`)
5. El LLM decide qué tool usar según la conversación; puede encadenar varias tools
6. `create_booking` valida → llama `ws_calendario.php` (CREAR_EVENTO) → devuelve enlace Meet si aplica

### Cache y rendimiento

| Cache | Clave | TTL |
|-------|-------|-----|
| Agente compilado (`TTLCache`) | `(id_empresa, personalidad)` | `SCHEDULE_CACHE_TTL_MINUTES` (default 5 min) |
| Horario de reuniones | `id_empresa` | `SCHEDULE_CACHE_TTL_MINUTES` |
| Contexto de negocio (`TTLCache`) | `id_empresa` | 1 hora |
| Circuit breaker contexto | `id_empresa` | 5 min (auto-reset) |

### Herramientas del agente

| Tool | Cuándo se usa | APIs que llama |
|------|--------------|----------------|
| `check_availability(date, time?)` | El cliente pregunta por disponibilidad | `SUGERIR_HORARIOS` (sin hora) o `CONSULTAR_DISPONIBILIDAD` (con hora) |
| `create_booking(date, time, customer_name, customer_contact)` | Tiene los 4 datos: fecha, hora, nombre, email | `OBTENER_HORARIO_REUNIONES` + `CONSULTAR_DISPONIBILIDAD` + `CREAR_EVENTO` |
| `search_productos_servicios(busqueda, limite?)` | El cliente pregunta por precio o detalle de un producto/servicio específico | `OBTENER_CONTEXTO_NEGOCIO` (vía ws_informacion_ia) |

### Soporte de imágenes (Vision)

Si el mensaje contiene URLs de imágenes (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`), se convierten automáticamente a bloques `image_url` para OpenAI Vision. Máximo 10 imágenes por mensaje.

## Desarrollo

### Estructura del proyecto

```
agent_citas/
├── src/citas/                         # Código fuente principal
│   ├── main.py                        # Servidor FastAPI (punto de entrada)
│   ├── logger.py                      # Logging centralizado (JSON o texto)
│   ├── metrics.py                     # Métricas Prometheus (counters, histogramas, gauges)
│   ├── validation.py                  # Validadores de datos de booking
│   ├── __init__.py
│   │
│   ├── agent/
│   │   ├── agent.py                   # Lógica principal: cache, locks, process_cita_message()
│   │   └── __init__.py
│   │
│   ├── tool/
│   │   ├── tools.py                   # check_availability, create_booking, search_productos_servicios
│   │   └── __init__.py
│   │
│   ├── services/
│   │   ├── schedule_validator.py      # ScheduleValidator: cache de horarios + CONSULTAR_DISPONIBILIDAD
│   │   ├── booking.py                 # confirm_booking() → ws_calendario.php (CREAR_EVENTO)
│   │   ├── contexto_negocio.py        # fetch_contexto_negocio() con cache TTL + circuit breaker
│   │   ├── horario_reuniones.py       # Obtención de horarios para system prompt
│   │   ├── busqueda_productos.py      # buscar_productos_servicios() → ws_informacion_ia
│   │   ├── productos_servicios_citas.py  # Carga de productos/servicios para el prompt
│   │   ├── http_client.py             # Cliente httpx compartido (singleton async)
│   │   └── __init__.py
│   │
│   ├── config/
│   │   ├── config.py                  # Variables de entorno con validación de tipos
│   │   ├── models.py                  # Pydantic: CitaConfig, ChatRequest, ChatResponse
│   │   └── __init__.py
│   │
│   └── prompts/
│       ├── __init__.py                # build_citas_system_prompt() (async, Jinja2)
│       └── citas_system.j2            # Template Jinja2 del system prompt
│
├── requirements.txt                   # Dependencias
├── .env.example                       # Ejemplo de configuración
└── README.md
```

### Ejecutar en modo DEBUG

```bash
LOG_LEVEL=DEBUG python -m citas.main
```

### Stack tecnológico

| Componente | Librería | Versión mínima |
|------------|----------|----------------|
| Web framework | FastAPI + Uvicorn | `>=0.110.0` |
| Validación | Pydantic v2 | `>=2.6.0` |
| LLM agent | LangChain | `>=1.2.0` |
| Memoria/grafos | LangGraph + InMemorySaver | `>=0.2.0` |
| LLM provider | OpenAI (via langchain-openai) | `>=0.3.0` |
| HTTP client | httpx (async) | `>=0.27.0` |
| Templates | Jinja2 | `>=3.1.3` |
| Métricas | prometheus-client | `>=0.19.0` |
| Cache TTL | cachetools | `>=5.3.0` |
| Fechas naturales | dateparser | `>=1.2.0` |

## Métricas Prometheus

Disponibles en `http://localhost:8002/metrics`. Principales:

| Métrica | Tipo | Descripción |
|---------|------|-------------|
| `agent_citas_chat_requests_total` | Counter | Mensajes recibidos, label `empresa_id` |
| `agent_citas_chat_errors_total` | Counter | Errores, label `error_type` |
| `agent_citas_booking_attempts_total` | Counter | Intentos de cita |
| `agent_citas_booking_success_total` | Counter | Citas creadas exitosamente |
| `agent_citas_booking_failed_total` | Counter | Citas fallidas, label `reason` |
| `agent_citas_tool_calls_total` | Counter | Llamadas a tools, label `tool_name` |
| `agent_citas_chat_response_duration_seconds` | Histogram | Latencia total de respuesta |
| `agent_citas_llm_call_duration_seconds` | Histogram | Latencia de llamada al LLM |
| `agent_citas_tool_execution_duration_seconds` | Histogram | Latencia de ejecución de tools |
| `agent_citas_api_call_duration_seconds` | Histogram | Latencia de APIs externas |
| `agent_citas_cache_entries` | Gauge | Entradas actuales en cache, label `cache_type` |
| `agent_citas_info` | Info | Versión, modelo, tipo de agente |

## Limitaciones Conocidas

- **Memoria volátil**: Usa `InMemorySaver` (se pierde al reiniciar). Para producción con múltiples instancias, migrar a Redis o PostgreSQL checkpointer.
- **Sin rate limiting**: Implementar antes de producción pública.
- **Sin tests automatizados**: En desarrollo.
- **Modificar/cancelar citas**: No hay herramienta implementada; el agente responde que se contactará a un asesor.

## Licencia

Propiedad de MaravIA Team.

## Soporte

Para problemas o preguntas, contactar al equipo de desarrollo de MaravIA.
