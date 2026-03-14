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
├─ ovc_heartbeat.yml — cada 4h (0,4,8,12,16,20 Miami)
│    └─ ovc_heartbeat.py — "Estoy vivo" a Telegram
│
└─ Telegram → alerta con botón ABRIR AHORA
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
| `TELEGRAM_CHAT_ID` | Chat ID donde llegan las alertas |
| `AVC_TRAMITE` | Trámite a vigilar (ej: `LMD`) |

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

## Fixes implementados (sesión Mar 13 2026)

- **Anti-bot sleep aleatorio**: 10-90s antes de cada consulta
- **User-agent rotativo**: 6 UAs reales de Chrome/Firefox/Safari
- **Viewport random**: 5 resoluciones reales (1920×1080 ... 1280×800)
- **Stealth Playwright**: elimina `navigator.webdriver` y añade plugins/idiomas reales
- **Cron irregular**: minutos 0,7,13,19,26,32,38,44,51,57 — no detectable como bot
- **Botón ABRIR AHORA**: alerta Telegram con botón que abre directo al captcha
- **Heartbeat cada 4h**: confirma que el bot está activo en Telegram
- **Repo privado**: visibilidad privada en GitHub

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
