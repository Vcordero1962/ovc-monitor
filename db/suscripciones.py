#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suscripciones.py — CRUD de la tabla suscripciones.

Reglas de negocio:
- Solo el admin (via bot) puede activar suscripciones.
- El precio y método de pago son opcionales en pruebas/cortesías.
- Expirar vencidas: llamar periódicamente desde el bot.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from .connection import get_conn
from .usuarios import actualizar_plan
from core.logger import info, warn, error


# ── Activar suscripción ────────────────────────────────────────────────────────

def activar_suscripcion(
    telegram_id: int,
    plan: str,
    dias: int = 90,
    precio_usd: float = None,
    metodo_pago: str = None,
    referencia: str = None,
    activado_por: int = None,   # telegram_id del admin
    notas: str = None,
) -> Optional[dict]:
    """
    Crea una suscripción activa para el usuario.
    Actualiza también su plan en la tabla usuarios.
    Retorna el registro creado o None si el usuario no existe.
    """
    planes_validos = ("directo", "premium")
    if plan not in planes_validos:
        warn(f"[DB] activar_suscripcion: plan inválido '{plan}'")
        return None

    # Obtener usuario_id desde telegram_id
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM usuarios WHERE telegram_id = %s AND activo = true;",
                        (telegram_id,))
            row = cur.fetchone()

    if not row:
        warn("[DB] activar_suscripcion: usuario no encontrado o inactivo")
        return None

    usuario_id = row["id"]

    # Desactivar suscripciones previas del mismo plan
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE suscripciones SET activa = false WHERE usuario_id = %s AND activa = true;",
                (usuario_id,)
            )

    # Crear nueva suscripción
    fecha_expira = datetime.now(timezone.utc) + timedelta(days=dias)

    sql = """
        INSERT INTO suscripciones
            (usuario_id, plan, precio_usd, metodo_pago, referencia,
             activado_por, dias, fecha_expira, notas)
        VALUES
            (%(uid)s, %(plan)s, %(precio)s, %(metodo)s, %(ref)s,
             %(admin)s, %(dias)s, %(expira)s, %(notas)s)
        RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "uid":    usuario_id,
                "plan":   plan,
                "precio": precio_usd,
                "metodo": metodo_pago,
                "ref":    referencia,
                "admin":  activado_por,
                "dias":   dias,
                "expira": fecha_expira,
                "notas":  notas,
            })
            nueva = cur.fetchone()

    # Actualizar plan en tabla usuarios
    actualizar_plan(telegram_id, plan)

    info(f"[DB] Suscripción activada: plan={plan}, dias={dias}, usuario_id={usuario_id}")
    return dict(nueva)


# ── Consultas ──────────────────────────────────────────────────────────────────

def listar_activas(limit: int = 50, offset: int = 0) -> list[dict]:
    """
    Lista suscripciones activas con alias Telegram.
    Solo para uso del admin — datos mínimos necesarios.
    """
    sql = """
        SELECT u.telegram_user, s.plan, s.fecha_expira,
               s.metodo_pago, s.dias
          FROM suscripciones s
          JOIN usuarios u ON u.id = s.usuario_id
         WHERE s.activa = true
           AND s.fecha_expira > NOW()
           AND u.activo = true
         ORDER BY s.fecha_expira ASC
         LIMIT %s OFFSET %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit, offset))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def listar_por_expirar(dias_margen: int = 7) -> list[dict]:
    """
    Suscripciones que vencen en los próximos N días.
    Útil para el admin: recordar renovaciones.
    """
    sql = """
        SELECT u.telegram_user, u.telegram_id, s.plan,
               s.fecha_expira,
               EXTRACT(DAY FROM s.fecha_expira - NOW())::INT AS dias_restantes
          FROM suscripciones s
          JOIN usuarios u ON u.id = s.usuario_id
         WHERE s.activa = true
           AND s.fecha_expira > NOW()
           AND s.fecha_expira <= NOW() + (%s || ' days')::INTERVAL
           AND u.activo = true
         ORDER BY s.fecha_expira ASC;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(dias_margen),))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def contar_por_plan() -> dict:
    """Retorna {'directo': N, 'premium': N} con suscripciones activas vigentes."""
    sql = """
        SELECT s.plan, COUNT(*) AS total
          FROM suscripciones s
         WHERE s.activa = true AND s.fecha_expira > NOW()
         GROUP BY s.plan;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return {r["plan"]: int(r["total"]) for r in rows}


def ingresos_estimados(mes: int = None, anio: int = None) -> float:
    """
    Suma precio_usd de suscripciones activadas en el mes/año indicado.
    Por defecto: mes y año actual.
    """
    now = datetime.now(timezone.utc)
    mes  = mes  or now.month
    anio = anio or now.year

    sql = """
        SELECT COALESCE(SUM(precio_usd), 0) AS total
          FROM suscripciones
         WHERE EXTRACT(MONTH FROM fecha_inicio) = %s
           AND EXTRACT(YEAR  FROM fecha_inicio) = %s
           AND precio_usd IS NOT NULL;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (mes, anio))
            row = cur.fetchone()
    return float(row["total"]) if row else 0.0


# ── Expiración automática ──────────────────────────────────────────────────────

def expirar_vencidas() -> int:
    """
    Llama a la función SQL que expira suscripciones vencidas
    y degrada el plan del usuario a 'free'.
    Retorna el número de suscripciones expiradas.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT expirar_suscripciones_vencidas() AS expiradas;")
            row = cur.fetchone()
    n = int(row["expiradas"]) if row else 0
    if n > 0:
        info(f"[DB] {n} suscripciones expiradas y degradadas a free")
    return n
