# Cambios: SOLID-2 y C1

---

## SOLID-2 — Inyección de Circuit Breakers en funciones de fetch

### Problema que resolvía

Las 4 funciones que construyen el system prompt usaban el circuit breaker como **singleton hardwired** — importado directamente del módulo, imposible de reemplazar en tests sin `mock.patch`.

```python
# ❌ ANTES — singleton hardwired, no testeable
from .circuit_breaker import informacion_cb

async def fetch_contexto_negocio(id_empresa):
    if informacion_cb.is_open(id_empresa):   # atado al singleton
        return None
    await resilient_call(..., cb=informacion_cb, ...)
```

`ScheduleValidator` y `ScheduleRecommender` ya usaban el patrón correcto (inyección por constructor). SOLID-2 uniformiza ese patrón en las 4 funciones de fetch.

En producción el comportamiento es **idéntico** — nadie pasa `cb`, siempre usa el singleton. El beneficio es que en tests puedes inyectar un CB falso sin usar `mock.patch`.

---

### Archivos modificados

#### 1. `src/citas/services/contexto_negocio.py`

**Imports — antes:**
```python
from .circuit_breaker import informacion_cb
from ._resilience import resilient_call
```
**Imports — después:**
```python
from .circuit_breaker import informacion_cb as _default_informacion_cb
from ._resilience import resilient_call, CircuitBreakerProtocol
```

**Firma — antes:**
```python
async def fetch_contexto_negocio(id_empresa: Any | None) -> str | None:
    if informacion_cb.is_open(id_empresa):
        return None
    ...resilient_call(..., cb=informacion_cb, ...)
```
**Firma — después:**
```python
async def fetch_contexto_negocio(
    id_empresa: Any | None,
    cb: CircuitBreakerProtocol | None = None,
) -> str | None:
    _cb = cb or _default_informacion_cb
    if _cb.is_open(id_empresa):
        return None
    ...resilient_call(..., cb=_cb, ...)
```

---

#### 2. `src/citas/services/horario_reuniones.py`

**Imports — antes:**
```python
from .circuit_breaker import informacion_cb
from ._resilience import resilient_call
```
**Imports — después:**
```python
from .circuit_breaker import informacion_cb as _default_informacion_cb
from ._resilience import resilient_call, CircuitBreakerProtocol
```

**Firma — antes:**
```python
async def fetch_horario_reuniones(id_empresa: Any | None) -> str:
    if informacion_cb.is_open(id_empresa):
        return "No hay horario cargado."
    ...resilient_call(..., cb=informacion_cb, ...)
```
**Firma — después:**
```python
async def fetch_horario_reuniones(
    id_empresa: Any | None,
    cb: CircuitBreakerProtocol | None = None,
) -> str:
    _cb = cb or _default_informacion_cb
    if _cb.is_open(id_empresa):
        return "No hay horario cargado."
    ...resilient_call(..., cb=_cb, ...)
```

> `format_horario_for_system_prompt` es función pura — no se tocó.

---

#### 3. `src/citas/services/preguntas_frecuentes.py`

**Imports — antes:**
```python
from .circuit_breaker import preguntas_cb
from ._resilience import resilient_call
```
**Imports — después:**
```python
from .circuit_breaker import preguntas_cb as _default_preguntas_cb
from ._resilience import resilient_call, CircuitBreakerProtocol
```

**Firma — antes:**
```python
async def fetch_preguntas_frecuentes(id_chatbot: Any | None) -> str:
    if preguntas_cb.is_open(id_chatbot):
        return ""
    ...resilient_call(..., cb=preguntas_cb, ...)
```
**Firma — después:**
```python
async def fetch_preguntas_frecuentes(
    id_chatbot: Any | None,
    cb: CircuitBreakerProtocol | None = None,
) -> str:
    _cb = cb or _default_preguntas_cb
    if _cb.is_open(id_chatbot):
        return ""
    ...resilient_call(..., cb=_cb, ...)
```

> `format_preguntas_frecuentes_para_prompt` es función pura — no se tocó.

---

#### 4. `src/citas/services/productos_servicios_citas.py`

Este es el más complejo porque el CB vivía en el helper privado `_fetch_nombres`, no en la función pública.

**Imports — antes:**
```python
from .circuit_breaker import informacion_cb
from ._resilience import resilient_call
```
**Imports — después:**
```python
from .circuit_breaker import informacion_cb as _default_informacion_cb
from ._resilience import resilient_call, CircuitBreakerProtocol
```

**`_fetch_nombres` — antes:**
```python
async def _fetch_nombres(cod_ope, id_empresa, max_items, response_key):
    if informacion_cb.is_open(id_empresa): return []
    ...resilient_call(..., cb=informacion_cb, ...)
```
**`_fetch_nombres` — después:**
```python
async def _fetch_nombres(cod_ope, id_empresa, max_items, response_key, cb: CircuitBreakerProtocol):
    if cb.is_open(id_empresa): return []
    ...resilient_call(..., cb=cb, ...)
```

