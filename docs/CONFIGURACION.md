# Guia de configuracion — Variables de entorno

Todas las variables se leen en `config/config.py` al iniciar el proceso. Si el valor es invalido (tipo incorrecto, fuera de rango), se usa el default sin lanzar excepcion.

Este documento explica **que hace cada variable, cuando cambiarla y que pasa si no la cambias**.

---

## Indice

1. [OpenAI y LLM](#1-openai-y-llm)
2. [Servidor](#2-servidor)
3. [Timeouts](#3-timeouts)
4. [HTTP — Retry y connection pool](#4-http--retry-y-connection-pool)
5. [Cache](#5-cache)
6. [Circuit breaker](#6-circuit-breaker)
7. [Logging](#7-logging)
8. [Zona horaria](#8-zona-horaria)
9. [Redis](#9-redis)
10. [URLs de APIs externas](#10-urls-de-apis-externas)
11. [Variables derivadas (no configurables)](#11-variables-derivadas-no-configurables)

---

## 1. OpenAI y LLM

### `api_key` (per-request)

La API key de OpenAI se recibe en cada request (`ChatRequest.api_key`) desde el gateway. No se configura como variable de entorno.

### `OPENAI_MODEL`

- **Default:** `gpt-4o-mini`
- **Rango:** cualquier modelo de OpenAI

El modelo de lenguaje que usa el agente. Se crea por tenant (cache key = `id_empresa` + hash de `api_key`).

**Cuando cambiarlo:** Si quieres usar un modelo mas capaz (`gpt-4o`) o mas barato (`gpt-4o-mini`).

**Ejemplo:** El agente falla en conversaciones complejas con muchos datos de productos:
```
OPENAI_MODEL=gpt-4o
```

### `OPENAI_TEMPERATURE`

- **Default:** `0.5`
- **Rango:** 0.0 a 2.0

Controla la aleatoriedad de las respuestas del LLM. Valores bajos (0.0-0.3) dan respuestas mas predecibles y repetitivas. Valores altos (0.8+) dan respuestas mas variadas pero con mayor riesgo de inventar informacion.

**Cuando cambiarlo:** Si el agente suena muy robotico (subir a 0.6-0.7) o si inventa horarios o datos que no existen (bajar a 0.2-0.3).

### `OPENAI_TIMEOUT`

- **Default:** `60` segundos
- **Rango:** 1 a 300

Timeout de la llamada al LLM (OpenAI API). Si el LLM no responde en este tiempo, la llamada falla.

**Cuando cambiarlo:** Si usas un modelo lento (como `o1`) que necesita mas tiempo para pensar. Para `gpt-4o-mini`, 60 segundos es mas que suficiente — tipicamente responde en 2-5 segundos.

### `MAX_TOKENS`

- **Default:** `2048`
- **Rango:** 1 a 128000

Maximo de tokens que el LLM puede generar en una sola respuesta. Una respuesta tipica del agente de citas usa 100-300 tokens.

**Cuando cambiarlo:** Generalmente no necesitas tocarlo. Solo si las respuestas del agente se cortan a la mitad (subir) o si quieres reducir costos limitando respuestas largas (bajar).

---

## 2. Servidor

### `SERVER_HOST`

- **Default:** `0.0.0.0`

Direccion donde escucha uvicorn. `0.0.0.0` acepta conexiones de cualquier IP (necesario en Docker). `127.0.0.1` solo acepta conexiones locales.

**Cuando cambiarlo:** Casi nunca. En Docker siempre debe ser `0.0.0.0`.

### `SERVER_PORT`

- **Default:** `8002`
- **Rango:** 1 a 65535

Puerto donde escucha el servidor. El gateway Go envia requests a este puerto.

**Cuando cambiarlo:** Si otro servicio ya usa el 8002, o si el equipo de infra requiere un puerto especifico.

---

## 3. Timeouts

Hay 3 timeouts que forman una cadena. Cada uno debe ser menor que el siguiente:

```
API_TIMEOUT (10s) < OPENAI_TIMEOUT (60s) < CHAT_TIMEOUT (120s)
```

### `API_TIMEOUT`

- **Default:** `10` segundos
- **Rango:** 1 a 120

Timeout de lectura (`read`) para las APIs externas de MaravIA (`ws_informacion_ia.php`, `ws_agendar_reunion.php`, etc.). Si la API no envia datos en este tiempo, httpx lanza `ReadTimeout` (un `TransportError`).

**Que pasa cuando vence:** El retry de tenacity reintenta (hasta `HTTP_RETRY_ATTEMPTS` veces). Si todos fallan, el circuit breaker registra el fallo.

**Cuando cambiarlo:**
- Las APIs de MaravIA tipicamente responden en 200-500ms. Con 10 segundos hay mucho margen.
- Subir si las APIs son lentas bajo carga (ej: consultas a Google Calendar que tardan).
- Bajar si prefieres fallar rapido y que el circuit breaker se active antes.

**Otros timeouts de httpx (hardcodeados, no configurables):**
- `connect=5.0s` — tiempo para establecer la conexion TCP
- `write=5.0s` — tiempo para enviar el body del request
- `pool=2.0s` — tiempo para obtener una conexion del pool (si todas estan en uso)

### `CHAT_TIMEOUT`

- **Default:** `120` segundos
- **Rango:** 30 a 300

Timeout total de un request a `POST /api/chat`. Incluye todo: crear agente (si cache miss), llamar al LLM, ejecutar tools, llamar APIs externas. Si se supera, el usuario recibe un mensaje de error amigable.

**Cuando cambiarlo:**
- Un flujo tipico (cache hit + 1 llamada LLM + 1 tool) toma 3-8 segundos.
- Un flujo largo (cache miss con 4 API calls + 2 llamadas LLM + validacion + booking) puede tomar 15-25 segundos.
- 120 segundos da margen para reintentos y APIs lentas. Solo bajar si el gateway Go tiene un timeout menor.

---

## 4. HTTP — Retry y connection pool

### `HTTP_RETRY_ATTEMPTS`

- **Default:** `3`
- **Rango:** 1 a 10

Cuantas veces reintentar un POST a las APIs de MaravIA cuando falla por error de red (`httpx.TransportError`: timeout, conexion rechazada, DNS failure, etc.).

**Que NO reintenta:** Errores HTTP (4xx, 5xx). Si la API responde con `500 Internal Server Error`, no se reintenta — el servidor esta funcionando, el error es de logica.

**Que NO usa retry:** `CREAR_EVENTO` (booking). Las escrituras no se reintentan porque no son idempotentes — un retry podria duplicar la cita en el calendario.

**Cuando cambiarlo:** Si las APIs son inestables y quieres mas oportunidades (subir a 4-5). Si prefieres fallar rapido (bajar a 1-2). Con 1, no hay retry.

### `HTTP_RETRY_WAIT_MIN` y `HTTP_RETRY_WAIT_MAX`

- **Default:** `1` y `4` segundos
- **Rango:** 0-30 y 1-60

Tiempo de espera entre reintentos usando **backoff exponencial**. El primer retry espera ~1s, el segundo ~2s, el tercero ~4s. Nunca espera menos que `WAIT_MIN` ni mas que `WAIT_MAX`.

**Ejemplo con defaults:** 3 intentos
```
Intento 1: falla → espera ~1s
Intento 2: falla → espera ~2s
Intento 3: falla → se rinde (total ~7s de espera + tiempo de cada intento)
```

**Cuando cambiarlos:** Si quieres retry mas agresivo (bajar `WAIT_MIN` a 0) o si las APIs necesitan tiempo para recuperarse (subir `WAIT_MAX` a 10).

### `HTTP_MAX_CONNECTIONS`

- **Default:** `50`
- **Rango:** 10 a 500

Maximo de **conexiones TCP simultaneas** que el pool de httpx puede tener abiertas hacia todas las APIs de MaravIA combinadas. Cada request HTTP activo (que esta esperando respuesta) ocupa una conexion.

**Que pasa si se llena:** El request 51 **no falla** — espera hasta que una conexion se libere (hasta `pool=2.0s`). Si no se libera en 2 segundos, falla con `PoolTimeout`.

**Ejemplo:**
- 20 empresas envian mensajes simultaneamente
- Cada request del agente puede hacer 1-4 llamadas HTTP a MaravIA (horarios, disponibilidad, productos, booking)
- En el peor caso: 20 empresas x 4 calls = 80 conexiones simultaneas → necesitarias subir a 100

**Cuando cambiarlo:**
- Con < 50 empresas activas simultaneas y el default de 50, es muy raro que se llene
- Si ves errores `PoolTimeout` en los logs o latencias altas sin que las APIs esten lentas, sube este valor
- No subir mas de lo necesario — cada conexion TCP consume memoria del OS y file descriptors

### `HTTP_MAX_KEEPALIVE`

- **Default:** `20`
- **Rango:** 5 a 200

De las `HTTP_MAX_CONNECTIONS` conexiones, cuantas mantener **abiertas en espera** (keep-alive) despues de usarse. Una conexion keep-alive se reutiliza en el proximo request sin repetir el handshake TCP — ahorra ~50-100ms por request.

**Como funciona:**
```
Trafico alto (30 requests simultaneos):
  → 20 conexiones keep-alive se reutilizan (rapido, sin handshake)
  → 10 conexiones nuevas se abren (handshake TCP, mas lento)
  → Total: 30 activas

Trafico baja:
  → Las 10 extra se cierran (despues de keepalive_expiry=30s)
  → Quedan 20 en espera para el proximo pico
```

**Cuando cambiarlo:**
- Si el trafico es constantemente alto (> 20 requests simultaneos), subir para reutilizar mas conexiones
- Siempre debe ser <= `HTTP_MAX_CONNECTIONS` (no tiene sentido mantener en espera mas de las que puedes abrir)
- Regla general: `HTTP_MAX_KEEPALIVE` = 30-50% de `HTTP_MAX_CONNECTIONS`

---

## 5. Cache

El agente usa 2 caches TTL independientes. Los datos del system prompt (horarios, contexto, FAQs, productos) no tienen cache propio — quedan cacheados dentro del agente compilado.

### `AGENT_CACHE_TTL_MINUTES`

- **Default:** `60` minutos
- **Rango:** 5 a 1440 (24 horas)

Cuanto tiempo vive un agente compilado en cache antes de recrearse. Recrear un agente implica:
1. 4 llamadas HTTP a MaravIA (horarios, productos, contexto, FAQs) — en paralelo, ~1-2s
2. Compilar el grafo LangGraph — ~ms, despreciable

**Que contiene un agente cacheado:** El grafo LangGraph con el system prompt renderizado (horarios de la empresa, lista de productos, contexto de negocio, FAQs). Si la empresa cambia su horario en el panel de MaravIA, el cambio se refleja cuando expire el cache.

**Cuando cambiarlo:**
- Bajar a 15-30 min si las empresas cambian horarios frecuentemente y necesitan verlo reflejado rapido
- Subir a 120-240 min si los datos cambian rara vez y quieres minimizar llamadas a las APIs
- **No bajar de 5 min** — recrear el agente en cada mensaje desperdicia llamadas HTTP y agrega 1-2s de latencia

### `AGENT_CACHE_MAXSIZE`

- **Default:** `500`
- **Rango:** 10 a 5000

Maximo de agentes compilados que caben en memoria al mismo tiempo. Un agente por empresa.

**Que pasa si se llena:** TTLCache usa politica **LRU** (Least Recently Used). Si hay 500 agentes y llega la empresa 501, se elimina el agente de la empresa que lleva mas tiempo sin enviar mensajes. La proxima vez que esa empresa envie un mensaje, su agente se recrea (~1-2s).

**En la practica:** Con < 50 empresas activas, los agentes expiran por TTL (60 min sin uso) mucho antes de que el cache se llene. El maxsize es una red de seguridad para el caso extremo.

**Cuando cambiarlo:**
- Si manejas 400+ empresas activas en la misma ventana de 60 minutos, sube a 1000+
- Si el container tiene poca RAM, baja a 100-200 (cada agente pesa poco, pero el system prompt con FAQs y productos puede ocupar varios KB)

**Efecto colateral:** `AGENT_CACHE_MAXSIZE` tambien controla los thresholds de limpieza de locks internos (ver seccion 11).

### `SEARCH_CACHE_TTL_MINUTES`

- **Default:** `15` minutos
- **Rango:** 1 a 60

Cuanto tiempo se cachean los resultados de busqueda de productos/servicios. La clave del cache es `(id_empresa, busqueda.lower())`.

**Ejemplo:** Si un prospecto pregunta "cuanto cuesta NovaX" y otro prospecto de la misma empresa pregunta lo mismo 10 minutos despues, el segundo obtiene la respuesta del cache sin llamar a la API.

**Cuando cambiarlo:**
- Bajar a 5 min si los precios o productos cambian frecuentemente
- Subir a 30-60 min si el catalogo es estable y quieres minimizar llamadas

### `SEARCH_CACHE_MAXSIZE`

- **Default:** `2000`
- **Rango:** 10 a 10000

Maximo de busquedas distintas cacheadas. Cada entrada es un par `(id_empresa, busqueda)`.

**Ejemplo de calculo:** 50 empresas x 20 busquedas distintas por empresa = 1000 entradas. Con 2000 hay margen de sobra.

**Cuando cambiarlo:** Solo si tienes muchas empresas con catalogos grandes y muchas busquedas distintas. Con < 50 empresas, el default sobra.

### `MAX_MESSAGES_HISTORY`

- **Default:** `20`
- **Rango:** 4 a 200

Cuantos mensajes ve el LLM en cada llamada. **No es la cantidad de mensajes que se guardan** — el checkpointer guarda todo. Solo limita la ventana que se envia al LLM para ahorrar tokens.

**Como funciona:** Si la conversacion tiene 50 mensajes, el middleware `_message_window` envia solo los ultimos 20 al LLM. El system prompt siempre se incluye (no cuenta contra el limite).

**Cuando cambiarlo:**
- Bajar a 10-15 si quieres ahorrar tokens (menos contexto por llamada)
- Subir a 30-50 si las conversaciones son largas y el agente "olvida" datos mencionados antes
- Con 4 (minimo): el agente solo ve el ultimo par de mensajes — muy agresivo, pierde contexto facilmente

---

## 6. Circuit breaker

El circuit breaker protege contra APIs externas caidas. Cuando una API falla repetidamente, el circuit se "abre" y las siguientes llamadas fallan inmediatamente sin tocar la red — evita timeouts innecesarios y cascadas de error.

### `CB_THRESHOLD`

- **Default:** `3`
- **Rango:** 1 a 20

Cuantos errores de red **consecutivos** (para la misma key) abren el circuit. Un solo exito resetea el contador a cero.

**Ejemplo con threshold=3:**
```
Request 1: TransportError → contador = 1 (circuit cerrado)
Request 2: TransportError → contador = 2 (circuit cerrado)
Request 3: TransportError → contador = 3 → CIRCUIT ABIERTO
Request 4: rechazado inmediatamente sin llamar a la API
...
(despues de CB_RESET_TTL segundos, el circuit se cierra automaticamente)
```

**Ejemplo con exito intermedio:**
```
Request 1: TransportError → contador = 1
Request 2: Exito          → contador = 0 (reset)
Request 3: TransportError → contador = 1
→ El circuit nunca se abre porque el exito resetea el contador
```

**Cuando cambiarlo:**
- Bajar a 1-2 si quieres que el circuit se abra rapido (agresivo, puede abrir por un error puntual)
- Subir a 5-10 si las APIs tienen errores esporadicos pero generalmente funcionan (tolerante)

### `CB_RESET_TTL`

- **Default:** `300` segundos (5 minutos)
- **Rango:** 60 a 3600

Cuanto tiempo permanece abierto el circuit antes de cerrarse automaticamente. Implementado via `TTLCache` — cuando expira la entrada, el contador desaparece y el circuit vuelve a cerrarse.

**Que pasa durante esos 5 minutos:**
- Todas las llamadas a esa API (para esa key/empresa) fallan inmediatamente con `RuntimeError`
- El servicio que usa la API muestra un fallback (ej: "No pude consultar disponibilidad, intenta en un momento")
- `/health` reporta el servicio como `degraded`
- Despues de 5 minutos, el circuit se cierra y se intenta llamar a la API de nuevo

**Cuando cambiarlo:**
- Bajar a 60-120s si las APIs se recuperan rapido y quieres reintentar antes
- Subir a 600-900s si las caidas son prolongadas y no quieres desperdiciar requests

### `CB_MAX_KEYS`

- **Default:** `500`
- **Rango:** 50 a 10000

Maximo de keys (empresas, chatbots, etc.) que cada circuit breaker puede rastrear simultaneamente. Cada circuit breaker tiene su propia instancia de `TTLCache(maxsize=CB_MAX_KEYS)`.

**Por que existe:** Cada CB rastrea fallos **por key**. `informacion_cb` tiene un contador separado para cada `id_empresa`. Si empresa 42 tiene problemas de red pero empresa 99 no, solo el circuit de la empresa 42 se abre.

**Que pasa si se llena:** TTLCache evicta la key mas vieja — esa empresa pierde su historial de fallos y empieza de cero. En la practica es inofensivo: lo peor que pasa es que una empresa con circuit abierto "se olvida" de sus fallos y hace una llamada mas antes de volver a abrir.

**Cuando cambiarlo:** Solo si manejas mas de ~400 empresas activas simultaneas. Con < 50 empresas, nunca se llena.

---

## 7. Logging

### `LOG_LEVEL`

- **Default:** `INFO`
- **Valores:** `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

Que tan detallados son los logs.

| Nivel | Que se ve |
|-------|-----------|
| `DEBUG` | Todo: payloads de API, mensajes del usuario, respuestas del LLM, estados de cache, contadores de CB |
| `INFO` | Startup, requests recibidos, respuestas generadas, bookings, errores de contexto |
| `WARNING` | Circuit breakers abiertos (threshold), respuestas fuera de formato, validaciones fallidas |
| `ERROR` | Errores de OpenAI, errores inesperados, timeouts |
| `CRITICAL` | API key invalida |

**En produccion:** Usar `INFO`. Los payloads de API en `DEBUG` pueden contener datos personales (nombres, emails, telefonos).

**Para debugging:** Usar `DEBUG` temporalmente. Los payloads de API solo se serializan si `DEBUG` esta activo (hay un guard `logger.isEnabledFor(logging.DEBUG)` para no penalizar produccion).

### `LOG_FILE`

- **Default:** `""` (vacio = solo stdout)

Ruta a un archivo donde guardar los logs ademas de stdout. Util si no tienes un sistema de log aggregation (como Loki o CloudWatch) y necesitas revisar logs historicos.

**Cuando usarlo:** En desarrollo local o si el container no tiene log rotation externo.

---

## 8. Zona horaria

### `TIMEZONE`

- **Default:** `America/Lima`
- **Valores:** cualquier key valida de `zoneinfo` (ej: `America/Bogota`, `America/Mexico_City`)

Se usa en dos lugares:
1. **System prompt:** El agente sabe que "hoy" es lunes 10 de marzo y que son las 3:00 PM en Lima
2. **Validacion de citas:** `ScheduleValidator` verifica que la fecha/hora no sea en el pasado comparando contra la hora actual en esta zona horaria

**Cuando cambiarlo:** Si el negocio opera en otra zona horaria. Todas las empresas del agente comparten la misma zona horaria.

---

## 9. Redis

### `REDIS_URL`

- **Default:** `""` (vacio = usar `InMemorySaver`)

URL de Redis para el checkpointer de conversaciones (`AsyncRedisSaver`). Si esta vacio o Redis no responde, el agente usa `InMemorySaver` como fallback automatico.

**Produccion (Easypanel):** `redis://memori_agentes:6379`

**Cuando cambiarlo:** Solo si el hostname o puerto de Redis cambia. Ver [CHECKPOINTER.md](design/CHECKPOINTER.md) para detalles de la arquitectura.

### `REDIS_CHECKPOINT_TTL_HOURS`

- **Default:** `24` horas
- **Rango:** 0 a 8760 (1 ano)

Cuanto tiempo persiste una conversacion en Redis. Despues del TTL, el checkpoint expira y el proximo mensaje del usuario inicia una conversacion nueva.

**Como funciona:** El TTL se convierte a minutos internamente (`ttl_hours * 60`) y se aplica por key individual — cada write tiene su propio EXPIRE.

**Cuando cambiarlo:**
- Bajar a 4-8h si las conversaciones de citas son cortas y no necesitan contexto del dia anterior
- Subir a 48-72h si los prospectos retoman conversaciones despues de un dia
- `0` = sin expiracion (no recomendado, Redis crece sin limite)

### `MAX_CONCURRENT_AGENT`

- **Default:** `50`
- **Rango:** 5 a 500

Maximo de invocaciones concurrentes al agente (LLM + tools). Implementado como `asyncio.Semaphore` — el request 51 espera hasta que uno de los 50 activos termine.

**Que pasa si se llena:** El request queda en espera. Si el `CHAT_TIMEOUT` vence antes de que se libere un slot, el usuario recibe un mensaje de error.

**Cuando cambiarlo:**
- Con < 50 empresas activas, el default es suficiente (1 request por empresa en paralelo)
- Subir si tienes muchas empresas con alto trafico simultaneo
- Bajar si el servidor tiene pocos recursos y quieres proteger la memoria/CPU

---

## 10. URLs de APIs externas

### `API_CALENDAR_URL`

- **Default:** `https://api.maravia.pe/servicio/ws_calendario.php`

Endpoint para crear eventos en el calendario (`CREAR_EVENTO`). Usado por `scheduling/booking.py`.

### `API_AGENDAR_REUNION_URL`

- **Default:** `https://api.maravia.pe/servicio/ws_agendar_reunion.php`

Endpoint para consultar disponibilidad y sugerir horarios (`CONSULTAR_DISPONIBILIDAD`, `SUGERIR_HORARIOS`). Usado por `scheduling/availability_client.py` y `scheduling/schedule_recommender.py`.

### `API_INFORMACION_URL`

- **Default:** `https://api.maravia.pe/servicio/ws_informacion_ia.php`

Endpoint para datos de la empresa: horarios, contexto de negocio, productos, servicios. Usado por todos los modulos de `prompt_data/` y `busqueda_productos.py`.

### `API_PREGUNTAS_FRECUENTES_URL`

- **Default:** `https://api.maravia.pe/servicio/n8n/ws_preguntas_frecuentes.php`

Endpoint para FAQs del chatbot. Usado por `prompt_data/preguntas_frecuentes.py`.

**Cuando cambiar las URLs:** Si el backend de MaravIA se mueve a otro dominio, o si quieres apuntar a un entorno de staging/testing.

---

## 11. Variables derivadas (no configurables)

Estas no son variables de entorno. Se calculan automaticamente a partir de otras variables. Se documentan aqui para que se entienda de donde salen los numeros.

### `_SESSION_LOCKS_CLEANUP_THRESHOLD`

- **Valor:** `AGENT_CACHE_MAXSIZE` (default 500)
- **Definido en:** `agent/runtime/_cache.py`

Cada sesion de WhatsApp crea un `asyncio.Lock` para evitar que dos mensajes del mismo usuario se procesen en paralelo (doble-click, reintento del gateway). Estos locks se acumulan porque los `session_id` de WhatsApp son permanentes.

**Que hace el threshold:** Cuando se acumulan mas de 500 locks, `_cleanup_stale_session_locks()` recorre el dict y elimina los que **no estan bloqueados** en ese momento. Un lock no bloqueado significa que esa sesion no tiene un request en curso — es seguro eliminarlo.

**Por que escala con `AGENT_CACHE_MAXSIZE`:** Ambos crecen con la cantidad de empresas/sesiones. Si subes el cache a 1000, el threshold sube a 1000. Si lo bajas a 100, la limpieza se activa antes.

### `_LOCKS_CLEANUP_THRESHOLD`

- **Valor:** `AGENT_CACHE_MAXSIZE * 1.5` (default 750)
- **Definido en:** `agent/runtime/_cache.py`

Mismo concepto pero para los locks de **creacion de agentes** (uno por empresa).

**El problema que resuelve:** El cache de agentes tiene `maxsize=500`. Cuando se llena, TTLCache evicta el agente mas viejo para hacer espacio. Pero el lock de esa empresa queda en un dict separado que no tiene maxsize. Si entran y salen 1000 empresas, el dict de locks crece a 1000 aunque el cache nunca pasa de 500.

**Como funciona la limpieza:**
```
1. Cache tiene agentes para empresas [1, 2, 3, ..., 500]
2. Dict de locks tiene locks para empresas [1, 2, 3, ..., 750]
3. Locks 501-750 son "huerfanos" — su agente ya expiro del cache
4. Cuando el dict pasa de 750, se eliminan los huerfanos no bloqueados
5. Despues de la limpieza: locks ≈ 500 (los que tienen agente en cache)
```

**Por que 1.5x y no 1.0x:** Para no ejecutar la limpieza en cada request. Si el threshold fuera 500 (= maxsize), cada empresa nueva que entra y otra sale dispararia la limpieza. Con 750 hay un colchon de 250 locks huerfanos antes de activar el barrido — un poco mas de memoria a cambio de no ejecutar la limpieza constantemente.

---

## Ejemplo de configuracion para distintos escenarios

### Escenario 1: Pocas empresas (< 20), APIs estables

Los defaults funcionan bien. Solo necesitas configurar lo esencial:

```env
# api_key viene per-request desde el gateway
OPENAI_MODEL=gpt-4o-mini
LOG_LEVEL=INFO
```

### Escenario 2: Muchas empresas (200+), trafico alto

```env
# api_key viene per-request desde el gateway
OPENAI_MODEL=gpt-4o-mini

# Mas espacio para agentes y conexiones
AGENT_CACHE_MAXSIZE=1000
HTTP_MAX_CONNECTIONS=100
HTTP_MAX_KEEPALIVE=50

# Mas tolerancia en circuit breaker
CB_THRESHOLD=5
CB_MAX_KEYS=1000
```

### Escenario 3: APIs de MaravIA inestables

```env
# api_key viene per-request desde el gateway

# Mas reintentos y mas tiempo de espera
HTTP_RETRY_ATTEMPTS=5
HTTP_RETRY_WAIT_MAX=8

# Circuit breaker rapido y reset corto
CB_THRESHOLD=2
CB_RESET_TTL=120
```

### Escenario 4: Debugging de un problema

```env
LOG_LEVEL=DEBUG
LOG_FILE=/tmp/agent_citas_debug.log
```

Revisar el archivo despues con `grep "[TOOL]" /tmp/agent_citas_debug.log` o `grep "[CB:" /tmp/agent_citas_debug.log`.
