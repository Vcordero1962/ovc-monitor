#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bookitit.py — Verificación de disponibilidad via Bookitit API.

Ingeniería inversa confirmó que el flujo GET/POST a citaconsular.es
es un "soft block" de Imperva: el token POST es aceptado sintácticamente
pero Imperva devuelve bkt_init_widget({}) VACÍO fabricado para engañar bots.

NUEVO ENFOQUE (Capa 1 → Capa 2):
  Capa 1 — DIRECTO a app.bookitit.com (sin Imperva):
    GET app.bookitit.com/onlinebookings/main/?pk={PK}&callback=bkt_init_widget
    El PK se extrae del path de la URL configurada (/widgetdefault/{PK}/).
    app.bookitit.com NO tiene Imperva (es el SaaS origin, no el CDN del cliente).

  Capa 2 — GET/POST citaconsular.es (fallback diagnóstico):
    Si Capa 1 falla completamente (timeout, 404, etc.), intentamos el flujo
    GET→POST legacy. Útil para diagnóstico aunque los datos serán vacíos.

Función pública:
  check_all(tramites: list) → list[(tramite, nombre, url, info_dict)]
"""

import re
import random
import time
import requests

from core.config import SERVICIOS, USER_AGENTS, get_url_for_tramite
from core.logger import info, warn, error
from core.security import validate_widget_url, validate_imperva_token, SecurityError


# ── Helpers internos ───────────────────────────────────────────────────────────

def _human_sleep(min_s: float, max_s: float):
    """Sleep con distribución normal — más natural que uniforme."""
    media = (min_s + max_s) / 2
    std   = (max_s - min_s) / 4
    t = max(min_s, min(max_s, random.gauss(media, std)))
    time.sleep(t)


def _extract_pk_sid(widget_url: str) -> tuple:
    """Extrae (pk, sid) del path /widgetdefault/{pk}/{sid}"""
    m = re.search(r'/widgetdefault/([a-zA-Z0-9]{10,64})(?:/([a-zA-Z0-9]+))?', widget_url)
    if m:
        return m.group(1), m.group(2) or ""
    return "", ""


def _parse_bkt_widget(text: str) -> dict:
    """
    Extrae agendas[], dates[] y hours[] del objeto JS bkt_init_widget.

    Soporta claves con y sin comillas (JS estándar vs JSON).
    Busca fechas YYYY-MM-DD en todo el bloque (no solo en dates[]) porque
    Bookitit puede anidar las fechas dentro de agendas[].dates o agendas[].hours.
    """
    # --- agendas: contar objetos { en el bloque agendas (regex simple, no anidada)
    m_ag = re.search(r"(?:['\"]agendas['\"]|agendas)\s*:\s*\[", text, re.DOTALL)
    agendas_raw = ""
    if m_ag:
        # Extraer hasta 4000 chars del bloque agendas para cubrir estructuras grandes
        agendas_raw = text[m_ag.end(): m_ag.end() + 4000]

    # --- dates top-level (puede estar vacío si Bookitit anida fechas en agendas)
    m2 = re.search(r"(?:['\"]dates['\"]|dates)\s*:\s*(\[[^\]]*\])", text, re.DOTALL)
    dates_raw = m2.group(1) if m2 else "[]"

    # --- búsqueda amplia: cualquier YYYY-MM-DD en TODO el bloque del widget
    all_dates = re.findall(r'\d{4}-\d{2}-\d{2}', text)

    # --- hours: indicador alternativo de disponibilidad (slots de hora HH:MM)
    m_hours = re.search(r"(?:['\"]hours['\"]|hours)\s*:\s*\[([^\]]*)\]", text, re.DOTALL)
    hours_raw = m_hours.group(1) if m_hours else ""
    hours_count = len(re.findall(r'\d{1,2}:\d{2}', hours_raw))

    # --- id_centro y nombre del servicio (indica respuesta real, no vacío fabricado)
    id_centro  = re.search(r"['\"]?id_centro['\"]?\s*:\s*['\"]?(\w+)['\"]?", text)
    nombre_svc = re.search(r"['\"]?nombre['\"]?\s*:\s*['\"]([^'\"]+)['\"]", text)

    dates_count = len(all_dates)

    return {
        "agendas_count": len(re.findall(r'\{', agendas_raw)),
        "dates_count":   dates_count,
        "hours_count":   hours_count,
        "dates_raw":     str(all_dates[:5]),   # primeras 5 fechas encontradas
        "id_centro":     id_centro.group(1)  if id_centro  else "",
        "nombre_svc":    nombre_svc.group(1) if nombre_svc else "",
    }


def _base_headers(ua: str) -> dict:
    return {
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "es-ES,es;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Cache-Control":             "max-age=0",
    }


def _jsonp_headers(ua: str) -> dict:
    """Headers para llamada JSONP — simula request del widget en el browser."""
    return {
        "User-Agent":      ua,
        "Accept":          "*/*",
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         "https://app.bookitit.com/",
        "Origin":          "https://app.bookitit.com",
        "Sec-Fetch-Dest":  "script",
        "Sec-Fetch-Mode":  "no-cors",
        "Sec-Fetch-Site":  "same-origin",
        "Connection":      "keep-alive",
    }


# ── Capa 1: Bookitit directo (sin Imperva) ─────────────────────────────────────

def _check_directo(pk: str, sid: str, ua: str) -> tuple:
    """
    Capa 1 — Llama directamente a app.bookitit.com/onlinebookings/main/.

    app.bookitit.com es el SaaS origin de Bookitit. citaconsular.es/onlinebookings/
    es solo un reverse proxy con Imperva delante. El origin directo no tiene Imperva.

    Retorna (disponible: bool, data: dict, exito: bool).
      exito=True  → el endpoint respondió con bkt_init_widget (real o vacío)
      exito=False → timeout, 404, respuesta no-JSONP — pasar a Capa 2
    """
    if not pk:
        return False, {}, False

    ts   = int(time.time() * 1000)
    base = "https://app.bookitit.com/onlinebookings/main/"
    hdrs = _jsonp_headers(ua)

    # Variantes de parámetros — citaconsular.es usa 'publickey=' (alias antiguo)
    # Bookitit API moderno usa 'pk='. Probamos ambas.
    variantes = [
        # Variante A — pk= con sid (estándar Bookitit + servicio específico)
        ({"callback": "bkt_init_widget", "pk": pk, "lang": "es",
          "services[]": sid, "_": ts} if sid else None),
        # Variante B — pk= sin sid (todas las agendas)
        {"callback": "bkt_init_widget", "pk": pk, "lang": "es", "_": ts},
        # Variante C — publickey= (citaconsular.es alias)
        {"callback": "bkt_init_widget", "publickey": pk, "lang": "es",
         "type": "default", "version": "5",
         **({"services[]": sid} if sid else {}), "_": ts},
    ]

    for params in variantes:
        if params is None:
            continue
        pk_param = "pk" if "pk" in params else "publickey"
        try:
            r = requests.get(base, params=params, headers=hdrs, timeout=15, allow_redirects=True)
            text = r.text
            info(f"BKT-DIRECTO [{pk_param}=, {'con' if sid and 'services[]' in params else 'sin'} sid]: "
                 f"HTTP {r.status_code} — {len(text)} chars")

            if "bkt_init_widget" not in text:
                # No es respuesta JSONP de Bookitit
                if r.status_code in (404, 301, 302):
                    info(f"BKT-DIRECTO: endpoint no existe o redirige ({r.status_code})")
                    return False, {}, False   # Capa 1 no disponible para este tramite
                if len(text) > 200 and "<html" in text[:200].lower():
                    info(f"BKT-DIRECTO: respuesta HTML inesperada — {text[:200]}")
                else:
                    info(f"BKT-DIRECTO: sin bkt_init_widget — {text[:150]}")
                continue   # probar siguiente variante

            # Encontramos bkt_init_widget — parse
            bkt_pos = text.find("bkt_init_widget")
            bkt_block = text[bkt_pos: bkt_pos + 8000]
            info(f"BKT-DIRECTO widget block: {bkt_block[:500].replace(chr(10), ' | ')}")

            data = _parse_bkt_widget(bkt_block)
            info(
                f"BKT-DIRECTO: agendas={data['agendas_count']} "
                f"dates={data['dates_count']} "
                f"hours={data['hours_count']} "
                f"raw={data['dates_raw']}"
            )

            if data["dates_count"] > 0 or data["hours_count"] > 0:
                info("BKT-DIRECTO: *** DISPONIBILIDAD DETECTADA ***")
                return True, data, True

            # bkt_init_widget presente pero sin fechas
            if data["agendas_count"] > 0 or data["id_centro"]:
                # Respuesta real del servidor: agendas configuradas pero sin citas hoy
                info("BKT-DIRECTO: agendas presentes pero sin fechas — sin citas disponibles")
                return False, data, True   # exito=True: endpoint funciona, sin citas
            else:
                # agendas=0, id_centro="" → puede ser PK incorrecto o endpoint vació fabricado
                # Intentar siguiente variante antes de concluir
                info("BKT-DIRECTO: bkt_init_widget completamente vacío — probando siguiente variante")

        except requests.exceptions.Timeout:
            warn(f"BKT-DIRECTO [{pk_param}=]: timeout")
        except Exception as e:
            warn(f"BKT-DIRECTO [{pk_param}=]: {e}")

    # Todas las variantes fallaron o devolvieron vacío total
    info("BKT-DIRECTO: sin respuesta válida en todas las variantes")
    return False, {}, False


# ── Capa 2: GET/POST citaconsular.es (fallback diagnóstico) ───────────────────

def _check_get_post(widget_url: str, ua: str, session: requests.Session) -> tuple:
    """
    Capa 2 — Flujo GET/POST a citaconsular.es via token Imperva.

    NOTA: Investigación confirma que este flujo sufre un "soft block":
    Imperva acepta el token pero devuelve bkt_init_widget({}) vacío fabricado.
    Se mantiene como fallback diagnóstico — los datos vacíos son esperados.

    Retorna (disponible: bool, data: dict).
    """
    headers = _base_headers(ua)

    # Paso 1 — GET: obtener captcha gate + token oculto
    r_get = session.get(widget_url, headers=headers, timeout=20, allow_redirects=True)
    if not r_get.ok:
        warn(f"BKT GET: HTTP {r_get.status_code}")
        return False, {}

    html_get = r_get.text
    info(f"BKT GET: {r_get.status_code} — {len(html_get)} chars")

    # Extraer token Imperva del HTML
    m = re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']', html_get)
    if not m:
        m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html_get)

    if not m:
        warn("BKT token: campo <input name='token'> NO encontrado en GET response")
        return False, {}

    raw_token = m.group(1)

    # Paso 2 — Validar token antes de enviarlo (anti-inyección)
    try:
        token = validate_imperva_token(raw_token, source_url=widget_url)
        info(f"BKT token: {token[:20]}... ({len(token)} chars) — validado ✓")
    except SecurityError as se:
        error(f"BKT token RECHAZADO por seguridad: {se}")
        return False, {}

    # Paso 3 — POST: enviar token
    _human_sleep(0.8, 2.0)
    post_headers = dict(headers)
    post_headers.update({
        "Content-Type":   "application/x-www-form-urlencoded",
        "Referer":        widget_url,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    })

    r_post = session.post(
        widget_url,
        data={"token": token},
        headers=post_headers,
        timeout=20,
        allow_redirects=True,
    )
    if not r_post.ok:
        warn(f"BKT POST: HTTP {r_post.status_code}")
        return False, {}

    post_text = r_post.text
    info(f"BKT POST: {r_post.status_code} — {len(post_text)} chars")
    info(f"BKT POST preview: {post_text[:800].replace(chr(10), ' | ')}")

    # Paso 4 — Parsear bkt_init_widget
    bkt_pos = post_text.find("bkt_init_widget")
    if bkt_pos < 0:
        warn("BKT: bkt_init_widget NO encontrado en POST response (Imperva soft-block?)")
        return False, {}

    bkt_block = post_text[bkt_pos: bkt_pos + 8000]
    info(f"BKT widget block: {bkt_block[:600].replace(chr(10), ' | ')}")

    data = _parse_bkt_widget(bkt_block)
    info(
        f"BKT: agendas={data['agendas_count']} "
        f"dates={data['dates_count']} "
        f"hours={data['hours_count']} "
        f"raw={data['dates_raw']}"
    )

    if data["dates_count"] > 0 or data["hours_count"] > 0:
        info("BKT: *** DISPONIBILIDAD DETECTADA (fechas o slots) ***")
        return True, data

    if data["agendas_count"] > 0:
        info("BKT: agendas presentes pero sin fechas ni horas — sin citas hoy")
    else:
        info("BKT: agendas[], dates[] y hours[] vacíos — soft block Imperva confirmado")

    return False, data


# ── Función principal ──────────────────────────────────────────────────────────

def check_url(widget_url: str) -> tuple:
    """
    Verifica disponibilidad en un widget de citaconsular.es.

    Flujo:
      1. Extraer PK/SID del widget URL
      2. Capa 1: llamar app.bookitit.com directamente (sin Imperva)
         → Si responde con datos reales → resultado definitivo
      3. Capa 2 (fallback): GET/POST citaconsular.es via token Imperva
         → Solo útil para diagnóstico — esperamos datos vacíos por soft block

    Retorna (disponible: bool, info: dict).
    """
    # Paso 0 — Validar URL (anti-inyección de dominio)
    try:
        widget_url = validate_widget_url(widget_url)
    except SecurityError as e:
        error(f"BKT: URL rechazada — {e}")
        return False, {}

    ua      = random.choice(USER_AGENTS)
    session = requests.Session()

    # ── Capa 1: Bookitit directo ───────────────────────────────────────────────
    pk, sid = _extract_pk_sid(widget_url)
    if pk:
        info(f"BKT-DIRECTO: intentando app.bookitit.com (pk={pk[:12]}... sid={sid or 'N/A'})")
        try:
            disponible, data, exito = _check_directo(pk, sid, ua)
            if exito:
                # El endpoint respondió — resultado confiable
                return disponible, data
            else:
                warn("BKT-DIRECTO: endpoint no respondió con JSONP válido — fallback a Capa 2")
        except Exception as e:
            warn(f"BKT-DIRECTO excepción: {e} — fallback a Capa 2")
    else:
        warn(f"BKT: no se pudo extraer PK del URL — omitiendo Capa 1")

    # ── Capa 2: GET/POST citaconsular.es (fallback) ────────────────────────────
    info("BKT-FALLBACK: intentando GET/POST citaconsular.es (Imperva soft-block esperado)")
    try:
        return _check_get_post(widget_url, ua, session)
    except Exception as e:
        error(f"BKT error inesperado en Capa 2: {e}", exc=e)
        return False, {}


def check_all(tramites: list) -> list:
    """
    Verifica Bookitit para todos los tramites activos que tengan URL configurada.

    Retorna lista de (tramite, nombre, url, info_dict) donde hay disponibilidad.
    """
    hits = []
    for i, tramite in enumerate(tramites):
        servicio = SERVICIOS[tramite]
        url = get_url_for_tramite(tramite)

        if not url:
            info(f"BKT [{tramite}]: sin URL configurada ({servicio['url_env']} vacío) — omitiendo")
            continue

        info(f"BKT verificando [{tramite}] {servicio['nombre']}...")
        disponible, data = check_url(url)

        if disponible:
            hits.append((tramite, servicio["nombre"], url, data))

        if i < len(tramites) - 1:
            _human_sleep(1.5, 3.5)

    return hits
