# 🚀 Backend Django - Microservicio REST API

Microservicio Django REST Framework para gestión de **Personas** y **Productos**, con PostgreSQL (Supabase), Docker, autenticación JWT y documentación Swagger.

## 🎯 Estado del Proyecto

✅ **Implementado según Desafío:**
- ✅ CRUD completo Personas y Productos
- ✅ Filtros avanzados (email, last_name, sku, price_min/max, búsqueda)
- ✅ Paginación (20 items por página)
- ✅ Autenticación JWT (login/refresh)
- ✅ Documentación Swagger/OpenAPI
- ✅ Health checks (/healthz, /readyz, /metrics)
- ✅ Logs estructurados JSON
- ✅ Docker multi-stage + docker-compose
- ✅ Settings por entorno (dev/prod)
- ✅ Tests con pytest (37+ tests)
- ✅ Código formateado (black) y linted (ruff)

---

## 🚀 Inicio Rápido

### 1. Setup Local

```bash
# Activar entorno virtual
# Windows
back\Scripts\activate
# Linux/Mac
source back/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar .env (copiar de .env.example y ajustar DATABASE_URL)
cp .env.example .env

# Aplicar migraciones Django (solo tablas de Django, no persons/products)
python manage.py migrate

# Crear superusuario para JWT (opcional pero recomendado)
python manage.py createsuperuser

# Ejecutar servidor
python manage.py runserver
```

El servidor estará disponible en: **http://localhost:8000**

### 2. Setup Docker

```bash
# Construir y levantar
docker-compose up --build

# Ver logs
docker-compose logs -f web

# Detener
docker-compose down
```

**Nota:** Requiere `.env` configurado con `DATABASE_URL` de Supabase.

---

## 🌐 URLs Directas para Probar (Abrir en Navegador)

Una vez que el servidor esté corriendo en `http://localhost:8000`:

### 📖 Documentación Interactiva
- **Swagger UI:** http://localhost:8000/api/schema/swagger-ui/
  - Interfaz visual para probar todos los endpoints
  - Incluye autenticación JWT
  - Permite hacer requests directamente desde el navegador

- **ReDoc:** http://localhost:8000/api/schema/redoc/
  - Documentación alternativa estilo ReDoc

- **OpenAPI Schema (JSON):** http://localhost:8000/api/schema/
  - Schema OpenAPI 3.0 en formato JSON

### 🏥 Health Checks
- **Liveness:** http://localhost:8000/healthz
- **Readiness:** http://localhost:8000/readyz
- **Métricas Prometheus:** http://localhost:8000/metrics

### 📋 Listados (GET - No requiere autenticación)
- **Personas:** http://localhost:8000/api/v1/persons/
- **Productos:** http://localhost:8000/api/v1/products/

---

## 🧪 Guía de Pruebas - Endpoints según Desafío

### 📌 Base URL
```bash
BASE_URL="http://localhost:8000"
```

### 🔐 Paso 1: Autenticación JWT (Opcional pero recomendado)

Primero, crea un usuario con Django:

```bash
python manage.py createsuperuser
# Ingresa username, email y password
```

Luego, obtén el token JWT:

```bash
# Login y obtener tokens
curl -X POST $BASE_URL/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "tu_usuario",
    "password": "tu_password"
  }'
```

**Respuesta:**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Guarda el token `access` en una variable para usar en los siguientes comandos:**
```bash
TOKEN="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
```

---

### 👤 PERSONAS - CRUD Completo

#### ✅ 1. Crear Persona (POST) - **Requiere autenticación**

```bash
curl -X POST $BASE_URL/api/v1/persons/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "first_name": "Juan",
    "last_name": "Pérez",
    "email": "juan.perez@example.com"
  }'
```

**Respuesta esperada:** `201 Created`
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user": null,
  "first_name": "Juan",
  "last_name": "Pérez",
  "email": "juan.perez@example.com",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "is_active": true
}
```

**Guarda el ID para usar después:**
```bash
PERSON_ID="550e8400-e29b-41d4-a716-446655440000"
```

#### ✅ 2. Listar Personas (GET) - **Público (no requiere auth)**

```bash
# Listar todas
curl $BASE_URL/api/v1/persons/
```

**Respuesta esperada:** `200 OK` con paginación
```json
{
  "count": 50,
  "next": "http://localhost:8000/api/v1/persons/?page=2",
  "previous": null,
  "results": [...]
}
```

#### ✅ 3. Filtros de Personas - **Según Desafío**

**Filtro por email (parcial, case-insensitive):**
```bash
curl "$BASE_URL/api/v1/persons/?email=juan"
```

**Filtro por last_name (parcial, case-insensitive):**
```bash
curl "$BASE_URL/api/v1/persons/?last_name=Pérez"
```

**Combinar filtros:**
```bash
curl "$BASE_URL/api/v1/persons/?email=example&last_name=Pérez"
```

#### ✅ 4. Ordenamiento por created_at - **Según Desafío**

**Ascendente (más antiguos primero):**
```bash
curl "$BASE_URL/api/v1/persons/?ordering=created_at"
```

**Descendente (más recientes primero) - Default:**
```bash
curl "$BASE_URL/api/v1/persons/?ordering=-created_at"
```

#### ✅ 5. Paginación - **Según Desafío**

```bash
# Página 1 (default)
curl "$BASE_URL/api/v1/persons/"

