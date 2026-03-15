#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC-Once — Check único para GitHub Actions / nube
- Monitorea TODOS los servicios consulares simultáneamente (AVC_TRAMITE=ALL)
- Anti-detección: sleep aleatorio + user-agent rotativo + viewport random
- Alerta Telegram con botón "ABRIR AHORA" (un toque → captcha directo)
"""

import os
import re
import sys
import time
import random
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

URL_SISTEMA        = os.getenv("URL_SISTEMA", "")   # Legacy — URL del widget LEGA
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
AVC_TRAMITE        = os.getenv("AVC_TRAMITE", "ALL").upper()  # "ALL" o "LMD,LEGA" o "LMD"

URL_AVC         = "https://t.me/s/AsesorVirtualC"
TEXTO_BLOQUEADO = "No hay horas disponibles"

# ─── Catálogo de servicios consulares ────────────────────────────────────────
# Cada servicio tiene:
#   nombre    → texto amigable para alertas
#   keywords  → palabras clave a buscar en el canal AVC
#   url_env   → variable de entorno con la URL del widget de citaconsular.es
#
# Para agregar la URL de un servicio nuevo:
#   1. Consigue la URL del widget en citaconsular.es
#   2. Agrega al .env: URL_PASAPORTE=https://www.citaconsular.es/...
#   3. El bot la usará automáticamente en el siguiente run

SERVICIOS = {
    "LEGA": {
        "nombre":   "Legalizaciones (LEGA)",
        "keywords": ["LEGALIZACI", "LEGALIZ", "LEGA"],
        "url_env":  "URL_LEGA",
    },
    "LMD": {
        "nombre":   "Ley Memoria Democratica (LMD)",
        "keywords": ["LMD", "MEMORIA DEMOCR", "CREDENCIALES LMD", "CIUDADAN"],
        "url_env":  "URL_LMD",
    },
    "PASAPORTE": {
        "nombre":   "Pasaporte / DNI",
        "keywords": ["PASAPORTE", "PASAPORTES", "DNI", "DOCUMENTO NACIONAL"],
        "url_env":  "URL_PASAPORTE",
    },
    "VISADO": {
        "nombre":   "Visados",
        "keywords": ["VISADO", "VISADOS", "VISA SCHENGEN", "VISA NACIONAL"],
        "url_env":  "URL_VISADO",
    },
    "MATRIMONIO": {
        "nombre":   "Matrimonio / Registro Civil",
        "keywords": ["MATRIMONIO", "TRANSCRIPCI", "REGISTRO CIVIL", "ACTA MATRIMON"],
        "url_env":  "URL_MATRIMONIO",
    },
    "NACIMIENTO": {
        "nombre":   "Nacimiento / Fe de Vida",
        "keywords": ["NACIMIENTO", "FE DE VIDA", "ACTA DE NACI", "ACTA NACIM"],
        "url_env":  "URL_NACIMIENTO",
    },
    "NOTARIAL": {
        "nombre":   "Tramites Notariales / Apostilla",
        "keywords": ["NOTARIAL", "APOSTILLA", "PODER NOTARIAL", "NOTARI"],
        "url_env":  "URL_NOTARIAL",
    },
}

# Frases del canal AVC que indican que están por abrir citas
AVC_ALERTAS = [
    "CITAS QUE SER", "SERAN HABILITADAS", "PROXIMA FECHA",
    "HABRAN CITAS", "SE ABRIRAN", "DISPONIBLES", "HABILITADAS",
    "APERTURA", "ABRIRA CITAS", "NUEVAS CITAS", "FECHA DE APERTURA",
    "ABRIRAN CITAS", "HABRAN TURNOS",
]

# Pool de user-agents reales — desktop + mobile — rota en cada ejecución
USER_AGENTS = [
    # Desktop Chrome — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Desktop Chrome — Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Desktop Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Desktop Safari — Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    # Mobile Chrome — Android (simula usuario móvil real)
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36",
    # Mobile Safari — iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
]

# Resoluciones — desktop + mobile
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1536, "height": 864},
    {"width": 390,  "height": 844},   # iPhone 14
    {"width": 412,  "height": 915},   # Pixel 7
]

def _make_stealth_script(viewport: dict) -> str:
    """Genera el script de stealth con los valores reales del viewport actual."""
    w = viewport["width"]
    h = viewport["height"]
    # Simular plataforma según si es mobile (ancho < 500)
    platform = "Linux armv8l" if w < 500 else "Win32"
    cores = random.choice([4, 8, 12, 16])
    mem   = random.choice([4, 8, 16])
    return f"""
