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

# Pool de user-agents reales — rota en cada ejecución
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# Resoluciones comunes de pantalla para aparentar usuario real
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1536, "height": 864},
]

# Script para ocultar que es Playwright (elimina navigator.webdriver)
STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en-US', 'en'] });
window.chrome = { runtime: {} };
"""


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


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
    """Envía alerta al grupo. Si url_boton está definida agrega botón ABRIR AHORA."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado")
        return
    try:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        url_destino = url_boton or URL_SISTEMA
        if url_destino:
            payload["reply_markup"] = {
                "inline_keyboard": [[
                    {"text": "ABRIR AHORA", "url": url_destino}
                ]]
            }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        log(f"Telegram: {'OK' if r.ok else f'error {r.status_code} — {r.text[:80]}'}")
    except Exception as e:
        log(f"Telegram error: {e}")


def verificar_url_widget(url: str) -> bool:
    """Verifica si el widget de citaconsular.es tiene disponibilidad para una URL dada."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWT

        ua       = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORTS)
        log(f"  UA: {ua[:60]}...")
        log(f"  Viewport: {viewport['width']}x{viewport['height']}")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=ua,
                viewport=viewport,
                locale="es-ES",
                timezone_id="America/Havana",
            )
            ctx.add_init_script(STEALTH_SCRIPT)
            page = ctx.new_page()
            try:
                # Paso 1: handshake en la página principal — obtener cookie de sesión
                page.goto("https://www.citaconsular.es", timeout=30000, wait_until="domcontentloaded")
                time.sleep(random.uniform(1.0, 2.5))
                try:
                    page.click("button:has-text('Aceptar'), button:has-text('Accept'), button:has-text('Entrar')", timeout=5000)
                    time.sleep(random.uniform(0.5, 1.5))
                except Exception:
                    pass

                # Paso 2: navegar al widget con la cookie ya establecida
                page.goto(url, timeout=35000, wait_until="domcontentloaded")
                time.sleep(random.uniform(0.8, 3.5))

                try:
                    page.wait_for_selector(
                        "#bk-widget, #bookitit-widget, .bk-container, #datetime",
                        timeout=25000,
                    )
                except PWT:
                    pass

                time.sleep(random.uniform(0.3, 1.2))
                contenido = page.content()
                log(f"  Contenido recibido: {len(contenido)} chars")

                if TEXTO_BLOQUEADO in contenido:
                    log("  Sitio: bloqueado explicitamente (sin horas)")
                    return False

                indicadores = ["bookitit", "bk-widget", "datetime", "Selecciona", "Confirmar", "horas"]
                widget_ok = any(i in contenido for i in indicadores)
                if not widget_ok:
                    log("  Sitio: widget vacio (posible bloqueo por IP o captcha)")
                return widget_ok

            except PWT:
                log("  Sitio: timeout")
                return False
            finally:
                browser.close()

    except Exception as e:
        log(f"  Playwright error: {e}")
        return False


def verificar_sitios_multi(tramites: list) -> list:
    """
    Verifica el widget oficial para cada tramite que tenga URL configurada.
    Retorna lista de (tramite, nombre, url) con disponibilidad.
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
        if verificar_url_widget(url):
            hits.append((tramite, servicio["nombre"], url))
            # Pausa entre checks para no parecer bot agresivo
            time.sleep(random.uniform(2.0, 5.0))
    return hits


def verificar_avc_todos(tramites: list) -> list:
    """
    Verifica el canal AVC para todos los tramites de la lista en UNA sola petición.
    Retorna lista de (tramite, nombre, fragmento) para cada servicio con alerta.
    """
    try:
        ua = random.choice(USER_AGENTS)
        headers = {"User-Agent": ua}
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
    # Sleep aleatorio al inicio — rompe el patrón regular del cron
    espera = random.randint(10, 90)
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
    for tramite, nombre, url in hits_sitio:
        log(f"*** CITA DISPONIBLE en sitio oficial: {nombre} ***")
        enviar_telegram(
            f"CITA DISPONIBLE — Consulado Espana\n"
            f"Servicio: {nombre}\n"
            f"Detectado: {hora}\n\n"
            f"Toca el boton para abrir el captcha YA:",
            url_boton=url,
        )

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
