#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_admin.py — Comandos exclusivos del administrador.

Acceso: solo el Telegram ID configurado en ADMIN_TELEGRAM_ID.
El admin NO necesita acceso al código, GitHub ni Supabase.
Toda gestión es via Telegram.

Comandos:
  /admin_stats              → Resumen general (usuarios, ingresos, planes)
  /admin_listar             → Lista suscriptores activos (paginada)
  /admin_activar @u plan dias → Activa suscripción manual
  /admin_desactivar @u      → Desactiva suscripción
  /admin_expiran [dias]     → Lista suscripciones próximas a vencer
  /admin_broadcast <msg>    → Envía mensaje a todos los suscriptores activos
  /admin_audit              → Últimas 10 acciones del admin
"""

import os
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from core.logger import info, warn, error
from db.usuarios import (
    obtener_usuario, desactivar_usuario,
    contar_usuarios_por_plan, total_usuarios
)
from db.suscripciones import (
    activar_suscripcion, listar_activas,
    listar_por_expirar, contar_por_plan, ingresos_estimados
)
from db.connection import get_conn


# ── Guard de acceso ────────────────────────────────────────────────────────────

ADMIN_IDS = set()

def _cargar_admin_ids():
    """Carga IDs de admin desde variable de entorno. Soporta múltiples IDs separados por coma."""
    raw = os.getenv("ADMIN_TELEGRAM_ID", "")
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def es_admin(update: Update) -> bool:
    """Verifica si el usuario es admin. Recarga IDs cada vez (cambios sin reinicio)."""
    admin_ids = _cargar_admin_ids()
    uid = update.effective_user.id
    if uid not in admin_ids:
        warn(f"[ADMIN] Acceso denegado a comando admin — id=***")
        return False
    return True


async def _denegar(update: Update):
    await update.message.reply_text("⛔ Acceso restringido.")


def _registrar_audit(admin_id: int, comando: str, detalle: str = ""):
    """Registra cada acción del admin en la tabla admin_audit."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO admin_audit (admin_telegram_id, comando, detalle)
                       VALUES (%s, %s, %s);""",
                    (admin_id, comando, detalle[:500])
                )
    except Exception as e:
        error(f"[ADMIN] Error en audit log", exc=e)


# ── /admin_stats ───────────────────────────────────────────────────────────────

async def cmd_admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return await _denegar(update)

    por_plan   = contar_por_plan()
    total      = total_usuarios()
    ingresos   = ingresos_estimados()
    x_plan_u   = contar_usuarios_por_plan()
    expiran_7d = len(listar_por_expirar(7))

    directo  = por_plan.get("directo",  0)
    premium  = por_plan.get("premium",  0)
    free_u   = x_plan_u.get("free",     0)
    total_act = directo + premium

    msg = (
        f"📊 *OVC — Estadísticas*\n"
        f"────────────────────\n"
        f"👥 Usuarios totales:     {total}\n"
        f"✅ Suscripciones activas: {total_act}\n"
        f"  ├── Plan Directo:    {directo}\n"
        f"  └── Plan Premium:   {premium}\n"
        f"🆓 Plan Gratuito:        {free_u}\n\n"
        f"💰 Ingresos este mes:   ${ingresos:.2f} USD\n"
        f"⚠️  Vencen en 7 días:    {expiran_7d}\n"
        f"────────────────────\n"
        f"_Generado: {(datetime.now(timezone.utc) - timedelta(hours=4)).strftime('%d/%m/%Y %I:%M %p')} (Miami)_"
    )
    _registrar_audit(update.effective_user.id, "/admin_stats")
    await update.message.reply_text(msg, parse_mode="Markdown")


# ── /admin_listar ──────────────────────────────────────────────────────────────

async def cmd_admin_listar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not es_admin(update):
        return await _denegar(update)

    activas = listar_activas(limit=30)
    if not activas:
        await update.message.reply_text("No hay suscripciones activas.")
        return

    lineas = ["*Suscripciones activas:*\n"]
    for s in activas:
        user  = f"@{s['telegram_user']}" if s.get("telegram_user") else "(sin @)"
        plan  = s.get("plan", "?").capitalize()
        exp   = s["fecha_expira"].strftime("%d/%m/%Y") if s.get("fecha_expira") else "N/A"
        lineas.append(f"• {user} — {plan} — vence {exp}")

    _registrar_audit(update.effective_user.id, "/admin_listar")
    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")


# ── /admin_activar ─────────────────────────────────────────────────────────────

async def cmd_admin_activar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Uso: /admin_activar @username plan dias [precio] [metodo]
    Ej:  /admin_activar @juanito directo 90 15 zelle
    """
    if not es_admin(update):
        return await _denegar(update)

    args = ctx.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "⚠️ Uso: `/admin_activar @username plan dias [precio] [metodo]`\n"
            "Ejemplo: `/admin_activar @juanito directo 90 15 zelle`",
            parse_mode="Markdown"
        )
        return

    username_raw = args[0].lstrip("@")
    plan         = args[1].lower()
    dias_str     = args[2]
    precio_str   = args[3] if len(args) > 3 else None
    metodo       = args[4] if len(args) > 4 else "manual"

    # Validar días
    if not dias_str.isdigit():
        await update.message.reply_text("⚠️ Los días deben ser un número. Ej: 90")
        return

    dias   = int(dias_str)
    precio = float(precio_str) if precio_str and precio_str.replace(".", "").isdigit() else None

    # Buscar usuario por username en DB
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT telegram_id FROM usuarios WHERE telegram_user = %s AND activo = true;",
                (username_raw,)
            )
            row = cur.fetchone()

    if not row:
        await update.message.reply_text(
            f"⚠️ Usuario @{username_raw} no encontrado o no registrado en el bot."
        )
        return

    resultado = activar_suscripcion(
        telegram_id  = row["telegram_id"],
        plan         = plan,
        dias         = dias,
        precio_usd   = precio,
        metodo_pago  = metodo,
        activado_por = update.effective_user.id,
    )

    if resultado:
        expira = resultado["fecha_expira"].strftime("%d/%m/%Y")
        await update.message.reply_text(
            f"✅ @{username_raw} activado — Plan *{plan.capitalize()}* hasta {expira}",
            parse_mode="Markdown"
        )
        _registrar_audit(
            update.effective_user.id,
            "/admin_activar",
            f"@{username_raw} plan={plan} dias={dias} precio={precio} metodo={metodo}"
        )
        # Notificar al usuario
        try:
            plan_nombre = "Directo" if plan == "directo" else "Premium"
            await ctx.bot.send_message(
                chat_id=row["telegram_id"],
                text=(
                    f"🎉 *¡Tu plan está activo!*\n\n"
                    f"Plan: *{plan_nombre}*\n"
                    f"Válido hasta: {expira}\n\n"
                    f"A partir de ahora recibirás alertas directas cuando haya citas disponibles "
                    f"para tus trámites seleccionados.\n\n"
                    f"Usa /estado para ver tu suscripción."
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            warn(f"[ADMIN] No se pudo notificar al usuario", )
    else:
        await update.message.reply_text(f"❌ Error al activar. Plan inválido o usuario no existe.")


# ── /admin_desactivar ──────────────────────────────────────────────────────────

async def cmd_admin_desactivar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Uso: /admin_desactivar @username"""
    if not es_admin(update):
        return await _denegar(update)

    args = ctx.args or []
    if not args:
        await update.message.reply_text("Uso: /admin_desactivar @username")
        return

    username_raw = args[0].lstrip("@")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT telegram_id FROM usuarios WHERE telegram_user = %s;",
                (username_raw,)
            )
            row = cur.fetchone()

    if not row:
        await update.message.reply_text(f"⚠️ @{username_raw} no encontrado.")
        return

    desactivar_usuario(row["telegram_id"])

    # Desactivar también suscripciones
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE suscripciones SET activa = false
                   WHERE usuario_id = (SELECT id FROM usuarios WHERE telegram_id = %s);""",
                (row["telegram_id"],)
            )

    _registrar_audit(update.effective_user.id, "/admin_desactivar", f"@{username_raw}")
    await update.message.reply_text(f"🚫 @{username_raw} desactivado.")


# ── /admin_expiran ─────────────────────────────────────────────────────────────

async def cmd_admin_expiran(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Uso: /admin_expiran [dias] — default 7"""
    if not es_admin(update):
        return await _denegar(update)

    args  = ctx.args or []
    dias  = int(args[0]) if args and args[0].isdigit() else 7
    lista = listar_por_expirar(dias)

    if not lista:
        await update.message.reply_text(f"✅ Ninguna suscripción vence en los próximos {dias} días.")
        return

    lineas = [f"*Vencen en {dias} días:*\n"]
    for s in lista:
        user = f"@{s['telegram_user']}" if s.get("telegram_user") else "(sin @)"
        plan = s.get("plan", "?").capitalize()
        rest = s.get("dias_restantes", "?")
        exp  = s["fecha_expira"].strftime("%d/%m/%Y") if s.get("fecha_expira") else "N/A"
        lineas.append(f"• {user} — {plan} — {rest} días — vence {exp}")

    _registrar_audit(update.effective_user.id, "/admin_expiran", f"dias={dias}")
    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")


# ── /admin_broadcast ───────────────────────────────────────────────────────────

async def cmd_admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Uso: /admin_broadcast Mensaje a enviar a todos los suscriptores activos.
    Solo envía a usuarios con plan directo o premium activo.
    """
    if not es_admin(update):
        return await _denegar(update)

    texto = " ".join(ctx.args or []).strip()
    if not texto:
        await update.message.reply_text("Uso: /admin_broadcast <mensaje>")
        return

    activos = listar_activas(limit=500)
    if not activos:
        await update.message.reply_text("No hay suscriptores activos para enviar.")
        return

    enviados  = 0
    fallidos  = 0

    for s in activos:
        try:
            tid = s.get("telegram_id")
            if not tid:
                # Buscar desde DB
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT telegram_id FROM usuarios WHERE telegram_user = %s;",
                            (s.get("telegram_user"),)
                        )
                        row = cur.fetchone()
                if row:
                    tid = row["telegram_id"]

            if tid:
                await ctx.bot.send_message(
                    chat_id=tid,
                    text=f"📢 *Mensaje del administrador OVC:*\n\n{texto}",
                    parse_mode="Markdown"
                )
                enviados += 1
        except Exception:
            fallidos += 1

    _registrar_audit(
        update.effective_user.id,
        "/admin_broadcast",
        f"enviados={enviados} fallidos={fallidos} msg={texto[:100]}"
    )
    await update.message.reply_text(
        f"📤 Broadcast completado:\n✅ Enviados: {enviados}\n❌ Fallidos: {fallidos}"
    )


# ── /admin_audit ───────────────────────────────────────────────────────────────

async def cmd_admin_audit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra las últimas 15 acciones del admin."""
    if not es_admin(update):
        return await _denegar(update)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT comando, detalle, creado_en
                     FROM admin_audit
                    ORDER BY creado_en DESC
                    LIMIT 15;"""
            )
            rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("Sin acciones registradas.")
        return

    lineas = ["*Últimas acciones admin:*\n"]
    for r in rows:
        ts  = r["creado_en"].strftime("%d/%m %H:%M") if r.get("creado_en") else "?"
        cmd = r.get("comando", "?")
        det = r.get("detalle", "")[:60]
        lineas.append(f"`{ts}` {cmd} {det}")

    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")
