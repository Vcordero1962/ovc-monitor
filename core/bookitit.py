#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bookitit.py — Verificación de disponibilidad via Bookitit API.

Inspector Mar 17 confirmó:
  - citaconsular.es/onlinebookings/main/ → soft block Imperva (bkt_init_widget({}) falso)
  - app.bookitit.com/onlinebookings/main/ → HTTP 200 cuerpo VACÍO (0 chars) — también Imperva
  - app.bookitit.com/es/hosteds/widgetdefault/{PK}/ → 1317 chars (gate Imperva con token)

ESTRATEGIA ACTUAL (4 capas, en orden):
  Capa 0 — Cloudflare Worker relay (IPs CF edge 104.x.x.x):
    CF_WORKER_URL + CF_WORKER_SECRET — Worker propio en dash.cloudflare.com.
    Corre en IPs de Cloudflare, fuera de la lista negra de datacenter de Imperva.
    mode=full: Worker hace GET→POST→JSONP internamente (con cookie sesión Imperva).
    mode=jsonp: JSONP directo sin cookies (rápido, fallback si full falla).
    Requiere deploy manual — ver cloudflare_worker/worker.js.

  Capa 1 — GET/POST app.bookitit.com + JSONP con session cookie:
    El SaaS origin de Bookitit también tiene Imperva. Fallback si CF Worker
    no está configurado o falla.

  Capa 2 — GET JSONP directo app.bookitit.com (sin sesión):
    Variante simple sin cookies.

  Capa 3 — GET/POST citaconsular.es (fallback diagnóstico):
    El flujo original — soft block esperado.

Función pública:
  check_all(tramites: list) → list[(tramite, nombre, url, info_dict)]