// Eliminar marcadores de automatización
Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
delete window.__playwright;
delete window.__pwInitScripts;
try {{ delete window._phantom; }} catch(e) {{}}
try {{ delete window.callPhantom; }} catch(e) {{}}

// Plugins — simular browser real
Object.defineProperty(navigator, 'plugins', {{
    get: () => {{
        const arr = [1, 2, 3, 4, 5];
        arr.item = (i) => arr[i] || null;
        arr.namedItem = (n) => null;
        arr.refresh = () => {{}};
        return arr;
    }}
}});

// Idiomas y plataforma
Object.defineProperty(navigator, 'languages', {{ get: () => ['es-ES', 'es', 'en-US', 'en'] }});
Object.defineProperty(navigator, 'platform',  {{ get: () => '{platform}' }});

// Hardware — simular máquina real
Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {cores} }});
Object.defineProperty(navigator, 'deviceMemory',        {{ get: () => {mem}   }});

// Screen — ajustar al viewport del contexto
Object.defineProperty(screen, 'width',       {{ get: () => {w}      }});
Object.defineProperty(screen, 'height',      {{ get: () => {h}      }});
Object.defineProperty(screen, 'availWidth',  {{ get: () => {w}      }});
Object.defineProperty(screen, 'availHeight', {{ get: () => {h} - 40 }});
Object.defineProperty(screen, 'colorDepth',  {{ get: () => 24       }});
Object.defineProperty(screen, 'pixelDepth',  {{ get: () => 24       }});

// APIs Chrome completas — sin chrome = detectado como bot
window.chrome = {{
    runtime:    {{ id: undefined, connect: () => {{}}, sendMessage: () => {{}} }},
    loadTimes:  function() {{ return {{}}; }},
    csi:        function() {{ return {{}}; }},
    app:        {{ isInstalled: false }},
}};

// Permisos — respuesta realista
const _origQuery = window.navigator.permissions.query.bind(navigator.permissions);
window.navigator.permissions.query = (p) =>
    p.name === 'notifications'
        ? Promise.resolve({{ state: Notification.permission }})
        : _origQuery(p);
"""


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def human_sleep(min_s: float, max_s: float):
    """Sleep con distribución normal — más natural que uniforme.
    La mayoría de las esperas caen cerca de la media, con outliers ocasionales."""
    media = (min_s + max_s) / 2
    std   = (max_s - min_s) / 4
    t = max(min_s, min(max_s, random.gauss(media, std)))
    time.sleep(t)


def get_tramites_activos() -> list:
    """
    Retorna lista de códigos de tramite a vigilar.
    ALL → todos los servicios.
    "LMD,LEGA" → solo esos dos.
    "LMD" → solo LMD (backwards compat).
    """
    if AVC_TRAMITE == "ALL":
        return list(SERVICIOS.keys())
    tramites = [t.strip() for t in AVC_TRAMITE.split(",") if t.strip() in SERVICIOS]
    if not tramites:
        log(f"WARN: AVC_TRAMITE='{AVC_TRAMITE}' no reconocido — usando ALL")
        return list(SERVICIOS.keys())
    return tramites


def enviar_telegram(msg: str, url_boton: str = ""):
    """Envía alerta de texto al grupo con botón ABRIR AHORA."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado")
        return
    try:
        import json as _json
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        url_destino = url_boton or URL_SISTEMA
        if url_destino:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": "ABRIR AHORA", "url": url_destino}]]
            }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload, timeout=10,
        )
        log(f"Telegram texto: {'OK' if r.ok else f'error {r.status_code} — {r.text[:80]}'}")
    except Exception as e:
        log(f"Telegram error: {e}")


