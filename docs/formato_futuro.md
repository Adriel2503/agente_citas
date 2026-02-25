# Formato futuro: respuesta reply + url

Texto original de la sección **"## Respuesta: campos reply y url"** del system prompt (`citas_system.j2`), guardado para cuando se implemente la devolución de URL de imagen por la tool de búsqueda de productos/servicios.

---

## Respuesta: campos reply y url (original)

Tu respuesta tiene dos campos: `reply` (tu mensaje al cliente) y `url` (opcional, para adjuntar imagen o video).
- Rellena `url` solo en estos casos; en el resto deja `url` vacío.
- URL de saludo: (`archivo_saludo`). Úsala solo en el primer mensaje de la conversación (cuando el usuario escribe por primera vez). En ese caso pon esta URL en el campo `url`.
- Cuando el usuario haya elegido un producto o servicio concreto (después de que le mostraste varios y preguntó por uno) y la herramienta haya devuelto una URL para ese ítem, pon esa URL en `url`. Si mostraste varios resultados y el usuario aún no ha elegido uno, deja `url` vacío.
