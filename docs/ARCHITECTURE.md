# Arquitectura - Agent Citas

Documentación técnica completa del agente especializado en citas.

## Tabla de Contenidos

1. [Introducción](#introducción)
2. [Diagrama de Arquitectura](#diagrama-de-arquitectura)
3. [Descripción Detallada de Archivos](#descripción-detallada-de-archivos)
4. [Flujo de Datos Completo](#flujo-de-datos-completo)
5. [Comunicación entre Módulos](#comunicación-entre-módulos)
6. [Patrones de Diseño](#patrones-de-diseño)
7. [Dependencias entre Archivos](#dependencias-entre-archivos)

---

## Introducción

El **Agent Citas** es un microservicio de IA conversacional que automatiza la gestión de citas y reuniones comerciales. Construido con LangChain 1.2+ (API moderna), utiliza GPT-4o-mini/GPT-4o para procesamiento de lenguaje natural y se comunica mediante el protocolo MCP (Model Context Protocol).

### Información del Proyecto

- **Versión**: 2.0.0
- **Líneas de código**: ~2,534
- **Lenguaje**: Python 3.10+
- **Arquitectura**: Microservicio asíncrono con MCP
- **LLM**: GPT-4o-mini (configurable a GPT-4o)

### Stack Tecnológico

**Core:**
- LangChain 1.2+ - Framework de LLM con API moderna
- LangGraph 0.2+ - Gestión de memoria y grafos
- OpenAI API 1.12+ - Modelos GPT

**Web:**
- FastMCP 0.2+ - Servidor MCP sobre FastAPI
- FastAPI 0.110+ - Framework web ASGI
- Uvicorn - Servidor ASGI

**Cliente HTTP:**
- httpx 0.27+ - Cliente async (reemplazo de requests)

**Validación:**
- Pydantic 2.6+ - Modelos y validación de datos

**Templates:**
- Jinja2 3.1.3+ - Motor de templates para prompts

**Observabilidad:**
- prometheus-client 0.19+ - Métricas
- logging (stdlib) - Sistema de logs

**Utilidades:**
- python-dotenv - Variables de entorno
- dateparser - Parsing de fechas naturales

---

## Diagrama de Arquitectura

```
┌─────────────────────────────────────────────────────┐
│               ORQUESTADOR EXTERNO                   │
│           (Sistema Principal MaravIA)               │
└────────────────────┬────────────────────────────────┘
                     │
                     │ HTTP POST (MCP Protocol)
                     │ Tool: "chat"
                     │ {message, session_id, context}
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│                   AGENT RESERVAS (Puerto 8003)                  │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  main.py (Servidor MCP - 148 líneas)                   │    │
│  │  ┌──────────────┐         ┌──────────────┐            │    │
│  │  │  FastMCP     │◄───────►│  @mcp.tool() │            │    │
│  │  │  Server      │         │  chat()      │            │    │
│  │  └──────────────┘         └──────┬───────┘            │    │
│  └─────────────────────────────────┼────────────────────┘    │
│                                    │                          │
│                                    │ Invoca                   │
│                                    ↓                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  agent.py (Lógica LangChain - 241 líneas)             │  │
│  │                                                        │  │
│  │  process_cita_message(message, session_id, context) │  │
│  │         │                                              │  │
│  │         ├─→ _validate_context()                        │  │
│  │         ├─→ _get_agent(config)                         │  │
│  │         │      ├─→ init_chat_model(gpt-4o-mini)       │  │
│  │         │      ├─→ build_citas_system_prompt()      │  │
│  │         │      └─→ create_agent(model, tools, prompt) │  │
│  │         ├─→ _prepare_agent_context()                   │  │
│  │         └─→ agent.invoke(message, config, context)    │  │
│  │                                                        │  │
│  │  Checkpointer: InMemorySaver (memoria global)         │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                  │
│                           │ LLM decide tool                  │
│                           ↓                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  tools.py (Herramientas Internas - 215 líneas)     │    │
│  │                                                     │    │
│  │  AGENT_TOOLS = [check_availability, create_booking]│    │
│  └──────────────┬────────────────────┬─────────────────┘    │
│                 │                    │                      │
│                 ↓                    ↓                      │
│  ┌──────────────────────┐  ┌────────────────────────┐      │
│  │ check_availability   │  │  create_booking        │      │
│  │ (service, date)      │  │  (service, date, time, │      │
│  │                      │  │   customer_name,       │      │
│  │ Extrae runtime ctx   │  │   customer_contact)    │      │
│  │ ↓                    │  │  ↓                     │      │
│  │ ScheduleValidator    │  │  1. validate_booking   │      │
│  │ ↓                    │  │     _data() (Pydantic) │      │
│  │ recommendation()     │  │  ↓                     │      │
│  │                      │  │  2. ScheduleValidator  │      │
│  │                      │  │     .validate()        │      │
│  │                      │  │  ↓                     │      │
│  │                      │  │  3. confirm_booking()  │      │
│  └──────┬───────────────┘  └──────────┬─────────────┘      │
│         │                             │                    │
│         ↓                             ↓                    │
│  ┌────────────────────┐     ┌───────────────────────┐     │
│  │schedule_validator  │     │ validation.py         │     │
│  │    .py             │     │ (Pydantic Models)     │     │
│  │ (455 líneas)       │     │ (258 líneas)          │     │
│  │                    │     │                       │     │
│  │ - _fetch_schedule()│     │ - ContactInfo         │     │
│  │   + CACHE (5 min)  │     │ - CustomerName        │     │
│  │ - validate()       │     │ - BookingDateTime     │     │
│  │ - _check_          │     │ - BookingData         │     │
│  │   availability()   │     └───────────────────────┘     │
│  └────────┬───────────┘                                    │
│           │                      ┌───────────────────┐     │
│           │                      │ booking.py        │     │
│           │                      │ (158 líneas)      │     │
│           │                      │                   │     │
│           │                      │ confirm_booking() │     │
│           │                      └────────┬──────────┘     │
│           │                               │                │
│           │ POST                          │ POST           │
│           ↓                               ↓                │
│  ┌────────────────────────────────────────────────────┐   │
│  │           APIs EXTERNAS (MaravIA)                  │   │
│  │  https://api.maravia.pe/servicio/                  │   │
│  │                                                    │   │
│  │  1. ws_informacion_ia.php                          │   │
│  │     OBTENER_HORARIO_REUNIONES                      │   │
│  │                                                    │   │
│  │  2. n8n/ws_agendar_reunion.php                     │   │
│  │     CONSULTAR_DISPONIBILIDAD                       │   │
│  │     AGENDAR_REUNION                                │   │
│  └────────────────────────────────────────────────────┘   │
│                                                           │
│  ┌─────────────────────────────────────────────────┐     │
│  │  MÓDULOS DE SOPORTE                             │     │
│  │                                                 │     │
│  │  - config.py (39 líneas)                        │     │
│  │    Variables de entorno                         │     │
│  │                                                 │     │
│  │  - logger.py (79 líneas)                        │     │
│  │    Sistema de logging centralizado              │     │
│  │                                                 │     │
│  │  - metrics.py (219 líneas)                      │     │
│  │    Métricas Prometheus (13 métricas)            │     │
│  │    Expuesto en /metrics                         │     │
│  │                                                 │     │
│  │  - models.py (38 líneas)                        │     │
│  │    ChatRequest, ChatResponse, CitaConfig     │     │
│  │                                                 │     │
│  │  - prompts/ (56 + 166 líneas)                   │     │
│  │    __init__.py - Builder de prompts             │     │
│  │    citas_system.j2 - Template Jinja2          │     │
│  └─────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

---

## Descripción Detallada de Archivos

### 1. src/citas/main.py (148 líneas)

**Propósito:** Punto de entrada del sistema. Servidor MCP que expone la tool `chat` al orquestador.

**Tecnología:** FastMCP 0.2+, FastAPI (internamente), Uvicorn

**Responsabilidades:**
- Inicializar servidor MCP
- Exponer tool `chat` al orquestador
- Configurar logging
- Inicializar métricas
- Exponer endpoint `/metrics` para Prometheus

**Funciones principales:**

#### `chat(message: str, session_id: str, context: Dict | None) -> str`
- **Líneas**: 44-110
- **Decorador**: `@mcp.tool()`
- **Descripción**: Única herramienta expuesta al orquestador
- **Parámetros**:
  - `message` (str): Mensaje del usuario
  - `session_id` (str): ID único de sesión
  - `context` (Dict | None): Contexto con configuración
- **Retorna**: str (respuesta del agente)
- **Llama a**: `agent.process_cita_message()`
- **Validaciones**: Ninguna (delega a agent.py)
- **Manejo de errores**:
  - ValueError → retorna mensaje de error de configuración
  - Exception → retorna mensaje de error genérico

**Configuración usada:**
```python
app_config.SERVER_HOST      # Default: "0.0.0.0"
app_config.SERVER_PORT      # Default: 8003
app_config.LOG_LEVEL        # Default: "INFO"
app_config.LOG_FILE         # Default: ""
```

**Ejecución:**
```python
if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=SERVER_HOST,
        port=SERVER_PORT
    )
```

**Es llamado por:** Orquestador (sistema externo via HTTP)

**Llama a:**
- `setup_logging()` - Configuración inicial
- `initialize_agent_info()` - Métricas
- `agent.process_cita_message()` - Procesamiento

---

### 2. src/citas/agent.py (241 líneas)

**Propósito:** Lógica central del agente de IA usando LangChain 1.2+ API moderna.

**Tecnología:** LangChain 1.2+, LangGraph (InMemorySaver), OpenAI

**Responsabilidades:**
- Validar contexto de entrada
- Crear agente LangChain con tools
- Gestionar memoria automática (checkpointer)
- Invocar LLM con runtime context
- Retornar respuesta procesada

**Componentes globales:**

#### `_checkpointer = InMemorySaver()`
- **Línea**: 31
- **Tipo**: Checkpointer global
- **Propósito**: Memoria automática thread-safe
- **Scope**: Global (compartido entre invocaciones)
- **Limitación**: Volátil (se pierde al reiniciar)

#### `AgentContext` (dataclass)
- **Líneas**: 33-44
- **Campos**:
  - `id_empresa: int` - **Requerido**
  - `duracion_cita_minutos: int = 60`
  - `slots: int = 60`
  - `id_usuario: int = 1`
  - `session_id: str = ""`
- **Propósito**: Esquema de runtime context para tools
- **Uso**: Inyectado automáticamente por LangChain

**Funciones principales:**

#### `_validate_context(context: Dict) -> None`
- **Líneas**: 46-63
- **Propósito**: Validar parámetros requeridos
- **Valida**: Presencia de `context.config.id_empresa`
- **Raises**: ValueError si falta algún parámetro
- **Logging**: DEBUG level

#### `_get_agent(config: Dict) -> Agent`
- **Líneas**: 66-107
- **Propósito**: Factory del agente LangChain
- **Pasos**:
  1. Inicializar modelo: `init_chat_model("openai:gpt-4o-mini", temp=0.4, max_tokens=2048, timeout=90s)`
  2. Construir system prompt: `build_citas_system_prompt(config, history=None)`
  3. Crear agente: `create_agent(model, tools=AGENT_TOOLS, system_prompt, checkpointer=_checkpointer)`
- **Retorna**: Agente configurado
- **Nota**: Se recrea en cada llamada para tener config actualizada

**Configuración del modelo:**
```python
model = init_chat_model(
    f"openai:{app_config.OPENAI_MODEL}",  # gpt-4o-mini
    api_key=app_config.OPENAI_API_KEY,
    temperature=0.4,
    max_tokens=app_config.MAX_TOKENS,      # 2048
    timeout=app_config.OPENAI_TIMEOUT,     # 90s
)
```

#### `_prepare_agent_context(context: Dict, session_id: str) -> AgentContext`
- **Líneas**: 110-148
- **Propósito**: Preparar runtime context para tools
- **Extrae de context.config**:
  - `id_empresa` (requerido)
  - `duracion_cita_minutos` (opcional, default 60)
  - `slots` (opcional, default 60)
  - `agendar_usuario` (opcional, bool→int, default 1)
- **Retorna**: AgentContext configurado

#### `process_cita_message(message: str, session_id: str, context: Dict) -> str`
- **Líneas**: 151-240
- **Propósito**: Función principal que procesa mensajes
- **Flujo**:
  1. Validar entrada (message no vacío, session_id requerido)
  2. Registrar métrica: `chat_requests_total.inc()`
  3. Validar contexto: `_validate_context(context)`
  4. Crear agente: `_get_agent(config)`
  5. Preparar runtime context: `_prepare_agent_context()`
  6. Invocar agente con tracking de métricas
  7. Extraer último mensaje de la respuesta
  8. Retornar respuesta

**Invocación del agente:**
```python
config = {
    "configurable": {
        "thread_id": session_id  # Para memoria por sesión
    }
}

with track_chat_response():
    with track_llm_call():
        result = agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
            context=agent_context  # Runtime context para tools
        )
```

**Es llamado por:** `main.chat()`

**Llama a:**
- `config.*` - Variables de configuración
- `models.CitaConfig` - Validación de config
- `tools.AGENT_TOOLS` - Lista de herramientas
- `prompts.build_citas_system_prompt()` - Construcción de prompt
- `metrics.*` - Tracking de métricas
- LangChain: `init_chat_model()`, `create_agent()`

---

### 3. src/citas/tools.py (215 líneas)

**Propósito:** Herramientas internas que el LLM usa para consultar disponibilidad y crear citas/eventos.

**Tecnología:** LangChain @tool decorator

**Responsabilidades:**
- Definir herramientas con decorador `@tool`
- Extraer runtime context automático
- Validar datos antes de confirmar
- Llamar a módulos de validación y confirmación

**Tools disponibles:**

#### `check_availability(service: str, date: str, runtime: ToolRuntime) -> str`
- **Líneas**: 28-86
- **Decorador**: `@tool`
- **Propósito**: Consulta horarios disponibles
- **Parámetros**:
  - `service` (str): Nombre del servicio (ej: "corte", "manicure")
  - `date` (str): Fecha en formato YYYY-MM-DD
  - `runtime` (ToolRuntime): Context automático de LangChain
- **Extrae del runtime.context**:
  - `id_empresa`
  - `duracion_cita_minutos`
  - `slots`
  - `id_usuario`
- **Proceso**:
  1. Extraer configuración del runtime context
  2. Crear `ScheduleValidator(id_empresa, duracion_cita_minutos, slots, es_cita=True, agendar_usuario, agendar_sucursal=0)`
  3. Obtener recomendaciones: `await validator.recommendation()`
  4. Retornar texto formateado
- **Retorna**:
  - Si hay recomendaciones: Texto con horarios disponibles
  - Si no hay: Mensaje genérico de horarios típicos
- **Fallback**: Si hay error, retorna horarios típicos (09:00, 10:00, 14:00, etc.)
- **Logging**: INFO y WARNING levels
- **Métricas**: `track_tool_execution("check_availability")`

**Ejemplo de retorno:**
```
Horarios disponibles:
• Lunes: 09:00 AM - 06:00 PM
• Martes: 09:00 AM - 06:00 PM
...
```

#### `create_booking(service, date, time, customer_name, customer_contact, runtime) -> str`
- **Líneas**: 89-205
- **Decorador**: `@tool`
- **Propósito**: Crea cita/evento con validación completa
- **Parámetros**:
  - `service` (str): Servicio/motivo de la cita
  - `date` (str): Fecha YYYY-MM-DD
  - `time` (str): Hora HH:MM AM/PM
  - `customer_name` (str): Nombre del cliente
  - `customer_contact` (str): Teléfono (9XXXXXXXX) o email
  - `runtime` (ToolRuntime): Context automático
- **Extrae del runtime.context**:
  - `id_empresa`
  - `duracion_cita_minutos`
  - `slots`
  - `id_usuario`
  - `session_id`
- **Proceso (3 capas de validación)**:

**1. CAPA 1 - Validación Pydantic:**
```python
is_valid, error = validate_booking_data(
    service, date, time, customer_name, customer_contact
)
if not is_valid:
    return f"Datos inválidos: {error}..."
```

**2. CAPA 2 - Validación de Horario:**
```python
validator = ScheduleValidator(...)
validation = await validator.validate(date, time)
if not validation["valid"]:
    return f"{validation['error']}..."
```

**3. CAPA 3 - Confirmación en API:**
```python
booking_result = await confirm_booking(
    id_empresa, id_prospecto=session_id, nombre_completo,
    correo_o_telefono=customer_contact, fecha, hora, servicio, id_usuario
)
if booking_result["success"]:
    return f"Cita confirmada... {booking_result.get('message', '')}"
```

- **Retorna**:
  - Si éxito: Mensaje formateado con detalles de la cita
  - Si fallo: Mensaje de error descriptivo
- **Logging**: DEBUG, INFO, WARNING levels
- **Métricas**: `track_tool_execution("create_booking")`

**Ejemplo de retorno exitoso:**
```
Cita confirmada exitosamente

**Detalles:**
• Servicio: Corte de cabello
• Fecha: 2026-01-29
• Hora: 02:00 PM
• Nombre: Juan Pérez
• **Código: RES-12345**

Guarda este código para futuras consultas. ¡Te esperamos!
```

#### `AGENT_TOOLS`
- **Líneas**: 209-212
- **Tipo**: List[Tool]
- **Contenido**: `[check_availability, create_booking]`
- **Propósito**: Lista exportada al agente

**Es llamado por:** LangChain Agent (automáticamente según decisión del LLM)

**Llama a:**
- `schedule_validator.ScheduleValidator`
- `booking.confirm_booking()`
- `validation.validate_booking_data()`
- `logger.*`
- `metrics.*`

---

### 4. src/citas/schedule_validator.py (455 líneas)

**Propósito:** Validación de horarios con cache global y consulta a API externa.

**Tecnología:** httpx async, threading.Lock (cache thread-safe)

**Responsabilidades:**
- Obtener horarios desde API externa (con cache TTL)
- Validar fecha/hora contra reglas de negocio
- Verificar disponibilidad contra citas existentes
- Generar recomendaciones de horarios

**Constantes:**

```python
AGENDAR_REUNIONES_ENDPOINT = "https://api.maravia.pe/servicio/n8n/ws_agendar_reunion.php"
INFORMATION_ENDPOINT = "https://api.maravia.pe/servicio/ws_informacion_ia.php"

DAY_MAPPING = {
    0: "reunion_lunes",
    1: "reunion_martes",
    2: "reunion_miercoles",
    3: "reunion_jueves",
    4: "reunion_viernes",
    5: "reunion_sabado",
    6: "reunion_domingo"
}
```

**Cache Global (thread-safe):**

#### `_SCHEDULE_CACHE: Dict[int, Tuple[Dict, datetime]]`
- **Línea**: 39
- **Tipo**: Diccionario global {id_empresa: (schedule, timestamp)}
- **TTL**: Configurable (default 5 minutos)
- **Thread-safe**: Sí (con `_CACHE_LOCK`)

#### `_CACHE_LOCK = threading.Lock()`
- **Línea**: 40
- **Propósito**: Proteger acceso concurrente al cache

#### `_get_cached_schedule(id_empresa: int) -> Optional[Dict]`
- **Líneas**: 43-65
- **Propósito**: Obtener schedule del cache si no expiró
- **TTL check**: `datetime.now() - timestamp < TTL`
- **Retorna**: Schedule o None

#### `_set_cached_schedule(id_empresa: int, schedule: Dict) -> None`
- **Líneas**: 68-79
- **Propósito**: Guardar schedule en cache con timestamp actual
- **Side effect**: Actualiza métrica `update_cache_stats()`

#### `_clear_cache() -> None`
- **Líneas**: 82-87
- **Propósito**: Limpiar todo el cache (útil para testing)

**Clase Principal:**

#### `ScheduleValidator`
- **Líneas**: 92-451

**Constructor:**
```python
def __init__(
    self,
    id_empresa: int,
    duracion_cita_minutos: int = 60,
    slots: int = 60,
    es_cita: bool = True,
    agendar_usuario: int = 0,
    agendar_sucursal: int = 0,
    sucursal: Optional[str] = None
)
```

**Métodos principales:**

#### `_fetch_schedule() -> Optional[Dict]`
- **Líneas**: 114-160
- **Propósito**: Obtener horario desde API (con cache)
- **Flujo**:
  1. Intentar obtener del cache: `_get_cached_schedule(id_empresa)`
  2. Si cache hit: retornar cached
  3. Si cache miss: POST a API
- **API Call**:
  ```python
  POST https://api.maravia.pe/servicio/ws_informacion_ia.php
  Payload: {
      "codOpe": "OBTENER_HORARIO_REUNIONES",
      "id_empresa": 123
  }
  Response: {
      "success": true,
      "horario_reuniones": {
          "reunion_lunes": "09:00-18:00",
          "reunion_martes": "09:00-18:00",
          ...
          "horarios_bloqueados": "..."
      }
  }
  ```
- **Timeout**: `app_config.API_TIMEOUT` (10s)
- **Cache**: Guarda resultado con `_set_cached_schedule()`
- **Manejo de errores**: Retorna None en caso de error (graceful degradation)

#### `validate(fecha_str: str, hora_str: str) -> Dict[str, Any]`
- **Líneas**: 331-421
- **Propósito**: Validación completa de fecha/hora
- **Retorna**: `{"valid": bool, "error": str | None}`

**Validaciones (12 en total):**

1. **Formato de fecha**
   ```python
   try:
       fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
   except ValueError:
       return {"valid": False, "error": "Formato de fecha inválido..."}
   ```

2. **Formato de hora**
   ```python
   hora = self._parse_time(hora_str)  # HH:MM AM/PM
   if not hora:
       return {"valid": False, "error": "Formato de hora inválido..."}
   ```

3. **Fecha no en el pasado**
   ```python
   if fecha_hora_cita <= datetime.now():
       return {"valid": False, "error": "La fecha ya pasó..."}
   ```

4. **Obtener horario** (con cache)
   ```python
   schedule = await self._fetch_schedule()
   if not schedule:
       return {"valid": True, "error": None}  # Graceful degradation
   ```

5. **Día tiene atención**
   ```python
   dia_semana = fecha.weekday()  # 0=Lunes
   campo_dia = DAY_MAPPING.get(dia_semana)  # "reunion_lunes"
   horario_dia = schedule.get(campo_dia)
   if not horario_dia:
       return {"valid": False, "error": "No hay horario para el día..."}
   ```

6. **Día no cerrado**
   ```python
   if horario_dia.upper() in ["NO DISPONIBLE", "CERRADO", ...]:
       return {"valid": False, "error": "No hay atención el día..."}
   ```

7. **Parsear rango de horario**
   ```python
   rango = self._parse_time_range(horario_dia)  # "09:00-18:00"
   if not rango:
       return {"valid": True, "error": None}  # Graceful
   hora_inicio, hora_fin = rango
   ```

8. **Hora dentro del rango (inicio)**
   ```python
   if hora.time() < hora_inicio.time():
       return {"valid": False, "error": "Hora antes del horario..."}
   ```

9. **Hora dentro del rango (fin)**
   ```python
   if hora.time() >= hora_fin.time():
       return {"valid": False, "error": "Hora después del horario..."}
   ```

10. **Cita + duración no excede cierre**
    ```python
    hora_fin_cita = fecha_hora_cita + self.duracion_cita
    if hora_fin_cita > hora_cierre:
        return {"valid": False, "error": "Cita excede horario..."}
    ```

11. **Horarios bloqueados**
    ```python
    if self._is_time_blocked(fecha, hora, schedule.get("horarios_bloqueados")):
        return {"valid": False, "error": "Horario bloqueado..."}
    ```

12. **Disponibilidad (citas existentes)**
    ```python
    availability = await self._check_availability(fecha_str, hora_str)
    if not availability["available"]:
        return {"valid": False, "error": "Horario ocupado..."}
    ```

**Si todas pasan:**
```python
return {"valid": True, "error": None}
```

#### `_check_availability(fecha_str: str, hora_str: str) -> Dict[str, Any]`
- **Líneas**: 260-329
- **Propósito**: Verificar disponibilidad contra citas existentes
- **API Call**:
  ```python
  POST https://api.maravia.pe/servicio/n8n/ws_agendar_reunion.php
  Payload: {
      "codOpe": "CONSULTAR_DISPONIBILIDAD",
      "id_empresa": 123,
      "fecha_inicio": "2026-01-29 14:00:00",
      "fecha_fin": "2026-01-29 15:00:00",
      "slots": 60,
      "agendar_usuario": 1,
      "agendar_sucursal": 0
  }
  Response: {
      "success": true,
      "disponible": true
  }
  ```
- **Retorna**: `{"available": bool, "error": str | None}`
- **Graceful degradation**: Si falla API, retorna available=true

#### `recommendation() -> Dict[str, Any]`
- **Líneas**: 423-451
- **Propósito**: Generar recomendaciones de horarios
- **Proceso**:
  1. Obtener schedule (con cache)
  2. Construir texto con horarios por día
  3. Filtrar días cerrados
- **Retorna**: `{"text": "Horarios disponibles:\n• Lunes: 09:00-18:00\n..."}`

**Métodos auxiliares:**

- `_parse_time(time_str: str)` - Parsea hora en múltiples formatos
- `_parse_time_range(range_str: str)` - Parsea rango "09:00-18:00"
- `_is_time_blocked(fecha, hora, horarios_bloqueados)` - Verifica bloqueos

**Es llamado por:**
- `tools.check_availability()`
- `tools.create_booking()`

**Llama a:**
- APIs externas (httpx async)
- `logger.*`
- `metrics.track_api_call()`
- `config.API_TIMEOUT`, `config.SCHEDULE_CACHE_TTL_MINUTES`

---

### 5. src/citas/booking.py (158 líneas)

**Propósito:** Crear eventos/citas en la API real de MaravIA (ws_calendario).

**Tecnología:** httpx async

**Responsabilidades:**
- Enviar datos de evento/cita a API externa
- Obtener código de confirmación
- Registrar métricas de éxito/fallo
- Manejo de errores HTTP

**Constante:**
```python
AGENDAR_REUNIONES_ENDPOINT = "https://api.maravia.pe/servicio/n8n/ws_agendar_reunion.php"
```

**Función principal:**

#### `confirm_booking(...) -> Dict[str, Any]`
- **Líneas**: 23-154
- **Parámetros**:
  - `id_empresa: int`
  - `id_prospecto: str` - Session ID
  - `nombre_completo: str`
  - `correo_o_telefono: str`
  - `fecha: str` - YYYY-MM-DD
  - `hora: str` - HH:MM AM/PM
  - `servicio: str`
  - `id_usuario: int`
  - `sucursal: str = None` (opcional)

- **Retorna**:
  ```python
  {
      "success": bool,
      "codigo": str | None,  # Mensaje o enlace si success=True
      "message": str,
      "error": str | None
  }
  ```

**Flujo:**

1. **Registrar intento**:
   ```python
   record_booking_attempt()  # Métrica
   ```

2. **Preparar payload**:
   ```python
   payload = {
       "codOpe": "AGENDAR_REUNION",
       "id_empresa": 123,
       "id_prospecto": "session-id",
       "nombre_completo": "Juan Pérez",
       "correo_electronico": "987654321",  # ← Nota: campo es "correo_electronico" aunque puede ser teléfono
       "fecha_cita": "2026-01-29",
       "hora_cita": "02:00 PM",
       "servicio": "Corte de cabello",
       "id_usuario": 1
   }
   if sucursal:
       payload["sucursal"] = sucursal
   ```

3. **Llamar API**:
   ```python
   with track_api_call("agendar_reunion"):
       async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
           response = await client.post(
               AGENDAR_REUNIONES_ENDPOINT,
               json=payload,
               headers={"Content-Type": "application/json"}
           )
           response.raise_for_status()
           data = response.json()
   ```

4. **Procesar respuesta**:
   ```python
   if data.get("success"):
       codigo = data.get("codigo_cita")  # "RES-12345"
       record_booking_success()
       return {
           "success": True,
           "codigo": codigo,
           "message": f"Cita confirmada... {codigo or ''}",
           "error": None
       }
   else:
       error_msg = data.get("message", "Error desconocido")
       record_booking_failure("api_error")
       return {
           "success": False,
           "codigo": None,
           "message": "No se pudo confirmar...",
           "error": error_msg
       }
   ```

**Manejo de errores:**

- **TimeoutException**:
  ```python
  record_booking_failure("timeout")
  return {..., "error": "timeout"}
  ```

- **HTTPStatusError**:
  ```python
  record_booking_failure(f"http_{status_code}")
  return {..., "error": str(e)}
  ```

- **RequestError**:
  ```python
  record_booking_failure("connection_error")
  return {..., "error": str(e)}
  ```

- **Exception**:
  ```python
  record_booking_failure("unknown_error")
  return {..., "error": str(e)}
  ```

**Es llamado por:** `tools.create_booking()`

**Llama a:**
- API externa (httpx async)
- `logger.*`
- `metrics.record_booking_attempt/success/failure()`
- `config.API_TIMEOUT`

---

### 6. src/citas/validation.py (258 líneas)

**Propósito:** Validadores de datos con Pydantic 2.6+.

**Tecnología:** Pydantic BaseModel, field_validator

**Responsabilidades:**
- Validar formato de datos (email, teléfono, nombre, fecha, hora)
- Sanitizar datos (capitalización, limpieza)
- Proporcionar mensajes de error descriptivos

**Modelos Pydantic:**

#### `ContactInfo`
- **Líneas**: 12-59
- **Campo**: `contact: str`
- **Valida**: Email válido o teléfono peruano (9XXXXXXXX)
- **Patterns**:
  - Email: `r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'`
  - Teléfono: `r'^9\d{8}$'` (después de limpiar)
- **Limpieza**:
  - Remueve espacios, guiones, paréntesis
  - Remueve código +51 o 51
  - Convierte email a lowercase
- **Properties**:
  - `is_email: bool`
  - `is_phone: bool`
- **Raises**: ValueError si no es email ni teléfono válido

**Ejemplo:**
```python
ContactInfo(contact="987654321")       # ✓
ContactInfo(contact="+51 987654321")   # ✓ → "987654321"
ContactInfo(contact="user@email.com")  # ✓ → "user@email.com"
ContactInfo(contact="123")             # ✗ ValueError
```

#### `CustomerName`
- **Líneas**: 62-85
- **Campo**: `name: str` (min 2, max 100)
- **Valida**:
  - Mínimo 2 caracteres
  - No contiene números
  - Solo letras, espacios, guiones, apóstrofes (incluye acentos)
- **Pattern**: `r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\']+$'`
- **Sanitización**: `v.title()` (capitaliza)

**Ejemplo:**
```python
CustomerName(name="juan pérez")    # ✓ → "Juan Pérez"
CustomerName(name="O'Brien")       # ✓ → "O'Brien"
CustomerName(name="Juan123")       # ✗ ValueError (contiene números)
CustomerName(name="A")             # ✗ ValueError (muy corto)
```

#### `BookingDateTime`
- **Líneas**: 88-129
- **Campos**:
  - `date: str` (formato YYYY-MM-DD)
  - `time: str` (formato HH:MM AM/PM)
- **Valida date**:
  - Formato YYYY-MM-DD
  - No en el pasado (`date >= today`)
- **Valida time**:
  - Formatos: "%I:%M %p", "%I:%M%p", "%H:%M"
  - Ejemplos: "02:30 PM", "02:30PM", "14:30"

**Ejemplo:**
```python
BookingDateTime(date="2026-01-29", time="02:30 PM")  # ✓
BookingDateTime(date="2026-01-29", time="14:30")     # ✓
BookingDateTime(date="2020-01-01", time="10:00 AM")  # ✗ (fecha pasada)
BookingDateTime(date="29/01/2026", time="14:30")     # ✗ (formato inválido)
```

#### `BookingData`
- **Líneas**: 132-171
- **Campos**:
  - `service: str` (min 2, max 200)
  - `date: str`
  - `time: str`
  - `customer_name: str`
  - `customer_contact: str`
- **Valida**: Todos los campos usando los modelos anteriores
- **Validator**: `@model_validator(mode='after')` valida los datos de la cita completos

**Ejemplo:**
```python
BookingData(
    service="Corte de cabello",
    date="2026-01-29",
    time="02:30 PM",
    customer_name="Juan Pérez",
    customer_contact="987654321"
)  # ✓ Todo válido
```

**Funciones de utilidad:**

#### `validate_booking_data(...) -> tuple[bool, Optional[str]]`
- **Líneas**: 221-245
- **Propósito**: Función wrapper para validar datos de cita completos
- **Retorna**: `(True, None)` si válido, `(False, error_msg)` si inválido
- **Uso**: Llamada desde `tools.create_booking()`

**Otras funciones:**
- `validate_contact()`
- `validate_customer_name()`
- `validate_datetime()`

**Es llamado por:** `tools.create_booking()`

**No llama a otros módulos internos** (solo Pydantic)

---

### 7. src/citas/config.py (39 líneas)

**Propósito:** Configuración centralizada desde variables de entorno.

**Tecnología:** os.getenv, python-dotenv

**Responsabilidades:**
- Cargar archivo .env
- Definir variables de configuración con defaults
- Proporcionar acceso global a configuración

**Carga de .env:**
```python
from pathlib import Path
from dotenv import load_dotenv

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(_BASE_DIR / ".env")
```

**Variables (11 configurables):**

```python
# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Servidor
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8003"))

# Futuras (no usadas)
DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "")

# Timeouts
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "90"))
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "10"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))

# Cache
SCHEDULE_CACHE_TTL_MINUTES = int(os.getenv("SCHEDULE_CACHE_TTL_MINUTES", "5"))
```

**Es llamado por:** TODOS los módulos (importado como `app_config`)

**No llama a otros módulos internos**

---

### 8. src/citas/logger.py (79 líneas)

**Propósito:** Sistema de logging centralizado.

**Tecnología:** logging (stdlib)

**Responsabilidades:**
- Configurar formato de logs
- Configurar handlers (stdout + archivo)
- Silenciar loggers ruidosos de terceros
- Proporcionar getters de logger

**Formato de log:**
```python
'%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
```

**Ejemplo de output:**
```
2026-01-28 10:30:45 - citas.agent - INFO - [agent.py:212] - [AGENT] Invocando agent - Session: sess-001
```

**Funciones:**

#### `setup_logging(level, log_file, log_format)`
- **Líneas**: 19-55
- **Parámetros**:
  - `level: int` (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - `log_file: Optional[str]` - Ruta al archivo (opcional)
  - `log_format: Optional[str]` - Formato personalizado (opcional)
- **Handlers**:
  - `StreamHandler(sys.stdout)` - Siempre
  - `FileHandler(log_file)` - Solo si log_file especificado
- **Silenciamiento**:
  ```python
  logging.getLogger("httpx").setLevel(logging.WARNING)
  logging.getLogger("httpcore").setLevel(logging.WARNING)
  logging.getLogger("openai").setLevel(logging.WARNING)
  logging.getLogger("langchain").setLevel(logging.WARNING)
  ```

#### `get_logger(name: str) -> logging.Logger`
- **Líneas**: 58-72
- **Propósito**: Obtener logger por nombre de módulo
- **Uso**: `logger = get_logger(__name__)`

**Logger por defecto:**
```python
logger = get_logger("citas")
```

**Es llamado por:** TODOS los módulos

**No llama a otros módulos internos**

---

### 9. src/citas/metrics.py (219 líneas)

**Propósito:** Sistema de métricas Prometheus.

**Tecnología:** prometheus-client

**Responsabilidades:**
- Definir métricas (counters, histograms, gauges)
- Proporcionar context managers para tracking automático
- Funciones de registro de eventos

**Métricas definidas (13 métricas):**

**Counters (8):**

1. `agent_reservas_chat_requests_total{session_id}`
   - Total de mensajes recibidos

2. `agent_reservas_chat_errors_total{error_type}`
   - Errores en procesamiento de mensajes

3. `agent_reservas_booking_attempts_total`
   - Intentos de cita

4. `agent_reservas_booking_success_total`
   - Citas exitosas

5. `agent_reservas_booking_failed_total{reason}`
   - Citas fallidas por motivo

6. `agent_reservas_tool_calls_total{tool_name}`
   - Llamadas a tools

7. `agent_reservas_tool_errors_total{tool_name, error_type}`
   - Errores en tools

8. `agent_reservas_api_calls_total{endpoint, status}`
   - Llamadas a APIs externas

**Histograms (4):**

9. `agent_reservas_chat_response_duration_seconds`
   - Buckets: 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 90.0
   - Latencia de respuesta del chat

10. `agent_reservas_tool_execution_duration_seconds{tool_name}`
    - Buckets: 0.1, 0.5, 1.0, 2.0, 5.0, 10.0
    - Tiempo de ejecución de tools

11. `agent_reservas_api_call_duration_seconds{endpoint}`
    - Buckets: 0.1, 0.5, 1.0, 2.0, 5.0, 10.0
    - Tiempo de llamadas a API

12. `agent_reservas_llm_call_duration_seconds`
    - Buckets: 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 90.0
    - Tiempo de llamadas al LLM

**Gauges (1):**

13. `agent_reservas_cache_entries{cache_type}`
    - Número de entradas en cache

**Context Managers:**

#### `track_chat_response()`
- **Líneas**: 108-116
- **Uso**:
  ```python
  with track_chat_response():
      result = await process_message()
  ```
- **Registra**: Duración en `chat_response_duration_seconds`

#### `track_tool_execution(tool_name)`
- **Líneas**: 119-134
- **Incrementa**: `tool_calls_total`
- **Registra**: Duración en `tool_execution_duration_seconds`
- **Captura errores**: `tool_errors_total`

#### `track_api_call(endpoint)`
- **Líneas**: 137-151
- **Incrementa**: `api_calls_total{endpoint, status}`
- **Registra**: Duración en `api_call_duration_seconds`

#### `track_llm_call()`
- **Líneas**: 154-162
- **Registra**: Duración en `llm_call_duration_seconds`

**Funciones de registro:**

- `record_booking_attempt()` - Incrementa intentos
- `record_booking_success()` - Incrementa éxitos
- `record_booking_failure(reason)` - Incrementa fallos con razón
- `record_chat_error(error_type)` - Registra error de chat
- `update_cache_stats(cache_type, count)` - Actualiza gauge
- `initialize_agent_info(model, version)` - Info del agente

**Es llamado por:** TODOS los módulos operacionales

**No llama a otros módulos internos**

---

### 10. src/citas/models.py (38 líneas)

**Propósito:** Modelos Pydantic para requests/responses.

**Tecnología:** Pydantic 2.6+

**Responsabilidades:**
- Definir schemas de datos
- Validación automática
- Serialización/deserialización

**Modelos:**

#### `ChatRequest`
- **Líneas**: 9-17
- **Campos**:
  - `message: str`
  - `session_id: str`
  - `context: Dict[str, Any] = {}`

#### `ChatResponse`
- **Líneas**: 20-28
- **Campos**:
  - `reply: str`
  - `session_id: str`
  - `metadata: Optional[Dict[str, Any]] = None`

#### `CitaConfig`
- **Líneas**: 31-38
- **Campos**:
  - `personalidad: str = "amable, profesional y eficiente"`

**Es llamado por:** `agent.py` (valida config)

**No llama a otros módulos internos**

---

### 11. src/citas/prompts/__init__.py (56 líneas)

**Propósito:** Constructor de system prompt con Jinja2.

**Tecnología:** Jinja2 templates

**Responsabilidades:**
- Cargar template desde archivo
- Aplicar defaults a configuración
- Renderizar prompt con variables

**Constantes:**

```python
_TEMPLATES_DIR = Path(__file__).resolve().parent
_DEFAULTS = {
    "personalidad": "amable, profesional y eficiente"
}
```

**Funciones:**

#### `_apply_defaults(config: Dict) -> Dict`
- **Líneas**: 16-22
- **Propósito**: Merge config con defaults
- **Lógica**: Solo aplica valores no None, no "", no []

#### `build_citas_system_prompt(config: Dict, history: List[Dict]) -> str`
- **Líneas**: 25-52
- **Propósito**: Construir system prompt completo
- **Proceso**:
  1. Crear Jinja2 environment
  2. Cargar template "citas_system.j2"
  3. Aplicar defaults
  4. Agregar history y has_history
  5. Renderizar template
- **Retorna**: System prompt formateado (string)

**Ejemplo de variables:**
```python
{
    "personalidad": "amable y profesional",
    "history": [
        {"user": "Hola", "response": "¡Hola!..."}
    ],
    "has_history": True
}
```

**Es llamado por:** `agent._get_agent()`

**Llama a:** Template `citas_system.j2`

---

### 12. src/citas/prompts/citas_system.j2 (166 líneas)

**Propósito:** Template Jinja2 del system prompt.

**Tecnología:** Jinja2 template syntax

**Responsabilidades:**
- Definir rol del agente
- Describir herramientas disponibles
- Establecer flujo de trabajo
- Proporcionar ejemplos

**Estructura del template:**

1. **Rol** (líneas 1-12)
   - Descripción del agente
   - Función principal
   - Datos necesarios

2. **Personalidad** (líneas 13-15)
   ```jinja
   Eres {{ personalidad }}.
   ```

3. **Herramientas disponibles** (líneas 17-37)
   - `check_availability(service, date)`
   - `create_booking(service, date, time, customer_name, customer_contact)`
   - Instrucciones de uso

4. **Historial** (líneas 39-58)
   ```jinja
   {% if has_history %}
   ## Historial de esta Conversación
   {% for turn in history %}
   **Turno {{ loop.index }}:**
   - Usuario: "{{ turn.user }}"
   - Respondiste: "{{ turn.response }}"
   {% endfor %}
   {% endif %}
   ```

5. **Flujo de trabajo** (líneas 60-68)
   - Pasos a seguir

6. **Flujo de captura de datos** (líneas 70-90)
   - Qué preguntar según datos faltantes

7. **Reglas importantes** (líneas 92-100)
   - Una pregunta a la vez
   - Brevedad
   - Confirmación
   - etc.

8. **Casos especiales** (líneas 102-121)
   - Consulta de disponibilidad
   - Modificación
   - Cancelación

9. **Ejemplos** (líneas 125-162)
   - Flujo completo desde cero
   - Flujo con información completa
   - Flujo de modificación

**Variables usadas:**
- `{{ personalidad }}` - Personalidad del agente
- `{{ history }}` - Lista de turnos previos
- `{{ has_history }}` - Boolean si hay historial

**Es usado por:** `prompts/__init__.py`

---

### 13. src/citas/__init__.py (42 líneas)

**Propósito:** Módulo de inicialización y exports.

**Responsabilidades:**
- Definir metadata del proyecto
- Exportar funciones principales
- Proporcionar `__all__`

**Metadata:**
```python
__version__ = "2.0.0"
__author__ = "MaravIA Team"
```

**Exports:**
```python
from .agent import process_cita_message
from .logger import get_logger, setup_logging
from .metrics import (
    track_chat_response,
    track_tool_execution,
    record_booking_success,
    record_booking_failure
)

__all__ = [
    "process_cita_message",
    "get_logger",
    "setup_logging",
    "track_chat_response",
    "track_tool_execution",
    "record_booking_success",
    "record_booking_failure",
]
```

---

## Flujo de Datos Completo

### Caso 1: Usuario Consulta Disponibilidad

```
1. ORQUESTADOR
   ↓ HTTP POST (MCP)
   {
     "tool": "chat",
     "arguments": {
       "message": "¿Tienen horarios el viernes?",
       "session_id": "sess-001",
       "context": {"config": {"id_empresa": 123}}
     }
   }

2. main.chat() [main.py:44]
   ↓ Recibe request
   ↓ logger.info("[MCP] Mensaje recibido")
   ↓ Llama a agent.process_cita_message()

3. agent.process_cita_message() [agent.py:151]
   ↓
   ├─ Valida message no vacío ✓
   ├─ Valida session_id presente ✓
   ├─ chat_requests_total.inc()
   ├─ _validate_context(context)
   │  └─ Verifica id_empresa=123 ✓
   │
   ├─ _get_agent(config)
   │  ├─ init_chat_model("openai:gpt-4o-mini", temp=0.4, timeout=90s)
   │  ├─ build_citas_system_prompt(config, history=None)
   │  │  └─ Renderiza template con personalidad="amable, profesional y eficiente"
   │  └─ create_agent(model, tools=[check_availability, create_booking], prompt, checkpointer)
   │
   ├─ _prepare_agent_context(context, "sess-001")
   │  └─ AgentContext(id_empresa=123, duracion_cita_minutos=60, slots=60, id_usuario=1, session_id="sess-001")
   │
   └─ agent.invoke()
      with track_chat_response():
        with track_llm_call():
          ↓
          4. LANGCHAIN AGENT (GPT-4o-mini)
             ↓ Analiza: "¿Tienen horarios el viernes?"
             ↓ System prompt indica usar check_availability para consultas
             ↓ Decide: Usar check_availability(service="consulta", date="2026-01-31")
             ↓
             5. tools.check_availability() [tools.py:28]
                with track_tool_execution("check_availability"):
                  ↓
                  ├─ Extrae runtime.context
                  │  id_empresa = 123
                  │  duracion_cita_minutos = 60
                  │  slots = 60
                  │  id_usuario = 1
                  │
                  ├─ ScheduleValidator(id_empresa=123, duracion_cita_minutos=60, slots=60, es_cita=True, agendar_usuario=1, agendar_sucursal=0)
                  │
                  └─ await validator.recommendation()
                     ↓
                     6. schedule_validator.recommendation() [schedule_validator.py:423]
                        ↓
                        ├─ await _fetch_schedule()
                        │  ↓
                        │  7. schedule_validator._fetch_schedule() [schedule_validator.py:114]
                        │     ↓
                        │     ├─ _get_cached_schedule(123)
                        │     │  └─ Cache MISS (primera vez)
                        │     │
                        │     ├─ POST https://api.maravia.pe/servicio/ws_informacion_ia.php
                        │     │  with track_api_call("obtener_horario"):
                        │     │    Payload: {"codOpe": "OBTENER_HORARIO_REUNIONES", "id_empresa": 123}
                        │     │    Timeout: 10s
                        │     │    Response: {
                        │     │      "success": true,
                        │     │      "horario_reuniones": {
                        │     │        "reunion_lunes": "09:00-18:00",
                        │     │        "reunion_martes": "09:00-18:00",
                        │     │        "reunion_miercoles": "09:00-18:00",
                        │     │        "reunion_jueves": "09:00-18:00",
                        │     │        "reunion_viernes": "09:00-18:00",
                        │     │        "reunion_sabado": "09:00-13:00",
                        │     │        "reunion_domingo": "NO DISPONIBLE"
                        │     │      }
                        │     │    }
                        │     │
                        │     └─ _set_cached_schedule(123, schedule)
                        │        └─ Guarda en cache global con timestamp
                        │        └─ update_cache_stats('schedule', 1)
                        │
                        ├─ Construir texto recomendación:
                        │  "Horarios disponibles:
                        │   • Lunes: 09:00 AM - 06:00 PM
                        │   • Martes: 09:00 AM - 06:00 PM
                        │   • Miércoles: 09:00 AM - 06:00 PM
                        │   • Jueves: 09:00 AM - 06:00 PM
                        │   • Viernes: 09:00 AM - 06:00 PM
                        │   • Sábado: 09:00 AM - 01:00 PM"
                        │
                        └─ return {"text": "Horarios disponibles:..."}

                  └─ return recommendations["text"]

             ↓ LLM recibe: "Horarios disponibles:\n• Lunes: 09:00 AM - 06:00 PM\n..."
             ↓ LLM procesa respuesta de tool
             ↓ LLM genera respuesta natural:
             ↓ "¡Claro! El viernes tenemos disponibilidad de 09:00 AM a 06:00 PM. ¿A qué hora te gustaría agendar?"
             ↓
             └─ return {"messages": [..., AIMessage(content="¡Claro! El viernes...")]}

   └─ Extrae último mensaje
      response_text = "¡Claro! El viernes tenemos disponibilidad de 09:00 AM a 06:00 PM. ¿A qué hora te gustaría agendar?"

   └─ return response_text

8. main.chat() retorna al ORQUESTADOR
   ↓
   Response: {
     "result": "¡Claro! El viernes tenemos disponibilidad de 09:00 AM a 06:00 PM. ¿A qué hora te gustaría agendar?"
   }
```

---

### Caso 2: Usuario Crea Cita Completa

```
1. ORQUESTADOR
   ↓
   {
     "message": "Necesito corte de cabello para mañana a las 2pm, soy Juan Pérez, mi teléfono es 987654321",
     "session_id": "sess-002",
     "context": {"config": {"id_empresa": 123}}
   }

2. main.chat() → agent.process_cita_message()

3. agent.process_cita_message()
   ├─ Validaciones ✓
   ├─ Crea agente
   └─ agent.invoke()
      ↓
      4. LANGCHAIN AGENT (GPT-4o-mini)
         ↓ Analiza mensaje
         ↓ Detecta: servicio="corte de cabello", fecha="mañana" (2026-01-29), hora="2pm", nombre="Juan Pérez", contacto="987654321"
         ↓ System prompt indica que con todos los datos debe usar create_booking
         ↓ Decide: create_booking("Corte de cabello", "2026-01-29", "02:00 PM", "Juan Pérez", "987654321")
         ↓
         5. tools.create_booking() [tools.py:89]
            with track_tool_execution("create_booking"):
              ↓
              ├─ Extrae runtime.context
              │  id_empresa = 123, duracion_cita_minutos = 60, slots = 60
              │  id_usuario = 1, session_id = "sess-002"
              │
              ├─ CAPA 1: VALIDACIÓN PYDANTIC
              │  ↓
              │  6. validation.validate_booking_data() [validation.py:221]
              │     ↓
              │     7. BookingData() [validation.py:132]
              │        ├─ service: "Corte de cabello" ✓ (>2 chars)
              │        ├─ date: "2026-01-29"
              │        │  └─ BookingDateTime.validate_date()
              │        │     ├─ Parse YYYY-MM-DD ✓
              │        │     └─ date >= today ✓
              │        ├─ time: "02:00 PM"
              │        │  └─ BookingDateTime.validate_time()
              │        │     └─ Parse "%I:%M %p" ✓
              │        ├─ customer_name: "Juan Pérez"
              │        │  └─ CustomerName.validate_name()
              │        │     ├─ No números ✓
              │        │     ├─ Min 2 chars ✓
              │        │     └─ Capitaliza → "Juan Pérez"
              │        └─ customer_contact: "987654321"
              │           └─ ContactInfo.validate_contact()
              │              ├─ Not email pattern
              │              ├─ Clean phone (ya está limpio)
              │              ├─ Remove +51 (no tiene)
              │              └─ Match r'^9\d{8}$' ✓
              │
              │        └─ return (True, None)
              │
              ├─ CAPA 2: VALIDACIÓN DE HORARIO
              │  ↓
              │  8. ScheduleValidator.validate("2026-01-29", "02:00 PM") [schedule_validator.py:331]
              │     ↓
              │     ├─ Parse fecha: 2026-01-29 ✓
              │     ├─ Parse hora: 02:00 PM (14:00) ✓
              │     ├─ Combinar: 2026-01-29 14:00:00
              │     ├─ Validar no pasado: ahora < 2026-01-29 14:00:00 ✓
              │     │
              │     ├─ await _fetch_schedule()
              │     │  └─ Cache HIT (ya cacheado en caso anterior)
              │     │  └─ return schedule
              │     │
              │     ├─ Día de semana: 29/01/2026 = Miércoles (weekday=2)
              │     ├─ Campo: DAY_MAPPING[2] = "reunion_miercoles"
              │     ├─ Horario: schedule["reunion_miercoles"] = "09:00-18:00"
              │     ├─ Validar no cerrado: "09:00-18:00" not in ["NO DISPONIBLE", ...] ✓
              │     │
              │     ├─ Parse rango: "09:00-18:00" → (09:00, 18:00)
              │     ├─ Validar hora en rango:
              │     │  ├─ 14:00 >= 09:00 ✓
              │     │  └─ 14:00 < 18:00 ✓
              │     │
              │     ├─ Validar cita + duración <= cierre:
              │     │  ├─ hora_fin_cita = 14:00 + 60min = 15:00
              │     │  └─ 15:00 <= 18:00 ✓
              │     │
              │     ├─ Validar no bloqueado:
              │     │  └─ _is_time_blocked(2026-01-29, 14:00, horarios_bloqueados)
              │     │     └─ No bloqueado ✓
              │     │
              │     └─ CAPA 3: VALIDACIÓN DE DISPONIBILIDAD
              │        ↓
              │        9. schedule_validator._check_availability("2026-01-29", "02:00 PM") [schedule_validator.py:260]
              │           ↓
              │           ├─ fecha_hora_inicio = 2026-01-29 14:00:00
              │           ├─ fecha_hora_fin = 2026-01-29 15:00:00
              │           │
              │           ├─ POST https://api.maravia.pe/servicio/n8n/ws_agendar_reunion.php
              │           │  with track_api_call("consultar_disponibilidad"):
              │           │    Payload: {
              │           │      "codOpe": "CONSULTAR_DISPONIBILIDAD",
              │           │      "id_empresa": 123,
              │           │      "fecha_inicio": "2026-01-29 14:00:00",
              │           │      "fecha_fin": "2026-01-29 15:00:00",
              │           │      "slots": 60,
              │           │      "agendar_usuario": 1,
              │           │      "agendar_sucursal": 0
              │           │    }
              │           │    Timeout: 10s
              │           │    Response: {
              │           │      "success": true,
              │           │      "disponible": true
              │           │    }
              │           │
              │           └─ return {"available": True, "error": None}
              │
              │     └─ return {"valid": True, "error": None}
              │
              ├─ CONFIRMACIÓN EN API
              │  ↓
              │  10. booking.confirm_booking() [booking.py:23]
              │      ↓
              │      ├─ record_booking_attempt()
              │      │
              │      ├─ Preparar payload:
              │      │  {
              │      │    "codOpe": "AGENDAR_REUNION",
              │      │    "id_empresa": 123,
              │      │    "id_prospecto": "sess-002",
              │      │    "nombre_completo": "Juan Pérez",
              │      │    "correo_electronico": "987654321",
              │      │    "fecha_cita": "2026-01-29",
              │      │    "hora_cita": "02:00 PM",
              │      │    "servicio": "Corte de cabello",
              │      │    "id_usuario": 1
              │      │  }
              │      │
              │      ├─ POST https://api.maravia.pe/servicio/n8n/ws_agendar_reunion.php
              │      │  with track_api_call("agendar_reunion"):
              │      │    Timeout: 10s
              │      │    Response: {
              │      │      "success": true,
              │      │      "codigo_cita": "RES-12345"
              │      │    }
              │      │
              │      ├─ record_booking_success()
              │      │
              │      └─ return {
              │           "success": True,
              │           "codigo": "RES-12345",
              │           "message": "Reserva confirmada... Código: RES-12345",
              │           "error": None
              │         }
              │
              └─ Formatear respuesta:
                 return """Cita confirmada exitosamente

**Detalles:**
• Servicio: Corte de cabello
• Fecha: 2026-01-29
• Hora: 02:00 PM
• Nombre: Juan Pérez
• **Código: RES-12345**

Guarda este código para futuras consultas. ¡Te esperamos!"""

         ↓ LLM recibe resultado de create_booking
         ↓ LLM retorna directamente (ya está formateado)
         ↓
         └─ return {"messages": [..., AIMessage(content="Cita confirmada...")]}

   └─ return "Cita confirmada exitosamente\n\n**Detalles:**..."

8. main.chat() retorna al ORQUESTADOR
   Response: {"result": "Cita confirmada exitosamente..."}
```

---

## Comunicación entre Módulos

### Tabla de Dependencias

| Módulo Origen | Módulo Destino | Función/Clase | Datos Enviados | Datos Recibidos |
|---------------|----------------|---------------|----------------|-----------------|
| **Orquestador** | main.chat() | Tool call | {message, session_id, context} | str: respuesta |
| **main.py** | agent.process_cita_message() | Llamada directa | message, session_id, context | str: respuesta |
| **main.py** | logger.setup_logging() | Config inicial | level, log_file | None |
| **main.py** | metrics.initialize_agent_info() | Config inicial | model="gpt-4o-mini", version="2.0.0" | None |
| **agent.py** | config.* | Import | - | Variables de configuración |
| **agent.py** | models.ReservaConfig() | Validación | config dict | ReservaConfig validado |
| **agent.py** | prompts.build_citas_system_prompt() | Construcción | config, history=None | str: system prompt |
| **agent.py** | tools.AGENT_TOOLS | Registro | - | List[Tool] |
| **agent.py** | LangChain create_agent() | Invocación | model, tools, prompt, checkpointer | Agent |
| **agent.py** | agent.invoke() | Ejecución | messages, config, context | dict: resultado |
| **agent.py** | metrics.chat_requests_total.inc() | Tracking | labels={session_id} | None |
| **agent.py** | metrics.track_chat_response() | Context mgr | - | Context |
| **agent.py** | metrics.track_llm_call() | Context mgr | - | Context |
| **LangChain** | tools.check_availability() | Function call | service, date, runtime | str: horarios |
| **LangChain** | tools.create_booking() | Function call | service, date, time, name, contact, runtime | str: confirmación |
| **tools.py** | runtime.context | Extracción | - | AgentContext |
| **tools.py** | ScheduleValidator() | Instanciación | id_empresa, duracion, slots, etc | Instancia |
| **tools.py** | validator.recommendation() | Async call | - | dict: {text} |
| **tools.py** | validator.validate() | Async call | date, time | dict: {valid, error} |
| **tools.py** | validation.validate_booking_data() | Validación | service, date, time, name, contact | tuple: (bool, str) |
| **tools.py** | booking.confirm_booking() | Async call | id_empresa, id_prospecto, nombre, contacto, fecha, hora, servicio, id_usuario | dict: {success, codigo, message, error} |
| **tools.py** | metrics.track_tool_execution() | Context mgr | tool_name | Context |
| **schedule_validator.py** | _get_cached_schedule() | Lectura cache | id_empresa | dict \| None |
| **schedule_validator.py** | _set_cached_schedule() | Escritura cache | id_empresa, schedule | None |
| **schedule_validator.py** | API ws_informacion_ia.php | HTTP POST | {codOpe, id_empresa} | {success, horario_reuniones} |
| **schedule_validator.py** | API ws_agendar_reunion.php | HTTP POST | {codOpe, id_empresa, fecha_inicio, fecha_fin, slots, ...} | {success, disponible} |
| **schedule_validator.py** | metrics.track_api_call() | Context mgr | endpoint | Context |
| **schedule_validator.py** | metrics.update_cache_stats() | Update gauge | cache_type, count | None |
| **booking.py** | API ws_agendar_reunion.php | HTTP POST | {codOpe, id_empresa, id_prospecto, nombre_completo, correo_electronico, fecha_cita, hora_cita, servicio, id_usuario} | {success, codigo_cita} |
| **booking.py** | metrics.record_booking_attempt() | Counter inc | - | None |
| **booking.py** | metrics.record_booking_success() | Counter inc | - | None |
| **booking.py** | metrics.record_booking_failure() | Counter inc | reason | None |
| **validation.py** | Pydantic validators | Validación | datos crudos | Modelos validados |
| **prompts/__init__.py** | Jinja2 template | Renderizado | variables | str: prompt |
| **Todos** | logger.get_logger() | Obtener logger | __name__ | Logger |
| **Todos** | config.* | Lectura | - | Valores configurados |

---

## Patrones de Diseño

### 1. Factory Pattern
**Ubicación:** `agent._get_agent(config)`

El agente se recrea en cada invocación para tener configuración actualizada.

```python
def _get_agent(config: Dict):
    model = init_chat_model(...)
    system_prompt = build_citas_system_prompt(config, history=None)
    agent = create_agent(model, tools, system_prompt, checkpointer)
    return agent
```

**Beneficio:** Configuración dinámica por request.

---

### 2. Runtime Context Injection (LangChain 1.2+)
**Ubicación:** `agent.py`, `tools.py`

El contexto se inyecta automáticamente en las tools sin parámetros explícitos.

```python
@tool
async def check_availability(service: str, date: str, runtime: ToolRuntime = None) -> str:
    ctx = runtime.context  # ← Inyectado automáticamente
    id_empresa = ctx.id_empresa
```

**Beneficio:** Código más limpio, sin repetición de parámetros.

---

### 3. Repository Pattern
**Ubicación:** `schedule_validator.py`

Abstrae el acceso a datos de horarios con cache.

```python
class ScheduleValidator:
    async def _fetch_schedule(self):
        # Intenta cache primero
        # Si miss, consulta API
        # Guarda en cache
```

**Beneficio:** Cache transparente, separación de lógica de acceso.

---

### 4. Cache with TTL + Singleton
**Ubicación:** `schedule_validator.py`

Cache global thread-safe compartido entre instancias.

```python
_SCHEDULE_CACHE: Dict[int, Tuple[Dict, datetime]] = {}
_CACHE_LOCK = threading.Lock()

def _get_cached_schedule(id_empresa: int):
    with _CACHE_LOCK:
        if id_empresa in _SCHEDULE_CACHE:
            schedule, timestamp = _SCHEDULE_CACHE[id_empresa]
            if datetime.now() - timestamp < TTL:
                return schedule
```

**Beneficio:** Reduce llamadas API, thread-safe.

---

### 5. Observer Pattern (Metrics)
**Ubicación:** `metrics.py`

Métricas observan el sistema sin interferir con lógica de negocio.

```python
@contextmanager
def track_tool_execution(tool_name: str):
    start = time.time()
    tool_calls_total.labels(tool_name=tool_name).inc()
    try:
        yield
    finally:
        duration = time.time() - start
        tool_execution_duration_seconds.labels(tool_name).observe(duration)
```

**Beneficio:** Separación de concerns, tracking automático.

---

### 6. Template Method (Prompts)
**Ubicación:** `prompts/citas_system.j2`

Estructura del prompt definida en template, variables inyectadas.

```jinja
Eres {{ personalidad }}.

{% if has_history %}
## Historial
{% for turn in history %}
...
{% endfor %}
{% endif %}
```

**Beneficio:** Personalización sin modificar código.

---

### 7. Validator Pattern (Pydantic)
**Ubicación:** `validation.py`

Validación declarativa con decoradores.

```python
class ContactInfo(BaseModel):
    contact: str

    @field_validator('contact')
    @classmethod
    def validate_contact(cls, v: str) -> str:
        # Validación automática
```

**Beneficio:** Validación consistente, mensajes de error automáticos.

---

### 8. Checkpointer Pattern (LangChain)
**Ubicación:** `agent.py`

Memoria automática gestionada por checkpointer.

```python
_checkpointer = InMemorySaver()

agent = create_agent(..., checkpointer=_checkpointer)

agent.invoke(
    ...,
    config={"configurable": {"thread_id": session_id}}
)
```

**Beneficio:** Memoria sin gestión manual.

---

### 9. Graceful Degradation
**Ubicación:** `schedule_validator.py`, `tools.py`

Si falla una operación no crítica, continúa con fallback.

```python
try:
    schedule = await self._fetch_schedule()
    if not schedule:
        return {"valid": True, "error": None}  # ← Graceful
except Exception:
    return {"available": True, "error": None}  # ← Graceful
```

**Beneficio:** Sistema resiliente ante fallos externos.

---

### 10. Strategy Pattern (Validación Multicapa)
**Ubicación:** `tools.create_booking()`

Tres estrategias de validación aplicadas secuencialmente.

```python
# Estrategia 1: Pydantic
is_valid, error = validate_booking_data(...)

# Estrategia 2: Horario
validation = await validator.validate(...)

# Estrategia 3: Disponibilidad
booking_result = await confirm_booking(...)
```

**Beneficio:** Validación exhaustiva con separación de concerns.

---

## Dependencias entre Archivos

```
config.py (0 dependencias internas)
    ↑
    ├── logger.py (1 dep: config)
    │       ↑
    ├── metrics.py (1 dep: config)
    │       ↑
    └── models.py (1 dep: pydantic)
            ↑
            ├── validation.py (2 deps: models, pydantic)
            │       ↑
            ├── schedule_validator.py (4 deps: config, logger, metrics, httpx)
            │       ↑
            └── booking.py (4 deps: config, logger, metrics, httpx)
                    ↑
                    └── tools.py (6 deps: schedule_validator, booking, validation, logger, metrics, langchain)
                            ↑
                            └── prompts/__init__.py (1 dep: jinja2)
                                    ↑ (usa citas_system.j2)
                                    └── agent.py (9 deps: config, models, tools, logger, metrics, prompts, langchain)
                                            ↑
                                            └── main.py (7 deps: config, agent, logger, metrics, fastmcp)
                                                    ↑
                                                    └── ORQUESTADOR (externo)
```

**Niveles de dependencia:**
- Nivel 0: config.py
- Nivel 1: logger.py, metrics.py, models.py
- Nivel 2: validation.py, schedule_validator.py, booking.py
- Nivel 3: tools.py, prompts/__init__.py
- Nivel 4: agent.py
- Nivel 5: main.py

**Total de archivos:** 13 (sin contar __init__.py vacíos)

---

## Resumen

El **Agent Citas** es un sistema bien arquitectado que utiliza:

- **LangChain 1.2+ API moderna** con memoria automática
- **Validación multicapa** (Pydantic + horarios + disponibilidad)
- **Cache thread-safe con TTL** para optimizar performance
- **Observabilidad completa** (logging + métricas Prometheus)
- **Arquitectura asíncrona** con httpx para mejor concurrencia
- **Patrones de diseño sólidos** (Factory, Repository, Observer, etc.)

El flujo de datos es claro y la separación de responsabilidades permite mantenibilidad y escalabilidad.

**Limitación principal:** Memoria volátil (InMemorySaver) requiere migración a Redis/PostgreSQL para producción multi-instancia.

---

**Versión:** 2.0.0
**Última actualización:** 2026-01-28
