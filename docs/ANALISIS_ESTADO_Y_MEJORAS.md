# Análisis del estado actual – Agent Citas (MaravIA)

Documento de análisis detallado del proyecto **agent_citas**: estructura, archivos de código y mejoras recomendadas.

**Fecha:** 2026-02-14  
**Versión analizada:** 2.0.0

---

## 1. Estructura de carpetas y archivos

```
agent_citas/
├── src/citas/                    # Código fuente (paquete citas)
│   ├── main.py                   # Servidor MCP, tool chat
│   ├── logger.py                # Logging centralizado
│   ├── metrics.py                # Métricas Prometheus
│   ├── validation.py             # Validadores Pydantic (booking)
│   ├── __init__.py               # Exports y versión
│   │
│   ├── agent/
│   │   ├── agent.py              # Agente LangChain, process_cita_message
│   │   └── __init__.py
│   │
│   ├── tool/
│   │   ├── tools.py              # check_availability, create_booking, search_productos_servicios
│   │   └── __init__.py
│   │
│   ├── services/
│   │   ├── schedule_validator.py # Validación horarios + cache + APIs
│   │   ├── booking.py            # CREAR_EVENTO (ws_calendario)
│   │   ├── horario_reuniones.py  # Horario para system prompt (sync)
│   │   ├── productos_servicios_citas.py  # Nombres productos/servicios para prompt (sync)
│   │   ├── busqueda_productos.py # BUSCAR_PRODUCTOS_SERVICIOS_CITAS (async)
│   │   └── __init__.py
│   │
│   ├── config/
│   │   ├── config.py             # Variables de entorno
│   │   ├── models.py             # CitaConfig, ChatRequest, ChatResponse
│   │   └── __init__.py
│   │
│   └── prompts/
│       ├── __init__.py           # build_citas_system_prompt
│       └── citas_system.j2       # Template Jinja2 del system prompt
│
├── docs/
│   ├── ARCHITECTURE.md           # Arquitectura técnica
│   ├── API.md                    # Referencia API MCP
│   ├── DEPLOYMENT.md             # Despliegue
│   ├── REVISION_AGENT_CITAS.md   # Revisiones
│   └── ANALISIS_ESTADO_Y_MEJORAS.md  # Este documento
│
├── .env.example
├── .env
├── .gitignore
├── compose.yaml
├── README.md
└── requirements.txt
```

**Resumen:** Estructura clara y alineada con el README. Los módulos están bien separados (agent, tool, services, config, prompts).

---

## 2. Análisis por archivo / módulo

### 2.1 `main.py`

- **Rol:** Punto de entrada MCP; expone la tool `chat` al orquestador.
- **Detalle:** Usa FastMCP, configura logging y métricas, delega en `process_cita_message`. Maneja `ValueError` y excepciones genéricas.
- **Observación:** La firma de `chat` declara `session_id: int`. En API.md y README se muestra `session_id` como string (ej. `"user-12345"`). Si el orquestador envía string, puede fallar o comportarse distinto; conviene aceptar `int | str` y normalizar a string para `thread_id`.

### 2.2 `agent/agent.py`

- **Rol:** Crea el agente LangChain, valida contexto, prepara `AgentContext`, invoca el agente con memoria (InMemorySaver).
- **Detalle:** `_get_agent(config)` recrea el agente en cada request (config dinámico). Usa `build_citas_system_prompt(config, history=None)`; el historial siempre es `None`, por lo que el bloque `{% if has_history %}` del template nunca se usa. El checkpointer usa `thread_id=str(session_id)`.
- **Observación:** El TODO sobre “pasar historial real cuando se implemente límite de memoria (5 turnos)” sigue pendiente; el prompt no recibe historial real.

### 2.3 `tool/tools.py`

