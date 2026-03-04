# Gestión de memoria y ventana de mensajes — agent_citas

Versiones analizadas: **LangChain 1.2.8 · LangGraph 1.0.7 · langgraph-checkpoint 4.0.0**

Este documento recoge todas las opciones investigadas para limitar el historial de mensajes
enviado al LLM, sus diferencias técnicas, trade-offs y cómo se relacionan con el checkpointer
(InMemorySaver hoy, Redis en el futuro).

---

## Conceptos clave

### Checkpointer vs ventana de mensajes

Son dos cosas distintas que se confunden fácilmente:

| Concepto | Qué hace | Implementación actual |
|----------|----------|-----------------------|
| **Checkpointer** | Guarda el historial completo de la sesión (persistencia) | `InMemorySaver` → futuro `AsyncRedisSaver` |
| **Ventana de mensajes** | Limita cuántos mensajes ve el LLM en cada llamada | `wrap_model_call` + `trim_messages` |

Son independientes. Puedes tener historial completo en Redis y aun así enviar solo los
últimos 20 mensajes al LLM en cada llamada.

### El problema del par AI↔Tool

OpenAI exige que todo `ToolMessage` tenga un `AIMessage` padre con el mismo `tool_call_id`
en la misma ventana de contexto. Si un corte elimina el `AIMessage` pero deja el
`ToolMessage`, la API lanza:

```
BadRequestError: messages with role 'tool' must be a response
to a preceding message with 'tool_calls'
```

La solución es `trim_messages(..., allow_partial=False)` de `langchain_core`, que nunca
corta en medio de un par. Si el corte exacto caería entre un par, retrocede hasta encontrar
un punto limpio.

---

## Versiones de la API — historia y cambios

### LangGraph `create_react_agent` (LangGraph directo, NO LangChain)

```python
from langgraph.prebuilt import create_react_agent
```

Parámetros para memoria disponibles según versión:

| Parámetro | Disponible desde | Notas |
|-----------|-----------------|-------|
| `messages_modifier` | LangGraph 0.2.x | Deprecated en versiones recientes |
| `state_modifier` | LangGraph 0.2.4+ | Reemplaza `messages_modifier` |
| `pre_model_hook` | LangGraph 1.0.x | Actual, más flexible |

**Importante:** `create_agent` de LangChain 1.2.8 **no acepta** `state_modifier` ni
`messages_modifier` — esos son parámetros de `create_react_agent` de LangGraph directamente.
Usarlos en `create_agent` lanza `TypeError`.

El archivo `docs/PENDIENTES.md` (sección M1) menciona `state_modifier` — esa implementación
es **incorrecta** para LangChain 1.2.8 y no hubiera funcionado.

### LangChain `create_agent` (LangChain 1.2.8 — el usado en este proyecto)

```python
from langchain.agents import create_agent
```

No tiene `state_modifier` ni `pre_model_hook`. El sistema de extensión es **middleware**:

```python
agent = create_agent(
    model=model,
    tools=AGENT_TOOLS,
    system_prompt=system_prompt,
    checkpointer=_checkpointer,
    response_format=CitaStructuredResponse,
    middleware=[mi_middleware],   # ← punto de extensión
)
```

---

## Opciones investigadas

### Opción A — `@before_model` con `RemoveMessage` (trim permanente)

**Qué hace:** Modifica el state del grafo antes de llamar al LLM. El checkpointer
(Redis) guarda el historial ya recortado.

```python
from langchain.agents.middleware import before_model
from langchain_core.messages import trim_messages, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

@before_model
async def _trim_history(state, runtime):
    msgs = state["messages"]
    if len(msgs) <= MAX_MESSAGES_HISTORY:
        return None
    trimmed = trim_messages(
        msgs,
        max_tokens=MAX_MESSAGES_HISTORY,
        strategy="last",
        token_counter=len,
        allow_partial=False,
        include_system=True,
        start_on="human",
    )
    return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *trimmed]}
```

