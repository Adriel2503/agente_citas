# Checkpointer — Guía de Configuración y Serialización

## 1. Arquitectura del Checkpointer

El agente usa LangGraph checkpointer para persistir conversaciones. Soporta dos backends con fallback automático:

```
                    ┌─────────────────────┐
                    │  init_checkpointer()│  (lifespan startup)
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  ¿REDIS_URL vacío?   │
                    └─────────┬───────────┘
                         │          │
                        Sí         No
                         │          │
                         │   ┌──────▼──────────┐
                         │   │ Crear AsyncRedis │
                         │   │ Saver + asetup() │
                         │   └──────┬──────────┘
                         │          │
                         │   ┌──────▼──────────┐
                         │   │   ¿Funcionó?     │
                         │   └──────┬──────────┘
                         │      │         │
                         │     Sí        No (ImportError, conexión, módulos)
                         │      │         │
                         │      │         ▼
                         ▼      │    Log warning
                  InMemorySaver │    + InMemorySaver (fallback)
                                │
                         AsyncRedisSaver ✓
```

**Ciclo de vida:**
- `init_checkpointer()` — async, llamado una vez en FastAPI lifespan (startup)
- `get_checkpointer()` — sync, retorna el singleton (InMemory o Redis)
- `close_checkpointer()` — async, cierra conexión Redis via `__aexit__`; no-op para InMemory

**Archivos involucrados:**
- `agent/runtime/_llm.py` — lógica de init/get/close
- `main.py` — lifespan llama init y close
- `config/config.py` — `REDIS_URL`, `REDIS_CHECKPOINT_TTL_HOURS`

---

## 2. Serialización: JsonPlusSerializer vs JsonPlusRedisSerializer

Cada backend usa un serializer diferente con paths de serialización distintos:

### InMemorySaver → `JsonPlusSerializer`

```
dumps_typed(obj):
  None        → ("null", b"")
  bytes       → ("bytes", obj)
  bytearray   → ("bytearray", obj)
  otros       → ("msgpack", ormsgpack.packb(obj))  ← SIEMPRE este path
  fallback    → ("pickle", pickle.dumps(obj))       ← solo si pickle_fallback=True Y msgpack falla

loads_typed(data):
  "msgpack"   → ormsgpack.unpackb(data, ext_hook=...)  ← usa allowed_msgpack_modules
  "json"      → json.loads(data, object_hook=_reviver)  ← usa allowed_json_modules (NUNCA se usa con InMemory)
```

**InMemorySaver siempre serializa como msgpack**, incluso strings y dicts. El path JSON existe por compatibilidad pero nunca se activa.

### AsyncRedisSaver → `JsonPlusRedisSerializer`

```
dumps_typed(obj):
  None        → ("null", b"")
  bytes       → ("bytes", obj)
  bytearray   → ("bytearray", obj)
  otros       → ("json", orjson.dumps(obj))     ← PRIMERO intenta JSON
  fallback    → ("msgpack", ormsgpack.packb(obj)) ← solo si orjson falla (bytes en estructura)

loads_typed(data):
  "json"      → orjson.loads(data) + _revive_if_needed  ← usa allowed_json_modules (via _reviver)
  "msgpack"   → super().loads_typed(data)                ← usa allowed_msgpack_modules (fallback)
```

**AsyncRedisSaver primero intenta JSON** (orjson). Solo cae a msgpack si el objeto contiene `bytes` o `bytearray`. `CitaStructuredResponse` tiene solo strings → siempre va por JSON.

### Tabla comparativa

| Aspecto | InMemorySaver | AsyncRedisSaver |
|---------|--------------|-----------------|
| Serializer | `JsonPlusSerializer` | `JsonPlusRedisSerializer` |
| Path principal | msgpack (ormsgpack) | JSON (orjson) |
| Path fallback | pickle (si habilitado) | msgpack (si hay bytes) |
| Allowlist principal | `allowed_msgpack_modules` | `allowed_json_modules` |
| Almacenamiento | RAM (tuple[str, bytes]) | Redis JSON (JSON.SET/JSON.GET) |
| Persistencia | Se pierde al reiniciar | Sobrevive reinicios |
| Cierre | No-op | `__aexit__` cierra conexión |

