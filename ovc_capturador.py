#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ovc_capturador.py — Addon mitmproxy para captura TOTAL del flujo Bookitit/citaconsular

USO:
  1. Ejecutar: ovc_captura.bat
  2. En Chrome: Configurar proxy → 127.0.0.1:8080
  3. Navegar a: https://www.citaconsular.es/es/hosteds/widgetdefault/25b6cfa9f112aef4ca19457abc237f7ba/
  4. Esperar que cargue el widget (seleccionar servicio si es posible)
  5. Ctrl+C para detener — revisar ovc_flujo_FECHA.json y ovc_flujo_FECHA.txt

CAPTURA:
  - TODOS los GET/POST hacia bookitit.com, citaconsular.es, imperva, etc.
  - Headers completos (request + response)
  - Cookies en ambas direcciones
  - Cuerpos completos (HTML, JSONP, JSON, formularios)
  - Secuencia cronológica numerada
  - Análisis automático de tokens, PKs, SIDs, cookies de sesión
"""

import json
import re
import os
from datetime import datetime
from pathlib import Path

# ── Dominios a capturar (todo lo demás se ignora) ────────────────────────────
DOMINIOS_TARGET = [
    "citaconsular.es",
    "bookitit.com",
    "imperva",
    "incapsula",
    "cdn.bookitit",
    "app.bookitit",
]

# ── Archivo de salida ─────────────────────────────────────────────────────────
TIMESTAMP   = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_DIR    = Path(__file__).parent / "logs"
BASE_DIR.mkdir(exist_ok=True)
ARCHIVO_JSON = BASE_DIR / f"ovc_flujo_{TIMESTAMP}.json"
ARCHIVO_TXT  = BASE_DIR / f"ovc_flujo_{TIMESTAMP}.txt"

# ── Estado global ─────────────────────────────────────────────────────────────
flujo: list = []         # lista de intercambios request/response
seq: int    = 0          # número de secuencia


def _es_target(host: str) -> bool:
    """Filtra solo dominios relevantes."""
    h = host.lower()
    return any(d in h for d in DOMINIOS_TARGET)


def _headers_dict(headers) -> dict:
    """Convierte headers mitmproxy a dict (permite duplicados → lista)."""
    result = {}
    for k, v in headers.items():
        k_lower = k.lower()
        if k_lower in result:
            if isinstance(result[k_lower], list):
                result[k_lower].append(v)
            else:
                result[k_lower] = [result[k_lower], v]
        else:
            result[k_lower] = v
    return result


def _parsear_body(content: bytes, content_type: str) -> dict:
    """
    Parsea el body según content-type. Devuelve dict con:
      raw_size, encoding, texto_preview (500 chars), parsed (si es JSON/JSONP/form)
    """
    if not content:
        return {"raw_size": 0, "texto_preview": ""}

    ct = (content_type or "").lower()
    resultado = {"raw_size": len(content)}

    try:
        texto = content.decode("utf-8", errors="replace")
    except Exception:
        texto = repr(content[:200])

    resultado["texto_preview"] = texto[:800]  # primeros 800 chars visibles

    # ── Intentar parsear según tipo ──────────────────────────────────────────
    if "json" in ct:
        try:
            resultado["parsed"] = json.loads(texto)
            resultado["tipo"] = "JSON"
        except Exception:
            resultado["tipo"] = "JSON-malformado"

    elif "javascript" in ct or texto.strip().startswith("bkt_init_widget"):
        # JSONP — extraer el JSON dentro del callback
        m = re.match(r'\w+\s*\((.*)\)\s*;?\s*$', texto.strip(), re.DOTALL)
        if m:
            try:
                resultado["parsed"] = json.loads(m.group(1))
                resultado["tipo"] = "JSONP"
                resultado["callback"] = texto.split("(")[0].strip()
            except Exception:
                resultado["tipo"] = "JSONP-malformado"
        else:
            resultado["tipo"] = "JS"

    elif "x-www-form-urlencoded" in ct:
        # Form POST — parsear key=value
        from urllib.parse import parse_qs
        try:
            resultado["parsed"] = parse_qs(texto)
            resultado["tipo"] = "FORM"
        except Exception:
            resultado["tipo"] = "FORM-malformado"

    elif "html" in ct:
        # HTML — extraer campos clave: token, scripts, cookies, captcha
        resultado["tipo"] = "HTML"
        _analizar_html(texto, resultado)

    else:
        resultado["tipo"] = ct or "desconocido"

    return resultado


def _analizar_html(html: str, dest: dict):
    """Extrae tokens, PKs, scripts y datos de Imperva del HTML."""
    hallazgos = {}

    # Token anti-CSRF (citaconsular.es / Imperva)
    token_m = (
        re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']{10,})["\']', html) or
        re.search(r'value=["\']([^"\']{10,})["\'][^>]*name=["\']token["\']', html)
    )
    if token_m:
        hallazgos["token_csrf"] = token_m.group(1)

    # Public Key (PK) de Bookitit
    pk_m = re.findall(r'publickey[=:\s"\']+([a-f0-9]{28,36})', html, re.I)
    if pk_m:
        hallazgos["public_keys"] = list(set(pk_m))

    # Service IDs (SID) — clave para llamadas JSONP
    sid_m = re.findall(r'services\[\][\s=:"\']+(\d+)', html)
    if sid_m:
        hallazgos["service_ids"] = list(set(sid_m))

    # Scripts externos cargados
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I)
    if scripts:
        hallazgos["scripts_externos"] = scripts[:10]  # max 10

    # Imperva/Incapsula markers
    if "incapsula" in html.lower() or "imperva" in html.lower():
        hallazgos["imperva_detectado"] = True
        # Buscar el challenge JS
        ch_m = re.search(r'(IncapsulaRequest|window\.__imp|reese84)', html)
        if ch_m:
            hallazgos["imperva_challenge_type"] = ch_m.group(1)

    # hCaptcha
    if "hcaptcha" in html.lower():
        hallazgos["captcha"] = "hCaptcha"
    elif "recaptcha" in html.lower():
        hallazgos["captcha"] = "reCAPTCHA"

    # PHPSESSID en form oculto
    sess_m = re.search(r'PHPSESSID[^=]*=\s*([a-f0-9]{20,})', html)
    if sess_m:
        hallazgos["phpsessid_en_html"] = sess_m.group(1)

    if hallazgos:
        dest["hallazgos_html"] = hallazgos


def _analizar_cookies(cookies_str: str) -> list:
    """Parsea header Set-Cookie o Cookie en lista de dicts."""
    if not cookies_str:
        return []
    cookies = []
    for parte in cookies_str.split(";"):
        parte = parte.strip()
        if "=" in parte:
            nombre, valor = parte.split("=", 1)
            cookies.append({"nombre": nombre.strip(), "valor": valor.strip()})
    return cookies


def _guardar():
    """Guarda el flujo completo a JSON y TXT."""
    # JSON estructurado (máquina)
    with open(ARCHIVO_JSON, "w", encoding="utf-8") as f:
        json.dump(flujo, f, ensure_ascii=False, indent=2, default=str)

    # TXT legible (humano)
    with open(ARCHIVO_TXT, "w", encoding="utf-8") as f:
        f.write(f"OVC CAPTURADOR — Flujo completo {TIMESTAMP}\n")
        f.write(f"Total intercambios: {len(flujo)}\n")
        f.write("=" * 80 + "\n\n")

        for item in flujo:
            f.write(f"{'=' * 80}\n")
            f.write(f"[#{item['seq']}] {item['metodo']} {item['url']}\n")
            f.write(f"Tiempo: {item['timestamp']}\n")
            f.write(f"Host: {item['host']}\n\n")

            # REQUEST
            f.write("── REQUEST ──────────────────────────────────────────────\n")
            f.write(f"Método: {item['metodo']}\n")
            f.write(f"Path:   {item['path']}\n")
            if item.get("query"):
                f.write(f"Query params:\n")
                for k, v in item["query"].items():
                    f.write(f"  {k} = {v}\n")
            f.write(f"\nHeaders request:\n")
            for k, v in item.get("req_headers", {}).items():
                f.write(f"  {k}: {v}\n")
            if item.get("req_cookies"):
                f.write(f"\nCookies enviadas:\n")
                for c in item["req_cookies"]:
                    f.write(f"  {c['nombre']} = {c['valor'][:80]}\n")
            if item.get("req_body"):
                f.write(f"\nBody request ({item['req_body'].get('tipo','')}, {item['req_body'].get('raw_size',0)} bytes):\n")
                f.write(f"  {item['req_body'].get('texto_preview','')[:400]}\n")
                if item['req_body'].get('parsed'):
                    f.write(f"  PARSED: {json.dumps(item['req_body']['parsed'], ensure_ascii=False)[:400]}\n")

            # RESPONSE
            f.write(f"\n── RESPONSE ─────────────────────────────────────────────\n")
            f.write(f"Status: {item.get('resp_status','?')}\n")
            f.write(f"\nHeaders response:\n")
            for k, v in item.get("resp_headers", {}).items():
                f.write(f"  {k}: {v}\n")
            if item.get("resp_cookies"):
                f.write(f"\nCookies nuevas (Set-Cookie):\n")
                for c in item["resp_cookies"]:
                    f.write(f"  {c['nombre']} = {c['valor'][:80]}\n")
            if item.get("resp_body"):
                rb = item["resp_body"]
                f.write(f"\nBody response ({rb.get('tipo','')}, {rb.get('raw_size',0)} bytes):\n")
                f.write(f"  {rb.get('texto_preview','')[:600]}\n")
                if rb.get('parsed'):
                    f.write(f"  PARSED: {json.dumps(rb['parsed'], ensure_ascii=False)[:600]}\n")
                if rb.get('hallazgos_html'):
                    f.write(f"\n  *** HALLAZGOS HTML ***\n")
                    for k2, v2 in rb['hallazgos_html'].items():
                        f.write(f"    {k2}: {v2}\n")

            f.write(f"\n")


# ── Addon mitmproxy ───────────────────────────────────────────────────────────

class OVCCapturador:
    """Addon mitmproxy que intercepta y registra todo el tráfico hacia Bookitit/citaconsular."""

    def response(self, flow):
        global seq

        host = flow.request.host or ""
        if not _es_target(host):
            return  # ignorar otros dominios

        seq += 1
        ts = datetime.now().isoformat()

        # ── Parsear query string ──────────────────────────────────────────────
        from urllib.parse import parse_qs, urlparse
        parsed_url = urlparse(flow.request.url)
        query_params = {}
        for k, vlist in parse_qs(parsed_url.query).items():
            query_params[k] = vlist[0] if len(vlist) == 1 else vlist

        # ── Request body ──────────────────────────────────────────────────────
        req_ct  = flow.request.headers.get("content-type", "")
        req_body = _parsear_body(flow.request.content or b"", req_ct)

        # ── Cookies de request ────────────────────────────────────────────────
        cookie_hdr = flow.request.headers.get("cookie", "")
        req_cookies = _analizar_cookies(cookie_hdr)

        # ── Response body ─────────────────────────────────────────────────────
        resp_ct   = flow.response.headers.get("content-type", "") if flow.response else ""
        resp_body = _parsear_body(flow.response.content or b"", resp_ct) if flow.response else {}

        # ── Set-Cookie ────────────────────────────────────────────────────────
        resp_cookies = []
        if flow.response:
            sc = flow.response.headers.get("set-cookie", "")
            if sc:
                resp_cookies = _analizar_cookies(sc)

        # ── Armar registro ────────────────────────────────────────────────────
        registro = {
            "seq":          seq,
            "timestamp":    ts,
            "metodo":       flow.request.method,
            "url":          flow.request.url,
            "host":         host,
            "path":         parsed_url.path,
            "query":        query_params,
            "req_headers":  _headers_dict(flow.request.headers),
            "req_cookies":  req_cookies,
            "req_body":     req_body if req_body.get("raw_size", 0) > 0 else None,
            "resp_status":  flow.response.status_code if flow.response else None,
            "resp_headers": _headers_dict(flow.response.headers) if flow.response else {},
            "resp_cookies": resp_cookies,
            "resp_body":    resp_body if resp_body.get("raw_size", 0) > 0 else None,
        }

        flujo.append(registro)

        # ── Print en consola ──────────────────────────────────────────────────
        status  = flow.response.status_code if flow.response else "?"
        rb_size = resp_body.get("raw_size", 0)
        rb_tipo = resp_body.get("tipo", "")
        parsed  = resp_body.get("parsed")
        bkt_ok  = "bkt_init_widget" in (flow.response.text if flow.response else "")

        hallazgos_str = ""
        if resp_body.get("hallazgos_html"):
            h = resp_body["hallazgos_html"]
            partes = []
            if h.get("token_csrf"):
                partes.append(f"TOKEN={h['token_csrf'][:16]}...")
            if h.get("public_keys"):
                partes.append(f"PK={h['public_keys']}")
            if h.get("service_ids"):
                partes.append(f"SID={h['service_ids']}")
            if h.get("imperva_detectado"):
                partes.append(f"IMPERVA={h.get('imperva_challenge_type','SI')}")
            if partes:
                hallazgos_str = " | " + " | ".join(partes)

        parsed_str = ""
        if parsed and isinstance(parsed, dict):
            agendas = parsed.get("agendas", "?")
            dates   = parsed.get("dates", "?")
            parsed_str = f" → agendas={len(agendas) if isinstance(agendas,list) else agendas} dates={len(dates) if isinstance(dates,list) else dates}"

        print(
            f"[#{seq:03d}] {flow.request.method:4s} {status} | {rb_size:6d}b {rb_tipo:15s}"
            f" | {'BKT✓' if bkt_ok else '    '}"
            f"{hallazgos_str}{parsed_str}"
            f"\n       {flow.request.url[:120]}"
        )

        # Guardar después de cada intercambio (por si se interrumpe)
        _guardar()


# ── Entry point para mitmproxy ────────────────────────────────────────────────
addons = [OVCCapturador()]