**Flujo:**
```
State (checkpointer) ──→ before_model nodo
                              ↓ retorna {"messages": [...]}
                         LangGraph aplica al STATE
                              ↓
                         Checkpointer guarda mensajes recortados
                              ↓
                         LLM recibe los 20 mensajes
```

**Por qué `[RemoveMessage(id=REMOVE_ALL_MESSAGES), *trimmed]` y no solo `trimmed`:**
LangGraph usa un reducer para el campo `messages` — no reemplaza la lista, la fusiona/añade.
Retornar la lista trimmed sin `RemoveMessage` duplicaría mensajes. El `RemoveMessage` borra
todo primero y luego inserta los mensajes recortados.

| Aspecto | Valor |
|---------|-------|
| Modifica checkpointer | ✅ Sí (permanente) |
| Redis guarda | Solo los últimos N mensajes |
| Historial recuperable | ❌ No, se pierde al trimear |
| Compatible con C1 (Redis full history) | ❌ No |
| Costo extra LLM | ❌ Ninguno |
| Complejidad | Baja |

**Cuándo usar:** Si no te importa perder el historial completo y quieres la implementación
más simple. Útil con `InMemorySaver` donde el historial de todas formas se pierde al reiniciar.

---

### Opción B — `wrap_model_call` con `trim_messages` (trim no destructivo) ✅ IMPLEMENTADA

**Qué hace:** Intercepta la llamada al LLM y modifica una copia del request. El state y el
checkpointer no se tocan. Redis sigue guardando el historial completo.

```python
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from langchain_core.messages import trim_messages

@wrap_model_call
async def _message_window(request: ModelRequest, handler) -> ModelResponse:
    if not request.messages:
        return await handler(request)
    trimmed = trim_messages(
        list(request.messages),
        max_tokens=app_config.MAX_MESSAGES_HISTORY,
        strategy="last",
        token_counter=len,
        allow_partial=False,
        include_system=True,
        start_on="human",
    )
    return await handler(request.override(messages=trimmed))
```

`request.override(messages=trimmed)` crea un nuevo request con los mensajes recortados
sin modificar el request original ni el state.

**Flujo:**
```
State (checkpointer) ──→ [intacto, no se modifica]
                              ↓
                         wrap_model_call intercepta
                              ↓ copia del request con msgs recortados
                         LLM recibe los 20 mensajes
                              ↓
                         State sigue con historial completo
```

| Aspecto | Valor |
|---------|-------|
| Modifica checkpointer | ❌ No |
| Redis guarda | Historial completo ♾️ |
| Historial recuperable | ✅ Sí, siempre |
| Compatible con C1 (Redis full history) | ✅ Sí, diseñado para esto |
| Costo extra LLM | ❌ Ninguno |
| Complejidad | Baja-media |

**Configuración:** Variable de entorno `MAX_MESSAGES_HISTORY` (default 20, min 4, max 200).

**Cuándo usar:** Cuando quieres historial completo en Redis y solo limitar lo que ve el LLM.
Es la implementación actual del proyecto.

---

### Opción C — `SummarizationMiddleware` (built-in LangChain 1.2.8)

**Qué hace:** Cuando el historial supera un umbral, llama al LLM para generar un resumen
de los mensajes viejos y los reemplaza en el state. Es un trim inteligente que preserva
semántica pero modifica el checkpointer permanentemente.

```python
from langchain.agents.middleware import SummarizationMiddleware

agent = create_agent(
    ...
    middleware=[
        SummarizationMiddleware(
            model=model,                        # modelo para generar el resumen
            trigger=("messages", 20),           # se activa al llegar a 20 mensajes
            keep=("messages", 10),              # mantiene los 10 más recientes tras resumir
            # trigger=("tokens", 4000),         # alternativa: por tokens
            # trigger=("fraction", 0.8),        # alternativa: % del context window
            # trigger=[("messages", 20), ("tokens", 3000)],  # múltiples condiciones (OR)
        )
    ],
)
```