---

## 3. Allowlists de deserialización

Las allowlists controlan qué tipos custom se permiten deserializar desde un checkpoint. Sin ellas, se genera un warning (o se bloquea en futuras versiones).

### `allowed_msgpack_modules` (InMemorySaver)

```python
# Formato: tupla (módulo dotted, nombre de clase)
allowed_msgpack_modules=[("citas.agent.content", "CitaStructuredResponse")]
```

Matchea contra `(obj.__class__.__module__, obj.__class__.__name__)`.

### `allowed_json_modules` (AsyncRedisSaver)

```python
# Formato: tupla con cada segmento del path separado
allowed_json_modules=[("citas", "agent", "content", "CitaStructuredResponse")]
```

Matchea contra `value["id"]` del formato LC constructor `{"lc": 2, "type": "constructor", "id": [...]}`.

### Comportamiento default (sin allowlist)

Cuando no se pasa `allowed_msgpack_modules`, el default es `True`:

```python
# JsonPlusSerializer.__init__ (langgraph-checkpoint 4.0.1)
if allowed_msgpack_modules is _SENTINEL:
    if STRICT_MSGPACK_ENABLED:
        allowed_msgpack_modules = None   # bloquea todo
    else:
        allowed_msgpack_modules = True   # permite todo + warning
```

Con `True`, la deserialización **funciona** pero genera el warning:

```
WARNING - Deserializing unregistered type citas.agent.content.CitaStructuredResponse
from checkpoint. This will be blocked in a future version.
Add to allowed_msgpack_modules to silence: [('citas.agent.content', 'CitaStructuredResponse')]
```

### Estado de los warnings

| Warning | Causa | Estado |
|---------|-------|--------|
| Warning 1: "Deserializing unregistered type" | InMemorySaver usa msgpack, tipo no registrado | **Resuelto** — `allowed_msgpack_modules` configurado |
| Warning 2: "PydanticSerializationUnexpectedValue" | AgentContext (dataclass) pasado como `context=` en ainvoke | **Pendiente** — cosmético, no afecta funcionamiento |

---

## 4. Configuración (variables de entorno)

| Variable | Default | Rango | Descripción |
|----------|---------|-------|-------------|
| `REDIS_URL` | `""` (vacío) | — | URL de conexión Redis. Vacío = InMemorySaver |
| `REDIS_CHECKPOINT_TTL_HOURS` | `24` | 0–8760 | TTL de checkpoints en horas. 0 = sin expiración |

### Formato de REDIS_URL

```
redis://user:password@host:port
```

**Evitar caracteres especiales** (`#`, `@`, `%`, `/`) en la contraseña. Si es necesario, usar URL encoding (ej: `#` → `%23`).

### TTL: conversión interna

```python
# En _llm.py:
ttl_hours = app_config.REDIS_CHECKPOINT_TTL_HOURS      # 24 (del .env)
ttl_config = {"default_ttl": ttl_hours * 60}            # {"default_ttl": 1440} (minutos)
saver = AsyncRedisSaver(redis_url=..., ttl=ttl_config)  # Redis recibe minutos
```

El TTL se aplica **por key individual** — cada write tiene su propio EXPIRE. No es un TTL global de la sesión.

---

## 5. Redis: requisitos y persistencia

### Módulos requeridos

`langgraph-checkpoint-redis` necesita:
- **RedisJSON** — almacena checkpoints como documentos JSON (`JSON.SET`, `JSON.GET`)
- **RediSearch** — busca checkpoints por thread_id, checkpoint_ns (`FT.SEARCH`, `FT.CREATE`)

| Redis | Módulos |
|-------|---------|
| Redis 8+ | Incluidos de fábrica |
| Redis 7 | Necesita Redis Stack (`redis/redis-stack`) |
| Redis 7 vanilla | No funciona → fallback a InMemorySaver |

Verificar módulos instalados:

```bash
127.0.0.1:6379> MODULE LIST
# Debe mostrar "ReJSON" y "search"
```

### Persistencia RDB (snapshots)

Redis guarda toda la RAM a disco periódicamente (`dump.rdb`):

```bash
127.0.0.1:6379> CONFIG GET save
# "3600 1 300 100 60 10000"
```

