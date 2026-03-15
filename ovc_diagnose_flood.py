#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Diagnóstico de Ráfaga Telegram
===================================
Detecta QUIÉN está enviando los mensajes duplicados.

Qué hace:
  1. Escanea todos los .py del proyecto → lista TODOS los sendMessage/sendPhoto
  2. Consulta Telegram API → muestra los message_ids reales del chat admin
  3. Chequea procesos Windows activos que puedan estar enviando a Telegram
  4. Revisa Docker containers activos
"""

import os
import sys
import re
import subprocess
from pathlib import Path
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Instalando requests...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID     = os.getenv("ADMIN_CHAT_ID", "")
GROUP_ID     = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_DIR     = Path(__file__).parent

SEP = "─" * 60

def titulo(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


# ─── 1. Escanear todos los .py ────────────────────────────────────────────────

def scan_python_files():
    titulo("1. TODOS LOS sendMessage / sendPhoto en el proyecto")
    py_files = list(BASE_DIR.rglob("*.py"))
    encontrados = []
    for f in py_files:
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if re.search(r"send(Message|Photo|Document|Video)", line, re.IGNORECASE):
                # Buscar qué chat_id usa — mirar las 5 líneas siguientes
                contexto = "\n".join(lines[max(0,i-3):i+5])
                chat = "?"
                m = re.search(r'"chat_id"\s*:\s*([^,}\n]+)', contexto)
                if m:
                    chat = m.group(1).strip()
                entry = {
                    "file": f.relative_to(BASE_DIR),
                    "line": i,
                    "code": line.strip(),
                    "chat": chat,
                }
                encontrados.append(entry)
                print(f"  [{f.name}:{i}]  chat→{chat}")
                print(f"     {line.strip()[:90]}")

    print(f"\n  Total: {len(encontrados)} endpoints encontrados")
    return encontrados


# ─── 2. Consultar Telegram: mensajes reales en chat admin ────────────────────

def check_telegram_admin():
    titulo("2. MENSAJES REALES EN CHAT ADMIN (Telegram API)")
    if not BOT_TOKEN:
        print("  ERROR: TELEGRAM_BOT_TOKEN no encontrado en .env")
        return
    if not ADMIN_ID:
        print("  ERROR: ADMIN_CHAT_ID no encontrado en .env")
        return

    print(f"  Bot token: ...{BOT_TOKEN[-8:]}")
    print(f"  ADMIN_CHAT_ID: {ADMIN_ID}")
    print(f"  TELEGRAM_CHAT_ID (grupo): {GROUP_ID}")
    print(f"  ¿Son iguales? {'SÍ ← AQUÍ ESTÁ EL BUG' if ADMIN_ID == GROUP_ID else 'No (correcto)'}")

    # getUpdates para ver mensajes recientes (últimos 100)
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"limit": 100, "offset": -100},
            timeout=15
        )
        if not r.ok:
            print(f"  getUpdates ERROR: {r.status_code} {r.text[:100]}")
            return
        updates = r.json().get("result", [])
        print(f"\n  Updates recibidos por el bot: {len(updates)}")
        for u in updates[-5:]:
            msg = u.get("message") or u.get("channel_post") or {}
            print(f"    update_id={u.get('update_id')} | "
                  f"chat={msg.get('chat',{}).get('id','?')} | "
                  f"text={str(msg.get('text',''))[:50]}")
    except Exception as e:
        print(f"  getUpdates excepción: {e}")

    # getChat para verificar info del admin chat
    for label, cid in [("ADMIN_CHAT_ID", ADMIN_ID), ("TELEGRAM_CHAT_ID", GROUP_ID)]:
        if not cid:
            continue
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
                params={"chat_id": cid},
                timeout=10
            )
            if r.ok:
                info = r.json().get("result", {})
                tipo = info.get("type", "?")
                titulo_chat = info.get("title") or info.get("username") or info.get("first_name", "?")
                print(f"\n  {label} = {cid}")
                print(f"    Tipo: {tipo}")
                print(f"    Nombre: {titulo_chat}")
            else:
                print(f"\n  {label} = {cid} → ERROR {r.status_code}")
        except Exception as e:
            print(f"  getChat {label}: {e}")


# ─── 3. Procesos Windows activos ──────────────────────────────────────────────

def check_procesos_windows():
    titulo("3. PROCESOS PYTHON ACTIVOS (Windows)")
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l for l in result.stdout.splitlines() if "python" in l.lower()]
        if lines:
            print(f"  Procesos python.exe activos: {len(lines)}")
            for l in lines:
                print(f"    {l}")
        else:
            print("  No hay procesos python.exe activos")

        # También pythonw.exe
        result2 = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq pythonw.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10
        )
        lines2 = [l for l in result2.stdout.splitlines() if "python" in l.lower()]
        if lines2:
            print(f"  pythonw.exe activos:")
            for l in lines2:
                print(f"    {l}")
    except Exception as e:
        print(f"  Error tasklist: {e}")


# ─── 4. Docker containers activos ────────────────────────────────────────────

def check_docker():
    titulo("4. DOCKER CONTAINERS ACTIVOS")
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Image}}"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            ovc_containers = [l for l in lines if "ovc" in l.lower() or "sentinel" in l.lower()]
            print(f"  Todos los containers: {len(lines)-1}")
            if ovc_containers:
                print(f"  Containers OVC/Sentinel activos:")
                for l in ovc_containers:
                    print(f"    {l}")
            else:
                print("  No hay containers OVC activos")
            # Mostrar todos igualmente
            for l in lines:
                print(f"    {l}")
        else:
            print(f"  Docker no disponible: {result.stderr[:100]}")
    except Exception as e:
        print(f"  Docker error: {e}")


# ─── 5. Logs del sentinel Docker ──────────────────────────────────────────────

def check_sentinel_logs():
    titulo("5. LOGS RECIENTES DEL SENTINEL DOCKER")
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", "30", "ovc-sentinel"],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout + result.stderr
        if output.strip():
            lines = output.strip().splitlines()
            for l in lines:
                print(f"  {l}")
        else:
            print("  Container ovc-sentinel no encontrado o sin logs")
    except Exception as e:
        print(f"  docker logs error: {e}")


# ─── 6. Verificar si ADMIN_CHAT_ID == GROUP_ID ───────────────────────────────

def check_ids_collision():
    titulo("6. VERIFICACIÓN DE IDs TELEGRAM")
    print(f"  ADMIN_CHAT_ID    = '{ADMIN_ID}'")
    print(f"  TELEGRAM_CHAT_ID = '{GROUP_ID}'")
    if ADMIN_ID == GROUP_ID:
        print("\n  *** BUG DETECTADO: ADMIN_CHAT_ID == TELEGRAM_CHAT_ID ***")
        print("  El heartbeat envía al mismo destino que las alertas del grupo.")
        print("  Solución: configurar ADMIN_CHAT_ID con el ID de tu chat privado.")
    elif not ADMIN_ID:
        print("\n  *** AVISO: ADMIN_CHAT_ID vacío ***")
        print("  ovc_heartbeat.py usa TELEGRAM_CHAT_ID como fallback → va al grupo.")
    else:
        print("\n  IDs distintos — configuración correcta.")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  OVC DIAGNÓSTICO DE RÁFAGA — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*60}")

    scan_python_files()
    check_ids_collision()
    check_telegram_admin()
    check_procesos_windows()
    check_docker()
    check_sentinel_logs()

    print(f"\n{SEP}")
    print("  Diagnóstico completo.")
    print(f"{SEP}\n")
