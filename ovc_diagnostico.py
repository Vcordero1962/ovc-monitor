#!/usr/bin/env python3
"""
Diagnóstico: verifica si citaconsular.es responde con contenido real o 0 bytes.
Envía resultado a Telegram con bytes recibidos y screenshot.
"""
import os, sys, time, requests
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

URL       = os.getenv("URL_SISTEMA", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

def telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram no configurado")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
        print("Telegram:", "OK" if r.ok else r.text[:80])
    except Exception as e:
        print("Telegram error:", e)

def get_public_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=5).text.strip()
    except:
        return "?"

def check_site():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="es-ES"
        )
        response_info = {}
        def on_response(resp):
            if "citaconsular" in resp.url:
                try:
                    body = resp.body()
                    response_info["bytes"] = len(body)
                    response_info["status"] = resp.status
                    response_info["url"] = resp.url
                except:
                    response_info["bytes"] = -1

        page = ctx.new_page()
        page.on("response", on_response)

        try:
            page.goto(URL, timeout=35000, wait_until="domcontentloaded")
            time.sleep(3)
            html = page.content()
            screenshot = page.screenshot()
        except Exception as e:
            html = ""
            screenshot = None
            response_info["error"] = str(e)
        finally:
            browser.close()

        return html, screenshot, response_info

if __name__ == "__main__":
    ip = get_public_ip()
    print(f"IP publica: {ip}")
    print(f"URL: {URL}")
    print("Cargando sitio con Playwright...")

    html, screenshot, info = check_site()

    bytes_html  = len(html.encode("utf-8")) if html else 0
    status      = info.get("status", "?")
    net_bytes   = info.get("bytes", "?")
    error       = info.get("error", None)

    tiene_widget    = any(k in html for k in ["bookitit", "bk-widget", "datetime", "Selecciona"])
    tiene_bloqueado = "No hay horas disponibles" in html
    tiene_captcha   = any(k in html.lower() for k in ["captcha", "robot", "cloudflare", "access denied"])
    snippet = html[:300].replace("<", "&lt;").replace(">", "&gt;") if html else "(vacio)"

    if bytes_html == 0 or net_bytes == 0:
        estado = "BLOQUEADO — 0 bytes (IP bloqueada)"
        emoji  = "🔴"
    elif tiene_widget:
        estado = "PAGINA REAL — Widget de citas detectado"
        emoji  = "🟢"
    elif tiene_bloqueado:
        estado = "PAGINA REAL — Sin disponibilidad (normal)"
        emoji  = "🟡"
    elif tiene_captcha:
        estado = "CAPTCHA/WAF — Requiere verificacion humana"
        emoji  = "🟠"
    else:
        estado = f"PAGINA RECIBIDA — {bytes_html} bytes (sin widget)"
        emoji  = "🟡"

    msg = (
        f"<b>{emoji} DIAGNOSTICO OVC</b>\n"
        f"IP: <code>{ip}</code>\n"
        f"HTTP status: {status}\n"
        f"Bytes red: {net_bytes}\n"
        f"Bytes HTML: {bytes_html}\n"
        + (f"ERROR: {error}\n" if error else "") +
        f"\n<b>{estado}</b>\n\n"
        f"<b>Snippet:</b>\n<code>{snippet[:200]}</code>"
    )

    print(f"\n{'='*50}")
    print(f"IP: {ip}")
    print(f"Bytes red: {net_bytes} | HTML: {bytes_html}")
    print(f"Estado: {emoji} {estado}")
    print(f"{'='*50}")

    telegram(msg)

    if screenshot and bytes_html > 100 and BOT_TOKEN and CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": f"Screenshot desde {ip}"},
                files={"photo": ("screenshot.png", screenshot, "image/png")},
                timeout=15
            )
            print("Screenshot enviado a Telegram")
        except Exception as e:
            print("Error screenshot:", e)

    sys.exit(0 if bytes_html > 0 else 1)
