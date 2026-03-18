# CLAUDE.md — Contexto del Proyecto OVC
## Versión: 2.1 — Actualizado: 18 Marzo 2026

## Propósito
Sistema integral de vigilancia y alerta de citas consulares para **legalización de documentos**
en el Consulado de España en La Habana, Cuba.

**Dos componentes:**
1. **Monitor** (`ovc_once.py`) — detecta disponibilidad en citaconsular.es vía Bookitit POST
2. **Bot Gestor** (`bot/ovc_bot.py`) — gestiona suscriptores, recibe pagos, envía DMs privados con watermark

---

## Arquitectura de archivos

```
OVC/
├── ovc_once.py              ← MONITOR PRINCIPAL — GitHub Actions, 2 capas de detección
├── ovc_burst.py             ← BURST MODE — loop 35min × 45s para ventanas críticas
├── ovc_heartbeat.py         ← Heartbeat — edita mensaje PINNEADO cada 4h
├── ovc_monitor.py           ← Alternativo — corre en PC local (loop continuo)
├── ovc_sitio_watch.py       ← Watcher simple sin Playwright
│
├── core/
│   ├── config.py            ← Configuración y catálogo de servicios consulares
│   ├── logger.py            ← Logging estructurado con niveles
│   ├── security.py          ← Validaciones anti-inyección de tokens
│   ├── bookitit.py          ← Check Bookitit POST directo ($0, ~5s, sin proxy)
│   ├── playwright_check.py  ← Check sitio directo con Playwright + stealth
│   ├── telegram.py          ← Envío de alertas y confirmaciones al grupo/admin
│   ├── alertas_dm.py        ← Envío DM privado a suscriptores con watermark
│   └── watermark.py         ← Watermark zero-width Unicode (44 chars invisibles/DM)
│
├── db/
│   ├── schema.sql           ← Schema PostgreSQL (Neon): usuarios, suscripciones, etc.
│   ├── connection.py        ← Conexión Neon con retry SSL x3 + keepalives TCP
│   ├── usuarios.py          ← CRUD usuarios + listar suscriptores por trámite
│   └── suscripciones.py     ← CRUD suscripciones + ingresos + expiración
│
├── bot/
│   ├── ovc_bot.py           ← Entry point bot gestor (polling continuo)
│   ├── handlers_usuario.py  ← /start /servicios /pagar /estado /ayuda
│   └── handlers_admin.py    ← /admin_stats /admin_listar /admin_activar /admin_desactivar
│                               /admin_expiran /admin_broadcast /admin_audit
│
├── ovc_sentinel/
│   ├── sentinel.py          ← Vigilancia local 24/7 (Docker container)
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── MANUAL_ADMINISTRADOR.md  ← Guía admin — solo Telegram, sin acceso técnico
├── requirements.txt         ← psycopg2, python-telegram-bot, playwright, requests, etc.
├── .env                     ← Credenciales locales (NUNCA en git)
├── .gitignore               ← Excluye .env y __pycache__
│
└── .github/workflows/
    ├── ovc_monitor.yml      ← Cron irregular cada ~7 min — ovc_once.py
    ├── ovc_heartbeat.yml    ← Cron cada 4h — ovc_heartbeat.py
    ├── ovc_burst.yml        ← Cron 2x/día (ventanas críticas) — ovc_burst.py
    └── ovc_bot.yml          ← Bot gestor 24/7 — bot/ovc_bot.py (timeout 350min)
```

---

## GitHub Repository

- **Repo**: https://github.com/Vcordero1962/ovc-monitor (privado)
- **Token (PAT)**: guardado en .env local

### Secrets configurados en GitHub Actions

