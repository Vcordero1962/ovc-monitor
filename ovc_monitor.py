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
        
           # usa globals
        "activo":   True,
    },
    {
        "nombre":   "LMD",
        "label":    "Recogida LMD (Habana)",
        "url":      os.getenv("URL_LMD", "https://www.citaconsular.es/es/hosteds/widgetdefault/28330379fc95acafd31ee9e8938c278ff/"),
        "pk":       "28330379fc95acafd31ee9e8938c278ff",
        
        
        "activo":   True,
    },
    {
        "nombre":   "PASAPORTE",
        "label":    "Primer Pasaporte Español",
        "url":      os.getenv("URL_PASAPORTE", "https://www.citaconsular.es/es/hosteds/widgetdefault/22091b5b8d43b89fb226cabb272a844f9/"),
        "pk":       "22091b5b8d43b89fb226cabb272a844f9",
        
        
        "activo":   True,
    },
    {
        "nombre":   "MATRIMONIO",
        "label":    "Certificado de Matrimonio",
        "url":      os.getenv("URL_MATRIMONIO", "https://www.citaconsular.es/es/hosteds/widgetdefault/2096463e6aff35e340c87439bc59e410c/"),
        "pk":       "2096463e6aff35e340c87439bc59e410c",
        
        
        "activo":   True,
    },
    {
        "nombre":   "VISADO_FAMILIAR",
        "label":    "Visado Familiar Comunitario",
        "url":      os.getenv("URL_VISADO", "https://www.citaconsular.es/es/hosteds/widgetdefault/28db94e270580be60f6e00285a7d8141f/"),
        "pk":       "28db94e270580be60f6e00285a7d8141f",
        
        
        "activo":   True,
    },
    {
        "nombre":   "VISADO_CORTA",
        "label":    "Visado de Corta Duración (Schengen)",
        "url":      os.getenv("URL_VISADO", "https://www.citaconsular.es/es/hosteds/widgetdefault/28db94e270580be60f6e00285a7d8141f/"),
        "pk":       "28db94e270580be60f6e00285a7d8141f",
        
        
        "activo":   True,
    },
    {
        "nombre":   "NACIMIENTO",
        "label":    "Certificado Literal de Nacimiento / DNI",
        "url":      os.getenv("URL_NACIMIENTO", "https://www.citaconsular.es/es/hosteds/widgetdefault/2f21cd9c0d8aa26725bf8930e4691d645/"),
        "pk":       "2f21cd9c0d8aa26725bf8930e4691d645",
        
        
        "activo":   True,
    },
    {
        "nombre":   "L36_MENORES",
        "label":    "L-36 Inscripción Directa Menores",
        "url":      os.getenv("URL_NACIMIENTO", "https://www.citaconsular.es/es/hosteds/widgetdefault/2f21cd9c0d8aa26725bf8930e4691d645/"),
        "pk":       "2f21cd9c0d8aa26725bf8930e4691d645",
        
        
        "activo":   True,
    },
    {
        "nombre":   "EMIGRANTE",
        "label":    "Certificado Emigrante Retornado",
        "url":      os.getenv("URL_NOTARIAL", "https://www.citaconsular.es/es/hosteds/widgetdefault/2f21cd9c0d8aa26725bf8930e4691d645/"),
        "pk":       "2f21cd9c0d8aa26725bf8930e4691d645",
        
        
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

        time.sleep(intervalo)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        log("\nMonitor detenido por el usuario.")
        sys.exit(0)