- **Rol:** Define las tres tools del agente: `check_availability`, `create_booking`, `search_productos_servicios`. Usa `ToolRuntime` para contexto (id_empresa, duracion, etc.).
- **Detalle:** Validación en capas en `create_booking`: Pydantic → ScheduleValidator → confirm_booking. Mensajes de éxito incluyen detalles y enlace Meet si aplica.
- **Observación:** En `check_availability`, si `time` viene como string vacío después de `.strip()`, se pasa `None` correctamente; no hay bug evidente. Los `logger.info("[create_booking] Tool en uso...")` son redundantes con el tracking de métricas.

### 2.4 `config/config.py`

- **Rol:** Carga `.env` desde la raíz del proyecto y expone variables (OpenAI, servidor, APIs MaravIA, timezone, cache, timeouts).
- **Detalle:** `_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent` asume que `config.py` está en `src/citas/config/`; correcto para la estructura actual.
- **Observación:** `DATABASE_URL` y `REDIS_URL` están definidos pero no se usan (preparación para memoria persistente).

### 2.5 `config/models.py`

- **Rol:** Modelos Pydantic para request/response y configuración.
- **Detalle:** `CitaConfig` solo tiene `personalidad` (con default). En `agent.py` se hace `CitaConfig(**config_data)` con un `config_data` que incluye `id_empresa`, etc.; Pydantic 2 ignora por defecto las claves extra, así que no rompe. No hay validación explícita de `id_empresa` en el modelo.
- **Observación:** Opcionalmente se podría extender `CitaConfig` con los campos que el orquestador envía (id_empresa, duracion_cita_minutos, slots, etc.) para documentar y validar en un solo lugar.

### 2.6 `services/schedule_validator.py`

- **Rol:** Validación de horarios: formato, rango de atención, bloqueos, disponibilidad real vía APIs. Cache en memoria con TTL.
- **Detalle:** Cache global `_SCHEDULE_CACHE` con `threading.Lock`, TTL configurable. `validate()` hace hasta 12 pasos (fecha, hora, pasado, horario por día, rango, cierre, bloqueos, disponibilidad). `recommendation()` usa CONSULTAR_DISPONIBILIDAD si hay fecha+hora; si no, SUGERIR_HORARIOS (hoy/mañana) o mensaje para que indiquen hora.
- **Observación:** Código sólido y bien comentado. `_is_time_blocked` hace `import json` dentro del método; podría moverse al tope del archivo.

### 2.7 `services/booking.py`

- **Rol:** Llamada a ws_calendario (CREAR_EVENTO) con id_usuario, id_prospecto, titulo, fecha_inicio/fin, correo_cliente, correo_usuario, agendar_usuario.
- **Detalle:** Convierte hora AM/PM a 24h, construye fecha_inicio/fin, registra intento/éxito/fallo en métricas. Devuelve `google_meet_link` y `google_calendar_synced` cuando la API los envía.
- **Observación:** Sin observaciones críticas; flujo claro.

### 2.8 `services/horario_reuniones.py`

- **Rol:** Obtener horario de reuniones para inyectar en el system prompt (OBTENER_HORARIO_REUNIONES).
- **Detalle:** Usa `requests.post` (síncrono). Formatea por día de la semana para el prompt.
- **Observación:** Usa **requests** (bloqueante). Se llama desde `build_citas_system_prompt()`, que a su vez se ejecuta en el flujo async del agente; una llamada bloqueante aquí puede afectar la concurrencia. Recomendación: migrar a `httpx` async y que `build_citas_system_prompt` sea async, o ejecutar estas llamadas en un thread pool.

### 2.9 `services/productos_servicios_citas.py`

- **Rol:** Obtener listas de nombres de productos y servicios (OBTENER_PRODUCTOS_CITAS, OBTENER_SERVICIOS_CITAS) para el system prompt.
- **Detalle:** También usa `requests.post` (síncrono). Máximo 10 productos y 10 servicios.
- **Observación:** Misma recomendación que horario_reuniones: evitar bloqueo en el event loop; usar httpx async o ejecutor.

### 2.10 `services/busqueda_productos.py`

