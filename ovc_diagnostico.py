#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Diagnóstico — Prueba cada capa de comunicación e informa por Telegram
Ejecutar local: python ovc_diagnostico.py
Ejecutar en GitHub Actions: añadir step con run: python ovc_diagnostico.py

Detecta EXACTAMENTE qué está fallando:
  ✓ Lectura de variables de entorno (secrets de GitHub)
  ✓ Acceso a api.telegram.org (¿bloqueado el runner?)
  ✓ Qué responde citaconsular.es desde ESTA IP (bytes, headers, contenido)
  ✓ Qué IP pública usa el runner
  ✓ Prueba via proxy europeo alternativo
  ✓ Prueba con Playwright (headless Chromium)
  ✓ Screenshot y envío a Telegram
"""

import os
import sys
import time
import socket
import traceback
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # En GitHub Actions no hay .env, usa secrets como env vars

# ─── Configuración desde entorno ───────────────────────────────────────────────
BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
URL_CITA   = os.getenv("URL_SISTEMA", "https://www.citaconsular.es/es/hosteds/widgetdefault/25b6cfa9f112aef4ca19457abc237f7ba/#services")
AVC_TRAMITE = os.getenv("AVC_TRAMITE", "LMD")

# Proxies europeos públicos para prueba (HTTP CONNECT)
EU_PROXIES = [
    "144.124.253.249:3128",   # Amsterdam NL — verificado en sesión anterior
    "51.158.68.68:8811",      # Paris FR — Scaleway
    "185.162.231.106:80",     # Frankfurt DE
]

RESULTADOS = []

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    RESULTADOS.append(msg)

def sep(titulo=""):
    log(f"{'─'*40}")
    if titulo:
        log(f"  {titulo}")

# ─── Envío Telegram ─────────────────────────────────────────────────────────
def telegram_texto(msg: str) -> bool:
    """Envía texto puro. Retorna True si ok."""
    if not BOT_TOKEN or not CHAT_ID:
        log("⚠️  Telegram NO configurado — bot_token o chat_id vacío")
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=15,
        )
        if r.ok:
            log(f"✅ Telegram OK — message_id={r.json().get('result',{}).get('message_id','?')}")
            return True
        else:
            log(f"❌ Telegram ERROR: {r.status_code} — {r.text[:120]}")
            return False
    except Exception as e:
        log(f"❌ Telegram EXCEPCIÓN: {e}")
        return False

def telegram_foto(path_png: str, caption: str = "") -> bool:
    """Envía screenshot PNG. Retorna True si ok."""
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        import requests
        with open(path_png, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption[:1024]},
                files={"photo": ("diag.png", f, "image/png")},
                timeout=30,
            )
        if r.ok:
            log(f"✅ Telegram foto OK")
            return True
        else:
            log(f"❌ Telegram foto ERROR: {r.status_code} — {r.text[:120]}")
            return False
    except Exception as e:
        log(f"❌ Telegram foto EXCEPCIÓN: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Variables de entorno
# ═══════════════════════════════════════════════════════════════════════════════
def test_env():
    sep("TEST 1 — Variables de entorno")
    vars_criticas = {
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_CHAT_ID":   CHAT_ID,
        "URL_SISTEMA":        URL_CITA,
        "AVC_TRAMITE":        AVC_TRAMITE,
    }
    ok = True
    for nombre, valor in vars_criticas.items():
        if valor:
            preview = valor[:20] + "..." if len(valor) > 20 else valor
            log(f"  ✅ {nombre} = {preview}")
        else:
            log(f"  ❌ {nombre} = VACÍO — falta en GitHub Secrets o .env")
            ok = False
    return ok


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2 — IP pública del runner
# ═══════════════════════════════════════════════════════════════════════════════
def test_ip_publica():
    sep("TEST 2 — IP pública del runner")
    import requests
    servicios = [
        "https://api.ipify.org?format=json",
        "https://ipinfo.io/json",
        "https://ifconfig.me/all.json",
    ]
    for url in servicios:
        try:
            r = requests.get(url, timeout=8)
            if r.ok:
                data = r.json()
                ip   = data.get("ip") or data.get("IP_ADDR", "?")
                pais = data.get("country", data.get("country_code", "?"))
                ciudad = data.get("city", "")
                log(f"  📍 IP: {ip} | País: {pais} | Ciudad: {ciudad}")
                if pais.upper() in ("US", "USA", "UNITED STATES"):
                    log("  ⚠️  RUNNER EN EEUU — citaconsular.es bloqueará desde esta IP")
                elif pais.upper() in ("NL", "DE", "FR", "ES", "GB", "EU"):
                    log("  ✅ RUNNER EN EUROPA — citaconsular.es debería responder")
                return ip, pais
        except Exception as e:
            log(f"  ({url[:40]}: {e})")
    log("  ❌ No se pudo determinar IP pública")
    return "?", "?"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Conectividad a api.telegram.org
# ═══════════════════════════════════════════════════════════════════════════════
def test_telegram_api():
    sep("TEST 3 — Conectividad api.telegram.org")
    import requests
    try:
        # TCP puro al puerto 443
        sock = socket.create_connection(("api.telegram.org", 443), timeout=8)
        sock.close()
        log("  ✅ TCP:443 → api.telegram.org OK")
    except Exception as e:
        log(f"  ❌ TCP:443 → api.telegram.org FALLÓ: {e}")

    # GET /getMe
    if BOT_TOKEN:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10)
            if r.ok:
                nombre = r.json().get("result", {}).get("first_name", "?")
                log(f"  ✅ Bot autenticado: {nombre}")
            else:
                log(f"  ❌ getMe: {r.status_code} — {r.text[:80]}")
        except Exception as e:
            log(f"  ❌ getMe excepción: {e}")
    else:
        log("  ⚠️  TELEGRAM_BOT_TOKEN vacío — omitiendo getMe")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4 — citaconsular.es desde IP directa (requests)
# ═══════════════════════════════════════════════════════════════════════════════
def test_cita_directa():
    sep("TEST 4 — citaconsular.es directo (requests, sin VPN)")
    import requests
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "es-ES,es;q=0.9",
        }
        r = requests.get(
            "https://www.citaconsular.es/",
            headers=headers, timeout=20, allow_redirects=True,
        )
        bytes_recibidos = len(r.content)
        log(f"  HTTP {r.status_code} | Content-Length: {bytes_recibidos} bytes")
        log(f"  Content-Type: {r.headers.get('Content-Type','?')}")
        log(f"  Server: {r.headers.get('Server','?')}")
        if bytes_recibidos == 0:
            log("  ❌ RESPUESTA VACÍA — runner bloqueado por WAF (IP USA)")
        elif bytes_recibidos < 200:
            log(f"  ⚠️  Respuesta muy corta: {r.content[:200]}")
        else:
            log(f"  ✅ Respuesta OK — primeros 100 chars: {r.text[:100]}")
        return bytes_recibidos
    except Exception as e:
        log(f"  ❌ Excepción: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5 — citaconsular.es vía proxy europeo
# ═══════════════════════════════════════════════════════════════════════════════
def test_cita_proxy():
    sep("TEST 5 — citaconsular.es via proxy europeo")
    import requests
    for proxy_addr in EU_PROXIES:
        try:
            proxies = {"http": f"http://{proxy_addr}", "https": f"http://{proxy_addr}"}
            headers = {"User-Agent": "Mozilla/5.0 Chrome/122.0"}
            r = requests.get(
                "https://www.citaconsular.es/",
                headers=headers, proxies=proxies, timeout=20,
            )
            bytes_recibidos = len(r.content)
            log(f"  Proxy {proxy_addr} → HTTP {r.status_code} | {bytes_recibidos} bytes")
            if bytes_recibidos > 500:
                log(f"  ✅ PROXY FUNCIONA — recibidos {bytes_recibidos} bytes con IP europea")
                return proxy_addr, bytes_recibidos
            elif bytes_recibidos == 0:
                log(f"  ❌ Aún 0 bytes via proxy")
            else:
                log(f"  ⚠️  {bytes_recibidos} bytes — respuesta parcial: {r.content[:80]}")
        except Exception as e:
            log(f"  ❌ {proxy_addr}: {e}")
    log("  ❌ Ningún proxy europeo funcionó")
    return None, 0


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6 — Playwright headless + screenshot
# ═══════════════════════════════════════════════════════════════════════════════
def test_playwright_screenshot():
    sep("TEST 6 — Playwright headless → citaconsular.es")
    screenshot_path = Path(__file__).parent / "diag_screenshot.png"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="es-ES",
            )
            ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)
            page = ctx.new_page()

            log(f"  Navegando a: {URL_CITA[:70]}...")
            try:
                resp = page.goto(URL_CITA, timeout=30000, wait_until="domcontentloaded")
                status = resp.status if resp else "?"
                log(f"  HTTP status Playwright: {status}")
            except Exception as e:
                log(f"  goto excepción: {e}")

            time.sleep(3)

            contenido = page.content()
            log(f"  Contenido HTML: {len(contenido)} caracteres")

            if len(contenido) < 200:
                log(f"  ❌ PÁGINA VACÍA — WAF bloqueó. Contenido: {contenido[:100]}")
            elif "No hay horas disponibles" in contenido:
                log("  ✅ Página cargó — dice: No hay horas disponibles")
            elif any(k in contenido for k in ["bookitit", "datetime", "horas", "Selecciona"]):
                log("  🎉 ¡CITA POSIBLEMENTE DISPONIBLE!")
            else:
                log(f"  ⚠️  Página cargó pero sin marcadores esperados. Preview: {contenido[:200]}")

            # Siempre tomar screenshot
            page.screenshot(path=str(screenshot_path), full_page=False)
            log(f"  📸 Screenshot guardado: {screenshot_path}")
            browser.close()

        return str(screenshot_path) if screenshot_path.exists() else None

    except ImportError:
        log("  ⚠️  playwright no instalado — pip install playwright && playwright install chromium")
        return None
    except Exception as e:
        log(f"  ❌ Playwright excepción: {e}")
        traceback.print_exc()
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# INFORME FINAL
# ═══════════════════════════════════════════════════════════════════════════════
def enviar_informe(ip, pais, bytes_directos, proxy_ok, screenshot_path):
    sep("INFORME FINAL → Telegram")

    icono_ip  = "🇪🇺" if pais.upper() in ("NL","DE","FR","ES","GB","CH","NO") else "🇺🇸"
    icono_cita = "✅" if bytes_directos > 500 else ("⚠️" if bytes_directos > 0 else "❌")
    icono_proxy = "✅" if proxy_ok else "❌"

    hora = datetime.now().strftime("%H:%M del %d/%m/%Y")
    env_ok = bool(BOT_TOKEN and CHAT_ID and URL_CITA)

    msg = (
        f"🔬 <b>OVC Diagnóstico</b> — {hora}\n\n"
        f"{icono_ip} <b>IP runner:</b> {ip} ({pais})\n"
        f"{icono_cita} <b>citaconsular.es directo:</b> {bytes_directos} bytes\n"
        f"{icono_proxy} <b>Via proxy EU:</b> {'OK' if proxy_ok else 'FALLÓ'}\n"
        f"{'✅' if env_ok else '❌'} <b>Variables entorno:</b> {'completas' if env_ok else 'INCOMPLETAS'}\n\n"
        f"<b>Diagnóstico:</b>\n"
    )

    if bytes_directos == 0 and not proxy_ok:
        msg += "❌ El runner no puede ver citaconsular.es\ndirecto NI via proxy. Necesita VPN europea (WireGuard)."
    elif bytes_directos == 0 and proxy_ok:
        msg += "⚠️ Sin VPN/proxy = 0 bytes (bloqueado).\nCon proxy EU funciona. Agregar proxy al script."
    elif bytes_directos > 500:
        msg += "✅ Acceso directo funciona. Si no llegan alertas,\nrevisar lógica de detección de citas."
    else:
        msg += f"⚠️ Respuesta parcial ({bytes_directos} bytes). Puede ser bloqueo parcial."

    ok = telegram_texto(msg)

    if not ok and not BOT_TOKEN:
        log("  No se pudo enviar — faltan credenciales Telegram")
        log("  Resultado del diagnóstico impreso en consola arriba ↑")
        return

    # Enviar screenshot si existe
    if screenshot_path:
        caption = f"Screenshot citaconsular.es desde IP {ip} ({pais})"
        telegram_foto(screenshot_path, caption)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    log("=" * 50)
    log("  OVC DIAGNÓSTICO — Iniciando pruebas...")
    log("=" * 50)

    # Instalar requests si falta (GitHub Actions fresh environment)
    try:
        import requests
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
        import requests

    env_ok       = test_env()
    ip, pais     = test_ip_publica()
    test_telegram_api()
    bytes_directo = test_cita_directa()
    proxy_addr, bytes_proxy = test_cita_proxy()
    screenshot   = test_playwright_screenshot()

    enviar_informe(ip, pais, bytes_directo, proxy_addr is not None, screenshot)

    log("=" * 50)
    log("  Diagnóstico completado.")
    log("=" * 50)

    # Exit 0 siempre — este script solo reporta, no falla
    sys.exit(0)