# Página 2
curl "$BASE_URL/api/v1/persons/?page=2"

# Página 3
curl "$BASE_URL/api/v1/persons/?page=3"
```

Cada página contiene **20 items** (configurado en `PAGE_SIZE=20`).

#### ✅ 6. Obtener Persona por ID (GET) - **Público**

```bash
curl "$BASE_URL/api/v1/persons/$PERSON_ID/"
```

#### ✅ 7. Actualizar Persona (PUT) - **Requiere autenticación**

Actualización completa (debes enviar todos los campos):

```bash
curl -X PUT "$BASE_URL/api/v1/persons/$PERSON_ID/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "first_name": "Juan Carlos",
    "last_name": "Pérez González",
    "email": "juan.carlos@example.com"
  }'
```

#### ✅ 8. Actualización Parcial (PATCH) - **Requiere autenticación**

Actualiza solo los campos enviados:

```bash
curl -X PATCH "$BASE_URL/api/v1/persons/$PERSON_ID/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "email": "nuevo.email@example.com"
  }'
```

#### ✅ 9. Eliminar Persona (DELETE) - **Requiere autenticación**

**Soft delete** (marca `is_active=False`, no elimina físicamente):

```bash
curl -X DELETE "$BASE_URL/api/v1/persons/$PERSON_ID/" \
  -H "Authorization: Bearer $TOKEN"
```

**Respuesta esperada:** `204 No Content`

**Verificar que no aparece en listado:**
```bash
curl "$BASE_URL/api/v1/persons/$PERSON_ID/"
# Debería retornar 404 o la persona con is_active=false
```

---

### 🏷️ PRODUCTOS - CRUD Completo

#### ✅ 1. Crear Producto (POST) - **Requiere autenticación**

```bash
curl -X POST $BASE_URL/api/v1/products/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Laptop Dell XPS 15",
    "sku": "LAP-DEL-001",
    "price": "1299.99",
    "owner": "'$PERSON_ID'"
  }'
```

**Respuesta esperada:** `201 Created`
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "name": "Laptop Dell XPS 15",
  "sku": "LAP-DEL-001",
  "price": "1299.99",
  "owner": "550e8400-e29b-41d4-a716-446655440000",
  "owner_details": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "first_name": "Juan",
    "last_name": "Pérez",
    "email": "juan.perez@example.com"
  },
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "is_active": true
}
```

**Guarda el ID del producto:**
```bash
PRODUCT_ID="660e8400-e29b-41d4-a716-446655440000"
```

**Crear producto sin owner (opcional según desafío):**
```bash
curl -X POST $BASE_URL/api/v1/products/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Monitor LG 27\"",
    "sku": "MON-LG-001",
    "price": "349.50",
    "owner": null
  }'
```

#### ✅ 2. Listar Productos (GET) - **Público**

```bash
curl $BASE_URL/api/v1/products/
```

#### ✅ 3. Filtros de Productos - **Según Desafío**

**Filtro por SKU (exacto, case-insensitive):**
```bash
curl "$BASE_URL/api/v1/products/?sku=LAP-DEL-001"
```

**Filtro por precio mínimo (price_min):**
```bash
curl "$BASE_URL/api/v1/products/?price_min=500"
```

**Filtro por precio máximo (price_max):**
```bash
curl "$BASE_URL/api/v1/products/?price_max=1000"
```

**Filtro por rango de precios (price_min + price_max):**
```bash
curl "$BASE_URL/api/v1/products/?price_min=100&price_max=500"
```

**Búsqueda por nombre (parámetro q):**
```bash
curl "$BASE_URL/api/v1/products/?q=Laptop"
```

**Combinar múltiples filtros:**
```bash
curl "$BASE_URL/api/v1/products/?price_min=500&price_max=1500&q=Dell&ordering=price"
```

