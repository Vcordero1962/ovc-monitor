# SESIÓN OVC: 16 Marzo 2026

## 🎯 Objetivo
Construir modelo de suscripción pago (PostgreSQL Neon), bot gestor @ovc_gestor_bot
con administración 100% vía Telegram, alertas DM privadas con watermark anti-scraping,
y eliminar toda dependencia del canal AVC (competidor directo).

> **Sesión extendida** — Protocolo de cierre ejecutado al finalizar (madrugada España)

---

## ✅ Logros

### 1. Base de datos PostgreSQL Neon — commit `968e9db`
- **Archivo**: `db/schema.sql` — tablas: `usuarios`, `suscripciones`, `alertas_log`, `admin_audit`, `watermarks`
- **Archivo**: `db/connection.py` — conexión fresca por operación, keepalives TCP, retry SSL x3
- **Archivo**: `db/usuarios.py` — CRUD completo: registrar, obtener, listar suscriptores, actualizar plan
- **Archivo**: `db/suscripciones.py` — activar, listar activas, listar por expirar, ingresos estimados
- Antes: sin persistencia de suscriptores
- Después: PostgreSQL Neon con reconexión automática ante drops SSL (Neon cierra idle >5 min)

### 2. Bot Gestor @ovc_gestor_bot — commit `968e9db`
- **Archivo**: `bot/ovc_bot.py` — entry point con fix sys.path Windows
- **Archivo**: `bot/handlers_usuario.py` — /start, /servicios (inline keyboard), /pagar, /estado, /ayuda
- **Archivo**: `bot/handlers_admin.py` — /admin_stats, /admin_listar, /admin_activar, /admin_desactivar, /admin_expiran, /admin_broadcast, /admin_audit
- Admin guard via ADMIN_TELEGRAM_ID env var — carga dinámica sin reinicio
- Timezone Miami en todas las fechas del admin
- Antes: sin bot de gestión de suscriptores
- Después: admin gestiona todo desde Telegram, sin acceso a código/DB

### 3. Watermark anti-scraping — commit `2be4169`
- **Archivo**: `core/watermark.py` — caracteres Unicode zero-width (ZWJ/ZWNJ/ZWS), 44 chars invisibles
- `aplicar(mensaje, telegram_id)` — incrusta ID en cada DM
- `detectar_desde_db(mensaje)` — recupera quién filtró el mensaje
- Antes: sin protección contra redistribución de alertas
- Después: cada DM tiene huella digital única del suscriptor

### 4. Alertas DM privadas — commit `2be4169`
- **Archivo**: `core/alertas_dm.py` — envío privado a suscriptores activos por trámite
- Anti-duplicado: no reenvía si ya se envió alerta para ese trámite en los últimos 30 min
- Solo llegan a planes Directo/Premium activos y vigentes
- ovc_once.py integrado: llama a `enviar_alerta_suscriptores()` en Capa 1 y Capa 2
- Antes: alertas al canal público (scrapeables y redistribuibles)
- Después: DM privado watermarked, indetectable para terceros

### 5. Fix hora Miami admin_stats — commit `f2be8b4`
- Antes: mostraba UTC
- Después: `(datetime.now(UTC) - timedelta(hours=4)).strftime(...)` → hora Miami correcta

### 6. Fix SSL Neon + sentinel threshold — commit `f337e63`
- `db/connection.py`: get_conn con retry exponencial 2s, 4s, 6s
- `ovc_sentinel/sentinel.py`: threshold 90→150 min para evitar falsas alarmas por throttling GH Actions

### 7. Manual del Administrador — commit `f337e63`
- **Archivo**: `MANUAL_ADMINISTRADOR.md` — guía completa en español sin referencias técnicas
- Cubre: /admin_stats, /admin_listar, /admin_activar, /admin_desactivar, /admin_expiran, /admin_broadcast, /admin_audit
- Flujo diario documentado, prohibiciones claras