Son pares `segundos cambios`:

```
3600 1      → snapshot cada 1 hora   si hubo al menos 1 cambio
300  100    → snapshot cada 5 min    si hubo al menos 100 cambios
60   10000  → snapshot cada 1 min    si hubo al menos 10,000 cambios
```

La que se cumpla primero dispara el snapshot. Cada mensaje del prospecto genera ~16-21 writes en Redis, así que 100 cambios se alcanzan en ~5-6 mensajes.

**¿Qué pasa al reiniciar Redis?**

```
Funcionando → RAM es la fuente de verdad
Snapshot    → RAM → dump.rdb (copia completa de toda la RAM, no incremental)
Redis cae   → ...
Redis arranca → dump.rdb → carga a RAM (recupera todo del último snapshot)
```

Se pierde solo lo que pasó entre el último snapshot y el crash.

### AOF (Append Only File)

```bash
127.0.0.1:6379> CONFIG GET appendonly
# "no" (desactivado por defecto)
```

AOF escribe cada comando a disco en tiempo real. Más seguro que RDB (máximo 1 segundo de pérdida) pero más lento. Para un chatbot, RDB es suficiente — perder 5 minutos de chat en un crash no es crítico.

---

## 6. Almacenamiento en Redis

### Formato de keys

```
checkpoint:{session_id}:__empty__:{checkpoint_uuid}
checkpoint_write:{session_id}:__empty__:{checkpoint_uuid}:{task_uuid}:{idx}
checkpoint_latest:{session_id}:__empty__
write_keys_zset:{session_id}:__empty__:{checkpoint_uuid}
```

El `session_id` es el `thread_id` de LangGraph (viene del request como `session_id`).

### Tipos de keys

| Key | Tipo Redis | Contenido |
|-----|-----------|-----------|
| `checkpoint:*` | JSON | Checkpoint completo (mensajes, channel_values, metadata) |
| `checkpoint_write:*` | JSON | Writes individuales (canales) |
| `checkpoint_latest:*` | string | Apuntador al último checkpoint UUID |
| `write_keys_zset:*` | sorted set | Registro de keys de writes |

### Comandos útiles

```bash
# Ver todas las keys de una sesión
KEYS checkpoint:3796:*

# Ver el último checkpoint (string → apuntador)
GET checkpoint_latest:3796:__empty__

# Ver contenido de un checkpoint (JSON)
JSON.GET checkpoint:3796:__empty__:<uuid> $

# Ver tipo de una key
TYPE checkpoint_latest:3796:__empty__

# Ver índices de búsqueda
FT._LIST

# Borrar sesión (equivalente a /clear)
# El agente lo hace con: await checkpointer.adelete_thread("3796")
```

---

## 7. Para nuevos agentes (plantilla)

Cada microservicio (agent_citas, agent_ventas, etc.) configura su propia allowlist en `runtime/_llm.py`. Solo cambiar el tipo custom:

```python
# agent_citas
saver.serde = JsonPlusRedisSerializer(
    allowed_json_modules=[("citas", "agent", "content", "CitaStructuredResponse")],
    allowed_msgpack_modules=[("citas.agent.content", "CitaStructuredResponse")],
)

# agent_ventas (futuro)
saver.serde = JsonPlusRedisSerializer(
    allowed_json_modules=[("ventas", "agent", "content", "VentaStructuredResponse")],
    allowed_msgpack_modules=[("ventas.agent.content", "VentaStructuredResponse")],
)
```

Para InMemorySaver (fallback), lo mismo pero solo `allowed_msgpack_modules`:

```python
InMemorySaver(
    serde=JsonPlusSerializer(
        allowed_msgpack_modules=[("citas.agent.content", "CitaStructuredResponse")]
    )
)
```

**Múltiples agentes comparten el mismo Redis** sin conflicto. Los checkpoints se separan por `thread_id` (session_id) que es único por agente desde el gateway.

---

## 8. Versiones verificadas

| Paquete | Versión | Nota |
|---------|---------|------|
| `langgraph-checkpoint` | 4.0.1 | Tiene `allowed_msgpack_modules`. La 4.0.0 **NO** lo tenía |
| `langgraph-checkpoint-redis` | 0.4.0 | Usa `JsonPlusRedisSerializer` internamente |
| Redis server | 8.6.1 | Standalone, RedisJSON + RediSearch integrados |

