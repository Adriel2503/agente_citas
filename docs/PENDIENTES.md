# Pendientes técnicos — agent_citas

Estado tras la segunda auditoría técnica (2026-02). Madurez actual: **8.5 / 10**.

---

## Resuelto en esta sesión

| ID | Descripción | Archivo(s) |
|----|-------------|-----------|
| O2 | `/health` retorna 503 cuando APIs degradadas | `main.py`, `circuit_breaker.py` |
| O3 | Thundering herd en `contexto_negocio` y `preguntas_frecuentes` | `contexto_negocio.py`, `preguntas_frecuentes.py` |
| M3 | Lock cleanup simplificado (async → sync, `lock.locked()`) | `agent/agent.py` |
| M2 | Circuit breaker para `ws_calendario.php` | `booking.py`, `circuit_breaker.py`, `main.py` |

---

## 🔴 Críticos (deben resolverse antes de producción)

### C1 — InMemorySaver sin TTL (memory leak) ⏸️ EN PAUSA

**Problema:** `InMemorySaver` guarda el historial de cada sesión en RAM sin límite de tiempo.
El `session_id` en WhatsApp es permanente por contacto y nunca cambia → la RAM crece
indefinidamente mientras el proceso esté vivo. Con 50–200 empresas y múltiples contactos
activos esto eventualmente agota la memoria del container.

**Solución: migrar a `AsyncRedisSaver` con TTL de 24 horas y fallback automático a InMemorySaver.**

> ⚠️ **Implementado en commit `ed47eae` y revertido (2026-03-05).** Pendiente re-implementar cuando Redis Stack esté confirmado en Easypanel y `REDIS_URL` configurado.

**Infraestructura requerida:**
- Redis Stack (imagen `redis/redis-stack-server:latest`) — requiere módulos RedisJSON y RediSearch
- Redis estándar (7.x u 8.x) NO tiene estos módulos
- Redis (`memori_agentes` en Easypanel) ya existe. Solo falta configurarlo.

#### Paso 1 — Instalar dependencia

Agregar a `pyproject.toml`:
```toml
"langgraph-checkpoint-redis>=0.3.0",
```

#### Paso 2 — Configurar `REDIS_URL` en Easypanel

```
REDIS_URL=redis://memori_agentes:6379
```

`REDIS_URL` ya está leída en `config/config.py`, no hay que agregarla.

#### Paso 3 — Modificar `agent/agent.py`

Reemplazar el checkpointer estático por init/close con fallback:

```python
# Valor inicial: InMemorySaver. init_checkpointer() lo reemplaza
# por AsyncRedisSaver si REDIS_URL está configurado y la conexión tiene éxito.
_checkpointer: Any = InMemorySaver()
_checkpointer_ctx: Any = None  # Context manager de AsyncRedisSaver (para close)


async def init_checkpointer() -> None:
    """
    Inicializa el checkpointer LangGraph.
    Si REDIS_URL está configurado, intenta usar AsyncRedisSaver (TTL 24 h,
    refresh_on_read=True). Si Redis no está disponible o el paquete no está
    instalado, mantiene InMemorySaver como fallback sin lanzar excepciones.
    Debe llamarse una sola vez al arrancar la app (FastAPI lifespan).
    """
    global _checkpointer, _checkpointer_ctx

    if not app_config.REDIS_URL:
        logger.info("[AGENT] REDIS_URL no configurado — usando InMemorySaver")
        return

    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        ctx = AsyncRedisSaver.from_conn_string(
            app_config.REDIS_URL,
            ttl={"default_ttl": 1440, "refresh_on_read": True},
        )
        checkpointer = await ctx.__aenter__()
        await checkpointer.asetup()
        _checkpointer = checkpointer
        _checkpointer_ctx = ctx
        logger.info("[AGENT] AsyncRedisSaver inicializado (TTL 24 h, refresh_on_read=True)")

    except ImportError:
        logger.warning("[AGENT] langgraph-checkpoint-redis no instalado — usando InMemorySaver")
    except Exception as e:
        logger.warning("[AGENT] No se pudo conectar a Redis (%s) — usando InMemorySaver", e)


async def close_checkpointer() -> None:
    """Cierra AsyncRedisSaver al apagar la app. No-op si usa InMemorySaver."""
    global _checkpointer_ctx
    if _checkpointer_ctx is None:
        return
    try:
        await _checkpointer_ctx.__aexit__(None, None, None)
        logger.info("[AGENT] AsyncRedisSaver cerrado correctamente")
    except Exception as e:
        logger.warning("[AGENT] Error cerrando Redis checkpointer: %s", e)
    finally:
        _checkpointer_ctx = None
```