#### ✅ 4. Ordenamiento - **Según Desafío**

**Por precio ascendente:**
```bash
curl "$BASE_URL/api/v1/products/?ordering=price"
```

**Por precio descendente:**
```bash
curl "$BASE_URL/api/v1/products/?ordering=-price"
```

**Por created_at descendente (default):**
```bash
curl "$BASE_URL/api/v1/products/?ordering=-created_at"
```

#### ✅ 5. Paginación - **Según Desafío**

```bash
# Página 1
curl "$BASE_URL/api/v1/products/"

# Página 2
curl "$BASE_URL/api/v1/products/?page=2"
```

#### ✅ 6. Obtener Producto por ID (GET) - **Público**

```bash
curl "$BASE_URL/api/v1/products/$PRODUCT_ID/"
```

**Nota:** Incluye `owner_details` con información completa del owner.

#### ✅ 7. Actualizar Producto (PUT) - **Requiere autenticación**

```bash
curl -X PUT "$BASE_URL/api/v1/products/$PRODUCT_ID/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Laptop Dell XPS 15 Updated",
    "sku": "LAP-DEL-002",
    "price": "1399.99",
    "owner": "'$PERSON_ID'"
  }'
```

#### ✅ 8. Actualización Parcial (PATCH) - **Requiere autenticación**

```bash
curl -X PATCH "$BASE_URL/api/v1/products/$PRODUCT_ID/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "price": "1199.99"
  }'
```

#### ✅ 9. Eliminar Producto (DELETE) - **Requiere autenticación**

**Soft delete:**

```bash
curl -X DELETE "$BASE_URL/api/v1/products/$PRODUCT_ID/" \
  -H "Authorization: Bearer $TOKEN"
```

---

### 🏥 Health Checks - **Según Desafío**

#### ✅ GET /healthz - Liveness Probe

```bash
curl $BASE_URL/healthz
```

**Respuesta esperada:** `200 OK`
```json
{
  "status": "ok"
}
```

#### ✅ GET /readyz - Readiness Probe (verifica DB)

```bash
curl $BASE_URL/readyz
```

**Respuesta esperada:** `200 OK`
```json
{
  "status": "ready",
  "database": "connected"
}
```

**Si DB no está conectada:** `503 Service Unavailable`
```json
{
  "status": "not ready",
  "database": "disconnected"
}
```

#### ✅ GET /metrics - Métricas Prometheus

```bash
curl $BASE_URL/metrics
```

**Respuesta esperada:** `200 OK` (text/plain)
```
# HELP django_persons_total Total number of active persons
# TYPE django_persons_total gauge
django_persons_total 15

# HELP django_products_total Total number of active products
# TYPE django_products_total gauge
django_products_total 25

# HELP django_database_status Database connection status (1=connected, 0=disconnected)
# TYPE django_database_status gauge
django_database_status 1
```

---

### 🔄 Refrescar Token JWT

Cuando el access token expire (por defecto 60 minutos):

```bash
curl -X POST $BASE_URL/api/v1/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d '{
    "refresh": "tu-refresh-token-aqui"
  }'
```

**Respuesta:**
```json
{
  "access": "nuevo-access-token..."
}
```

---

## ✅ Checklist de Pruebas según Desafío

Marca cada funcionalidad después de probarla:

### Requisitos Funcionales (MVP)

#### Personas
- [ ] ✅ POST /api/v1/persons/ - Crear persona
- [ ] ✅ GET /api/v1/persons/ - Listar personas
- [ ] ✅ GET /api/v1/persons/{id}/ - Obtener persona
- [ ] ✅ PUT /api/v1/persons/{id}/ - Actualizar (completo)
- [ ] ✅ PATCH /api/v1/persons/{id}/ - Actualizar (parcial)
- [ ] ✅ DELETE /api/v1/persons/{id}/ - Eliminar (soft delete)
- [ ] ✅ Filtro por email: `?email=valor`
- [ ] ✅ Filtro por last_name: `?last_name=valor`
- [ ] ✅ Ordenamiento: `?ordering=created_at` o `?ordering=-created_at`
- [ ] ✅ Paginación: `?page=2` (20 items por página)

