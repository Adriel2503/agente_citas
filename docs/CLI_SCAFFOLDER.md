# CLI Scaffolder — Diseño de `maravia-cli`

Herramienta CLI pip-installable para generar nuevos agentes a partir de `agent_citas` como template base.

```bash
pip install maravia-cli
maravia new agent_automotriz
```

---

## 1. Stack Tecnológico

| Herramienta | Rol | Por qué |
|-------------|-----|---------|
| **Copier** | Genera el proyecto desde template | Soporta Jinja2 en archivos y nombres, actualización post-generación, `copier.yml` declarativo |
| **Typer** | CLI interactivo | Tipado Python nativo, auto-genera `--help`, subcomandos, integración con Rich |
| **Rich** | UI en terminal | Tablas, colores, spinners — viene incluido con `typer[all]` |

**Flujo:** El usuario ejecuta `maravia new` (Typer) → Typer hace preguntas interactivas → pasa respuestas a Copier via `run_copy(data=answers)` → Copier genera el proyecto.

---

## 2. Flujo Interactivo

```
$ maravia new agent_automotriz

  Creando nuevo agente...

  Nombre del proyecto: agent_automotriz
  Puerto del servidor [8002]: 8003
  Modelo OpenAI [gpt-4o-mini]: gpt-4o-mini
  Timezone [America/Lima]: America/Lima

  --- TOOLS ---
  ¿Habilitar check_availability? (consulta horarios) [s/N]: N
  ¿Habilitar create_booking? (crea citas/eventos) [s/N]: N
  ¿Habilitar search_productos_servicios? (busca productos) [s/N]: N

  --- SERVICES (datos inyectados en system prompt) ---
  ¿Habilitar fetch_horario_reuniones? [s/N]: N
  ¿Habilitar fetch_nombres_productos_servicios? [s/N]: N
  ¿Habilitar fetch_contexto_negocio? [s/N]: N
  ¿Habilitar fetch_preguntas_frecuentes? [s/N]: N

  --- INFRAESTRUCTURA ---
  ¿Usar Redis para checkpointing? [s/N]: N

  ✓ Proyecto generado en ./agent_automotriz/

  Próximos pasos:
    cd agent_automotriz
    cp .env.example .env        # configurar OPENAI_MODEL y otras opciones
    uv sync
    uv run python -m agent_automotriz
```

### Modo no-interactivo

```bash
maravia new agent_automotriz --quiet          # usa todos los defaults
maravia new agent_automotriz --no-tools       # sin tools
maravia new agent_automotriz --no-services    # sin services
```

---

## 3. Arquitectura del Paquete CLI

```
maravia-cli/
├── pyproject.toml                    # Paquete pip con entry point
├── src/
│   └── maravia_cli/
│       ├── __init__.py               # __version__
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py               # app = typer.Typer() + subcomandos
│       │   ├── create.py             # maravia new <nombre>
│       │   └── list_cmd.py           # maravia list (templates disponibles)
│       └── templates/
│           └── agent_base/           # Template Copier (agent_citas limpio)
│               ├── copier.yml        # Preguntas y condicionales
│               ├── pyproject.toml.jinja
│               ├── .env.example.jinja
│               └── src/
│                   └── {{ project_slug }}/
│                       ├── main.py
│                       ├── agent/
│                       │   ├── agent.py
│                       │   ├── prompts/
│                       │   │   ├── __init__.py.jinja
│                       │   │   └── system.j2       # Prompt genérico
│                       │   └── runtime/            # Copiado tal cual
│                       ├── tools/
│                       │   └── tools.py.jinja       # AGENT_TOOLS condicional
│                       ├── services/                # Condicional
│                       ├── config/
│                       └── infra/
└── test/
```

### pyproject.toml del CLI

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "maravia-cli"
version = "0.1.0"
description = "CLI para scaffolding de agentes MaravIA"
requires-python = ">=3.12"
dependencies = [
    "typer[all]>=0.14.0",
    "copier>=10.0.0",
]

