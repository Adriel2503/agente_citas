# Agent Citas - MaravIA

Agente de IA conversacional especializado en gestión de citas y reuniones comerciales.

## Características

- **Procesamiento de lenguaje natural** con GPT-4o-mini/GPT-4o
- **Validación multicapa** de horarios (formato, disponibilidad, bloqueos)
- **Confirmación en tiempo real** con eventos en calendario (ws_calendario)
- **Memoria conversacional automática** (LangChain 1.2+ con InMemorySaver)
- **Observabilidad completa** (Prometheus metrics + logging centralizado)
- **Performance optimizado** (async/await + cache con TTL)

## Versión

**v2.0.0** - LangChain 1.2+ API Moderna

## Requisitos Previos

- Python 3.10 o superior
- OpenAI API Key
- Acceso a APIs MaravIA (ws_calendario, horario reuniones)

## Inicio Rápido

### 1. Clonar e instalar

```bash
# Clonar repositorio
git clone <repository-url>
cd agent_citas

# Crear entorno virtual
python -m venv venv_agent_citas

# Activar entorno virtual
# Windows:
venv_agent_citas\Scripts\activate
# Linux/Mac:
source venv_agent_citas/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
# Copiar archivo de ejemplo
cp .env.example .env

# Editar .env con tus credenciales
# IMPORTANTE: Agregar tu OPENAI_API_KEY
```

### 3. Ejecutar servidor

```bash
python -m citas.main
```

El servidor estará disponible en `http://localhost:8003`

## Variables de Entorno

| Variable | Requerido | Default | Descripción |
|----------|-----------|---------|-------------|
| `OPENAI_API_KEY` | ✅ Sí | - | API Key de OpenAI |
| `OPENAI_MODEL` | ❌ No | `gpt-4o-mini` | Modelo de OpenAI a usar |
| `SERVER_HOST` | ❌ No | `0.0.0.0` | Host del servidor |
| `SERVER_PORT` | ❌ No | `8003` | Puerto del servidor |
| `LOG_LEVEL` | ❌ No | `INFO` | Nivel de logging (DEBUG\|INFO\|WARNING\|ERROR) |
| `LOG_FILE` | ❌ No | `""` | Archivo de log (vacío = solo stdout) |
| `OPENAI_TIMEOUT` | ❌ No | `90` | Timeout para llamadas a OpenAI (segundos) |
| `API_TIMEOUT` | ❌ No | `10` | Timeout para APIs externas (segundos) |
| `MAX_TOKENS` | ❌ No | `2048` | Máximo de tokens por respuesta |
| `SCHEDULE_CACHE_TTL_MINUTES` | ❌ No | `5` | Duración del cache de horarios (minutos) |

## Uso Básico

El agente se comunica mediante el protocolo MCP (Model Context Protocol). Expone una sola herramienta:

**Tool:** `chat`

**Parámetros:**
- `message` (string): Mensaje del usuario
- `session_id` (string): ID único de sesión para memoria
- `context` (object): Configuración del agente
  - `context.config.id_empresa` (int, **requerido**): ID de la empresa
  - `context.config.personalidad` (string, opcional): Personalidad del agente
  - Otros parámetros opcionales (ver [API.md](docs/API.md))

**Ejemplo de request:**
```json
{
  "tool": "chat",
  "arguments": {
    "message": "Quiero agendar una cita para mañana a las 2pm",
    "session_id": "user-12345",
    "context": {
      "config": {
        "id_empresa": 123,
        "personalidad": "amable y profesional"
      }
    }
  }
}
```

## Métricas

Métricas Prometheus disponibles en:
```
http://localhost:8003/metrics
```

Incluye:
- Latencia de respuestas
- Tasa de éxito/fallo de citas
- Uso de cache
- Llamadas a APIs externas

## Documentación

- **[API Reference](docs/API.md)** - Referencia completa de la API
- **[Architecture](docs/ARCHITECTURE.md)** - Arquitectura y diseño del sistema
- **[Deployment](docs/DEPLOYMENT.md)** - Guía de despliegue

## Stack Tecnológico

- **LangChain 1.2+** - Framework de LLM con API moderna
- **LangGraph** - Gestión de memoria y grafos
- **OpenAI API** - Modelos GPT
- **FastMCP** - Servidor MCP sobre FastAPI
- **httpx** - Cliente HTTP async
- **Pydantic** - Validación de datos
- **Prometheus** - Métricas y observabilidad

## Arquitectura

```
ORQUESTADOR → MCP (HTTP) → Agent Citas
                                ↓
                         LangChain Agent
                                ↓
                    ┌───────────┴───────────┐
                    ↓                       ↓
            check_availability      create_booking
                    ↓                       ↓
            (Valida horarios)      (Crea evento/cita)
                    ↓                       ↓
                [APIs MaravIA]        [APIs MaravIA]
```

Ver [ARCHITECTURE.md](docs/ARCHITECTURE.md) para detalles completos.

## Desarrollo

### Estructura del proyecto

```
agent_citas/
├── src/citas/              # Código fuente
│   ├── main.py            # Servidor MCP
│   ├── agent.py           # Lógica del agente LangChain
│   ├── tools.py           # Herramientas internas
│   ├── schedule_validator.py  # Validación de horarios
│   ├── booking.py         # Creación de eventos/citas
│   ├── validation.py      # Validadores Pydantic
│   ├── logger.py          # Sistema de logging
│   ├── metrics.py         # Métricas Prometheus
│   └── prompts/           # Templates de prompts
├── docs/                  # Documentación
├── .env.example           # Ejemplo de configuración
└── requirements.txt       # Dependencias
```

### Ejecutar en modo DEBUG

```bash
LOG_LEVEL=DEBUG python -m citas.main
```

## Mejoras Recientes (v2.0.0)

- ✅ Migración a LangChain 1.2+ API moderna
- ✅ Logging centralizado con formato consistente
- ✅ Performance async real con httpx (30x más rápido)
- ✅ Cache global con TTL thread-safe
- ✅ Validación de datos robusta con Pydantic
- ✅ Sistema completo de métricas Prometheus
- ✅ Nomenclatura consistente (citas/reuniones/eventos)

## Limitaciones Conocidas

- **Memoria volátil**: Usa InMemorySaver (se pierde al reiniciar). Para producción con múltiples instancias, migrar a Redis o PostgreSQL.
- **Sin rate limiting**: Implementar antes de producción pública.
- **Sin tests automatizados**: En desarrollo.

## Licencia

Propiedad de MaravIA Team.

## Soporte

Para problemas o preguntas, contactar al equipo de desarrollo de MaravIA.
