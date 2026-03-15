# CLAUDE.md — Contexto del Proyecto OVC

## Propósito
Bot de vigilancia automatizada de citas consulares para **legalización de documentos**
en el Consulado de España en La Habana, Cuba. Monitorea el sistema `citaconsular.es`
y alerta via Telegram cuando aparece disponibilidad.

## Caso de uso
- **Usuario**: Vladimir (en Miami, USA)
- **Para quién**: Sobrino en Cuba
- **Trámite**: Legalización de documentos — código `LEGA`
- **AVC_TRAMITE**: `LMD` (Ley de Memoria Democrática — keywords: LMD, LEGALIZACI, CREDENCIALES)

---

## Arquitectura de archivos

```
OVC/
├── ovc_once.py          ← PRINCIPAL — corre en GitHub Actions nube
├── ovc_monitor.py       ← Alternativo — corre en PC local (loop continuo)
├── ovc_heartbeat.py     ← Heartbeat — mensaje "Estoy vivo" cada 4h
├── ovc_sitio_watch.py   ← Watcher simple sin Playwright
├── ovc_nocturno.bat     ← Lanzador Windows tarea nocturna
├── programar_tarea.ps1  ← Registra tarea en Task Scheduler Windows
├── requirements.txt     ← playwright, requests, python-dotenv
├── .env                 ← Credenciales locales (NO en git)
├── .gitignore           ← Excluye .env y __pycache__
└── .github/
    └── workflows/
        ├── ovc_monitor.yml    ← Cron irregular + ovc_once.py
        └── ovc_heartbeat.yml  ← Cron cada 4h + ovc_heartbeat.py
```

---

## GitHub Repository

- **Repo**: https://github.com/Vcordero1962/ovc-monitor
- **Visibilidad**: Privado
- **Token (PAT)**: guardado en .env local (variable GITHUB_TOKEN o GITHUB_PAT)
- **Secretos configurados**: URL_SISTEMA, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, AVC_TRAMITE, HTTP_PROXY_URL, SITIO_DIRECTO_ENABLED, WG_CONFIG_NL

---

## Telegram

- **Bot**: @ovc_consular_bot
- **Grupo alertas**: "OVC Alertas Consulado" — chat_id: `-5127911137`
- **Chat personal Vladimir** (backup): `1951356386`
- **Secret TELEGRAM_CHAT_ID**: apunta al grupo (todos los miembros reciben alerta simultanea)
- **Alerta cita**: mensaje con boton inline "ABRIR AHORA" -> abre citaconsular.es directo
- **Heartbeat**: cada 4h (0,4,8,12,16,20 Miami) — mensaje "Estoy vivo"

---

## Anti-bot — Fixes activos (NO revertir)

| Fix | Archivo | Descripción |
|---|---|---|
| Sleep gaussiano | `ovc_once.py` L~632 | `random.gauss(45, 20)` antes de consultar |
| UA rotativo | `ovc_once.py` L~106 | 13 user-agents reales Chrome/Firefox/Safari/Mobile |
| Viewport random | `ovc_once.py` L~128 | 7 resoluciones desktop+mobile |
| Stealth script dinámico | `ovc_once.py` L~138 | Elimina `webdriver`, plugins, hardware fingerprint |
| Perfil Chromium persistente | `ovc_once.py` L~356 | `launch_persistent_context` + `actions/cache@v4` |
| CDP latency throttling | `ovc_once.py` L~407 | 40-80ms RTT (emula hogar vs datacenter 1-5ms) |
| Session age management | `ovc_once.py` L~202 | Limpia cookies si sesión > 25 min |
| Warm-up navigation | `ovc_once.py` L~427 | Google search antes de consulado (solo sin proxy) |
| Cron irregular | `ovc_monitor.yml` | Minutos: 0,7,13,19,26,32,38,44,51,57 |
| Botón ABRIR AHORA | `ovc_once.py` L~251 | `reply_markup` inline keyboard |

## Proxy — Estado actual

- **`SITIO_DIRECTO_ENABLED=0`** — solo canal AVC activo (datacenter no bypassea Imperva)
- **Proxy configurado** (datacenter, no activo): credenciales en GitHub Secret `HTTP_PROXY_URL` (Webshare free, España/Madrid)
- **Para activar check directo**: necesitas proxy RESIDENCIAL real (Webshare Static Residential ~$3/mes)
  1. Actualizar `HTTP_PROXY_URL` secret con nueva IP residencial
  2. `gh secret set SITIO_DIRECTO_ENABLED --body "1" --repo Vcordero1962/ovc-monitor`
  3. Subir `timeout-minutes` a 10 en `ovc_monitor.yml`

---

## Flujo cuando HAY cita disponible

```
citaconsular.es → widget activo
→ ovc_once.py detecta (no encuentra "No hay horas disponibles")
→ enviar_telegram(con_boton=True)
→ Telegram: "CITA DISPONIBLE — Consulado España"
             [ABRIR AHORA] ← botón directo al captcha
→ Usuario toca botón en celular → abre browser → llena captcha → reserva
```

---

## Comandos frecuentes

```bash
# Ver últimos runs
GITHUB_TOKEN=... gh run list --repo Vcordero1962/ovc-monitor --limit 5

# Lanzar check manual
GITHUB_TOKEN=... gh workflow run ovc_monitor.yml --repo Vcordero1962/ovc-monitor

# Lanzar heartbeat manual
GITHUB_TOKEN=... gh workflow run ovc_heartbeat.yml --repo Vcordero1962/ovc-monitor

# Ver logs de un run
GITHUB_TOKEN=... gh run view <ID> --repo Vcordero1962/ovc-monitor --log

# Actualizar secreto
GITHUB_TOKEN=... gh secret set NOMBRE --repo Vcordero1962/ovc-monitor --body "VALOR"

# Arrancar bot local
cd "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"
C:\Users\aemes\anaconda3\python.exe -B ovc_monitor.py
```

---

## Notas importantes

- El `.env` contiene credenciales reales — NUNCA hacer push (está en .gitignore)
- La contraseña del sistema citaconsular.es NO se puede cambiar — es asignada
- Las IPs de GitHub Actions (Azure) rotan — imposible bloqueo permanente
- El bot corre ~10 veces/hora × 24h = ~240 checks/día
- GitHub Actions gratuito: 2,000 min/mes — uso estimado: ~50 min/día ✅
- Repo privado: Actions sigue siendo gratis
- La cita dura ~2 minutos antes que otro la tome — responder INMEDIATAMENTE al alerta

---

## Historial de sesiones

| Fecha | Cambios |
|---|---|
| Mar 15 2026 (tarde) | Proxy Webshare + SITIO_DIRECTO_ENABLED flag — AVC-only mode (59s/run) |
| Mar 15 2026 (mañana) | Grupo Telegram "OVC Alertas Consulado" (-5127911137) — alertas a multiples miembros |
| Mar 14 2026 | Fix WiFi + Fix DNS GitHub Actions (168.63.129.16) + auto-fallback wg0 sin handshake |
| Mar 13 2026 | Setup inicial GitHub Actions, anti-bot, heartbeat, repo privado |
| Mar 12 2026 | Bot local — primera alerta real (8 mensajes CITA DISPONIBLE falsos positivos) |
