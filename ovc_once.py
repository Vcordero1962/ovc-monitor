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
import json
import random
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

URL_SISTEMA        = os.getenv("URL_SISTEMA", "")   # Legacy — URL del widget LEGA
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_CHAT_ID      = os.getenv("ADMIN_CHAT_ID", "")           # chat personal admin — alerta directa
AVC_TRAMITE        = os.getenv("AVC_TRAMITE", "ALL").upper()  # "ALL" o "LMD,LEGA" o "LMD"

# ─── Proxy residencial ────────────────────────────────────────────────────────
# Mantenido para diagnóstico y uso futuro. Por defecto Playwright NO lo usa
# (PLAYWRIGHT_PROXY_ENABLED=0) porque las IPs de GitHub Actions superan la gate
# de Imperva directamente (GET/POST 200 confirmado sin proxy).
# Formato: http://usuario:contraseña@host:puerto
# Webshare.io static residential: http://user:pass@IP:PORT
# Si está vacío → sin proxy (AVC Telegram nunca requiere proxy)
HTTP_PROXY_URL = os.getenv("HTTP_PROXY_URL", "")

# ─── Control de verificación directa del sitio ───────────────────────────────
# SITIO_DIRECTO_ENABLED=1 → verifica el widget de citaconsular.es con Playwright
# SITIO_DIRECTO_ENABLED=0 → salta el check directo, solo usa canal AVC
#
# Las IPs de GitHub Actions NO están IP-bloqueadas por Imperva — la gate de Imperva
# es un click-through (token POST), no un bloqueo real. Playwright lo supera
# directamente sin proxy residencial.
# Usar 0 solo si Playwright falla de forma persistente (ej. Imperva cambia política).
SITIO_DIRECTO_ENABLED = os.getenv("SITIO_DIRECTO_ENABLED", "1") == "1"

# ─── Control de proxy para Playwright ────────────────────────────────────────
# PLAYWRIGHT_PROXY_ENABLED=0 (default) → Playwright usa IP directa del runner
#   (GitHub Actions IPs no están IP-bloqueadas — GET/POST 200 confirmado sin proxy)
# PLAYWRIGHT_PROXY_ENABLED=1 → Playwright usa HTTP_PROXY_URL (residencial)
#   (necesario solo si Imperva empieza a bloquear IPs de datacenter con JS)
PLAYWRIGHT_PROXY_ENABLED = os.getenv("PLAYWRIGHT_PROXY_ENABLED", "0") == "1"

# ─── Confirmación de run al admin ─────────────────────────────────────────────
# STATUS_CADA_RUN=1 (default) → envía mensaje silencioso al ADMIN_CHAT_ID
#   al final de cada run confirmando que el bot corrió y qué encontró.
#   Útil para verificar que el bot está vivo sin esperar una cita real.
# STATUS_CADA_RUN=0 → no envía confirmación (solo avisa cuando hay citas)
STATUS_CADA_RUN = os.getenv("STATUS_CADA_RUN", "1") == "1"

# ─── Perfil persistente de Chromium ──────────────────────────────────────────
# El user-data-dir se cachea en GitHub Actions entre runs.
# Resultado: el sitio ve una sesión que "ya existía", no un browser virgen.
# CHROMIUM_PROFILE_DIR se pasa como env var desde el workflow.
_DEFAULT_PROFILE = Path.home() / ".config" / "chromium-ovc"
USER_DATA_DIR  = Path(os.getenv("CHROMIUM_PROFILE_DIR", str(_DEFAULT_PROFILE)))
SESSION_STAMP  = USER_DATA_DIR / "ovc_session.json"   # dentro del dir → se cachea junto
SESSION_MAX_MIN = 25  # minutos — tokens del consulado duran ~20-30 min

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