"""

import re
import random
import time
import requests

from core.config import SERVICIOS, USER_AGENTS, get_url_for_tramite, CF_WORKER_URL, CF_WORKER_SECRET, CF_WORKER_ENABLED
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


# ── Capa 0: Cloudflare Worker relay (IPs de CF edge — no datacenter) ──────────

def _check_cf_worker(pk: str, sid: str, ua: str, mode: str = "full") -> tuple:
    """
    Capa 0 — Llama al CF Worker propio como intermediario.

    El Worker corre en IPs de Cloudflare (104.x.x.x) que Imperva/Bookitit
    trata diferente a IPs de GitHub Actions/datacenter.

    mode="jsonp" → JSONP directo desde CF (rápido, puede no tener cookies)
    mode="full"  → Worker hace GET→POST→JSONP internamente (con cookie Imperva)

    Retorna (disponible: bool, data: dict, exito: bool).
    """
    if not CF_WORKER_ENABLED or not CF_WORKER_URL:
        return False, {}, False
    if not pk:
        return False, {}, False

    params = {"pk": pk, "mode": mode}
    if sid:
        params["sid"] = sid
    if CF_WORKER_SECRET:
        params["secret"] = CF_WORKER_SECRET

    try:
        r = requests.get(
            CF_WORKER_URL,
            params=params,
            headers={"User-Agent": ua, "Accept": "*/*"},
            timeout=35,   # mode=full necesita más tiempo (3 requests encadenados)
        )
        text = r.text
        chars = len(text)
        has_bkt = "bkt_init_widget" in text
        info(f"CF-WORKER [{mode}]: HTTP {r.status_code} — {chars} chars — bkt={has_bkt}")

        if r.status_code in (401, 403):
            warn(f"CF-WORKER: acceso denegado ({r.status_code}) — verificar CF_WORKER_SECRET")
            return False, {}, False

        if not has_bkt:
            if chars > 0:
                info(f"CF-WORKER preview: {text[:200].replace(chr(10), ' | ')}")
            warn(f"CF-WORKER: sin bkt_init_widget — {chars} chars")
            return False, {}, False

        bkt_pos = text.find("bkt_init_widget")
        data = _parse_bkt_widget(text[bkt_pos: bkt_pos + 10000])
        info(f"CF-WORKER: agendas={data['agendas_count']} dates={data['dates_count']} hours={data['hours_count']} raw={data['dates_raw']}")

        if data["dates_count"] > 0 or data["hours_count"] > 0:
            info("CF-WORKER: *** DISPONIBILIDAD DETECTADA ***")
            return True, data, True
        if data["agendas_count"] > 0 or data["id_centro"]:
            info("CF-WORKER: agendas reales — sin citas disponibles")
            return False, data, True
        info("CF-WORKER: bkt_init_widget vacío — Worker también bloqueado por Imperva")
        return False, {}, False

    except requests.exceptions.Timeout:
        warn(f"CF-WORKER [{mode}]: timeout (>{35}s)")
        return False, {}, False
    except Exception as e:
        warn(f"CF-WORKER error: {e}")
        return False, {}, False


# ── Capa 1: GET/POST app.bookitit.com + JSONP con session cookie ───────────────

def _check_app_bookitit_con_sesion(pk: str, sid: str, ua: str) -> tuple:
    """
    Capa 1 — Flujo completo en app.bookitit.com:
      GET  widget → extrae token Imperva del gate HTML
      POST token  → establece sesión/cookie con el SaaS origin
      GET  JSONP  → llama onlinebookings/main/ con esa sesión

    La hipótesis: el gate de app.bookitit.com puede tener configuración
    Imperva más permisiva que citaconsular.es (SaaS origin vs cliente).
    Con la cookie de sesión POST, el JSONP que antes daba 0 chars
    podría responder con datos reales.

    Retorna (disponible: bool, data: dict, exito: bool).
      exito=True  → endpoint JSONP respondió con bkt_init_widget
      exito=False → gate POST falló o JSONP sigue en 0 chars
    """
    if not pk:
        return False, {}, False

    widget_url = f"https://app.bookitit.com/es/hosteds/widgetdefault/{pk}/{sid or ''}"
    session = requests.Session()
    ts = int(time.time() * 1000)

    # ── GET widget → token ──────────────────────────────────────────────────────
    try:
        r_get = session.get(widget_url, headers=_base_headers(ua), timeout=20, allow_redirects=True)
        html = r_get.text
        info(f"BKT-APP GET: {r_get.status_code} — {len(html)} chars")

        m = re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']', html)
        if not m:
            m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html)

        if not m:
            info("BKT-APP: sin token Imperva en GET — app.bookitit.com gate diferente")
            return False, {}, False

        raw_token = m.group(1)
        info(f"BKT-APP: token {raw_token[:20]}... ({len(raw_token)} chars)")
    except Exception as e:
        warn(f"BKT-APP GET error: {e}")
        return False, {}, False

    # ── POST token → establecer sesión ─────────────────────────────────────────
    try:
        _human_sleep(0.5, 1.5)
        post_hdrs = dict(_base_headers(ua))
        post_hdrs.update({
            "Content-Type":   "application/x-www-form-urlencoded",
            "Referer":        widget_url,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
        })
        r_post = session.post(
            widget_url, data={"token": raw_token},
            headers=post_hdrs, timeout=20, allow_redirects=True,
        )
        post_text = r_post.text
        info(f"BKT-APP POST: {r_post.status_code} — {len(post_text)} chars")
        info(f"BKT-APP POST preview: {post_text[:400].replace(chr(10), ' | ')}")

        # Comprobar si el POST ya contiene bkt_init_widget (caso ideal)
        if "bkt_init_widget" in post_text:
            bkt_pos = post_text.find("bkt_init_widget")
            data = _parse_bkt_widget(post_text[bkt_pos: bkt_pos + 8000])
            info(f"BKT-APP POST contiene bkt_init_widget: agendas={data['agendas_count']} dates={data['dates_count']}")
            if data["dates_count"] > 0 or data["hours_count"] > 0:
                return True, data, True
            if data["agendas_count"] > 0 or data["id_centro"]:
                return False, data, True
    except Exception as e:
        warn(f"BKT-APP POST error: {e}")
        return False, {}, False

    # ── GET JSONP con sesión activa ─────────────────────────────────────────────
    # Ahora la sesión tiene la cookie post-POST. El JSONP que antes daba
    # 0 chars puede responder con datos reales al tener autenticación.
    for param_name in ["pk", "publickey"]:
        params = {
            "callback": "bkt_init_widget",
            param_name: pk,
            "lang":     "es",
            "version":  "5",
            "_":        ts,
        }
        if sid:
            params["services[]"] = sid

        try:
            r_jsonp = session.get(
                "https://app.bookitit.com/onlinebookings/main/",
                params=params,
                headers=_jsonp_headers(ua),
                timeout=15,
                allow_redirects=True,
            )
            text = r_jsonp.text
            info(f"BKT-APP JSONP [{param_name}=]: {r_jsonp.status_code} — {len(text)} chars")
            if text:
                info(f"BKT-APP JSONP preview: {text[:300].replace(chr(10), ' | ')}")

            if "bkt_init_widget" in text:
                bkt_pos = text.find("bkt_init_widget")
                bkt_block = text[bkt_pos: bkt_pos + 8000]
                data = _parse_bkt_widget(bkt_block)
                info(f"BKT-APP JSONP: agendas={data['agendas_count']} dates={data['dates_count']} hours={data['hours_count']}")
                if data["dates_count"] > 0 or data["hours_count"] > 0:
                    info("BKT-APP: *** DISPONIBILIDAD DETECTADA ***")
                    return True, data, True
                if data["agendas_count"] > 0 or data["id_centro"]:
                    info("BKT-APP: agendas presentes pero sin fechas — sin citas")
                    return False, data, True
                # bkt completamente vacío — puede ser soft block igual que citaconsular.es
                info("BKT-APP: bkt_init_widget vacío — probando siguiente variante")
            elif len(text) == 0:
                info("BKT-APP JSONP: 0 chars — sesión POST no desbloqueó el JSONP")
            else:
                info(f"BKT-APP JSONP: respuesta sin bkt_init_widget ({len(text)} chars)")
        except Exception as e:
            warn(f"BKT-APP JSONP [{param_name}=] error: {e}")

    return False, {}, False


# ── Capa 2: Bookitit JSONP directo (sin sesión) ────────────────────────────────

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


# ── Capa principal: GET/POST citaconsular.es + JSONP con cookie de sesión ──────

def _check_get_post(widget_url: str, ua: str, session: requests.Session) -> tuple:
    """
    Flujo completo citaconsular.es — ARQUITECTURA REAL descubierta Mar 17:

    El POST response contiene bkt_init_widget = { srvsrc, publickey, services, agendas:[], dates:[] }
    Esto es solo CONFIGURACIÓN del widget, NO datos de disponibilidad.
    El widget carga loadermaec.js que hace el JSONP real con la cookie Imperva del POST.

    Flujo correcto:
      1. GET widget → token Imperva
      2. POST con token → Imperva establece cookie sesión + devuelve config
      3. Extraer srvsrc + publickey + services del config
      4. GET {srvsrc}/onlinebookings/main/?publickey=...&services[]=... CON cookie
         → Datos REALES de disponibilidad

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

    # Paso 3 — POST: enviar token → Imperva establece cookie de sesión
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
    cookies_set = list(session.cookies.keys())
    info(f"BKT POST: {r_post.status_code} — {len(post_text)} chars | cookies: {cookies_set}")

    # Paso 4 — Extraer config del widget del POST response
    bkt_pos = post_text.find("bkt_init_widget")
    if bkt_pos < 0:
        warn("BKT: bkt_init_widget NO encontrado en POST response")
        return False, {}

    bkt_config = post_text[bkt_pos: bkt_pos + 3000]

    # Extraer srvsrc (dominio base para el JSONP real)
    m_src = re.search(r"srvsrc\s*:\s*['\"]([^'\"]+)['\"]", bkt_config)
    srvsrc = m_src.group(1).rstrip("/") if m_src else "https://www.citaconsular.es"

    # Extraer publickey del config
    m_pk = re.search(r"publickey\s*:\s*['\"]([a-zA-Z0-9]+)['\"]", bkt_config)
    pk_config = m_pk.group(1) if m_pk else ""
    if not pk_config:
        pk_config, _ = _extract_pk_sid(widget_url)

    # Extraer services[] del config
    m_svc = re.search(r"services\s*:\s*\[([^\]]*)\]", bkt_config)
    services_raw = m_svc.group(1) if m_svc else ""
    services = re.findall(r"['\"]([^'\"]+)['\"]", services_raw)

    info(f"BKT config: srvsrc={srvsrc} pk={pk_config[:16]}... services={services}")

    # Paso 5 — GET JSONP con cookie de sesión Imperva
    # loadermaec.js hace este call con las cookies del browser → nosotros con Session()
    ts = int(time.time() * 1000)
    params_list = [
        ("callback",  "bkt_init_widget"),
        ("publickey", pk_config),
        ("lang",      "es"),
        ("type",      "default"),
        ("version",   "5"),
        ("_",         ts),
    ]
    for svc in services:
        params_list.append(("services[]", svc))

    jsonp_url = f"{srvsrc}/onlinebookings/main/"
    jsonp_hdrs = {
        "User-Agent":      ua,
        "Accept":          "*/*",
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         widget_url,
        "Sec-Fetch-Dest":  "script",
        "Sec-Fetch-Mode":  "no-cors",
        "Sec-Fetch-Site":  "same-origin",
        "Connection":      "keep-alive",
    }

    try:
        _human_sleep(0.3, 0.8)
        r_jsonp = session.get(
            jsonp_url, params=params_list,
            headers=jsonp_hdrs, timeout=20, allow_redirects=True,
        )
        jsonp_text = r_jsonp.text
        info(f"BKT JSONP: {r_jsonp.status_code} — {len(jsonp_text)} chars")
        if jsonp_text:
            info(f"BKT JSONP preview: {jsonp_text[:600].replace(chr(10), ' | ')}")

        if "bkt_init_widget" in jsonp_text or "agendas" in jsonp_text:
            j_pos = jsonp_text.find("bkt_init_widget")
            if j_pos < 0:
                j_pos = 0
            data = _parse_bkt_widget(jsonp_text[j_pos: j_pos + 10000])
            info(f"BKT JSONP parsed: agendas={data['agendas_count']} dates={data['dates_count']} hours={data['hours_count']} raw={data['dates_raw']}")
            if data["dates_count"] > 0 or data["hours_count"] > 0:
                info("BKT JSONP: *** DISPONIBILIDAD DETECTADA ***")
                return True, data
            if data["agendas_count"] > 0 or data["id_centro"]:
                info("BKT JSONP: agendas reales pero sin fechas — sin citas hoy")
                return False, data
            info("BKT JSONP: bkt vacío — agendas=0, sin citas o soft-block persistente")
            return False, data
        elif len(jsonp_text) == 0:
            warn("BKT JSONP: 0 chars — cookie de sesión no desbloqueó el endpoint")
        else:
            info(f"BKT JSONP: respuesta sin bkt_init_widget ({len(jsonp_text)} chars)")
    except Exception as e:
        warn(f"BKT JSONP error: {e}")

    # Si JSONP falló, al menos tenemos el config del POST
    data = _parse_bkt_widget(bkt_config)
    info(f"BKT (config POST): agendas={data['agendas_count']} dates={data['dates_count']}")
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

    pk, sid = _extract_pk_sid(widget_url)

    # ── Capa 0: Cloudflare Worker relay ───────────────────────────────────────
    if pk and CF_WORKER_ENABLED and CF_WORKER_URL:
        info(f"CF-WORKER: intentando relay via Cloudflare edge (pk={pk[:12]}... sid={sid or 'N/A'})")
        try:
            # Primero mode=full (GET→POST→JSONP interno en el Worker)
            disponible, data, exito = _check_cf_worker(pk, sid, ua, mode="full")
            if exito:
                return disponible, data
            # Si full falló, probar mode=jsonp (más rápido, sin cookies)
            disponible, data, exito = _check_cf_worker(pk, sid, ua, mode="jsonp")
            if exito:
                return disponible, data
            warn("CF-WORKER: sin respuesta válida en ambos modos — pasando a Capa 1")
        except Exception as e:
            warn(f"CF-WORKER excepción: {e} — pasando a Capa 1")
    elif CF_WORKER_ENABLED and not CF_WORKER_URL:
        info("CF-WORKER: CF_WORKER_URL no configurada — omitiendo Capa 0 (ver DEPLOY.md)")

    # ── Capa 1: GET/POST app.bookitit.com + JSONP con sesión ──────────────────
    if pk:
        info(f"BKT-APP: intentando GET/POST app.bookitit.com (pk={pk[:12]}... sid={sid or 'N/A'})")
        try:
            disponible, data, exito = _check_app_bookitit_con_sesion(pk, sid, ua)
            if exito:
                return disponible, data
            warn("BKT-APP: sin JSONP válido — pasando a Capa 2")
        except Exception as e:
            warn(f"BKT-APP excepción: {e} — pasando a Capa 2")
    else:
        warn("BKT: no se pudo extraer PK del URL — omitiendo Capas 1 y 2")

    # ── Capa 2: JSONP directo app.bookitit.com (sin sesión) ───────────────────
    if pk:
        info("BKT-DIRECTO: intentando JSONP directo sin sesión (app.bookitit.com)")
        try:
            disponible, data, exito = _check_directo(pk, sid, ua)
            if exito:
                return disponible, data
            warn("BKT-DIRECTO: sin JSONP válido — pasando a Capa 3")
        except Exception as e:
            warn(f"BKT-DIRECTO excepción: {e} — pasando a Capa 3")

    # ── Capa 3: GET/POST citaconsular.es (fallback diagnóstico) ───────────────
    info("BKT-CITA: intentando GET/POST citaconsular.es (soft-block Imperva esperado)")
    try:
        return _check_get_post(widget_url, ua, session)
    except Exception as e:
        error(f"BKT error inesperado en Capa 3: {e}", exc=e)
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
