# OVC — Orquestador de Vigilancia Consular

Sistema de monitoreo 24/7 de citas en el sistema consular de España (`citaconsular.es`).
Corre en **GitHub Actions** (nube) — funciona aunque la PC esté apagada.

Incluye modelo de **suscripción pago** con alertas privadas (DM) por Telegram.

---

## Arquitectura

```
GitHub Actions (Microsoft Azure)
│
├─ ovc_monitor.yml  — cron irregular cada ~7 min
│    └─ ovc_once.py — check único anti-bot
│         ├─ sleep gaussiano 10-90s (anti-detección)
│         ├─ user-agent rotativo (13 UAs reales)
│         ├─ Capa 1: Playwright sitio directo (SITIO_DIRECTO_ENABLED=0 actualmente)
│         ├─ Capa 2: Bookitit POST directo ($0, ~5s, sin proxy)
│         └─ DM privado a suscriptores con watermark (si hay disponibilidad)
│
├─ ovc_burst.yml    — cron 2x/día (08:00 y 17:55 Madrid)
│    └─ ovc_burst.py — loop 35min × 45s para ventanas críticas
│
├─ ovc_heartbeat.yml — 4x/día (UTC 3,9,15,21)
│    └─ ovc_heartbeat.py — edita mensaje PINNEADO (no crea nuevos mensajes)
│
├─ ovc_bot.yml      — bot gestor 24/7 (timeout 350min)
│    └─ bot/ovc_bot.py — @ovc_gestor_bot (suscripciones, pagos, admin)
│
└─ Telegram
     ├─ @ovc_consular_bot  → grupo "OVC Alertas Consulado" (alertas de citas)
     ├─ ADMIN_CHAT_ID      → chat personal admin (heartbeat + status técnico)
     └─ @ovc_gestor_bot    → DMs privados a suscriptores (alertas con watermark)
```

---

## Módulos

| Directorio/Archivo | Descripción |
|--------------------|-------------|
| `ovc_once.py` | Check principal para GitHub Actions — 2 capas anti-bot |
| `ovc_burst.py` | Burst mode para ventanas críticas (medianoche España) |
| `ovc_heartbeat.py` | Heartbeat silencioso 4x/día |
| `ovc_monitor.py` | Alternativo — loop continuo en PC local |
| `core/bookitit.py` | Detección via Bookitit POST ($0, sin proxy, ~5s) |
| `core/playwright_check.py` | Detección via Playwright + stealth (requiere proxy residencial) |
| `core/telegram.py` | Envío de alertas al grupo y admin |
| `core/alertas_dm.py` | DM privado a suscriptores con watermark |
| `core/watermark.py` | Watermark zero-width Unicode — 44 chars invisibles por DM |
| `db/connection.py` | Conexión Neon PostgreSQL con retry SSL automático |
| `db/schema.sql` | Tablas: usuarios, suscripciones, alertas_log, admin_audit, watermarks |
| `db/usuarios.py` | CRUD usuarios y suscriptores activos |
| `db/suscripciones.py` | Activar, expirar, listar suscripciones |
| `bot/ovc_bot.py` | Entry point bot gestor @ovc_gestor_bot |
| `bot/handlers_usuario.py` | /start /servicios /pagar /estado /ayuda |
| `bot/handlers_admin.py` | /admin_stats /admin_activar /admin_broadcast y más |
| `ovc_sentinel/` | Container Docker de vigilancia local 24/7 |
| `MANUAL_ADMINISTRADOR.md` | Guía para el admin — solo Telegram, sin acceso técnico |

---

## Secretos requeridos (GitHub → Settings → Secrets)

### Bot monitor (ovc_monitor.yml, ovc_burst.yml, ovc_heartbeat.yml)

| Secret | Descripción |
|--------|-------------|
| `TELEGRAM_BOT_TOKEN` | Token @ovc_consular_bot |
| `TELEGRAM_CHAT_ID` | Grupo "OVC Alertas Consulado" |
| `ADMIN_CHAT_ID` | Chat personal admin — heartbeat y status |
| `URL_SISTEMA` | URL widget citaconsular.es |
| `SITIO_DIRECTO_ENABLED` | `0` = Playwright desactivado |
| `BOOKITIT_POST_ENABLED` | `1` = Bookitit POST activo |
| `STATUS_CADA_RUN` | `1` = confirmación silenciosa por run |

