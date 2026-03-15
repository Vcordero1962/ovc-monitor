# SESIÓN OVC: 15 Marzo 2026 — [12:00 - 17:20]

## 🎯 Objetivo
Implementar proxy residencial europeo para bypassar bloqueo Imperva en GitHub Actions.
Imperva bloquea IPs de datacenter (Azure/GitHub) — necesitábamos salida por IP de hogar real.

## ✅ Logros

### 1. Anti-WAF — Perfil Chromium persistente + CDP throttling — commit `670dfbd`
- `ovc_once.py`: `launch_persistent_context` (reemplaza `launch()`) + `actions/cache@v4`
  - Antes: browser virgen cada run → Imperva lo detecta
  - Después: perfil con cookies/storage reutilizado entre runs → parece sesión existente
- CDP `Network.emulateNetworkConditions`: emula latencia residencial 40-80ms RTT (vs 1-5ms datacenter)
- Session stamp (`ovc_session.json`): limpia cookies si sesión > 25 min (tokens consulado expiran)
- Warm-up a google.es antes de entrar al consulado (solo sin proxy)

### 2. Proxy residencial — infraestructura completa — commit `670dfbd`, `992792e`
- `ovc_once.py`: parseo con `urlparse()` — Playwright requiere server/user/pass separados (no en URL)
- Timeouts adaptativos: `to_nav=55000` con proxy, `30000` sin proxy
- Diagnóstico en workflow: curl test IP directa vs IP por proxy antes de ejecutar Python

### 3. Webshare.io — credenciales reales obtenidas
- Cuenta: `cheo06112@gmail.com` | user: `rfdaygeo` | pass: `PASS_REDACTED`
- Proxy España Madrid: `64.137.96.74:6641` — confirmado funcional (curl retorna IP proxy)
- **Diagnóstico**: proxies free de Webshare = datacenter, NO residencial → Imperva sigue bloqueando
- Configurado en GitHub Secret `HTTP_PROXY_URL` y `.env` local (con backups UK)

### 4. Flag `SITIO_DIRECTO_ENABLED` — AVC-only mode — commit `1e4ce5f`
- `ovc_once.py`: `SITIO_DIRECTO_ENABLED = os.getenv("SITIO_DIRECTO_ENABLED","1") == "1"`
  - `0` → salta `verificar_sitios_multi` completo (Playwright/Imperva) → solo AVC
  - `1` → comportamiento anterior con proxy residencial real
- `ovc_monitor.yml`: `timeout-minutes: 10 → 4`, pasa `SITIO_DIRECTO_ENABLED` como secret
- GitHub Secret `SITIO_DIRECTO_ENABLED=0` configurado
- **Resultado**: run bajó de 4+ min a ~59 segundos

## 📁 Archivos modificados

| Archivo | Sección | Cambio |
|---------|---------|--------|
| `ovc_once.py` | constantes | `HTTP_PROXY_URL`, `SITIO_DIRECTO_ENABLED`, `USER_DATA_DIR`, `SESSION_STAMP` |
| `ovc_once.py` | `verificar_url_widget()` | `launch_persistent_context` + proxy_cfg + CDP throttle + session age |
| `ovc_once.py` | `__main__` | bloque `if SITIO_DIRECTO_ENABLED:` wrapping sitio check |
| `.github/workflows/ovc_monitor.yml` | `timeout-minutes` | 10 → 4 |
| `.github/workflows/ovc_monitor.yml` | `Verificar disponibilidad` env | `+SITIO_DIRECTO_ENABLED`, `+HTTP_PROXY_URL` |
| `.github/workflows/ovc_monitor.yml` | nuevo step | "Test proxy (diagnostico)" — curl IP directa vs proxy |
| `.github/workflows/ovc_monitor.yml` | nuevo step | "Cache perfil Chromium" — `actions/cache@v4` |
| `.env` | proxy section | `HTTP_PROXY_URL` con creds reales Webshare + `SITIO_DIRECTO_ENABLED=0` |

## 🔨 Commits

| Hash | Mensaje |
|------|---------|
| `670dfbd` | fix: proxy credentials separados para Playwright (server/username/password) |
| `70cf5a0` | fix: timeouts adaptativos con proxy + workflow 10 min |
| `28bc6e2` | chore: diagnostico proxy — curl test antes de Playwright |
| `992792e` | fix: quitar if:secrets en step proxy — invalido en GH Actions |
| `1e4ce5f` | feat: SITIO_DIRECTO_ENABLED flag — AVC-only mode hasta proxy residencial real |

## 🤖 Estado Bot al cierre

- **GitHub Actions**: ✅ OK — `completed success` ~1m36s (AVC-only mode)
- **Último run**: hace ~3 min — success (schedule)
- **Sentinel**: ✅ corriendo (`ovc-sentinel` up 3 hours)
- **Último heartbeat**: pendiente verificar (heartbeat cada 4h)
- **Modo activo**: `SITIO_DIRECTO_ENABLED=0` — solo canal AVC

## ❌ Pendiente

- **Proxy residencial real**: Webshare free = datacenter → Imperva lo bloquea igual que GH Actions.
  Para activar check directo: comprar Webshare Static Residential (~$3/mes) u Oxylabs/BrightData.
  Cuando lo tengas: actualizar `HTTP_PROXY_URL` + `gh secret set SITIO_DIRECTO_ENABLED --body "1"`
- **`timeout-minutes`**: cuando se active SITIO_DIRECTO volver a subir a 10 en el workflow
- **Heartbeat verificación**: no se verificó si llega correctamente cada 4h

## 🎯 Próxima sesión — empezar por:

1. Verificar heartbeat: `gh run list --repo Vcordero1962/ovc-monitor --limit 10` — buscar `ovc_heartbeat.yml`
2. Si se quiere activar check directo: contratar Webshare Static Residential → actualizar secrets

## 🔑 Decisiones técnicas

| Decisión | Razón | Alternativas descartadas |
|----------|-------|--------------------------|
| `SITIO_DIRECTO_ENABLED=0` por defecto | Proxy datacenter inútil contra Imperva, mejor AVC solo que 3 min de reintentos | Mantener reintentos con datacenter (desperdicio de minutos GH Actions) |
| Webshare free como "listo para residencial" | Ya está la infraestructura — solo cambiar IP cuando sea residencial | Eliminar toda la lógica proxy (futuro inmediato) |
| `urlparse()` para separar creds proxy | Playwright no acepta credenciales embebidas en URL format `http://user:pass@host` | Pasar proxy como string (no funciona) |
| `launch_persistent_context` vs `launch()` | Reutiliza cookies entre runs GitHub Actions vía cache — simula sesión existente | Nuevo contexto cada vez (Imperva detecta browser virgen) |

## ⚠️ Alertas

- **WiFi del usuario**: incidente Mar 14 — Docker Desktop Hyper-V adapter causa desconexiones ocasionales. No es problema del código OVC. Si vuelve: deshabilitar adaptadores virtuales en Administrador de dispositivos.
- **Webshare proxies free**: se renuevan cada X tiempo — si el bot falla con proxy, verificar que `64.137.96.74:6641` sigue activo en dashboard.webshare.io
- **GitHub Actions quota**: ~50 min/día × 15 días = ~750 min gastados de 2,000/mes. OK por ahora.
