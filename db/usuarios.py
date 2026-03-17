#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usuarios.py — CRUD de la tabla usuarios.

Reglas:
- Nunca exponer telegram_id en logs públicos.
- Nunca retornar datos en crudo al admin — solo resúmenes.
- Toda escritura queda trazada en updated_at.
"""

from typing import Optional
from .connection import get_conn
from core.logger import info, warn, error


# ── Registro / upsert ──────────────────────────────────────────────────────────

def registrar_usuario(
    telegram_id: int,
    telegram_user: str = None,
    nombre: str = None,
    whatsapp_phone: str = None,
) -> dict:
    """
    Registra un usuario nuevo o actualiza sus datos si ya existe.
    Retorna el registro completo del usuario.
    """
    sql = """
        INSERT INTO usuarios (telegram_id, telegram_user, nombre, whatsapp_phone)
        VALUES (%(tid)s, %(user)s, %(nombre)s, %(wa)s)
        ON CONFLICT (telegram_id) DO UPDATE
            SET telegram_user  = EXCLUDED.telegram_user,
                nombre         = COALESCE(EXCLUDED.nombre, usuarios.nombre),
                whatsapp_phone = COALESCE(EXCLUDED.whatsapp_phone, usuarios.whatsapp_phone),
                updated_at     = NOW()
        RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "tid":    telegram_id,
                "user":   telegram_user,
                "nombre": nombre,
                "wa":     whatsapp_phone,
            })
            row = cur.fetchone()
    info(f"[DB] Usuario registrado/actualizado id={row['id']}")
    return dict(row)


# ── Consultas ──────────────────────────────────────────────────────────────────

def obtener_usuario(telegram_id: int) -> Optional[dict]:
    """Retorna el usuario o None si no existe."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM usuarios WHERE telegram_id = %s;",
                (telegram_id,)
            )
            row = cur.fetchone()
    return dict(row) if row else None


def listar_suscriptores_para_tramite(tramite: str) -> list[dict]:
    """
    Retorna lista de suscriptores activos cuyo array servicios
    incluye el tramite indicado (ej: 'LEGA', 'LMD', 'PASAPORTE').
    Solo usuarios con plan activo y vigente.
    """
    sql = """
        SELECT u.id, u.telegram_id, u.telegram_user, u.nombre,
               u.plan, u.whatsapp_phone, s.fecha_expira
          FROM suscriptores_activos u
          JOIN suscripciones s ON s.usuario_id = u.id
         WHERE %s = ANY(u.servicios)
           AND s.activa = true
           AND s.fecha_expira > NOW()
         GROUP BY u.id, u.telegram_id, u.telegram_user, u.nombre,
                  u.plan, u.whatsapp_phone, s.fecha_expira;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (tramite,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Actualización de servicios ─────────────────────────────────────────────────

def actualizar_servicios(telegram_id: int, servicios: list[str]) -> bool:
    """
    Actualiza la lista de trámites que el usuario quiere vigilar.
    Valida que los servicios sean códigos reconocidos.
    """
    from core.config import SERVICIOS as SERVICIOS_VALIDOS
    servicios_limpios = [s.upper() for s in servicios if s.upper() in SERVICIOS_VALIDOS]

    if not servicios_limpios:
        warn(f"[DB] actualizar_servicios: ningún servicio válido en {servicios}")
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE usuarios
                      SET servicios = %s, updated_at = NOW()
                    WHERE telegram_id = %s;""",
                (servicios_limpios, telegram_id)
            )
    info(f"[DB] Servicios actualizados para telegram_id=*** → {servicios_limpios}")
    return True


def actualizar_plan(telegram_id: int, plan: str) -> bool:
    """Actualiza el plan del usuario (free | directo | premium)."""
    planes_validos = ("free", "directo", "premium")
    if plan not in planes_validos:
        warn(f"[DB] Plan inválido: '{plan}'")
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE usuarios SET plan = %s, updated_at = NOW() WHERE telegram_id = %s;",
                (plan, telegram_id)
            )
    return True


def desactivar_usuario(telegram_id: int) -> bool:
    """Desactiva un usuario (baja o bloqueo). No borra el registro."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE usuarios SET activo = false, updated_at = NOW() WHERE telegram_id = %s;",
                (telegram_id,)
            )
    info(f"[DB] Usuario desactivado (telegram_id protegido)")
    return True


# ── Estadísticas (para admin) ──────────────────────────────────────────────────

def contar_usuarios_por_plan() -> dict:
    """Retorna conteos por plan. Nunca expone IDs individuales."""
    sql = """
        SELECT plan, COUNT(*) AS total
          FROM usuarios
         WHERE activo = true
         GROUP BY plan;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return {r["plan"]: r["total"] for r in rows}


def total_usuarios() -> int:
    """Retorna el total de usuarios registrados (activos e inactivos)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM usuarios;")
            row = cur.fetchone()
    return row["n"] if row else 0