### Nota sobre 4.0.0 vs 4.0.1

```python
# 4.0.0: JsonPlusSerializer.__init__ solo acepta:
#   pickle_fallback, allowed_json_modules, __unpack_ext_hook__

# 4.0.1: JsonPlusSerializer.__init__ agrega:
#   allowed_msgpack_modules (con default _SENTINEL → True si no STRICT)
```

Si se usa 4.0.0, `allowed_msgpack_modules` no existe como parámetro → `TypeError`. Verificar versión con:

```bash
python -c "import importlib.metadata; print(importlib.metadata.version('langgraph-checkpoint'))"
```

### BaseRedisSaver no acepta `serde` en constructor

```python
# base.py línea 73:
super().__init__(serde=JsonPlusRedisSerializer())  # hardcoded
```

Por eso se sobreescribe `.serde` después de crear la instancia:

```python
saver = AsyncRedisSaver(redis_url=...)
saver.serde = JsonPlusRedisSerializer(allowed_json_modules=[...])  # overwrite
```

---

## 9. Ventana de mensajes (message window)

### Implementación actual: Opción B — `wrap_model_call`

Intercepta la llamada al LLM y recorta una copia del request. El checkpointer **no se modifica** — Redis guarda historial completo, el LLM solo ve los últimos N mensajes.

**Archivo:** `src/citas/agent/runtime/middleware.py`
**Variable:** `MAX_MESSAGES_HISTORY` (default 20, min 4, max 200)

### El problema del par AI↔Tool

OpenAI exige que todo `ToolMessage` tenga un `AIMessage` padre con el mismo `tool_call_id`. Si un corte elimina el `AIMessage` pero deja el `ToolMessage`:

```
BadRequestError: messages with role 'tool' must be a response
to a preceding message with 'tool_calls'
```

Solución: `trim_messages(..., allow_partial=False)` nunca corta en medio de un par.

### Opciones evaluadas

| | A `@before_model` | **B `wrap_model_call` ✅** | C `Summarization` | D `ContextEditing` | E Custom |
|---|---|---|---|---|---|
| Redis historial completo | No | **Sí** | No | No | Sí |
| Configurable por N msgs | Sí | **Sí** | Sí | No | Sí |
| Preserva semántica msgs viejos | No | **No** | Sí | Parcial | Sí |
| Costo extra LLM | No | **No** | 1 llamada | No | 1 llamada |
| Par AI↔Tool seguro | Sí | **Sí** | Sí | Sí | Manual |
| Built-in | Sí | **Sí** | Sí | Sí | No |

### Migración futura a SummarizationMiddleware (Opción C)

Si el agente necesita recordar contexto de muchos turnos atrás, reemplazar middleware:

```python
from langchain.agents.middleware import SummarizationMiddleware

agent = create_agent(
    ...,
    middleware=[SummarizationMiddleware(
        model=model,
        trigger=("messages", 20),
        keep=("messages", 10),
    )]
)
```

Trade-off: preserva semántica pero pierde historial exacto en Redis y cuesta 1 llamada extra al LLM.

---

## 10. Recursos y memoria RAM

### Por qué Redis es necesario

`InMemorySaver` crece sin límite (~50 MB/día con 100 contactos nuevos). Los caches TTL tienen techo fijo, pero el checkpointer no:

```
Sin Redis:  512 MB → OOM en ~3-5 días
            768 MB → OOM en ~7-10 días
            1 GB   → OOM en ~2-3 semanas

Con Redis:  RAM estable en ~308-428 MB (techo fijo)
            512 MB es suficiente indefinidamente
```

### Recomendaciones de recursos

| Escenario | RAM container | CPU |
|-----------|--------------|-----|
| Desarrollo local | 512 MB | 1 core |
| Producción con Redis | 512 MB | 1 core |
| Producción sin Redis (temporal) | 768 MB | 1 core |

| Redis (`memori_agentes`) | RAM |
|--------------------------|-----|
| < 50 empresas | 128 MB |
| 50-200 empresas | 256 MB |
