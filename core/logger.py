#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
logger.py — Logger estructurado con niveles para OVC.

Niveles:
  INFO     → flujo normal (stdout)
  WARN     → degradación no crítica (stdout)
  ERROR    → fallo recuperable (stderr + traceback si se pasa exc=)
  CRITICAL → fallo fatal, el bot debe parar (stderr + traceback)

Uso:
    from core.logger import info, warn, error, critical

    info("BKT GET: 200 — 1334 chars")
    warn("Token llegó tarde — GitHub throttle")
    error("Playwright timeout", exc=e)
    critical("TELEGRAM_BOT_TOKEN vacío — imposible alertar")
"""

import sys
import traceback
from datetime import datetime

# ── Niveles ────────────────────────────────────────────────────────────────────
INFO     = "INFO"
WARN     = "WARN"
ERROR    = "ERROR"
CRITICAL = "CRIT"   # 4 chars → columna alineada

_NIVEL_ANCHO = 4   # todos los niveles tienen <= 4 chars


def log(nivel: str, msg: str, exc: Exception = None):
    """
    Emite una línea de log formateada.

    Formato: [HH:MM:SS] [NIVEL] mensaje
    Si exc != None y nivel en (ERROR, CRITICAL): imprime traceback completo a stderr.
    """
    ts       = datetime.now().strftime("%H:%M:%S")
    nivel_s  = nivel.ljust(_NIVEL_ANCHO)
    linea    = f"[{ts}] [{nivel_s}] {msg}"
    es_error = nivel in (ERROR, CRITICAL)
    dest     = sys.stderr if es_error else sys.stdout

    print(linea, flush=True, file=dest)

    if exc is not None and es_error:
        tb = traceback.format_exc()
        if tb and tb.strip() != "NoneType: None":
            print(f"[{ts}] [{nivel_s}] TRACEBACK:\n{tb}", flush=True, file=sys.stderr)


# ── Shortcuts ──────────────────────────────────────────────────────────────────

def info(msg: str):
    log(INFO, msg)


def warn(msg: str, exc: Exception = None):
    log(WARN, msg, exc)


def error(msg: str, exc: Exception = None):
    log(ERROR, msg, exc)


def critical(msg: str, exc: Exception = None):
    log(CRITICAL, msg, exc)