def get_session_age_min() -> float:
    """Retorna la edad de la sesión en minutos, o None si no hay stamp."""
    try:
        data = json.loads(SESSION_STAMP.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except Exception:
        return None


def update_session_stamp():
    """Actualiza el timestamp de la sesión activa dentro del user-data-dir."""
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_STAMP.write_text(
            json.dumps({"timestamp": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
    except Exception as e:
        log(f"  stamp error: {e}")


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


def _generar_card_alerta(tipo: str, nombre: str, hora: str, detalle: str = ""):
    """Genera imagen PNG branded para la alerta — enviar como foto en Telegram.

    tipo:
      'SITIO' → rojo urgente (cita confirmada en el sitio oficial)
      'AVC'   → naranja (alerta temprana del canal AVC)

    Retorna bytes PNG o None si Pillow no está disponible.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        W, H = 800, 420

        if tipo == "SITIO":
            bg_top    = (120, 0, 0)
            bg_bottom = (60, 0, 0)
            accent    = (255, 60, 60)
            header    = "!! CITA DISPONIBLE AHORA"
            cta_color = (255, 210, 210)
            cta_texto = "Tienes ~2 minutos. Entra YA y completa el captcha."
        else:
            bg_top    = (110, 55, 0)
            bg_bottom = (55, 25, 0)
            accent    = (255, 165, 0)
            header    = ">>  ALERTA TEMPRANA - CANAL AVC"
            cta_color = (255, 230, 160)
            cta_texto = "Ten el formulario listo. Actua en cuanto abran."

        img  = Image.new("RGB", (W, H), bg_top)
        draw = ImageDraw.Draw(img)

        # Gradiente horizontal (líneas)
        for y in range(H):
            r = bg_top[0] + int((bg_bottom[0] - bg_top[0]) * y / H)
            g = bg_top[1] + int((bg_bottom[1] - bg_top[1]) * y / H)
            b = bg_top[2] + int((bg_bottom[2] - bg_top[2]) * y / H)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        # Fuente — intenta Bold, fallback default
        FONT_PATHS = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]

        def _font(size):
            for p in FONT_PATHS:
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
            try:
                return ImageFont.load_default(size=size)
            except Exception:
                return ImageFont.load_default()

        f_header   = _font(34)
        f_servicio = _font(46)
        f_hora     = _font(26)
        f_cta      = _font(30)
        f_detalle  = _font(20)
        f_footer   = _font(18)

        # Barra acento superior
        draw.rectangle([(0, 0), (W, 8)], fill=accent)

        # Header
        draw.text((40, 24), header, fill=accent, font=f_header)

        # Separador
        draw.line([(40, 86), (W - 40, 86)], fill=accent, width=2)

        # Nombre servicio
        draw.text((40, 100), nombre, fill=(255, 255, 255), font=f_servicio)

        # Hora
        draw.text((40, 165), f"Detectado: {hora}", fill=(190, 190, 190), font=f_hora)

        # Separador
        draw.line([(40, 210), (W - 40, 210)], fill=(90, 90, 90), width=1)

        # CTA
        draw.text((40, 228), cta_texto, fill=cta_color, font=f_cta)

        # Detalle AVC (opcional)
        if detalle and tipo == "AVC":
            txt = detalle[:90] + ("..." if len(detalle) > 90 else "")
            draw.text((40, 278), txt, fill=(160, 160, 160), font=f_detalle)

        # Footer
        draw.rectangle([(0, H - 48), (W, H)], fill=(15, 15, 15))
        draw.text(
            (40, H - 34),
            "OVC  Monitor Consular 24/7  |  Verificacion automatica cada 7 min",
            fill=(120, 120, 120),
            font=f_footer,
        )

        # Barra acento inferior
        draw.rectangle([(0, H - 4), (W, H)], fill=accent)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    except Exception as e:
        log(f"  Card imagen: error ({e})")
        return None


def _build_keyboard(url_sitio: str, url_avc: str = URL_AVC) -> list:
    """
    Construye teclado inline para alertas del grupo.
    SITIO → fila 1: ENTRAR Y RESERVAR (urgente), fila 2: canal AVC
    AVC   → fila 1: abrir citaconsular.es, fila 2: ver aviso en AVC
    """
    teclado = []
    if url_sitio:
        teclado.append([{"text": "🔴🔴  RESERVAR CITA — ENTRA YA  🔴🔴", "url": url_sitio}])
    teclado.append([{"text": "📢 Ver aviso oficial en AVC", "url": url_avc}])
    return teclado


def enviar_telegram(msg: str, url_boton: str = "", parse_mode: str = "HTML"):
    """Envía alerta de texto al grupo con botones RESERVAR + AVC."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado")
        return
    try:
        import json as _json
        url_destino = url_boton or URL_SISTEMA
        payload = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       msg,
            "parse_mode": parse_mode,
            "reply_markup": {"inline_keyboard": _build_keyboard(url_destino)},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload, timeout=10,
        )
        log(f"Telegram texto: {'OK' if r.ok else f'error {r.status_code} — {r.text[:80]}'}")
    except Exception as e:
        log(f"Telegram error: {e}")


def enviar_foto_telegram(caption: str, foto_bytes: bytes, url_boton: str = ""):
    """Envía screenshot del widget como foto al grupo con botones RESERVAR + AVC.
    Si el envío de foto falla, cae a texto plano como fallback."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado")
        return
    import json as _json
    url_destino = url_boton or URL_SISTEMA
    reply_markup = _json.dumps({"inline_keyboard": _build_keyboard(url_destino)})
    try:
        data = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "caption":    caption,
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
        }
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


def _enviar_alerta_admin(msg: str, url_boton: str = "", silencioso: bool = False):
    """Envía alerta directa al chat personal del admin (ADMIN_CHAT_ID).

    silencioso=False (default) → suena en el celular — para citas confirmadas (SITIO)
    silencioso=True            → llega sin sonido  — para alertas tempranas (AVC)
    """
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        return
    try:
        payload = {
            "chat_id":                ADMIN_CHAT_ID,
            "text":                   msg,
            "parse_mode":             "HTML",
            "disable_notification":   silencioso,
        }
        if url_boton:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": "🔴🔴  RESERVAR CITA — ENTRA YA  🔴🔴", "url": url_boton}]]
            }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload, timeout=10,
        )
        modo = "silencioso" if silencioso else "con sonido"
        log(f"Telegram admin ({modo}): {'OK' if r.ok else f'error {r.status_code}'}")
    except Exception as e:
        log(f"Telegram admin-directo error: {e}")


def verificar_url_widget(url: str) -> tuple:
    """
    Verifica si el widget tiene disponibilidad.
    Anti-WAF: perfil persistente (user-data-dir cacheado), CDP latency throttling,
    warm-up navegacion, session age management, stealth script dinámico.
    Retorna (disponible, screenshot_bytes, bloqueado_definitivo):
      (True,  bytes, False) → cita disponible, bytes = screenshot PNG del widget
      (False, None,  True)  → "No hay horas disponibles" — no reintentar
      (False, None,  False) → posible bloqueo temporal / captcha — reintentar
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWT

        ua        = random.choice(USER_AGENTS)
        viewport  = random.choice(VIEWPORTS)
        is_mobile = viewport["width"] < 500
        log(f"  UA: {ua[:70]}...")
        log(f"  Viewport: {viewport['width']}x{viewport['height']} {'(mobile)' if is_mobile else '(desktop)'}")

        stealth = _make_stealth_script(viewport)

        # Gestión de edad de sesión
        session_age = get_session_age_min()
        if session_age is not None:
            log(f"  Sesión cache: {session_age:.1f} min de antigüedad")
        else:
            log("  Sesión cache: nueva (sin stamp)")

        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Proxy residencial — solo si PLAYWRIGHT_PROXY_ENABLED=1 Y HTTP_PROXY_URL está set.
        # Por defecto Playwright corre con IP directa del runner (GitHub Actions):
        # las IPs de datacenter superan la gate de Imperva sin proxy (confirmado — GET/POST 200).
        # Playwright requiere username/password SEPARADOS del server (no en la URL)
        proxy_cfg = None
        if HTTP_PROXY_URL and PLAYWRIGHT_PROXY_ENABLED:
            try:
                from urllib.parse import urlparse
                _p = urlparse(HTTP_PROXY_URL)
                proxy_cfg = {
                    "server":   f"{_p.scheme}://{_p.hostname}:{_p.port}",
                    "username": _p.username or "",
                    "password": _p.password or "",
                }
                log(f"  Proxy: {_p.scheme}://{_p.hostname}:{_p.port} user={(_p.username or '')[:12]}...")
            except Exception as _pe:
                log(f"  Proxy: error parseando URL — {_pe}")
        else:
            reason = "PLAYWRIGHT_PROXY_ENABLED=0" if HTTP_PROXY_URL else "HTTP_PROXY_URL no configurado"
            log(f"  Proxy: no usado ({reason}) — IP directa del runner")

        with sync_playwright() as p:
            # launch_persistent_context: reutiliza cookies/storage del run anterior
            # (el user-data-dir se cachea en GitHub Actions entre runs via actions/cache)
            # --disable-quic: fuerza HTTP/2 sobre TCP, evita HTTP/3-QUIC
            ctx = p.chromium.launch_persistent_context(
                str(USER_DATA_DIR),
                headless=True,
                proxy=proxy_cfg,
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
                    "--disable-quic",
                    f"--window-size={viewport['width']},{viewport['height']}",
                ],
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

            # Limpiar cookies si la sesión expiró (tokens del consulado duran ~20-30 min)
            if session_age is not None and session_age > SESSION_MAX_MIN:
                log(f"  Sesión expirada ({session_age:.1f} min > {SESSION_MAX_MIN} min) — limpiando cookies")
                ctx.clear_cookies()

            page = ctx.new_page()
            try:
                # CDP: emular latencia residencial — diferencia vs datacenter puro
                # Un datacenter tiene 1-5 ms de latencia; una casa tiene 40-80 ms
                try:
                    cdp     = ctx.new_cdp_session(page)
                    dl_bps  = random.randint(1_500_000, 4_000_000)   # 1.5–4 Mbps
                    ul_bps  = random.randint(500_000,   1_500_000)    # 0.5–1.5 Mbps
                    latency = random.randint(40, 80)                   # 40–80 ms residencial
                    cdp.send("Network.emulateNetworkConditions", {
                        "offline":            False,
                        "downloadThroughput": dl_bps // 8,
                        "uploadThroughput":   ul_bps // 8,
                        "latency":            latency,
                    })
                    log(f"  CDP latencia: {dl_bps//1000} Kbps DL, {latency} ms RTT")
                except Exception as cdp_e:
                    log(f"  CDP (ignorado): {cdp_e}")

                # Timeouts adaptativos: proxy residencial es más lento que IP directa
                to_nav    = 55000 if proxy_cfg else 30000   # handshake citaconsular
                to_widget = 60000 if proxy_cfg else 35000   # carga del widget

                # Calentamiento: solo sin proxy (Google bloquea proxies residenciales)
                if not proxy_cfg:
                    try:
                        log("  Warm-up: buscando en Google...")
                        page.goto(
                            "https://www.google.es/search?q=consulado+espana+cuba+cita+previa",
                            timeout=20000, wait_until="domcontentloaded",
                        )
                        human_sleep(2.0, 4.0)
                        page.evaluate("window.scrollTo({top: Math.floor(Math.random()*300+100), behavior:'smooth'})")
                        human_sleep(1.0, 2.5)
                    except Exception:
                        log("  Warm-up: omitido")
                else:
                    log("  Warm-up: omitido (proxy activo — Google lo bloquearia)")

                # Paso 1: handshake — obtener cookie de sesión como usuario real
                page.goto("https://www.citaconsular.es", timeout=to_nav, wait_until="domcontentloaded")
                human_sleep(1.0, 2.8)

                # Scroll humano — Imperva detecta si no hay movimiento tras la carga
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
                page.goto(url, timeout=to_widget, wait_until="domcontentloaded")
                human_sleep(1.2, 4.0)

                # Paso 2b: detectar y superar el captcha gate de Imperva
                # El gate NO es un CAPTCHA real — solo requiere enviar un token oculto
                # (el mismo flujo GET→POST que verificar_bookitit_post_url, via Playwright)
                # Funciona desde IPs de datacenter (GitHub Actions) sin proxy residencial.
                try:
                    if page.locator('input[name="token"]').count() > 0:
                        log("  Imperva gate detectado — enviando token via Playwright...")
                        page.locator(
                            'button[type="submit"], input[type="submit"], '
                            'button:has-text("Continuar"), button:has-text("Continue"), '
                            'a:has-text("Continuar"), a:has-text("Continue")'
                        ).first.click(timeout=8000)
                        # networkidle: espera a que loadermaec.js ejecute la llamada JSONP completa
                        page.wait_for_load_state("networkidle", timeout=25000)
                        log(f"  Gate superado — {len(page.content())} chars tras POST token")
                        human_sleep(0.5, 1.5)
                except Exception as gate_e:
                    log(f"  Gate handling (ignorado): {gate_e}")

                page.evaluate("window.scrollTo({top: Math.floor(Math.random()*150+30), behavior:'smooth'})")
                human_sleep(0.5, 1.2)

                try:
                    page.wait_for_selector(
                        "#bk-widget, #bookitit-widget, .bk-container, #datetime, "
                        ".bk-time-slot, .bk-slot, [class*='bk-hour'], [class*='bk-time']",
                        timeout=20000,
                    )
                    # Dar tiempo extra para que el JSONP renderice todos los slots
                    human_sleep(2.0, 3.0)
                except PWT:
                    pass

                human_sleep(0.4, 1.5)
                contenido = page.content()
                log(f"  Contenido recibido: {len(contenido)} chars")

                # Actualizar stamp — la sesión fue usada ahora mismo
                update_session_stamp()

                if TEXTO_BLOQUEADO in contenido:
                    log("  Sitio: sin horas disponibles (confirmado)")
                    return False, None, True   # bloqueado definitivo — no reintentar

                # Indicadores de slots reales renderizados post-JSONP
                # (evitar falsos positivos con el HTML estático del bkt_init_widget)
                import re as _re
                slots_hora = len(_re.findall(r'\b\d{2}:\d{2}\b', contenido))
                indicadores_widget = ["Selecciona", "Confirmar", "bk-time-slot", "bk-slot", "bk-hour"]
                widget_con_slots = slots_hora >= 3 or any(i in contenido for i in indicadores_widget)

                if widget_con_slots:
                    log(f"  Sitio: CITA DISPONIBLE — {slots_hora} slots hora detectados — capturando screenshot")
                    screenshot = page.screenshot(type="png", full_page=False)
                    return True, screenshot, False
                elif "bkt_init_widget" in contenido or "bookitit" in contenido.lower():
                    log("  Sitio: widget cargado pero sin slots disponibles (JSONP sin citas)")
                    return False, None, True   # confirmado sin citas — no reintentar
                else:
                    log("  Sitio: widget vacio (posible bloqueo por IP o error)")
                    return False, None, False  # bloqueo temporal — reintentar

            except PWT:
                log("  Sitio: timeout")
                return False, None, False      # timeout — reintentar
            finally:
                ctx.close()

    except Exception as e:
        log(f"  Playwright error: {e}")
        return False, None, False


def verificar_url_con_retry(url: str, max_intentos: int = 2) -> tuple:
    """
    Wrapper con retry exponencial sobre verificar_url_widget.
    Solo reintenta si fue bloqueo temporal (no en bloqueo definitivo).
    Delays: intento 1=inmediato, intento 2=+8s
    max_intentos reducido de 3→2 para que el workflow quepa en 10 min.
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


def _parse_bkt_widget(text: str) -> dict:
    """
    Extrae agendas[] y dates[] del objeto JS bkt_init_widget.
    Soporta claves sin comillas (JS estándar) y con comillas simples/dobles.
    """
    import re as _re
    m  = _re.search(r"(?:['\"]agendas['\"]|agendas)\s*:\s*(\[[^\]]*\])", text, _re.DOTALL)
    m2 = _re.search(r"(?:['\"]dates['\"]|dates)\s*:\s*(\[[^\]]*\])",   text, _re.DOTALL)
    agendas_raw = m.group(1)  if m  else "[]"
    dates_raw   = m2.group(1) if m2 else "[]"
    return {
        "agendas_count": len(_re.findall(r'\{', agendas_raw)),
        "dates_count":   len(_re.findall(r'\d{4}-\d{2}-\d{2}', dates_raw)),
        "dates_raw":     dates_raw[:200],
    }


def verificar_bookitit_post_url(widget_url: str) -> tuple:
    """
    Verifica disponibilidad en un widget de citaconsular.es usando el flujo POST token.
    No necesita Playwright ni proxy — usa requests simple.

    Flujo Imperva bypass:
      1. GET widget_url → página captcha gate con <input name="token">
      2. POST widget_url con token → responde con bkt_init_widget JS object
      3. Parsea agendas[] y dates[] → si dates[] tiene entradas, hay citas disponibles

    Retorna (disponible: bool, info: dict)
      disponible=True  → dates[] no está vacío  — CITA DISPONIBLE
      disponible=False → todo vacío / error      — sin novedad
    """
    ua = random.choice(USER_AGENTS)
    session = requests.Session()
    headers = {
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "es-ES,es;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Cache-Control":             "max-age=0",
    }
    try:
        # Paso 1 — GET: obtener la página del captcha gate + el token oculto
        r_get = session.get(widget_url, headers=headers, timeout=20, allow_redirects=True)
        if not r_get.ok:
            log(f"    BKT GET: HTTP {r_get.status_code}")
            return False, {}

        html_get = r_get.text
        log(f"    BKT GET: {r_get.status_code} — {len(html_get)} chars")

        # Extraer token (Imperva lo requiere en el POST)
        token = None
        m = re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']', html_get)
        if not m:
            m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html_get)
        if m:
            token = m.group(1)
            log(f"    BKT token: {token[:20]}...")
        else:
            log("    BKT token: NO encontrado en GET response")
            return False, {}

        # Paso 2 — POST: enviar token → Imperva nos deja pasar, devuelve el widget real
        human_sleep(0.8, 2.0)
        post_headers = dict(headers)
        post_headers.update({
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer":      widget_url,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        })
        r_post = session.post(
            widget_url,
            data={"token": token},
            headers=post_headers,
            timeout=20,
            allow_redirects=True,
        )
        if not r_post.ok:
            log(f"    BKT POST: HTTP {r_post.status_code}")
            return False, {}

        post_text = r_post.text
        log(f"    BKT POST: {r_post.status_code} — {len(post_text)} chars")

        # Paso 3 — Parsear bkt_init_widget
        bkt_pos = post_text.find("bkt_init_widget")
        if bkt_pos < 0:
            log("    BKT: bkt_init_widget NO en POST response (bloqueado por Imperva?)")
            return False, {}

        bkt_ctx = post_text[bkt_pos:bkt_pos + 1500]
        data    = _parse_bkt_widget(bkt_ctx)
        log(f"    BKT: agendas={data['agendas_count']} dates={data['dates_count']} raw={data['dates_raw'][:80]}")

        if data["dates_count"] > 0:
            log("    BKT: *** FECHAS DISPONIBLES en dates[] ***")
            return True, data
        elif data["agendas_count"] > 0:
            log("    BKT: agendas presentes pero dates[] vacío — sin citas hoy")
        else:
            log("    BKT: agendas[] y dates[] vacíos — sin disponibilidad")
        return False, data

    except Exception as e:
        log(f"    BKT error: {e}")
        return False, {}


def verificar_bookitit_todos(tramites: list) -> list:
    """
    Verifica Bookitit vía POST token para todos los tramites con URL configurada.
    Retorna lista de (tramite, nombre, url, info_dict) con disponibilidad confirmada.
    No necesita Playwright ni proxy residencial.
    """
    hits = []
    for tramite in tramites:
        servicio = SERVICIOS[tramite]
        url = os.getenv(servicio["url_env"], "")
        if not url and tramite == "LEGA" and URL_SISTEMA:
            url = URL_SISTEMA
        if not url:
            log(f"  BKT [{tramite}]: sin URL configurada — omitiendo")
            continue
        log(f"  BKT verificando [{tramite}] {servicio['nombre']}...")
        disponible, info = verificar_bookitit_post_url(url)
        if disponible:
            hits.append((tramite, servicio["nombre"], url, info))
        if tramites.index(tramite) < len(tramites) - 1:
            human_sleep(1.5, 3.5)
    return hits


if __name__ == "__main__":
    # Sleep gaussiano al inicio — rompe el patrón regular del cron
    # Distribución normal: mayoría entre 30-60s, outliers ocasionales
    espera = max(10, min(90, int(random.gauss(45, 20))))
    log(f"Anti-deteccion: esperando {espera}s antes de consultar...")
    time.sleep(espera)

    tramites = get_tramites_activos()
    # Hora en Miami (UTC-4 EDT en verano, UTC-5 EST en invierno)
    # GitHub Actions corre en UTC — convertimos para mostrar hora local del usuario
    _miami = datetime.now(timezone.utc) - timedelta(hours=4)  # EDT (mar-nov)
    hora = _miami.strftime("%I:%M %p del %d/%m/%Y (Miami)")
    log(f"=== OVC check — {hora} — tramites: {', '.join(tramites)} ===")

    if not URL_SISTEMA and not any(os.getenv(SERVICIOS[t]["url_env"], "") for t in tramites):
        log("WARN: ninguna URL de widget configurada — solo se verificara AVC")

    # 1. Sitio oficial (verifica widgets con URL configurada)
    #    Requiere proxy RESIDENCIAL para bypassar Imperva desde GitHub Actions.
    #    Si SITIO_DIRECTO_ENABLED=0 se salta completamente (ahorra 3+ min/run).
    hits_sitio = []
    hits_bkt   = []   # inicializar aquí — puede no asignarse si BOOKITIT_POST_ENABLED=0
    hits_avc   = []   # inicializar aquí — siempre se reasigna más adelante
    if SITIO_DIRECTO_ENABLED:
        log(f"Verificando sitio oficial ({len(tramites)} servicios)...")
        hits_sitio = verificar_sitios_multi(tramites)
        for tramite, nombre, url, screenshot in hits_sitio:
            log(f"*** CITA DISPONIBLE en sitio oficial: {nombre} ***")

            # Mensaje grupo — urgente, marketing style
            caption = (
                f"🚨 <b>¡CITA DISPONIBLE AHORA!</b>\n\n"
                f"📋 <b>{nombre}</b>\n"
                f"⏰ {hora}\n\n"
                f"⚡ <b>Tienes ~2 minutos</b> antes de que desaparezca.\n"
                f"Entra YA y completa el captcha."
            )

            # Foto con screenshot real del sitio; fallback a card PIL si no hay screenshot
            foto = screenshot or _generar_card_alerta("SITIO", nombre, hora)
            if foto:
                enviar_foto_telegram(caption, foto, url_boton=url)
            else:
                enviar_telegram(caption, url_boton=url)

            # Admin — mensaje corto, suena fuerte
            admin_msg = (
                f"🚨 <b>CITA DISPONIBLE — {nombre}</b>\n"
                f"⏰ {hora}\n\n"
                f"Entra YA antes de que desaparezca."
            )
            _enviar_alerta_admin(admin_msg, url_boton=url, silencioso=False)

        if hits_sitio:
            sys.exit(0)
        log("Sitio oficial: sin disponibilidad")
    else:
        log("Sitio oficial: omitido (SITIO_DIRECTO_ENABLED=0 — requiere proxy residencial)")

    # 2. Bookitit POST directo — bypasea Imperva sin proxy ni Playwright
    #    Flujo: GET captcha gate → extraer token → POST → parsear bkt_init_widget
    #    Funciona desde GitHub Actions IPs (no requiere proxy residencial)
    #    Desactivar con: gh secret set BOOKITIT_POST_ENABLED --body "0"
    BOOKITIT_POST_ENABLED = os.getenv("BOOKITIT_POST_ENABLED", "1") == "1"
    if BOOKITIT_POST_ENABLED:
        log(f"Verificando Bookitit POST directo ({len(tramites)} servicios)...")
        hits_bkt = verificar_bookitit_todos(tramites)
        if hits_bkt:
            for tramite, nombre, url, info in hits_bkt:
                log(f"*** CITA DISPONIBLE via Bookitit POST: {nombre} ***")
                caption = (
                    f"🚨 <b>¡CITA DISPONIBLE AHORA!</b>\n\n"
                    f"📋 <b>{nombre}</b>\n"
                    f"⏰ {hora}\n\n"
                    f"⚡ <b>Tienes ~2 minutos</b> antes de que desaparezca.\n"
                    f"Entra YA y completa el captcha."
                )
                foto = _generar_card_alerta("SITIO", nombre, hora)
                if foto:
                    enviar_foto_telegram(caption, foto, url_boton=url)
                else:
                    enviar_telegram(caption, url_boton=url)
                admin_msg = (
                    f"🚨 <b>CITA DISPONIBLE — {nombre}</b>\n"
                    f"⏰ {hora}\n\nEntra YA antes de que desaparezca."
                )
                _enviar_alerta_admin(admin_msg, url_boton=url, silencioso=False)
            sys.exit(0)
        else:
            log("Bookitit POST: sin disponibilidad")
    else:
        log("Bookitit POST: desactivado (BOOKITIT_POST_ENABLED=0)")

    # 3. Canal AVC (una sola petición, verifica todos los tramites)
    log(f"Verificando canal AVC ({len(tramites)} servicios)...")
    hits_avc = verificar_avc_todos(tramites)
    if hits_avc:
        for tramite, nombre, detalle in hits_avc:
            log(f"*** Alerta AVC: {nombre} ***")
            url_servicio = os.getenv(SERVICIOS[tramite]["url_env"], URL_SISTEMA)

            # Mensaje grupo — alerta temprana, acción clara
            avc_msg = (
                f"⚠️ <b>¡CITAS ABRIENDOSE PRONTO!</b>\n\n"
                f"📋 <b>{nombre}</b>\n"
                f"⏰ {hora}\n\n"
                f"📢 {detalle[:180]}\n\n"
                f"Ten el formulario listo. <b>Actua en cuanto abran.</b>\n\n"
                f"💡 El consulado suele liberar citas a las <b>8:00 AM hora de España</b> "
                f"(3:00 AM Miami / 7:00 AM UTC). Este bot vigila esa ventana cada 7 min."
            )

            # Card PIL como imagen de alerta (no hay screenshot del sitio en modo AVC)
            card = _generar_card_alerta("AVC", nombre, hora, detalle)
            if card:
                enviar_foto_telegram(avc_msg, card, url_boton=url_servicio)
            else:
                enviar_telegram(avc_msg, url_boton=url_servicio)

            # Admin — llega silencioso (no es cita confirmada, no debe despertar a nadie)
            admin_avc = (
                f"⚠️ <b>Alerta AVC — {nombre}</b>\n"
                f"⏰ {hora}\n"
                f"Citas abriendo pronto — mantente atento."
            )
            _enviar_alerta_admin(admin_avc, url_boton=url_servicio, silencioso=True)
    else:
        log("  AVC: sin novedad")

    log("=== Check completado ===")

    # ── Confirmación de run al admin ──────────────────────────────────────────
    # Mensaje silencioso al chat personal. Llega sin sonido para no molestar.
    # Permite verificar que el bot está vivo sin esperar una cita real.
    if STATUS_CADA_RUN and ADMIN_CHAT_ID and TELEGRAM_BOT_TOKEN:
        sitio_txt = "omitido" if not SITIO_DIRECTO_ENABLED else (
            "🚨 CITA" if hits_sitio else "✅ sin citas"
        )
        bkt_txt   = "omitido" if not BOOKITIT_POST_ENABLED else (
            "🚨 CITA" if hits_bkt  else "✅ sin citas"
        )
        avc_txt   = "🚨 ALERTA" if hits_avc else "✅ sin novedad"
        tramites_str = ", ".join(tramites)
        status_msg = (
            f"🤖 <b>OVC — run completado</b>\n"
            f"⏰ {hora}\n\n"
            f"🌐 Sitio oficial: {sitio_txt}\n"
            f"📡 Bookitit POST: {bkt_txt}\n"
            f"📢 Canal AVC:     {avc_txt}\n\n"
            f"<i>Servicios: {tramites_str}</i>"
        )
        try:
            import requests as _req
            _req.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id":              ADMIN_CHAT_ID,
                    "text":                 status_msg,
                    "parse_mode":           "HTML",
                    "disable_notification": True,   # silencioso — no suena
                },
                timeout=10,
            )
            log("  Confirmacion enviada al admin (silencioso)")
        except Exception as _e:
            log(f"  Confirmacion admin: error ({_e})")
