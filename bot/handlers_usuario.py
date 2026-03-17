#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_usuario.py — Comandos del bot para usuarios finales.

Comandos disponibles:
  /start      → Registro / bienvenida
  /servicios  → Seleccionar qué trámites vigilar
  /pagar      → Ver instrucciones de pago
  /estado     → Ver plan activo y fecha de vencimiento
  /ayuda      → Lista de comandos
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core.config import SERVICIOS
from core.logger import info, warn
from db.usuarios import registrar_usuario, obtener_usuario, actualizar_servicios
from db.suscripciones import listar_activas


# ── Textos fijos ───────────────────────────────────────────────────────────────

BIENVENIDA = """
👋 *Bienvenido a OVC — Orquestador de Vigilancia Consular*

Monitoreo automático 24/7 del Consulado Español en La Habana.
Te aviso por Telegram en el momento en que aparezca una cita disponible.

*Planes disponibles:*
• *Gratuito* — Alertas en el canal público
• *Directo ($15)* — Alerta privada directa a tu Telegram con enlace exacto
• *Premium ($25)* — Todo lo anterior + prioridad en horas pico

Usa /servicios para elegir qué trámite vigilar.
Usa /pagar para activar tu plan.
Usa /estado para ver tu suscripción actual.
"""

AYUDA = """
*Comandos disponibles:*

/start       → Registro e información
/servicios   → Elegir trámite(s) a vigilar
/pagar       → Instrucciones de pago
/estado      → Ver tu plan y fecha de vencimiento
/ayuda       → Este mensaje
"""

SERVICIOS_NOMBRES = {
    "LEGA":       "📋 Legalización de Credenciales (LEGA)",
    "LMD":        "📄 Legalización de Matrimonio/Divorcio (LMD)",
    "PASAPORTE":  "🛂 Pasaporte español",
    "VISADO":     "✈️  Visado Schengen / Familiar / Residencia",
    "MATRIMONIO": "💍 Matrimonio en el consulado",
    "NACIMIENTO": "👶 Registro de nacimiento",
    "NOTARIAL":   "📜 Trámites notariales",
}


# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    registrar_usuario(
        telegram_id=u.id,
        telegram_user=u.username,
        nombre=u.full_name,
    )
    info(f"[BOT] /start — usuario registrado id=***")
    await update.message.reply_text(BIENVENIDA, parse_mode="Markdown")


# ── /servicios ─────────────────────────────────────────────────────────────────