def enviar_foto_telegram(caption: str, foto_bytes: bytes, url_boton: str = ""):
    """Envía screenshot del widget como foto al grupo con botón ABRIR AHORA.
    Si el envío de foto falla, cae a texto plano como fallback."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado")
        return
    import json as _json
    url_destino = url_boton or URL_SISTEMA
    reply_markup = ""
    if url_destino:
        reply_markup = _json.dumps({
            "inline_keyboard": [[{"text": "ABRIR AHORA", "url": url_destino}]]
        })
    try:
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}
        if reply_markup:
            data["reply_markup"] = reply_markup
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
            data=data,
            files={"photo": ("screenshot.png", foto_bytes, "image/png")},
            timeout=30,
        )
        if r.ok:
            log("Telegram foto: OK")
        else:
            log(f"Telegram foto: error {r.status_code} — {r.text[:80]}")
            log("  Fallback: enviando texto sin foto")
            enviar_telegram(caption, url_boton)
    except Exception as e:
        log(f"Telegram foto error: {e}")
        enviar_telegram(caption, url_boton)


def verificar_url_widget(url: str) -> tuple:
    """
    Verifica si el widget tiene disponibilidad.
    Retorna (disponible, screenshot_bytes, bloqueado_definitivo):
      (True,  bytes, False) → cita disponible, bytes = screenshot PNG del widget
      (False, None,  True)  → "No hay horas disponibles" — no reintentar
      (False, None,  False) → posible bloqueo temporal / captcha — reintentar
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWT

        ua       = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORTS)
        is_mobile = viewport["width"] < 500
        log(f"  UA: {ua[:70]}...")
        log(f"  Viewport: {viewport['width']}x{viewport['height']} {'(mobile)' if is_mobile else '(desktop)'}")

        stealth = _make_stealth_script(viewport)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-extensions",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-popup-blocking",
                    "--disable-translate",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    f"--window-size={viewport['width']},{viewport['height']}",
                ],
            )
            ctx = browser.new_context(
                user_agent=ua,
                viewport=viewport,
                locale="es-ES",
                timezone_id="America/Havana",
                is_mobile=is_mobile,
                has_touch=is_mobile,
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
            # Stealth dinámico — fingerprint ajustado al viewport elegido
            ctx.add_init_script(stealth)
            page = ctx.new_page()
            try:
                # Paso 1: handshake — obtener cookie de sesión como usuario real
                page.goto("https://www.citaconsular.es", timeout=30000, wait_until="domcontentloaded")
                human_sleep(1.0, 2.8)

                # Simular scroll humano al llegar — Imperva lo detecta si no hay movimiento
                page.evaluate("window.scrollTo({top: Math.floor(Math.random()*200+50), behavior:'smooth'})")
                human_sleep(0.4, 1.0)
                page.evaluate("window.scrollTo({top: 0, behavior:'smooth'})")
                human_sleep(0.3, 0.8)

                try:
                    page.click("button:has-text('Aceptar'), button:has-text('Accept'), button:has-text('Entrar')", timeout=5000)
                    human_sleep(0.5, 1.5)
                except Exception:
                    pass

                # Paso 2: navegar al widget
                page.goto(url, timeout=35000, wait_until="domcontentloaded")
                human_sleep(1.2, 4.0)

                # Scroll simulado en el widget — comportamiento humano
                page.evaluate("window.scrollTo({top: Math.floor(Math.random()*150+30), behavior:'smooth'})")
                human_sleep(0.5, 1.2)

                try:
                    page.wait_for_selector(
                        "#bk-widget, #bookitit-widget, .bk-container, #datetime",
                        timeout=25000,
                    )
                except PWT:
                    pass

                # Micro-pausa final antes de leer el DOM
                human_sleep(0.4, 1.5)
                contenido = page.content()
                log(f"  Contenido recibido: {len(contenido)} chars")

                if TEXTO_BLOQUEADO in contenido:
                    log("  Sitio: bloqueado explicitamente (sin horas)")
                    return False, None, True   # bloqueado definitivo — no reintentar

                indicadores = ["bookitit", "bk-widget", "datetime", "Selecciona", "Confirmar", "horas"]
                widget_ok = any(i in contenido for i in indicadores)
                if widget_ok:
                    log("  Sitio: CITA DISPONIBLE — capturando screenshot")
                    screenshot = page.screenshot(type="png", full_page=False)
                    return True, screenshot, False
                else:
                    log("  Sitio: widget vacio (posible bloqueo por IP o captcha)")
                    return False, None, False  # bloqueo temporal — reintentar

            except PWT:
                log("  Sitio: timeout")
                return False, None, False      # timeout — reintentar
            finally:
                browser.close()

    except Exception as e:
        log(f"  Playwright error: {e}")
        return False, None, False


def verificar_url_con_retry(url: str, max_intentos: int = 3) -> tuple:
    """
    Wrapper con retry exponencial sobre verificar_url_widget.
    Solo reintenta si fue bloqueo temporal (no en bloqueo definitivo).
    Delays: intento 1=inmediato, intento 2=+8s, intento 3=+20s
    Retorna (disponible, screenshot_bytes).
    """
    delays = [0, 8, 20]
    for intento in range(max_intentos):
        if intento > 0:
            espera = delays[intento]
            log(f"  Retry #{intento}/{max_intentos-1} en {espera}s...")
            time.sleep(espera)
        disponible, screenshot, bloqueado_definitivo = verificar_url_widget(url)
        if disponible:
            return True, screenshot
        if bloqueado_definitivo:
            log("  Bloqueo definitivo — sin mas reintentos")
            return False, None
        # Bloqueo temporal → continuar el loop
    log(f"  Agotados {max_intentos} intentos — sin disponibilidad confirmada")
    return False, None


def verificar_sitios_multi(tramites: list) -> list:
    """
    Verifica el widget oficial para cada tramite que tenga URL configurada.
    Retorna lista de (tramite, nombre, url, screenshot_bytes) con disponibilidad.
    """
    hits = []
    for tramite in tramites:
        servicio = SERVICIOS[tramite]
        url = os.getenv(servicio["url_env"], "")
        # Fallback: si es LEGA y no tiene URL_LEGA → usar URL_SISTEMA legacy
        if not url and tramite == "LEGA" and URL_SISTEMA:
            url = URL_SISTEMA
        if not url:
            log(f"  Sitio [{tramite}]: sin URL configurada ({servicio['url_env']} vacío) — omitiendo")
            continue
        log(f"  Verificando sitio [{tramite}] {servicio['nombre']}...")
        disponible, screenshot = verificar_url_con_retry(url)
        if disponible:
            hits.append((tramite, servicio["nombre"], url, screenshot))
        # Pausa entre servicios para no parecer bot agresivo
        if tramites.index(tramite) < len(tramites) - 1:
            human_sleep(2.0, 5.0)
    return hits


def verificar_avc_todos(tramites: list) -> list:
    """
    Verifica el canal AVC para todos los tramites de la lista en UNA sola petición.
    Retorna lista de (tramite, nombre, fragmento) para cada servicio con alerta.
    """
    try:
        ua = random.choice(USER_AGENTS)
        headers = {
            "User-Agent":                ua,
            "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language":           "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding":           "gzip, deflate, br",
            "Connection":                "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest":            "document",
            "Sec-Fetch-Mode":            "navigate",
            "Sec-Fetch-Site":            "none",
            "Cache-Control":             "max-age=0",
        }
        resp = requests.get(URL_AVC, headers=headers, timeout=15)
        if not resp.ok:
            log(f"  AVC no accesible: HTTP {resp.status_code}")
            return []

        html = resp.text
        ahora  = datetime.now(timezone.utc)
        limite = ahora - timedelta(hours=48)

        # Extraer mensajes recientes (últimas 48h)
        patron = re.findall(
            r'<time[^>]+datetime="([^"]+)"[^>]*>.*?'
            r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE,
        )

        html_reciente = ""
        for ts_str, texto in patron:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= limite:
                    html_reciente += " " + texto
            except Exception:
                pass

        if not html_reciente.strip():
            log("  AVC: sin mensajes en 48h")
            return []

        bloque = html_reciente.upper()

        # Verificar si hay alguna frase de alerta en el bloque completo
        hay_alerta_general = any(a in bloque for a in AVC_ALERTAS)
        if not hay_alerta_general:
            log("  AVC: sin frases de alerta en el canal")
            return []

        # Buscar qué tramites específicos se mencionan junto a la alerta
        hits = []
        for tramite in tramites:
            servicio  = SERVICIOS[tramite]
            keywords  = servicio["keywords"]
            if any(kw in bloque for kw in keywords):
                fragmento = re.sub(r'<[^>]+>', '', html_reciente)[:300].strip()
                log(f"  AVC HIT [{tramite}]: {servicio['nombre']}")
                hits.append((tramite, servicio["nombre"], fragmento))

        return hits

    except Exception as e:
        log(f"  AVC error: {e}")
        return []


if __name__ == "__main__":
    # Sleep gaussiano al inicio — rompe el patrón regular del cron
    # Distribución normal: mayoría entre 30-60s, outliers ocasionales
    espera = max(10, min(90, int(random.gauss(45, 20))))
    log(f"Anti-deteccion: esperando {espera}s antes de consultar...")
    time.sleep(espera)

    tramites = get_tramites_activos()
    hora = datetime.now().strftime("%H:%M del %d/%m/%Y")
    log(f"=== OVC check — {hora} — tramites: {', '.join(tramites)} ===")

    if not URL_SISTEMA and not any(os.getenv(SERVICIOS[t]["url_env"], "") for t in tramites):
        log("WARN: ninguna URL de widget configurada — solo se verificara AVC")

    # 1. Sitio oficial (verifica widgets con URL configurada)
    log(f"Verificando sitio oficial ({len(tramites)} servicios)...")
    hits_sitio = verificar_sitios_multi(tramites)
    for tramite, nombre, url, screenshot in hits_sitio:
        log(f"*** CITA DISPONIBLE en sitio oficial: {nombre} ***")
        caption = (
            f"CITA DISPONIBLE — Consulado Espana\n"
            f"Servicio: {nombre}\n"
            f"Detectado: {hora}\n\n"
            f"Toca el boton para abrir el captcha YA:"
        )
        if screenshot:
            enviar_foto_telegram(caption, screenshot, url_boton=url)
        else:
            enviar_telegram(caption, url_boton=url)

    if hits_sitio:
        sys.exit(0)
    log("Sitio oficial: sin disponibilidad")

    # 2. Canal AVC (una sola petición, verifica todos los tramites)
    log(f"Verificando canal AVC ({len(tramites)} servicios)...")
    hits_avc = verificar_avc_todos(tramites)
    if hits_avc:
        for tramite, nombre, detalle in hits_avc:
            log(f"*** Alerta AVC: {nombre} ***")
            url_servicio = os.getenv(SERVICIOS[tramite]["url_env"], URL_SISTEMA)
            enviar_telegram(
                f"ALERTA TEMPRANA — Canal AVC\n"
                f"Servicio: {nombre}\n"
                f"{hora}\n\n"
                f"{detalle[:200]}\n\n"
                f"Vigila el sitio — toca para abrir:",
                url_boton=url_servicio,
            )
    else:
        log("  AVC: sin novedad")

    log("=== Check completado ===")
