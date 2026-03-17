#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
playwright_check.py — Verificación directa del widget via Playwright + Chromium.

Anti-WAF completo:
  - Perfil persistente (user-data-dir cacheado entre GitHub Actions runs)
  - Stealth script dinámico (elimina webdriver markers, simula hardware real)
  - CDP latency throttling (emula conexión residencial)
  - Warm-up navigation (Google → evita browser virgen)
  - UA + viewport + locale aleatorio en cada run
  - Imperva gate bypass via click en botón "Continuar"
  - Gestión de edad de sesión (limpia cookies si el token expiró)

Funciones públicas:
  check_all(tramites: list)   → list[(tramite, nombre, url, screenshot_bytes)]
"""

import re
import json
import random
import time
from pathlib import Path

from core.config import (
    SERVICIOS, USER_AGENTS, VIEWPORTS,
    USER_DATA_DIR, SESSION_STAMP, SESSION_MAX_MIN,
    HTTP_PROXY_URL, PLAYWRIGHT_PROXY_ENABLED, TEXTO_BLOQUEADO,
    get_url_for_tramite,
)
from core.logger import info, warn, error
from core.security import validate_widget_url, SecurityError


# ── Helpers ────────────────────────────────────────────────────────────────────

def _human_sleep(min_s: float, max_s: float):
    media = (min_s + max_s) / 2
    std   = (max_s - min_s) / 4
    t = max(min_s, min(max_s, random.gauss(media, std)))
    time.sleep(t)


def _get_session_age_min() -> float | None:
    """Retorna edad de la sesión en minutos, o None si no hay stamp."""
    try:
        from datetime import datetime, timezone
        data = json.loads(SESSION_STAMP.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except Exception:
        return None


def _update_session_stamp():
    try:
        from datetime import datetime, timezone
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_STAMP.write_text(
            json.dumps({"timestamp": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
    except Exception as e:
        warn(f"Session stamp error: {e}")


def _make_stealth_script(viewport: dict) -> str:
    """Genera el script de stealth adaptado al viewport elegido."""
    w, h   = viewport["width"], viewport["height"]
    plat   = "Linux armv8l" if w < 500 else "Win32"
    cores  = random.choice([4, 8, 12, 16])
    mem    = random.choice([4, 8, 16])
    return f"""
Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
delete window.__playwright; delete window.__pwInitScripts;
try {{ delete window._phantom; }} catch(e) {{}}
try {{ delete window.callPhantom; }} catch(e) {{}}
Object.defineProperty(navigator, 'plugins', {{
    get: () => {{ const a=[1,2,3,4,5]; a.item=(i)=>a[i]||null; a.namedItem=()=>null; a.refresh=()=>{{}}; return a; }}
}});
Object.defineProperty(navigator, 'languages', {{ get: () => ['es-ES','es','en-US','en'] }});
Object.defineProperty(navigator, 'platform',  {{ get: () => '{plat}' }});
Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {cores} }});
Object.defineProperty(navigator, 'deviceMemory',        {{ get: () => {mem}   }});
Object.defineProperty(screen, 'width',       {{ get: () => {w}      }});
Object.defineProperty(screen, 'height',      {{ get: () => {h}      }});
Object.defineProperty(screen, 'availWidth',  {{ get: () => {w}      }});
Object.defineProperty(screen, 'availHeight', {{ get: () => {h} - 40 }});
Object.defineProperty(screen, 'colorDepth',  {{ get: () => 24       }});
Object.defineProperty(screen, 'pixelDepth',  {{ get: () => 24       }});
window.chrome = {{
    runtime: {{ id:undefined, connect:()=>{{}}, sendMessage:()=>{{}} }},
    loadTimes: function(){{ return {{}}; }},
    csi:       function(){{ return {{}}; }},
    app: {{ isInstalled: false }},
}};
const _oq = window.navigator.permissions.query.bind(navigator.permissions);
window.navigator.permissions.query = (p) =>
    p.name === 'notifications'
        ? Promise.resolve({{ state: Notification.permission }})
        : _oq(p);