### Bot gestor (ovc_bot.yml)

| Secret | Descripción |
|--------|-------------|
| `BOT_GESTOR_TOKEN` | Token @ovc_gestor_bot |
| `ADMIN_TELEGRAM_ID` | ID Telegram del administrador |
| `NEON_DATABASE_URL` | Connection string Neon PostgreSQL |

---

## Variables locales (.env — NO se sube a GitHub)

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ADMIN_CHAT_ID=...
URL_SISTEMA=...
BOT_GESTOR_TOKEN=...
ADMIN_TELEGRAM_ID=...
NEON_DATABASE_URL=...
BOOKITIT_POST_ENABLED=1
SITIO_DIRECTO_ENABLED=0
STATUS_CADA_RUN=1
```

---

## Modelo de Suscripción

El sistema incluye un bot de gestión de suscriptores pagos:

- **Plan Gratuito** — acceso al bot, sin alertas
- **Plan Directo** (~$15/90 días) — DM privado con URL directa cuando hay disponibilidad
- **Plan Premium** (~$25/90 días) — DM privado + soporte prioritario

**El administrador gestiona todo desde Telegram** — sin acceso a código ni base de datos.
Ver `MANUAL_ADMINISTRADOR.md` para los comandos disponibles.

---

## Seguridad anti-scraping

Cada alerta DM lleva un **watermark invisible** único por suscriptor (44 caracteres
Unicode zero-width incrustados). Si alguien redistribuye la alerta, el sistema puede
identificar qué suscriptor filtró el mensaje.

---

## ⚠️ Ventana Crítica — Cuándo Monitorear

El sistema libera cupos en el **reset de medianoche (España)**:

| Reset (España) | Cupos estimados | Probabilidad |
|----------------|-----------------|--------------|
| Jueves → Viernes | ~168 citas | Media-Baja |
| Domingo → Lunes | ~252 citas | Alta |
| Lunes → Martes | ~312 citas | **MÁXIMA** |

- **Medianoche España** = **6pm Miami** (UTC-5 invierno) / **5pm Miami** (UTC-4 verano)
- **ovc_burst.py** corre en las ventanas críticas (08:00 y 17:55 hora Madrid)

---

## Fixes implementados

### Anti-detección
- Sleep gaussiano antes de cada consulta (`random.gauss(45, 20)`)
- User-agent rotativo (13 UAs reales Chrome/Firefox/Safari/Mobile)
- Viewport random (7 resoluciones reales)
- Stealth Playwright: elimina `navigator.webdriver`
- Cron irregular: minutos 0,7,13,19,26,32,38,44,51,57

### Conexión
- Bookitit POST: GET captcha gate → token → POST → parsea `bkt_init_widget`
- Neon PostgreSQL: conexión fresca por operación + keepalives TCP + retry SSL x3
- Heartbeat: edita mensaje PINNEADO (anti-flood, 0 mensajes nuevos)

---

## Comandos rápidos

```bash
# Ver últimos runs GitHub Actions
gh run list --repo Vcordero1962/ovc-monitor --limit 5

# Lanzar check manual
gh workflow run ovc_monitor.yml --repo Vcordero1962/ovc-monitor

# Lanzar burst manual
gh workflow run ovc_burst.yml --repo Vcordero1962/ovc-monitor

# Ver logs de un run
gh run view <RUN_ID> --repo Vcordero1962/ovc-monitor --log

# Arrancar bot gestor local
python -X utf8 bot/ovc_bot.py

# Ver sentinel
docker logs ovc-sentinel --tail 30 -f
```

---

## Trámite monitorado

| Campo | Valor |
|-------|-------|
| Consulado | España en La Habana, Cuba |
| Trámite | Legalización de documentos (LEGA / LMD) |
| Sistema | citaconsular.es |
| Detección | Bookitit POST directo ($0) |

