#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ovc_spy.py — Captura COMPLETA del flujo de red del widget Bookitit/citaconsular
             usando Playwright con interceptación nativa de requests.

NO requiere proxy externo. Abre un browser real (headless o visible),
navega al widget y captura TODOS los intercambios HTTP/HTTPS con
máximo detalle: URL, método, headers, cookies, body, respuesta completa.

USO:
  python -X utf8 ovc_spy.py [URL] [--visible]

  URL      = URL del widget a espiar (default: URL_LEGA del .env)
  --visible = muestra el browser (útil para ver qué pasa en pantalla)

SALIDA:
  logs/ovc_spy_TIMESTAMP.json   — todos los intercambios en JSON
  logs/ovc_spy_TIMESTAMP.txt    — reporte legible con análisis
  Consola: resumen en tiempo real con hallazgos clave
"""

import sys
import json
import re
import os
import time
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Configuración ─────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent / "logs"
BASE_DIR.mkdir(exist_ok=True)
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_JSON  = BASE_DIR / f"ovc_spy_{TIMESTAMP}.json"
OUT_TXT   = BASE_DIR / f"ovc_spy_{TIMESTAMP}.txt"

URL_LEGA    = os.getenv("URL_LEGA",    "https://www.citaconsular.es/es/hosteds/widgetdefault/25b6cfa9f112aef4ca19457abc237f7ba/")
URL_LMD     = os.getenv("URL_LMD",     "")
URL_PAS     = os.getenv("URL_PASAPORTE","")

# Esperar N segundos tras carga para que el JS haga todas sus llamadas
ESPERA_POST_CARGA = 12   # segundos — el widget JS hace AJAX async

# ── Almacén global ────────────────────────────────────────────────────────────
intercambios: list = []

# ── Helpers ───────────────────────────────────────────────────────────────────

def _parsear_jsonp(texto: str) -> dict | None:
    m = re.match(r'(\w+)\s*\((.*)\)\s*;?\s*$', texto.strip(), re.DOTALL)
    if m:
        try:
            return {"callback": m.group(1), "data": json.loads(m.group(2))}
        except Exception:
            pass
    return None


def _analizar_html(html: str) -> dict:
    h = {}
    # Token CSRF / Imperva
    t = (re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']{10,})["\']', html) or
         re.search(r'value=["\']([^"\']{10,})["\'][^>]*name=["\']token["\']', html))
    if t:
        h["token_csrf"] = t.group(1)

    # PKs
    pk = re.findall(r'(?:publickey|pk)[=:\s"\']+([a-f0-9]{28,36})', html, re.I)
    if pk:
        h["public_keys"] = list(set(pk))

    # SIDs
    sid = re.findall(r'services\[\][\s=:"\']+(\d+)', html)
    if sid:
        h["service_ids"] = list(set(sid))

    # Scripts externos
    sc = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I)
    if sc:
        h["scripts"] = sc[:15]

    # loadermaec / mainv1 — scripts clave de Bookitit
    bkt_scripts = [s for s in sc if any(x in s for x in ["loadermaec","mainv1","widgets/default","bookitit","bkt"])]
    if bkt_scripts:
        h["bookitit_scripts"] = bkt_scripts

    # Imperva
    if any(x in html.lower() for x in ["incapsula","imperva","reese84","__imp_apg"]):
        h["imperva"] = True
        ch = re.search(r'(IncapsulaRequest|reese84|__imp_apg_hmac)', html)
        h["imperva_challenge"] = ch.group(1) if ch else "detectado"

    # Captcha
    if "hcaptcha" in html.lower():
        h["captcha"] = "hCaptcha"
    elif "recaptcha" in html.lower():
        h["captcha"] = "reCAPTCHA"

    # PHPSESSID en HTML
    s = re.search(r'PHPSESSID[^=]*=\s*([a-f0-9]{20,})', html)
    if s:
        h["phpsessid_en_html"] = s.group(1)

    # Widget cargado
    if any(x in html for x in ["bkt_init_widget", "bookitit-widget", "bk-container", "#datetime"]):
        h["widget_presente"] = True

    return h


def _resumen_request(item: dict) -> str:
    """Línea compacta para consola."""
    url   = item["url"][:100]
    met   = item["metodo"]
    st    = item.get("resp_status", "?")
    sz    = item.get("resp_size", 0)
    tp    = item.get("resp_tipo", "")
    bkt   = "✅BKT " if item.get("bkt_callback") else ""
    hal   = item.get("hallazgos", {})
    flags = []
    if hal.get("token_csrf"):
        flags.append(f"TOKEN={hal['token_csrf'][:12]}...")
    if hal.get("public_keys"):
        flags.append(f"PK={hal['public_keys'][0][:14]}...")
    if hal.get("service_ids"):
        flags.append(f"SID={hal['service_ids']}")
    if hal.get("imperva"):
        flags.append(f"IMPERVA={hal.get('imperva_challenge','?')}")
    if hal.get("captcha"):
        flags.append(f"CAPTCHA={hal['captcha']}")
    if hal.get("bookitit_scripts"):
        flags.append(f"BKT_SCRIPTS={len(hal['bookitit_scripts'])}")
    if item.get("bkt_callback"):
        d = item["bkt_callback"].get("data", {})
        ag = len(d.get("agendas", [])) if isinstance(d.get("agendas"), list) else d.get("agendas", "?")
        dt = len(d.get("dates",   [])) if isinstance(d.get("dates"),   list) else d.get("dates",   "?")
        flags.append(f"agendas={ag} dates={dt}")
    flag_str = " | ".join(flags)
    return f"[#{item['seq']:03d}] {met:4s} {st} | {sz:6d}b {tp:20s} | {bkt}{flag_str}\n        {url}"


def _guardar(items: list):
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2, default=str)

    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write(f"OVC SPY — Flujo completo {TIMESTAMP}\n")
        f.write(f"Total intercambios: {len(items)}\n")
        f.write("=" * 80 + "\n\n")

        for it in items:
            f.write(f"{'='*80}\n")
            f.write(f"[#{it['seq']:03d}] {it['metodo']} {it['resp_status']} — {it['url']}\n")
            f.write(f"Tiempo captura: {it['ts']}\n\n")

            # REQUEST
            f.write("── REQUEST ──────────────────────────────────────────────────────\n")
            f.write(f"URL:     {it['url']}\n")
            f.write(f"Metodo:  {it['metodo']}\n")
            f.write(f"Headers request:\n")
            for k, v in it.get("req_headers", {}).items():
                f.write(f"  {k}: {v}\n")
            if it.get("req_body"):
                f.write(f"\nBody request:\n  {it['req_body'][:600]}\n")

            # RESPONSE
            f.write(f"\n── RESPONSE ─────────────────────────────────────────────────────\n")
            f.write(f"Status: {it['resp_status']}\n")
            f.write(f"Tipo:   {it.get('resp_tipo','')}\n")
            f.write(f"Tamaño: {it.get('resp_size',0)} bytes\n")
            f.write(f"Headers response:\n")
            for k, v in it.get("resp_headers", {}).items():
                f.write(f"  {k}: {v}\n")
            if it.get("resp_body_preview"):
                f.write(f"\nBody response (primeros 800 chars):\n")
                f.write(f"  {it['resp_body_preview']}\n")
            if it.get("bkt_callback"):
                f.write(f"\n*** BOOKITIT JSONP ***\n")
                f.write(f"  Callback: {it['bkt_callback'].get('callback','?')}\n")
                f.write(f"  Data: {json.dumps(it['bkt_callback'].get('data',{}), ensure_ascii=False)[:800]}\n")
            if it.get("hallazgos"):
                f.write(f"\n*** HALLAZGOS ***\n")
                for k, v in it["hallazgos"].items():
                    f.write(f"  {k}: {v}\n")
            f.write("\n")

        # RESUMEN FINAL
        f.write("\n" + "="*80 + "\n")
        f.write("RESUMEN ANALISIS\n")
        f.write("="*80 + "\n")

        todos_tokens  = []
        todos_pks     = []
        todos_sids    = []
        todas_cookies = {}
        bkt_responses = []
        todos_scripts = []

        for it in items:
            h = it.get("hallazgos", {})
            if h.get("token_csrf"):
                todos_tokens.append(h["token_csrf"])
            if h.get("public_keys"):
                todos_pks.extend(h["public_keys"])
            if h.get("service_ids"):
                todos_sids.extend(h["service_ids"])
            if h.get("bookitit_scripts"):
                todos_scripts.extend(h["bookitit_scripts"])
            # Cookies en headers de response
            for k, v in it.get("resp_headers", {}).items():
                if "set-cookie" in k.lower():
                    nombre = v.split("=")[0] if "=" in v else v
                    todas_cookies[nombre.strip()] = v[:120]
            if it.get("bkt_callback"):
                bkt_responses.append(it["bkt_callback"])

        f.write(f"\nTokens CSRF encontrados: {list(set(todos_tokens))}\n")
        f.write(f"Public Keys (PK) encontrados: {list(set(todos_pks))}\n")
        f.write(f"Service IDs (SID) encontrados: {list(set(todos_sids))}\n")
        f.write(f"Cookies de sesión: {list(todas_cookies.keys())}\n")
        f.write(f"\nDetalle cookies:\n")
        for n, v in todas_cookies.items():
            f.write(f"  {n}: {v[:100]}\n")
        f.write(f"\nScripts Bookitit encontrados:\n")
        for s in list(set(todos_scripts)):
            f.write(f"  {s}\n")
        f.write(f"\nResponsas bkt_init_widget ({len(bkt_responses)}):\n")
        for r in bkt_responses:
            f.write(f"  {json.dumps(r, ensure_ascii=False)[:400]}\n")


# ── Captura con Playwright ────────────────────────────────────────────────────

def espiar_url(url_objetivo: str, visible: bool = False):
    from playwright.sync_api import sync_playwright, Route

    print(f"\n{'='*65}")
    print(f"  OVC SPY — Capturando flujo completo")
    print(f"  URL: {url_objetivo}")
    print(f"  Modo browser: {'VISIBLE' if visible else 'headless'}")
    print(f"  Esperando {ESPERA_POST_CARGA}s post-carga para AJAX async")
    print(f"  Salida: {OUT_TXT.name}")
    print(f"{'='*65}\n")

    seq = [0]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not visible,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="es-ES",
            viewport={"width": 1366, "height": 768},
            # Capturar todos los headers incluyendo los de la respuesta
            record_har_path=str(BASE_DIR / f"ovc_spy_{TIMESTAMP}.har"),
        )

        page = ctx.new_page()

        # ── Interceptar TODAS las requests/responses ──────────────────────────
        responses_pendientes: dict = {}

        def on_request(request):
            responses_pendientes[request.url] = {
                "ts":          datetime.now().isoformat(),
                "metodo":      request.method,
                "url":         request.url,
                "req_headers": dict(request.headers),
                "req_body":    request.post_data or "",
            }

        def on_response(response):
            seq[0] += 1
            url = response.url
            base = responses_pendientes.pop(url, {})

            # Leer body completo
            try:
                body_bytes = response.body()
                body_txt   = body_bytes.decode("utf-8", errors="replace")
            except Exception:
                body_bytes = b""
                body_txt   = ""

            ct = response.headers.get("content-type", "")

            # Clasificar tipo
            if "json" in ct:
                tipo = "JSON"
            elif "javascript" in ct or "bkt_init_widget" in body_txt:
                tipo = "JSONP/JS"
            elif "html" in ct:
                tipo = "HTML"
            elif "css" in ct:
                tipo = "CSS"
            elif "image" in ct:
                tipo = "IMG"
            else:
                tipo = ct.split(";")[0].split("/")[-1][:20] if ct else "?"

            # Saltear assets irrelevantes (CSS, fonts, imágenes)
            if tipo in ("CSS","IMG") or any(x in url for x in [".woff",".ttf",".png",".jpg",".gif",".ico",".svg"]):
                return

            # Análisis
            hallazgos  = {}
            bkt_parsed = None

            if tipo in ("JSONP/JS",) and "bkt_init_widget" in body_txt:
                bkt_parsed = _parsear_jsonp(body_txt)

            if tipo == "HTML" and len(body_txt) > 100:
                hallazgos = _analizar_html(body_txt)

            item = {
                "seq":              seq[0],
                "ts":               base.get("ts", datetime.now().isoformat()),
                "metodo":           base.get("metodo", response.request.method),
                "url":              url,
                "req_headers":      base.get("req_headers", {}),
                "req_body":         base.get("req_body", ""),
                "resp_status":      response.status,
                "resp_headers":     dict(response.headers),
                "resp_tipo":        tipo,
                "resp_size":        len(body_bytes),
                "resp_body_preview": body_txt[:800],
                "bkt_callback":     bkt_parsed,
                "hallazgos":        hallazgos,
            }

            intercambios.append(item)
            print(_resumen_request(item))
            _guardar(intercambios)

        page.on("request",  on_request)
        page.on("response", on_response)

        # ── Paso 1: handshake principal para obtener cookies Imperva ─────────
        print("[PASO 1] Handshake en citaconsular.es para obtener cookies Imperva...")
        try:
            page.goto("https://www.citaconsular.es", timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)
        except Exception as e:
            print(f"  [WARN] Handshake falló: {e}")

        # ── Paso 2: Cargar el widget objetivo ─────────────────────────────────
        print(f"\n[PASO 2] Cargando widget: {url_objetivo}")
        try:
            page.goto(url_objetivo, timeout=40000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"  [WARN] Carga con timeout: {e}")

        # ── Paso 3: Esperar que el JS haga todas sus llamadas AJAX ───────────
        print(f"\n[PASO 3] Esperando {ESPERA_POST_CARGA}s para AJAX async del widget...")
        for i in range(ESPERA_POST_CARGA):
            time.sleep(1)
            print(f"  {i+1}/{ESPERA_POST_CARGA}...", end="\r")
        print()

        # ── Paso 4: Capturar contenido final del DOM ──────────────────────────
        print("\n[PASO 4] Capturando DOM final...")
        try:
            contenido_final = page.content()
            texto_visible   = page.inner_text("body") if page.query_selector("body") else ""

            # Analizar DOM final para detectar resultado del widget
            if "No hay horas disponibles" in contenido_final:
                estado_widget = "SIN CITAS — No hay horas disponibles"
            elif "bkt_init_widget" in contenido_final or "bookitit" in contenido_final.lower():
                estado_widget = "Widget cargado — revisar datos JSONP"
            else:
                estado_widget = "Widget NO cargó o bloqueado"

            print(f"\n  *** ESTADO WIDGET: {estado_widget} ***")

            # Texto visible (lo que ve el usuario)
            print(f"\n  TEXTO VISIBLE EN PAGINA:\n  {texto_visible[:400]}")

        except Exception as e:
            print(f"  [WARN] Error DOM: {e}")

        browser.close()

    print(f"\n{'='*65}")
    print(f"  Captura completada: {len(intercambios)} intercambios")
    print(f"  JSON: {OUT_JSON}")
    print(f"  TXT:  {OUT_TXT}")
    print(f"  HAR:  {BASE_DIR}/ovc_spy_{TIMESTAMP}.har")
    print(f"{'='*65}")

    # ── Resumen final en consola ──────────────────────────────────────────────
    todos_tokens = [it["hallazgos"]["token_csrf"] for it in intercambios if it.get("hallazgos", {}).get("token_csrf")]
    todos_sids   = list(set(sid for it in intercambios for sid in it.get("hallazgos", {}).get("service_ids", [])))
    todos_pks    = list(set(pk  for it in intercambios for pk  in it.get("hallazgos", {}).get("public_keys",  [])))
    bkt_hits     = [it for it in intercambios if it.get("bkt_callback")]

    print(f"\n  TOKENS CSRF encontrados : {todos_tokens[:3]}")
    print(f"  SERVICE IDs (SID)       : {todos_sids}")
    print(f"  PUBLIC KEYS (PK)        : {todos_pks}")
    print(f"  Respuestas BKT JSONP    : {len(bkt_hits)}")
    for b in bkt_hits:
        d = b["bkt_callback"].get("data", {})
        ag = d.get("agendas", [])
        dt = d.get("dates",   [])
        print(f"    → agendas={len(ag) if isinstance(ag,list) else ag}  dates={len(dt) if isinstance(dt,list) else dt}  url={b['url'][:80]}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="OVC Spy — captura flujo completo Bookitit")
    ap.add_argument("url",     nargs="?", default=URL_LEGA, help="URL widget a espiar")
    ap.add_argument("--visible", action="store_true", help="Mostrar browser (no headless)")
    args = ap.parse_args()

    if not args.url:
        print("ERROR: URL no especificada y URL_LEGA no está en .env")
        sys.exit(1)

    espiar_url(args.url, visible=args.visible)
