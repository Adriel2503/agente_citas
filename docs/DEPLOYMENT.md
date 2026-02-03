# Deployment Guide - Agent Citas

Guía básica para desplegar el agente de citas.

## Ejecución Local

### Requisitos

- Python 3.10+
- OpenAI API Key
- Acceso a APIs MaravIA

### Pasos

```bash
# 1. Activar entorno virtual
# Windows:
venv_agent_citas\Scripts\activate
# Linux/Mac:
source venv_agent_citas/bin/activate

# 2. Verificar variables de entorno
cat .env  # Linux/Mac
type .env  # Windows

# 3. Ejecutar servidor
python -m citas.main
```

El servidor estará disponible en `http://localhost:8003`

---

## Variables de Entorno por Ambiente

### Development

```bash
# .env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_TEMPERATURE=0.5
OPENAI_TIMEOUT=90
MAX_TOKENS=2048
SERVER_HOST=0.0.0.0
SERVER_PORT=8003
LOG_LEVEL=DEBUG
LOG_FILE=
API_TIMEOUT=10
SCHEDULE_CACHE_TTL_MINUTES=5
TIMEZONE=America/Lima

# APIs MaravIA
API_CALENDAR_URL=https://api.maravia.pe/servicio/n8n/ws_calendario.php
API_AGENDAR_REUNION_URL=https://api.maravia.pe/servicio/n8n/ws_agendar_reunion.php
API_INFORMACION_URL=https://api.maravia.pe/servicio/ws_informacion_ia.php
```

### Production

```bash
# .env.production
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini     # o gpt-4o para mejor calidad
OPENAI_TEMPERATURE=0.5
OPENAI_TIMEOUT=90
MAX_TOKENS=2048
SERVER_HOST=0.0.0.0
SERVER_PORT=8003
LOG_LEVEL=WARNING            # Solo warnings y errores
LOG_FILE=logs/agent.log      # Guardar logs en archivo
API_TIMEOUT=10
SCHEDULE_CACHE_TTL_MINUTES=10  # Cache más largo en producción
TIMEZONE=America/Lima

# APIs MaravIA
API_CALENDAR_URL=https://api.maravia.pe/servicio/n8n/ws_calendario.php
API_AGENDAR_REUNION_URL=https://api.maravia.pe/servicio/n8n/ws_agendar_reunion.php
API_INFORMACION_URL=https://api.maravia.pe/servicio/ws_informacion_ia.php
```

---

## Docker (Básico)

### Dockerfile

El Dockerfile del proyecto usa el módulo `citas`:

```dockerfile
# Código de la aplicación
COPY src ./src
ENV PYTHONPATH=/app/src
EXPOSE 8003
CMD ["python", "-m", "citas.main"]
```

### Construir y ejecutar

```bash
# Construir imagen
docker build -t agent-citas:latest .

# Ejecutar contenedor
docker run -d \
  --name agent-citas \
  -p 8003:8003 \
  -e OPENAI_API_KEY=sk-... \
  -e LOG_LEVEL=INFO \
  agent-citas:latest

# Ver logs
docker logs -f agent-citas
```

---

## Verificación del Despliegue

### 1. Health Check

```bash
# Verificar que el servidor está corriendo
curl http://localhost:8003/metrics
```

Debería retornar métricas en formato Prometheus.

### 2. Test de Conectividad

```bash
# Test básico con curl (MCP)
curl -X POST http://localhost:8003/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "chat",
    "arguments": {
      "message": "Hola",
      "session_id": "test-123",
      "context": {
        "config": {
          "id_empresa": 123
        }
      }
    }
  }'
```

Debería retornar una respuesta del agente.

### 3. Verificar Logs

```bash
# Si LOG_FILE está configurado
tail -f logs/agent.log

# Si solo stdout
docker logs -f agent-citas  # Docker
# o revisar la salida en la terminal donde ejecutaste el servidor
```

---

## Monitoreo

### Métricas Prometheus

Las métricas están expuestas en `/metrics` (IDs compatibles: `agent_reservas_*`):

```bash
curl http://localhost:8003/metrics | grep agent_reservas
```

Métricas importantes a monitorear:

- `agent_reservas_chat_requests_total` - Total de requests
- `agent_reservas_booking_success_total` - Citas exitosas
- `agent_reservas_booking_failed_total` - Citas fallidas
- `agent_reservas_chat_response_duration_seconds` - Latencia

### Integración con Prometheus (Opcional)

Si tienes Prometheus instalado, agrega al `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'agent_citas'
    static_configs:
      - targets: ['localhost:8003']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

---

## Troubleshooting

### Error: "Context missing required keys"

**Problema:** No se está enviando `id_empresa`

**Solución:**
```json
{
  "context": {
    "config": {
      "id_empresa": 123  // ← Asegurarse de enviarlo
    }
  }
}
```

### Error: "Connection refused"

**Problema:** El servidor no está corriendo o el puerto está bloqueado

**Solución:**
```bash
# Verificar que el servidor esté corriendo
ps aux | grep "citas.main"  # Linux/Mac
tasklist | findstr python   # Windows

# Verificar puerto
netstat -an | grep 8003
```

### Alta Latencia

**Problema:** Respuestas lentas

**Solución:**
1. Verificar cache: `curl http://localhost:8003/metrics | grep cache_entries`
2. Revisar timeout de APIs: Ajustar `API_TIMEOUT` en `.env`
3. Revisar logs: Buscar timeouts o errores de conexión

### Memoria Crece Indefinidamente

**Problema:** InMemorySaver acumula sesiones

**Solución:** En producción con múltiples instancias, migrar a Redis:

```python
# Futuro: Reemplazar en agent.py
from langgraph.checkpoint.redis import RedisSaver
_checkpointer = RedisSaver(redis_url=os.getenv("REDIS_URL"))
```

---

## Escalado (Nota Importante)

### ⚠️ Limitación Actual

El agente usa **InMemorySaver** para memoria conversacional. Esto significa:

- ✅ Funciona perfectamente para **1 instancia**
- ❌ NO escala horizontalmente (múltiples instancias)
- ❌ Memoria se pierde al reiniciar

### Solución para Producción

Para desplegar múltiples instancias:

1. Migrar a **Redis** o **PostgreSQL** para checkpointer
2. Configurar `REDIS_URL` en `.env`
3. Actualizar `agent.py` para usar `RedisSaver`

```bash
# .env
REDIS_URL=redis://localhost:6379/0
```

Esto permitirá:
- ✅ Múltiples instancias compartiendo memoria
- ✅ Persistencia entre reinicios
- ✅ Load balancing real

---

## Comandos Útiles

### Ver variables de entorno

```bash
python -c "from citas.config import config; import pprint; pprint.pprint({k:v for k,v in vars(config).items() if k.isupper()})"
```

### Limpiar cache manualmente

```python
from citas.services.schedule_validator import _clear_cache
_clear_cache()
```

### Ver versión

```bash
python -c "from citas import __version__; print(__version__)"
# Output: 2.0.0
```

---

## Próximos Pasos

- Para entender cómo funciona internamente: [ARCHITECTURE.md](ARCHITECTURE.md)
- Para usar la API: [API.md](API.md)
- Para configuración avanzada: Ver [MEJORAS_IMPLEMENTADAS.md](../MEJORAS_IMPLEMENTADAS.md) si existe
