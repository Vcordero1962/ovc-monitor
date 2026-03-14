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
- **Secretos configurados**: URL_SISTEMA, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, AVC_TRAMITE

---

## Telegram

- **Bot**: @ovc_consular_bot
- **Chat ID**: 1951356386
- **Alerta cita**: mensaje con botón inline "ABRIR AHORA" → abre captcha directo
- **Heartbeat**: cada 4h (0,4,8,12,16,20 Miami) — mensaje "Estoy vivo"

---

## Anti-bot — Fixes activos (NO revertir)

| Fix | Archivo | Descripción |
|---|---|---|
| Sleep aleatorio | `ovc_once.py` L~200 | `random.randint(10, 90)` antes de consultar |
| UA rotativo | `ovc_once.py` L~35 | 6 user-agents reales Chrome/Firefox/Safari |
| Viewport random | `ovc_once.py` L~45 | 5 resoluciones reales |
| Stealth script | `ovc_once.py` L~52 | Elimina `navigator.webdriver` |
| Cron irregular | `ovc_monitor.yml` | Minutos: 0,7,13,19,26,32,38,44,51,57 |
| Botón ABRIR AHORA | `ovc_once.py` L~70 | `reply_markup` inline keyboard |

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
| Mar 13 2026 | Setup inicial GitHub Actions, anti-bot, heartbeat, repo privado |
| Mar 12 2026 | Bot local — primera alerta real (8 mensajes CITA DISPONIBLE) |