### 8. Eliminar dependencia AVC — commit `3b9d466`
- **Archivo**: `ovc_once.py` — eliminada Capa 3 completa (AVC scraping), `import core.avc`, `hits_avc`
- **Archivo**: `core/telegram.py` — `send_status()` ya no recibe ni reporta AVC
- Razón: AVC es canal de un competidor directo — OVC no puede depender de él
- Antes: 3 capas (Playwright + Bookitit + AVC)
- Después: 2 capas independientes y propias (Playwright opt + Bookitit POST $0)

---

## 📁 Archivos modificados / creados

| Archivo | Tipo | Cambio |
|---------|------|--------|
| `db/schema.sql` | NUEVO | Esquema PostgreSQL completo |
| `db/connection.py` | NUEVO | Conexión Neon con retry SSL |
| `db/usuarios.py` | NUEVO | CRUD usuarios + suscriptores |
| `db/suscripciones.py` | NUEVO | CRUD suscripciones + ingresos |
| `bot/ovc_bot.py` | NUEVO | Entry point bot gestor |
| `bot/handlers_usuario.py` | NUEVO | Comandos usuario (/start etc.) |
| `bot/handlers_admin.py` | NUEVO | Comandos admin (/admin_*) |
| `core/watermark.py` | NUEVO | Watermark zero-width Unicode |
| `core/alertas_dm.py` | NUEVO | Envío DM privado + anti-dup |
| `ovc_once.py` | MODIFICADO | Integra DM, elimina AVC Capa 3 |
| `core/telegram.py` | MODIFICADO | send_status sin AVC |
| `MANUAL_ADMINISTRADOR.md` | NUEVO | Guía admin solo Telegram |
| `.github/workflows/ovc_bot.yml` | NUEVO | Workflow bot gestor 24/7 |

---

### 9. Limpieza AVC completa — commit `c2df794`
- **Archivo**: `core/config.py` — elimina `URL_AVC`, `AVC_ALERTAS` list
- **Archivo**: `core/telegram.py` — elimina import `URL_AVC`, botón "📢 Ver aviso oficial en AVC" del keyboard, simplifica `generar_card()` a un único estilo rojo urgente
- Antes: alertas al grupo tenían botón que enviaba a canal AVC (competidor)
- Después: solo botón "🔴🔴 RESERVAR CITA — ENTRA YA 🔴🔴" con enlace directo al widget

### 10. Arquitectura de roles — documentado
- **Vladimir** = responsable técnico (GitHub, código, OVC Monitor Consular)
- **Administrador (Daysi @daysi7404)** = gestión suscripciones exclusivamente vía @ovc_gestor_bot
- **Suscriptores** = miembros de "OVC Alertas Consulado" + DM privado si pagan
- Daysi tiene 1 grupo en común (OVC Alertas Consulado), candidata a administradora
- Para activarla: obtener su ID numérico vía @userinfobot → `gh secret set ADMIN_TELEGRAM_ID`

---

## 🔨 Commits esta sesión

| Hash | Descripción |
|------|-------------|
| `968e9db` | feat: bot gestor OVC + PostgreSQL Neon |
| `2be4169` | feat: alertas DM privadas + watermark + workflow bot gestor |
| `f337e63` | fix: reconexion SSL Neon + sentinel threshold 150min + manual admin |
| `f2be8b4` | fix: hora Miami en /admin_stats (era UTC) |
| `3b9d466` | Remove AVC canal dependency — OVC es independiente y no depende de competidores |
| `95c3567` | docs: cierre sesion Mar 16 — arquitectura v2.0 sin AVC |
| `c2df794` | fix: eliminar toda referencia AVC de config.py y telegram.py |

---

## 🤖 Estado Bot al cierre

- **GitHub Actions ovc_monitor**: ✅ SUCCESS (run `23175658906`, 8m32s)
- **GitHub Actions ovc_bot**: ⚠️ falla con "workflow file issue" en 0s — ver Pendiente #1
- **Sentinel Docker**: ✅ `ovc-sentinel` Up ~1 hora
- **Bookitit POST**: ✅ activo, $0, ~5s/check
- **Sitio directo (Playwright)**: ⛔ `SITIO_DIRECTO_ENABLED=0` (sin proxy residencial)
- **AVC canal**: ❌ eliminado definitivamente — código + botones + imports limpiados

