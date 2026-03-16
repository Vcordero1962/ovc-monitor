# OVC — Orquestador de Vigilancia Consular

Bot de monitoreo 24/7 de citas en el sistema de citas consulares de España (`citaconsular.es`).
Corre en **GitHub Actions** (nube) — funciona aunque la PC esté apagada.

---

## Arquitectura

```
GitHub Actions (Microsoft Azure)
│
├─ ovc_monitor.yml  — cron irregular cada ~7 min
│    └─ ovc_once.py — check único anti-bot
│         ├─ sleep aleatorio 10-90s
│         ├─ user-agent rotativo (6 UA reales)
│         ├─ viewport random (5 resoluciones)
│         ├─ stealth Playwright (oculta webdriver)
│         ├─ verifica citaconsular.es
│         └─ verifica canal AVC Telegram
│
├─ ovc_heartbeat.yml — 2x/día: 9:15am y 5:15pm Miami (UTC 13:15 y 21:15)
│    └─ ovc_heartbeat.py — "Estoy vivo #N" → edita mensaje PINNEADO (no crea nuevos)
│         ├─ ADMIN_CHAT_ID → chat personal admin (técnico/status)
│         ├─ anti-duplicate: skip si ya corrió hace <2h
│         └─ #RUN_NUMBER consecutivo para verificar edición vs nuevo
│
└─ Telegram
     ├─ TELEGRAM_CHAT_ID → grupo "OVC Alertas Consulado" (SOLO alertas de citas)
     └─ ADMIN_CHAT_ID    → chat personal admin (heartbeat + alerts técnicas)
```

---

## Archivos

| Archivo | Descripción |
|---|---|
| `ovc_once.py` | Check único para GitHub Actions — anti-bot completo |
| `ovc_monitor.py` | Bot local para correr en PC (alternativo) |
| `ovc_heartbeat.py` | Script de heartbeat diario |
| `ovc_sitio_watch.py` | Watcher simple del sitio |
| `ovc_nocturno.bat` | Lanzador nocturno Windows |
| `programar_tarea.ps1` | Tarea programada Windows |
| `requirements.txt` | Dependencias Python |
| `.github/workflows/ovc_monitor.yml` | Workflow principal GitHub Actions |
| `.github/workflows/ovc_heartbeat.yml` | Workflow heartbeat cada 4h |

---

## Secretos requeridos (GitHub → Settings → Secrets)

| Secret | Descripción |
|---|---|
| `URL_SISTEMA` | URL del widget de citas (citaconsular.es) |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram |
| `TELEGRAM_CHAT_ID` | Chat ID grupo "OVC Alertas Consulado" — alertas de citas |
| `ADMIN_CHAT_ID` | Chat ID personal del admin `1951356386` — heartbeat y status |
| `AVC_TRAMITE` | Trámite a vigilar (ej: `LMD`) |
| `SITIO_DIRECTO_ENABLED` | `0`=solo AVC \| `1`=también verifica citaconsular.es directo |

---

## Variables locales (.env — NO se sube a GitHub)

```
USUARIO_CI=...
PASSWORD_CITA=...
URL_SISTEMA=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
AVC_TRAMITE=LMD
```

---

## ⚠️ Ventana Crítica — Cuándo Monitorear

El sistema de citaconsular.es libera cupos en el **reset de medianoche (España)**:

| Reset (medianoche España) | Día habilitado | Cupos estimados | Probabilidad |
|---|---|---|---|
| Jueves → **Viernes** | Viernes | ~168 citas | Media-Baja |
| Domingo → **Lunes** | Lunes | ~252 citas | Alta |
| Lunes → **Martes** | Martes | ~312 citas | **MÁXIMA** |

- **Horario crítico**: Medianoche España = **6pm Miami** (UTC-5 invierno) / **5pm Miami** (UTC-4 verano)
- **Ventana clave**: Lunes a Martes — máxima liberación de cupos
- **El bot monitorea 24/7** — no requiere acción manual

---

## Fixes implementados (sesión Mar 13 2026)

- **Anti-bot sleep aleatorio**: 10-90s antes de cada consulta
- **User-agent rotativo**: 6 UAs reales de Chrome/Firefox/Safari
- **Viewport random**: 5 resoluciones reales (1920×1080 ... 1280×800)
- **Stealth Playwright**: elimina `navigator.webdriver` y añade plugins/idiomas reales
- **Cron irregular**: minutos 0,7,13,19,26,32,38,44,51,57 — no detectable como bot
- **Botón ABRIR AHORA**: alerta Telegram con botón que abre directo al captcha
- **Heartbeat 2x/día**: 9:15am y 5:15pm Miami — edita mensaje PINNEADO (0 mensajes nuevos)
- **Anti-duplicate guard**: skip si heartbeat ya corrió hace <2h
- **ADMIN_CHAT_ID routing**: heartbeat va al admin personal; grupo recibe SOLO alertas de citas
- **#RUN_NUMBER**: número consecutivo en heartbeat para verificar edición vs nuevo mensaje
- **Repo privado**: visibilidad privada en GitHub

### Sesión Mar 15 2026 — Fix flood de mensajes
- **Flood resuelto**: heartbeat ahora EDITA el mensaje pinneado en vez de crear nuevos
- **Estrategia**: `getChat` → `pinned_message.message_id` → `editMessageText` — 1 mensaje permanente
- **BOT CAÍDO alert**: el sentinel envía alerta si monitor lleva >20 min sin correr (GitHub Actions delay)

---

## Trámite monitorado

| Campo | Valor |
|---|---|
| Consulado | España en La Habana, Cuba |
| Trámite | Legalización de documentos (LEGA) |
| Sistema | citaconsular.es |
| Canal AVC | t.me/AsesorVirtualC |

---

## Cómo lanzar manualmente

```bash
# Desde GitHub CLI:
gh workflow run ovc_monitor.yml --repo Vcordero1962/ovc-monitor

# Heartbeat manual:
gh workflow run ovc_heartbeat.yml --repo Vcordero1962/ovc-monitor

# Local (PC encendida):
cd "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"
python -B ovc_monitor.py
```

---

## Ver logs de GitHub Actions

```bash
gh run list --repo Vcordero1962/ovc-monitor --limit 10
gh run view <RUN_ID> --repo Vcordero1962/ovc-monitor --log
```
