#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC-Once — Check único para GitHub Actions / nube
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

URL_SISTEMA        = os.getenv("URL_SISTEMA", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
AVC_TRAMITE        = os.getenv("AVC_TRAMITE", "LMD").upper()

URL_AVC         = "https://t.me/s/AsesorVirtualC"
TEXTO_BLOQUEADO = "No hay horas disponibles"

AVC_KEYWORDS = {
    "LMD":        ["LMD", "LEGALIZACI", "CREDENCIALES"],
    "PASAPORTE":  ["PASAPORTE"],
    "MATRIMONIO": ["MATRIMONIO", "TRANSCRIPCI"],
    "VISADO":     ["VISADO"],
}
AVC_ALERTAS = ["CITAS QUE SER", "SERAN HABILITADAS", "PROXIMA FECHA"]

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


def enviar_telegram(msg: str, con_boton: bool = False):
    """Envía alerta. Si con_boton=True agrega botón ABRIR AHORA para ir directo al captcha."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado")
        return
    try:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        if con_boton and URL_SISTEMA:
            payload["reply_markup"] = {
                "inline_keyboard": [[
                    {"text": "ABRIR AHORA", "url": URL_SISTEMA}
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


def verificar_sitio() -> bool:
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
            # Inyectar stealth antes de cargar cualquier página
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
                    pass  # No hay botón o ya aceptado

                # Paso 2: navegar al widget con la cookie ya establecida
                page.goto(URL_SISTEMA, timeout=35000, wait_until="domcontentloaded")

                # Pausa humana aleatoria tras cargar (0.8 — 3.5 s)
                time.sleep(random.uniform(0.8, 3.5))

                try:
                    page.wait_for_selector(
                        "#bk-widget, #bookitit-widget, .bk-container, #datetime",
                        timeout=25000,
                    )
                except PWT:
                    pass

                # Otra micro-pausa antes de leer el DOM
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


def verificar_avc() -> tuple:
    try:
        ua = random.choice(USER_AGENTS)
        headers = {"User-Agent": ua}
        resp = requests.get(URL_AVC, headers=headers, timeout=15)
        if not resp.ok:
            log(f"  AVC no accesible: HTTP {resp.status_code}")
            return False, ""

        html = resp.text
        ahora  = datetime.now(timezone.utc)
        limite = ahora - timedelta(hours=48)
        keywords = AVC_KEYWORDS.get(AVC_TRAMITE, [])

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
            return False, ""

        bloque = html_reciente.upper()
        if any(kw in bloque for kw in keywords) and any(a in bloque for a in AVC_ALERTAS):
            fragmento = re.sub(r'<[^>]+>', '', html_reciente)[:300].strip()
            return True, fragmento

        return False, ""

    except Exception as e:
        log(f"  AVC error: {e}")
        return False, ""


if __name__ == "__main__":
    if not URL_SISTEMA:
        log("ERROR: URL_SISTEMA no definida")
        sys.exit(1)

    # Sleep aleatorio al inicio — rompe el patrón regular del cron
    # El sitio ve peticiones a horas distintas cada vez
    espera = random.randint(10, 90)
    log(f"Anti-deteccion: esperando {espera}s antes de consultar...")
    time.sleep(espera)

    hora = datetime.now().strftime("%H:%M del %d/%m/%Y")
    log(f"=== OVC check — {hora} — tramite: {AVC_TRAMITE} ===")

    # 1. Sitio oficial
    log("Verificando sitio oficial...")
    if verificar_sitio():
        log("*** CITA DISPONIBLE en sitio oficial! ***")
        enviar_telegram(
            f"CITA DISPONIBLE — Consulado Espana\n"
            f"Detectado: {hora}\n\n"
            f"Toca el boton para abrir el captcha YA:",
            con_boton=True,
        )
        sys.exit(0)
    log("Sitio: sin disponibilidad")

    # 2. Canal AVC
    log(f"Verificando canal AVC ({AVC_TRAMITE})...")
    hay_alerta, detalle = verificar_avc()
    if hay_alerta:
        log("*** Alerta en canal AVC! ***")
        enviar_telegram(
            f"ALERTA TEMPRANA — Canal AVC\n"
            f"Tramite: {AVC_TRAMITE} | {hora}\n\n"
            f"{detalle[:200]}\n\n"
            f"Vigila el sitio — toca para abrir:",
            con_boton=True,
        )
    else:
        log("  AVC: sin novedad")

    log("=== Check completado ===")
