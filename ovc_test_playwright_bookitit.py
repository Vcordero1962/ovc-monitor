#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Test v2 — Playwright profundo: captura todas las requests de red,
navega iframes, espera más, e intenta fetch manual del JSONP desde el contexto de la página.
"""

import os
import sys
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PK  = os.environ.get("PK",  "28db94e270580be60f6e00285a7d8141f")
SID = os.environ.get("SID", "bkt873048")

WIDGET_BOOKITIT     = f"https://app.bookitit.com/es/hosteds/widgetdefault/{PK}/{SID}"
WIDGET_CITACONSULAR = f"https://www.citaconsular.es/es/hosteds/widgetdefault/{PK}/{SID}"
JSONP_PATH = f"/onlinebookings/main/?callback=jQuery321&type=default&publickey={PK}&lang=es&services[]={SID}&version=5"

TEXTO_SIN_CITAS = "No hay horas disponibles"

def log(msg): print(msg, flush=True)


def probar_url(context, url, nombre):
    log(f"\n{'='*65}")
    log(f"  TEST: {nombre}")
    log(f"  URL: {url}")
    log(f"{'='*65}")

    all_requests = []
    all_responses = {}

    page = context.new_page()

    def on_request(req):
        all_requests.append(req.url)

    def on_response(resp):
        try:
            body_bytes = resp.body()
            all_responses[resp.url] = {
                "status": resp.status,
                "chars": len(body_bytes),
                "preview": body_bytes[:300].decode("utf-8", errors="replace").replace("\n"," ")
            }
        except Exception:
            pass

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)

        # Esperar 20 segundos para que el widget cargue completamente
        log("  Esperando 20s para carga completa del widget...")
        time.sleep(20)

        html = page.content()
        log(f"  [PAGE] Title: {page.title()!r}")
        log(f"  [PAGE] HTML: {len(html)} chars")

        # Todas las requests de red capturadas
        log(f"  [NETWORK] Total requests capturadas: {len(all_requests)}")
        bookitit_reqs = [u for u in all_requests if "bookitit" in u or "onlinebookings" in u]
        log(f"  [NETWORK] Requests Bookitit/onlinebookings: {len(bookitit_reqs)}")
        for u in bookitit_reqs[:8]:
            resp_data = all_responses.get(u, {})
            log(f"    → {u[:100]}")
            if resp_data:
                log(f"       status={resp_data['status']} chars={resp_data['chars']} preview: {resp_data['preview'][:100]}")

        # Detectar señales
        imperva = any(s.lower() in html.lower() for s in ["_Incapsula_Resource","incapsula","imperva"])
        sin_citas = TEXTO_SIN_CITAS in html
        con_citas = any(p in html for p in ["Huecos libres","clsDivDatetimeSlot","bkt_slot","selecttime"])
        log(f"  [IMPERVA] {('BLOQUEADO ❌' if imperva else 'LIBRE ✅')}")
        log(f"  [CITAS] {'Sin citas (widget OK)' if sin_citas else ('CON CITAS ✅' if con_citas else 'Sin datos de citas aún')}")

        # Iframes en la página
        frames = page.frames
        log(f"  [FRAMES] Total frames: {len(frames)}")
        for i, frame in enumerate(frames):
            try:
                frame_html = frame.content()
                frame_url = frame.url
                has_citas = TEXTO_SIN_CITAS in frame_html or "bkt_slot" in frame_html or "Huecos" in frame_html
                log(f"    Frame {i}: url={frame_url[:80]} chars={len(frame_html)} citas={has_citas}")
                if has_citas or len(frame_html) > 2000:
                    snippet = re.search(r'(No hay horas|Huecos|bkt_init|selecttime|agendas).{0,150}', frame_html, re.IGNORECASE)
                    if snippet:
                        log(f"      SNIPPET: {snippet.group()[:150]}")
            except Exception as e:
                log(f"    Frame {i}: ERROR {e}")

        # Intentar fetch manual del JSONP desde contexto de la página (tiene cookies)
        log("  [FETCH MANUAL] Intentando fetch() interno del JSONP...")
        try:
            base = "https://app.bookitit.com" if "app.bookitit.com" in url else "https://www.citaconsular.es"
            jsonp_url = base + JSONP_PATH
            result = page.evaluate(f"""
                async () => {{
                    try {{
                        const r = await fetch("{jsonp_url}", {{
                            method: "GET",
                            credentials: "include",
                            headers: {{
                                "Accept": "*/*",
                                "Referer": "{url}",
                                "Sec-Fetch-Dest": "script",
                                "Sec-Fetch-Mode": "no-cors",
                                "Sec-Fetch-Site": "same-origin"
                            }}
                        }});
                        const text = await r.text();
                        return {{ status: r.status, chars: text.length, preview: text.substring(0, 300) }};
                    }} catch(e) {{
                        return {{ error: e.toString() }};
                    }}
                }}
            """)
            log(f"  [FETCH MANUAL] Resultado: {result}")
            if result and result.get("chars", 0) > 100:
                prev = result.get("preview","")
                sin = TEXTO_SIN_CITAS in prev
                con = "Huecos" in prev or "bkt_slot" in prev or "agendas" in prev
                log(f"  [FETCH MANUAL] Datos útiles: {'SIN CITAS' if sin else ('CON CITAS ✅' if con else 'RESPONDE pero sin datos conocidos')}")
        except Exception as e:
            log(f"  [FETCH MANUAL] ERROR: {e}")

        # POST con token (técnica alternativa)
        log("  [POST TOKEN] Intentando POST con token Bookitit...")
        try:
            token_result = page.evaluate(f"""
                async () => {{
                    try {{
                        // Paso 1: obtener token de la pagina del widget
                        const r1 = await fetch("{url}", {{ credentials: "include" }});
                        const html = await r1.text();
                        const match = html.match(/name="token"[^>]*value="([^"]+)"/);
                        if (!match) return {{ error: "token no encontrado en HTML" }};
                        const token = match[1];

                        // Paso 2: POST con el token
                        const body = new URLSearchParams();
                        body.append("token", token);
                        const r2 = await fetch("{url}", {{
                            method: "POST",
                            credentials: "include",
                            headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
                            body: body.toString()
                        }});
                        const text2 = await r2.text();
                        return {{ status: r2.status, chars: text2.length, preview: text2.substring(0, 400), token: token }};
                    }} catch(e) {{
                        return {{ error: e.toString() }};
                    }}
                }}
            """)
            log(f"  [POST TOKEN] Resultado: status={token_result.get('status')} chars={token_result.get('chars')} token={token_result.get('token','N/A')[:20]}")
            if token_result.get("chars", 0) > 100:
                prev = token_result.get("preview","")
                sin = TEXTO_SIN_CITAS in prev
                con = "agendas" in prev or "bkt_init" in prev or "Huecos" in prev
                log(f"  [POST TOKEN] Datos: {'SIN CITAS' if sin else ('CON CITAS / AGENDAS ✅' if con else 'Responde: ' + prev[:100])}")
        except Exception as e:
            log(f"  [POST TOKEN] ERROR: {e}")

        page.screenshot(path=f"/tmp/test_{nombre[:25].replace('/','_')}.png")

        return {
            "nombre": nombre,
            "imperva": imperva,
            "sin_citas": sin_citas,
            "con_citas": con_citas,
            "html_chars": len(html),
            "bookitit_requests": len(bookitit_reqs),
        }

    except Exception as e:
        log(f"  [ERROR FATAL] {type(e).__name__}: {e}")
        return {"nombre": nombre, "error": str(e)}
    finally:
        page.close()


def main():
    log("="*70)
    log("OVC TEST v2 — Playwright profundo: red + iframes + fetch manual + POST token")
    log("="*70)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled","--lang=es-ES"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['es-ES','es','en'] });
            window.chrome = { runtime: {} };
        """)

        r1 = probar_url(context, WIDGET_BOOKITIT,     "A-app.bookitit.com")
        r2 = probar_url(context, WIDGET_CITACONSULAR, "B-citaconsular.es")

        browser.close()

    log("\n" + "="*70)
    log("RESUMEN")
    log("="*70)
    for r in [r1, r2]:
        if "error" in r:
            log(f"  {r['nombre']}: ERROR — {r['error']}")
        else:
            bloq = "BLOQUEADO ❌" if r.get("imperva") else "LIBRE ✅"
            datos = "SIN CITAS (OK)" if r.get("sin_citas") else ("CON CITAS ✅" if r.get("con_citas") else "SIN DATOS")
            log(f"  {r['nombre']}: {bloq} | Citas: {datos} | HTML: {r.get('html_chars')} | BkReqs: {r.get('bookitit_requests')}")


if __name__ == "__main__":
    main()