| Secret | Usado en | Descripción |
|--------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ovc_monitor, heartbeat, burst | Bot @ovc_consular_bot — alertas grupo |
| `TELEGRAM_CHAT_ID` | ovc_monitor | Grupo "OVC Alertas Consulado" (`-5127911137`) |
| `ADMIN_CHAT_ID` | ovc_monitor, heartbeat | Chat personal Vladimir (`1951356386`) |
| `URL_SISTEMA` | ovc_monitor | URL widget citaconsular.es (LEGA/LMD) |
| `SITIO_DIRECTO_ENABLED` | ovc_monitor | `0` = Playwright desactivado |
| `BOOKITIT_POST_ENABLED` | ovc_monitor | `1` = Bookitit POST activo |
| `HTTP_PROXY_URL` | ovc_monitor | Proxy datacenter (inactivo — no bypassea Imperva) |
| `BOT_GESTOR_TOKEN` | ovc_bot | Bot @ovc_gestor_bot — suscriptores |
| `ADMIN_TELEGRAM_ID` | ovc_bot | ID Telegram del administrador |
| `NEON_DATABASE_URL` | ovc_bot | Connection string Neon PostgreSQL |
| `STATUS_CADA_RUN` | ovc_monitor | `1` = envía confirmación silenciosa por run |

---

## Telegram

- **Bot monitor**: @ovc_consular_bot — alertas de disponibilidad
- **Bot gestor**: @ovc_gestor_bot — gestión de suscriptores y pagos
- **Grupo alertas**: "OVC Alertas Consulado" — chat_id: `-5127911137`
- **Chat personal Vladimir / Admin**: `1951356386` — heartbeat y status técnico
- **Heartbeat**: edita mensaje PINNEADO en chat admin (no crea nuevos mensajes)
  - Anti-duplicado: `MIN_INTERVALO_HORAS=2` — si corrió hace <2h → abortar

---

## Detección — 2 Capas (AVC eliminado definitivamente)

| Capa | Mecanismo | Costo | Estado |
|------|-----------|-------|--------|
| 1 | Playwright sitio directo (residencial) | $0 local | `SITIO_DIRECTO_ENABLED=1` local (ventanas críticas) |
| 2 | Bookitit getservices/POST directo | $0 | `BOOKITIT_POST_ENABLED=1` — **ACTIVO** |

**Estrategia IP:**
- **Local PC (residencial)**: Playwright con `AllowAppointment` interceptor — 100% fiable
- **GitHub Actions (datacenter)**: `_check_getservices` → bloqueado por Imperva → capas legacy

**API endpoints reales descubiertos (ovc_spy Mar 18):**
- `GET /onlinebookings/getwidgetconfigurations/?publickey={PK}` → config widget
- `GET /onlinebookings/getservices/?publickey={PK}` → **AllowAppointment** (flag definitivo)
- `GET /onlinebookings/getagendas/?services[]={SID}` → agendas (si AllowAppointment=true)
- **LEGA SID**: `bkt1180597` | **PK**: `25b6cfa9f112aef4ca19457abc237f7ba` (33 chars)

> ⛔ **AVC eliminado definitivamente** — canal Telegram de tercero que compite
> directamente con el mercado objetivo de OVC. OVC no depende de ningún competidor.

---

## Anti-bot — Fixes activos (NO revertir)

| Fix | Archivo | Descripción |
|-----|---------|-------------|
| Sleep gaussiano | `ovc_once.py` | `random.gauss(45, 20)` antes de consultar |
| UA rotativo | `ovc_once.py` | 13 user-agents reales Chrome/Firefox/Safari |
| Viewport random | `ovc_once.py` | 7 resoluciones desktop+mobile |
| Stealth script dinámico | `ovc_once.py` | Elimina `webdriver`, plugins, hardware fingerprint |
| Cron irregular | `ovc_monitor.yml` | Minutos: 0,7,13,19,26,32,38,44,51,57 |
| Sleep gaussiano burst | `ovc_burst.py` | `random.gauss(45, 10)` entre checks |

---

## Proxy — Estado actual

- **`SITIO_DIRECTO_ENABLED=0`** — Bookitit POST es la capa activa principal
- **Proxy configurado** (datacenter, inactivo): Webshare free, no bypassea Imperva
- **Para activar check directo**: requiere proxy RESIDENCIAL (~$3/mes Webshare Static)

