#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py — Fuente única de verdad para toda la configuración OVC.

Todos los demás módulos importan desde aquí.
NUNCA pongas os.getenv() fuera de este archivo.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")   # grupo — alertas de cita
ADMIN_CHAT_ID      = os.getenv("ADMIN_CHAT_ID",       "")   # chat personal admin

# ── URL legacy ─────────────────────────────────────────────────────────────────
URL_SISTEMA = os.getenv("URL_SISTEMA", "")   # alias de URL_LEGA (backwards compat)

# ── Flags de control ───────────────────────────────────────────────────────────
SITIO_DIRECTO_ENABLED    = os.getenv("SITIO_DIRECTO_ENABLED",    "1") == "1"
PLAYWRIGHT_PROXY_ENABLED = os.getenv("PLAYWRIGHT_PROXY_ENABLED", "0") == "1"
BOOKITIT_POST_ENABLED    = os.getenv("BOOKITIT_POST_ENABLED",    "1") == "1"
STATUS_CADA_RUN          = os.getenv("STATUS_CADA_RUN",          "1") == "1"
AVC_TRAMITE              = os.getenv("AVC_TRAMITE", "ALL").upper()
HTTP_PROXY_URL           = os.getenv("HTTP_PROXY_URL", "")
CF_WORKER_URL            = os.getenv("CF_WORKER_URL", "")      # https://ovc-relay.USUARIO.workers.dev
CF_WORKER_SECRET         = os.getenv("CF_WORKER_SECRET", "")   # valor de OVC_SECRET en CF dashboard
CF_WORKER_ENABLED        = os.getenv("CF_WORKER_ENABLED", "1") == "1"

# ── Perfil persistente de Chromium (anti-WAF) ──────────────────────────────────
_DEFAULT_PROFILE = Path.home() / ".config" / "chromium-ovc"
USER_DATA_DIR    = Path(os.getenv("CHROMIUM_PROFILE_DIR", str(_DEFAULT_PROFILE)))
SESSION_STAMP    = USER_DATA_DIR / "ovc_session.json"
SESSION_MAX_MIN  = 25   # tokens de citaconsular.es duran ~20-30 min

TEXTO_BLOQUEADO = "No hay horas disponibles"

# ── Catálogo de servicios consulares (Consulado de España en La Habana) ────────
SERVICIOS: dict = {
    "LEGA": {
        "nombre":   "Legalizaciones (LEGA)",
        "keywords": ["LEGALIZACI", "LEGALIZ", "LEGA"],
        "url_env":  "URL_LEGA",
    },
    "LMD": {
        "nombre":   "Ley Memoria Democratica (LMD)",
        "keywords": ["LMD", "MEMORIA DEMOCR", "CREDENCIALES LMD", "CIUDADAN"],
        "url_env":  "URL_LMD",
    },
    "PASAPORTE": {
        "nombre":   "Pasaporte / DNI",
        "keywords": ["PASAPORTE", "PASAPORTES", "DNI", "DOCUMENTO NACIONAL"],
        "url_env":  "URL_PASAPORTE",
    },
    "VISADO": {
        "nombre":   "Visados",
        "keywords": ["VISADO", "VISADOS", "VISA SCHENGEN", "VISA NACIONAL"],
        "url_env":  "URL_VISADO",
    },
    "MATRIMONIO": {
        "nombre":   "Matrimonio / Registro Civil",
        "keywords": ["MATRIMONIO", "TRANSCRIPCI", "REGISTRO CIVIL", "ACTA MATRIMON"],
        "url_env":  "URL_MATRIMONIO",
    },
    "NACIMIENTO": {
        "nombre":   "Nacimiento / Fe de Vida",
        "keywords": ["NACIMIENTO", "FE DE VIDA", "ACTA DE NACI", "ACTA NACIM"],
        "url_env":  "URL_NACIMIENTO",
    },
    "NOTARIAL": {
        "nombre":   "Tramites Notariales / Apostilla",
        "keywords": ["NOTARIAL", "APOSTILLA", "PODER NOTARIAL", "NOTARI"],
        "url_env":  "URL_NOTARIAL",
    },
}

# ── Pool de User-Agents (13 perfiles desktop + mobile) ─────────────────────────
USER_AGENTS: list = [
    # Desktop Chrome — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Desktop Chrome — Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Desktop Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Desktop Safari — Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    # Mobile Chrome — Android
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36",
    # Mobile Safari — iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
]

# ── Resoluciones (desktop + mobile) ────────────────────────────────────────────
VIEWPORTS: list = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1536, "height": 864},
    {"width": 390,  "height": 844},   # iPhone 14
    {"width": 412,  "height": 915},   # Pixel 7
]


def get_tramites_activos() -> list:
    """Retorna lista de códigos de tramite a vigilar según AVC_TRAMITE."""
    if AVC_TRAMITE == "ALL":
        return list(SERVICIOS.keys())
    tramites = [t.strip() for t in AVC_TRAMITE.split(",") if t.strip() in SERVICIOS]
    if not tramites:
        from core.logger import warn
        warn(f"AVC_TRAMITE='{AVC_TRAMITE}' no reconocido — usando ALL")
        return list(SERVICIOS.keys())
    return tramites


def get_url_for_tramite(tramite: str) -> str:
    """
    Retorna la URL del widget para un tramite.
    Fallback: si tramite==LEGA y URL_LEGA no está → usa URL_SISTEMA (legacy).
    """
    url = os.getenv(SERVICIOS[tramite]["url_env"], "").strip()
    if not url and tramite == "LEGA" and URL_SISTEMA:
        url = URL_SISTEMA
    return url
