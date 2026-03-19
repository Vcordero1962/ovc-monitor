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
  python -X utf8 ovc_spy.py [URL] --continuo [--intervalo 300] [--alerta]

  URL        = URL del widget a espiar (default: URL_LEGA del .env)
  --visible  = muestra el browser (útil para ver qué pasa en pantalla)
  --continuo = loop infinito — monitorea indefinidamente
  --intervalo= segundos entre checks en modo continuo (default: 300)
  --alerta   = envía alerta a Telegram cuando AllowAppointment=True

SALIDA (por run):
  logs/ovc_spy_TIMESTAMP.json   — todos los intercambios en JSON
  logs/ovc_spy_TIMESTAMP.txt    — reporte legible con análisis
  Consola: resumen en tiempo real con hallazgos clave
"""

import sys
import json
import re
import os
import time
import random
import argparse
import requests as http_requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Configuración ─────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent / "logs"
BASE_DIR.mkdir(exist_ok=True)

URL_LEGA    = os.getenv("URL_LEGA",    "https://www.citaconsular.es/es/hosteds/widgetdefault/25b6cfa9f112aef4ca19457abc237f7ba/")
URL_LMD     = os.getenv("URL_LMD",     "")
URL_PAS     = os.getenv("URL_PASAPORTE","")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID      = os.getenv("ADMIN_CHAT_ID", "")

# Esperar N segundos tras carga para que el JS haga todas sus llamadas
ESPERA_POST_CARGA = 10   # segundos — modo normal
ESPERA_CONTINUO   = 8    # segundos — modo continuo (más rápido)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _parsear_jsonp(texto: str) -> dict | None:
    # Formato: CallbackName({...}) o callback=CallbackName({...})
    i0 = texto.find("{")
    i1 = texto.rfind("}")
    if i0 != -1 and i1 > i0:
        try:
            data = json.loads(texto[i0: i1 + 1])
            # Extraer nombre del callback
            cb_m = re.match(r'[^(]*?(\w[\w.]*)\s*\(', texto[:i0])
            return {"callback": cb_m.group(1) if cb_m else "?", "data": data}
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
    # AllowAppointment flag
    if item.get("allow_appointment") is not None:
        ap = item["allow_appointment"]
        flags.append(f"AllowAppointment={'🚨TRUE' if ap else 'False'}")
    flag_str = " | ".join(flags)
    return f"[#{item['seq']:03d}] {met:4s} {st} | {sz:6d}b {tp:20s} | {bkt}{flag_str}\n        {url}"


def _guardar(items: list, out_json: Path, out_txt: Path):
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2, default=str)

    timestamp_str = out_json.stem.replace("ovc_spy_", "")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(f"OVC SPY — Flujo completo {timestamp_str}\n")
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
            f.write("Headers request:\n")
            for k, v in it.get("req_headers", {}).items():
                f.write(f"  {k}: {v}\n")
            if it.get("req_body"):
                f.write(f"\nBody request:\n  {it['req_body'][:600]}\n")

            # RESPONSE
            f.write("\n── RESPONSE ─────────────────────────────────────────────────────\n")
            f.write(f"Status: {it['resp_status']}\n")
            f.write(f"Tipo:   {it.get('resp_tipo','')}\n")
            f.write(f"Tamaño: {it.get('resp_size',0)} bytes\n")
            f.write("Headers response:\n")
            for k, v in it.get("resp_headers", {}).items():
                f.write(f"  {k}: {v}\n")
            if it.get("allow_appointment") is not None:
                f.write(f"\n  ⭐ AllowAppointment = {it['allow_appointment']}\n")
            if it.get("resp_body_preview"):
                f.write("\nBody response (primeros 800 chars):\n")
                f.write(f"  {it['resp_body_preview']}\n")
            if it.get("bkt_callback"):
                f.write("\n*** BOOKITIT JSONP ***\n")
                f.write(f"  Callback: {it['bkt_callback'].get('callback','?')}\n")
                f.write(f"  Data: {json.dumps(it['bkt_callback'].get('data',{}), ensure_ascii=False)[:800]}\n")
            if it.get("hallazgos"):
                f.write("\n*** HALLAZGOS ***\n")
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
        allow_vals    = []

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
            for k, v in it.get("resp_headers", {}).items():
                if "set-cookie" in k.lower():
                    nombre = v.split("=")[0] if "=" in v else v
                    todas_cookies[nombre.strip()] = v[:120]
            if it.get("bkt_callback"):
                bkt_responses.append(it["bkt_callback"])
            if it.get("allow_appointment") is not None:
                allow_vals.append(it["allow_appointment"])

        allow_final = allow_vals[-1] if allow_vals else None
        f.write(f"\n⭐ AllowAppointment (getservices): {allow_final}\n")
        f.write(f"\nTOKENS CSRF encontrados : {list(set(todos_tokens))}\n")
        f.write(f"SERVICE IDs (SID)       : {list(set(todos_sids))}\n")
        f.write(f"PUBLIC KEYS (PK)        : {list(set(todos_pks))}\n")
        f.write(f"Cookies de sesión       : {list(todas_cookies.keys())}\n")
        f.write("\nDetalle cookies:\n")
        for n, v in todas_cookies.items():
            f.write(f"  {n}: {v[:100]}\n")
        f.write("\nScripts Bookitit encontrados:\n")
        for s in list(set(todos_scripts)):
            f.write(f"  {s}\n")
        f.write(f"\nRespuestas BKT JSONP ({len(bkt_responses)}):\n")
        for r in bkt_responses:
            f.write(f"  {json.dumps(r, ensure_ascii=False)[:400]}\n")


def _send_telegram_alerta(url_widget: str, ts: str):
    """Envía alerta Telegram cuando AllowAppointment=True."""
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        print("  [ALERTA] TELEGRAM_BOT_TOKEN o ADMIN_CHAT_ID no configurados — alerta omitida")
        return
    try:
        msg = (
            f"🚨 <b>OVC SPY — CITA DETECTADA</b>\n\n"
            f"⭐ <b>AllowAppointment = TRUE</b>\n"
            f"⏰ {ts}\n\n"
            f"🔗 <a href='{url_widget}'>Abrir widget ahora</a>\n\n"
            f"<i>Detectado por ovc_spy modo continuo</i>"
        )
        r = http_requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.ok:
            print(f"  [ALERTA] ✅ Telegram enviado")
        else:
            print(f"  [ALERTA] ❌ Telegram error: {r.status_code} {r.text[:100]}")
    except Exception as e:
        print(f"  [ALERTA] ❌ Telegram excepción: {e}")


# ── Captura con Playwright ────────────────────────────────────────────────────

def espiar_url(url_objetivo: str, visible: bool = False, modo_rapido: bool = False) -> dict:
    """
    Navega al widget y captura todo el tráfico HTTP.
    Retorna dict con:
      allow_appointment: bool|None  (de getservices)
      intercambios_total: int
      estado_widget: str
      tokens_csrf: list
      sids: list
      ts: str
    """
    from playwright.sync_api import sync_playwright

    ts_run    = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json  = BASE_DIR / f"ovc_spy_{ts_run}.json"
    out_txt   = BASE_DIR / f"ovc_spy_{ts_run}.txt"
    espera    = ESPERA_CONTINUO if modo_rapido else ESPERA_POST_CARGA

    intercambios: list = []
    seq = [0]

    print(f"\n{'='*65}")
    print(f"  OVC SPY — Capturando flujo completo")
    print(f"  URL: {url_objetivo}")
    print(f"  Modo browser: {'VISIBLE' if visible else 'headless'} | espera: {espera}s")
    print(f"  Salida: {out_txt.name}")
    print(f"{'='*65}\n")

    # Resultado a retornar
    resultado = {
        "allow_appointment":  None,
        "intercambios_total": 0,
        "estado_widget":      "desconocido",
        "tokens_csrf":        [],
        "sids":               [],
        "ts":                 ts_run,
        "out_json":           str(out_json),
        "out_txt":            str(out_txt),
    }

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
            record_har_path=str(BASE_DIR / f"ovc_spy_{ts_run}.har"),
            extra_http_headers={
                # Sobrescribir sec-ch-ua para eliminar firma "HeadlessChrome"
                # que citaconsular.es detecta y devuelve página vacía cacheada (48h)
                "sec-ch-ua": '"Chromium";v="122", "Google Chrome";v="122", "Not(A:Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )

        page = ctx.new_page()
        responses_pendientes: dict = {}
        getservices_allows:   list = []  # AllowAppointment capturado de getservices

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

            try:
                body_bytes = response.body()
                body_txt   = body_bytes.decode("utf-8", errors="replace")
            except Exception:
                body_bytes = b""
                body_txt   = ""

            ct = response.headers.get("content-type", "")

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

            if tipo in ("CSS","IMG") or any(x in url for x in [".woff",".ttf",".png",".jpg",".gif",".ico",".svg"]):
                return

            hallazgos  = {}
            bkt_parsed = None
            allow_apt  = None  # AllowAppointment para este item

            # ── Detectar AllowAppointment de getservices ─────────────────────
            if "onlinebookings/getservices/" in url and body_txt:
                try:
                    i0 = body_txt.find("{")
                    i1 = body_txt.rfind("}")
                    if i0 != -1 and i1 > i0:
                        gs_data  = json.loads(body_txt[i0: i1 + 1])
                        allow_apt = gs_data.get("AllowAppointment")
                        svc_list  = gs_data.get("Services", [])
                        sid_val   = svc_list[0]["id"] if svc_list else ""
                        getservices_allows.append(allow_apt)
                        flag_icon = "🚨 TRUE" if allow_apt is True else ("✅ False" if allow_apt is False else f"? {allow_apt!r}")
                        print(f"\n  ⭐ GETSERVICES AllowAppointment={flag_icon} | SID={sid_val} | services={len(svc_list)}\n")
                except Exception:
                    pass

            if tipo in ("JSONP/JS",) and "bkt_init_widget" in body_txt:
                bkt_parsed = _parsear_jsonp(body_txt)

            if tipo == "HTML" and len(body_txt) > 100:
                hallazgos = _analizar_html(body_txt)

            item = {
                "seq":               seq[0],
                "ts":                base.get("ts", datetime.now().isoformat()),
                "metodo":            base.get("metodo", response.request.method),
                "url":               url,
                "req_headers":       base.get("req_headers", {}),
                "req_body":          base.get("req_body", ""),
                "resp_status":       response.status,
                "resp_headers":      dict(response.headers),
                "resp_tipo":         tipo,
                "resp_size":         len(body_bytes),
                "resp_body_preview": body_txt[:800],
                "bkt_callback":      bkt_parsed,
                "hallazgos":         hallazgos,
                "allow_appointment": allow_apt,
            }

            intercambios.append(item)
            print(_resumen_request(item))
            _guardar(intercambios, out_json, out_txt)

        page.on("request",  on_request)
        page.on("response", on_response)

        # ── Paso 1: handshake ─────────────────────────────────────────────────
        print("[PASO 1] Handshake citaconsular.es...")
        try:
            page.goto("https://www.citaconsular.es", timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
        except Exception as e:
            print(f"  [WARN] Handshake: {e}")

        # ── Paso 2: widget ─────────────────────────────────────────────────────
        print(f"\n[PASO 2] Cargando widget...")
        try:
            page.goto(url_objetivo, timeout=40000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"  [WARN] Widget: {e}")

        # ── Paso 2b: resolver challenge Imperva "Continuar" ────────────────────
        # Imperva muestra una pantalla intermedia: "Para solicitar cita pulse
        # en el botón continuar / Continue / Continuar"
        # Hay que detectarla y hacer clic para que establezca la cookie de sesión
        # y redirija al widget real.
        _IMPERVA_MARKERS = [
            "continuar", "continue / continuar",
            "pulse en el botón continuar",
            "click on the continue button",
        ]
        try:
            texto_inicial = page.inner_text("body").lower() if page.query_selector("body") else ""
            es_challenge   = any(m in texto_inicial for m in _IMPERVA_MARKERS)

            if es_challenge:
                print("\n  [IMPERVA] Challenge detectado — buscando botón Continuar...")
                # Selectores posibles del botón Imperva
                _BTN_SELECTORS = [
                    "button:has-text('Continuar')",
                    "button:has-text('Continue')",
                    "a:has-text('Continuar')",
                    "a:has-text('Continue')",
                    "input[type='submit']",
                    "input[type='button']",
                    "[id*='continue']",
                    "[class*='continue']",
                    "[name*='continue']",
                ]
                clicked = False
                for sel in _BTN_SELECTORS:
                    try:
                        btn = page.query_selector(sel)
                        if btn:
                            print(f"  [IMPERVA] Clic en: {sel}")
                            btn.click()
                            clicked = True
                            time.sleep(3)  # esperar redirección post-challenge
                            break
                    except Exception:
                        pass

                if not clicked:
                    # Último recurso: Enter o JS click en el primer botón
                    try:
                        page.keyboard.press("Enter")
                        time.sleep(2)
                        print("  [IMPERVA] Enter enviado (fallback)")
                    except Exception:
                        pass

                # Re-navegar al widget si la URL cambió a la página de challenge
                url_actual = page.url
                if url_actual != url_objetivo and "citaconsular.es/es/hosteds" not in url_actual:
                    print(f"  [IMPERVA] Re-navegando al widget tras challenge...")
                    try:
                        page.goto(url_objetivo, timeout=40000, wait_until="domcontentloaded")
                    except Exception as e2:
                        print(f"  [WARN] Re-nav: {e2}")
            else:
                print("  [IMPERVA] No se detectó challenge — widget directo")
        except Exception as e:
            print(f"  [WARN] Check challenge: {e}")

        # ── Paso 3: esperar AJAX ───────────────────────────────────────────────
        print(f"\n[PASO 3] Esperando {espera}s para AJAX...")
        for i in range(espera):
            time.sleep(1)
            print(f"  {i+1}/{espera}...", end="\r")
        print()

        # ── Paso 4: DOM final ──────────────────────────────────────────────────
        print("\n[PASO 4] Capturando DOM final...")
        estado_widget = "desconocido"
        try:
            contenido_final = page.content()
            texto_visible   = page.inner_text("body") if page.query_selector("body") else ""

            if "No hay horas disponibles" in contenido_final:
                estado_widget = "SIN CITAS — No hay horas disponibles"
            elif "bkt_init_widget" in contenido_final or "bookitit" in contenido_final.lower():
                estado_widget = "Widget cargado — revisar datos JSONP"
            else:
                estado_widget = "Widget NO cargó o bloqueado"

            print(f"\n  *** ESTADO WIDGET: {estado_widget} ***")
            print(f"\n  TEXTO VISIBLE EN PAGINA:\n  {texto_visible[:400]}")
        except Exception as e:
            print(f"  [WARN] DOM: {e}")

        browser.close()

    # ── Resumen final ─────────────────────────────────────────────────────────
    todos_tokens = [it["hallazgos"]["token_csrf"] for it in intercambios if it.get("hallazgos", {}).get("token_csrf")]
    todos_sids   = list(set(sid for it in intercambios for sid in it.get("hallazgos", {}).get("service_ids", [])))
    todos_pks    = list(set(pk  for it in intercambios for pk  in it.get("hallazgos", {}).get("public_keys",  [])))
    bkt_hits     = [it for it in intercambios if it.get("bkt_callback")]
    allow_final  = getservices_allows[-1] if getservices_allows else None

    print(f"\n{'='*65}")
    print(f"  Captura completada: {len(intercambios)} intercambios")
    print(f"  ⭐ AllowAppointment : {allow_final}")
    print(f"  TOKENS CSRF         : {todos_tokens[:3]}")
    print(f"  SERVICE IDs (SID)   : {todos_sids}")
    print(f"  PUBLIC KEYS (PK)    : {todos_pks}")
    print(f"  Respuestas BKT JSONP: {len(bkt_hits)}")
    print(f"  JSON: {out_json}")
    print(f"  TXT:  {out_txt}")
    print(f"{'='*65}")

    for b in bkt_hits:
        d  = b["bkt_callback"].get("data", {})
        ag = d.get("agendas", [])
        dt = d.get("dates",   [])
        print(f"    → agendas={len(ag) if isinstance(ag,list) else ag}  dates={len(dt) if isinstance(dt,list) else dt}  url={b['url'][:80]}")

    # Actualizar resultado
    resultado.update({
        "allow_appointment":  allow_final,
        "intercambios_total": len(intercambios),
        "estado_widget":      estado_widget,
        "tokens_csrf":        list(set(todos_tokens)),
        "sids":               todos_sids,
    })
    return resultado


# ── Modo continuo ─────────────────────────────────────────────────────────────

def monitorear_continuo(url: str, intervalo_s: int, alerta: bool, visible: bool):
    """
    Loop infinito — llama espiar_url() cada intervalo_s segundos.
    Detecta cambios en AllowAppointment y envía alerta Telegram si --alerta.
    """
    ultimo_estado = None
    ciclo = 0
    log_continuo = BASE_DIR / f"ovc_spy_continuo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    print(f"\n{'█'*65}")
    print(f"  OVC SPY — MODO CONTINUO")
    print(f"  Intervalo: {intervalo_s}s ± jitter | URL: {url}")
    print(f"  Alertas Telegram: {'SÍ' if alerta else 'NO'}")
    print(f"  Log continuo: {log_continuo.name}")
    print(f"  Ctrl+C para detener")
    print(f"{'█'*65}\n")

    def _log(msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linea = f"[{ts}] {msg}"
        print(linea)
        with open(log_continuo, "a", encoding="utf-8") as f:
            f.write(linea + "\n")

    try:
        while True:
            ciclo += 1
            ts_ciclo = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n{'─'*65}")
            print(f"  CICLO #{ciclo} — {ts_ciclo}")
            print(f"{'─'*65}")

            try:
                resultado = espiar_url(url, visible=visible, modo_rapido=True)
                allow     = resultado.get("allow_appointment")
                cambio    = (allow != ultimo_estado) and (ultimo_estado is not None)

                if allow is True:
                    _log(f"🚨 CICLO #{ciclo} — AllowAppointment=TRUE *** CITA DISPONIBLE ***")
                    if alerta:
                        _send_telegram_alerta(url, ts_ciclo)
                elif allow is False:
                    _log(f"✅ CICLO #{ciclo} — AllowAppointment=False — sin citas")
                else:
                    _log(f"⚠️  CICLO #{ciclo} — AllowAppointment={allow!r} (no interceptado)")

                if cambio:
                    _log(f"*** CAMBIO DE ESTADO: {ultimo_estado} → {allow} ***")
                    if allow is True and alerta:
                        _send_telegram_alerta(url, ts_ciclo)

                ultimo_estado = allow

            except Exception as run_e:
                _log(f"❌ CICLO #{ciclo} ERROR: {run_e}")

            # Sleep con jitter gaussiano anti-detección
            jitter    = int(random.gauss(0, intervalo_s * 0.1))
            sleep_t   = max(60, intervalo_s + jitter)
            ts_proximo = datetime.now().strftime("%H:%M:%S")
            print(f"\n  ⏳ Próximo check en {sleep_t}s (aprox. {ts_proximo})...")
            time.sleep(sleep_t)

    except KeyboardInterrupt:
        print(f"\n\n[CONTINUO] Detenido. Ciclos completados: {ciclo}")
        print(f"  Log guardado en: {log_continuo}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="OVC Spy — captura flujo completo Bookitit")
    ap.add_argument("url",         nargs="?", default=URL_LEGA, help="URL widget a espiar")
    ap.add_argument("--visible",   action="store_true",         help="Mostrar browser")
    ap.add_argument("--continuo",  action="store_true",         help="Loop infinito")
    ap.add_argument("--intervalo", type=int, default=300,       help="Segundos entre checks (modo continuo)")
    ap.add_argument("--alerta",    action="store_true",         help="Enviar Telegram cuando AllowAppointment=True")
    args = ap.parse_args()

    if not args.url:
        print("ERROR: URL no especificada y URL_LEGA no está en .env")
        sys.exit(1)

    if args.continuo:
        monitorear_continuo(args.url, args.intervalo, args.alerta, args.visible)
    else:
        espiar_url(args.url, visible=args.visible, modo_rapido=False)