---

## Modelo de Suscripción

| Plan | Precio | Acceso |
|------|--------|--------|
| Gratuito | $0 | Solo /servicios y /pagar (sin alertas) |
| Directo | ~$15/90 días | DM privado con URL directa al widget |
| Premium | ~$25/90 días | DM privado + soporte prioritario |

- **Admin activa** suscripción vía `/admin_activar @user plan dias precio metodo`
- **Watermark único** en cada DM — detecta si suscriptor filtra las alertas
- **Sin canal público** — alertas NUNCA van a canal; solo DM privado

---

## Flujo cuando HAY cita disponible

```
citaconsular.es → Bookitit POST detecta agendas/dates > 0
→ ovc_once.py Capa 2
→ tg.send_text/photo (grupo "OVC Alertas Consulado")  ← notificación pública
→ tg.send_admin (chat personal Vladimir)              ← alerta técnica
→ enviar_alerta_suscriptores(tramite, url)            ← DM privado con watermark
    → solo suscriptores plan Directo/Premium activos
    → cada DM lleva 44 chars invisibles con ID del suscriptor
```

---

## Comandos frecuentes

```bash
# Ver últimos runs
gh run list --repo Vcordero1962/ovc-monitor --limit 5

# Lanzar check manual
gh workflow run ovc_monitor.yml --repo Vcordero1962/ovc-monitor

# Ver logs de un run fallido
gh run view <ID> --repo Vcordero1962/ovc-monitor --log

# Actualizar secret
gh secret set NOMBRE --repo Vcordero1962/ovc-monitor --body "VALOR"

# Arrancar bot gestor local
cd "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"
C:\Users\aemes\anaconda3\python.exe -X utf8 bot/ovc_bot.py

# Rebuild sentinel (tras cambios en sentinel.py)
cd ovc_sentinel
docker compose build --no-cache
docker compose up -d
```

---

## Notas críticas

- `.env` contiene credenciales reales — NUNCA hacer push (en .gitignore)
- Neon cierra conexiones SSL idle >5 min — siempre usar `get_conn()` (conexión fresca)
- `fecha_expira` se calcula en Python (`now + timedelta(days=dias)`) — PostgreSQL rechaza GENERATED ALWAYS AS con intervalos
- Las IPs de GitHub Actions (Azure) rotan — imposible bloqueo permanente
- El bot gestor corre con polling continuo — si cae en Actions, no se reinicia solo
- `ADMIN_CHAT_ID` en CLAUDE.md es dato sensible (ID personal) — no compartir fuera del proyecto

---

## Historial de sesiones

| Fecha | Cambios principales |
|-------|---------------------|
| Mar 18 2026 | **Sesión 5**: ovc_spy flujo completo, AllowAppointment interceptor, ventanas críticas — commits `31c95e9`→`b1ce24c` |
| Mar 17 2026 | ovc_inspector + Capa 1 app.bookitit.com directo (root cause Imperva soft-block resuelto) — commit `ba591fc` |
| Mar 16 2026 | Bot gestor + Neon DB + watermark DM + elimina AVC definitivamente |
| Mar 16 2026 (burst) | ovc_burst.py + ovc_burst.yml — cron 2x/día ventanas críticas — commit `1e1a6a2` |
| Mar 16 2026 (Bookitit) | Bookitit POST directo confirmado producción — bypass Imperva $0 — commit `f2be8b4` |
| Mar 15 2026 (noche) | Heartbeat anti-ráfaga: edita mensaje pinneado + ADMIN_CHAT_ID + anti-dup 2h |
| Mar 15 2026 (tarde) | Proxy Webshare + SITIO_DIRECTO_ENABLED flag |
| Mar 15 2026 (mañana) | Grupo Telegram "OVC Alertas Consulado" — alertas a múltiples miembros |
| Mar 14 2026 | Fix WiFi + Fix DNS GitHub Actions + auto-fallback wg0 |
| Mar 13 2026 | Setup inicial GitHub Actions, anti-bot, heartbeat, repo privado |