"""


def _build_proxy_cfg() -> dict | None:
    """Construye config de proxy para Playwright si está habilitado."""
    if not HTTP_PROXY_URL or not PLAYWRIGHT_PROXY_ENABLED:
        reason = "PLAYWRIGHT_PROXY_ENABLED=0" if HTTP_PROXY_URL else "HTTP_PROXY_URL no configurado"
        info(f"Playwright proxy: no usado ({reason}) — IP directa del runner")
        return None

    try:
        from urllib.parse import urlparse
        p = urlparse(HTTP_PROXY_URL)
        cfg = {
            "server":   f"{p.scheme}://{p.hostname}:{p.port}",
            "username": p.username or "",
            "password": p.password or "",
        }
        info(f"Playwright proxy: {p.scheme}://{p.hostname}:{p.port}")
        return cfg
    except Exception as e:
        warn(f"Proxy: error parseando URL — {e}")
        return None


# ── Check de una URL ───────────────────────────────────────────────────────────

def _check_url_widget(url: str) -> tuple:
    """
    Verifica disponibilidad de un widget via Playwright.

    Retorna (disponible, screenshot_bytes, bloqueado_definitivo):
      (True,  bytes, False) → cita disponible
      (False, None,  True)  → sin citas confirmado — no reintentar
      (False, None,  False) → bloqueo temporal / timeout — reintentar
    """
    # Validar URL antes de lanzar browser
    try:
        url = validate_widget_url(url)
    except SecurityError as e:
        error(f"Playwright: URL rechazada — {e}")
        return False, None, True

    # Transformar URL de citaconsular.es → app.bookitit.com para evitar Imperva WAF
    # Imperva bloquea el JSONP /onlinebookings/main/ desde IPs de datacenter.
    # app.bookitit.com sirve el mismo widget sin WAF.
    bkt_direct_url = url
    if "citaconsular.es" in url and "/es/hosteds/widgetdefault/" in url:
        bkt_direct_url = url.replace("www.citaconsular.es", "app.bookitit.com") \
                            .replace("citaconsular.es", "app.bookitit.com")
        info(f"URL transformada → Bookitit directo (bypass Imperva): {bkt_direct_url[:80]}")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWT

        ua       = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORTS)
        is_mob   = viewport["width"] < 500
        stealth  = _make_stealth_script(viewport)
        proxy    = _build_proxy_cfg()

        info(f"Playwright UA: {ua[:70]}...")
        info(f"Playwright viewport: {viewport['width']}x{viewport['height']} {'(mobile)' if is_mob else '(desktop)'}")

        # Gestión de sesión
        age = _get_session_age_min()
        info(f"Sesión cache: {'nueva' if age is None else f'{age:.1f} min de antigüedad'}")
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Timeouts adaptativos: proxy residencial más lento
        to_nav    = 55000 if proxy else 30000
        to_widget = 60000 if proxy else 35000

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(USER_DATA_DIR),
                headless=True,
                proxy=proxy,
                args=[
                    "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars", "--disable-extensions",
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-popup-blocking", "--disable-translate",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding", "--disable-quic",
                    f"--window-size={viewport['width']},{viewport['height']}",
                ],
                user_agent=ua,
                viewport=viewport,
                locale="es-ES",
                timezone_id="America/Havana",
                is_mobile=is_mob,
                has_touch=is_mob,
                extra_http_headers={
                    "Accept-Language":           "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest":            "document",
                    "Sec-Fetch-Mode":            "navigate",
                    "Sec-Fetch-Site":            "none",
                    "Cache-Control":             "max-age=0",
                },
            )
            ctx.add_init_script(stealth)

            # Limpiar cookies si la sesión expiró
            if age is not None and age > SESSION_MAX_MIN:
                info(f"Sesión expirada ({age:.1f} min > {SESSION_MAX_MIN}) — limpiando cookies")
                ctx.clear_cookies()

            page = ctx.new_page()
            # Auto-aceptar dialogs JS (el gate de citaconsular.es muestra "Welcome/Bienvenido")
            page.on("dialog", lambda d: d.accept())
            try:
                # CDP: emular latencia residencial (datacenter = 1-5 ms, casa = 40-80 ms)
                try:
                    cdp     = ctx.new_cdp_session(page)
                    dl_bps  = random.randint(1_500_000, 4_000_000)
                    ul_bps  = random.randint(500_000,   1_500_000)
                    latency = random.randint(40, 80)
                    cdp.send("Network.emulateNetworkConditions", {
                        "offline":            False,
                        "downloadThroughput": dl_bps // 8,
                        "uploadThroughput":   ul_bps // 8,
                        "latency":            latency,
                    })
                    info(f"CDP latencia: {dl_bps // 1000} Kbps DL, {latency} ms RTT")
                except Exception as cdp_e:
                    info(f"CDP (ignorado): {cdp_e}")

                # Warm-up: solo sin proxy (Google bloquea proxies residenciales)
                if not proxy:
                    try:
                        info("Warm-up: buscando en Google...")
                        page.goto(
                            "https://www.google.es/search?q=consulado+espana+cuba+cita+previa",
                            timeout=20000, wait_until="domcontentloaded",
                        )
                        _human_sleep(2.0, 4.0)
                        page.evaluate("window.scrollTo({top: Math.floor(Math.random()*300+100), behavior:'smooth'})")
                        _human_sleep(1.0, 2.5)
                    except Exception:
                        info("Warm-up: omitido")
                else:
                    info("Warm-up: omitido (proxy activo)")

                # Handshake: cookie de sesión como usuario real
                page.goto("https://www.citaconsular.es", timeout=to_nav, wait_until="domcontentloaded")
                _human_sleep(1.0, 2.8)
                page.evaluate("window.scrollTo({top: Math.floor(Math.random()*200+50), behavior:'smooth'})")
                _human_sleep(0.4, 1.0)
                page.evaluate("window.scrollTo({top: 0, behavior:'smooth'})")
                _human_sleep(0.3, 0.8)

                try:
                    page.click(
                        "button:has-text('Aceptar'), button:has-text('Accept'), button:has-text('Entrar')",
                        timeout=5000,
                    )
                    _human_sleep(0.5, 1.5)
                except Exception:
                    pass

                # Interceptar el endpoint JSONP de Bookitit via page.route()
                # page.route() captura el body completo antes de que llegue al browser
                # (page.on('response') no puede leer body si es muy pequeño o streaming)
                bkt_responses: list = []

                def _route_jsonp(route):
                    try:
                        resp = route.fetch()
                        body = resp.text()
                        info(f"JSONP interceptado: {len(body)} chars — {route.request.url[:70]}")
                        bkt_responses.append(body)
                        route.fulfill(response=resp)
                    except Exception as re:
                        info(f"JSONP route error (ignorado): {re}")
                        route.continue_()

                ctx.route("**/onlinebookings/main/**", _route_jsonp)

                # Navegar al widget directo en Bookitit (bypass Imperva de citaconsular.es)
                page.goto(bkt_direct_url, timeout=to_widget, wait_until="networkidle")
                _human_sleep(1.2, 4.0)

                # Imperva gate bypass (por si acaso — normalmente no aplica en bookitit.com)
                try:
                    if page.locator('input[name="token"]').count() > 0:
                        info("Gate detectado — enviando token via click...")
                        page.locator(
                            'button[type="submit"], input[type="submit"], '
                            'button:has-text("Continuar"), button:has-text("Continue"), '
                            'a:has-text("Continuar"), a:has-text("Continue")'
                        ).first.click(timeout=8000)
                        page.wait_for_load_state("networkidle", timeout=25000)
                        info(f"Gate superado — {len(page.content())} chars")
                        _human_sleep(0.5, 1.5)
                except Exception as gate_e:
                    info(f"Gate handling (ignorado): {gate_e}")

                page.evaluate("window.scrollTo({top: Math.floor(Math.random()*150+30), behavior:'smooth'})")
                _human_sleep(0.5, 1.2)

                try:
                    page.wait_for_selector(
                        "#bk-widget, #bookitit-widget, .bk-container, #datetime, "
                        ".bk-time-slot, .bk-slot, [class*='bk-hour'], [class*='bk-time']",
                        timeout=20000,
                    )
                    _human_sleep(2.0, 3.0)
                except Exception:
                    pass

                _human_sleep(0.4, 1.5)

                # Recopilar contenido: página principal + respuestas de red interceptadas
                # (los iframes cross-origin no son legibles via DOM — usamos network interception)
                contenido = page.content()
                bkt_data = " ".join(bkt_responses)
                contenido_total = contenido + bkt_data

                info(f"Playwright contenido: {len(contenido)} chars página + {len(bkt_data)} chars JSONP ({len(bkt_responses)} resp)")
                if bkt_data:
                    info(f"JSONP preview: {bkt_data[:400].replace(chr(10), ' ')}")
                _update_session_stamp()

                if TEXTO_BLOQUEADO in contenido_total:
                    info("Playwright: sin horas disponibles (confirmado)")
                    return False, None, True

                slots_hora = len(re.findall(r'\b\d{2}:\d{2}\b', contenido_total))
                indicadores = [
                    "Selecciona", "Confirmar", "bk-time-slot", "bk-slot", "bk-hour",
                    "Huecos libres", "Hueco libre", "Huecos Libres", "Hueco Libre",
                    "Cambiar de día", "huecos_libres", "free_slots",
                ]
                widget_con_slots = slots_hora >= 3 or any(i in contenido_total for i in indicadores)

                if widget_con_slots:
                    info(f"Playwright: CITA DISPONIBLE — {slots_hora} slots hora detectados")
                    screenshot = page.screenshot(type="png", full_page=False)
                    return True, screenshot, False

                if "bkt_init_widget" in contenido_total or "bookitit" in contenido_total.lower():
                    info("Playwright: widget cargado pero sin slots disponibles (JSONP sin citas)")
                    return False, None, True

                info("Playwright: widget vacío (posible bloqueo por IP o error)")
                return False, None, False

            except PWT:
                warn("Playwright: timeout")
                return False, None, False
            finally:
                ctx.close()

    except Exception as e:
        error(f"Playwright error inesperado: {e}", exc=e)
        return False, None, False


def _check_url_con_retry(url: str, max_intentos: int = 2) -> tuple:
    """
    Wrapper con retry sobre _check_url_widget.
    Solo reintenta en bloqueo temporal, no en bloqueado_definitivo.

    Retorna (disponible, screenshot_bytes).
    """
    delays = [0, 8, 20]
    for intento in range(max_intentos):
        if intento > 0:
            espera = delays[intento]
            info(f"Retry #{intento}/{max_intentos - 1} en {espera}s...")
            time.sleep(espera)

        disponible, screenshot, definitivo = _check_url_widget(url)
        if disponible:
            return True, screenshot
        if definitivo:
            info("Bloqueo definitivo — sin más reintentos")
            return False, None

    info(f"Agotados {max_intentos} intentos — sin disponibilidad confirmada")
    return False, None


# ── Función pública ────────────────────────────────────────────────────────────

def check_all(tramites: list) -> list:
    """
    Verifica el widget oficial de citaconsular.es para cada tramite con URL configurada.

    Retorna lista de (tramite, nombre, url, screenshot_bytes) con disponibilidad.
    """
    hits = []
    for i, tramite in enumerate(tramites):
        servicio = SERVICIOS[tramite]
        url = get_url_for_tramite(tramite)

        if not url:
            info(f"Playwright [{tramite}]: sin URL configurada — omitiendo")
            continue

        info(f"Playwright verificando [{tramite}] {servicio['nombre']}...")
        disponible, screenshot = _check_url_con_retry(url)

        if disponible:
            hits.append((tramite, servicio["nombre"], url, screenshot))

        if i < len(tramites) - 1:
            _human_sleep(2.0, 5.0)

    return hits
