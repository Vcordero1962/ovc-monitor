#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
connection.py — Conexión única a Neon PostgreSQL.

Usa psycopg2 con pool de conexiones simple.
La URL viene de la variable de entorno NEON_DATABASE_URL.
Formato esperado:
  postgresql://usuario:clave@host.neon.tech/dbname?sslmode=require
"""

import os
import time
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

from core.logger import info, warn, error

# ── Configuración ─────────────────────────────────────────────────────────────
_DATABASE_URL = os.getenv("NEON_DATABASE_URL", "")
_POOL: psycopg2.pool.ThreadedConnectionPool | None = None
_MIN_CONN = 1
_MAX_CONN = 5   # Neon free tier permite hasta 10 conexiones concurrentes


def _build_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Crea el pool de conexiones. Se llama una sola vez."""
    if not _DATABASE_URL:
        raise EnvironmentError(
            "NEON_DATABASE_URL no configurada. "
            "Agrega la variable al .env o a los GitHub Secrets."
        )
    return psycopg2.pool.ThreadedConnectionPool(
        _MIN_CONN,
        _MAX_CONN,
        _DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=10,
    )


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Retorna el pool singleton, creándolo si es necesario."""
    global _POOL
    if _POOL is None or _POOL.closed:
        _POOL = _build_pool()
    return _POOL


@contextmanager
def get_conn() -> Generator:
    """
    Context manager que entrega una conexión del pool.

    Uso:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")
                rows = cur.fetchall()
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as exc:
        conn.rollback()
        error(f"[DB] Error de base de datos: {exc}")
        raise
    finally:
        pool.putconn(conn)


def test_connection() -> bool:
    """
    Verifica que la conexión a Neon funcione.
    Retorna True si OK, False si hay error.
    """
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
    """
    Ejecuta el archivo schema.sql contra la base de datos.
    Útil para inicializar tablas en un proyecto nuevo.
    """
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