**Flujo:**
```
State llega a 20 msgs
    ↓ SummarizationMiddleware (before_model interno)
    ↓ Llama al LLM: "resume estos mensajes"
    ↓ Genera 1 HumanMessage con el resumen
    ↓ State: [resumen + últimos 10 msgs]
    ↓ Redis guarda [resumen + últimos 10]   ← historial original perdido
    ↓ LLM recibe [resumen + últimos 10]
```

| Aspecto | Valor |
|---------|-------|
| Modifica checkpointer | ✅ Sí (permanente) |
| Redis guarda | Historial resumido (no completo) |
| Historial recuperable | ⚠️ Solo como resumen, no original |
| Compatible con C1 (Redis full history) | ❌ No |
| Costo extra LLM | ⚠️ 1 llamada extra al activarse |
| Complejidad | Baja (built-in) |

**Tipos de trigger disponibles:**

```python
("messages", 20)      # al llegar a 20 mensajes
("tokens", 4000)      # al llegar a 4000 tokens aproximados
("fraction", 0.8)     # al usar el 80% del context window del modelo
[("messages", 20), ("tokens", 3000)]  # cualquiera de los dos (OR)
```

**Cuándo usar:** Cuando el agente necesita recordar contexto importante de hace muchos
turnos (nombres, preferencias, decisiones) y aceptas perder el historial exacto a cambio
de preservar la semántica.

---

### Opción D — `ContextEditingMiddleware` (built-in LangChain 1.2.8)

**Qué hace:** Cuando el total de tokens supera un umbral, reemplaza el contenido de los
`ToolMessage` más antiguos con `"[cleared]"`. Los mensajes siguen existiendo (no se eliminan),
solo se vacía su contenido. Preserva siempre los últimos N resultados de tools.

```python
from langchain.agents.middleware import ContextEditingMiddleware
from langchain.agents.middleware.context_editing import ClearToolUsesEdit

agent = create_agent(
    ...
    middleware=[
        ContextEditingMiddleware(
            edits=[ClearToolUsesEdit(
                trigger=100_000,    # tokens antes de activarse (default 100k)
                keep=3,             # cuántos ToolMessages recientes preservar
                clear_tool_inputs=False,  # si también limpiar los args del AIMessage
                placeholder="[cleared]",  # texto que reemplaza el contenido
            )]
        )
    ],
)
```

**Flujo:**
```
ToolMessage antiguo: content="lunes 10am, martes 3pm..."
    ↓ threshold de tokens superado
ToolMessage antiguo: content="[cleared]"  ← limpiado, pero el mensaje existe
AIMessage sigue con su tool_call_id      ← par no roto
```

No rompe el par AI↔Tool porque el `ToolMessage` sigue presente con su ID correcto.
Solo limpia el contenido.

| Aspecto | Valor |
|---------|-------|
| Modifica checkpointer | ✅ Sí (contenido de tools limpiado) |
| Configurable por N mensajes | ❌ No, solo por tokens |
| Umbral default | 100,000 tokens (muy alto para citas) |
| Costo extra LLM | ❌ Ninguno |
| Complejidad | Baja (built-in) |

**Cuándo usar:** Sesiones muy largas con muchas llamadas a tools donde los resultados
viejos de tools ocupan mucho espacio pero los turnos de conversación deben preservarse.
Para el caso de citas, el umbral default de 100k tokens nunca se alcanzaría en una
conversación normal.

---

### Opción E — `wrap_model_call` con resumen custom (no destructivo + semántica)

Combina lo mejor de B y C: Redis guarda el historial completo, el LLM recibe un resumen
de los mensajes viejos + los recientes. Requiere implementación custom.

```python
@wrap_model_call
async def _message_window_summarized(request: ModelRequest, handler) -> ModelResponse:
    msgs = list(request.messages)
    if len(msgs) <= 20:
        return await handler(request)

    # Resumir los mensajes viejos con el LLM (llamada extra)
    old_msgs = msgs[:-10]
    recent_msgs = msgs[-10:]
    summary_content = await _summarize_with_llm(old_msgs)
    summary_msg = HumanMessage(content=f"[Resumen previo]: {summary_content}")

    condensed = [summary_msg] + recent_msgs
    return await handler(request.override(messages=condensed))
    # Redis no se entera — sigue con historial completo
```

