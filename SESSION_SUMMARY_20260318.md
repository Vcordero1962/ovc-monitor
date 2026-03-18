# SESIÓN OVC: 18 Marzo 2026 — [10:00 - 12:30 Miami]

## 🎯 Objetivo
Diagnosticar por qué el bot reporta "sin citas" para todos los servicios aunque el widget
citaconsular.es cargue correctamente. Capturar el flujo completo de red del sistema
Bookitit/citaconsular.es para entender la arquitectura real de la API.

---

## ✅ Logros

### 1. ovc_spy.py + ovc_spy.bat — Monitor completo de flujo de red — commit `3d9b3a8`
- **Archivo**: `ovc_spy.py` (nuevo), `ovc_spy.bat` (nuevo)
- **Función**: Playwright-based network interceptor — sin proxy manual, sin configuración
- **Captura**: GET/POST, headers completos, cookies, JSONP, HAR, JSON, TXT
- **Salida**: `logs/ovc_spy_TIMESTAMP.{json,txt,har}`
- **Uso**: `ovc_spy.bat` → opción 5 (LEGA visible) para ver el widget en pantalla

### 2. ovc_capturador.py + ovc_captura.bat — Interceptor mitmproxy — commit `8d2fb7c`
- **Puerto**: 8888 (8080 ocupado por Robot Clipper V2)
- **Función**: addon mitmproxy para captura de tráfico Bookitit/citaconsular.es
- Alternativa al spy para análisis profundo offline

### 3. Fix PK LEGA — commit `45a3ae3`
- **URL correcta**: `https://www.citaconsular.es/es/hosteds/widgetdefault/25b6cfa9f112aef4ca19457abc237f7ba/`
- **PK**: `25b6cfa9f112aef4ca19457abc237f7ba` (33 chars, CON 'f' al final)
- Corregido en `.env` local, `cloudflare_worker/worker.js`, GitHub Secret `URL_SISTEMA`

### 4. Ventanas críticas locales — commit `31c95e9`
- `ovc_ventana_critica.bat` — single-shot check desde PC local (IP residencial)
- `programar_ventanas_criticas.ps1` — crea 2 tareas en Task Scheduler Windows:
  - `OVC Ventana Critica Mañana`: 02:55 AM Miami
  - `OVC Ventana Critica Tarde`: 05:55 PM Miami
- `SITIO_DIRECTO_ENABLED=1` localmente — Playwright desde IP residencial bypassa Imperva

### 5. FIX PRINCIPAL — AllowAppointment interceptor — commit `b1ce24c`
- **Descubrimiento crítico** via ovc_spy Mar 18:
  - El widget Bookitit llama automáticamente `/onlinebookings/getservices/?publickey={PK}`
  - Respuesta JSONP contiene `AllowAppointment: true/false` — flag DEFINITIVO de disponibilidad
  - `AllowAppointment: false` = sin citas (confirmado, no necesita interacción usuario)
  - `AllowAppointment: true` = HAY CITAS DISPONIBLES
  - SID LEGA confirmado: `bkt1180597`, nombre: "LEGALIZACIÓN DE DOCUMENTOS"

- **`playwright_check.py`**:
  - Eliminada transformación URL `citaconsular.es → app.bookitit.com` (innecesaria en IP residencial)
  - Añadido `page.on("response", _on_getservices)` — intercepta getservices automáticamente
  - Verifica `AllowAppointment` ANTES del análisis DOM (más fiable, más rápido)
  - Si `AllowAppointment=True` → screenshot + alerta. Si `False` → sin citas definitivo.

- **`bookitit.py`**:
  - Añadido `import json` (faltaba)
  - Nueva función `_check_getservices(pk, widget_url, ua)` como primera capa
  - Intenta `app.bookitit.com` y `www.citaconsular.es` en orden
  - Headers correctos: `X-Requested-With: XMLHttpRequest`, `Referer: widget URL`

---

## 📁 Archivos modificados

| Archivo | Sección | Cambio |
|---------|---------|--------|
| `core/playwright_check.py` | `_check_url_widget()` | Interceptor getservices + quita URL transform |
| `core/bookitit.py` | `check_url()` + nuevo | `_check_getservices()` primera capa + import json |
| `ovc_spy.py` | nuevo | Monitor flujo de red Playwright (sin proxy) |
| `ovc_spy.bat` | nuevo | Launcher interactivo 5 opciones |
| `ovc_capturador.py` | nuevo | Addon mitmproxy (puerto 8888) |
| `ovc_captura.bat` | nuevo | Launcher mitmproxy (puerto 8888) |
| `ovc_ventana_critica.bat` | nuevo | Single-shot check local con IP residencial |
| `programar_ventanas_criticas.ps1` | nuevo | Task Scheduler: 02:55 AM y 05:55 PM Miami |
| `.env` | `URL_LEGA` | PK LEGA corregido (33 chars con 'f') |
| `cloudflare_worker/worker.js` | `ALLOWED_PKS` | PK LEGA corregido |
| `cloudflare_worker/wrangler.toml` | nuevo | Config deploy CF Worker |

