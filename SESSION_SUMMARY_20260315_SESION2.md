# SESIÓN OVC: 15 Marzo 2026 — Sesión 2 [18:00 - 22:50]

## 🎯 Objetivo
Mejorar el sistema de alertas Telegram: tarjetas PIL de alerta, mensajes marketing, heartbeat anti-ráfaga, routing correcto de mensajes.

## ✅ Logros

### 1. Tarjetas PIL de alerta — commit `712ac51` (sesión anterior)
- `ovc_once.py`: `_generar_card_alerta(tipo, nombre, hora, detalle)` → imagen PNG 800×420px
  - SITIO: fondo rojo, header "!! CITA DISPONIBLE AHORA"
  - AVC: fondo naranja, header ">> ALERTA TEMPRANA - CANAL AVC"
  - Gradiente, nombre servicio grande, hora, CTA, footer "OVC Monitor Consular 24/7"
- Botón urgente: "🔴🔴 RESERVAR CITA — ENTRA YA 🔴🔴"
- Admin AVC = silencioso (disable_notification=True); Admin SITIO = con sonido

### 2. Limpieza credenciales git history — commit `a54096d` + filter-repo
- GitGuardian detectó proxy credentials en commit `7997ca4`
- Eliminadas con `git filter-repo --replace-text` — 40 commits reescritos
- Force push a GitHub — historia limpia

### 3. Heartbeat → solo al admin — commit `d39a207`
- `ovc_heartbeat.py`: `ADMIN_CHAT_ID` en lugar de `TELEGRAM_CHAT_ID`
- `ovc_heartbeat.yml`: env pasa `ADMIN_CHAT_ID: ${{ secrets.ADMIN_CHAT_ID }}` (no `TELEGRAM_CHAT_ID`)
- Grupo "OVC Alertas Consulado" recibe SOLO alertas de citas disponibles

### 4. Anti-duplicado heartbeat — commit `21711ed`
- `ovc_heartbeat.py`: `ya_enviado_recientemente()` — consulta GitHub API runs recientes
- `MIN_INTERVALO_HORAS = 2` — si hubo run exitoso hace < 2h → abortar (cron backlog)
- `ovc_heartbeat.yml`: cron `'15 13,21 * * *'` → 2x/día (era 6x/día)
- `concurrency.cancel-in-progress: true` — cancela runs duplicados

### 5. Diagnóstico ráfaga — ovc_trace_flood.py + ovc_diagnose_flood.py
- `ovc_trace_flood.py`: monkey-patch `requests.post` + `HTTPAdapter.send` — captura cada llamada HTTP
- `ovc_diagnose_flood.py`: escanea todos los .py, verifica IDs Telegram, procesos Windows, Docker
- Resultado diagnóstico: 1 sola llamada por run, Retry(total=0), IDs correctos
- Conclusión: el código es correcto — la ráfaga visual era acumulación de mensajes no leídos

### 6. Heartbeat edita mensaje pinneado — commit `c91361d`
- `ovc_heartbeat.py`: nueva estrategia — edita el mensaje pinneado en lugar de crear nuevos
  - `get_pinned_msg_id()` → `getChat` → busca `pinned_message.message_id`
  - `editar_mensaje(id, texto)` → `editMessageText` — 0 mensajes nuevos
  - Si no hay pin → `enviar_nuevo()` + `pinnear()` — 1 mensaje fijo permanente
