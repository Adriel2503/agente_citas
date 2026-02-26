# Deployment Guide — Agent Citas v2.0.0

Guia completa para desplegar el agente de citas en local, Docker y Easypanel (produccion).

---

## Tabla de Contenidos

1. [Requisitos](#requisitos)
2. [Ejecucion Local](#ejecución-local)
3. [Variables de Entorno](#variables-de-entorno)
4. [Docker](#docker)
5. [Easypanel (Produccion)](#easypanel-producción)
6. [Verificacion del Despliegue](#verificación-del-despliegue)
7. [Monitoreo](#monitoreo)
8. [Troubleshooting](#troubleshooting)
9. [Escalado y Limitaciones](#escalado-y-limitaciones)
10. [Seguridad del Container](#seguridad-del-container)

---

## Requisitos

| Requisito | Version minima | Notas |
|-----------|---------------|-------|
| Python | 3.12 | Dockerfile usa `python:3.12-slim` |
| OpenAI API Key | — | Modelo `gpt-4o-mini` por defecto |
| Acceso a APIs MaravIA | — | `ws_calendario`, `ws_agendar_reunion`, `ws_informacion_ia`, `ws_preguntas_frecuentes` |
| Docker (opcional) | 24+ | Para despliegue en contenedor |
| Redis (opcional) | 7+ | Para checkpointer persistente (`memori_agentes` en Easypanel) |

---

## Ejecucion Local

### 1. Crear entorno virtual e instalar dependencias

```bash
# Crear entorno virtual
python -m venv venv_agent_citas

# Activar — Windows
venv_agent_citas\Scripts\activate

# Activar — Linux/Mac
source venv_agent_citas/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
# Copiar plantilla
cp .env.example .env

# Editar con tus credenciales (minimo requerido: OPENAI_API_KEY)
```

El servidor buscara el archivo `.env` hacia arriba en el arbol de directorios (hasta 6 niveles), por lo que puede estar en el directorio del proyecto o en un directorio padre.

### 3. Configurar PYTHONPATH

El codigo fuente vive en `src/`. Para que Python encuentre el modulo `citas` fuera de Docker:

```bash
# Linux/Mac
export PYTHONPATH=$(pwd)/src

# Windows (PowerShell)
$env:PYTHONPATH = "$(Get-Location)\src"

# Windows (CMD)
set PYTHONPATH=%CD%\src
```

### 4. Arrancar el servidor

```bash
# Modo normal
python -m citas.main

# Modo debug
LOG_LEVEL=DEBUG python -m citas.main
```

El servidor arranca en `http://0.0.0.0:8002` (configurable con `SERVER_PORT`).

**Salida esperada al arrancar:**
```
============================================================
INICIANDO AGENTE CITAS - MaravIA
============================================================
Host: 0.0.0.0:8002
Modelo: gpt-4o-mini
Timeout LLM: 60s
Timeout API: 10s
Cache TTL horario: 5 min
Cache TTL agente:  60 min
Log Level: INFO
------------------------------------------------------------
Endpoint: POST /api/chat
Health:   GET  /health
Metrics:  GET  /metrics
Tools internas del agente:
- check_availability (consulta horarios)
- create_booking (crea citas/eventos)
- search_productos_servicios (busca productos/servicios)
============================================================
```

---

## Variables de Entorno

### Minimas requeridas

```bash
OPENAI_API_KEY=sk-...
```

Todo lo demas tiene defaults funcionales. Ver `.env.example` para la plantilla completa.

### Referencia completa

#### Development (`.env`)

```bash
# ── LLM ────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_TEMPERATURE=0.5
OPENAI_TIMEOUT=60
MAX_TOKENS=2048

# ── Servidor ───────────────────────────────────────────────
SERVER_HOST=0.0.0.0
SERVER_PORT=8002
CHAT_TIMEOUT=120

# ── Logging ────────────────────────────────────────────────
LOG_LEVEL=DEBUG
LOG_FILE=                         # vacio = solo stdout

# ── HTTP y reintentos ─────────────────────────────────────
API_TIMEOUT=10                    # timeout de lectura de APIs MaravIA
HTTP_RETRY_ATTEMPTS=3             # reintentos ante TransportError
HTTP_RETRY_WAIT_MIN=1             # backoff minimo (segundos)
HTTP_RETRY_WAIT_MAX=4             # backoff maximo (segundos)

# ── Circuit breaker ───────────────────────────────────────
CB_THRESHOLD=3                    # fallos consecutivos para abrir
CB_RESET_TTL=300                  # segundos hasta auto-reset (5 min)

# ── Cache ─────────────────────────────────────────────────
SCHEDULE_CACHE_TTL_MINUTES=5      # horario de reuniones
AGENT_CACHE_TTL_MINUTES=60        # agente compilado por empresa
AGENT_CACHE_MAXSIZE=500           # maximo de agentes en cache

# ── Zona horaria ──────────────────────────────────────────
TIMEZONE=America/Lima

# ── APIs MaravIA ──────────────────────────────────────────
API_CALENDAR_URL=https://api.maravia.pe/servicio/ws_calendario.php
API_AGENDAR_REUNION_URL=https://api.maravia.pe/servicio/ws_agendar_reunion.php
API_INFORMACION_URL=https://api.maravia.pe/servicio/ws_informacion_ia.php
API_PREGUNTAS_FRECUENTES_URL=https://api.maravia.pe/servicio/n8n/ws_preguntas_frecuentes.php

# ── Redis (checkpointer persistente) ──────────────────────
# REDIS_URL=redis://localhost:6379

# ── LangSmith tracing (opcional, para debugging) ──────────
LANGCHAIN_TRACING_V2=false
# LANGCHAIN_API_KEY=<tu_langsmith_api_key>
# LANGCHAIN_PROJECT=agent_citas
```

#### Production (Easypanel / variables de entorno del servicio)

```bash
# ── LLM ────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini          # gpt-4o para mayor calidad
OPENAI_TEMPERATURE=0.5
OPENAI_TIMEOUT=60
MAX_TOKENS=2048

# ── Servidor ───────────────────────────────────────────────
SERVER_HOST=0.0.0.0
SERVER_PORT=8002
CHAT_TIMEOUT=120

# ── Logging ────────────────────────────────────────────────
LOG_LEVEL=INFO                    # WARNING en produccion estable
LOG_FILE=                         # vacio: Docker captura stdout (docker logs)

# ── HTTP y reintentos ─────────────────────────────────────
API_TIMEOUT=10
HTTP_RETRY_ATTEMPTS=3
HTTP_RETRY_WAIT_MIN=1
HTTP_RETRY_WAIT_MAX=4

# ── Circuit breaker ───────────────────────────────────────
CB_THRESHOLD=3
CB_RESET_TTL=300

# ── Cache ─────────────────────────────────────────────────
SCHEDULE_CACHE_TTL_MINUTES=10     # cache mas largo reduce llamadas a API
AGENT_CACHE_TTL_MINUTES=60
AGENT_CACHE_MAXSIZE=500

# ── Zona horaria ──────────────────────────────────────────
TIMEZONE=America/Lima

# ── APIs MaravIA ──────────────────────────────────────────
API_CALENDAR_URL=https://api.maravia.pe/servicio/ws_calendario.php
API_AGENDAR_REUNION_URL=https://api.maravia.pe/servicio/ws_agendar_reunion.php
API_INFORMACION_URL=https://api.maravia.pe/servicio/ws_informacion_ia.php
API_PREGUNTAS_FRECUENTES_URL=https://api.maravia.pe/servicio/n8n/ws_preguntas_frecuentes.php

# ── Redis (hostname interno Docker Compose en Easypanel) ──
REDIS_URL=redis://memori_agentes:6379

# ── LangSmith ─────────────────────────────────────────────
LANGCHAIN_TRACING_V2=false
```

**Nota sobre `LOG_FILE` en Docker:** El container corre como usuario `appuser` (sin home directory ni permisos de escritura fuera de `/tmp`). En produccion con Docker, dejar `LOG_FILE` vacio y usar `docker logs` para ver la salida de stdout. Si necesitas archivo de log, monta un volumen con permisos de escritura.

### Valores y rangos validados

Todos los valores se validan en `config/config.py`. Si un valor esta fuera de rango o tiene tipo invalido, el sistema usa el default sin error.

| Variable | Tipo | Rango | Default |
|----------|------|-------|---------|
| `OPENAI_TEMPERATURE` | float | 0.0 – 2.0 | `0.5` |
| `OPENAI_TIMEOUT` | int | 1 – 300s | `60` |
| `MAX_TOKENS` | int | 1 – 128000 | `2048` |
| `SERVER_PORT` | int | 1 – 65535 | `8002` |
| `API_TIMEOUT` | int | 1 – 120s | `10` |
| `CHAT_TIMEOUT` | int | 30 – 300s | `120` |
| `HTTP_RETRY_ATTEMPTS` | int | 1 – 10 | `3` |
| `HTTP_RETRY_WAIT_MIN` | int | 0 – 30s | `1` |
| `HTTP_RETRY_WAIT_MAX` | int | 1 – 60s | `4` |
| `CB_THRESHOLD` | int | 1 – 20 | `3` |
| `CB_RESET_TTL` | int | 60 – 3600s | `300` |
| `SCHEDULE_CACHE_TTL_MINUTES` | int | 1 – 1440 min | `5` |
| `AGENT_CACHE_TTL_MINUTES` | int | 5 – 1440 min | `60` |
| `AGENT_CACHE_MAXSIZE` | int | 10 – 5000 | `500` |
| `LOG_LEVEL` | string | `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` | `INFO` |

---

## Docker

El proyecto incluye `Dockerfile`, `compose.yaml` y `.dockerignore` listos para usar.

### Dockerfile (referencia)

```dockerfile
# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Lima

WORKDIR /app

# Usuario no privilegiado (UID 10001, sin home, sin shell)
ARG UID=10001
RUN adduser --disabled-password --gecos "" \
    --home "/nonexistent" --shell "/sbin/nologin" \
    --no-create-home --uid "${UID}" appuser

# Dependencias (capa separada para cache de Docker)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

USER appuser

COPY src ./src
ENV PYTHONPATH=/app/src

EXPOSE 8002

CMD ["python", "-m", "citas.main"]
```

**Caracteristicas de seguridad del Dockerfile:**
- Usuario no privilegiado (`appuser`, UID 10001)
- Sin home directory ni shell de login
- Solo copia `src/` (codigo) y `requirements.txt` (dependencias)
- `.dockerignore` excluye `.env`, `.git`, `docs/`, `venv*`, `logs/`

### Construir la imagen

```bash
docker build -t agent-citas:latest .

# Con tag de version
docker build -t agent-citas:2.0.0 .
```

### Ejecutar con Docker directamente

```bash
# Usando archivo .env
docker run -d \
  --name agent-citas \
  -p 8002:8002 \
  --env-file .env \
  --restart unless-stopped \
  --memory=512m \
  --cpus=1.0 \
  agent-citas:latest

# Ver logs en tiempo real
docker logs -f agent-citas
```

### Ejecutar con Docker Compose

El proyecto incluye `compose.yaml`:

```yaml
services:
  agent_citas:
    build:
      context: .
    ports:
      - "8002:8002"
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"
```

```bash
# Construir y arrancar
docker compose up -d

# Ver logs
docker compose logs -f agent_citas

# Detener
docker compose down
```

### `.dockerignore`

El archivo `.dockerignore` excluye: `__pycache__`, `.venv`/`venv`/`venv_agent_citas`, `.env`, `.git`, `docs/`, `logs/`, `*.md`, `Dockerfile`, `compose.yaml`, `.pytest_cache`, `.coverage`. La imagen final solo contiene `src/` y `requirements.txt`.

---

## Easypanel (Produccion)

El agente se despliega en **Easypanel** como un servicio Docker dentro del proyecto MaravIA. Easypanel gestiona el build, networking interno y variables de entorno.

### Arquitectura en Easypanel

```
┌─────────────────────────────────────────────────┐
│  Easypanel — Proyecto MaravIA                   │
│                                                 │
│  ┌──────────┐     ┌──────────────┐              │
│  │ Gateway  │────>│ agent_citas  │ :8002        │
│  │   (Go)   │     │  (FastAPI)   │              │
│  └──────────┘     └──────┬───────┘              │
│                          │                      │
│                   ┌──────▼───────┐              │
│                   │memori_agentes│ :6379        │
│                   │   (Redis)    │              │
│                   └──────────────┘              │
│                                                 │
│  Red interna Docker: servicios se comunican     │
│  por hostname (agent_citas, memori_agentes)     │
└─────────────────────────────────────────────────┘
```

### Configuracion del servicio en Easypanel

1. **Crear servicio** tipo "App" con source desde GitHub (o Dockerfile).
2. **Build:** Easypanel detecta el `Dockerfile` en la raiz del repo.
3. **Puerto expuesto:** `8002` (interno, el gateway Go llama directamente por hostname).
4. **Variables de entorno:** Configurar en la seccion "Environment" del servicio (ver seccion [Production](#production-easypanel--variables-de-entorno-del-servicio)).
5. **Red interna:** El gateway Go llama a `http://agent_citas:8002/api/chat`. Redis es accesible como `redis://memori_agentes:6379`.

### Variables criticas para Easypanel

```bash
# Estas DEBEN configurarse en el servicio:
OPENAI_API_KEY=sk-...

# Redis — hostname interno de Docker Compose en Easypanel
REDIS_URL=redis://memori_agentes:6379

# LOG_FILE vacio — Easypanel captura stdout automaticamente
LOG_FILE=
```

### Deploy / Redeploy

Easypanel rebuilds la imagen automaticamente al hacer push al branch configurado (o manualmente desde el panel).

**Al hacer redeploy:**
- El container se recrea → las conversaciones en `InMemorySaver` se pierden (mitigado con Redis).
- Los caches en memoria (agente, horario, contexto) se vacian → cold start normal, se rellenan con el primer request de cada empresa.
- Los circuit breakers se resetean → vuelven a estado cerrado (sano).

### Health check en Easypanel

Configurar en la seccion "Health Check" del servicio:

| Campo | Valor |
|-------|-------|
| Path | `/health` |
| Port | `8002` |
| Interval | `30s` |
| Timeout | `10s` |
| Retries | `3` |

Easypanel reinicia el container si `/health` falla 3 veces consecutivas (tambien si devuelve 503 por CBs abiertos, lo cual se auto-resuelve en `CB_RESET_TTL` segundos).

---

## Verificacion del Despliegue

### 1. Health check

```bash
curl http://localhost:8002/health
```

Respuesta esperada (HTTP 200):
```json
{"status": "ok", "agent": "citas", "version": "2.0.0", "issues": []}
```

Respuesta degradada (HTTP 503):
```json
{"status": "degraded", "agent": "citas", "version": "2.0.0", "issues": ["informacion_api_degraded"]}
```

**Issues posibles:**

| Issue | Significado | Auto-recuperacion |
|-------|-------------|-------------------|
| `openai_api_key_missing` | `OPENAI_API_KEY` no configurada | No — requiere configurar la variable |
| `informacion_api_degraded` | `ws_informacion_ia.php` acumulo 3+ fallos de red | Si — `CB_RESET_TTL` (default 5 min) |
| `preguntas_api_degraded` | `ws_preguntas_frecuentes.php` acumulo 3+ fallos | Si — `CB_RESET_TTL` |
| `calendario_api_degraded` | `ws_calendario.php` acumulo 3+ fallos | Si — `CB_RESET_TTL`. Impide crear citas |
| `agendar_reunion_api_degraded` | `ws_agendar_reunion.php` acumulo 3+ fallos | Si — `CB_RESET_TTL`. Impide verificar disponibilidad |

### 2. Test de chat

```bash
curl -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hola, quiero una cita",
    "session_id": 1,
    "context": {
      "config": {
        "id_empresa": 123
      }
    }
  }'
```

Respuesta esperada:
```json
{"reply": "¡Hola! ¿Para qué fecha te gustaría la reunión?", "url": null}
```

**Nota:** El campo `url` es `null` por defecto. Solo tiene valor cuando el agente adjunta una imagen de saludo (`archivo_saludo` en config) o un enlace de Google Meet (tras crear cita exitosamente).

### 3. Verificar metricas

```bash
curl http://localhost:8002/metrics | grep agent_citas
```

Deberia mostrar contadores como:
```
agent_citas_chat_requests_total{empresa_id="123"} 1
agent_citas_info{agent_type="citas",model="gpt-4o-mini",version="2.0.0"} 1
```

```bash
# Metricas HTTP (prefijo citas_)
curl http://localhost:8002/metrics | grep citas_http
```

```
citas_http_requests_total{status="success"} 1
citas_http_duration_seconds_count 1
```

### 4. Verificar logs

```bash
# Docker
docker logs agent-citas --tail 50

# Docker Compose
docker compose logs agent_citas --tail 50

# Easypanel: seccion "Logs" del servicio en el panel web

# Local (stdout por defecto)
# Con LOG_FILE configurado:
tail -f logs/agent_citas.log
```

---

## Monitoreo

### Prometheus

Agrega al `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'agent_citas'
    static_configs:
      - targets: ['agent_citas:8002']  # hostname interno en Easypanel
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Metricas clave a monitorear

| Metrica | Alerta sugerida | Significado |
|---------|----------------|-------------|
| `citas_http_duration_seconds` p95 > 10s | Latencia alta — revisar LLM o APIs |
| `citas_http_requests_total{status="timeout"}` tasa > 5% | Requests excediendo CHAT_TIMEOUT |
| `citas_http_requests_total{status="error"}` tasa creciente | Errores en el endpoint |
| `agent_citas_booking_failed_total{reason="timeout"}` tasa > 5% | APIs MaravIA con problemas |
| `agent_citas_booking_failed_total{reason="circuit_open"}` > 0 | Circuit breaker abierto, booking rechazado |
| `agent_citas_booking_failed_total{reason="connection_error"}` | Conectividad a MaravIA |
| `agent_citas_tool_errors_total` tasa creciente | Fallo en tools internas |
| `citas_agent_cache_total{result="miss"}` tasa alta | Cache de agentes fria o TTL muy corto |
| `citas_search_cache_total{result="circuit_open"}` > 0 | Circuit breaker abierto para busquedas |

### Comandos de diagnostico

```bash
# Latencia del endpoint
curl -w "\nTiempo total: %{time_total}s\n" -s -o /dev/null \
  -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test","session_id":99,"context":{"config":{"id_empresa":1}}}'

# Health check (503 = degradado)
curl -w "\nHTTP status: %{http_code}\n" -s http://localhost:8002/health

# Estado del cache
curl -s http://localhost:8002/metrics | grep cache

# Total de requests por empresa
curl -s http://localhost:8002/metrics | grep chat_requests_total

# Tasa de citas exitosas vs fallidas
curl -s http://localhost:8002/metrics | grep -E "booking_(success|failed)"

# Metricas HTTP (latencia y status)
curl -s http://localhost:8002/metrics | grep citas_http

# Circuit breakers (buscar labels con circuit_open)
curl -s http://localhost:8002/metrics | grep circuit_open
```

---

## Troubleshooting

### `"Context missing required keys in config: ['id_empresa']"`

**Causa:** El request no envia `context.config.id_empresa`.

**Solucion:** Asegurarse de incluirlo en todos los requests:
```json
{"message": "...", "session_id": 1, "context": {"config": {"id_empresa": 123}}}
```

---

### `Connection refused` en el puerto 8002

**Causa:** El servidor no esta corriendo o usa otro puerto.

```bash
# Verificar proceso (Linux/Mac)
ps aux | grep "citas.main"

# Verificar proceso (Windows)
tasklist | findstr python

# Verificar que escucha en el puerto
netstat -an | grep 8002      # Linux/Mac
netstat -ano | findstr 8002  # Windows

# Verificar el puerto configurado
grep SERVER_PORT .env
```

---

### `ModuleNotFoundError: No module named 'citas'`

**Causa:** `PYTHONPATH` no apunta a `src/`.

```bash
# Verificar
echo $PYTHONPATH   # debe contener /ruta/al/proyecto/src

# Corregir (Linux/Mac)
export PYTHONPATH=$(pwd)/src

# En Docker no ocurre: el Dockerfile define ENV PYTHONPATH=/app/src
```

---

### Latencia alta (>5s por respuesta)

**Causas posibles y diagnostico:**

```bash
# 1. Ver si el cache de horarios esta frio (0 entradas = cold start)
curl -s http://localhost:8002/metrics | grep cache_entries

# 2. Buscar timeouts en logs
docker logs agent-citas 2>&1 | grep -i timeout

# 3. Medir latencia del LLM vs total
curl -s http://localhost:8002/metrics | grep -E "llm_call|chat_response"
```

**Soluciones:**
- **Cache frio (cold start):** Normal en el primer request tras deploy. Las siguientes son rapidas.
- **APIs MaravIA lentas:** Aumentar `SCHEDULE_CACHE_TTL_MINUTES` (ej. 10 en produccion) para reducir llamadas.
- **LLM lento:** Verificar `OPENAI_TIMEOUT`; considerar `gpt-4o-mini` si usas `gpt-4o` (mas rapido, mas barato).
- **Red:** Verificar conectividad a `api.maravia.pe` desde el servidor (`curl -w "%{time_total}" https://api.maravia.pe`).

---

### `OPENAI_API_KEY` invalida o expirada

**Sintoma:** El agente responde siempre con error generico, logs muestran `401` o `AuthenticationError`.

```bash
# Verificar que la key esta cargada (local)
PYTHONPATH=src python -c "from citas.config import config; print(bool(config.OPENAI_API_KEY))"

# En Docker
docker exec agent-citas python -c "from citas.config import config; print(bool(config.OPENAI_API_KEY))"

# Health check reporta el problema
curl -s http://localhost:8002/health
# → {"status": "degraded", "issues": ["openai_api_key_missing"]}
```

---

### `/health` retorna 503 (degraded)

**Causa:** Al menos un circuit breaker esta abierto o falta `OPENAI_API_KEY`.

```bash
# Ver que issues reporta
curl -s http://localhost:8002/health | python -m json.tool
```

| Issue | Causa | Solucion |
|-------|-------|----------|
| `openai_api_key_missing` | `OPENAI_API_KEY` no configurada | Configurar en variables de entorno |
| `informacion_api_degraded` | `ws_informacion_ia.php` con 3+ TransportErrors | Verificar conectividad a `api.maravia.pe`. Auto-reset en `CB_RESET_TTL` (5 min) |
| `preguntas_api_degraded` | `ws_preguntas_frecuentes.php` con 3+ fallos | Igual que arriba |
| `calendario_api_degraded` | `ws_calendario.php` con 3+ fallos | Igual que arriba. **Impacto:** no se pueden crear citas |
| `agendar_reunion_api_degraded` | `ws_agendar_reunion.php` con 3+ fallos | Igual que arriba. **Impacto:** no se puede verificar disponibilidad |

Los circuit breakers se auto-resetean despues de `CB_RESET_TTL` segundos (default 300s = 5 min). No requieren intervencion manual si la API se recupera. Un request exitoso antes del TTL tambien resetea el contador.

---

### Memoria del agente no persiste entre reinicios

**Causa esperada:** El agente usa `InMemorySaver` (volatil por diseno).

**Impacto:** Al reiniciar el servidor (deploy, crash, redeploy en Easypanel), todas las conversaciones activas pierden contexto. El proximo mensaje del usuario inicia una conversacion nueva.

**Solucion:** Migrar a `AsyncRedisSaver` con TTL de 24h (ver [Escalado](#migración-a-checkpointer-persistente-redis)).

---

### El agente pide telefono pero el usuario da email (o viceversa)

**Comportamiento esperado:** La validacion de `customer_contact` **solo acepta email** (no telefono). Si el usuario proporciona un numero, el agente lo rechaza y pide el correo. Esto es correcto y por diseno (el email se usa en CREAR_EVENTO para la invitacion de Google Calendar).

---

## Escalado y Limitaciones

### Limitacion actual: memoria en proceso

| Escenario | Soporte |
|-----------|---------|
| 1 instancia, multiples usuarios | Funciona (locks por session_id) |
| Multiples instancias (horizontal) | No soportado (memoria no compartida) |
| Reinicio del servidor | Conversaciones perdidas |

### Migracion a checkpointer persistente (Redis)

Redis (`memori_agentes`) ya existe en Easypanel. La migracion resuelve los 3 problemas de la tabla anterior.

**Paso 1 — Instalar dependencia:**

```bash
pip install langgraph-checkpoint-redis
```

Agregar a `requirements.txt`:
```
langgraph-checkpoint-redis>=0.1.0
```

**Paso 2 — Configurar `REDIS_URL`:**

```bash
# Easypanel (hostname interno de Docker Compose)
REDIS_URL=redis://memori_agentes:6379

# Local
REDIS_URL=redis://localhost:6379
```

`REDIS_URL` ya esta definida en `config/config.py` (vacia por defecto).

**Paso 3 — Modificar `agent/agent.py`:**

```python
# Antes:
from langgraph.checkpoint.memory import InMemorySaver
_checkpointer = InMemorySaver()

# Despues:
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

_checkpointer: AsyncRedisSaver | None = None

async def _get_checkpointer() -> AsyncRedisSaver:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = AsyncRedisSaver.from_conn_string(
            app_config.REDIS_URL,
            ttl={"default_ttl": 86400},  # 24 horas
        )
        await _checkpointer.asetup()  # crea indices la primera vez
    return _checkpointer
```

Luego en `_get_agent()`:
```python
checkpointer = await _get_checkpointer()
agent = create_agent(
    model=model,
    tools=AGENT_TOOLS,
    system_prompt=system_prompt,
    checkpointer=checkpointer,
    response_format=CitaStructuredResponse,
)
```

**Beneficios tras la migracion:**
- Historial persiste si el container se reinicia (deploy, crash)
- TTL 24h: sesiones inactivas se eliminan automaticamente
- Preparado para escalar a multiples instancias del agente

### Workers de Uvicorn

Actualmente el servidor corre con 1 worker (default de `uvicorn.run()`). Para produccion con carga:

```python
# En main.py, cambiar CMD o agregar variable:
uvicorn.run(app, host="0.0.0.0", port=8002, workers=2)
```

**Importante:** Con multiples workers, `InMemorySaver` **no funciona** (cada worker tiene su propia memoria). Se requiere Redis antes de escalar workers.

### Capacidad del cache en una instancia

| Cache | Maxsize | TTL default | Variable de config |
|-------|---------|-------------|--------------------|
| Agentes compilados | 500 empresas | 60 min | `AGENT_CACHE_TTL_MINUTES`, `AGENT_CACHE_MAXSIZE` |
| Horarios de reunion | 500 empresas | 5 min | `SCHEDULE_CACHE_TTL_MINUTES` |
| Contexto de negocio | 500 empresas | 60 min | (hardcoded 3600s) |
| Preguntas frecuentes | 500 chatbots | 60 min | (hardcoded 3600s) |
| Busqueda productos | 2000 busquedas | 15 min | (hardcoded 900s) |
| Session locks | 500 sesiones | limpieza automatica | (cleanup threshold) |
| Agent cache locks | 750 locks | limpieza automatica | (1.5x cache maxsize) |

Con `SCHEDULE_CACHE_TTL_MINUTES=10` en produccion se reducen las llamadas a las APIs a la mitad.

### Estimacion de uso de memoria

| Componente | ~RAM por empresa activa |
|-----------|------------------------|
| Agente compilado (LangGraph) | ~2-5 MB |
| Horario cache | ~1 KB |
| Contexto de negocio cache | ~5 KB |
| InMemorySaver (por sesion) | ~50 KB por turno (crece sin limite) |

Para 50 empresas activas simultaneamente: ~150-300 MB solo en agentes + caches. `InMemorySaver` puede agregar 50-200 MB adicionales dependiendo de la cantidad de sesiones activas y la longitud de las conversaciones.

**Recomendacion:** Container con 512 MB de RAM es suficiente para 50 empresas con Redis. Sin Redis, monitorear el uso de memoria y reiniciar periodicamente si crece.

---

## Seguridad del Container

### Medidas implementadas

| Medida | Detalle |
|--------|---------|
| Usuario no privilegiado | `appuser` (UID 10001), sin home, sin shell |
| Sin secretos en imagen | `.env` excluido via `.dockerignore` |
| Imagen slim | `python:3.12-slim` (sin compiladores ni tools innecesarios) |
| Read-only code | El codigo en `/app/src` es propiedad de root, `appuser` solo puede leer |
| No PYTHONDONTWRITEBYTECODE | Evita escritura de `.pyc` en el filesystem |

### Pendiente de implementar

| Medida | Estado | Referencia |
|--------|--------|------------|
| Auth `X-Internal-Token` en `/api/chat` | Pendiente | [PENDIENTES.md](PENDIENTES.md) C2 |
| HTTPS / TLS | N/A — Easypanel/gateway maneja TLS | — |
| Rate limiting | No implementado | Depende del gateway Go |
| Read-only filesystem | Compatible — el agente no escribe al disco | `--read-only` en Docker |

---

## Comandos de Referencia Rapida

```bash
# ── Local ─────────────────────────────────────────────────
PYTHONPATH=src python -m citas.main              # arrancar
LOG_LEVEL=DEBUG PYTHONPATH=src python -m citas.main  # debug

# ── Docker ────────────────────────────────────────────────
docker build -t agent-citas:latest .             # construir
docker compose up -d                             # arrancar
docker compose logs -f agent_citas               # logs
docker compose down                              # detener
docker compose up -d --build                     # rebuild + arrancar

# ── Verificacion ──────────────────────────────────────────
curl http://localhost:8002/health                 # health check
curl -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test","session_id":1,"context":{"config":{"id_empresa":1}}}'

# ── Metricas ──────────────────────────────────────────────
curl -s http://localhost:8002/metrics | grep agent_citas
curl -s http://localhost:8002/metrics | grep citas_http
curl -s http://localhost:8002/metrics | grep booking

# ── Version ───────────────────────────────────────────────
PYTHONPATH=src python -c "from citas import __version__; print(__version__)"
```

---

## Proximos Pasos

- [API.md](API.md) — referencia completa del endpoint `/api/chat`
- [ARCHITECTURE.md](ARCHITECTURE.md) — arquitectura interna del agente
- [MEMORY_PROFILE.md](MEMORY_PROFILE.md) — analisis detallado de consumo de RAM por componente
- [PENDIENTES.md](PENDIENTES.md) — roadmap tecnico (Redis, auth, trim_messages, tests)
