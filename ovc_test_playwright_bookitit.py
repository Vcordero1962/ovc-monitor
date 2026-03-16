#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Test — Playwright en app.bookitit.com directo (sin pasar por citaconsular.es/Imperva)

Hipotesis: el WAF Imperva esta en citaconsular.es, no en app.bookitit.com.
Si Playwright carga el widget desde app.bookitit.com, las llamadas JSONP de disponibilidad
van a app.bookitit.com/onlinebookings/main/ — que puede no tener el mismo bloqueo.

Comparacion:
  URL A: https://app.bookitit.com/es/hosteds/widgetdefault/{PK}/{SID}   <- SIN Imperva?
  URL B: https://www.citaconsular.es/es/hosteds/widgetdefault/{PK}/{SID} <- CON Imperva

Ejecutar via: gh workflow run ovc_test_playwright_bookitit.yml
"""

import os
import sys
import json
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PK  = os.environ.get("PK",  "28db94e270580be60f6e00285a7d8141f")
SID = os.environ.get("SID", "bkt873048")
CHROMIUM_PROFILE = os.environ.get("CHROMIUM_PROFILE_DIR", "/tmp/chromium-ovc-test")

WIDGET_BOOKITIT    = f"https://app.bookitit.com/es/hosteds/widgetdefault/{PK}/{SID}"
WIDGET_CITACONSULAR = f"https://www.citaconsular.es/es/hosteds/widgetdefault/{PK}/{SID}"

TEXTO_SIN_CITAS = "No hay horas disponibles"
TEXTO_CON_CITAS_PATTERNS = ["Huecos libres", "clsDivDatetimeSlot", "selecttime", "bkt_slot"]

def log(msg):
    print(msg, flush=True)


def probar_url(page, url, nombre, timeout_ms=25000):
    """
    Carga la URL con Playwright y analiza si:
    - Imperva la bloqueo (challenge page / captcha)
    - El widget cargo correctamente
    - Hay o no citas disponibles
    """
    log(f"\n{'='*60}")
    log(f"  PROBANDO: {nombre}")
    log(f"  URL: {url}")
    log(f"{'='*60}")

    requests_capturadas = []

    def on_request(req):
        if "onlinebookings" in req.url or "bookitit" in req.url:
            requests_capturadas.append({"url": req.url[:120], "method": req.method})

    def on_response(resp):
        if "onlinebookings" in resp.url:
            try:
                body = resp.body()
                log(f"  [NETWORK] onlinebookings response: status={resp.status} chars={len(body)}")
                preview = body[:300].decode("utf-8", errors="replace").replace("\n", " ")
                log(f"  [NETWORK] Preview: {preview}")
            except Exception:
                pass

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        time.sleep(3)  # dejar que JS cargue el widget

        # Esperar elemento del widget o timeout
        try:
            page.wait_for_selector('[id*="bookitit"], [class*="bookitit"], [id*="bkt"], iframe',
                                   timeout=10000)
            log("  [DOM] Elemento Bookitit encontrado en el DOM")
        except PWTimeout:
            log("  [DOM] Timeout esperando elemento Bookitit — widget puede no haber cargado")

        html = page.content()
        title = page.title()
        log(f"  [PAGE] Title: {title!r}")
        log(f"  [PAGE] HTML total chars: {len(html)}")

        # Detectar bloqueo Imperva
        imperva_signals = ["_Incapsula_Resource", "incapsula", "imperva", "challenge",
                           "Ray ID", "Cloudflare", "Please enable cookies"]
        bloqueado = any(s.lower() in html.lower() for s in imperva_signals)
        log(f"  [IMPERVA] Bloqueo detectado: {'SI ❌' if bloqueado else 'NO ✅'}")

        # Detectar disponibilidad
        sin_citas = TEXTO_SIN_CITAS in html
        con_citas = any(p in html for p in TEXTO_CON_CITAS_PATTERNS)

        if sin_citas:
            log("  [DISPONIBILIDAD] 'No hay horas disponibles' — widget cargó, sin citas hoy")
        elif con_citas:
            log("  [DISPONIBILIDAD] *** CITAS DISPONIBLES DETECTADAS *** ✅")
        else:
            log("  [DISPONIBILIDAD] Widget no mostró datos de disponibilidad (puede ser JS tardío)")

        # Mostrar requests de red capturadas
        if requests_capturadas:
            log(f"  [NETWORK] Requests Bookitit capturadas ({len(requests_capturadas)}):")
            for r in requests_capturadas[:5]:
                log(f"    {r['method']} {r['url']}")
        else:
            log("  [NETWORK] Sin requests a onlinebookings capturadas")

        # Screenshot para inspección visual
        screenshot_path = f"/tmp/test_{nombre.replace(' ','_').replace('/','_')[:30]}.png"
        page.screenshot(path=screenshot_path, full_page=False)
        log(f"  [SCREENSHOT] Guardado: {screenshot_path}")

        # Snippet HTML relevante
        import re
        snippet = re.search(r'(bookitit|bkt_init|No hay horas|Huecos).{0,200}', html, re.IGNORECASE)
        if snippet:
            log(f"  [HTML SNIPPET] ...{snippet.group()[:200]}...")

        return {
            "nombre": nombre,
            "bloqueado": bloqueado,
            "sin_citas": sin_citas,
            "con_citas": con_citas,
            "html_chars": len(html),
            "requests_red": len(requests_capturadas),
        }

    except Exception as e:
        log(f"  [ERROR] {type(e).__name__}: {e}")
        return {"nombre": nombre, "error": str(e)}
    finally:
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)


def main():
    log("=" * 70)
    log("OVC TEST — Playwright: app.bookitit.com vs citaconsular.es")
    log("Objetivo: verificar si Imperva bloquea solo citaconsular.es o tambien app.bookitit.com")
    log("=" * 70)

    resultados = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--lang=es-ES",
            ]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            }
        )

        # Eliminar señales de automatizacion
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en'] });
            window.chrome = { runtime: {} };
        """)

        page = context.new_page()

        # TEST 1: app.bookitit.com (sin Imperva esperado)
        r1 = probar_url(page, WIDGET_BOOKITIT, "A-app.bookitit.com")
        resultados.append(r1)
        time.sleep(2)

        # TEST 2: citaconsular.es (con Imperva - referencia)
        r2 = probar_url(page, WIDGET_CITACONSULAR, "B-citaconsular.es")
        resultados.append(r2)

        browser.close()

    # Resumen final
    log("\n" + "=" * 70)
    log("RESUMEN FINAL")
    log("=" * 70)
    for r in resultados:
        if "error" in r:
            log(f"  {r['nombre']}: ERROR — {r['error']}")
            continue
        bloq = "BLOQUEADO ❌" if r.get("bloqueado") else "LIBRE ✅"
        datos = "SIN CITAS (widget OK)" if r.get("sin_citas") else ("CON CITAS ✅" if r.get("con_citas") else "SIN DATOS")
        log(f"  {r['nombre']}: {bloq} | Disponibilidad: {datos} | HTML: {r.get('html_chars','?')} chars")

    log("")
    r_bookitit = next((r for r in resultados if "bookitit" in r.get("nombre","").lower()), None)
    r_citacons = next((r for r in resultados if "citaconsular" in r.get("nombre","").lower()), None)

    if r_bookitit and r_citacons:
        if not r_bookitit.get("bloqueado") and r_citacons.get("bloqueado"):
            log("*** CONCLUSION: app.bookitit.com NO tiene Imperva — SOLUCION VIABLE ***")
            log("    Accion: cambiar URL del bot de citaconsular.es a app.bookitit.com")
        elif not r_bookitit.get("bloqueado") and not r_citacons.get("bloqueado"):
            log("*** CONCLUSION: Ambas URLs pasan — quizas Imperva no bloquea Playwright con estos headers ***")
            log("    Accion: verificar si los datos de disponibilidad se cargan correctamente")
        elif r_bookitit.get("bloqueado") and r_citacons.get("bloqueado"):
            log("*** CONCLUSION: Ambas bloqueadas — Imperva detecta GitHub Actions en ambos dominios ***")
            log("    Accion: necesario ScrapingAnt (Paso 2) o curl_cffi mas profundo")
        else:
            log("*** CONCLUSION: Resultado inesperado — revisar logs detallados arriba ***")


if __name__ == "__main__":
    main()
