#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC-X — Orquestador de Vigilancia Consular
Monitor de disponibilidad de citas | Consulado de España en La Habana

Fuentes de monitoreo:
  1. Sitio oficial bookitit (citaconsular.es) — detección directa
  2. Canal AVC en Telegram  (t.me/s/AsesorVirtualC) — alerta anticipada
"""

import os
import sys
import re
import time
import random
import hashlib
import subprocess
import winsound
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ─── Configuración ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

URL_SISTEMA         = os.getenv("URL_SISTEMA", "")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
AVC_TRAMITE         = os.getenv("AVC_TRAMITE", "LMD").upper()
INTERVALO_MIN       = int(os.getenv("INTERVALO_MIN", "180"))
INTERVALO_MAX       = int(os.getenv("INTERVALO_MAX", "600"))

# Texto que indica que NO hay citas disponibles en el sitio oficial
TEXTO_BLOQUEADO = "No hay horas disponibles"

# Canal AVC en Telegram (versión web pública)
URL_AVC = "https://t.me/s/AsesorVirtualC"

# Palabras clave por trámite para detectar en el canal AVC
AVC_KEYWORDS = {
    "LMD": ["LMD", "LEGALIZACI", "CREDENCIALES"],
    "PASAPORTE": ["PASAPORTE"],
    "MATRIMONIO": ["MATRIMONIO", "TRANSCRIPCI"],
    "VISADO": ["VISADO"],
}

# Frases de alerta en el canal AVC
# "HABILITADOS" solo cuenta si NO va seguido de "AGOTADOS" en el mismo contexto
AVC_ALERTAS = ["CITAS QUE SER", "SERAN HABILITADAS", "PROXIMA FECHA"]

# Rutas posibles de Chrome en Windows
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\aemes\AppData\Local\Google\Chrome\Application\chrome.exe",
]

# ─── Utilidades ───────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Eliminar emojis para compatibilidad con terminal Windows (cp1252)
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    print(f"[{ts}] {safe}", flush=True)


def alarma_sonora(ciclos: int = 15):
    """Beeps alternados y persistentes."""
    log("🔔 ALARMA SONORA ACTIVA — presiona Ctrl+C cuando hayas tomado control")
    for _ in range(ciclos):
        winsound.Beep(880, 400)
        time.sleep(0.1)
        winsound.Beep(1320, 400)
        time.sleep(0.1)
        winsound.Beep(1760, 600)
        time.sleep(0.3)


def enviar_telegram(mensaje: str, nivel: str = "🚨"):
    """Envía mensaje al bot de Telegram configurado."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️  Telegram no configurado — omitiendo alerta (completa .env)")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        # Sin parse_mode: evita error 400 cuando el detalle AVC contiene HTML roto
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
        }, timeout=10)
        if resp.ok:
            log("✅ Alerta Telegram enviada")
        else:
            log(f"❌ Telegram error HTTP {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        log(f"❌ Error Telegram: {e}")


def rafaga_alerta(mensaje_principal: str, repeticiones: int = 6, intervalo_seg: int = 90):
    """
    Envía el mensaje principal y luego repite la alarma cada 'intervalo_seg' segundos
    hasta 'repeticiones' veces — fuerza múltiples notificaciones sonoras en el celular.
    """
    enviar_telegram(mensaje_principal)
    for i in range(1, repeticiones + 1):
        time.sleep(intervalo_seg)
        aviso = (
            f"🔴 ALERTA #{i}/{repeticiones} — CITA DISPONIBLE AHORA\n"
            f"Tienes aproximadamente {(repeticiones - i) * intervalo_seg // 60} min antes "
            f"de que otro tome el turno.\n"
            f"Entra YA: {URL_SISTEMA}"
        )
        log(f"  [RAFAGA] Reenvio #{i} de alerta Telegram...")
        enviar_telegram(aviso)
        winsound.Beep(1760, 800)  # Beep adicional local en la PC


def abrir_chrome_incognito(url: str):
    """Abre Chrome incógnito apuntando al formulario de citas."""
    chrome_exe = next((p for p in CHROME_PATHS if Path(p).exists()), None)
    if chrome_exe:
        subprocess.Popen([chrome_exe, "--incognito", url])
        log(f"✅ Chrome incógnito abierto → {url}")
    else:
        subprocess.Popen(f'start chrome --incognito "{url}"', shell=True)
        log(f"✅ Chrome incógnito (shell) → {url}")


# ─── Monitor AVC ─────────────────────────────────────────────────────────────

def revisar_canal_avc() -> tuple[bool, str]:
    """
    Lee los mensajes recientes del canal AVC en Telegram.
    Solo procesa mensajes publicados en las últimas 48 horas.

    Retorna (hay_alerta, detalle):
      - hay_alerta = True si se encontró un mensaje RECIENTE con alerta del trámite
      - detalle = texto del mensaje detectado (vacío si no hay alerta)
    """
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
            log(f"⚠️  AVC no accesible: HTTP {resp.status_code}")
            return False, ""

        html = resp.text
        ahora = datetime.now(timezone.utc)
        limite = ahora - timedelta(hours=48)
        keywords_tramite = AVC_KEYWORDS.get(AVC_TRAMITE, [])

        # Extraer bloques de mensaje con su timestamp
        # t.me/s/ usa <time datetime="2026-03-12T10:00:00+00:00">
        patron_msg = re.findall(
            r'<time[^>]+datetime="([^"]+)"[^>]*>.*?'
            r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE
        )

        if not patron_msg:
            # Fallback: si no parsea bien, buscar timestamps sueltos
            log("  [AVC]   Sin mensajes parseables — revisando HTML completo (ultimas 48h)")
            # Buscar si hay fechas recientes en el HTML antes de analizar keywords
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
            if not hay_reciente:
                log("  [AVC]   No hay mensajes recientes (48h) — ignorando historial")
                return False, ""
            # Hay mensajes recientes: analizar solo el bloque final del HTML
            html_reciente = html[-8000:]  # ultimos ~8KB donde están los mensajes nuevos
        else:
            # Filtrar solo mensajes de las últimas 48h
            html_reciente = ""
            for ts_str, texto in patron_msg:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= limite:
                        html_reciente += " " + texto
                except Exception:
                    pass

            if not html_reciente.strip():
                log("  [AVC]   Sin mensajes nuevos en 48h")
                return False, ""

        # Buscar keywords solo en mensajes recientes
        bloque = html_reciente.upper()
        tiene_tramite = any(kw in bloque for kw in keywords_tramite)
        tiene_alerta  = any(a in bloque for a in AVC_ALERTAS)

        if tiene_tramite and tiene_alerta:
            fragmento = re.sub(r'<[^>]+>', '', html_reciente)[:300].strip()
            return True, fragmento

        return False, ""

    except Exception as e:
        log(f"⚠️  Error al leer canal AVC: {e}")
        return False, ""


# ─── Monitor sitio oficial ────────────────────────────────────────────────────

def verificar_disponibilidad(_page=None) -> bool:
    """
    Retorna True si HAY disponibilidad en el sitio bookitit.
    Usa Playwright headless para ejecutar el JavaScript del widget.
    Solo declara disponibilidad si el widget cargo Y no muestra bloqueo.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="es-ES",
            )
            page = ctx.new_page()
            try:
                # Paso 1: handshake en la página principal para obtener cookie de sesión
                page.goto("https://www.citaconsular.es", timeout=30000, wait_until="domcontentloaded")
                try:
                    page.click("button:has-text('Aceptar'), button:has-text('Accept'), button:has-text('Entrar')", timeout=5000)
                except Exception:
                    pass  # No hay botón o ya está aceptado
                # Paso 2: navegar al widget con la cookie ya establecida
                page.goto(URL_SISTEMA, timeout=35000, wait_until="domcontentloaded")

                # Esperar carga del widget — selectores CSS válidos únicamente
                try:
                    page.wait_for_selector(
                        "#bk-widget, #bookitit-widget, .bk-container, #datetime",
                        timeout=30000,
                    )
                except PlaywrightTimeout:
                    pass  # Si no aparece CSS, igual leemos el contenido
                contenido = page.content()

                if TEXTO_BLOQUEADO in contenido:
                    return False  # Bloqueado explícitamente

                # Verificar que el widget SÍ cargo (no página en blanco)
                indicadores_widget = [
                    "bookitit", "bk-widget", "datetime",
                    "Selecciona", "Confirmar", "horas",
                ]
                widget_cargado = any(ind in contenido for ind in indicadores_widget)
                if not widget_cargado:
                    log("[SITIO] Pagina cargada pero widget vacio — posible caida del sitio")
                    return False

                return True  # Widget cargo, no hay bloqueo → HAY DISPONIBILIDAD

            except PlaywrightTimeout:
                log("[SITIO] Widget no cargo en 30s — sitio caido o sin conexion")
                return False
            finally:
                browser.close()
    except Exception as e:
        log(f"[SITIO] Error Playwright: {e}")
        return False


# ─── Acciones de alerta ───────────────────────────────────────────────────────

def ejecutar_alerta(origen: str, detalle: str = ""):
    """Ejecuta la secuencia completa de alerta: sonido + Telegram + Chrome."""
    hora = datetime.now().strftime("%H:%M:%S del %d/%m/%Y")

    log(f"🎯 ══════════════════════════════════════════")
    log(f"🎯  ¡CITA DISPONIBLE DETECTADA! [{origen}]")
    log(f"🎯  Hora: {hora}")
    log(f"🎯 ══════════════════════════════════════════")

    # 1. Alarma sonora
    alarma_sonora()

    # 2. Telegram
    if origen == "AVC":
        cuerpo = (
            f"📣 <b>ALERTA TEMPRANA — Canal AVC</b>\n"
            f"Trámite: <b>{AVC_TRAMITE}</b>\n"
            f"Detectado: {hora}\n\n"
            f"<i>{detalle[:200]}</i>\n\n"
            f"👉 Vigila el sitio oficial ahora:\n{URL_SISTEMA}"
        )
    else:
        cuerpo = (
            f"🚨 <b>¡CITA DISPONIBLE — Sitio Oficial!</b>\n"
            f"Consulado España · La Habana\n"
            f"Detectado: {hora}\n\n"
            f"⚠️ Ingresa TÚ las credenciales y resuelve el captcha\n"
            f"🔗 {URL_SISTEMA}"
        )

    # 2b. Ráfaga — repite la alarma cada 90s hasta 6 veces (9 minutos en total)
    # El usuario DEBE reaccionar — múltiples notificaciones sonoras en el celular
    rafaga_alerta(cuerpo, repeticiones=8, intervalo_seg=30)

    # 3. Chrome incógnito — solo si es disponibilidad REAL en el sitio oficial
    if origen == "SITIO":
        abrir_chrome_incognito(URL_SISTEMA)
        log("⛔ STOP — Ingresa USUARIO_CI y PASSWORD_CITA manualmente.")
        log("   Resuelve el hCaptcha y pulsa Confirmar.")
        log("   ⚠️  La cita NO admite cancelación ni modificación.")


# ─── Loop principal ───────────────────────────────────────────────────────────

def monitor_loop():
    if not URL_SISTEMA:
        log("❌ URL_SISTEMA no definida en .env — abortando")
        sys.exit(1)

    telegram_ok = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

    log("=" * 64)
    log("  OVC-X — Orquestador de Vigilancia Consular   INICIADO")
    log(f"  URL sitio : {URL_SISTEMA}")
    log(f"  Monitor AVC: {AVC_TRAMITE}  ({URL_AVC})")
    log(f"  Telegram   : {'✅ configurado' if telegram_ok else '⚠️  NO configurado'}")
    log(f"  Intervalo  : {INTERVALO_MIN // 60} a {INTERVALO_MAX // 60} min (anti-deteccion)")
    log("  Ctrl+C para detener")
    log("=" * 64)

    ultimo_avc = datetime.min       # Para no spam-alertar por tiempo
    ultimo_avc_hash = ""            # Para no alertar sobre el mismo contenido

    ciclo = 0
    while True:
        ciclo += 1
        log(f"[Ciclo #{ciclo:03d}] -----------------------------------------")

        # ── 1. Verificar disponibilidad real en sitio oficial ─────────────
        log("  [SITIO] Verificando citaconsular.es...")
        if verificar_disponibilidad():
            ejecutar_alerta("SITIO")
            break  # Detener: el usuario toma control

        log("  [SITIO] Sin disponibilidad")

        # ── 2. Verificar canal AVC (alerta anticipada) ────────────────────
        log(f"  [AVC]   Revisando canal (tramite: {AVC_TRAMITE})...")
        hay_alerta_avc, detalle_avc = revisar_canal_avc()

        if hay_alerta_avc:
            hash_actual = hashlib.md5(detalle_avc.encode()).hexdigest()
            if hash_actual != ultimo_avc_hash:
                log("  [AVC]   Mensaje NUEVO relevante detectado!")
                ejecutar_alerta("AVC", detalle_avc)
                ultimo_avc = datetime.now()
                ultimo_avc_hash = hash_actual
            else:
                log("  [AVC]   Mismo mensaje ya alertado — ignorando")
        else:
            log("  [AVC]   Sin novedad")

        # ── 3. Espera aleatoria anti-detección ────────────────────────────
        intervalo = random.randint(INTERVALO_MIN, INTERVALO_MAX)
        proxima = datetime.fromtimestamp(time.time() + intervalo).strftime("%H:%M:%S")
        log(f"  Proxima revision a las {proxima} ({intervalo // 60}m {intervalo % 60}s)\n")
        time.sleep(intervalo)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        log("\n⏹  Monitor detenido por el usuario.")
        sys.exit(0)
