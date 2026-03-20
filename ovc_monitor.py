#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC-X — Orquestador de Vigilancia Consular
Monitor MULTI-TRÁMITE de disponibilidad de citas | Consulado de España en La Habana

Fuentes de monitoreo:
  1. Canal AVC en Telegram (t.me/s/AsesorVirtualC) — alerta anticipada (TODOS los trámites)
  2. Sitio oficial bookitit (citaconsular.es) — detección directa via CF Worker o Playwright
  3. CF Worker Relay (Cloudflare Edge IPs) — bypass bloqueo Imperva en GA

Refactorizado: 20 Marzo 2026 — Soporte multi-trámite simultáneo
"""

import os
import sys
import re
import time
import random
import hashlib
import subprocess
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

# ─── Configuración ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
INTERVALO_MIN       = int(os.getenv("INTERVALO_MIN", "180"))
INTERVALO_MAX       = int(os.getenv("INTERVALO_MAX", "600"))

# CF Worker
CF_WORKER_URL       = os.getenv("CF_WORKER_URL", "")
CF_WORKER_SECRET    = os.getenv("CF_WORKER_SECRET", "")
CF_WORKER_ENABLED   = os.getenv("CF_WORKER_ENABLED", "1") == "1"

# Texto que indica que NO hay citas disponibles en el sitio oficial
TEXTO_BLOQUEADO = "No hay horas disponibles"

# Canal AVC en Telegram (versión web pública)
URL_AVC = "https://t.me/s/AsesorVirtualC"

# ─── Configuración MULTI-TRÁMITE ──────────────────────────────────────────────
# Cada trámite tiene:
#   nombre    : identificador corto para logs y alertas
#   url       : URL del widget bookitit
#   pk        : Public Key de bookitit (extraída de la URL)
#   keywords  : palabras del canal AVC que indican actividad en ESTE trámite
#   alertas   : frases de alerta específicas de este trámite (vacío = usa AVC_ALERTAS_GLOBAL)
#   activo    : True/False para activar/desactivar sin borrar

AVC_ALERTAS_GLOBAL = [
    "TURNOS HABILITADOS",
    "SERAN HABILITADAS",
    "CITAS QUE SER",
    "PROXIMA FECHA",
    "HABILITADOS",
]

TRAMITES_CONFIG = [
    {
        "nombre":   "LEGA",
        "label":    "Legalización Consular",
        "url":      os.getenv("URL_LEGA", "https://www.citaconsular.es/es/hosteds/widgetdefault/25b6cfa9f112aef4ca19457abc237f7ba/"),
        "pk":       "25b6cfa9f112aef4ca19457abc237f7ba",
        "keywords": ["LEGALIZACI", "LEGALIZACIÓN", "LEGALIZACION CONSULAR"],
        "alertas":  [],   # usa globals
        "activo":   True,
    },
    {
        "nombre":   "LMD",
        "label":    "Recogida LMD (Habana)",
        "url":      os.getenv("URL_LMD", "https://www.citaconsular.es/es/hosteds/widgetdefault/28330379fc95acafd31ee9e8938c278ff/"),
        "pk":       "28330379fc95acafd31ee9e8938c278ff",
        "keywords": ["LMD", "LLEGANDO CREDENCIALES LMD", "CREDENCIALES LMD"],
        "alertas":  ["LLEGANDO CREDENCIALES", "CREDENCIALES"],
        "activo":   True,
    },
    {
        "nombre":   "PASAPORTE",
        "label":    "Primer Pasaporte Español",
        "url":      os.getenv("URL_PASAPORTE", "https://www.citaconsular.es/es/hosteds/widgetdefault/22091b5b8d43b89fb226cabb272a844f9/"),
        "pk":       "22091b5b8d43b89fb226cabb272a844f9",
        "keywords": ["PRIMER PASAPORTE", "PASAPORTE ESPAÑOL"],
        "alertas":  [],
        "activo":   True,
    },
    {
        "nombre":   "MATRIMONIO",
        "label":    "Certificado de Matrimonio",
        "url":      os.getenv("URL_MATRIMONIO", "https://www.citaconsular.es/es/hosteds/widgetdefault/2096463e6aff35e340c87439bc59e410c/"),
        "pk":       "2096463e6aff35e340c87439bc59e410c",
        "keywords": ["MATRIMONIO", "CERTIFICADO DE MATRIMONIO", "TRANSCRIPCI"],
        "alertas":  [],
        "activo":   True,
    },
    {
        "nombre":   "VISADO_FAMILIAR",
        "label":    "Visado Familiar Comunitario",
        "url":      os.getenv("URL_VISADO", "https://www.citaconsular.es/es/hosteds/widgetdefault/28db94e270580be60f6e00285a7d8141f/"),
        "pk":       "28db94e270580be60f6e00285a7d8141f",
        "keywords": ["VISADO FAMILIAR", "FAMILIAR COMUNITARIO", "CREDENCIALES VISADO FAMILIAR"],
        "alertas":  ["LLEGANDO CREDENCIALES", "CREDENCIALES"],
        "activo":   True,
    },
    {
        "nombre":   "VISADO_CORTA",
        "label":    "Visado de Corta Duración (Schengen)",
        "url":      os.getenv("URL_VISADO", "https://www.citaconsular.es/es/hosteds/widgetdefault/28db94e270580be60f6e00285a7d8141f/"),
        "pk":       "28db94e270580be60f6e00285a7d8141f",
        "keywords": ["VISADO DE CORTA", "VISADO CORTA", "SCHENGEN"],
        "alertas":  ["LLEGANDO CREDENCIALES", "CREDENCIALES"],
        "activo":   True,
    },
    {
        "nombre":   "NACIMIENTO",
        "label":    "Certificado Literal de Nacimiento / DNI",
        "url":      os.getenv("URL_NACIMIENTO", "https://www.citaconsular.es/es/hosteds/widgetdefault/2f21cd9c0d8aa26725bf8930e4691d645/"),
        "pk":       "2f21cd9c0d8aa26725bf8930e4691d645",
        "keywords": ["NACIMIENTO", "CERTIFICADO LITERAL", "PRIMER DNI", "DNI"],
        "alertas":  [],
        "activo":   True,
    },
    {
        "nombre":   "L36_MENORES",
        "label":    "L-36 Inscripción Directa Menores",
        "url":      os.getenv("URL_NACIMIENTO", "https://www.citaconsular.es/es/hosteds/widgetdefault/2f21cd9c0d8aa26725bf8930e4691d645/"),
        "pk":       "2f21cd9c0d8aa26725bf8930e4691d645",
        "keywords": ["LEY 36", "L-36", "INSCRIPCION DIRECTA", "INSCRIPCIÓN DIRECTA", "MENORES"],
        "alertas":  [],
        "activo":   True,
    },
    {
        "nombre":   "EMIGRANTE",
        "label":    "Certificado Emigrante Retornado",
        "url":      os.getenv("URL_NOTARIAL", "https://www.citaconsular.es/es/hosteds/widgetdefault/2f21cd9c0d8aa26725bf8930e4691d645/"),
        "pk":       "2f21cd9c0d8aa26725bf8930e4691d645",
        "keywords": ["EMIGRANTE RETORNADO", "CERTIFICADO DE EMIGRANTE", "CERTIFICADO EMIGRANTE"],
        "alertas":  [],
        "activo":   True,
    },
]

# Rutas posibles de Chrome en Windows
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\aemes\AppData\Local\Google\Chrome\Application\chrome.exe",
]


# ─── Utilidades ───────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    print(f"[{ts}] {safe}", flush=True)


def alarma_sonora(ciclos: int = 15):
    """Beeps alternados y persistentes."""
    import winsound
    log("ALARMA SONORA ACTIVA — presiona Ctrl+C cuando hayas tomado control")
    for _ in range(ciclos):
        winsound.Beep(880, 400)
        time.sleep(0.1)
        winsound.Beep(1320, 400)
        time.sleep(0.1)
        winsound.Beep(1760, 600)
        time.sleep(0.3)


def enviar_telegram(mensaje: str):
    """Envía mensaje al bot de Telegram configurado."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado — omitiendo alerta (completa .env)")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text":    mensaje,
        }, timeout=10)
        if resp.ok:
            log("Alerta Telegram enviada")
        else:
            log(f"Telegram error HTTP {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        log(f"Error Telegram: {e}")


def rafaga_alerta(mensaje_principal: str, repeticiones: int = 6, intervalo_seg: int = 90):
    """Envía el mensaje y repite la alarma N veces."""
    enviar_telegram(mensaje_principal)
    for i in range(1, repeticiones + 1):
        time.sleep(intervalo_seg)
        aviso = (
            f"ALERTA #{i}/{repeticiones} — CITA DISPONIBLE AHORA\n"
            f"Tienes aproximadamente {(repeticiones - i) * intervalo_seg // 60} min antes "
            f"de que otro tome el turno.\n"
        )
        log(f"  [RAFAGA] Reenvio #{i} de alerta Telegram...")
        enviar_telegram(aviso)


def abrir_chrome_incognito(url: str):
    """Abre Chrome incógnito apuntando al formulario de citas."""
    chrome_exe = next((p for p in CHROME_PATHS if Path(p).exists()), None)
    if chrome_exe:
        subprocess.Popen([chrome_exe, "--incognito", url])
        log(f"Chrome incognito abierto -> {url}")
    else:
        subprocess.Popen(f'start chrome --incognito "{url}"', shell=True)
        log(f"Chrome incognito (shell) -> {url}")


# ─── Monitor AVC — Multi-trámite ─────────────────────────────────────────────

def revisar_canal_avc() -> list[dict]:
    """
    Lee el canal AVC y retorna lista de trámites con alerta detectada.
    Retorna: [{"tramite": <config>, "detalle": str}, ...]
    """
    alertas_detectadas = []
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(URL_AVC, headers=headers, timeout=15)
        if not resp.ok:
            log(f"  [AVC] No accesible: HTTP {resp.status_code}")
            return []

        html  = resp.text
        ahora = datetime.now(timezone.utc)
        limite = ahora - timedelta(hours=48)

        # Extraer bloques de mensajes con timestamp (fix: mapeo msg_id→datetime)
        patron_msg = re.findall(
            r'<time[^>]+datetime="([^"]+)"[^>]*>.*?'
            r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE
        )

        # Construir texto de los mensajes recientes (últimas 48h)
        bloques_recientes = []
        if patron_msg:
            for ts_str, texto in patron_msg:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= limite:
                        bloques_recientes.append(texto)
                except Exception:
                    pass
        else:
            # Fallback: verificar fechas recientes y usar últimos 8KB
            fechas = re.findall(r'datetime="(\d{4}-\d{2}-\d{2}T[^"]+)"', html)
            hay_reciente = False
            for f in fechas:
                try:
                    ts = datetime.fromisoformat(f)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= limite:
                        hay_reciente = True
                        break
                except Exception:
                    pass
            if hay_reciente:
                bloques_recientes = [html[-8000:]]

        if not bloques_recientes:
            log("  [AVC] Sin mensajes nuevos en 48h")
            return []

        html_reciente = " ".join(bloques_recientes).upper()

        # ── Verificar cada trámite activo ─────────────────────────────────────
        for tramite in TRAMITES_CONFIG:
            if not tramite.get("activo", True):
                continue

            keywords = [kw.upper() for kw in tramite["keywords"]]
            alertas  = [a.upper() for a in tramite["alertas"]] or [a.upper() for a in AVC_ALERTAS_GLOBAL]

            tiene_keyword = any(kw in html_reciente for kw in keywords)
            tiene_alerta  = any(a  in html_reciente for a  in alertas)

            if tiene_keyword and tiene_alerta:
                # Extraer fragmento del texto relevante
                fragmento = re.sub(r'<[^>]+>', '', " ".join(bloques_recientes))[:300].strip()
                alertas_detectadas.append({
                    "tramite": tramite,
                    "detalle": fragmento,
                })
                log(f"  [AVC] ALERTA detectada: {tramite['nombre']} — {tramite['label']}")

        if not alertas_detectadas:
            log(f"  [AVC] Sin novedad en {len([t for t in TRAMITES_CONFIG if t['activo']])} tramites")

    except Exception as e:
        log(f"  [AVC] Error al leer canal: {e}")

    return alertas_detectadas


# ─── Monitor bookitit via CF Worker ───────────────────────────────────────────

def verificar_via_cf_worker(tramite: dict) -> bool | None:
    """
    Verifica disponibilidad via Cloudflare Worker.
    Retorna True (cita disponible), False (sin cita), None (error/desconocido).
    """
    if not CF_WORKER_URL or not CF_WORKER_ENABLED:
        return None
    try:
        pk = tramite["pk"]
        params = {
            "mode":   "getservices",
            "pk":     pk,
            "secret": CF_WORKER_SECRET,
        }
        r = requests.get(CF_WORKER_URL, params=params, timeout=20)
        if r.ok:
            data = r.json()
            allow = data.get("AllowAppointment")
            if allow is not None:
                log(f"  [CF] {tramite['nombre']}: AllowAppointment={allow} | "
                    f"domain={data.get('domain','?')} svc={data.get('services_count','?')}")
                return allow
            else:
                log(f"  [CF] {tramite['nombre']}: respuesta sin AllowAppointment — {data}")
        else:
            log(f"  [CF] {tramite['nombre']}: HTTP {r.status_code}")
    except Exception as e:
        log(f"  [CF] {tramite['nombre']}: Error {e}")
    return None


def verificar_via_playwright(tramite: dict) -> bool:
    """
    Verifica disponibilidad directa via Playwright (headless).
    Solo si CF Worker falla o está desactivado.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="es-ES",
                extra_http_headers={
                    "sec-ch-ua": '"Chromium";v="122", "Google Chrome";v="122", "Not(A:Brand";v="24"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                },
            )
            page = ctx.new_page()
            try:
                page.goto("https://www.citaconsular.es", timeout=30000, wait_until="domcontentloaded")
                try:
                    page.click("button:has-text('Aceptar'), button:has-text('Accept'), button:has-text('Entrar')", timeout=5000)
                except Exception:
                    pass
                page.goto(tramite["url"], timeout=35000, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector("#bk-widget, #bookitit-widget, .bk-container, #datetime", timeout=30000)
                except PlaywrightTimeout:
                    pass
                contenido = page.content()
                if TEXTO_BLOQUEADO in contenido:
                    return False
                indicadores = ["bookitit", "bk-widget", "datetime", "Selecciona", "Confirmar", "horas"]
                return any(ind in contenido for ind in indicadores)
            except PlaywrightTimeout:
                return False
            finally:
                browser.close()
    except Exception as e:
        log(f"  [PLAYWRIGHT] {tramite['nombre']}: Error {e}")
        return False


def verificar_disponibilidad_tramite(tramite: dict) -> bool | None:
    """
    Capa 0: CF Worker (IPs Cloudflare, no bloqueadas por Imperva)
    Capa 1: Playwright headless (IP local o residencial)
    """
    # Capa 0: CF Worker
    resultado_cf = verificar_via_cf_worker(tramite)
    if resultado_cf is not None:
        return resultado_cf

    # Capa 1: Playwright (fallback si CF Worker falla)
    log(f"  [SITIO] CF Worker sin resultado — intentando Playwright para {tramite['nombre']}...")
    return verificar_via_playwright(tramite)


# ─── Acciones de alerta ───────────────────────────────────────────────────────

def ejecutar_alerta(origen: str, tramite: dict, detalle: str = ""):
    """Ejecuta la secuencia completa de alerta: Telegram + Chrome."""
    hora = datetime.now().strftime("%H:%M:%S del %d/%m/%Y")

    log(f"============================================================")
    log(f"  CITA DISPONIBLE DETECTADA! [{origen}] — {tramite['label']}")
    log(f"  Hora: {hora}")
    log(f"============================================================")

    # 1. Alarma sonora (solo en PC local, no en GA)
    try:
        alarma_sonora()
    except Exception:
        pass  # En GitHub Actions no hay winsound

    # 2. Telegram
    if origen == "AVC":
        cuerpo = (
            f"ALERTA TEMPRANA — Canal AVC\n"
            f"Tramite: {tramite['label']}\n"
            f"Detectado: {hora}\n\n"
            f"{detalle[:200]}\n\n"
            f"Vigila el sitio oficial ahora:\n{tramite['url']}"
        )
    else:
        cuerpo = (
            f"CITA DISPONIBLE — Sitio Oficial!\n"
            f"Consulado Espana - La Habana\n"
            f"Tramite: {tramite['label']}\n"
            f"Detectado: {hora}\n\n"
            f"INGRESA TUS CREDENCIALES AHORA:\n"
            f"{tramite['url']}"
        )

    rafaga_alerta(cuerpo, repeticiones=8, intervalo_seg=30)

    # 3. Chrome incógnito — solo si es disponibilidad REAL en el sitio oficial
    if origen == "SITIO":
        abrir_chrome_incognito(tramite["url"])
        log("STOP — Ingresa USUARIO_CI y PASSWORD_CITA manualmente.")
        log("   Resuelve el hCaptcha y pulsa Confirmar.")
        log("   ATENCION: La cita NO admite cancelacion ni modificacion.")


# ─── Loop principal ───────────────────────────────────────────────────────────

def monitor_loop():
    tramites_activos = [t for t in TRAMITES_CONFIG if t.get("activo", True)]
    if not tramites_activos:
        log("ERROR: No hay tramites activos en TRAMITES_CONFIG — abortando")
        sys.exit(1)

    telegram_ok = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    cf_ok       = bool(CF_WORKER_URL and CF_WORKER_ENABLED)

    log("=" * 64)
    log("  OVC-X MULTI-TRAMITE — Orquestador de Vigilancia Consular")
    log(f"  Tramites activos : {len(tramites_activos)}")
    for t in tramites_activos:
        log(f"    [{t['nombre']}] {t['label']}")
    log(f"  AVC Canal        : {URL_AVC}")
    log(f"  Telegram         : {'OK' if telegram_ok else 'NO configurado'}")
    log(f"  CF Worker        : {'OK (' + CF_WORKER_URL[:40] + '...)' if cf_ok else 'NO configurado'}")
    log(f"  Intervalo        : {INTERVALO_MIN // 60} a {INTERVALO_MAX // 60} min")
    log("  Ctrl+C para detener")
    log("=" * 64)

    # Estado por trámite: {nombre: {"ultimo_hash": str, "ultima_alerta_ts": datetime}}
    estado_avc  = {t["nombre"]: {"ultimo_hash": "", "ultima_ts": datetime.min} for t in tramites_activos}

    ciclo = 0
    while True:
        ciclo += 1
        log(f"\n[Ciclo #{ciclo:03d}] -----------------------------------------")

        # ── 1. Verificar disponibilidad REAL en sitio oficial (todos los trámites) ──
        for tramite in tramites_activos:
            log(f"  [SITIO] Verificando {tramite['nombre']}...")
            resultado = verificar_disponibilidad_tramite(tramite)
            if resultado is True:
                ejecutar_alerta("SITIO", tramite)
                break  # Detener todo: el usuario toma control
            elif resultado is False:
                log(f"  [SITIO] {tramite['nombre']}: Sin disponibilidad")
            else:
                log(f"  [SITIO] {tramite['nombre']}: Sin dato (bloqueado o error)")

        # ── 2. Verificar canal AVC (todos los trámites simultáneamente) ─────────
        log(f"  [AVC] Revisando canal ({len(tramites_activos)} tramites)...")
        alertas_avc = revisar_canal_avc()

        for alerta in alertas_avc:
            tramite = alerta["tramite"]
            detalle = alerta["detalle"]
            nombre  = tramite["nombre"]
            hash_actual = hashlib.md5(detalle.encode()).hexdigest()
            est = estado_avc.get(nombre, {"ultimo_hash": "", "ultima_ts": datetime.min})

            if hash_actual != est["ultimo_hash"]:
                log(f"  [AVC] NUEVO mensaje relevante: {nombre}")
                ejecutar_alerta("AVC", tramite, detalle)
                estado_avc[nombre]["ultimo_hash"] = hash_actual
                estado_avc[nombre]["ultima_ts"]   = datetime.now()
            else:
                log(f"  [AVC] {nombre}: mismo mensaje ya alertado — ignorando")

        # ── 3. Espera aleatoria anti-detección ────────────────────────────────
        intervalo = random.randint(INTERVALO_MIN, INTERVALO_MAX)
        proxima   = datetime.fromtimestamp(time.time() + intervalo).strftime("%H:%M:%S")
        log(f"  Proxima revision a las {proxima} ({intervalo // 60}m {intervalo % 60}s)\n")
        time.sleep(intervalo)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        log("\nMonitor detenido por el usuario.")
        sys.exit(0)
