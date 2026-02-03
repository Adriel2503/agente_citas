# Revisión del Agente de Citas (agent_citas)

**Última actualización:** 2026-02-03

## Resumen

El agente está bien estructurado, alineado con ws_calendario (CREAR_EVENTO) y con el flujo MaravIA (orquestador → agente citas → tools → API).

**Estructura de directorios:**
```
src/citas/
├── agent/agent.py           # Lógica LangChain
├── tool/tools.py            # check_availability, create_booking
├── services/
│   ├── schedule_validator.py
│   ├── booking.py           # CREAR_EVENTO → ws_calendario.php
│   └── horario_reuniones.py
├── config/
│   ├── config.py
│   └── models.py
├── prompts/
├── validation.py
├── logger.py
├── metrics.py
└── main.py
```

---

## Lo que está bien

- **Payload CREAR_EVENTO**: booking.py envía codOpe, id_usuario, id_prospecto, titulo, fecha_inicio, fecha_fin, correo_cliente, correo_usuario, agendar_usuario. Coincide con ws_calendario.php.
- **Contexto del orquestador**: id_empresa, agendar_usuario, id_usuario, correo_usuario se reciben y se convierten a int/str en AgentContext; el identificador del prospecto es el **session_id** que envía el orquestador (no se envía id_prospecto en config). Las tools usan ese contexto y pasan session_id como id_prospecto a confirm_booking.
- **System prompt**: Inyecta fecha/hora Perú, horario de reuniones (API), instrucciones claras para las tools.
- **Validación**: validation.py valida servicio, fecha, hora, nombre, contacto (email).
- **ScheduleValidator**: Cache TTL, SUGERIR_HORARIOS para hoy/mañana, OBTENER_HORARIO_REUNIONES; validate() para comprobar slot antes de confirmar; es_cita=True para flujo de citas.
- **MCP**: Una sola tool `chat` expuesta al orquestador; contexto requerido documentado.
- **Manejo de errores**: booking.py captura timeout, HTTP, RequestError; tools devuelven mensajes claros al usuario.

---

## Mejoras menores aplicadas / sugeridas

1. **main.py (chat docstring)**: Se documenta el contexto que espera el agente (id_empresa, id_usuario, correo_usuario, agendar_usuario, etc.). El orquestador no envía id_prospecto; el agente usa solo session_id como identificador del prospecto.
2. **citas_system.j2**: Instrucciones para check_availability y create_booking; flujo de captura (motivo, fecha, hora, nombre, email).
3. **booking.py**: Si se quiere un mensaje más claro cuando la hora tiene formato inválido, se captura ValueError en confirm_booking y se devuelve `{"success": False, "error": "Formato de fecha u hora inválido"}`; las tools devuelven mensaje amigable.

---

## Comportamiento esperado end-to-end

1. Orquestador envía message, session_id, context (config con id_empresa, id_usuario, correo_usuario, agendar_usuario, personalidad, etc.). No envía id_prospecto; el agente usa session_id como identificador del prospecto.
2. Agente construye el system prompt (fecha Perú, horario de reuniones desde API, instrucciones).
3. Usuario conversa; la IA usa check_availability cuando pide disponibilidad y create_booking cuando tiene todos los datos.
4. create_booking valida datos, valida horario con ScheduleValidator, llama a confirm_booking con id_prospecto=session_id, id_usuario, correo_usuario, etc.
5. booking.py arma fecha_inicio/fecha_fin, titulo, y envía el JSON a ws_calendario.php (CREAR_EVENTO); el evento se crea en el calendario.

---

## Archivos clave

| Archivo | Rol |
|--------|-----|
| `agent/agent.py` | AgentContext, _prepare_agent_context, process_cita_message |
| `services/booking.py` | confirm_booking, payload CREAR_EVENTO → ws_calendario.php |
| `tool/tools.py` | check_availability, create_booking, uso de runtime context |
| `prompts/citas_system.j2` | Instrucciones, flujo de captura (motivo, fecha, hora, nombre, email) |
| `prompts/__init__.py` | build_citas_system_prompt, fecha Perú, fetch_horario_reuniones |
| `services/schedule_validator.py` | Cache TTL, validate, recommendation (SUGERIR_HORARIOS), es_cita |
| `services/horario_reuniones.py` | fetch_horario_reuniones para system prompt |
| `validation.py` | validate_booking_data, ContactInfo, BookingDateTime |
| `config/config.py` | Variables de entorno, URLs de APIs |
| `config/models.py` | CitaConfig (Pydantic) |
| `main.py` | MCP tool chat, punto de entrada |

## AgentContext (campos actuales)

```python
@dataclass
class AgentContext:
    id_empresa: int              # REQUERIDO
    duracion_cita_minutos: int = 60
    slots: int = 60
    agendar_usuario: int = 1
    id_usuario: int = 1
    correo_usuario: str = ""
    agendar_sucursal: int = 0
    id_prospecto: str = ""       # = session_id
    session_id: str = ""
```