#### Paso 4 — Modificar `agent/__init__.py`

```python
from .agent import process_cita_message, init_checkpointer, close_checkpointer
__all__ = ["process_cita_message", "init_checkpointer", "close_checkpointer"]
```

#### Paso 5 — Modificar `main.py` (lifespan)

```python
from .agent import process_cita_message, init_checkpointer, close_checkpointer

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    await init_checkpointer()
    try:
        yield
    finally:
        await close_checkpointer()
        await close_http_client()
```

#### Pasos para activar en producción

1. Agregar dep a `pyproject.toml`: `langgraph-checkpoint-redis>=0.3.0`
2. Desplegar Redis Stack en Easypanel: imagen `redis/redis-stack-server:latest`
3. Configurar variable: `REDIS_URL=redis://memori_agentes:6379`

#### Beneficios tras la migración

- Historial persiste si el container se reinicia (deploy, crash)
- TTL 24h: sesiones inactivas se eliminan automáticamente
- Fallback automático: si Redis cae, sigue con InMemorySaver
- Preparado para escalar a múltiples instancias del agente

---

### C2 — Sin autenticación en `/api/chat`

**Problema:** Cualquiera con acceso de red puede llamar al endpoint. En Easypanel los
servicios son internos, pero es buena práctica tenerlo de todas formas.

**Solución mínima:** Header compartido `X-Internal-Token` validado en FastAPI.

```python
# main.py — agregar middleware o dependency
from fastapi import Header, HTTPException, Depends

INTERNAL_TOKEN = app_config.INTERNAL_API_TOKEN  # nueva env var

async def verify_token(x_internal_token: str = Header(...)):
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# Aplicar a /api/chat:
@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def chat(req: ChatRequest) -> ChatResponse:
    ...
```

También requiere agregar el header en el gateway Go al hacer la llamada al agente.

---

## 🟡 Mejoras importantes

### ✅ M1 — Límite de ventana de mensajes (20 turnos) — IMPLEMENTADO

**Problema:** Aunque Redis resuelva el TTL, sin un límite de ventana el historial de una
sesión muy activa puede crecer y consumir tokens en exceso en cada llamada al LLM.

**Esta mejora es independiente de Redis y se puede hacer ahora.**

#### Implementación en `agent/agent.py`

```python
from langchain_core.messages import trim_messages

# En _get_agent(), al llamar create_agent():
agent = create_agent(
    model=model,
    tools=AGENT_TOOLS,
    system_prompt=system_prompt,
    checkpointer=_checkpointer,
    response_format=CitaStructuredResponse,
    # Mantiene solo los últimos 20 mensajes (10 turnos usuario/asistente).
    # strategy="last" conserva los más recientes.
    # token_counter=len cuenta mensajes, no tokens — más predecible.
    state_modifier=trim_messages(
        max_tokens=20,
        strategy="last",
        token_counter=len,
        allow_partial=False,
        include_system=True,   # conserva el system prompt
        start_on="human",      # el primer mensaje del recorte es siempre del usuario
    ),
)
```

**Resultado:** El agente procesa máximo 20 mensajes por invocación (system + últimos turnos),
independientemente de cuántos haya en Redis. Reduce costo de tokens en sesiones largas.

---

### B1 — `CREAR_EVENTO` no envía `slots` → backend usa default desconocido

**Problema:** `CONSULTAR_DISPONIBILIDAD` recibe `slots` para validar capacidad, pero
`CREAR_EVENTO` no lo incluye en el payload. El backend (`ws_calendario.php`) asigna un
default interno desconocido, que puede diferir del valor con el que se validó.

```python
# CONSULTAR_DISPONIBILIDAD — sí recibe slots
{"codOpe": "CONSULTAR_DISPONIBILIDAD", "slots": slots, ...}

# CREAR_EVENTO — slots ausente
{"codOpe": "CREAR_EVENTO", "usuario_id": ..., "fecha_inicio": ..., ...}
```

