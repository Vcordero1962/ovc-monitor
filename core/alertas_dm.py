#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alertas_dm.py — Envío de alertas privadas (DM) a suscriptores.

Reglas críticas:
- Las alertas NUNCA van a un canal público.
- Cada DM lleva watermark único del suscriptor.
- Solo suscriptores con plan activo y vigente reciben DM.
- El enlace al widget solo se incluye en planes Directo/Premium.
- Se registra cada alerta en alertas_log para no duplicar.
"""

import os
import time
import requests
from datetime import datetime, timezone
from core.logger import info, warn, error
from core.watermark import aplicar as aplicar_watermark
from db.usuarios import listar_suscriptores_para_tramite
from db.connection import get_conn

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_API = "https://api.telegram.org/bot"

# Mapa de nombres legibles por trámite
TRAMITE_NOMBRES = {
    "LEGA":       "Legalización de Credenciales",
    "LMD":        "Legalización Matrimonio/Divorcio",
    "PASAPORTE":  "Pasaporte Español",
    "VISADO":     "Visado Schengen / Familiar / Residencia",
    "MATRIMONIO": "Matrimonio Consular",
    "NACIMIENTO": "Registro de Nacimiento",
    "NOTARIAL":   "Trámites Notariales",
}


# ── Envío principal ────────────────────────────────────────────────────────────

def enviar_alerta_suscriptores(
    tramite: str,
    url_widget: str,
    fecha_detectada: str = None,
    detalles: str = "",
) -> dict:
    """
    Envía DM privado a todos los suscriptores activos del trámite detectado.

    Args:
        tramite:         Código del trámite (ej: 'LEGA', 'PASAPORTE')
        url_widget:      URL del widget de citaconsular.es
        fecha_detectada: Fecha/hora de detección (string legible)
        detalles:        Texto adicional detectado en la página

    Retorna: {'enviados': N, 'fallidos': N, 'omitidos': N}
    """
    if not TELEGRAM_BOT_TOKEN:
        error("[DM] TELEGRAM_BOT_TOKEN no configurado — imposible enviar DMs")
        return {"enviados": 0, "fallidos": 0, "omitidos": 0}

    # Verificar que no se haya enviado alerta reciente para este trámite (30 min)
    if _alerta_reciente(tramite, minutos=30):
        info(f"[DM] Alerta para {tramite} ya enviada en los últimos 30 min — omitida")
        return {"enviados": 0, "fallidos": 0, "omitidos": 1}

    suscriptores = listar_suscriptores_para_tramite(tramite)

    if not suscriptores:
        info(f"[DM] No hay suscriptores activos para {tramite}")
        return {"enviados": 0, "fallidos": 0, "omitidos": 0}

    nombre_tramite = TRAMITE_NOMBRES.get(tramite, tramite)
    hora_miami     = _hora_miami()
    enviados = fallidos = 0

    for sus in suscriptores:
        try:
            tid  = sus["telegram_id"]
            plan = sus.get("plan", "free")

            # Construir mensaje personalizado por plan
            mensaje = _construir_mensaje(
                nombre_tramite  = nombre_tramite,
                plan            = plan,
                url_widget      = url_widget,
                hora_detectada  = fecha_detectada or hora_miami,
                detalles        = detalles,
            )

            # Aplicar watermark único del suscriptor
            mensaje_firmado = aplicar_watermark(mensaje, telegram_id=tid)

            # Registrar watermark en DB antes de enviar
            _registrar_watermark(tid, tramite)

            # Enviar DM
            ok = _send_dm(tid, mensaje_firmado)

            if ok:
                enviados += 1
                info(f"[DM] Alerta enviada a suscriptor id=*** trámite={tramite}")
            else:
                fallidos += 1
                warn(f"[DM] Fallo al enviar DM a suscriptor id=***")

            time.sleep(0.1)   # Rate limit Telegram: max 30 msgs/seg

        except Exception as e:
            fallidos += 1
            error(f"[DM] Error procesando suscriptor", exc=e)

    # Registrar en alertas_log
    _registrar_alerta_log(tramite, enviados)

    info(f"[DM] {tramite}: {enviados} enviados, {fallidos} fallidos")
    return {"enviados": enviados, "fallidos": fallidos, "omitidos": 0}


# ── Construcción de mensajes ───────────────────────────────────────────────────

def _construir_mensaje(
    nombre_tramite: str,
    plan: str,
    url_widget: str,
    hora_detectada: str,
    detalles: str,
) -> str:
    """
    Construye el mensaje según el plan del suscriptor.
    Plan directo/premium: incluye URL exacta del widget.
    """
    base = (
        f"🚨 *CITA DISPONIBLE — OVC*\n\n"
        f"📋 Trámite: *{nombre_tramite}*\n"
        f"⏰ Detectado: {hora_detectada}\n"
    )

    if detalles:
        base += f"📝 Detalle: _{detalles}_\n"

    if plan in ("directo", "premium"):
        base += (
            f"\n🔗 *Reserva tu cita ahora:*\n"
            f"{url_widget}\n\n"
            f"⚡ _Actúa rápido — las citas se agotan en minutos._"
        )
    else:
        # Plan free no debería llegar aquí — solo precaución
        base += (
            f"\n_Para recibir el enlace directo, activa tu plan con /pagar_"
        )

    return base


# ── Helpers de Telegram ────────────────────────────────────────────────────────

def _send_dm(telegram_id: int, texto: str) -> bool:
    """Envía un DM silencioso al suscriptor."""
    url = f"{_TG_API}{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id":              telegram_id,
            "text":                 texto,
            "parse_mode":           "Markdown",
            "disable_notification": False,   # Alerta CON sonido — es urgente
        }, timeout=10)
        return r.status_code == 200 and r.json().get("ok", False)
    except Exception as e:
        warn(f"[DM] Error HTTP al enviar DM: {e}")
        return False


# ── Control de duplicados ──────────────────────────────────────────────────────

def _alerta_reciente(tramite: str, minutos: int = 30) -> bool:
    """Verifica si ya se envió una alerta para este trámite en los últimos N minutos."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) AS n FROM alertas_log
                       WHERE tramite = %s
                         AND creado_en > NOW() - (%s || ' minutes')::INTERVAL
                         AND usuarios_dm > 0;""",
                    (tramite, str(minutos))
                )
                row = cur.fetchone()
        return (row["n"] if row else 0) > 0
    except Exception as e:
        warn(f"[DM] Error verificando alerta reciente: {e}")
        return False


def _registrar_alerta_log(tramite: str, enviados: int):
    """Registra la alerta en alertas_log."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO alertas_log
                           (tramite, detectado_en, canal_publico, usuarios_dm)
                       VALUES (%s, NOW(), false, %s);""",
                    (tramite, enviados)
                )
    except Exception as e:
        warn(f"[DM] Error registrando alertas_log: {e}")


def _registrar_watermark(telegram_id: int, tramite: str):
    """Registra el watermark enviado para trazabilidad."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO watermarks (telegram_id, tipo, fragmento)
                       VALUES (%s, 'alerta_enviada', %s)
                       ON CONFLICT DO NOTHING;""",
                    (telegram_id, f"tramite={tramite}")
                )
    except Exception as e:
        warn(f"[DM] Error registrando watermark: {e}")


# ── Timezone Miami ─────────────────────────────────────────────────────────────

def _hora_miami() -> str:
    from datetime import timedelta
    miami = datetime.now(timezone.utc) - timedelta(hours=4)
    return miami.strftime("%I:%M %p del %d/%m/%Y (Miami)")
