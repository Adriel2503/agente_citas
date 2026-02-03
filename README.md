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
| `OPENAI_TEMPERATURE` | ❌ No | `0.5` | Temperatura del modelo |
| `OPENAI_TIMEOUT` | ❌ No | `90` | Timeout para llamadas a OpenAI (segundos) |
| `MAX_TOKENS` | ❌ No | `2048` | Máximo de tokens por respuesta |
| `SERVER_HOST` | ❌ No | `0.0.0.0` | Host del servidor |
| `SERVER_PORT` | ❌ No | `8003` | Puerto del servidor |
| `LOG_LEVEL` | ❌ No | `INFO` | Nivel de logging (DEBUG\|INFO\|WARNING\|ERROR) |
| `LOG_FILE` | ❌ No | `""` | Archivo de log (vacío = solo stdout) |
| `API_TIMEOUT` | ❌ No | `10` | Timeout para APIs externas (segundos) |
| `SCHEDULE_CACHE_TTL_MINUTES` | ❌ No | `5` | Duración del cache de horarios (minutos) |
| `TIMEZONE` | ❌ No | `America/Lima` | Zona horaria para fechas |
| `API_CALENDAR_URL` | ❌ No | `https://api.maravia.pe/.../ws_calendario.php` | URL API calendario |
| `API_AGENDAR_REUNION_URL` | ❌ No | `https://api.maravia.pe/.../ws_agendar_reunion.php` | URL API disponibilidad |
| `API_INFORMACION_URL` | ❌ No | `https://api.maravia.pe/.../ws_informacion_ia.php` | URL API información |

## Uso Básico

El agente se comunica mediante el protocolo MCP (Model Context Protocol). Expone una sola herramienta:

**Tool:** `chat`

**Parámetros:**
- `message` (string): Mensaje del usuario
- `session_id` (string): ID único de sesión para memoria (usado como `id_prospecto`)
- `context` (object): Configuración del agente
  - `context.config.id_empresa` (int, **requerido**): ID de la empresa
  - `context.config.personalidad` (string, opcional): Personalidad del agente
  - `context.config.duracion_cita_minutos` (int, opcional): Duración de cita (default: 60)
  - `context.config.slots` (int, opcional): Slots disponibles (default: 60)
  - `context.config.agendar_usuario` (int, opcional): Flag 1/0 (default: 1)
  - `context.config.id_usuario` (int, opcional): ID del vendedor/usuario
  - `context.config.correo_usuario` (string, opcional): Email del vendedor
  - `context.config.agendar_sucursal` (int, opcional): Flag 0/1 (default: 0)
  - Ver todos los parámetros en [API.md](docs/API.md)

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
ORQUESTADOR → MCP (HTTP) → Agent Citas (Puerto 8003)
                                ↓
                         LangChain Agent (GPT-4o-mini)
                                ↓
                    ┌───────────┴───────────┐
                    ↓                       ↓
            check_availability      create_booking
                    ↓                       ↓
          ScheduleValidator         3 capas validación:
                    ↓               1. Pydantic
         ws_informacion_ia.php      2. ScheduleValidator
         (OBTENER_HORARIO)          3. ws_calendario.php
                                       (CREAR_EVENTO)
```

**Flujo de datos:**
1. Orquestador envía `message`, `session_id`, `context` (con `id_empresa`)
2. Agent procesa con LangChain y memoria automática
3. LLM decide qué tool usar según la conversación
4. `create_booking` valida → crea evento en `ws_calendario.php`

Ver [ARCHITECTURE.md](docs/ARCHITECTURE.md) para detalles completos.

## Desarrollo

### Estructura del proyecto

```
agent_citas/
├── src/citas/                    # Código fuente
│   ├── main.py                   # Servidor MCP (punto de entrada)
│   ├── logger.py                 # Sistema de logging centralizado
│   ├── metrics.py                # Métricas Prometheus
│   ├── validation.py             # Validadores Pydantic
│   ├── __init__.py               # Exports y metadata
│   │
│   ├── agent/                    # Lógica del agente
│   │   ├── agent.py              # Agente LangChain con memoria
│   │   └── __init__.py
│   │
│   ├── tool/                     # Herramientas del LLM
│   │   ├── tools.py              # check_availability, create_booking
│   │   └── __init__.py
│   │
│   ├── services/                 # Servicios de negocio
│   │   ├── schedule_validator.py # Validación de horarios con cache
│   │   ├── booking.py            # Creación de eventos (ws_calendario)
│   │   ├── horario_reuniones.py  # Obtención de horarios para prompt
│   │   └── __init__.py
│   │
│   ├── config/                   # Configuración
│   │   ├── config.py             # Variables de entorno
│   │   ├── models.py             # Modelos Pydantic (CitaConfig)
│   │   └── __init__.py
│   │
│   └── prompts/                  # Templates de prompts
│       ├── __init__.py           # Builder de system prompt
│       └── citas_system.j2       # Template Jinja2
│
├── docs/                         # Documentación
├── .env.example                  # Ejemplo de configuración
└── requirements.txt              # Dependencias
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
