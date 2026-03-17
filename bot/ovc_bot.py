#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ovc_bot.py — Bot gestor de suscriptores OVC.

Arranque: python -X utf8 bot/ovc_bot.py

Variables de entorno requeridas:
  BOT_GESTOR_TOKEN      → Token del bot @ovc_gestor_bot
  ADMIN_TELEGRAM_ID     → ID Telegram del administrador (ej: 123456789)
  NEON_DATABASE_URL     → Connection string de Neon PostgreSQL

El bot corre en polling continuo. En producción se mantiene vivo
por GitHub Actions (ovc_bot.yml) o como proceso local.
"""

import os
import sys
import asyncio

# Asegurar que la raíz del proyecto esté en el path (necesario en Windows)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.logger import info, warn, error, critical
from bot.handlers_usuario import (
    cmd_start, cmd_servicios, cmd_pagar, cmd_estado, cmd_ayuda,
    cb_toggle_servicio, cb_guardar_servicios,
)
from bot.handlers_admin import (
    cmd_admin_stats, cmd_admin_listar, cmd_admin_activar,
    cmd_admin_desactivar, cmd_admin_expiran,
    cmd_admin_broadcast, cmd_admin_audit,
)


def main():
    token = os.getenv("BOT_GESTOR_TOKEN", "").strip()
    if not token:
        critical("[BOT] BOT_GESTOR_TOKEN no configurado — imposible arrancar")
        sys.exit(1)

    if not os.getenv("ADMIN_TELEGRAM_ID", "").strip():
        warn("[BOT] ADMIN_TELEGRAM_ID no configurado — comandos admin deshabilitados")

    neon_url = os.getenv("NEON_DATABASE_URL", "").strip()
    if not neon_url:
        critical("[BOT] NEON_DATABASE_URL no configurado — sin base de datos")
        sys.exit(1)

    info("[BOT] Arrancando OVC Gestor Bot...")

    app = Application.builder().token(token).build()

    # ── Comandos de usuario ──────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("servicios", cmd_servicios))
    app.add_handler(CommandHandler("pagar",     cmd_pagar))
    app.add_handler(CommandHandler("estado",    cmd_estado))
    app.add_handler(CommandHandler("ayuda",     cmd_ayuda))
    app.add_handler(CommandHandler("help",      cmd_ayuda))

    # ── Callbacks de botones inline ──────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_toggle_servicio,  pattern=r"^toggle_"))
    app.add_handler(CallbackQueryHandler(cb_guardar_servicios, pattern=r"^guardar_servicios$"))

    # ── Comandos de admin ────────────────────────────────────────────────────
    app.add_handler(CommandHandler("admin_stats",       cmd_admin_stats))
    app.add_handler(CommandHandler("admin_listar",      cmd_admin_listar))
    app.add_handler(CommandHandler("admin_activar",     cmd_admin_activar))
    app.add_handler(CommandHandler("admin_desactivar",  cmd_admin_desactivar))
    app.add_handler(CommandHandler("admin_expiran",     cmd_admin_expiran))
    app.add_handler(CommandHandler("admin_broadcast",   cmd_admin_broadcast))
    app.add_handler(CommandHandler("admin_audit",       cmd_admin_audit))

    info("[BOT] Handlers registrados — iniciando polling...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
