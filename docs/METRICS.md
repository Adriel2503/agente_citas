# Metricas Prometheus — Agent Citas

El agente expone **21 metricas** en `GET /metrics` (puerto 8002) via `prometheus_client`.
Formato: Prometheus text/plain.

Prefijo unico: **`citas_`** para todas las metricas (negocio e infraestructura).

> Config de scraping: ver [DEPLOYMENT.md](DEPLOYMENT.md).
> Descripcion del endpoint: ver [API.md](API.md).

---

## Inventario de metricas

### Contadores (14)

| Nombre | Labels | Descripcion |
|--------|--------|-------------|
| `citas_chat_requests_total` | `empresa_id` | Mensajes recibidos por el agente |
| `citas_chat_errors_total` | `error_type` | Errores procesando mensajes |
| `citas_llm_requests_total` | `status` | Invocaciones al agente LLM |
| `citas_llm_tokens_total` | `type` | Tokens consumidos (input/output/total) |
| `citas_llm_tokens_by_empresa_total` | `empresa_id`, `type` | Tokens consumidos por empresa |
| `citas_booking_attempts_total` | — | Intentos de crear cita |
| `citas_booking_success_total` | — | Citas creadas exitosamente |
| `citas_booking_failed_total` | `reason` | Citas fallidas |
| `citas_tool_calls_total` | `tool_name` | Llamadas a tools del agente |
| `citas_tool_errors_total` | `tool_name`, `error_type` | Errores en tools |
| `citas_api_calls_total` | `endpoint`, `status` | Llamadas a APIs externas MaravIA |
| `citas_http_requests_total` | `status` | Requests HTTP al endpoint /api/chat |
| `citas_agent_cache_total` | `result` | Hits/misses del cache de agente |
| `citas_search_cache_total` | `result` | Hits/misses del cache de busqueda |
| `citas_availability_degradation_total` | `service`, `reason` | Validacion degradada (riesgo double-booking) |

### Histogramas (5)

| Nombre | Labels | Descripcion | Buckets (s) |
|--------|--------|-------------|-------------|
| `citas_http_duration_seconds` | — | Latencia total /api/chat | 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 90, 120 |
| `citas_llm_duration_seconds` | `status` | Latencia de agent.ainvoke (LLM + tool calls) | 0.5, 1, 2, 5, 10, 20, 30, 60, 90 |
| `citas_chat_response_duration_seconds` | `status` | Latencia total del procesamiento (lock + ainvoke + resultado) | 0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 90 |
| `citas_tool_execution_duration_seconds` | `tool_name` | Latencia por tool | 0.1, 0.5, 1, 2, 5, 10, 20, 30 |
| `citas_api_call_duration_seconds` | `endpoint` | Latencia de APIs externas | 0.1, 0.25, 0.5, 1, 2.5, 5, 10 |

Cada histograma genera 3 series: `_bucket`, `_sum`, `_count`.

### Gauge (1)

| Nombre | Labels | Descripcion |
|--------|--------|-------------|
| `citas_cache_entries` | `cache_type` | Entradas actuales en cache |

### Info (1)

| Nombre | Campos | Descripcion |
|--------|--------|-------------|
| `citas_info` | `version`, `model`, `agent_type` | Metadata del agente |

---

## Valores de labels

### `status` — citas_http_requests_total

| Valor | Significado |
|-------|-------------|
| `success` | Request procesado correctamente |
| `timeout` | Excedio CHAT_TIMEOUT |
| `error` | ValueError o excepcion general |

> Nota: `asyncio.CancelledError` no se cuenta (request abortado externamente).

### `status` — histogramas (chat_response, llm_call)

| Valor | Significado |
|-------|-------------|
| `success` | Operacion exitosa |
| `error` | Excepcion durante la operacion |

### `error_type` — chat_errors_total

| Valor | Significado |
|-------|-------------|
| `context_error` | Validacion de contexto fallida |
| `agent_creation_error` | Error creando el agente LangGraph |
| `openai_auth_error` | API key invalida (401) |
| `openai_permission_denied` | API key sin permisos (403) |
| `openai_not_found` | Modelo no disponible (404) |
| `openai_rate_limit` | Rate limit de OpenAI (429) |
| `openai_server_error` | Error del servidor OpenAI (5xx) |
| `openai_timeout` | Timeout de OpenAI |
| `openai_connection_error` | No se pudo conectar a OpenAI |
| `openai_content_filter` | Contenido rechazado por filtro |
| `openai_length_limit` | Respuesta cortada por max_tokens |
| `openai_bad_request` | Request invalido a OpenAI (400) |
| `agent_execution_error` | Error no clasificado durante ejecucion |

### `reason` — booking_failed_total

| Valor | Significado |
|-------|-------------|
| `invalid_datetime` | Fecha/hora invalida |
| `circuit_open` | Circuit breaker abierto |
| `api_error` | Error en respuesta de API |
| `timeout` | Timeout de la solicitud |
| `http_{code}` | Error HTTP (ej: `http_400`, `http_500`) |
| `connection_error` | Error de conexion |
| `unknown_error` | Error no clasificado |

### `service` y `reason` — availability_degradation_total

**service:**

| Valor | Origen |
|-------|--------|
| `availability_check` | `availability_client.py` |
| `schedule_fetch` | `schedule_validator.py` |