- **Rol:** Búsqueda por término (BUSCAR_PRODUCTOS_SERVICIOS_CITAS) para la tool `search_productos_servicios`.
- **Detalle:** Usa `httpx.AsyncClient`, correctamente async. Formato de ítems (precio, categoría, descripción) coherente.
- **Observación:** Consistente con el resto del stack async.

### 2.11 `prompts/__init__.py`

- **Rol:** Construir el system prompt: fecha/hora Perú, horario de atención, lista de productos/servicios, historial (no usado aún).
- **Detalle:** Jinja2 con `citas_system.j2`. Llama a `fetch_horario_reuniones(id_empresa)` y `fetch_nombres_productos_servicios(id_empresa)` (ambas síncronas).
- **Observación:** Variable `lista_productos_servicios` se rellena con `format_nombres_para_prompt`; en el template se usa `lista_productos_servicios | default('...')`; correcto.

### 2.12 `prompts/citas_system.j2`

- **Rol:** Define rol, personalidad, formato WhatsApp, fecha/hora actual, horario de atención, productos/servicios, reglas de uso de herramientas, flujo de captura, casos especiales y ejemplos.
- **Detalle:** Muy completo: aclara cuándo llamar `check_availability` con/sin `time`, cuándo usar `search_productos_servicios` vs lista estática, y que no se inventen enlaces ni códigos.
- **Observación:** Sin cambios críticos; es el centro de la calidad conversacional.

### 2.13 `validation.py`

- **Rol:** Validación Pydantic de datos de la cita: contacto (solo email), nombre, fecha/hora, y modelo agregado BookingData.
- **Detalle:** ContactInfo solo acepta email (comentario en docstring dice “para citas solo email”). BookingData compone CustomerName, ContactInfo, BookingDateTime.
- **Observación:** La API y el prompt piden “email del cliente”; el código es coherente. Si en el futuro se aceptara teléfono para citas, habría que ampliar ContactInfo y actualizar documentación.

### 2.14 `logger.py` y `metrics.py`

- **Rol:** Logging unificado y métricas Prometheus (contadores, histogramas, gauge, info).
- **Detalle:** Silencian httpx, httpcore, openai, langchain. Métricas usan el prefijo `agent_reservas_*` (nombre heredado de “reservas”); el agente es de **citas**.
- **Observación:** Las métricas se llaman `agent_reservas_*`; conceptualmente es el agente de citas. Para coherencia de naming se podría renombrar a `agent_citas_*` en una futura versión (con cuidado si ya hay dashboards/alertas).

---

## 3. Puntos fuertes

- **Arquitectura:** Separación clara entre MCP, agente, tools, servicios, config y prompts.
- **Validación:** Tres capas (Pydantic, ScheduleValidator, API) antes de crear la cita.
- **Cache:** Cache de horarios con TTL y lock; reduce llamadas a ws_informacion_ia.
- **Observabilidad:** Logging por módulo y métricas Prometheus (latencia, errores, booking, tools, API).
- **Async:** Uso de httpx async en schedule_validator, booking y busqueda_productos.
- **Prompt:** Template Jinja2 detallado y alineado con las tools y el flujo de citas.
- **Documentación:** README, ARCHITECTURE.md y API.md dan una base sólida para onboarding y mantenimiento.

---

## 4. Mejoras recomendadas

### 4.1 Tipo de `session_id` (main.py / API)

- **Problema:** `chat` declara `session_id: int`; la documentación y ejemplos usan string.
- **Acción:** Aceptar `int | str` en `chat` y normalizar a string para `thread_id` y logs (p. ej. `str(session_id)`). Actualizar API.md y README para indicar que se aceptan ambos y que internamente se usa como string para la memoria.

### 4.2 Uso de historial en el system prompt