| Aspecto | Valor |
|---------|-------|
| Modifica checkpointer | ❌ No |
| Redis guarda | Historial completo ♾️ |
| LLM recibe | Resumen + últimos 10 msgs |
| Costo extra LLM | ⚠️ 1 llamada extra al activarse |
| Complejidad | Alta (implementación custom) |

**Cuándo usar:** Si en el futuro el agente necesita recordar contexto de conversaciones
muy largas Y quieres mantener historial completo en Redis para auditoría/debugging.

---

## Comparativa final

| | A `@before_model` | B `wrap_model_call` ✅ | C `Summarization` | D `ContextEditing` | E Custom |
|---|---|---|---|---|---|
| Redis historial completo | ❌ | ✅ | ❌ | ❌* | ✅ |
| Configurable por N msgs | ✅ | ✅ | ✅ | ❌ | ✅ |
| Preserva semántica msgs viejos | ❌ | ❌ | ✅ | ⚠️ | ✅ |
| Costo extra LLM | ❌ | ❌ | ⚠️ | ❌ | ⚠️ |
| Par AI↔Tool seguro | ✅** | ✅** | ✅ | ✅ | manual |
| Built-in (sin código custom) | ✅ | ✅ | ✅ | ✅ | ❌ |
| Cambio de código desde actual | pequeño | — | pequeño | pequeño | grande |

*D limpia contenido de tools pero los mensajes existen
**Siempre que se use `trim_messages(allow_partial=False)`

---

## Implementación actual

**Archivo:** `src/citas/agent/agent.py`
**Opción:** B — `wrap_model_call`
**Variable de control:** `MAX_MESSAGES_HISTORY` (env, default 20, min 4, max 200)

```python
# src/citas/config/config.py
MAX_MESSAGES_HISTORY: int = _get_int("MAX_MESSAGES_HISTORY", 20, min_val=4, max_val=200)

# src/citas/agent/agent.py
@wrap_model_call
async def _message_window(request: ModelRequest, handler) -> ModelResponse:
    if not request.messages:
        return await handler(request)
    trimmed = trim_messages(
        list(request.messages),
        max_tokens=app_config.MAX_MESSAGES_HISTORY,
        strategy="last",
        token_counter=len,
        allow_partial=False,
        include_system=True,
        start_on="human",
    )
    return await handler(request.override(messages=trimmed))

agent = create_agent(..., middleware=[_message_window])
```

---

## Cómo cambiar de opción en el futuro

### De B (actual) a C (SummarizationMiddleware)

Eliminar `_message_window` y sus imports. Agregar:

```python
from langchain.agents.middleware import SummarizationMiddleware

# en create_agent():
middleware=[
    SummarizationMiddleware(
        model=model,
        trigger=("messages", 20),
        keep=("messages", 10),
    )
]
```

### De B (actual) a OpenAI Agents SDK

Reescritura completa del agente. El SDK maneja memoria nativamente:

```python
from agents import Agent, Runner
from agents.memory import RedisSession

session = RedisSession(redis_url=REDIS_URL, session_id=str(session_id))
result = await Runner.run(agent, input=message, session=session,
                          session_settings=SessionSettings(limit=20))
```

Ventaja: `limit=20` reemplaza todo el middleware custom. Desventaja: migración completa
de tools, prompts y lógica de sesión.

---

## Referencias

- [LangChain 1.2 — Short-term memory](https://docs.langchain.com/oss/python/langchain/short-term-memory)
- [LangChain 1.2 — Built-in middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- [LangChain 1.2 — Custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)
- [OpenAI Agents SDK — Sessions](https://openai.github.io/openai-agents-python/sessions/)
- [langchain_core.messages.trim_messages API](https://python.langchain.com/api_reference/core/messages/langchain_core.messages.utils.trim_messages.html)
