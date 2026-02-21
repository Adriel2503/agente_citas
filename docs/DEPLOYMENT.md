# Deployment Guide — Agent Citas v2.0.0

Guía completa para desplegar el agente de citas en local y producción.

---

## Tabla de Contenidos

1. [Requisitos](#requisitos)
2. [Ejecución Local](#ejecución-local)
3. [Variables de Entorno](#variables-de-entorno)
4. [Docker](#docker)
5. [Verificación del Despliegue](#verificación-del-despliegue)
6. [Monitoreo](#monitoreo)
7. [Troubleshooting](#troubleshooting)
8. [Escalado y Limitaciones](#escalado-y-limitaciones)

---

## Requisitos

| Requisito | Versión mínima | Notas |
|-----------|---------------|-------|
| Python | 3.10+ | En Docker se usa 3.12-slim |
| OpenAI API Key | — | Modelo `gpt-4o-mini` por defecto |
| Acceso a APIs MaravIA | — | `ws_calendario`, `ws_agendar_reunion`, `ws_informacion_ia` |
| Docker (opcional) | 24+ | Para despliegue en contenedor |

---

## Ejecución Local

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

# Editar con tus credenciales (mínimo requerido: OPENAI_API_KEY)
```

El servidor buscará el archivo `.env` hacia arriba en el árbol de directorios (hasta 6 niveles), por lo que puede estar en el directorio del proyecto o en un directorio padre.

### 3. Arrancar el servidor

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
Cache TTL: 5 min
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

### Mínimas requeridas

```bash
OPENAI_API_KEY=sk-...
```

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
LOG_FILE=                         # vacío = solo stdout

# ── Timeouts y cache ───────────────────────────────────────
API_TIMEOUT=10
SCHEDULE_CACHE_TTL_MINUTES=5
TIMEZONE=America/Lima

# ── APIs MaravIA ───────────────────────────────────────────
API_CALENDAR_URL=https://api.maravia.pe/servicio/ws_calendario.php
API_AGENDAR_REUNION_URL=https://api.maravia.pe/servicio/ws_agendar_reunion.php
API_INFORMACION_URL=https://api.maravia.pe/servicio/ws_informacion_ia.php
```

#### Production (`.env.production`)

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
LOG_LEVEL=INFO                    # WARNING en producción estable
LOG_FILE=logs/agent_citas.log     # archivo rotado por el host/orquestador

# ── Timeouts y cache ───────────────────────────────────────
API_TIMEOUT=10
SCHEDULE_CACHE_TTL_MINUTES=10     # cache más largo reduce llamadas a API
TIMEZONE=America/Lima

# ── APIs MaravIA ───────────────────────────────────────────
API_CALENDAR_URL=https://api.maravia.pe/servicio/ws_calendario.php
API_AGENDAR_REUNION_URL=https://api.maravia.pe/servicio/ws_agendar_reunion.php
API_INFORMACION_URL=https://api.maravia.pe/servicio/ws_informacion_ia.php
```

### Valores y rangos validados

| Variable | Tipo | Rango | Default |
|----------|------|-------|---------|
| `OPENAI_TEMPERATURE` | float | 0.0 – 2.0 | `0.5` |
| `OPENAI_TIMEOUT` | int | 1 – 300s | `60` |
| `MAX_TOKENS` | int | 1 – 128000 | `2048` |
| `SERVER_PORT` | int | 1 – 65535 | `8002` |
| `API_TIMEOUT` | int | 1 – 120s | `10` |
| `CHAT_TIMEOUT` | int | 30 – 300s | `120` |
| `SCHEDULE_CACHE_TTL_MINUTES` | int | 1 – 1440 min | `5` |
| `LOG_LEVEL` | string | `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` | `INFO` |

Si una variable tiene un valor fuera de rango o tipo inválido, el sistema usa el default sin error.

---

## Docker

El proyecto incluye `Dockerfile` y `compose.yaml` listos para usar.

### Dockerfile (referencia)

```dockerfile
# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Lima

WORKDIR /app

# Usuario no privilegiado
ARG UID=10001
RUN adduser --disabled-password --gecos "" \
    --home "/nonexistent" --shell "/sbin/nologin" \
    --no-create-home --uid "${UID}" appuser

# Dependencias (capa separada para caché)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

USER appuser

COPY src ./src
ENV PYTHONPATH=/app/src

EXPOSE 8002

CMD ["python", "-m", "citas.main"]
```

### Construir la imagen

```bash
docker build -t agent-citas:latest .

# Especificar versión de Python (opcional)
docker build --build-arg PYTHON_VERSION=3.12 -t agent-citas:2.0.0 .
```

### Ejecutar con Docker directamente

```bash
# Usando archivo .env
docker run -d \
  --name agent-citas \
  -p 8002:8002 \
  --env-file .env \
  --restart unless-stopped \
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

El archivo `.dockerignore` excluye: `__pycache__`, `venv*`, `.env`, `.git`, `docs/`, `logs/`, `*.md`. La imagen solo contiene `src/` y `requirements.txt`.

---

## Verificación del Despliegue

### 1. Health check

```bash
curl http://localhost:8002/health
```

Respuesta esperada:
```json
{"status": "ok", "agent": "citas", "version": "2.0.0"}
```

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
{"reply": "¡Hola! ¿Para qué fecha te gustaría la reunión?"}
```

### 3. Verificar métricas

```bash
curl http://localhost:8002/metrics | grep agent_citas
```

Debería mostrar contadores como:
```
agent_citas_chat_requests_total{empresa_id="123"} 1
agent_citas_info{agent_type="citas",model="gpt-4o-mini",version="2.0.0"} 1
```

### 4. Verificar logs

```bash
# Docker
docker logs agent-citas --tail 50

# Docker Compose
docker compose logs agent_citas --tail 50

# Local con LOG_FILE configurado
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
      - targets: ['localhost:8002']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Métricas clave a monitorear

| Métrica | Alerta sugerida | Significado |
|---------|----------------|-------------|
| `agent_citas_chat_response_duration_seconds` p95 > 10s | Latencia alta — revisar LLM o APIs |
| `agent_citas_booking_failed_total{reason="timeout"}` tasa > 5% | APIs MaravIA con problemas |
| `agent_citas_booking_failed_total{reason="api_error"}` | Errores en ws_calendario |
| `agent_citas_tool_errors_total` tasa creciente | Fallo en tools internas |
| `agent_citas_cache_entries{cache_type="schedule"}` = 0 | Cache limpio tras reinicio |

### Comandos de diagnóstico

```bash
# Latencia del endpoint
curl -w "\nTiempo total: %{time_total}s\n" -s -o /dev/null \
  -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test","session_id":99,"context":{"config":{"id_empresa":1}}}'

# Estado del cache de horarios
curl -s http://localhost:8002/metrics | grep cache_entries

# Total de requests por empresa
curl -s http://localhost:8002/metrics | grep chat_requests_total

# Tasa de citas exitosas vs fallidas
curl -s http://localhost:8002/metrics | grep -E "booking_(success|failed)"
```

---

## Troubleshooting

### `"Context missing required keys in config: ['id_empresa']"`

**Causa:** El request no envía `context.config.id_empresa`.

**Solución:** Asegurarse de incluirlo en todos los requests:
```json
{"message": "...", "session_id": 1, "context": {"config": {"id_empresa": 123}}}
```

---

### `Connection refused` en el puerto 8002

**Causa:** El servidor no está corriendo o usa otro puerto.

```bash
# Verificar proceso (Linux/Mac)
ps aux | grep "citas.main"

# Verificar proceso (Windows)
tasklist | findstr python

# Verificar qué escucha en el puerto
netstat -an | grep 8002      # Linux/Mac
netstat -ano | findstr 8002  # Windows

# Verificar el puerto configurado
grep SERVER_PORT .env
```

---

### Latencia alta (>5s por respuesta)

**Causas posibles y diagnóstico:**

```bash
# 1. Ver si el cache de horarios está frío (0 entradas = cold start)
curl -s http://localhost:8002/metrics | grep cache_entries

# 2. Buscar timeouts en logs
grep -i timeout logs/agent_citas.log

# 3. Medir latencia del LLM vs total
curl -s http://localhost:8002/metrics | grep -E "llm_call|chat_response"
```

**Soluciones:**
- Aumentar `SCHEDULE_CACHE_TTL_MINUTES` para reducir llamadas a APIs MaravIA
- Verificar conectividad a `api.maravia.pe` desde el servidor
- Si el LLM es el cuello de botella, revisar `OPENAI_TIMEOUT` y el modelo

---

### `OPENAI_API_KEY` inválida o expirada

**Síntoma:** El agente responde siempre con error genérico, logs muestran `401` o `AuthenticationError`.

```bash
# Verificar que la key está cargada
python -c "from citas.config import config; print(bool(config.OPENAI_API_KEY))"

# Verificar que no tiene espacios ni comillas extras
python -c "from citas.config import config; print(repr(config.OPENAI_API_KEY[:10]))"
```

---

### Memoria del agente no persiste entre reinicios

**Causa esperada:** El agente usa `InMemorySaver` (volátil por diseño).

**Impacto:** Al reiniciar el servidor, todas las conversaciones activas pierden contexto. El próximo mensaje del usuario iniciará una conversación nueva.

**Solución para producción multi-instancia:** Migrar el checkpointer a Redis o PostgreSQL (ver [Escalado](#escalado-y-limitaciones)).

---

### `venv_agent_citas` incluido en imagen Docker

**Causa:** El `.dockerignore` excluye `venv*` pero puede haber un nombre diferente.

Verificar el `.dockerignore`:
```
venv
venv_agent_citas
.venv
```

---

### El agente pide teléfono pero el usuario da email (o viceversa)

**Comportamiento esperado:** La validación de `customer_contact` **solo acepta email** (no teléfono). Si el usuario proporciona un número, el agente lo rechaza y pide el correo. Esto es correcto y por diseño.

---

## Escalado y Limitaciones

### Limitación actual: memoria en proceso

| Escenario | Soporte |
|-----------|---------|
| 1 instancia, múltiples usuarios | ✅ Funciona (locks por session_id) |
| Múltiples instancias (horizontal) | ❌ Memoria no compartida |
| Reinicio del servidor | ❌ Conversaciones perdidas |

### Migración a checkpointer persistente

Para escalar horizontalmente o persistir conversaciones entre reinicios:

**Opción A — Redis (recomendado para producción):**
```python
# En agent/agent.py, reemplazar:
from langgraph.checkpoint.memory import InMemorySaver
_checkpointer = InMemorySaver()

# Por:
from langgraph.checkpoint.redis import AsyncRedisSaver
_checkpointer = AsyncRedisSaver.from_conn_string(os.getenv("REDIS_URL"))
```

```bash
# .env
REDIS_URL=redis://localhost:6379/0
```

**Opción B — PostgreSQL:**
```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
_checkpointer = AsyncPostgresSaver.from_conn_string(os.getenv("DATABASE_URL"))
```

### Capacidad del cache en una instancia

| Cache | Máx. entradas | TTL default |
|-------|--------------|-------------|
| Agentes compilados | 100 empresas | 5 min (`SCHEDULE_CACHE_TTL_MINUTES`) |
| Horarios de reunión | ilimitado (dict) | 5 min |
| Contexto de negocio | 500 empresas | 60 min |
| Locks de sesión | 500 sesiones | limpieza automática |

Con `SCHEDULE_CACHE_TTL_MINUTES=10` en producción se reducen las llamadas a las APIs a la mitad.

---

## Comandos de Referencia Rápida

```bash
# Arrancar local
python -m citas.main

# Arrancar con debug
LOG_LEVEL=DEBUG python -m citas.main

# Docker: construir
docker build -t agent-citas:latest .

# Docker: arrancar
docker compose up -d

# Docker: logs
docker compose logs -f agent_citas

# Docker: detener
docker compose down

# Health check
curl http://localhost:8002/health

# Test de chat mínimo
curl -X POST http://localhost:8002/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test","session_id":1,"context":{"config":{"id_empresa":1}}}'

# Ver métricas
curl http://localhost:8002/metrics | grep agent_citas

# Ver versión
python -c "from citas import __version__; print(__version__)"
```

---

## Próximos Pasos

- [API.md](API.md) — referencia completa del endpoint `/api/chat`
- [ARCHITECTURE.md](ARCHITECTURE.md) — arquitectura interna del agente
