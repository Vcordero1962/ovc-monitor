#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram.py — Módulo de comunicación con Telegram para OVC.

Funciones públicas:
  send_text(msg, url_boton)            → alerta de texto al grupo
  send_photo(caption, bytes, url_boton)→ foto al grupo (fallback a texto)
  send_admin(msg, url_boton, silent)   → mensaje al admin
  send_status(...)                     → confirmación silenciosa de run
  generar_card(tipo, nombre, hora, det)→ imagen PNG branded (PIL)
"""

import json
import requests

from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_CHAT_ID
from core.logger import info, warn, error
from core.security import validate_telegram_creds

_TG_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# ── Helpers internos ───────────────────────────────────────────────────────────

def _creds_ok() -> bool:
    """Valida credenciales antes de cada envío. Loguea si hay problema."""
    valido, motivo = validate_telegram_creds()
    if not valido:
        error(f"Telegram: credenciales inválidas — {motivo}")
    return valido


def _post(endpoint: str, **kwargs) -> bool:
    """POST a la API de Telegram. Retorna True si HTTP 200 OK."""
    try:
        r = requests.post(f"{_TG_BASE}/{endpoint}", timeout=12, **kwargs)
        if not r.ok:
            error(f"Telegram/{endpoint}: HTTP {r.status_code} — {r.text[:120]}")
        return r.ok
    except Exception as e:
        error(f"Telegram/{endpoint}: excepción de red — {e}", exc=e)
        return False


def _build_keyboard(url_sitio: str) -> list:
    """Construye inline keyboard con botón RESERVAR (solo si hay URL)."""
    teclado = []
    if url_sitio:
        teclado.append([{"text": "🔴🔴  RESERVAR CITA — ENTRA YA  🔴🔴", "url": url_sitio}])
    return teclado


# ── Funciones públicas ─────────────────────────────────────────────────────────

def send_text(msg: str, url_boton: str = "") -> bool:
    """Envía mensaje de texto al grupo con botón RESERVAR CITA."""
    if not _creds_ok() or not TELEGRAM_CHAT_ID:
        return False
    ok = _post("sendMessage", json={
        "chat_id":      TELEGRAM_CHAT_ID,
        "text":         msg,
        "parse_mode":   "HTML",
        "reply_markup": {"inline_keyboard": _build_keyboard(url_boton)},
    })
    info(f"send_text → grupo: {'OK' if ok else 'FALLÓ'}")
    return ok


def send_photo(caption: str, foto_bytes: bytes, url_boton: str = "") -> bool:
    """
    Envía foto + caption al grupo.
    Si el envío de foto falla → fallback automático a send_text.
    """
    if not _creds_ok() or not TELEGRAM_CHAT_ID:
        return False

    ok = _post("sendPhoto",
        data={
            "chat_id":      TELEGRAM_CHAT_ID,
            "caption":      caption,
            "parse_mode":   "HTML",
            "reply_markup": json.dumps({"inline_keyboard": _build_keyboard(url_boton)}),
        },
        files={"photo": ("alerta.png", foto_bytes, "image/png")},
    )

    if ok:
        info("send_photo → grupo: OK")
        return True

    warn("send_photo falló — fallback a texto plano")
    return send_text(caption, url_boton)


def send_admin(msg: str, url_boton: str = "", silencioso: bool = False) -> bool:
    """
    Envía mensaje al chat personal del admin (ADMIN_CHAT_ID).

    silencioso=False → suena en el teléfono (cita confirmada)
    silencioso=True  → llega sin sonido (alerta temprana / status)
    """
    if not _creds_ok() or not ADMIN_CHAT_ID:
        return False

    payload: dict = {
        "chat_id":              ADMIN_CHAT_ID,
        "text":                 msg,
        "parse_mode":           "HTML",
        "disable_notification": silencioso,
    }
    if url_boton:
        payload["reply_markup"] = {
            "inline_keyboard": [[{
                "text": "🔴🔴  RESERVAR CITA — ENTRA YA  🔴🔴",
                "url":  url_boton,
            }]]
        }

    modo = "silencioso" if silencioso else "con sonido"
    ok = _post("sendMessage", json=payload)
    info(f"send_admin ({modo}): {'OK' if ok else 'FALLÓ'}")
    return ok


def send_status(
    hora: str,
    tramites: list,
    hits_sitio: list,
    hits_bkt: list,
    sitio_enabled: bool,
    bkt_enabled: bool,
) -> bool:
    """
    Envía confirmación silenciosa de run al admin.
    Permite verificar que el bot está vivo sin esperar una cita real.
    """
    if not _creds_ok() or not ADMIN_CHAT_ID:
        return False

    sitio_txt = "omitido" if not sitio_enabled else ("🚨 CITA" if hits_sitio else "✅ sin citas")
    bkt_txt   = "omitido" if not bkt_enabled   else ("🚨 CITA" if hits_bkt   else "✅ sin citas")

    msg = (
        f"🤖 <b>OVC — run completado</b>\n"
        f"⏰ {hora}\n\n"
        f"🌐 Sitio oficial: {sitio_txt}\n"
        f"📡 Bookitit POST: {bkt_txt}\n\n"
        f"<i>Servicios: {', '.join(tramites)}</i>"
    )
    ok = _post("sendMessage", json={
        "chat_id":              ADMIN_CHAT_ID,
        "text":                 msg,
        "parse_mode":           "HTML",
        "disable_notification": True,
    })
    info(f"send_status → admin: {'OK' if ok else 'FALLÓ'}")
    return ok


# ── Card visual PIL ────────────────────────────────────────────────────────────

def generar_card(tipo: str, nombre: str, hora: str, detalle: str = "") -> bytes | None:
    """
    Genera imagen PNG branded para alertas de cita disponible.
    Retorna bytes PNG o None si Pillow no está disponible.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        W, H = 800, 420

        bg_top    = (120, 0, 0)
        bg_bottom = (60, 0, 0)
        accent    = (255, 60, 60)
        header    = "!! CITA DISPONIBLE AHORA"
        cta_color = (255, 210, 210)
        cta_texto = "Tienes ~2 minutos. Entra YA y completa el captcha."

        img  = Image.new("RGB", (W, H), bg_top)
        draw = ImageDraw.Draw(img)

        # Gradiente vertical
        for y in range(H):
            r = bg_top[0] + int((bg_bottom[0] - bg_top[0]) * y / H)
            g = bg_top[1] + int((bg_bottom[1] - bg_top[1]) * y / H)
            b = bg_top[2] + int((bg_bottom[2] - bg_top[2]) * y / H)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        FONT_PATHS = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]

        def _font(size: int):
            for p in FONT_PATHS:
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
            try:
                return ImageFont.load_default(size=size)
            except Exception:
                return ImageFont.load_default()

        draw.rectangle([(0, 0), (W, 8)], fill=accent)
        draw.text((40, 24),  header, fill=accent,         font=_font(34))
        draw.line([(40, 86), (W - 40, 86)], fill=accent,  width=2)
        draw.text((40, 100), nombre, fill=(255, 255, 255), font=_font(46))
        draw.text((40, 165), f"Detectado: {hora}", fill=(190, 190, 190), font=_font(26))
        draw.line([(40, 210), (W - 40, 210)], fill=(90, 90, 90), width=1)
        draw.text((40, 228), cta_texto, fill=cta_color, font=_font(30))

        if detalle:
            txt = detalle[:90] + ("..." if len(detalle) > 90 else "")
            draw.text((40, 278), txt, fill=(160, 160, 160), font=_font(20))

        draw.rectangle([(0, H - 48), (W, H)], fill=(15, 15, 15))
        draw.text(
            (40, H - 34),
            "OVC  Monitor Consular 24/7  |  Verificacion automatica cada 7 min",
            fill=(120, 120, 120), font=_font(18),
        )
        draw.rectangle([(0, H - 4), (W, H)], fill=accent)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    except Exception as e:
        warn(f"generar_card PIL: error — {e}")
        return None