[project.scripts]
maravia = "maravia_cli.cli.main:app"

[tool.hatch.build.targets.wheel]
packages = ["src/maravia_cli"]
```

---

## 4. Template Copier (copier.yml)

```yaml
_templates_suffix: .jinja

# --- Datos del proyecto ---
project_name:
  type: str
  help: Nombre del proyecto (ej. agent_automotriz)

project_slug:
  type: str
  default: "{{ project_name.lower().replace('-', '_').replace(' ', '_') }}"
  when: false  # calculado automáticamente, no preguntar

server_port:
  type: int
  default: 8002
  help: Puerto del servidor

openai_model:
  type: str
  default: gpt-4o-mini
  help: Modelo OpenAI

timezone:
  type: str
  default: America/Lima

# --- Tools (cada una independiente) ---
enable_check_availability:
  type: bool
  default: false
  help: "¿Habilitar tool check_availability?"

enable_create_booking:
  type: bool
  default: false
  help: "¿Habilitar tool create_booking?"

enable_search_productos:
  type: bool
  default: false
  help: "¿Habilitar tool search_productos_servicios?"

# --- Services (fetches para system prompt) ---
enable_horario:
  type: bool
  default: false
  help: "¿Fetch horario de reuniones?"

enable_productos:
  type: bool
  default: false
  help: "¿Fetch nombres de productos/servicios?"

enable_contexto:
  type: bool
  default: false
  help: "¿Fetch contexto de negocio?"

enable_preguntas:
  type: bool
  default: false
  help: "¿Fetch preguntas frecuentes?"

# --- Infra ---
use_redis:
  type: bool
  default: false
  help: "¿Usar Redis para checkpointing?"
```

---

## 5. Archivos Condicionales (Jinja2)

### tools.py.jinja

```python
"""Tools del agente {{ project_name }}."""

{% if enable_check_availability %}
from .check_availability import check_availability
{% endif %}
{% if enable_create_booking %}
from .create_booking import create_booking
{% endif %}
{% if enable_search_productos %}
from .search_productos import search_productos_servicios
{% endif %}

AGENT_TOOLS = [
{% if enable_check_availability %}
    check_availability,
{% endif %}
{% if enable_create_booking %}
    create_booking,
{% endif %}
{% if enable_search_productos %}
    search_productos_servicios,
{% endif %}
]
```

### prompts/__init__.py.jinja (bloque de services)

```python
{% if enable_horario or enable_productos or enable_contexto or enable_preguntas %}
    _fetches = []
{% if enable_horario %}
    _fetches.append(fetch_horario_reuniones(id_empresa))
{% endif %}
{% if enable_productos %}
    _fetches.append(fetch_nombres_productos_servicios(id_empresa))
{% endif %}
{% if enable_contexto %}
    _fetches.append(fetch_contexto_negocio(id_empresa))
{% endif %}
{% if enable_preguntas %}
    _fetches.append(fetch_preguntas_frecuentes(config.id_chatbot if config else None))
{% endif %}

    results = await asyncio.gather(*_fetches, return_exceptions=True)
    # ... asignar variables según services habilitados ...
{% endif %}

    return _template.render(**variables)
