#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ovc_inspector.py — Inspector de Cuellos de Botella OVC
=======================================================

Herramienta de diagnóstico integral que prueba TODAS las capas de detección
y reporta exactamente dónde falla cada servicio.

Capas analizadas:
  1. Conectividad básica (IP pública, latencia)
  2. GET citaconsular.es → analiza headers Imperva, token, tamaño
  3. POST citaconsular.es (bypass token) → analiza bkt_init_widget completo
  4. GET app.bookitit.com/onlinebookings/main/ → endpoint directo SIN Imperva
  5. AVC canal Telegram (t.me/s/AsesorVirtualC) → mensajes últimas 48h
  6. Canales alternativos (t.me/s/LMDCuba, t.me/s/cubatramite)

Para cada servicio configurado (LEGA, LMD, NACIMIENTO, etc.) extrae
PK y SID de la URL y prueba el endpoint directo de Bookitit.

Uso:
  python ovc_inspector.py                    # todos los servicios
  python ovc_inspector.py LMD NACIMIENTO     # solo esos tramites
  python ovc_inspector.py --no-avc           # omite AVC (más rápido)

Variables de entorno requeridas: las mismas que ovc_once.py (.env o secrets)
"""

import os
import re
import sys
import time
import random
import argparse
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Importar módulos del proyecto ──────────────────────────────────────────────
from core.config import (
    SERVICIOS, USER_AGENTS, get_tramites_activos, get_url_for_tramite,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_CHAT_ID,
)
from core.logger import info, warn, error

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

TIMEOUT = 20
BOOKITIT_JSONP_BASE = "https://app.bookitit.com/onlinebookings/main/"
BOOKITIT_WIDGET_BASE = "https://app.bookitit.com/es/hosteds/widgetdefault/"
CITACONSULAR_JSONP_BASE = "https://www.citaconsular.es/onlinebookings/main/"

# Parámetros JSONP descubiertos por ingeniería inversa del widget
JSONP_PARAMS_TEMPLATE = (
    "?callback=bkt_init_widget"
    "&type=default"
    "&publickey={pk}"
    "&lang=es"
    "&version=5"
    "&src=https%3A%2F%2Fwww.citaconsular.es%2F"
    "&_={ts}"
)
# Con SID (services[])
JSONP_PARAMS_WITH_SID = (
    "?callback=bkt_init_widget"
    "&type=default"
    "&publickey={pk}"
    "&lang=es"
    "&services[]={sid}"
    "&version=5"
    "&src=https%3A%2F%2Fwww.citaconsular.es%2F"
    "&_={ts}"
)


def ua() -> str:
    return random.choice(USER_AGENTS)


def headers_browser(referer: str = "") -> dict:
    h = {
        "User-Agent":        ua(),
        "Accept":            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":   "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding":   "gzip, deflate, br",
        "Connection":        "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":    "document",
        "Sec-Fetch-Mode":    "navigate",
        "Sec-Fetch-Site":    "none",
        "Cache-Control":     "max-age=0",
    }
    if referer:
        h["Referer"] = referer
        h["Sec-Fetch-Site"] = "same-origin"
    return h


def headers_jsonp(referer: str) -> dict:
    """Headers para llamada JSONP (XHR desde el widget)."""
    return {
        "User-Agent":      ua(),
        "Accept":          "*/*",
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         referer,
        "Origin":          "https://www.citaconsular.es",
        "Sec-Fetch-Dest":  "script",
        "Sec-Fetch-Mode":  "no-cors",
        "Sec-Fetch-Site":  "same-origin",
        "Connection":      "keep-alive",
    }


def get_public_ip() -> str:
    try:
        r = requests.get("https://api.ipify.org", timeout=8)
        return r.text.strip()
    except Exception as e:
        return f"ERROR: {e}"


def extract_pk_sid(widget_url: str) -> tuple:
    """Extrae (PK, SID) de URL tipo /es/hosteds/widgetdefault/{PK}/{SID}"""
    m = re.search(r'/widgetdefault/([a-zA-Z0-9]{10,64})(?:/([a-zA-Z0-9]+))?', widget_url)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def parse_bkt_widget(text: str) -> dict:
    """Extrae todos los campos relevantes de bkt_init_widget."""
    # Fechas en cualquier lugar del bloque
    all_dates = re.findall(r'\d{4}-\d{2}-\d{2}', text)

    # Horas HH:MM
    m_hours = re.search(r"(?:['\"]hours['\"]|hours)\s*:\s*\[([^\]]*)\]", text, re.DOTALL)
    hours_raw = m_hours.group(1) if m_hours else ""
    hours = re.findall(r'\d{1,2}:\d{2}', hours_raw)

    # Agendas
    m_ag = re.search(r"(?:['\"]agendas['\"]|agendas)\s*:\s*\[", text, re.DOTALL)
    agendas_block = text[m_ag.end(): m_ag.end() + 6000] if m_ag else ""
    n_agendas = len(re.findall(r'\{', agendas_block))

    # IDs y nombres
    id_centro = re.search(r"['\"]?id_centro['\"]?\s*:\s*['\"]?(\w+)['\"]?", text)
    id_servicio = re.search(r"['\"]?id_servicio['\"]?\s*:\s*['\"]?(\w+)['\"]?", text)
    nombre_svc = re.search(r"['\"]?nombre['\"]?\s*:\s*'([^']+)'", text)

    return {
        "dates":        all_dates[:10],
        "dates_count":  len(all_dates),
        "hours":        hours[:10],
        "hours_count":  len(hours),
        "agendas_count": n_agendas,
        "id_centro":    id_centro.group(1) if id_centro else "?",
        "id_servicio":  id_servicio.group(1) if id_servicio else "?",
        "nombre_svc":   nombre_svc.group(1)[:60] if nombre_svc else "?",
    }


def imperva_headers_info(resp: requests.Response) -> dict:
    """Extrae headers clave de Imperva del response."""
    h = resp.headers
    return {
        "x-iinfo":        h.get("x-iinfo", ""),
        "x-cdn":          h.get("x-cdn", ""),
        "x-check-cacheable": h.get("x-check-cacheable", ""),
        "set-cookie-imperva": any("visid_incap" in c or "incap_ses" in c
                                  for c in h.get("set-cookie", "").split(",")),
        "content-type":   h.get("content-type", ""),
        "server":         h.get("server", ""),
    }


def detect_imperva_gate(html: str) -> bool:
    """Detecta si el response es una página gate de Imperva."""
    signals = [
        "visid_incap", "incapsula", "incap_ses",
        "/_Incapsula_Resource", "/_Incapsula_Resource",
        "name=\"token\"",  # token input del gate
    ]
    html_low = html.lower()
    return any(s.lower() in html_low for s in signals)


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 1: IP & Conectividad
# ─────────────────────────────────────────────────────────────────────────────

def etapa_ip() -> dict:
    info("─" * 60)
    info("ETAPA 1: Conectividad e IP pública")
    ip = get_public_ip()
    info(f"  IP pública: {ip}")

    # Rango conocido de GitHub Actions (Azure)
    is_azure = ip.startswith(("4.", "13.", "20.", "40.", "52.", "65.", "104.", "168."))
    is_known_datacenter = is_azure
    info(f"  Tipo IP: {'⚠️  DATACENTER (Azure/GitHub Actions)' if is_known_datacenter else '✅ posiblemente residencial'}")

    # Latencia a Bookitit
    t0 = time.time()
    try:
        requests.get("https://app.bookitit.com", timeout=8, allow_redirects=False)
        lat_bkt = (time.time() - t0) * 1000
        info(f"  Latencia app.bookitit.com: {lat_bkt:.0f} ms")
    except Exception as e:
        lat_bkt = -1
        info(f"  Latencia app.bookitit.com: ERROR — {e}")

    return {"ip": ip, "datacenter": is_known_datacenter, "latencia_bookitit_ms": lat_bkt}


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 2+3: GET/POST citaconsular.es (flujo actual)
# ─────────────────────────────────────────────────────────────────────────────

def etapa_get_post(tramite: str, url: str) -> dict:
    info(f"\n{'─' * 60}")
    info(f"ETAPA 2+3 [{tramite}]: GET/POST citaconsular.es")
    info(f"  URL: {url[:80]}")

    sess = requests.Session()
    result = {"tramite": tramite, "get_ok": False, "post_ok": False,
              "token_found": False, "bkt_found": False,
              "disponible": False, "data": {}, "diagnostico": []}

    # ── GET ────────────────────────────────────────────────────────────────────
    try:
        t0 = time.time()
        r_get = sess.get(url, headers=headers_browser(), timeout=TIMEOUT, allow_redirects=True)
        lat = (time.time() - t0) * 1000
        html_get = r_get.text

        result["get_ok"] = r_get.ok
        result["get_status"] = r_get.status_code
        result["get_chars"] = len(html_get)
        result["get_lat_ms"] = lat
        result["imperva_headers"] = imperva_headers_info(r_get)
        result["is_gate"] = detect_imperva_gate(html_get)

        info(f"  GET → HTTP {r_get.status_code} | {len(html_get)} chars | {lat:.0f} ms")
        info(f"  Imperva gate: {'SÍ ⚠️' if result['is_gate'] else 'no'}")
        info(f"  x-iinfo: {result['imperva_headers']['x-iinfo'][:60] or 'ausente'}")
        info(f"  server: {result['imperva_headers']['server'] or 'ausente'}")
        info(f"  Set-Cookie Imperva: {result['imperva_headers']['set-cookie-imperva']}")

        # Preview GET (primeros 500 chars)
        info(f"  GET preview: {html_get[:500].replace(chr(10), ' ')[:200]}")

    except Exception as e:
        error(f"  GET error: {e}")
        result["diagnostico"].append(f"GET falló: {e}")
        return result

    # ── Extraer token ──────────────────────────────────────────────────────────
    m = re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']', html_get)
    if not m:
        m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html_get)

    if m:
        token = m.group(1)
        result["token_found"] = True
        result["token_len"] = len(token)
        info(f"  Token: encontrado ✅ ({len(token)} chars) {token[:20]}...")
    else:
        info("  Token: NO encontrado ❌")
        result["diagnostico"].append("Token Imperva no encontrado en GET response")
        # Buscar qué hay en el body (¿captcha visual?)
        captcha_signals = ["captcha", "robot", "verify", "human", "challenge"]
        for sig in captcha_signals:
            if sig in html_get.lower():
                result["diagnostico"].append(f"Señal captcha visual: '{sig}' en body")
        return result

    # ── POST ───────────────────────────────────────────────────────────────────
    time.sleep(random.uniform(0.8, 2.0))
    try:
        post_hdrs = headers_browser(referer=url)
        post_hdrs["Content-Type"] = "application/x-www-form-urlencoded"

        t0 = time.time()
        r_post = sess.post(url, data={"token": token},
                           headers=post_hdrs, timeout=TIMEOUT, allow_redirects=True)
        lat = (time.time() - t0) * 1000
        post_text = r_post.text

        result["post_ok"] = r_post.ok
        result["post_status"] = r_post.status_code
        result["post_chars"] = len(post_text)
        result["post_lat_ms"] = lat
        result["post_is_gate"] = detect_imperva_gate(post_text)

        info(f"  POST → HTTP {r_post.status_code} | {len(post_text)} chars | {lat:.0f} ms")
        info(f"  POST Imperva gate: {'SÍ ⚠️ — POST no bypass Imperva' if result['post_is_gate'] else 'no (bypass ok)'}")

        # ── Preview completo del POST response ──────────────────────────────────
        info(f"\n  ── POST response (primeros 1500 chars) ──")
        info(f"  {post_text[:1500].replace(chr(10), ' | ')}")

        # ── Buscar bkt_init_widget ─────────────────────────────────────────────
        bkt_pos = post_text.find("bkt_init_widget")
        if bkt_pos >= 0:
            result["bkt_found"] = True
            bkt_block = post_text[bkt_pos: bkt_pos + 8000]
            data = parse_bkt_widget(bkt_block)
            result["data"] = data

            info(f"\n  bkt_init_widget: ENCONTRADO ✅ en posición {bkt_pos}")
            info(f"  ── Bloque (primeros 800 chars) ──")
            info(f"  {bkt_block[:800].replace(chr(10), ' | ')}")
            info(f"  id_centro   : {data['id_centro']}")
            info(f"  id_servicio : {data['id_servicio']}")
            info(f"  nombre      : {data['nombre_svc']}")
            info(f"  agendas     : {data['agendas_count']}")
            info(f"  dates       : {data['dates_count']} → {data['dates']}")
            info(f"  hours       : {data['hours_count']} → {data['hours']}")

            if data["dates_count"] > 0 or data["hours_count"] > 0:
                result["disponible"] = True
                info("  *** CITA DISPONIBLE *** 🟢")
            elif data["agendas_count"] > 0:
                info("  Agendas presentes pero vacías (sin citas) 🟡")
                result["diagnostico"].append(
                    "bkt_init_widget tiene agendas pero sin dates/hours. "
                    "La data de disponibilidad puede cargarse via AJAX posterior (bloqueada por Imperva)."
                )
            else:
                info("  bkt_init_widget completamente vacío 🔴")
                result["diagnostico"].append(
                    "bkt_init_widget({}) vacío. Imperva dejó pasar la petición pero "
                    "el servidor devuelve widget shell sin datos."
                )
        else:
            info("  bkt_init_widget: NO encontrado ❌")
            result["diagnostico"].append("bkt_init_widget ausente en POST — Imperva aún bloquea")

            # ¿Es gate HTML de Imperva?
            if result["post_is_gate"]:
                result["diagnostico"].append(
                    "POST response ES la página gate de Imperva. "
                    "El token GET no es suficiente para bypass completo desde esta IP."
                )
            # ¿Hay alguna señal de datos?
            for kw in ["bookitit", "bkt_", "agenda", "fecha", "huecos", "booking"]:
                if kw in post_text.lower():
                    result["diagnostico"].append(f"Keyword '{kw}' encontrado en POST body")

    except Exception as e:
        error(f"  POST error: {e}")
        result["diagnostico"].append(f"POST falló: {e}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 4: Bookitit directo (app.bookitit.com) — SIN Imperva
# ─────────────────────────────────────────────────────────────────────────────

def etapa_bookitit_directo(tramite: str, url: str) -> dict:
    info(f"\n{'─' * 60}")
    info(f"ETAPA 4 [{tramite}]: Bookitit directo (app.bookitit.com/onlinebookings/main/)")

    pk, sid = extract_pk_sid(url)
    if not pk:
        warn(f"  No se pudo extraer PK de URL: {url[:80]}")
        return {"pk": None, "disponible": False, "error": "PK no extraíble"}

    info(f"  PK: {pk}")
    info(f"  SID: {sid or 'no presente'}")

    ts = int(time.time() * 1000)
    widget_ref = f"{BOOKITIT_WIDGET_BASE}{pk}/{sid or ''}"

    resultados = []
    for modo, params_tpl in [
        ("sin SID", JSONP_PARAMS_TEMPLATE),
        ("con SID", JSONP_PARAMS_WITH_SID if sid else None),
    ]:
        if params_tpl is None:
            continue

        params = params_tpl.format(pk=pk, sid=sid or "", ts=ts)
        endpoint_url = BOOKITIT_JSONP_BASE + params
        info(f"\n  [Modo: {modo}]")
        info(f"  URL: {endpoint_url[:120]}")

        try:
            # Intentar con diferentes orígenes
            for origen, hdrs in [
                ("headers JSONP (mismo origen)", headers_jsonp(widget_ref)),
                ("headers browser simple", headers_browser()),
            ]:
                try:
                    t0 = time.time()
                    r = requests.get(endpoint_url, headers=hdrs, timeout=TIMEOUT, allow_redirects=True)
                    lat = (time.time() - t0) * 1000
                    text = r.text

                    info(f"    [{origen}] HTTP {r.status_code} | {len(text)} chars | {lat:.0f} ms")
                    info(f"    Preview: {text[:300].replace(chr(10), ' ')}")

                    is_gate = detect_imperva_gate(text)
                    has_bkt = "bkt_init_widget" in text
                    has_error_html = "<html" in text[:200].lower()

                    if has_bkt:
                        bkt_pos = text.find("bkt_init_widget")
                        data = parse_bkt_widget(text[bkt_pos: bkt_pos + 8000])
                        info(f"    ✅ bkt_init_widget ENCONTRADO")
                        info(f"    agendas={data['agendas_count']} dates={data['dates_count']} hours={data['hours_count']}")
                        info(f"    dates: {data['dates']}")
                        info(f"    hours: {data['hours']}")
                        disponible = data["dates_count"] > 0 or data["hours_count"] > 0
                        resultados.append({
                            "modo": modo, "origen": origen,
                            "status": r.status_code, "chars": len(text),
                            "bkt_found": True, "disponible": disponible, "data": data,
                            "is_gate": False,
                        })
                        if disponible:
                            info(f"    *** CITA DISPONIBLE VIA BOOKITIT DIRECTO *** 🟢🟢🟢")
                    elif is_gate:
                        info(f"    ❌ Imperva gate también en app.bookitit.com ({origen})")
                        resultados.append({"modo": modo, "origen": origen,
                                           "status": r.status_code, "chars": len(text),
                                           "bkt_found": False, "is_gate": True})
                    elif has_error_html:
                        info(f"    ⚠️  HTML inesperado (no es JSONP)")
                        resultados.append({"modo": modo, "origen": origen,
                                           "status": r.status_code, "chars": len(text),
                                           "bkt_found": False, "is_gate": False, "html_error": True})
                    else:
                        info(f"    ⚠️  Respuesta desconocida: {text[:200]}")
                        resultados.append({"modo": modo, "origen": origen,
                                           "status": r.status_code, "chars": len(text),
                                           "bkt_found": False, "is_gate": False})
                    break  # con 1 origen que responda es suficiente para este modo
                except Exception as e:
                    info(f"    [{origen}] Error: {e}")

        except Exception as e:
            error(f"  Error en modo {modo}: {e}")
            resultados.append({"modo": modo, "error": str(e)})

        time.sleep(0.5)

    # También probar el widget HTML directo
    info(f"\n  [Widget HTML directo] app.bookitit.com/es/hosteds/widgetdefault/{pk}/")
    try:
        r_widget = requests.get(
            widget_ref, headers=headers_browser(), timeout=TIMEOUT, allow_redirects=True
        )
        info(f"    HTTP {r_widget.status_code} | {len(r_widget.text)} chars")
        info(f"    Preview: {r_widget.text[:300].replace(chr(10), ' ')}")
        resultados.append({
            "modo": "widget_html_directo",
            "status": r_widget.status_code,
            "chars": len(r_widget.text),
            "is_gate": detect_imperva_gate(r_widget.text),
        })
    except Exception as e:
        info(f"    Error: {e}")

    return {"pk": pk, "sid": sid, "resultados": resultados}


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 5: AVC + canales Telegram alternativos
# ─────────────────────────────────────────────────────────────────────────────

def _scrapear_canal_telegram(canal: str, horas: int = 48) -> list:
    """
    Scrapea la versión pública web de un canal Telegram.
    Retorna lista de (timestamp, texto) de los últimos {horas} horas.
    """
    url = f"https://t.me/s/{canal}"
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122",
            "Accept-Language": "es-ES,es;q=0.9",
        }, timeout=15, allow_redirects=True)
        html = r.text
    except Exception as e:
        warn(f"  [{canal}] Error GET: {e}")
        return []

    # Extraer mensajes con timestamp
    ahora = datetime.now(timezone.utc)
    limite = ahora - timedelta(hours=horas)

    mensajes = []
    # t.me/s/ usa <time datetime="..."> con ISO format
    bloques = re.findall(
        r'<time[^>]+datetime="([^"]+)"[^>]*>.*?</time>.*?'
        r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        html, re.DOTALL
    )

    for ts_str, body in bloques:
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts < limite:
                continue
            texto = re.sub(r'<[^>]+>', ' ', body).strip()
            texto = re.sub(r'\s+', ' ', texto)
            mensajes.append((ts, texto[:300]))
        except Exception:
            continue

    return mensajes


def _analizar_mensajes_citas(mensajes: list, tramites: list) -> list:
    """Filtra mensajes que mencionan disponibilidad de citas para los tramites."""
    keywords_positivos = [
        "cita disponible", "hay cita", "abrió cita", "liberó cita",
        "fecha disponible", "slot disponible", "huecos disponibles",
        "se abrieron", "citas abiertas", "agendamiento", "turno disponible",
    ]
    keywords_negativos = [
        "sin citas", "no hay citas", "no hay horas", "agotado",
    ]

    hits = []
    for ts, texto in mensajes:
        texto_low = texto.lower()
        # Verificar si menciona algún tramite de interés
        menciona_tramite = False
        for t in tramites:
            svc = {"LEGA": ["legaliz", "lega"],
                   "LMD": ["lmd", "memoria democr", "ciudadan"],
                   "NACIMIENTO": ["nacimient", "fe de vida"],
                   "PASAPORTE": ["pasaport", "dni"],
                   "VISADO": ["visad", "visa"],
                   "MATRIMONIO": ["matrimon", "registro civil"],
                   "NOTARIAL": ["notarial", "apostil"]}.get(t, [t.lower()])
            if any(kw in texto_low for kw in svc):
                menciona_tramite = True
                break

        es_positivo = any(kw in texto_low for kw in keywords_positivos)
        es_negativo = any(kw in texto_low for kw in keywords_negativos)

        if menciona_tramite and es_positivo and not es_negativo:
            hits.append((ts, texto))

    return hits


def etapa_telegram_canales(tramites: list) -> dict:
    info(f"\n{'─' * 60}")
    info("ETAPA 5+6: Canales Telegram alternativos")

    canales = {
        "AsesorVirtualC": "AVC (Asesor Virtual Cubano)",
        "LMDCuba":        "LMD Cuba",
        "cubatramite":    "Cuba Trámite",
        "alertacitasconsulado": "Alerta Citas Consulado",
    }

    resultado = {}
    for canal, nombre in canales.items():
        info(f"\n  [{nombre}] @{canal}")
        mensajes = _scrapear_canal_telegram(canal, horas=48)
        info(f"    Mensajes últimas 48h: {len(mensajes)}")

        hits = _analizar_mensajes_citas(mensajes, tramites)
        info(f"    Alertas de citas relevantes: {len(hits)}")

        for ts, texto in hits[:3]:
            info(f"    📢 [{ts.strftime('%d/%m %H:%M')}] {texto[:150]}")

        # Últimos 3 mensajes para ver actividad
        info(f"    Últimos mensajes recientes:")
        for ts, texto in mensajes[-3:]:
            info(f"      [{ts.strftime('%d/%m %H:%M')}] {texto[:120]}")

        resultado[canal] = {
            "nombre": nombre,
            "total_mensajes_48h": len(mensajes),
            "alertas_citas": len(hits),
            "hits": [(str(ts), t) for ts, t in hits],
        }
        time.sleep(1)

    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Reporte final
# ─────────────────────────────────────────────────────────────────────────────

def generar_reporte(ip_data: dict, resultados_get_post: list,
                    resultados_bkt_directo: list, telegram_data: dict,
                    tramites: list) -> str:
    """Genera reporte Markdown/HTML para enviar a Telegram."""
    lineas = ["<b>🔍 INSPECTOR OVC — DIAGNÓSTICO COMPLETO</b>\n"]
    ahora = datetime.now(timezone.utc) - timedelta(hours=4)
    lineas.append(f"⏰ {ahora.strftime('%d/%m/%Y %H:%M')} Miami\n")

    # IP
    lineas.append(f"<b>IP:</b> <code>{ip_data['ip']}</code> "
                  f"{'⚠️ Datacenter' if ip_data['datacenter'] else '✅ Residencial'}\n")
    lineas.append(f"Latencia Bookitit: {ip_data['latencia_bookitit_ms']:.0f} ms\n")

    lineas.append("\n<b>═══ CAPA GET/POST (citaconsular.es) ═══</b>")
    for r in resultados_get_post:
        t = r["tramite"]
        if not r.get("get_ok"):
            lineas.append(f"❌ [{t}] GET falló")
        elif not r.get("token_found"):
            lineas.append(f"🔴 [{t}] GET OK pero sin token Imperva")
        elif not r.get("post_ok"):
            lineas.append(f"🔴 [{t}] POST falló (token no sirvió)")
        elif not r.get("bkt_found"):
            lineas.append(f"🔴 [{t}] POST OK pero sin bkt_init_widget "
                          f"({'gate Imperva' if r.get('post_is_gate') else 'sin datos'})")
        elif r.get("disponible"):
            d = r.get("data", {})
            lineas.append(f"🟢 [{t}] CITA DISPONIBLE — {d.get('dates', [])} {d.get('hours', [])}")
        else:
            d = r.get("data", {})
            lineas.append(f"🟡 [{t}] bkt encontrado — agendas={d.get('agendas_count',0)} "
                          f"dates={d.get('dates_count',0)} hours={d.get('hours_count',0)}")

        for diag in r.get("diagnostico", []):
            lineas.append(f"  ℹ️ {diag[:100]}")

    lineas.append("\n<b>═══ CAPA BOOKITIT DIRECTO (app.bookitit.com) ═══</b>")
    for r in resultados_bkt_directo:
        t = r.get("tramite", "?")
        if not r.get("pk"):
            lineas.append(f"❓ [{t}] PK no extraíble de URL")
            continue
        pk_short = r["pk"][:12] + "..."
        subr = r.get("resultados", [])
        if not subr:
            lineas.append(f"❓ [{t}] Sin resultados")
            continue

        bkt_results = [x for x in subr if x.get("bkt_found")]
        gate_results = [x for x in subr if x.get("is_gate")]
        html_error   = [x for x in subr if x.get("html_error")]

        if bkt_results:
            br = bkt_results[0]
            d  = br.get("data", {})
            if br.get("disponible"):
                lineas.append(f"🟢🟢 [{t}] DIRECTO DISPONIBLE — {d.get('dates',[])} {d.get('hours',[])}")
            elif d.get("agendas_count", 0) > 0:
                lineas.append(f"🟡 [{t}] Directo: agendas={d['agendas_count']} pero sin fechas")
            else:
                lineas.append(f"🟡 [{t}] Directo: bkt_init_widget vacío (sin citas)")
        elif gate_results:
            lineas.append(f"🔴 [{t}] Directo bloqueado por Imperva también (pk={pk_short})")
        elif html_error:
            lineas.append(f"⚠️ [{t}] Directo: HTML inesperado — endpoint no existe o redirige")
        else:
            lineas.append(f"❓ [{t}] Directo: respuesta inesperada (pk={pk_short})")

    lineas.append("\n<b>═══ CANALES TELEGRAM ═══</b>")
    for canal, data in telegram_data.items():
        n_msg = data["total_mensajes_48h"]
        n_hit = data["alertas_citas"]
        emoji = "🟢" if n_hit > 0 else ("🟡" if n_msg > 0 else "🔴")
        lineas.append(f"{emoji} @{canal}: {n_msg} msgs/48h | {n_hit} alertas citas")
        for ts_str, texto in data["hits"][:2]:
            lineas.append(f"   📢 {texto[:80]}")

    lineas.append("\n<b>═══ DIAGNÓSTICO RAÍZ ═══</b>")
    # Determinar causa raíz
    todos_get_ok = all(r.get("get_ok") and r.get("token_found") for r in resultados_get_post if r)
    todos_post_sin_bkt = all(not r.get("bkt_found") for r in resultados_get_post if r)
    todos_post_gate = all(r.get("post_is_gate") for r in resultados_get_post if r)
    bkt_directo_ok = any(
        any(x.get("bkt_found") for x in r.get("resultados", []))
        for r in resultados_bkt_directo if r
    )

    if todos_post_gate:
        lineas.append("🔴 CAUSA: token GET no es suficiente — POST sigue dando gate Imperva")
        lineas.append("   IP del runner es datacenter y Imperva la bloquea a nivel de IP")
        if bkt_directo_ok:
            lineas.append("✅ SOLUCIÓN: usar app.bookitit.com/onlinebookings/main/ directamente")
        else:
            lineas.append("🔴 app.bookitit.com tampoco accesible — necesita proxy residencial")
    elif todos_post_sin_bkt:
        lineas.append("🟡 CAUSA: POST llega pero bkt_init_widget ausente o vacío")
        lineas.append("   Imperva puede filtrar la respuesta o la data se carga por AJAX")
        if bkt_directo_ok:
            lineas.append("✅ SOLUCIÓN: usar app.bookitit.com directo (no Imperva)")
        else:
            lineas.append("🔴 app.bookitit.com tampoco accesible")
    elif bkt_directo_ok:
        lineas.append("✅ Bookitit directo funciona — actualizar bookitit.py para usar este endpoint")
    else:
        lineas.append("❓ Estado mixto — revisar logs individuales")

    return "\n".join(lineas)


def enviar_telegram(texto: str, admin_only: bool = False):
    """Envía mensaje al canal principal y al admin."""
    targets = []
    if TELEGRAM_CHAT_ID and not admin_only:
        targets.append(TELEGRAM_CHAT_ID)
    if ADMIN_CHAT_ID:
        targets.append(ADMIN_CHAT_ID)

    for chat_id in targets:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": texto[:4000],
                    "parse_mode": "HTML",
                    "disable_notification": True,
                },
                timeout=10,
            )
            if r.ok:
                info(f"Telegram → {chat_id}: OK")
            else:
                warn(f"Telegram → {chat_id}: {r.status_code} {r.text[:80]}")
        except Exception as e:
            warn(f"Telegram error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Inspector de cuellos de botella OVC")
    parser.add_argument("tramites", nargs="*",
                        help="Tramites a inspeccionar (default: todos los configurados)")
    parser.add_argument("--no-avc", action="store_true",
                        help="Omitir análisis de canales Telegram (más rápido)")
    parser.add_argument("--no-telegram", action="store_true",
                        help="No enviar reporte a Telegram")
    parser.add_argument("--solo-directo", action="store_true",
                        help="Solo probar endpoint Bookitit directo (más rápido)")
    args = parser.parse_args()

    info("=" * 70)
    info("OVC INSPECTOR — Diagnóstico integral de cuellos de botella")
    info("=" * 70)

    # Determinar tramites a inspeccionar
    todos_activos = get_tramites_activos()
    if args.tramites:
        tramites = [t.upper() for t in args.tramites if t.upper() in SERVICIOS]
        if not tramites:
            error(f"Tramites no reconocidos: {args.tramites}")
            sys.exit(1)
    else:
        tramites = todos_activos

    info(f"Tramites: {', '.join(tramites)}")

    # Verificar que haya URLs configuradas
    urls = {t: get_url_for_tramite(t) for t in tramites}
    sin_url = [t for t, u in urls.items() if not u]
    if sin_url:
        warn(f"Sin URL configurada: {sin_url}")

    tramites_con_url = [t for t in tramites if urls.get(t)]
    if not tramites_con_url:
        error("Ningún tramite tiene URL configurada — verifica .env")
        sys.exit(1)

    # ── Ejecutar etapas ──────────────────────────────────────────────────────
    ip_data = etapa_ip()

    resultados_get_post = []
    resultados_bkt_directo = []

    for tramite in tramites_con_url:
        url = urls[tramite]

        # Etapa 4: Bookitit directo (siempre — es la prueba clave)
        r_directo = etapa_bookitit_directo(tramite, url)
        r_directo["tramite"] = tramite
        resultados_bkt_directo.append(r_directo)

        if not args.solo_directo:
            # Etapa 2+3: GET/POST citaconsular.es
            r_gp = etapa_get_post(tramite, url)
            resultados_get_post.append(r_gp)

        time.sleep(random.uniform(1.0, 2.0))

    # Etapa 5+6: Canales Telegram
    telegram_data = {}
    if not args.no_avc:
        telegram_data = etapa_telegram_canales(tramites_con_url)

    # ── Reporte ──────────────────────────────────────────────────────────────
    info("\n" + "=" * 70)
    info("RESUMEN EJECUTIVO")
    info("=" * 70)

    reporte = generar_reporte(
        ip_data, resultados_get_post, resultados_bkt_directo,
        telegram_data, tramites_con_url
    )
    info(reporte.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))

    if not args.no_telegram and TELEGRAM_BOT_TOKEN:
        info("\nEnviando reporte a Telegram...")
        enviar_telegram(reporte, admin_only=True)
    else:
        info("(--no-telegram activo o sin token — reporte solo en consola)")

    # Código de salida: 0 si hay disponibilidad en alguna capa, 1 si todo vacío
    hay_disponible = (
        any(r.get("disponible") for r in resultados_get_post) or
        any(
            any(x.get("disponible") for x in r.get("resultados", []))
            for r in resultados_bkt_directo
        )
    )
    sys.exit(0 if hay_disponible else 1)


if __name__ == "__main__":
    main()