Además, `confirm_booking()` ni siquiera recibe `slots` como parámetro (`booking.py`),
así que el dato nunca llega a la función de escritura.

**Riesgo:** una empresa con `slots=2` (dos citas simultáneas permitidas) podría ver el
slot validado como disponible pero creado con comportamiento distinto al esperado.

**Fix requiere coordinación con backend PHP:**
1. Confirmar que `ws_calendario.php` acepta `slots` en `CREAR_EVENTO`
2. Agregar `slots: int` a la firma de `confirm_booking()` en `booking.py`
3. Incluirlo en el payload de `CREAR_EVENTO`
4. Pasarlo desde `create_booking` tool (`tools.py`) → `confirm_booking`

**Archivos Python a modificar cuando el PHP esté listo:**
- `src/citas/services/booking.py` — agregar `slots` al payload
- `src/citas/tool/tools.py` — pasar `slots` desde `ctx.slots`

---

### B2 — Graceful degradation en disponibilidad → double booking posible

**Problema:** Si `ws_agendar_reunion.php` está caído, `check_slot_availability()`
devuelve `{"available": True}` para cualquier slot, sin verificar citas existentes.
Google Calendar no bloquea eventos solapados, así que el double booking se concretaría.

```python
# availability_client.py
except RuntimeError:          # CB abierto
    return {"available": True, "error": None}
except httpx.TimeoutException:
    return {"available": True, "error": None}
except Exception:
    return {"available": True, "error": None}  # cualquier fallo = disponible
```

Combinado con `_fetch_horario()` que también retorna `{"valid": True}` si
`ws_informacion_ia.php` falla (`schedule_validator.py:108-110`), una caída simultánea
de ambas APIs permite booking sin ninguna validación.

**Decisión de diseño actual (aceptada):** priorizar disponibilidad del servicio sobre
riesgo de double booking. En producción con < 50 empresas simultáneas y APIs
generalmente estables, la probabilidad es baja.

**Mitigación implementada:** counter Prometheus `citas_availability_degradation_total`
registra cada degradación con labels `service` y `reason`:
- `service`: `availability_check` (CONSULTAR_DISPONIBILIDAD) | `schedule_fetch` (OBTENER_HORARIO_REUNIONES)
- `reason`: `timeout` | `circuit_open` | `api_success_false` | `http_error` | `transport_error` | `parse_error` | `unknown`

La política de degradación no cambió (sigue retornando available=True / valid=True ante fallos).
El counter permite detectar patrones de falla recurrente vía dashboards/alertas Prometheus.

---

## 🟢 Diferidas (no urgentes)

### Tests

No existe suite de tests. Las áreas más importantes a cubrir:

- `services/booking.py` — `_parse_time_to_24h`, `_build_fecha_inicio_fin`
- `services/circuit_breaker.py` — transiciones CLOSED → OPEN → reset
- `agent/agent.py` — `_validate_context`, `_prepare_agent_context`
- `services/schedule_validator.py` — validación de horarios y slots

### Formato futuro: respuesta reply + url con imagen de producto

Cuando la tool de búsqueda de productos/servicios devuelva URL de imagen, el campo `url` de `CitaStructuredResponse` podrá usarse para adjuntar la imagen al mensaje de WhatsApp.

Reglas pendientes de implementar en el prompt:
- `url` de saludo (`archivo_saludo`): solo en el primer mensaje de la conversación.
- `url` de producto: solo cuando el usuario eligió un producto concreto y la tool devolvió URL. Si mostró varios y el usuario no eligió, dejar `url` vacío.

### Streaming

Actualmente el gateway espera la respuesta completa antes de enviarla al cliente.
El TTFT (Time To First Token) es igual al tiempo total de respuesta (~3–8s).

Para habilitar streaming: FastAPI `StreamingResponse` + LangGraph `astream_events`.
Requiere cambios en el gateway Go para consumir SSE y retransmitir a N8N/WhatsApp.

---

## Resumen de prioridades

```
✅ M1 — trim_messages implementado (wrap_model_call en agent.py)

Antes de producción con carga real:
  ⏸️  C1 — AsyncRedisSaver (implementado/revertido, código de referencia arriba)
  ⚠️  C2 — Auth X-Internal-Token

Después:
  📋 Tests unitarios
  📋 Streaming SSE (descartado — canal WhatsApp, respuesta siempre completa)
```