**reason:**

| Valor | Significado |
|-------|-------------|
| `api_success_false` | API retorno success=false |
| `circuit_open` | Circuit breaker abierto |
| `transport_error` | Error de red/transporte |
| `timeout` | Timeout de solicitud |
| `http_error` | Error de estado HTTP |
| `parse_error` | Error parseando respuesta JSON |
| `unknown` | Error no clasificado |

### `tool_name` — tool_calls_total, tool_errors_total, tool_execution_duration

| Valor |
|-------|
| `check_availability` |
| `create_booking` |
| `search_productos_servicios` |

### `endpoint` — api_calls_total, api_call_duration

| Valor | Operacion |
|-------|-----------|
| `crear_evento` | Crear cita/evento en calendario |
| `consultar_disponibilidad` | Consultar disponibilidad de horario |
| `sugerir_horarios` | Sugerir horarios disponibles |

### `result` — caches

| Valor | Donde |
|-------|-------|
| `hit` | agent_cache, search_cache |
| `miss` | agent_cache, search_cache |
| `circuit_open` | solo search_cache |

### `cache_type` — cache_entries (Gauge)

| Valor |
|-------|
| `agent` |
| `search` |

---

## Consultas PromQL

### Tasas (requests por segundo)

```promql
# Requests HTTP por segundo (ventana 5 min)
rate(citas_http_requests_total[5m])

# Mensajes por empresa por minuto
rate(citas_chat_requests_total{empresa_id="123"}[5m]) * 60
```

### Tasa de exito de citas

```promql
# Booking success rate (ultima hora)
rate(citas_booking_success_total[1h])
  / rate(citas_booking_attempts_total[1h])

# Fallo por razon
sum by (reason) (rate(citas_booking_failed_total[1h]))
```

### Tasa de error

```promql
# Error rate HTTP
sum(rate(citas_http_requests_total{status=~"timeout|error"}[5m]))
  / sum(rate(citas_http_requests_total[5m]))

# Error rate por tool
sum by (tool_name) (rate(citas_tool_errors_total[5m]))
  / sum by (tool_name) (rate(citas_tool_calls_total[5m]))
```

### Hit rate de caches

```promql
# Agent cache hit rate
rate(citas_agent_cache_total{result="hit"}[5m])
  / sum(rate(citas_agent_cache_total[5m]))

# Search cache hit rate
rate(citas_search_cache_total{result="hit"}[5m])
  / sum(rate(citas_search_cache_total[5m]))
```

### Latencia promedio

```promql
# Latencia promedio /api/chat
rate(citas_http_duration_seconds_sum[5m])
  / rate(citas_http_duration_seconds_count[5m])

# Latencia promedio LLM
rate(citas_llm_duration_seconds_sum[5m])
  / rate(citas_llm_duration_seconds_count[5m])

# Latencia promedio por tool
rate(citas_tool_execution_duration_seconds_sum[5m])
  / rate(citas_tool_execution_duration_seconds_count[5m])

# Latencia promedio APIs externas
rate(citas_api_call_duration_seconds_sum[5m])
  / rate(citas_api_call_duration_seconds_count[5m])
```

### Percentiles

```promql
# p95 latencia /api/chat
histogram_quantile(0.95, rate(citas_http_duration_seconds_bucket[5m]))

# p50 latencia LLM
histogram_quantile(0.50, rate(citas_llm_duration_seconds_bucket[5m]))

# p99 latencia /api/chat
histogram_quantile(0.99, rate(citas_http_duration_seconds_bucket[5m]))

# p95 por tool
histogram_quantile(0.95,
  sum by (le, tool_name) (
    rate(citas_tool_execution_duration_seconds_bucket[5m])
  )
)
```

### Degradacion y alertas

```promql
# ALERTA: degradacion activa (riesgo double-booking)
# Cualquier valor > 0 indica que se retorno available=True sin validar
rate(citas_availability_degradation_total[5m]) > 0

# Desglose por servicio y razon
sum by (service, reason) (rate(citas_availability_degradation_total[5m]))

# ALERTA: circuit breaker bloqueando bookings
increase(citas_booking_failed_total{reason="circuit_open"}[5m]) > 0

# ALERTA: p95 > 10s
histogram_quantile(0.95, rate(citas_http_duration_seconds_bucket[5m])) > 10

# ALERTA: timeout rate > 5%
sum(rate(citas_http_requests_total{status="timeout"}[5m]))
  / sum(rate(citas_http_requests_total[5m])) > 0.05
```

### Totales globales

```promql
# Total mensajes (todas las empresas)
sum(citas_chat_requests_total)

# Total citas exitosas
citas_booking_success_total

# Entradas actuales en caches
citas_cache_entries
```

### Desglose por empresa

```promql
# Top 10 empresas mas activas (ultima hora)
topk(10, increase(citas_chat_requests_total[1h]))

# Mensajes por empresa por minuto
sum by (empresa_id) (rate(citas_chat_requests_total[5m])) * 60
```

---

## Scraping

- **Target:** `agente_citas:8002`
- **Path:** `/metrics`
- **Intervalo recomendado:** 15s

Para la configuracion completa de Prometheus, ver [DEPLOYMENT.md](DEPLOYMENT.md).
