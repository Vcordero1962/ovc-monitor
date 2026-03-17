#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
connection.py — Conexión robusta a Neon PostgreSQL.

Neon cierra conexiones inactivas >5 min (SSL drop).
Solución: conexión nueva por cada operación (no pool persistente)
+ keepalives TCP + reintento automático si SSL cae.
"""

import os
import time
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from core.logger import info, warn, error

_DATABASE_URL = os.getenv("NEON_DATABASE_URL", "")


def _nueva_conn():
    """Abre una conexión fresca a Neon con keepalives TCP."""
    if not _DATABASE_URL:
        raise EnvironmentError(
            "NEON_DATABASE_URL no configurada. "
            "Agrega la variable al .env o a los GitHub Secrets."
        )
    return psycopg2.connect(
        _DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=15,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


@contextmanager
def get_conn(reintentos: int = 3):
    """
    Context manager que entrega una conexión fresca a Neon.
    Reintenta automáticamente si la conexión SSL fue cerrada.

    Uso:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")
                rows = cur.fetchall()
    """
    conn = None
    ultimo_error = None

    for intento in range(1, reintentos + 1):
        try:
            conn = _nueva_conn()
            yield conn
            conn.commit()
            return
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
            ultimo_error = exc
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            conn = None
            if intento < reintentos:
                espera = intento * 2
                warn(f"[DB] Conexión SSL caída (intento {intento}/{reintentos}) — reintentando en {espera}s")
                time.sleep(espera)
            else:
                error(f"[DB] Fallo tras {reintentos} intentos: {exc}")
                raise
        except Exception as exc:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            error(f"[DB] Error de base de datos: {exc}")
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


def test_connection() -> bool:
    """Verifica que la conexión a Neon funcione. Retorna True si OK."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ping;")
                row = cur.fetchone()
                if row and row["ping"] == 1:
                    info("[DB] ✅ Conexión a Neon PostgreSQL OK")
                    return True
    except Exception as exc:
        error(f"[DB] ❌ Fallo al conectar a Neon: {exc}")
    return False


def ejecutar_schema(schema_path: str = None) -> bool:
    """Ejecuta schema.sql contra la DB. Idempotente (CREATE IF NOT EXISTS)."""
    if schema_path is None:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            sql = f.read()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
        info("[DB] ✅ Schema aplicado correctamente")
        return True
    except Exception as exc:
        error(f"[DB] ❌ Error al aplicar schema: {exc}")
        return False