**`fetch_nombres_productos_servicios` — antes:**
```python
async def fetch_nombres_productos_servicios(id_empresa: Any | None):
    results = await asyncio.gather(
        _fetch_nombres(..., "productos"),
        _fetch_nombres(..., "servicios"),
    )
```
**`fetch_nombres_productos_servicios` — después:**
```python
async def fetch_nombres_productos_servicios(
    id_empresa: Any | None,
    cb: CircuitBreakerProtocol | None = None,
):
    _cb = cb or _default_informacion_cb
    results = await asyncio.gather(
        _fetch_nombres(..., "productos", _cb),
        _fetch_nombres(..., "servicios", _cb),
    )
```

---

---

## C1 — Migración de checkpointer a AsyncRedisSaver

### Problema que resolvía

LangGraph usa un **checkpointer** para guardar el historial de conversación por sesión (`thread_id`). El checkpointer original era `InMemorySaver` — guarda todo en RAM, se pierde al reiniciar el servidor.

Con `AsyncRedisSaver` el historial se persiste en Redis con TTL de 24h, sobreviviendo reinicios.

**Diseño: fallback automático**
Si `REDIS_URL` está vacío o Redis falla → sigue usando `InMemorySaver` sin romper nada.

**Infraestructura requerida:**
- Redis Stack (imagen `redis/redis-stack-server:latest`) — requiere módulos RedisJSON y RediSearch
- Redis estándar (7.x u 8.x) NO tiene estos módulos

---

### Archivos modificados

#### 1. `requirements.txt` — línea 17

**Diff exacto (`@@ -14,6 +14,7 @@`):**
```diff
 langgraph>=0.2.0
 langgraph-checkpoint>=0.2.0
+langgraph-checkpoint-redis>=0.3.0

 # HTTP client
```

---

#### 2. `src/citas/agent/__init__.py` — líneas 5 y 7

**Diff exacto (`@@ -2,6 +2,6 @@`):**
```diff
-from .agent import process_cita_message
+from .agent import process_cita_message, init_checkpointer, close_checkpointer

-__all__ = ["process_cita_message"]
+__all__ = ["process_cita_message", "init_checkpointer", "close_checkpointer"]
```

---

#### 3. `src/citas/agent/agent.py` — dos hunks, +61 líneas netas

**Hunk 1 — líneas 44-48 (`@@ -41,8 +41,11 @@`):**
```diff
-# Checkpointer global para memoria automática
-_checkpointer = InMemorySaver()
+# Checkpointer global para memoria automática.
+# Valor inicial: InMemorySaver (sin Redis). init_checkpointer() lo reemplaza
+# por AsyncRedisSaver si REDIS_URL está configurado y la conexión tiene éxito.
+_checkpointer: Any = InMemorySaver()
+_checkpointer_ctx: Any = None  # Context manager de AsyncRedisSaver (para close)
```

**Hunk 2 — insertado tras línea 72 (`@@ -69,6 +72,60 @@`) — 60 líneas nuevas:**
```python
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
    """
    Cierra el checkpointer AsyncRedisSaver al apagar la app.
    No hace nada si se está usando InMemorySaver.
    """
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

---

#### 4. `src/citas/main.py` — dos hunks, +2 líneas netas

**Hunk 1 — líneas 22 y 30 (`@@ -19,14 +19,14 @@`) — solo imports:**
```diff
-    from .agent import process_cita_message
+    from .agent import process_cita_message, init_checkpointer, close_checkpointer
 ...
-    from citas.agent import process_cita_message
+    from citas.agent import process_cita_message, init_checkpointer, close_checkpointer
```

**Hunk 2 — líneas 69 y 73 (`@@ -66,9 +66,11 @@`) — lifespan:**
```diff
 @asynccontextmanager
 async def app_lifespan(app: FastAPI):
+    await init_checkpointer()
     try:
         yield
     finally:
+        await close_checkpointer()
         await close_http_client()
```

---

## Resumen

| Cambio | Archivos tocados | Archivos nuevos | Líneas netas |
|--------|-----------------|-----------------|--------------|
| SOLID-2 | 4 (`services/`) | 0 | +~40 |
| C1 | 4 (`agent/`, `main.py`, `requirements.txt`) | 0 | +60 |

## Pasos para activar C1 en producción

1. Instalar paquete en el venv: `pip install langgraph-checkpoint-redis`
2. Desplegar Redis Stack en Easypanel: imagen `redis/redis-stack-server:latest`
3. Configurar variable de entorno en el agente: `REDIS_URL=redis://host:6379`