- **Problema:** `history` siempre es `None`; el bloque de historial en `citas_system.j2` nunca se renderiza.
- **Acción:** Cuando el checkpointer o el orquestador expongan los últimos N turnos, pasar esa lista a `build_citas_system_prompt(config, history=...)` y limitar a 5 turnos (o valor configurable) para no inflar el prompt.

### 4.3 Llamadas síncronas en el flujo async

- **Problema:** `fetch_horario_reuniones` y `fetch_nombres_productos_servicios` usan `requests` y se llaman desde `build_citas_system_prompt`, dentro del flujo async.
- **Acción:**  
  - Opción A: Pasar a `httpx` async y hacer `build_citas_system_prompt` async; que `_get_agent` la espere con `await`.  
  - Opción B: Ejecutar las dos llamadas en un executor (p. ej. `run_in_executor`) para no bloquear el event loop.  
  Preferible A para homogeneidad con el resto del código.

### 4.4 Nomenclatura de métricas

- **Problema:** Prefijo `agent_reservas_*` en un agente de citas.
- **Acción:** Planificar cambio a `agent_citas_*` (con migración en Prometheus/grafana si aplica) para alinear nombre del servicio y métricas.

### 4.5 Documentación ARCHITECTURE.md

- **Problema:** En el diagrama aparece “AGENT RESERVAS (Puerto 8003)”;
- **Acción:** Sustituir por “AGENT CITAS (Puerto 8003)” y revisar el resto del doc para evitar “reservas” donde se hable de este agente.

### 4.6 CitaConfig y validación de config

- **Mejora:** Ampliar `CitaConfig` con los campos que envía el orquestador (id_empresa, duracion_cita_minutos, slots, agendar_usuario, id_usuario, correo_usuario, agendar_sucursal) para validar y documentar el contrato en un solo lugar. Usar valores por defecto donde corresponda.

### 4.7 Tests automatizados

- **Problema:** README indica “Sin tests automatizados: En desarrollo”.
- **Acción:** Añadir al menos:  
  - Tests unitarios de `validation.py` (ContactInfo, CustomerName, BookingDateTime, validate_booking_data).  
  - Tests de `schedule_validator` (parseo de hora/rango, lógica de validate sin mockear API en una primera fase).  
  - Tests de integración del tool `chat` con mocks de LLM y APIs (opcional pero muy útil).

### 4.8 Rate limiting y memoria persistente

- **Limitaciones conocidas (README):** Sin rate limiting; memoria volátil (InMemorySaver).
- **Acción:** Antes de producción pública: añadir rate limiting (p. ej. por session_id o IP). Para múltiples instancias, documentar e implementar checkpointer persistente (Redis o PostgreSQL) según guía de LangGraph.

### 4.9 Logs redundantes en tools

- **Detalle:** En `tools.py`, los `logger.info("[create_booking] Tool en uso: create_booking")` (y el equivalente en search_productos_servicios) aportan poco frente a `track_tool_execution`.
- **Acción:** Eliminarlos o reducir a DEBUG para evitar ruido.

### 4.10 Integración del endpoint /metrics

- **Detalle:** En `main.py` se crea `metrics_app = make_asgi_app()` pero no está claro si FastMCP monta ese ASGI en `/metrics`.
- **Acción:** Verificar en la documentación de FastMCP cómo montar rutas adicionales (p. ej. `/metrics`) y asegurar que Prometheus pueda scrapear ese endpoint.

---

## 5. Resumen ejecutivo

El proyecto **agent_citas** está bien estructurado, con responsabilidades claras, validación multicapa, cache, observabilidad y un prompt muy trabajado. Las mejoras más impactantes son: unificar tipo de `session_id` (int/str) y documentación, evitar llamadas bloqueantes (requests) en el camino async, incorporar historial real en el prompt cuando esté disponible, y añadir tests y ajustes de naming/métricas. Con estos ajustes, el agente queda en buena posición para evolución y despliegue en producción controlada.

---

**Versión del documento:** 1.0  
**Próxima revisión sugerida:** Tras implementar historial en prompt o migrar horario/productos a async.