---

## ❌ Pendiente

1. **ovc_bot.yml "workflow file issue"** — GitHub reporta fallo en 0s con "This run likely failed because of a workflow file issue". El `run: python -X utf8 -c "` con comillas dobles en YAML puede causar parsing error. Fix próxima sesión: cambiar a `run: |` (block scalar) en el step "Aplicar schema DB". El bot gestor puede correr localmente mientras tanto: `python -X utf8 bot/ovc_bot.py`

2. **Activar a Daysi como administradora** — Obtener su Telegram ID numérico (via @userinfobot) y ejecutar: `gh secret set ADMIN_TELEGRAM_ID --repo Vcordero1962/ovc-monitor --body "ID_DAYSI"`

3. **`/admin_activar` por telegram_id** — actualmente solo acepta `@username`. Usuarios sin username público no pueden ser activados. Pendiente: agregar soporte para activación por ID numérico.

4. **Prueba E2E completa** — /estado debería mostrar "Plan Directo activo" para Vladimir (telegram_id=1951356386).

5. **`core/avc.py` — dead code en repo** — el archivo sigue trackeado en git pero ya nadie lo importa. Limpiar con `git rm core/avc.py` en próxima sesión.

6. **Sentinel threshold rebuild** — threshold cambiado en código a 150min pero Docker container tiene imagen anterior bakeada. Requiere: `cd ovc_sentinel && docker compose build --no-cache && docker compose up -d`

7. **Watermark salt** — `_SALT = "OVC-WM-2026-SALT-INMUTABLE"` en `core/watermark.py`. Riesgo bajo pero mover a env var `WATERMARK_SALT` en próxima sesión.

---

## 🎯 Próxima sesión — empezar por

1. **Fix ovc_bot.yml** — cambiar step "Aplicar schema DB" de `run: python -X utf8 -c "..."` a `run: |` block scalar
2. **Activar Daysi como admin** — `gh secret set ADMIN_TELEGRAM_ID --body "ID_NUMERICO_DAYSI"`
3. **Limpiar core/avc.py** — `git rm core/avc.py && git commit -m "chore: eliminar avc.py obsoleto"`
4. **Rebuild sentinel** — `cd ovc_sentinel && docker compose build --no-cache && docker compose up -d`
5. **Fix /admin_activar por ID numérico** — soporte para usuarios sin @username público

---

## 🔑 Decisiones técnicas

| Decisión | Razón | Alternativas descartadas |
|----------|-------|--------------------------|
| **Sin AVC** | OVC compite en el mismo mercado | Mantener como "Layer 3 opcional" |
| **Neon PostgreSQL free tier** | Sin costo, sin infra, conexión directa desde Actions | XAMPP local (sin acceso desde nube), Supabase |
| **Conexión fresca por operación** | Neon cierra idle SSL >5 min | Pool persistente (falla en Actions con gaps) |
| **fecha_expira en Python** | PostgreSQL rechaza GENERATED ALWAYS AS con timedelta | Calcular en DB (no soportado) |
| **Watermark zero-width Unicode** | Invisible, no altera el mensaje, resistente a copia | Hash visible, marca de agua de imagen |
| **Admin 100% Telegram** | Sin acceso técnico requerido | Panel web (costo/mantenimiento) |

---

## ⚠️ Alertas

- `ADMIN_CHAT_ID=1951356386` aparece en CLAUDE.md — es el chat ID personal de Vladimir (admin), no es un secreto técnico pero es dato sensible. Queda documentado solo en archivos NO commiteados o en docs de contexto interno.
- El bot @ovc_gestor_bot (token `BOT_GESTOR_TOKEN`) corre en GitHub Actions con timeout 350min. Si cae, GitHub Actions no lo reinicia automáticamente — el sentinel debería detectarlo.
- AVC eliminado definitivamente. Si en futuro se detecta disponibilidad por otra vía de terceros, evaluar solo si es completamente independiente y no compite con OVC.
