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

### C1 — InMemorySaver sin TTL (memory leak)

**Problema:** `InMemorySaver` guarda el historial de cada sesión en RAM sin límite de tiempo.
El `session_id` en WhatsApp es permanente por contacto y nunca cambia → la RAM crece
indefinidamente mientras el proceso esté vivo. Con 50–200 empresas y múltiples contactos
activos esto eventualmente agota la memoria del container.

**Solución: migrar a `AsyncRedisSaver` con TTL de 24 horas.**

Redis (`memori_agentes` en Easypanel) ya existe. Solo falta configurarlo.

#### Paso 1 — Instalar dependencia

```bash
pip install langgraph-checkpoint-redis
```

Agregar a `requirements.txt`:
```
langgraph-checkpoint-redis>=0.1.0
```

#### Paso 2 — Configurar `REDIS_URL` en Easypanel

En las variables de entorno del servicio `agente_citas`:
```
REDIS_URL=redis://memori_agentes:6379
```

El nombre `memori_agentes` es el hostname interno de Docker Compose en Easypanel.
`REDIS_URL` ya está leída en `config/config.py` (línea 105), no hay que agregarla.

#### Paso 3 — Modificar `agent/agent.py`

Reemplazar `InMemorySaver` por `AsyncRedisSaver`:

```python
# Antes:
from langgraph.checkpoint.memory import InMemorySaver
_checkpointer = InMemorySaver()

# Después:
import os
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

# El TTL de 86400 segundos (24h) elimina automáticamente el historial de cada sesión
# pasado un día de inactividad — mismo criterio que N8N/WhatsApp.
_checkpointer: AsyncRedisSaver | None = None

async def _get_checkpointer() -> AsyncRedisSaver:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = AsyncRedisSaver.from_conn_string(
            app_config.REDIS_URL,
            ttl={"default_ttl": 86400},  # 24 horas en segundos
        )
        await _checkpointer.asetup()  # crea índices la primera vez
    return _checkpointer
```

Luego en `_get_agent()` cambiar:
```python
# Antes:
agent = create_agent(
    model=model,
    tools=AGENT_TOOLS,
    system_prompt=system_prompt,
    checkpointer=_checkpointer,
    response_format=CitaStructuredResponse,
)

# Después:
checkpointer = await _get_checkpointer()
agent = create_agent(
    model=model,
    tools=AGENT_TOOLS,
    system_prompt=system_prompt,
    checkpointer=checkpointer,
    response_format=CitaStructuredResponse,
)
```

#### Beneficios tras la migración

- Historial persiste si el container se reinicia (deploy, crash)
- TTL 24h: sesiones inactivas se eliminan automáticamente
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

### M1 — Límite de ventana de mensajes (20 turnos)

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

## 🟢 Diferidas (no urgentes)

### Tests

No existe suite de tests. Las áreas más importantes a cubrir:

- `services/booking.py` — `_parse_time_to_24h`, `_build_fecha_inicio_fin`
- `services/circuit_breaker.py` — transiciones CLOSED → OPEN → reset
- `agent/agent.py` — `_validate_context`, `_prepare_agent_context`
- `services/schedule_validator.py` — validación de horarios y slots

### Streaming

Actualmente el gateway espera la respuesta completa antes de enviarla al cliente.
El TTFT (Time To First Token) es igual al tiempo total de respuesta (~3–8s).

Para habilitar streaming: FastAPI `StreamingResponse` + LangGraph `astream_events`.
Requiere cambios en el gateway Go para consumir SSE y retransmitir a N8N/WhatsApp.

---

## Resumen de prioridades

```
Ahora mismo (sin Redis):
  ✅ Implementar trim_messages (M1) — 10 min, 1 archivo

Antes de producción con carga real:
  ⚠️  Migrar InMemorySaver → AsyncRedisSaver (C1)
  ⚠️  Auth X-Internal-Token (C2)

Después:
  📋 Tests unitarios
  📋 Streaming SSE
```
