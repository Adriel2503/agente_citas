# Pendientes técnicos — agent_citas

Madurez actual: **10 / 10** (auth implementado, solo quedan tests y coordinación backend).

---

## Resueltos

C1 (AsyncRedisSaver), C2 (auth X-Internal-Token), M1 (message window 20 turnos), M2 (circuit breaker calendario),
M3 (lock cleanup), O2 (health 503), O3 (thundering herd), E1 (mapeo 10 excepciones OpenAI).

---

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
- `src/citas/tools/tools.py` — pasar `slots` desde `ctx.slots`

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

---

## Resumen de prioridades

```
Pendiente:
  📋 B1 — slots en CREAR_EVENTO (requiere backend PHP)
  📋 Tests unitarios
  📋 Activar auth — configurar INTERNAL_API_TOKEN en Easypanel + gateway Go
```
