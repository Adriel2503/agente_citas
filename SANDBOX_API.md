# Sandbox API

**Base URL:** `/api/sandbox`

---

## Configuración

### GET `/api/sandbox/configuracion`
- **Request:** —
- **Response:** `{ data: [{ id, url_bot_service, canal }] }`

### POST `/api/sandbox/configuracion`
- **Request Body:** `{ url_bot_service, canal }`
- **Response:** `{ data: [{ id, url_bot_service, canal }] }`

### PUT `/api/sandbox/configuracion/:id`
- **Request Body:** `{ url_bot_service, canal }`
- **Response:** `{ data: [{ id, url_bot_service, canal }] }`

---

## Chats

### GET `/api/sandbox/chats?canal=whatsapp`
- **Request:** query param `canal` (requerido)
- **Response:** `{ data: [{ id, channel, fecha_hora }] }`

### POST `/api/sandbox/chats`
- **Request Body:** `{ channel }`
- **Response:** `{ data: [{ id, channel }] }`

### DELETE `/api/sandbox/chats/:id`
- **Request:** param `id`
- **Response:** `{ message: "Chat eliminado exitosamente" }`

---

## Mensajes

### GET `/api/sandbox/chats/:idChat/messages`
- **Request:** param `idChat`
- **Response:** `{ data: [{ id, direction, message, type, url, id_chat_sandbox, fecha_hora }] }`

### POST `/api/sandbox/chats/:idChat/messages`
- **Request Body:** `{ message, type?, url? }`
- **Response:** `{ data: [{ id, id_chat_sandbox, message }] }`

---

## Webhook (usado por el Bot)

### POST `/api/sandbox/reply`
- **Request Body:** `{ chatid, reply, type?, url? }`
- **Response:** `{ data: [{ id, id_chat_sandbox, reply }] }`