```

### .env.example.jinja

```env
# api_key viene per-request desde el gateway (ChatRequest.api_key)
OPENAI_MODEL={{ openai_model }}
SERVER_PORT={{ server_port }}
TIMEZONE={{ timezone }}
{% if use_redis %}
REDIS_URL=redis://localhost:6379
REDIS_CHECKPOINT_TTL_HOURS=24
{% endif %}
```

---

## 6. Qué se Personaliza vs Qué se Copia Tal Cual

| Archivo | Acción | Motivo |
|---------|--------|--------|
| `tools/tools.py` | **Jinja2** | `AGENT_TOOLS` condicional por tool |
| `prompts/__init__.py` | **Jinja2** | `asyncio.gather` condicional por service |
| `prompts/*.j2` | **Reemplazar** | Prompt completamente custom |
| `pyproject.toml` | **Jinja2** | Nombre, versión, deps condicionales |
| `.env.example` | **Jinja2** | Variables según features habilitadas |
| `main.py` | **Jinja2** | Título y descripción de FastAPI |
| `schemas.py` | **Copiar** | Extensible manualmente post-generación |
| `agent/agent.py` | **Copiar** | Framework — no tocar |
| `agent/content.py` | **Copiar** | Framework — no tocar |
| `agent/context.py` | **Copiar** | Framework — no tocar |
| `agent/runtime/` | **Copiar** | Framework — no tocar |
| `config/` | **Copiar** | Framework — no tocar |
| `infra/` | **Copiar** | Framework — no tocar |
| `logger.py` | **Copiar** | Framework — no tocar |
| `metrics.py` | **Copiar** | Framework — no tocar |

---

## 7. Subcomandos del CLI

| Comando | Descripción |
|---------|-------------|
| `maravia new <nombre>` | Genera un nuevo proyecto interactivamente |
| `maravia new <nombre> --quiet` | Genera con defaults (chatbot puro, sin tools ni services) |
| `maravia new <nombre> --no-tools` | Sin tools, pregunta el resto |
| `maravia new <nombre> --no-services` | Sin services, pregunta el resto |
| `maravia list` | Lista templates disponibles |
| `maravia --version` | Muestra versión del CLI |

---

## 8. Ejemplo: Resultado Generado

```bash
$ maravia new agent_automotriz --no-tools --no-services
```

Genera:

```
agent_automotriz/
├── pyproject.toml              # name="agent_automotriz", deps sin redis
├── .env.example                # OPENAI_MODEL, SERVER_PORT=8002
├── src/
│   └── agent_automotriz/
│       ├── __init__.py
│       ├── main.py             # FastAPI title="Agente agent_automotriz"
│       ├── schemas.py
│       ├── logger.py
│       ├── metrics.py
│       ├── agent/
│       │   ├── agent.py        # create_agent(tools=[], ...)
│       │   ├── content.py
│       │   ├── context.py
│       │   ├── prompts/
│       │   │   ├── __init__.py  # Sin asyncio.gather (services deshabilitados)
│       │   │   └── system.j2    # Prompt genérico editable
│       │   └── runtime/
│       │       ├── _cache.py
│       │       ├── _llm.py
│       │       └── middleware.py
│       ├── tools/
│       │   └── tools.py         # AGENT_TOOLS = []
│       ├── config/
│       │   ├── config.py
│       │   └── circuit_breakers.py
│       └── infra/
│           ├── http_client.py
│           ├── circuit_breaker.py
│           └── _resilience.py
└── test/
    └── test_health.py           # Test básico GET /health
```

El usuario solo necesita:
1. `cp .env.example .env` y ajustar `OPENAI_MODEL` y otras opciones
2. Editar `system.j2` con su prompt personalizado
3. `uv sync && uv run python -m agent_automotriz`

---

## 9. Dependencias del CLI

| Paquete | Versión | Uso |
|---------|---------|-----|
| `typer[all]` | >=0.14.0 | CLI framework + Rich incluido |
| `copier` | >=10.0.0 | Motor de templating, `run_copy()` async |

Solo 2 dependencias. Rich viene incluido en `typer[all]`.

---

## 10. Próximos Pasos

1. Crear repo `maravia-cli` separado de `agent_citas`
2. Extraer template base desde `agent_citas` actual
3. Crear `copier.yml` con las preguntas definidas arriba
4. Implementar CLI con Typer (3 archivos: `main.py`, `create.py`, `list_cmd.py`)
5. Testear generación de proyecto mínimo
6. Publicar en PyPI: `pip install maravia-cli`
