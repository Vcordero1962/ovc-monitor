#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watermark.py — Watermark invisible por suscriptor en alertas DM.

Método: Unicode zero-width characters (ZWJ, ZWNJ, ZWS).
- Invisibles en Telegram, WhatsApp, pantalla normal.
- Detectables extrayendo caracteres especiales del texto.
- Cada suscriptor recibe una firma única basada en su ID.

Uso:
    from core.watermark import aplicar, detectar

    msg_firmado = aplicar("Texto alerta", telegram_id=123456789)
    id_detectado = detectar(msg_capturado)  # → 123456789 o None
"""

import hashlib
from core.logger import info, warn

# Caracteres zero-width invisibles
_ZWJ   = "\u200d"  # Zero Width Joiner
_ZWNJ  = "\u200c"  # Zero Width Non-Joiner
_ZWS   = "\u200b"  # Zero Width Space
_SEP   = "\u2060"  # Word Joiner (separador de bloques)

# Cabecera y cola de la firma (delimitadores)
_INICIO = "\u200d\u2060"
_FIN    = "\u2060\u200d"


def _id_a_bits(telegram_id: int, bits: int = 20) -> str:
    """
    Convierte telegram_id a secuencia de bits usando HMAC-SHA256
    con un salt fijo interno. Los primeros N bits del hash.
    El salt nunca sale del código — sin él el watermark no es recuperable.
    """
    _SALT = "OVC-WM-2026-SALT-INMUTABLE"
    h = hashlib.sha256(f"{_SALT}:{telegram_id}".encode()).hexdigest()
    # Convertir hex a binario, tomar los primeros `bits` bits
    n = int(h, 16)
    return format(n, f"0{bits}b")[:bits]


def _bits_a_zwc(bits: str) -> str:
    """Convierte '0' → ZWJ, '1' → ZWNJ, separados por ZWS."""
    chars = []
    for b in bits:
        chars.append(_ZWJ if b == "0" else _ZWNJ)
        chars.append(_ZWS)
    return "".join(chars)


def _zwc_a_bits(texto: str) -> str:
    """Extrae la secuencia de bits de caracteres zero-width."""
    bits = []
    for ch in texto:
        if ch == _ZWJ:
            bits.append("0")
        elif ch == _ZWNJ:
            bits.append("1")
        # ZWS y SEP son ignorados
    return "".join(bits)


def aplicar(mensaje: str, telegram_id: int) -> str:
    """
    Inserta el watermark del suscriptor al final del mensaje.
    El mensaje aparece idéntico visualmente.
    """
    bits   = _id_a_bits(telegram_id)
    firma  = _INICIO + _bits_a_zwc(bits) + _FIN
    return mensaje + firma


def detectar(mensaje_filtrado: str) -> int | None:
    """
    Intenta recuperar el telegram_id del suscriptor que filtró el mensaje.
    Retorna el ID si la firma es reconocible, None si no hay watermark.

    NOTA: Requiere buscar en la DB todos los suscriptores y comparar
    su firma esperada con la encontrada en el mensaje.
    Usar detectar_desde_db() para búsqueda automática.
    """
    if _INICIO not in mensaje_filtrado or _FIN not in mensaje_filtrado:
        return None

    start = mensaje_filtrado.index(_INICIO) + len(_INICIO)
    end   = mensaje_filtrado.index(_FIN)
    fragmento = mensaje_filtrado[start:end]
    bits_encontrados = _zwc_a_bits(fragmento)

    if not bits_encontrados:
        warn("[WM] Watermark detectado pero sin bits recuperables")
        return None

    return bits_encontrados   # Retorna bits raw — comparar con DB


def detectar_desde_db(mensaje_filtrado: str) -> int | None:
    """
    Versión completa: busca en la DB el suscriptor cuya firma
    coincide con el watermark del mensaje.
    Retorna telegram_id o None.
    """
    bits_msg = detectar(mensaje_filtrado)
    if not bits_msg:
        return None

    try:
        from db.connection import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT telegram_id FROM usuarios WHERE activo = true;")
                rows = cur.fetchall()

        for row in rows:
            tid = row["telegram_id"]
            bits_esperados = _id_a_bits(tid)
            if bits_esperados == bits_msg:
                info(f"[WM] Filtración detectada — suscriptor identificado")
                _registrar_filtracion(tid, mensaje_filtrado[:200])
                return tid

    except Exception as e:
        warn(f"[WM] Error buscando watermark en DB: {e}")

    warn("[WM] Watermark presente pero suscriptor no identificado en DB")
    return None


def _registrar_filtracion(telegram_id: int, fragmento: str):
    """Registra la filtración en la tabla watermarks."""
    try:
        from db.connection import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO watermarks (telegram_id, tipo, fragmento)
                       VALUES (%s, 'filtracion_detectada', %s)
                       ON CONFLICT DO NOTHING;""",
                    (telegram_id, fragmento)
                )
    except Exception as e:
        warn(f"[WM] Error registrando filtración: {e}")
