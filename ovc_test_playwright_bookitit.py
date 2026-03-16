#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Test v3 — Parsear bkt_init_widget del POST con token.
Objetivo: verificar si el POST token devuelve agendas/dates con disponibilidad real.
También prueba JSONP con parámetros completos (src + timestamp).
"""

import os
import sys
import time
import re
import json as jsonlib
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PK  = os.environ.get("PK",  "28db94e270580be60f6e00285a7d8141f")
SID = os.environ.get("SID", "bkt873048")
WIDGET_URL = f"https://www.citaconsular.es/es/hosteds/widgetdefault/{PK}/{SID}"
TEXTO_SIN_CITAS = "No hay horas disponibles"

def log(msg): print(msg, flush=True)


def main():
    log("="*70)
    log("OVC TEST v3 — POST token + bkt_init_widget + JSONP completo")
    log(f"Widget: {WIDGET_URL}")
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
            Object.defineProperty(navigator, 'languages', { get: () => ['es-ES','es','en'] });
            window.chrome = { runtime: {} };
        """)

        all_requests = []
        all_responses = {}

        page = context.new_page()

        def on_request(req):
            all_requests.append(req.url)

        def on_response(resp):
            try:
                body = resp.body()
                all_responses[resp.url] = {
                    "status": resp.status,
                    "chars": len(body),
                    "text": body.decode("utf-8", errors="replace")
                }
            except Exception:
                pass

        page.on("request",  on_request)
        page.on("response", on_response)

        # ── 1. Cargar widget y esperar ──────────────────────────────────────
        log("\n[PASO 1] Cargando widget con Playwright...")
        page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=20000)
        time.sleep(15)

        html = page.content()
        log(f"  HTML final: {len(html)} chars | Title: {page.title()!r}")

        # ── 2. Ver TODAS las requests capturadas ────────────────────────────
        log(f"\n[PASO 2] Todas las requests de red ({len(all_requests)} total):")
        for url in all_requests:
            resp = all_responses.get(url, {})
            log(f"  {url[:100]}")
            if resp:
                preview = resp['text'][:150].replace('\n',' ')
                log(f"    → {resp['status']} | {resp['chars']} chars | {preview}")

        # ── 3. POST con token via fetch() interno ───────────────────────────
        log("\n[PASO 3] POST con token via fetch() interno...")
        ts = int(time.time() * 1000)
        post_result = page.evaluate(f"""
            async () => {{
                try {{
                    // Obtener token del HTML actual
                    const tokenInput = document.querySelector('input[name="token"]');
                    const token = tokenInput ? tokenInput.value : null;
                    if (!token) {{
                        // buscar en el HTML
                        const match = document.documentElement.innerHTML.match(/name="token"[^>]*value="([^"]+)"/);
                        if (!match) return {{ error: 'token no encontrado', html_snippet: document.documentElement.innerHTML.substring(0, 500) }};
                    }}
                    const tok = tokenInput ? tokenInput.value : document.documentElement.innerHTML.match(/name="token"[^>]*value="([^"]+)"/)[1];

                    const body = new URLSearchParams();
                    body.append('token', tok);

                    const r = await fetch("{WIDGET_URL}", {{
                        method: "POST",
                        credentials: "include",
                        headers: {{
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Referer": "{WIDGET_URL}",
                            "Origin": "https://www.citaconsular.es"
                        }},
                        body: body.toString()
                    }});
                    const text = await r.text();
                    return {{ status: r.status, chars: text.length, text: text.substring(0, 2000), token: tok }};
                }} catch(e) {{
                    return {{ error: e.toString() }};
                }}
            }}
        """)

        log(f"  POST result: status={post_result.get('status')} chars={post_result.get('chars')} token={post_result.get('token','N/A')[:25]}")
        if "error" in post_result:
            log(f"  ERROR: {post_result['error']}")
        else:
            post_text = post_result.get("text", "")
            log(f"  Preview: {post_text[:300]}")

            # Buscar bkt_init_widget en el response
            bkt_match = re.search(r'bkt_init_widget\s*=\s*(\{.+?\});', post_text, re.DOTALL)
            if bkt_match:
                log("\n  *** bkt_init_widget ENCONTRADO ***")
                try:
                    bkt_data = jsonlib.loads(bkt_match.group(1))
                    agendas = bkt_data.get("agendas", [])
                    dates   = bkt_data.get("dates", [])
                    log(f"  agendas: {len(agendas)} | dates: {len(dates)}")
                    if agendas or dates:
                        log(f"  AGENDAS: {agendas[:3]}")
                        log(f"  DATES: {dates[:5]}")
                        log("  ✅ HAY DISPONIBILIDAD DE CITAS" if dates else "  ❌ Sin fechas disponibles")
                    else:
                        log("  Sin agendas ni fechas → sin disponibilidad hoy")
                except Exception as e:
                    log(f"  Parse error: {e} | Raw: {bkt_match.group(1)[:200]}")
            else:
                log("  bkt_init_widget NO encontrado en el response")
                # Buscar señales de disponibilidad directas
                if TEXTO_SIN_CITAS in post_text:
                    log("  'No hay horas disponibles' presente → sin citas")
                elif "Huecos" in post_text or "selecttime" in post_text:
                    log("  *** SEÑAL DE CITAS DISPONIBLES ***")

        # ── 4. JSONP con parámetros completos ──────────────────────────────
        log("\n[PASO 4] JSONP con parámetros completos (src + timestamp)...")
        ts2 = int(time.time() * 1000)
        jsonp_url = f"https://www.citaconsular.es/onlinebookings/main/?callback=jQuery321_{ts2}&type=default&publickey={PK}&lang=es&services[]={SID}&version=5&src=https%3A%2F%2Fwww.citaconsular.es%2Fes%2Fhosteds%2Fwidgetdefault%2F{PK}%2F{SID}&_={ts2}"

        jsonp_result = page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch("{jsonp_url}", {{
                        credentials: "include",
                        headers: {{
                            "Accept": "*/*",
                            "Referer": "{WIDGET_URL}",
                            "Sec-Fetch-Dest": "script",
                            "Sec-Fetch-Mode": "no-cors",
                            "Sec-Fetch-Site": "same-origin"
                        }}
                    }});
                    const text = await r.text();
                    return {{ status: r.status, chars: text.length, text: text.substring(0, 500) }};
                }} catch(e) {{
                    return {{ error: e.toString() }};
                }}
            }}
        """)

        log(f"  JSONP result: {jsonp_result}")
        if jsonp_result.get("chars", 0) > 50:
            jtext = jsonp_result.get("text","")
            if "No hay horas" in jtext:
                log("  → Sin citas disponibles (confirmado vía JSONP)")
            elif "Exception" in jtext:
                log(f"  → Error Bookitit: {jtext[:200]}")
            elif "agendas" in jtext or "dates" in jtext or "Huecos" in jtext:
                log("  → *** DATOS DE DISPONIBILIDAD EN JSONP ***")
                log(f"  {jtext[:400]}")

        # ── 5. Intentar capturar el JSONP real del widget JS ───────────────
        log("\n[PASO 5] Requests de onlinebookings capturadas durante la carga:")
        jsonp_reqs = {u: r for u, r in all_responses.items() if "onlinebookings" in u}
        if jsonp_reqs:
            for url, resp in jsonp_reqs.items():
                log(f"  URL: {url[:120]}")
                log(f"  status={resp['status']} chars={resp['chars']}")
                log(f"  Texto: {resp['text'][:300]}")
        else:
            log("  Ninguna request a /onlinebookings/ fue capturada durante la carga del widget")
            log("  → El widget JS no está ejecutando el JSONP call")

        page.screenshot(path="/tmp/test_v3_final.png")
        browser.close()

    log("\n" + "="*70)
    log("FIN DEL TEST v3")
    log("="*70)


if __name__ == "__main__":
    main()