#### Productos
- [ ] ✅ POST /api/v1/products/ - Crear producto
- [ ] ✅ GET /api/v1/products/ - Listar productos
- [ ] ✅ GET /api/v1/products/{id}/ - Obtener producto
- [ ] ✅ PUT /api/v1/products/{id}/ - Actualizar (completo)
- [ ] ✅ PATCH /api/v1/products/{id}/ - Actualizar (parcial)
- [ ] ✅ DELETE /api/v1/products/{id}/ - Eliminar (soft delete)
- [ ] ✅ Filtro por sku: `?sku=valor`
- [ ] ✅ Filtro por precio mínimo: `?price_min=100`
- [ ] ✅ Filtro por precio máximo: `?price_max=500`
- [ ] ✅ Búsqueda por nombre: `?q=valor`
- [ ] ✅ Ordenamiento: `?ordering=price` o `?ordering=-price`
- [ ] ✅ Paginación: `?page=2` (20 items por página)
- [ ] ✅ Owner opcional (puede ser null)

#### Funcionalidades Extra
- [ ] ✅ POST /api/v1/auth/login/ - Autenticación JWT
- [ ] ✅ POST /api/v1/auth/refresh/ - Refrescar token
- [ ] ✅ Protección endpoints escritura (POST/PUT/PATCH/DELETE requieren auth)
- [ ] ✅ Documentación Swagger: `/api/schema/swagger-ui/`
- [ ] ✅ Documentación ReDoc: `/api/schema/redoc/`

#### Requisitos No Funcionales
- [ ] ✅ GET /healthz - Health check (liveness)
- [ ] ✅ GET /readyz - Readiness (verifica DB)
- [ ] ✅ GET /metrics - Métricas Prometheus
- [ ] ✅ Logs estructurados (formato JSON)
- [ ] ✅ Nivel de log configurable (LOG_LEVEL env)

---

## 📝 Script de Prueba Completo (Bash)

Copia y pega este script para probar todos los endpoints:

```bash
#!/bin/bash

BASE_URL="http://localhost:8000"

echo "🔐 1. Login JWT..."
LOGIN_RESPONSE=$(curl -s -X POST $BASE_URL/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "tu_usuario", "password": "tu_password"}')

TOKEN=$(echo $LOGIN_RESPONSE | grep -o '"access":"[^"]*' | cut -d'"' -f4)
echo "Token obtenido: ${TOKEN:0:50}..."

echo "👤 2. Crear Persona..."
PERSON_RESPONSE=$(curl -s -X POST $BASE_URL/api/v1/persons/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"first_name": "Test", "last_name": "User", "email": "test@example.com"}')
PERSON_ID=$(echo $PERSON_RESPONSE | grep -o '"id":"[^"]*' | cut -d'"' -f4)
echo "Persona creada: $PERSON_ID"

echo "📋 3. Listar Personas..."
curl -s "$BASE_URL/api/v1/persons/" | head -20

echo "🔍 4. Filtrar por email..."
curl -s "$BASE_URL/api/v1/persons/?email=test"

echo "🏷️ 5. Crear Producto..."
PRODUCT_RESPONSE=$(curl -s -X POST $BASE_URL/api/v1/products/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"name\": \"Test Product\", \"sku\": \"TEST-001\", \"price\": \"99.99\", \"owner\": \"$PERSON_ID\"}")
PRODUCT_ID=$(echo $PRODUCT_RESPONSE | grep -o '"id":"[^"]*' | cut -d'"' -f4)
echo "Producto creado: $PRODUCT_ID"

echo "📋 6. Listar Productos..."
curl -s "$BASE_URL/api/v1/products/" | head -20

echo "🔍 7. Filtrar por rango de precios..."
curl -s "$BASE_URL/api/v1/products/?price_min=50&price_max=200"

echo "🔍 8. Búsqueda por nombre..."
curl -s "$BASE_URL/api/v1/products/?q=Test"

echo "🏥 9. Health checks..."
curl -s "$BASE_URL/healthz"
curl -s "$BASE_URL/readyz"
curl -s "$BASE_URL/metrics" | head -10

echo "✅ Pruebas completadas!"
```

---

## 🐳 Docker - Setup y Pruebas

### Construir y Ejecutar

```bash
# Construir imagen
docker build -t backend-django .

# O usar docker-compose
docker-compose up --build
```

### Probar Endpoints desde Host

Si usas Docker, los endpoints están disponibles en `http://localhost:8000` (puerto mapeado).

```bash
# Desde tu máquina local
curl http://localhost:8000/healthz
curl http://localhost:8000/api/v1/persons/
```

### Ver Logs

```bash
# Docker Compose
docker-compose logs -f web

# Docker manual
docker logs -f backend_web
```

---

## 📊 Documentación Interactiva

La forma más fácil de probar la API es usar **Swagger UI**:

1. Ejecuta el servidor: `python manage.py runserver`
2. Abre en navegador: http://localhost:8000/api/schema/swagger-ui/
3. Click en **"Authorize"** (botón verde) e ingresa tu token JWT
4. Prueba cualquier endpoint directamente desde el navegador

**Ventajas de Swagger:**
- ✅ No necesitas curl
- ✅ Interfaz visual
- ✅ Auto-generado desde el código
- ✅ Incluye esquemas de request/response
- ✅ Permite autenticación JWT directa

---

## ⚙️ Configuración

### Variables de Entorno (.env)

```env
# Django
DEBUG=True
SECRET_KEY=tu-secret-key-super-segura
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (Supabase o PostgreSQL)
DATABASE_URL=postgresql://usuario:password@host:5432/database

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:4200,http://localhost:3000

# JWT
JWT_ACCESS_TTL_MIN=60

# Logs
LOG_LEVEL=INFO
```

### Crear Tablas en Supabase

1. Ve a Supabase SQL Editor
2. Ejecuta el contenido de `create_tables.sql`
3. Copia tu `DATABASE_URL` a `.env`

---

## 🧪 Tests Automatizados

```bash
# Ejecutar todos los tests
pytest

# Con cobertura
pytest --cov=. --cov-report=term-missing --cov-report=html

# Test específico
pytest persons/tests.py::TestPersonAPI::test_create_person

# Verbose
pytest -v
```

**Cobertura objetivo:** >65%

Ver reporte HTML: `htmlcov/index.html`

---

## 🔍 Troubleshooting

### Error: "401 Unauthorized" en POST/PUT/DELETE

**Solución:** Necesitas autenticarte. Obtén un token JWT primero:
```bash
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "usuario", "password": "password"}'
```

### Error: "403 Forbidden"

**Solución:** Tu token puede haber expirado. Refréscalo:
```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh": "tu-refresh-token"}'
```

### Error: "503 Service Unavailable" en /readyz

**Solución:** La base de datos no está conectada. Verifica:
- `DATABASE_URL` en `.env` es correcta
- Supabase está accesible
- Credenciales son correctas

### Error: "Email ya está registrado"

**Solución:** El email debe ser único entre personas activas. Intenta con otro email o elimina la persona existente primero.

### Error: "SKU ya existe"

**Solución:** El SKU debe ser único entre productos activos. Usa otro SKU.

---

## 📚 Recursos

- **Swagger UI:** http://localhost:8000/api/schema/swagger-ui/
- **ReDoc:** http://localhost:8000/api/schema/redoc/
- **Healthz:** http://localhost:8000/healthz
- **Readyz:** http://localhost:8000/readyz
- **Metrics:** http://localhost:8000/metrics

---

## 🎯 Resumen de Endpoints

| Método | Endpoint | Auth | Descripción |
|--------|----------|------|-------------|
| GET | `/healthz` | ❌ | Liveness probe |
| GET | `/readyz` | ❌ | Readiness probe (DB) |
| GET | `/metrics` | ❌ | Métricas Prometheus |
| POST | `/api/v1/auth/login/` | ❌ | Login JWT |
| POST | `/api/v1/auth/refresh/` | ❌ | Refrescar token |
| GET | `/api/v1/persons/` | ❌ | Listar personas |
| POST | `/api/v1/persons/` | ✅ | Crear persona |
| GET | `/api/v1/persons/{id}/` | ❌ | Obtener persona |
| PUT | `/api/v1/persons/{id}/` | ✅ | Actualizar persona |
| PATCH | `/api/v1/persons/{id}/` | ✅ | Actualizar parcial |
| DELETE | `/api/v1/persons/{id}/` | ✅ | Eliminar persona |
| GET | `/api/v1/products/` | ❌ | Listar productos |
| POST | `/api/v1/products/` | ✅ | Crear producto |
| GET | `/api/v1/products/{id}/` | ❌ | Obtener producto |
| PUT | `/api/v1/products/{id}/` | ✅ | Actualizar producto |
| PATCH | `/api/v1/products/{id}/` | ✅ | Actualizar parcial |
| DELETE | `/api/v1/products/{id}/` | ✅ | Eliminar producto |
| GET | `/api/schema/swagger-ui/` | ❌ | Swagger UI |
| GET | `/api/schema/redoc/` | ❌ | ReDoc |

**Leyenda:**
- ✅ = Requiere autenticación JWT (Bearer token)
- ❌ = Público (no requiere autenticación)

---

**¡Listo para probar! 🚀**

Empieza abriendo Swagger UI en http://localhost:8000/api/schema/swagger-ui/ y prueba los endpoints desde allí.