async def cmd_servicios(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    usuario = obtener_usuario(u.id)

    if not usuario:
        await update.message.reply_text(
            "Primero escribe /start para registrarte.", parse_mode="Markdown"
        )
        return

    actuales = usuario.get("servicios") or []
    teclado = []

    for codigo, nombre in SERVICIOS_NOMBRES.items():
        marcado = "✅ " if codigo in actuales else ""
        teclado.append([InlineKeyboardButton(
            f"{marcado}{nombre}",
            callback_data=f"toggle_{codigo}"
        )])

    teclado.append([InlineKeyboardButton("💾 Guardar selección", callback_data="guardar_servicios")])

    markup = InlineKeyboardMarkup(teclado)
    await update.message.reply_text(
        "*¿Qué trámite(s) quieres vigilar?*\n"
        "Toca para seleccionar/deseleccionar:",
        reply_markup=markup,
        parse_mode="Markdown"
    )


async def cb_toggle_servicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback de los botones de selección de servicios."""
    query = update.callback_query
    await query.answer()

    u = query.from_user
    codigo = query.data.replace("toggle_", "")

    if codigo not in SERVICIOS:
        return

    usuario = obtener_usuario(u.id)
    actuales = list(usuario.get("servicios") or [])

    if codigo in actuales:
        actuales.remove(codigo)
    else:
        actuales.append(codigo)

    # Guardar temporalmente en contexto del usuario
    ctx.user_data["servicios_pendientes"] = actuales

    # Reconstruir teclado con estado actualizado
    teclado = []
    for cod, nombre in SERVICIOS_NOMBRES.items():
        marcado = "✅ " if cod in actuales else ""
        teclado.append([InlineKeyboardButton(
            f"{marcado}{nombre}",
            callback_data=f"toggle_{cod}"
        )])
    teclado.append([InlineKeyboardButton("💾 Guardar selección", callback_data="guardar_servicios")])

    await query.edit_message_reply_markup(InlineKeyboardMarkup(teclado))


async def cb_guardar_servicios(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Guarda la selección de servicios en la DB."""
    query = update.callback_query
    await query.answer()

    u = query.from_user
    seleccion = ctx.user_data.get("servicios_pendientes", [])

    if not seleccion:
        await query.edit_message_text("⚠️ No seleccionaste ningún trámite.")
        return

    actualizar_servicios(u.id, seleccion)
    nombres = [SERVICIOS_NOMBRES.get(s, s) for s in seleccion]
    lista = "\n".join(f"• {n}" for n in nombres)

    await query.edit_message_text(
        f"✅ *Guardado.* Vigilaré:\n{lista}\n\n"
        f"Usa /pagar para activar alertas directas.",
        parse_mode="Markdown"
    )
    info(f"[BOT] Servicios guardados para id=*** → {seleccion}")


# ── /pagar ─────────────────────────────────────────────────────────────────────

async def cmd_pagar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    usuario = obtener_usuario(u.id)

    if not usuario:
        await update.message.reply_text("Primero escribe /start para registrarte.")
        return

    if not usuario.get("servicios"):
        await update.message.reply_text(
            "⚠️ Primero elige los trámites con /servicios."
        )
        return

    servicios_sel = ", ".join(usuario.get("servicios") or [])

    msg = (
        f"💳 *Opciones de pago — OVC*\n\n"
        f"*Plan Directo* — $15 USD (90 días)\n"
        f"Alerta privada directa en Telegram con enlace exacto al widget de cita.\n\n"
        f"*Plan Premium* — $25 USD (90 días)\n"
        f"Todo lo anterior + prioridad en horas pico + notificaciones adicionales.\n\n"
        f"─────────────────────\n"
        f"*Trámites seleccionados:* {servicios_sel}\n\n"
        f"*Métodos de pago aceptados:*\n"
        f"• Zelle: `pagos@ovc-consulado.com`\n"
        f"• PayPal: `@ovc-consulado`\n\n"
        f"*Instrucciones:*\n"
        f"1️⃣ Realiza el pago por el monto del plan elegido\n"
        f"2️⃣ Toma una captura de pantalla del comprobante\n"
        f"3️⃣ Envíala al administrador para activar tu plan\n\n"
        f"_Tu suscripción se activa en menos de 24 horas._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ── /estado ────────────────────────────────────────────────────────────────────

async def cmd_estado(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    usuario = obtener_usuario(u.id)

    if not usuario:
        await update.message.reply_text("Escribe /start para registrarte.")
        return

    plan     = usuario.get("plan", "free")
    servicios = usuario.get("servicios") or []
    activo   = usuario.get("activo", True)

    if plan == "free":
        estado_txt = (
            "📋 *Tu plan actual:* Gratuito\n"
            "Recibes alertas generales del canal público.\n\n"
            "Usa /pagar para activar alertas directas."
        )
    else:
        # Buscar fecha de expiración
        activas = listar_activas()
        expira_txt = "N/A"
        for s in activas:
            if s.get("telegram_user") == u.username:
                if s.get("fecha_expira"):
                    expira_txt = s["fecha_expira"].strftime("%d/%m/%Y")
                break

        plan_nombre = "Directo" if plan == "directo" else "Premium"
        estado_txt = (
            f"✅ *Tu plan actual:* {plan_nombre}\n"
            f"📅 Vence: {expira_txt}\n\n"
        )

    servicios_txt = (
        "\n".join(f"• {SERVICIOS_NOMBRES.get(s, s)}" for s in servicios)
        if servicios else "Ninguno seleccionado — usa /servicios"
    )

    await update.message.reply_text(
        f"{estado_txt}\n*Trámites vigilados:*\n{servicios_txt}",
        parse_mode="Markdown"
    )


# ── /ayuda ─────────────────────────────────────────────────────────────────────

async def cmd_ayuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, parse_mode="Markdown")
