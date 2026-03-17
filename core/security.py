#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
security.py — Validaciones anti-inyección para OVC.

Protecciones implementadas:
  1. validate_widget_url()      → solo acepta URLs de citaconsular.es con path de widget válido
  2. validate_imperva_token()   → valida charset, longitud y ausencia de payloads JS/HTML
  3. validate_telegram_creds()  → verifica formato del token de bot antes de usarlo
  4. sanitize_html_fragment()   → limpia HTML del canal AVC para uso seguro en mensajes

Por qué importa:
  El bot extrae un token de la respuesta GET de Imperva y lo reenvía en un POST.
  Si un atacante pudiera interceptar (MitM) o la respuesta contuviera un token
  manipulado, podría intentar inyectar contenido en el POST o en los mensajes
  de Telegram. Este módulo detiene esos vectores antes de que lleguen a la red.
"""

import re
import os
from urllib.parse import urlparse

from core.logger import warn, error

# ── Dominios permitidos para widgets ───────────────────────────────────────────
_DOMINIOS_PERMITIDOS = {
    "www.citaconsular.es",
    "citaconsular.es",
    "app.bookitit.com",   # Bookitit directo (bypass Imperva de citaconsular.es)
    "www.bookitit.com",
}

# ── Formato del token Imperva ──────────────────────────────────────────────────
# Imperva usa tokens hexadecimales o base64url, típicamente 32-512 chars.
# Charset: A-Z a-z 0-9 + / = _ -  (base64 estándar + base64url)
_TOKEN_REGEX   = re.compile(r'^[A-Za-z0-9+/=_\-]{8,512}$')
_TOKEN_MIN_LEN = 8
_TOKEN_MAX_LEN = 512

# ── Path esperado en URLs de widget ────────────────────────────────────────────
# Formato: /es/hosteds/widgetdefault/{PK}/  o  /{PK}/{SID}
# PK: 10-64 hex chars alfanuméricos
_WIDGET_PATH_RE = re.compile(
    r'^/es/hosteds/widgetdefault/[a-zA-Z0-9]{10,64}(/[a-zA-Z0-9]+)?/?$'
)

# ── Payloads peligrosos que NO deben aparecer en un token legítimo ──────────────
_TOKEN_PAYLOADS_PELIGROSOS = [
    "<script", "</script", "javascript:", "onerror=", "onload=",
    "eval(", "document.", "window.", "alert(", "fetch(", "xhr",
    "base64", "data:", "vbscript:",
]


class SecurityError(Exception):
    """Excepción de seguridad — detiene el procesamiento inmediatamente."""
    pass


# ── Validación de URL de widget ────────────────────────────────────────────────

def validate_widget_url(url: str) -> str:
    """
    Valida que una URL sea de citaconsular.es y tenga el path de widget esperado.

    Rechaza:
      - Dominios distintos a citaconsular.es
      - Esquemas que no sean https
      - Paths que no coincidan con /es/hosteds/widgetdefault/{PK}/

    Raises SecurityError si no pasa.
    Retorna la URL validada (stripped).
    """
    if not url or not url.strip():
        raise SecurityError("URL vacía")

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SecurityError(f"URL no parseable: {e}")

    # Esquema
    if parsed.scheme not in ("https", "http"):
        raise SecurityError(f"Esquema no permitido: {parsed.scheme!r}")

    if parsed.scheme != "https":
        raise SecurityError("URL debe usar HTTPS")

    # Dominio
    hostname = (parsed.hostname or "").lower().strip()
    if hostname not in _DOMINIOS_PERMITIDOS:
        raise SecurityError(
            f"Dominio no permitido: {hostname!r} — solo se aceptan: {_DOMINIOS_PERMITIDOS}"
        )

    # Path de widget
    path = parsed.path or ""
    if not _WIDGET_PATH_RE.match(path):
        raise SecurityError(
            f"Path no reconocido como widget: {path!r}\n"
            f"Esperado: /es/hosteds/widgetdefault/{{PK}}[/{{SID}}][/]"
        )

    return url


# ── Validación del token Imperva ───────────────────────────────────────────────

def validate_imperva_token(raw_token: str, source_url: str = "") -> str:
    """
    Valida el token Imperva extraído del GET antes de enviarlo en el POST.

    Rechaza:
      - Tokens vacíos o solo espacios
      - Tokens demasiado cortos (probablemente inválidos o truncados)
      - Tokens demasiado largos (posible payload malicioso)
      - Tokens con caracteres fuera del charset permitido
      - Tokens que contienen secuencias JS/HTML (inyección via respuesta)

    Raises SecurityError si no pasa.
    Retorna el token validado (stripped).
    """
    if not raw_token or not raw_token.strip():
        raise SecurityError("Token vacío o solo espacios")

    token = raw_token.strip()

    # Longitud
    if len(token) < _TOKEN_MIN_LEN:
        raise SecurityError(
            f"Token demasiado corto ({len(token)} chars, mínimo {_TOKEN_MIN_LEN})"
        )

    if len(token) > _TOKEN_MAX_LEN:
        raise SecurityError(
            f"Token demasiado largo ({len(token)} chars, máximo {_TOKEN_MAX_LEN}) — "
            f"posible payload malicioso"
        )

    # Charset
    if not _TOKEN_REGEX.match(token):
        chars_invalidos = sorted(set(c for c in token if not re.match(r'[A-Za-z0-9+/=_\-]', c)))
        raise SecurityError(
            f"Token con caracteres fuera del charset permitido: "
            f"{[repr(c) for c in chars_invalidos[:5]]} — posible inyección"
        )

    # Payloads peligrosos
    token_lower = token.lower()
    for payload in _TOKEN_PAYLOADS_PELIGROSOS:
        if payload in token_lower:
            raise SecurityError(
                f"Token contiene secuencia peligrosa: {payload!r} — "
                f"posible inyección via respuesta GET"
            )

    return token


# ── Validación de credenciales Telegram ───────────────────────────────────────

def validate_telegram_creds() -> tuple:
    """
    Verifica que TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID y ADMIN_CHAT_ID tengan
    el formato esperado por la API de Telegram.

    Retorna (valido: bool, motivo: str).
    No lanza excepción — el caller decide si abortar o continuar.
    """
    from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_CHAT_ID

    if not TELEGRAM_BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN vacío"

    # Formato del token de bot: {id_numerico}:{hash_alfanumerico}
    partes = TELEGRAM_BOT_TOKEN.split(":")
    if len(partes) != 2:
        return False, (
            f"TELEGRAM_BOT_TOKEN formato inválido — "
            f"esperado {{id}}:{{hash}}, encontrado {len(partes)} parte(s)"
        )

    bot_id, bot_hash = partes

    if not bot_id.isdigit():
        return False, f"TELEGRAM_BOT_TOKEN: ID no es numérico ({bot_id!r})"

    if not re.match(r'^[A-Za-z0-9_\-]{20,60}$', bot_hash):
        return False, (
            f"TELEGRAM_BOT_TOKEN: hash con longitud o charset inesperado "
            f"({len(bot_hash)} chars)"
        )

    if not TELEGRAM_CHAT_ID and not ADMIN_CHAT_ID:
        return False, "Ni TELEGRAM_CHAT_ID ni ADMIN_CHAT_ID configurados"

    # Chat IDs: número positivo o negativo (grupos tienen ID negativo)
    for nombre, valor in [("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID), ("ADMIN_CHAT_ID", ADMIN_CHAT_ID)]:
        if valor and not re.match(r'^-?\d+$', valor.strip()):
            return False, f"{nombre} no tiene formato de chat ID numérico: {valor!r}"

    return True, "OK"


# ── Sanitización de fragmentos HTML ───────────────────────────────────────────

def sanitize_html_fragment(html: str, max_len: int = 300) -> str:
    """
    Elimina todos los tags HTML y limita la longitud.

    Previene que contenido del canal AVC inyecte HTML o Markdown
    en mensajes de Telegram cuando se incluye como fragmento de texto.

    Retorna texto plano seguro, truncado a max_len si es necesario.
    """
    if not html:
        return ""

    # Eliminar tags HTML
    clean = re.sub(r'<[^>]+>', '', html)

    # Collapse whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()

    # Truncar con ellipsis
    if len(clean) > max_len:
        clean = clean[:max_len] + "..."

    return clean