---

## 🔨 Commits esta sesión

| Hash | Descripción |
|------|-------------|
| `b1ce24c` | fix: interceptar AllowAppointment en getservices — detección directa de citas |
| `3d9b3a8` | feat: ovc_spy — captura completa flujo Bookitit/citaconsular via Playwright |
| `8d2fb7c` | feat: OVC Capturador — interceptor completo de tráfico Bookitit/citaconsular |
| `45a3ae3` | fix: PK LEGA corregido — 33 chars con 'f' (verificado browser residencial) |
| `31c95e9` | feat: ventanas críticas locales — alternancia IP residencial vs datacenter |

---

## 🤖 Estado Bot al cierre

- **GitHub Actions**: ✅ OK — último run `success` hace ~9 min (run #23255848084)
- **Sentinel**: ✅ CORRIENDO — 27h up, ciclo cada 30 min
- **Heartbeat**: ✅ — último hace 25 min (run #23254999178 success)
- **Bot Gestor**: 🔄 in_progress — procesando commit `b1ce24c`
- **Checks hoy**: 9 ejecutados, todos "sin citas" (correcto — widget dice "No hay horas disponibles")

---

## 🔍 Arquitectura del API descubierta (ovc_spy Mar 18)

```
Widget Bookitit — flujo completo (residencial IP):
  1. GET citaconsular.es → 302 redirect
  2. GET citaconsular.es/es/hosteds/widgetdefault/{PK}/ → HTML + TOKEN CSRF
  3. GET citaconsular.es/onlinebookings/getwidgetconfigurations/?publickey={PK} → widget config
  4. GET citaconsular.es/onlinebookings/getservices/?publickey={PK} → *** AllowAppointment ***
  5. (Si usuario selecciona servicio) GET getagendas/?services[]={SID} → agendas
  6. (Si agendas disponibles) GET getdates/?... → fechas disponibles

LEGA SID: bkt1180597 | groups_id: bkt77
TOKEN CSRF capturado: f7daf2435096169fd0dbddc82424a326860a
hCaptcha detectado en la página principal citaconsular.es (no en el widget API)
```

---

## ❌ Pendiente

- **Verificación `AllowAppointment: true` en producción**: Cuando haya citas reales,
  confirmar que el interceptor detecta correctamente. Esperamos noticias del widget.
- **Completar análisis getagendas**: Si `AllowAppointment=true`, ¿qué información
  adicional devuelve `getagendas`? Hay que correr ovc_spy en ese momento.
- **NutriScan TK2 approval**: `nutriscant-tk2-v4` job `9ea012e5` sigue awaiting_approval

---

## 🎯 Próxima sesión — empezar por:

1. **Verificar si `AllowAppointment` cambió** — ver logs de ventana crítica (02:55 AM / 05:55 PM)
2. Si hay cita → confirmar que la alerta llegó correctamente al grupo y suscriptores
3. Si no hay cita → continuar monitoreando, bot está correcto

---

## 🔑 Decisiones técnicas

| Decisión | Razón | Alternativas descartadas |
|----------|-------|--------------------------|
| `AllowAppointment` como flag primario | Campo JSON boolean directo del API — no necesita análisis DOM | texto "No hay horas disponibles" (puede fallar si widget carga lento) |
| Quitar URL transform a app.bookitit.com | IP residencial no necesita bypass — citaconsular.es funciona directo | Mantener transform (confundía AJAX calls del widget) |
| `_check_getservices` en bookitit.py | Primera capa más simple que bkt_init_widget — descubierto con ovc_spy | Esperar respuesta bkt_init_widget del flujo legacy |
| Monitor flujo (ovc_spy) con Playwright | Captura AJAX calls del widget sin proxy manual | mitmproxy (conflicto puerto 8080, requiere cert SSL manual) |

---

## ⚠️ Notas importantes

- **IP residencial es CRÍTICA**: Imperva de Bookitit bloquea todas las IPs de datacenter
  (GitHub Actions, Cloudflare Worker). Solo IP residencial (PC local) puede acceder.
- **GitHub Actions (cada 7 min)**: Con Imperva blockeando, solo puede detectar si
  `_check_getservices` logra pasar la barrera desde app.bookitit.com (experimental).
- **Ventanas críticas locales (02:55 AM + 05:55 PM Miami)**: SON LA DETECCIÓN FIABLE.
  Playwright desde IP residencial + interceptor `AllowAppointment` = detección garantizada.
- **ovc_spy.bat**: Herramienta de diagnóstico manual. Correr con opción 5 (visible)
  para ver el widget y capturar el flujo completo.
