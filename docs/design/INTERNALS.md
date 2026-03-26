# Internals — Documentación técnica interna del agente

Detalle de implementación de tools, validaciones, caché, circuit breakers y concurrencia. Para la visión general del proyecto, ver el [README](../../README.md).

---

## 1. Tools del agente

Las tools son el puente entre el LLM y los sistemas externos. El LLM decide autónomamente cuándo y cuáles invocar basándose en el estado de la conversación.

Definidas en `tools/tools.py`. Exportadas como `AGENT_TOOLS = [check_availability, create_booking, search_productos_servicios]`.

### Tabla resumen: origen de cada parámetro

> **🤖 IA** = el LLM decide el valor basándose en la conversación.
> **🔧 Gateway** = viene de `config` (CitasConfig) enviado por el gateway Go (originado en N8N).
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
    id_empresa: int                        # 🔧 Gateway (requerido)
    duracion_cita_minutos: int | None = None  # 🔧 Gateway (None si no enviado)
    slots: int | None = None               # 🔧 Gateway (None si no enviado)
    agendar_usuario: int = 1               # 🔧 Gateway (default: 1) — 1=asignar vendedor
    usuario_id: int | None = None          # 🔧 Gateway (None si no enviado) — ID del vendedor
    correo_usuario: str | None = None      # 🔧 Gateway (None si no enviado) — email del vendedor
    agendar_sucursal: int = 0              # 🔧 Gateway (default: 0)
    session_id: int = 0                    # = session_id del request (número WhatsApp)
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
| `usuario_id` | `usuario_id` | `config.usuario_id` del gateway |
| `session_id` | `id_prospecto` | `session_id` del request (nro WhatsApp) |
| `correo_usuario` | `correo_usuario` | `config.correo_usuario` del gateway |
| `agendar_usuario` | `agendar_usuario` | `config.agendar_usuario` del gateway |
| `duracion_cita_minutos` | Cálculo de `fecha_fin` | `config.duracion_cita_minutos` del gateway |

**Parámetros calculados por el código (ni IA ni gateway):**

| Campo en payload | Cómo se calcula |
|-----------------|-----------------|
| `titulo` | `f"Reunion para el usuario: {customer_name}"` — construido por código, no por LLM |
| `fecha_inicio` | `date + _parse_time_to_24h(time)` → `"2026-02-28 15:00:00"` |
| `fecha_fin` | `fecha_inicio + duracion_cita_minutos` → `"2026-02-28 16:00:00"` |
| `correo_cliente` | `customer_contact` (viene de la IA, pasa directo) |

**Pipeline de 3 fases:**

```
Fase 1 — Validación de datos (Pydantic + regex en tools/validation.py)
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

## 2. Validación de horarios (ScheduleValidator)

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

## 3. Construcción del system prompt

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

## 4. Estrategia de caché

El agente usa **2 caches TTL** independientes. Horarios, contexto de negocio y FAQs no tienen cache propio — se obtienen de la API al construir el agente y quedan cacheados dentro del agente compilado.

| Caché | Módulo | Clave | Maxsize | TTL | Propósito |
|-------|--------|-------|---------|-----|-----------|
| `_agent_cache` | `agent/runtime/_cache.py` | `(id_empresa, key_hash)` | 500 | `AGENT_CACHE_TTL_MINUTES` (60 min) | Agente compilado (grafo LangGraph + system prompt con horarios, contexto, FAQs) |
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

## 5. Circuit breakers

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

## 6. Modelo de concurrencia

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
