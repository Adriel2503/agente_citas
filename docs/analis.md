
  ---
  Auditoría Técnica — Agente de Citas (MaravIA)

  ---
  1. Resumen Ejecutivo

  El sistema está bien estructurado para un agente Python con FastAPI + LangGraph + httpx. El código muestra buenas prácticas en asincronismo,
  observabilidad y caching. Sin embargo, presenta un memory leak real en producción, ausencia de retry en la mayoría de servicios HTTP, y estado in-memory
  que impide escalar horizontalmente. No hay operaciones síncronas bloqueantes críticas en rutas calientes.

  Nivel de madurez: 6.5 / 10

  ---
  2. Problemas Detectados

  ---
  🔴 CRÍTICO — InMemorySaver sin evicción: memory leak real

  Archivo: agent/agent.py:43

  _checkpointer = InMemorySaver()

  InMemorySaver de LangGraph almacena el historial completo de todas las conversaciones, de todas las sesiones, de todas las empresas, en un dict interno
  que nunca libera memoria. No tiene TTL, ni maxsize, ni política de evicción.

  Los _session_locks tienen cleanup (threshold 500), pero el checkpointer guarda los mensajes por thread_id indefinidamente. En un sistema multi-empresa de
  larga duración, esto agota la RAM del proceso progresivamente.

  Impacto: Memory leak gradual → OOM del servidor en producción.

  ---
  🔴 CRÍTICO — threading.Lock mezclado con asyncio en ruta caliente

  Archivo: services/schedule_validator.py:55-56

  _SCHEDULE_CACHE: Dict[int, Tuple[Dict, datetime]] = {}
  _CACHE_LOCK = threading.Lock()

  _get_cached_schedule y _set_cached_schedule adquieren un threading.Lock() de forma síncrona dentro de funciones llamadas desde contexto async. Funciona
  hoy porque uvicorn corre en un único hilo del event loop. Riesgo real:

  1. Si se añade run_in_executor o workers threaded → deadlock posible.
  2. Es un anti-patrón que confunde a futuros desarrolladores.
  3. _CACHE_LOCK no es necesario en asyncio single-thread; las operaciones de dict son atómicas bajo el GIL.

  Fix recomendado: eliminar _CACHE_LOCK o reemplazar por asyncio.Lock si se necesita serialización real (ya se tiene para fetch HTTP).

  ---
  🔴 CRÍTICO — Sin retry/backoff en la mayoría de servicios HTTP

  Solo contexto_negocio.py tiene retry (2 intentos + backoff exponencial). El resto falla sin reintento en la primera excepción de red:

  ┌────────────────────────────────────────┬───────┐
  │                Servicio                │ Retry │
  ├────────────────────────────────────────┼───────┤
  │ horario_reuniones.py                   │ ❌    │
  ├────────────────────────────────────────┼───────┤
  │ productos_servicios_citas.py           │ ❌    │
  ├────────────────────────────────────────┼───────┤
  │ busqueda_productos.py                  │ ❌    │
  ├────────────────────────────────────────┼───────┤
  │ booking.py                             │ ❌    │
  ├────────────────────────────────────────┼───────┤
  │ schedule_validator._check_availability │ ❌    │
  ├────────────────────────────────────────┼───────┤
  │ schedule_validator._fetch_schedule     │ ❌    │
  ├────────────────────────────────────────┼───────┤
  │ contexto_negocio.py                    │ ✅    │
  └────────────────────────────────────────┴───────┘

  Un timeout transitorio de 100ms en booking.py hace fallar la creación de una cita, cuando un reintento la habría salvado.

  ---
  🔴 CRÍTICO — fetch_horario_reuniones sin caché propia

  Archivo: services/horario_reuniones.py (llamada desde prompts/__init__.py:100)

  Cuando el _agent_cache expira, _get_agent llama build_citas_system_prompt, que lanza 4 requests en paralelo sin caché propia para horario, productos, FAQ.
   Solo contexto_negocio tiene TTLCache.

  results = await asyncio.gather(
      fetch_horario_reuniones(id_empresa),     # ← Sin caché
      fetch_nombres_productos_servicios(...),  # ← Sin caché
      fetch_contexto_negocio(id_empresa),      # ← Con TTLCache ✓
      fetch_preguntas_frecuentes(id_chatbot),  # ← ?
  )

  Irónicamente, schedule_validator._SCHEDULE_CACHE SÍ cachea el mismo endpoint OBTENER_HORARIO_REUNIONES, pero es una caché separada que no comparte datos
  con horario_reuniones.py. La misma API se llama dos veces con dos cachés distintas.

  ---
  3. Riesgos Técnicos

  ---
  🟡 MEDIO — Escalado horizontal imposible

  Todo el estado crítico es in-memory y per-proceso:

  ┌───────────────────────────┬──────┬─────────────────────────────┐
  │          Estado           │ Tipo │ Compartido entre instancias │
  ├───────────────────────────┼──────┼─────────────────────────────┤
  │ InMemorySaver (historial) │ RAM  │ ❌                          │
  ├───────────────────────────┼──────┼─────────────────────────────┤
  │ _SCHEDULE_CACHE           │ RAM  │ ❌                          │
  ├───────────────────────────┼──────┼─────────────────────────────┤
  │ _agent_cache              │ RAM  │ ❌                          │
  ├───────────────────────────┼──────┼─────────────────────────────┤
  │ _session_locks            │ RAM  │ ❌                          │
  ├───────────────────────────┼──────┼─────────────────────────────┤
  │ _contexto_cache           │ RAM  │ ❌                          │
  └───────────────────────────┴──────┴─────────────────────────────┘

  Con 2 instancias del agente, dos mensajes de la misma sesión pueden llegar a instancias distintas → el checkpointer no tiene el historial de conversación
  → el agente pierde contexto.

  ---
  🟡 MEDIO — Inconsistencia de timezone en ScheduleValidator.validate

  Archivo: services/schedule_validator.py:428 vs :509

  # validate() — datetime naïve (sin zona horaria)
  ahora = datetime.now()
  if fecha_hora_cita <= ahora:
      ...

  # recommendation() — datetime con zona horaria Perú
  now_peru = datetime.now(_ZONA_PERU)

  Si el servidor corre en UTC (contenedor estándar), datetime.now() devuelve UTC, no hora de Lima. Una cita para las 9:00 AM Lima podría rechazarse como
  "pasada" si el servidor marca 9:05 AM UTC (= 4:05 AM Lima). Bug silencioso con impacto directo al usuario.

  ---
  🟡 MEDIO — Duplicación de modelos Pydantic con schemas distintos

  config/models.py define ChatRequest y ChatResponse con session_id y metadata, pero main.py define sus propios ChatRequest y ChatResponse con url en lugar
  de metadata. Los de config/models.py no son usados. Deuda técnica que confunde.

  ---
  🟡 MEDIO — Sin rate limiting ni límite de tamaño de mensaje

  class ChatRequest(BaseModel):
      message: str  # ← Sin max_length

  Un mensaje de 1 MB pasa la validación, se inyecta como contenido al LLM y consume tokens al precio de OpenAI. No hay rate limiting por session_id ni por
  empresa_id.

  ---
  🟡 MEDIO — Doble validación redundante en BookingData

  Archivo: validation.py:132-152

  @model_validator(mode='after')
  def validate_booking(self):
      CustomerName(name=self.customer_name)   # ← Instancia Pydantic para validar
      ContactInfo(contact=self.customer_contact)
      BookingDateTime(date=self.date, time=self.time)

  Los campos ya fueron validados por sus @field_validator individuales cuando se construyó BookingData. El model_validator los re-valida creando 3
  instancias Pydantic innecesarias. Puede reemplazarse con lógica cruzada si fuera necesaria.

  ---
  🟡 MEDIO — Sin soporte streaming → TTFT alto

  El agente usa agent.ainvoke(...) que espera la respuesta completa antes de devolverla. Para respuestas largas del LLM (con razonamiento de tools), el
  usuario percibe latencia de 10-30s sin ningún feedback. LangGraph soporta astream_events para streaming token a token.

  ---
  4. Oportunidades de Optimización

  ---
  🟢 Granular httpx timeouts

  Archivo: services/http_client.py:26-29

  # Actual
  _client = httpx.AsyncClient(timeout=app_config.API_TIMEOUT, ...)

  # Recomendado
  _client = httpx.AsyncClient(
      timeout=httpx.Timeout(
          connect=5.0,
          read=app_config.API_TIMEOUT,
          write=5.0,
          pool=2.0,
      ),
      limits=httpx.Limits(
          max_connections=50,
          max_keepalive_connections=20,
          keepalive_expiry=30.0,
      ),
  )

  ---
  🟢 Catchall redundante en contexto_negocio.py

  Archivo: services/contexto_negocio.py:94

  # Actual — Exception ya incluye las anteriores
  except (httpx.TimeoutException, httpx.RequestError, Exception) as e:

  # Recomendado
  except Exception as e:

  ---
  🟢 Métricas de LLM no registran errores en el histograma

  track_chat_response y track_llm_call usan else: (solo registran latencia en éxito). Las llamadas fallidas no contribuyen al histograma de latencia,
  sesgando los percentiles hacia abajo. Considera usar finally: con un label de status.

  ---
  5. Recomendaciones Concretas

  ---
  R1 — Reemplazar InMemorySaver con TTL explícito o Redis

  # Opción 1: usar AsyncRedisSaver de langgraph-checkpoint-redis
  from langgraph.checkpoint.redis.aio import AsyncRedisSaver

  async def create_checkpointer():
      return AsyncRedisSaver.from_conn_string(app_config.REDIS_URL)

  # Opción 2: Saver custom con TTLCache (sin Redis)
  # Requiere implementar BaseSaver con evicción por TTL o LRU

  ---
  R2 — Unificar caché del horario

  Actualmente horario_reuniones.py llama a la API sin caché, y schedule_validator.py tiene su propio _SCHEDULE_CACHE. Propuesta: que fetch_horario_reuniones
   use el mismo _SCHEDULE_CACHE de schedule_validator, o extraer un HorarioCache compartido:

  # services/horario_cache.py (módulo nuevo centralizado)
  _horario_cache: TTLCache = TTLCache(
      maxsize=500,
      ttl=app_config.SCHEDULE_CACHE_TTL_MINUTES * 60
  )

  ---
  R3 — Corregir timezone en ScheduleValidator.validate

  # Cambiar en schedule_validator.py:428
  # ❌ ahora = datetime.now()
  # ✅
  ahora = datetime.now(_ZONA_PERU).replace(tzinfo=None)  # naive Lima

  ---
  R4 — Agregar retry con tenacity de forma uniforme

  from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

  @retry(
      stop=stop_after_attempt(3),
      wait=wait_exponential(multiplier=1, min=1, max=4),
      retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
      reraise=True,
  )
  async def _post_with_retry(client, url, json):
      response = await client.post(url, json=json)
      response.raise_for_status()
      return response.json()

  Centralizar en http_client.py para que todos los servicios lo usen.

  ---
  R5 — Añadir límite al mensaje de entrada

  class ChatRequest(BaseModel):
      message: str = Field(..., max_length=4096)
      session_id: int
      context: Dict[str, Any] | None = None

  ---
  R6 — Eliminar threading.Lock del caché de schedules

  # schedule_validator.py
  # Antes:
  _CACHE_LOCK = threading.Lock()
  def _get_cached_schedule(id_empresa):
      with _CACHE_LOCK:
          ...

  # Después (asyncio single-thread → dict ops son atómicas bajo GIL):
  def _get_cached_schedule(id_empresa):
      entry = _SCHEDULE_CACHE.get(id_empresa)
      if entry is None:
          return None
      schedule, timestamp = entry
      if datetime.now() - timestamp < timedelta(minutes=app_config.SCHEDULE_CACHE_TTL_MINUTES):
          return schedule
      del _SCHEDULE_CACHE[id_empresa]
      return None

  ---
  6. Nivel de Madurez

  ┌─────────────────────────────────┬────────────┬─────────────────────────────────────────────────────┐
  │            Dimensión            │ Puntuación │                        Notas                        │
  ├─────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Asincronismo                    │ 8/10       │ Buen uso de httpx, asyncio.gather, locks async      │
  ├─────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Gestión de memoria              │ 4/10       │ InMemorySaver sin bounds, cache inconsistente       │
  ├─────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Resiliencia HTTP                │ 5/10       │ Solo un servicio tiene retry                        │
  ├─────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Observabilidad                  │ 8/10       │ Prometheus completo, histogramas, gauges            │
  ├─────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Escalabilidad                   │ 3/10       │ Todo in-memory, sin Redis, sin sticky sessions      │
  ├─────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Seguridad de inputs             │ 6/10       │ Pydantic bien usado, pero sin max_length en message │
  ├─────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Separación de responsabilidades │ 8/10       │ Buena estructura de módulos                         │
  ├─────────────────────────────────┼────────────┼─────────────────────────────────────────────────────┤
  │ Correctness de timezone         │ 5/10       │ Bug datetime naïve en validate()                    │
  └─────────────────────────────────┴────────────┴─────────────────────────────────────────────────────┘

  Promedio global: 6.5 / 10

  El sistema es sólido para un MVP o deployment de instancia única. Para producción multi-instancia o carga alta, los ítems marcados 🔴 deben resolverse
  antes de escalar.