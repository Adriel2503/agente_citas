# Pendientes técnicos — agent_citas

Madurez actual: **9 / 10** (C1 resuelto, solo queda C2 auth y tests).

---

## Resueltos

| ID | Descripción | Archivo(s) |
|----|-------------|-----------|
| C1 | AsyncRedisSaver con TTL 24h + fallback InMemorySaver | `agent/runtime/_llm.py`, `main.py`, `pyproject.toml` |
| M1 | Límite de ventana de mensajes (20 turnos) | `agent/runtime/middleware.py` |
| O2 | `/health` retorna 503 cuando APIs degradadas | `main.py`, `circuit_breaker.py` |
| O3 | Thundering herd en `contexto_negocio` y `preguntas_frecuentes` | `contexto_negocio.py`, `preguntas_frecuentes.py` |
| M3 | Lock cleanup simplificado (async → sync, `lock.locked()`) | `agent/agent.py` |
| M2 | Circuit breaker para `ws_calendario.php` | `booking.py`, `circuit_breaker.py`, `main.py` |

C1 implementado en `agent/runtime/_llm.py` (`init_checkpointer` / `close_checkpointer`),
dep `langgraph-checkpoint-redis>=0.4.0` en `pyproject.toml`, `REDIS_URL` configurado en Easypanel
apuntando a `memori_agentes`. Fallback automático a InMemorySaver si Redis no disponible.

---

## 🔴 Críticos (deben resolverse antes de producción)

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
✅ C1 — AsyncRedisSaver con TTL 24h (en producción, Redis en Easypanel)
✅ M1 — trim_messages (message_window middleware)

Pendiente:
  ⚠️  C2 — Auth X-Internal-Token
  📋 B1 — slots en CREAR_EVENTO (requiere coordinación con backend PHP)
  📋 Tests unitarios
```
