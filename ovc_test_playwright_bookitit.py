#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Test v4 — Extraer y parsear bkt_init_widget con regex (JS no es JSON estricto).
Foco: ¿tiene agendas[]? ¿tiene dates[]? ¿Qué hay en el POST response completo?
"""

import os, sys, time, re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PK  = os.environ.get("PK",  "28db94e270580be60f6e00285a7d8141f")
SID = os.environ.get("SID", "bkt873048")
WIDGET_URL = f"https://www.citaconsular.es/es/hosteds/widgetdefault/{PK}/{SID}"
TEXTO_SIN_CITAS = "No hay horas disponibles"

def log(msg): print(msg, flush=True)


def parse_bkt_widget(text):
    """Extrae datos clave de bkt_init_widget usando regex (evita problemas de JSON con comillas simples).
    Maneja claves JS sin comillas: agendas: [] y "agendas": [] son ambas válidas."""
    results = {}

    # Extraer agendas array — clave puede ser sin comillas (JS estándar) o con comillas
    m = re.search(r"(?:['\"]agendas['\"]|agendas)\s*:\s*(\[[^\]]*\])", text, re.DOTALL)
    results["agendas_raw"] = m.group(1) if m else "NO ENCONTRADO"
    results["agendas_count"] = len(re.findall(r'\{', m.group(1))) if m else 0

    # Extraer dates array — igual, clave sin/con comillas
    m2 = re.search(r"(?:['\"]dates['\"]|dates)\s*:\s*(\[[^\]]*\])", text, re.DOTALL)
    results["dates_raw"] = m2.group(1)[:200] if m2 else "NO ENCONTRADO"
    # Acepta fechas con o sin comillas: '2024-03-16' o "2024-03-16" o 2024-03-16
    results["dates_count"] = len(re.findall(r"\d{4}-\d{2}-\d{2}", m2.group(1))) if m2 else 0

    # Extraer id del centro
    m3 = re.search(r"['\"]id_centro['\"]\s*:\s*['\"]?(\w+)['\"]?", text)
    results["id_centro"] = m3.group(1) if m3 else "?"

    # Extraer nombre del servicio
    m4 = re.search(r"['\"]nombre['\"]\s*:\s*'([^']+)'", text)
    results["nombre_servicio"] = m4.group(1)[:80] if m4 else "?"

    # Extraer id_servicio
    m5 = re.search(r"['\"]id_servicio['\"]\s*:\s*['\"]?(\w+)['\"]?", text)
    results["id_servicio"] = m5.group(1) if m5 else "?"

    return results


def main():
    log("="*70)
    log("OVC TEST v4 — bkt_init_widget parser + análisis completo POST")
    log("="*70)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="es-ES", timezone_id="Europe/Madrid",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"}
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['es-ES','es'] });
            window.chrome = { runtime: {} };
        """)
        page = context.new_page()

        # ── 1. Cargar widget ────────────────────────────────────────────────
        log("\n[1] Cargando widget...")
        page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=20000)
        time.sleep(5)

        html_inicial = page.content()
        log(f"  HTML: {len(html_inicial)} chars")

        # Mostrar HTML completo inicial (es pequeño, 1331 chars)
        log("\n[2] HTML COMPLETO del widget (para entender qué carga):")
        log("-"*60)
        log(html_inicial)
        log("-"*60)

        # ── 2. Extraer token ────────────────────────────────────────────────
        token_match = re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']', html_inicial)
        if not token_match:
            token_match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html_inicial)

        if token_match:
            token = token_match.group(1)
            log(f"\n[3] Token encontrado: {token[:30]}...")
        else:
            log("\n[3] Token NO encontrado en HTML — buscando via JavaScript...")
            token = page.evaluate("""
                () => {
                    const inp = document.querySelector('input[name="token"]');
                    return inp ? inp.value : null;
                }
            """)
            if token:
                log(f"  Token via JS: {token[:30]}...")
            else:
                log("  Token no encontrado ni via HTML ni JS")
                token = None

        # ── 3. POST con token ───────────────────────────────────────────────
        if token:
            log(f"\n[4] POST con token a {WIDGET_URL}")
            post_result = page.evaluate(f"""
                async () => {{
                    const body = new URLSearchParams();
                    body.append('token', '{token}');
                    const r = await fetch("{WIDGET_URL}", {{
                        method: "POST",
                        credentials: "include",
                        headers: {{
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Referer": "{WIDGET_URL}"
                        }},
                        body: body.toString()
                    }});
                    const text = await r.text();
                    return {{ status: r.status, chars: text.length, text: text }};
                }}
            """)

            post_text = post_result.get("text","")
            log(f"  status={post_result.get('status')} chars={post_result.get('chars')}")

            # Mostrar primeros 2000 chars del response POST
            log("\n[5] Contenido POST response (primeros 2000 chars):")
            log("-"*60)
            log(post_text[:2000])
            log("-"*60)

            # Buscar bkt_init_widget
            bkt_pos = post_text.find("bkt_init_widget")
            if bkt_pos >= 0:
                log(f"\n[6] bkt_init_widget encontrado en posición {bkt_pos}")
                bkt_context = post_text[bkt_pos:bkt_pos+1000]
                log(f"Contexto: {bkt_context}")

                # Parsear con regex
                data = parse_bkt_widget(bkt_context)
                log(f"\n[7] DATOS EXTRAÍDOS:")
                log(f"  id_centro    : {data['id_centro']}")
                log(f"  id_servicio  : {data['id_servicio']}")
                log(f"  nombre       : {data['nombre_servicio']}")
                log(f"  agendas[]    : {data['agendas_count']} agenda(s) — {data['agendas_raw'][:100]}")
                log(f"  dates[]      : {data['dates_count']} fecha(s) — {data['dates_raw'][:100]}")

                if data['dates_count'] > 0:
                    log("\n  *** CITAS DISPONIBLES — HAY FECHAS EN dates[] ***")
                elif data['agendas_count'] > 0:
                    log("\n  Hay agendas pero sin fechas → sin citas disponibles hoy")
                else:
                    log("\n  Sin agendas ni fechas → sin citas disponibles")
            else:
                log("\n[6] bkt_init_widget NO en el POST response")
                if TEXTO_SIN_CITAS in post_text:
                    log("  'No hay horas disponibles' presente")
                log(f"  Fragmentos relevantes: {re.findall(r'(bookitit|agenda|fecha|cita|slot|avail).{0,50}', post_text, re.I)[:5]}")
        else:
            log("\n[4] Sin token — no se puede hacer POST")

        page.screenshot(path="/tmp/test_v4.png")
        browser.close()

    log("\n" + "="*70)
    log("FIN TEST v4")
    log("="*70)


if __name__ == "__main__":
    main()