- `GITHUB_RUN_NUMBER` en el texto → contador consecutivo visible (#27, #28...)
- `ovc_heartbeat.yml`: `permissions: actions: write`

## 📁 Archivos modificados

| Archivo | Sección | Cambio |
|---------|---------|--------|
| `ovc_once.py` | `_generar_card_alerta()` | Nueva función PIL tarjetas alerta |
| `ovc_once.py` | `_enviar_alerta_admin()` | `disable_notification` param |
| `ovc_once.py` | `_build_keyboard()` | Botón RESERVAR más urgente |
| `ovc_heartbeat.py` | Completo | Anti-duplicado + ADMIN_CHAT_ID + editar pinneado + RUN_NUMBER |
| `.github/workflows/ovc_heartbeat.yml` | env + permissions | ADMIN_CHAT_ID, actions: write, cron 2x/día |
| `requirements.txt` | `Pillow>=10.0.0` | Para tarjetas PIL |
| `ovc_trace_flood.py` | Nuevo | Script diagnóstico monkey-patch |
| `ovc_diagnose_flood.py` | Nuevo | Script diagnóstico completo |

## 🔨 Commits

| Hash | Mensaje |
|------|---------|
| `d39a207` | fix: heartbeat solo al admin — grupo recibe solo alertas de citas |
| `21711ed` | fix: anti-duplicado heartbeat — guard 2h + cron 2x/día |
| `42925f1` | tools: ovc_diagnose_flood.py — detecta fuente de mensajes duplicados |
| `28a76cb` | diag: ovc_trace_flood — monkey-patch requests para capturar ráfaga |
| `c91361d` | feat: heartbeat edita msg pinneado + numero consecutivo #RUN_NUMBER |
| `0790b54` | fix: restaurar MIN_INTERVALO_HORAS=2 — prod ready |

## 🤖 Estado Bot al cierre

- **GitHub Actions**: ✅ OK — runs cada ~7 min, ~59s (AVC-only mode)
- **Último run monitor**: success — `23120940875` hace ~5 min
- **Último heartbeat**: #27 — pinneado en chat admin, message_id=81
- **Sentinel**: ✅ corriendo (`ovc-sentinel` Up 5 hours)
- **Modo activo**: `SITIO_DIRECTO_ENABLED=0` — solo canal AVC

## ❌ Pendiente

- **Proxy residencial**: aún pendiente para activar check directo del sitio
- **LAST_HB_MSG_ID variable**: creada en GitHub (valor=79) pero ya no se usa — pin es el mecanismo de estado
- **ovc_trace_flood.yml**: workflow de diagnóstico queda en repo (puede eliminarse si molesta)
- **Cleanup mensajes viejos**: el chat admin tiene ~80 mensajes acumulados de las pruebas

## 🎯 Próxima sesión — empezar por:

1. Verificar que heartbeat de las 09:15 Miami (13:15 UTC) editó el mensaje pinneado #28
2. NutriScan TK2 aprobación: ver preview en `volumes/output/nutriscan/tiktok/nutriscant-tk2-v4_preview.mp4`
3. Proxy residencial: evaluar Webshare Static Residential ~$3/mes para activar SITIO_DIRECTO

## 🔑 Decisiones técnicas

| Decisión | Razón | Alternativas descartadas |
|----------|-------|--------------------------|
| Pinned message como storage de state | No requiere permisos de escritura de variables (403), no requiere git commit extra | GitHub variables (403 forbidden), archivo en repo (commit extra) |
| ADMIN_CHAT_ID separado de TELEGRAM_CHAT_ID | Grupo solo para alertas reales, admin para status técnico | Todo al grupo (spam para miembros) |
| `editMessageText` en lugar de `sendMessage` | 1 solo mensaje permanente, sin acumulación visual | Enviar nuevo + borrar viejo (necesita state externo) |
| RUN_NUMBER para diagnóstico | Número consecutivo GitHub Actions, disponible como env var, sin código extra | Contador propio (necesita storage) |

## ⚠️ Alertas

- **Sentinel detectó BOT CAÍDO** a las 10:33 AM (35 min sin correr) — runs cancelados por concurrencia. Se auto-recuperó.
- **Tarjetas PIL**: emojis en títulos se ven como "□" en algunas fuentes — se reemplazaron por ASCII
- **GitGuardian**: credenciales proxy expuestas en commit `7997ca4` — LIMPIADAS con filter-repo
