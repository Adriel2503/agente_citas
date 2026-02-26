# Memory Profile — Agent Citas v2.0.0

Analisis detallado del consumo de RAM del microservicio en distintos escenarios de carga. Basado en los parametros reales del codigo y la configuracion por defecto.

---

## Tabla de Contenidos

1. [Parametros del sistema](#parámetros-del-sistema)
2. [Baseline: proceso en frio](#baseline-proceso-en-frío)
3. [Caches en memoria](#caches-en-memoria)
4. [InMemorySaver (checkpointer)](#inmemorysaver-checkpointer)
5. [Objetos auxiliares](#objetos-auxiliares)
6. [Escenarios de carga](#escenarios-de-carga)
7. [Proyeccion temporal (sin Redis)](#proyección-temporal-sin-redis)
8. [Impacto de la migracion a Redis](#impacto-de-la-migración-a-redis)
9. [Recomendaciones de recursos](#recomendaciones-de-recursos)
10. [Como monitorear](#cómo-monitorear)

---

## Parametros del sistema

Valores extraidos directamente del codigo y `config/config.py`:

| Parametro | Valor default | Archivo |
|-----------|--------------|---------|
| `AGENT_CACHE_MAXSIZE` | 500 | `config.py` |
| `AGENT_CACHE_TTL_MINUTES` | 60 min | `config.py` |
| `SCHEDULE_CACHE_TTL_MINUTES` | 5 min | `config.py` |
| `_SESSION_LOCKS_CLEANUP_THRESHOLD` | 500 | `agent.py:53` |
| `_LOCKS_CLEANUP_THRESHOLD` | 750 | `agent.py:66` |
| Horario cache maxsize | 500 | `horario_cache.py:34` |
| Contexto negocio cache maxsize | 500 | `contexto_negocio.py:28` |
| Preguntas frecuentes cache maxsize | 500 | `preguntas_frecuentes.py:27` |
| Busqueda productos cache maxsize | 2000 | `busqueda_productos.py:48` |
| Circuit breaker TTLCache maxsize (x4) | 500 c/u | `circuit_breaker.py:51` |
| httpx max_connections | 50 | `http_client.py:44` |
| httpx max_keepalive_connections | 20 | `http_client.py:45` |
| Checkpointer | `InMemorySaver` (sin limite) | `agent.py:41` |
| Docker image base | `python:3.12-slim` | `Dockerfile:3` |
| Empresas simultaneas (diseno) | < 50 | — |

---

## Baseline: proceso en frio

RAM consumida al arrancar el servidor sin ningun request. El proceso carga Python, las dependencias y espera conexiones.

| Componente | RAM estimada | Notas |
|-----------|-------------|-------|
| Python 3.12 runtime | ~25 MB | Interprete + stdlib |
| FastAPI + Uvicorn + Starlette | ~8 MB | Framework ASGI |
| Pydantic v2 | ~7 MB | Validacion + modelos |
| LangChain + LangChain-Core | ~40 MB | Framework de agentes |
| LangGraph + checkpoint | ~15 MB | Grafo de ejecucion |
| langchain-openai + OpenAI SDK | ~25 MB | Cliente OpenAI |
| httpx + httpcore | ~5 MB | Cliente HTTP async |
| prometheus-client | ~3 MB | Metricas |
| Jinja2 + template compilado | ~2 MB | System prompt |
| tenacity + cachetools + dotenv | ~2 MB | Utilidades |
| Codigo de la aplicacion (`src/citas/`) | ~1 MB | Modulos propios |
| **Total baseline** | **~133 MB** | |

Este es el piso minimo. El servidor esta arriba pero no ha procesado ningun mensaje.

---

## Caches en memoria

Cada cache usa `cachetools.TTLCache` con un `maxsize` fijo. Cuando el cache esta lleno y llega una nueva entrada, la mas antigua se desaloja. El consumo maximo es predecible.

### Agent cache (el mas pesado)

```python
# agent.py:59
_agent_cache: TTLCache = TTLCache(maxsize=500, ttl=3600)
```

Cada entrada es un **grafo LangGraph compilado** que contiene:
- Referencia al modelo LLM (compartido, no duplica)
- System prompt renderizado (~2-10 KB segun empresa)
- Lista de tools con schemas (~1 KB)
- Grafo de estados compilado (~50-100 KB)
- Metadata del checkpointer

| Empresas en cache | RAM estimada | Calculo |
|-------------------|-------------|---------|
| 1 | ~2-5 MB | Primer agente compilado |
| 10 | ~20-50 MB | Escenario tipico |
| 50 | ~100-250 MB | Diseno maximo |
| 500 (maxsize) | ~1-2.5 GB | Teorico, nunca deberia llegar |

**En la practica con < 50 empresas simultaneas:** ~100-250 MB. El modelo LLM (`_model`) es un singleton compartido, no se duplica por empresa.

### Caches de datos (ligeros)

| Cache | maxsize | Contenido | Tamano por entrada | A tope |
|-------|---------|-----------|-------------------|--------|
| `_horario_cache` | 500 | Dict con 7 dias (`reunion_lunes`...) | ~1-2 KB | ~1 MB |
| `_contexto_cache` | 500 | String de contexto de negocio | ~5-20 KB | ~5-10 MB |
| `_preguntas_cache` | 500 | FAQs formateadas (Pregunta/Respuesta) | ~5-30 KB | ~5-15 MB |
| `_busqueda_cache` | 2000 | Lista de hasta 10 productos con metadata | ~2-10 KB | ~10-20 MB |
| **Total caches de datos** | | | | **~21-46 MB** |

### Resumen de caches

| Cache | A 50 empresas | A maxsize (500) |
|-------|--------------|-----------------|
| Agentes compilados | ~100-250 MB | ~1-2.5 GB |
| Datos (horario + contexto + FAQs + busqueda) | ~15-30 MB | ~21-46 MB |
| **Total caches** | **~115-280 MB** | **~1-2.5 GB** |

---

## InMemorySaver (checkpointer)

Este es el componente de **crecimiento ilimitado**. `InMemorySaver` guarda el historial completo de cada sesion en un dict en RAM. No tiene maxsize, no tiene TTL, no tiene limite de mensajes.

### Estructura interna

```
InMemorySaver._storage = {
    "thread_id_1": {  # session_id como string
        "channel_values": {
            "messages": [HumanMessage, AIMessage, ToolMessage, ...],
        },
        "metadata": {...},
        "parent_config": {...},
    },
    "thread_id_2": {...},
    ...  # crece indefinidamente
}
```

### Tamano por sesion

Cada mensaje en el historial contiene:
- `HumanMessage`: texto del usuario (~100-500 bytes)
- `AIMessage`: respuesta del LLM (~200-2000 bytes) + tool_calls si los hay
- `ToolMessage`: resultado de cada tool (~500-5000 bytes, depende de la tool)

Un turno tipico (usuario pregunta → agente responde, posiblemente usando 1-2 tools):

| Turno | Mensajes | ~Tamano |
|-------|----------|---------|
| Simple (sin tools) | 2 (Human + AI) | ~1-3 KB |
| Con check_availability | 4 (Human + AI + Tool + AI) | ~5-10 KB |
| Con create_booking | 6 (Human + AI + Tool(validate) + Tool(create) + AI) | ~8-15 KB |
| Promedio ponderado | ~3 mensajes | **~5 KB por turno** |

### Crecimiento por escenario

**Session_id de WhatsApp es permanente por contacto.** Nunca se reutiliza ni expira. Cada persona que escribe alguna vez queda en RAM para siempre.

| Escenario | Sesiones | Turnos/sesion | RAM InMemorySaver |
|-----------|----------|---------------|-------------------|
| 50 empresas, 5 contactos c/u, conversacion corta | 250 | 5 | ~6 MB |
| 50 empresas, 5 contactos c/u, conversacion normal | 250 | 15 | ~19 MB |
| 50 empresas, 20 contactos c/u (hora pico) | 1,000 | 10 | ~50 MB |
| Acumulado 1 dia (nuevos contactos) | 2,000 | 10 | ~100 MB |
| Acumulado 1 semana | 5,000 | 15 | ~375 MB |
| Acumulado 1 mes | 15,000+ | 15 | **~1.1 GB** |

**El problema no es el pico, es la acumulacion.** En WhatsApp los contactos no "cierran sesion"; simplemente dejan de escribir. Pero su historial queda en RAM.

---

## Objetos auxiliares

Objetos menores que contribuyen poco al total pero completan el cuadro:

| Componente | Max entradas | RAM estimada | Limpieza |
|-----------|-------------|-------------|----------|
| `_session_locks` | 500 (cleanup threshold) | ~0.5 MB | Automatica: elimina locks no-locked cuando supera 500 |
| `_agent_cache_locks` | 750 (1.5x maxsize) | ~0.5 MB | Automatica: elimina locks cuya key ya no esta en cache |
| `_fetch_locks` (horario) | 1 por empresa | ~despreciable | pop() en finally |
| `_fetch_locks` (contexto) | 1 por empresa | ~despreciable | pop() en finally |
| `_fetch_locks` (preguntas) | 1 por chatbot | ~despreciable | pop() en finally |
| `_busqueda_locks` | 1 por busqueda | ~despreciable | pop() en finally |
| Circuit breakers (4x TTLCache maxsize=500) | 2000 counters total | ~0.5 MB | TTL auto-expiry |
| httpx connection pool | 50 conexiones | ~2 MB | keepalive_expiry=30s |
| Prometheus metrics | ~30 series | ~1 MB | Fijo |
| **Total auxiliar** | | **~5 MB** | |

---

## Escenarios de carga

Combinacion de todos los componentes para escenarios reales.

### Escenario 1: Cold start (0 usuarios)

```
Baseline                        ~133 MB
Caches                             0 MB
InMemorySaver                      0 MB
Auxiliar                          ~2 MB
────────────────────────────────────────
TOTAL                           ~135 MB
```

### Escenario 2: Carga normal (50 empresas, hora pico)

50 empresas activas, ~10 contactos por empresa, conversaciones de ~10 turnos.

```
Baseline                        ~133 MB
Agent cache (50 empresas)       ~150 MB  (promedio 3 MB/agente)
Caches de datos (50 empresas)    ~20 MB
InMemorySaver (500 sesiones)     ~25 MB
Auxiliar                          ~5 MB
────────────────────────────────────────
TOTAL                           ~333 MB
```

### Escenario 3: Carga alta (50 empresas, pico maximo)

50 empresas, 20 contactos simultaneos por empresa, agentes pesados.

```
Baseline                        ~133 MB
Agent cache (50 empresas)       ~250 MB  (agentes con prompts largos)
Caches de datos (llenos)         ~40 MB
InMemorySaver (1000 sesiones)    ~50 MB
Auxiliar                          ~5 MB
────────────────────────────────────────
TOTAL                           ~478 MB
```

### Escenario 4: 1 semana sin reiniciar

50 empresas, acumulacion de sesiones de WhatsApp.

```
Baseline                        ~133 MB
Agent cache (50 empresas)       ~200 MB
Caches de datos                  ~30 MB
InMemorySaver (5000 sesiones)   ~375 MB  ← CRECIMIENTO ILIMITADO
Auxiliar                          ~5 MB
────────────────────────────────────────
TOTAL                           ~743 MB
```

### Escenario 5: 1 mes sin reiniciar (worst case)

```
Baseline                        ~133 MB
Agent cache (50 empresas)       ~200 MB
Caches de datos                  ~30 MB
InMemorySaver (15000+ sesiones) ~1.1 GB  ← MEMORY LEAK
Auxiliar                          ~5 MB
────────────────────────────────────────
TOTAL                          ~1.47 GB
```

---

## Proyeccion temporal (sin Redis)

Asumiendo 50 empresas activas, ~100 contactos nuevos por dia, ~10 turnos promedio por conversacion:

```
         RAM
  1.5 GB ┤                                              ╭──
         │                                          ╭───╯
  1.2 GB ┤                                     ╭────╯
         │                                ╭────╯
  1.0 GB ┤ · · · · · · · · · · · · · ·╭──╯· · · · · · · ← OOM con 1 GB
         │                         ╭───╯
  768 MB ┤ · · · · · · · · · · ╭──╯ · · · · · · · · · · ← OOM con 768 MB
         │                 ╭───╯
  512 MB ┤ · · · · · · ╭──╯ · · · · · · · · · · · · · · ← OOM con 512 MB
         │          ╭───╯
  333 MB ┤─────────╯           ← carga normal estable
         │     ╭───╯
  135 MB ┤─────╯ cold start
         │
       0 ┼──────┬──────┬──────┬──────┬──────┬──────┬────
         0     Dia 1  Dia 3  Dia 7  Dia 14 Dia 21 Dia 30
              (100)  (300)  (700)  (1400) (2100) (3000)
                        sesiones acumuladas
```

**El componente que crece es unicamente `InMemorySaver`.** Los caches TTL tienen techo fijo.

| Limite de RAM | Tiempo estimado hasta OOM | Sesiones acumuladas |
|---------------|---------------------------|---------------------|
| 512 MB | ~3-5 dias | ~300-500 |
| 768 MB | ~7-10 dias | ~700-1000 |
| 1 GB | ~14-20 dias | ~1400-2000 |
| 2 GB | ~30-45 dias | ~3000-5000 |

---

## Impacto de la migracion a Redis

Con `AsyncRedisSaver` (TTL 24h), el `InMemorySaver` desaparece completamente de la RAM del proceso Python.

### Comparacion directa

| Componente | Sin Redis | Con Redis |
|-----------|-----------|-----------|
| Baseline | ~133 MB | ~133 MB |
| Agent cache (50 empresas) | ~150-250 MB | ~150-250 MB (igual, es in-process) |
| Caches de datos | ~20-40 MB | ~20-40 MB (igual) |
| **InMemorySaver** | **~25 MB → 1+ GB** (crece) | **~0 MB** (en Redis) |
| Auxiliar | ~5 MB | ~5 MB |
| **Total** | **333 MB → 1.5 GB+** | **~308-428 MB (estable)** |

### RAM del container Redis (`memori_agentes`)

Redis es extremadamente eficiente en memoria:

| Sesiones activas (TTL 24h) | RAM Redis estimada |
|----------------------------|-------------------|
| 500 sesiones (10 turnos c/u) | ~25 MB |
| 2000 sesiones | ~100 MB |
| 5000 sesiones | ~250 MB |

Redis con 256 MB de RAM es mas que suficiente para el volumen actual.

### Perfil estable con Redis

```
         RAM
  512 MB ┤─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  ← limite container
         │
  428 MB ┤                    pico maximo
         │                ╭──────╮
  350 MB ┤───────────────╯      ╰───────────────────────  ← carga normal
         │          ╭────╯
  308 MB ┤─────────╯   caches llenandose
         │     ╭───╯
  133 MB ┤─────╯ cold start
         │
       0 ┼──────┬──────┬──────┬──────┬──────┬──────┬────
         0     Dia 1  Dia 3  Dia 7  Dia 14 Dia 21 Dia 30

                    RAM ESTABLE — sin crecimiento
```

---

## Recomendaciones de recursos

### Container agent_citas

| Escenario | RAM recomendada | CPU | Justificacion |
|-----------|----------------|-----|---------------|
| Desarrollo local | 512 MB | 1 core | Pocas empresas, sesiones cortas |
| Produccion con Redis | 512 MB | 1 core | InMemorySaver eliminado; caches con techo fijo |
| Produccion sin Redis (temporal) | 768 MB | 1 core | Margen para ~7-10 dias sin reiniciar |
| Produccion sin Redis + margen | 1 GB | 1 core | ~2-3 semanas antes de OOM |

### Container Redis (`memori_agentes`)

| Escenario | RAM recomendada |
|-----------|----------------|
| < 50 empresas | 128 MB |
| 50-200 empresas | 256 MB |

### Configuracion Docker recomendada

```yaml
# compose.yaml — produccion con Redis
services:
  agent_citas:
    build: .
    ports:
      - "8002:8002"
    env_file:
      - .env
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"
        reservations:
          memory: 256M
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

```bash
# docker run — produccion sin Redis (temporal)
docker run -d \
  --name agent-citas \
  -p 8002:8002 \
  --env-file .env \
  --restart unless-stopped \
  --memory=768m \
  --cpus=1.0 \
  agent-citas:latest
```

---

## Como monitorear

### Metricas Prometheus disponibles

```bash
# Entradas en cache (gauge)
curl -s http://localhost:8002/metrics | grep cache_entries
# agent_citas_cache_entries{cache_type="schedule"} 12

# Hits vs misses del agent cache
curl -s http://localhost:8002/metrics | grep citas_agent_cache
# citas_agent_cache_total{result="hit"} 450
# citas_agent_cache_total{result="miss"} 50

# Hits vs misses de busqueda
curl -s http://localhost:8002/metrics | grep citas_search_cache
```

### Memoria del proceso (desde fuera)

```bash
# Docker stats (en vivo)
docker stats agent-citas --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"

# Snapshot unico
docker stats agent-citas --no-stream

# Detalle del container
docker inspect agent-citas --format '{{.HostConfig.Memory}}'
```

### Alertas sugeridas

| Condicion | Accion |
|-----------|--------|
| RSS > 400 MB (con Redis) | Investigar: cache maxsize excesivo o leak |
| RSS > 600 MB (sin Redis) | Normal si lleva dias arriba. Planificar reinicio o migrar a Redis |
| RSS > 80% del limite del container | Alerta critica: OOM inminente |
| OOM kill en logs de Docker | Aumentar memoria o migrar a Redis |

```bash
# Verificar si hubo OOM kill
docker inspect agent-citas --format '{{.State.OOMKilled}}'

# Logs del sistema (Linux)
dmesg | grep -i "oom\|killed"
```

---

## Resumen ejecutivo

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  Sin Redis:  RAM crece ~50 MB/dia por InMemorySaver          │
│              512 MB → OOM en ~3-5 dias                       │
│              768 MB → OOM en ~7-10 dias                      │
│              1 GB   → OOM en ~2-3 semanas                    │
│                                                              │
│  Con Redis:  RAM estable en ~308-428 MB (techo fijo)         │
│              512 MB es suficiente indefinidamente             │
│              Costo: Redis con 128-256 MB adicional           │
│                                                              │
│  Componente mas caro: agent cache (~3-5 MB por empresa)      │
│  Componente peligroso: InMemorySaver (crece sin limite)      │
│  Todo lo demas: ~30 MB total con techo fijo                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```
