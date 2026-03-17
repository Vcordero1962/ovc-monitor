# Manual del Administrador — OVC Gestor
## Solo lectura para el administrador — sin acceso técnico requerido

---

## ¿Qué es tu rol?

Eres el administrador del servicio OVC. Tu trabajo es:
- Confirmar pagos de suscriptores
- Activar y desactivar planes
- Enviar comunicados a los suscriptores
- Revisar estadísticas del servicio

**No necesitas saber programar. Todo se hace desde Telegram.**

---

## ¿Cómo accedo?

Busca en Telegram: **@ovc_gestor_bot**

Escríbele directamente. Solo tú puedes usar los comandos de administrador.

---

## Comandos disponibles

### 📊 Ver estadísticas
```
/admin_stats
```
Te muestra:
- Total de usuarios registrados
- Cuántos tienen plan Directo y cuántos Premium
- Ingresos estimados del mes actual
- Cuántas suscripciones vencen en 7 días

---

### 📋 Ver lista de suscriptores activos
```
/admin_listar
```
Te muestra los primeros 30 suscriptores activos con:
- Su alias de Telegram (@usuario)
- Su plan (Directo o Premium)
- Fecha en que vence su suscripción

---

### ✅ Activar una suscripción (después de recibir el pago)
```
/admin_activar @usuario plan dias precio metodo
```

**Ejemplos:**
```
/admin_activar @juanperez directo 90 15 zelle
/admin_activar @maria_cu premium 90 25 paypal
/admin_activar @carlos directo 90
```

- `@usuario` → El alias Telegram de quien pagó
- `plan` → `directo` o `premium`
- `dias` → Cuántos días dura (normalmente 90)
- `precio` → Cuánto pagó en USD (opcional)
- `metodo` → Cómo pagó: zelle, paypal, etc. (opcional)

El bot notifica automáticamente al usuario que su plan está activo.

---

### 🚫 Desactivar una suscripción
```
/admin_desactivar @usuario
```

Úsalo si:
- El pago fue rechazado o fraudulento
- El usuario solicita cancelación con reembolso
- Hay abuso del servicio

---

### ⚠️ Ver suscripciones próximas a vencer
```
/admin_expiran
/admin_expiran 14
```

Sin número: muestra las que vencen en 7 días.
Con número: muestra las que vencen en esos días (ej: 14 = dos semanas).

Útil para contactar a usuarios y ofrecerles renovación.

---

### 📢 Enviar mensaje a todos los suscriptores activos
```
/admin_broadcast Tu mensaje aquí
```

**Ejemplo:**
```
/admin_broadcast Recordatorio: el consulado estará cerrado el 19 de marzo por festivo en España. El bot continuará monitoreando normalmente.
```

Solo llega a usuarios con plan Directo o Premium activo.
No usar para spam — solo comunicados relevantes al servicio.

---

### 🔍 Ver historial de tus acciones
```
/admin_audit
```

Muestra las últimas 15 acciones que realizaste: qué comandos usaste, cuándo y sobre quién. Sirve como registro de tu actividad.

---

## Flujo típico de trabajo diario

### Cuando alguien paga:
1. El usuario te envía captura del pago
2. Verificas que el monto y el método son correctos
3. Ejecutas: `/admin_activar @suusuario directo 90 15 zelle`
4. El bot le notifica automáticamente
5. Listo — no hay más pasos

### Cada semana:
1. Ejecuta `/admin_expiran 7` para ver quién vence pronto
2. Contacta a esos usuarios para ofrecerles renovación
3. Ejecuta `/admin_stats` para revisar el estado general

### Si hay una queja:
1. Verifica con `/admin_listar` si el usuario está activo
2. Si hay problema técnico, repórtalo al responsable técnico (Vladimir)
3. Si es problema de pago, usa `/admin_desactivar` si es necesario

---

## Lo que NO debes hacer

- ❌ No compartas los comandos admin con nadie
- ❌ No actives suscripciones sin verificar el pago
- ❌ No uses /admin_broadcast para mensajes no relacionados con el servicio
- ❌ No intentes acceder a GitHub, Neon, ni ninguna plataforma técnica
- ❌ No compartas capturas de pantalla de /admin_listar (contiene datos de usuarios)

---

## ¿Qué hago si el bot no responde?

Espera 5 minutos — puede estar reiniciándose automáticamente.
Si después de 10 minutos no responde, comunícaselo al responsable técnico.

**No intentes reiniciarlo tú mismo.**

---

## Contacto técnico

Cualquier problema técnico → Vladimir (responsable de infraestructura)
