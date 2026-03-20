# SESIÓN OVC: 19 Marzo 2026 — Sesión 7 [Miami] (ACTUALIZADO)

## 🎯 Objetivo
Revisión de logs de los spies (ovc_spy + avc_intel) — análisis de la pérdida de cita LEGA
16/04/2026 detectada por AVC a las 12:18 PM. Diagnóstico de 3 bugs raíz + fix CF Worker
para cobertura nocturna garantizada independiente de la PC.

---

## ✅ Logros — Parte 1: Gap nocturno (commits 04b7935)

### 1. Análisis completo de logs de vigilancia
- **Período revisado**: Mar 18 19:17 → Mar 19 11:48 (continuo)
- **Resultado**: Sin citas LEGA en el período — pero se identificaron bugs críticos

### 2. Fix gap nocturno — 2 cambios
| Archivo | Cambio |
|---------|--------|
| `.github/workflows/ovc_burst.yml` | +2 cron nocturnos: 02:30 y 07:30 UTC |
| `INICIAR_SPIES.bat` | +proceso OVC_ANTI_SLEEP via SetThreadExecutionState |

---

## ✅ Logros — Parte 2: 3 bugs raíz pérdida cita LEGA (commit 7bcd551)

### Bug 1 — ovc_spy HeadlessChrome detectado (**CRÍTICO**)
- **Causa**: Playwright headless envía `sec-ch-ua: "HeadlessChrome"` automáticamente
- **Efecto**: citaconsular.es devuelve `content-length: 0` con `cache-control: max-age=172800` (48h)
- **Fix**: `extra_http_headers` en context con `sec-ch-ua` real Chrome 122

### Bug 2 — ovc_monitor.py AVC keywords (**CRÍTICO**)
- **Causa**: `AVC_ALERTAS` no tenía `"TURNOS HABILITADOS"`
- **Efecto**: OVC NOCTURNO reportó "Sin novedad" mientras AVC publicaba cita LEGA
- **Fix**: Añadido `"TURNOS HABILITADOS"` al set de alertas

### Bug 3 — avc_intel timestamps vacíos
- **Causa**: El `<time datetime="...">` está en el footer del mensaje, fuera del bloque capturado
- **Efecto**: `hora=[]` en todos los posts — análisis de horario de AVC inútil
- **Fix**: Pre-extrae mapa `msg_id→datetime` del HTML completo antes de parsear bloques

### Por qué OVC perdió la cita del 12:18 PM
1. **ovc_spy local**: HeadlessChrome → página vacía → AllowAppointment=None (11:03–12:49)
2. **OVC NOCTURNO (GA)**: "TURNOS HABILITADOS" no estaba en AVC_ALERTAS → "Sin novedad"
3. **GitHub Actions getservices**: bloqueado por Imperva desde IPs datacenter → sin detección directa

---

## ✅ Logros — Parte 3: Cobertura nocturna $0 via CF Worker (commit d28826e)

### Solución: Cloudflare Worker relay
- **Código**: `cloudflare_worker/worker.js` — ya existía, actualizado con `mode=getservices`
- **Costo**: $0 (Cloudflare free tier 100k requests/día — OVC usa ~48/día)
- **Lógica**: CF edge IPs (104.x.x.x) no están en lista negra de Imperva

### Cambios técnicos
| Archivo | Cambio |
|---------|--------|
| `cloudflare_worker/worker.js` | +`mode=getservices` — retorna `AllowAppointment` directamente |
| `core/bookitit.py` | `_check_cf_worker()` default=getservices; cascada: getservices→full→jsonp |

### DEPLOY pendiente (5 min, $0)
1. dash.cloudflare.com → Workers & Pages → Create Worker → pegar `worker.js`
2. Settings → Variables → `OVC_SECRET` = cualquier string
3. Copiar URL: `https://ovc-relay.TU-USUARIO.workers.dev`
4. GitHub Actions secrets:
   - `CF_WORKER_URL` = URL del worker
   - `CF_WORKER_SECRET` = el string del paso 2

---

## 📁 Archivos modificados en sesión 7 (total)

| Archivo | Cambio |
|---------|--------|
| `ovc_spy.py` | extra_http_headers elimina HeadlessChrome |
| `ovc_monitor.py` | AVC_ALERTAS + "TURNOS HABILITADOS" |
| `ovc_avc_intel.py` | fix extracción timestamps posts |
| `ovc_captura.bat` | puerto 8080→8888 (commiteado) |
| `.github/workflows/ovc_burst.yml` | +2 cron nocturnos |
| `INICIAR_SPIES.bat` | +OVC_ANTI_SLEEP |
| `cloudflare_worker/worker.js` | +mode=getservices |
| `core/bookitit.py` | CF Worker Capa 0 actualizada |

---

## 🤖 Estado al cierre

- **Spies locales**: ✅ Reiniciados con código nuevo (HeadlessChrome fix activo)
- **GitHub Actions**: ✅ 4 ventanas burst + cron cada 7 min (24/7)
- **CF Worker**: ⏳ Código listo — falta deploy manual en dash.cloudflare.com
- **LEGA**: Sin citas detectadas hoy
- **Repo remoto**: ✅ Push realizado (main ahead 0)

---

## ❌ Pendiente

1. **Deploy CF Worker** — 5 min en dash.cloudflare.com → garantiza detección nocturna sin PC
2. **Verificación `AllowAppointment: true` end-to-end** — no se ha probado con cita real
3. **PASAPORTE URL/PK** — AVC reportó fechas para Primer Pasaporte, verificar configuración

---

## 🎯 Próxima sesión — empezar por

1. Verificar logs spy: ¿`AllowAppointment` ya devuelve False (no None)?
2. Deploy CF Worker si no se hizo
3. `gh run list --repo Vcordero1962/ovc-monitor --limit 5` — ver estado GA
