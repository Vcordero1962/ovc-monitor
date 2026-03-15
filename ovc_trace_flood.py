#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Trace Flood — Intercepta TODAS las llamadas HTTP de ovc_heartbeat.py
Monkey-patchea requests.post y urllib3 para capturar duplicados.
Corre en GitHub Actions via ovc_trace.yml
"""

import os
import sys
import time
import traceback
import threading
import requests
import requests.adapters
import urllib3
from datetime import datetime, timezone, timedelta

# ─── Contadores globales ──────────────────────────────────────────────────────
_call_log = []
_lock = threading.Lock()

# ─── Monkey-patch requests.post ──────────────────────────────────────────────
_original_post = requests.post

def _traced_post(url, **kwargs):
    ts = datetime.now(timezone.utc).isoformat()
    caller = traceback.extract_stack()[-2]
    entry = {
        "ts":   ts,
        "url":  url,
        "file": f"{caller.filename}:{caller.lineno}",
        "func": caller.name,
        "pid":  os.getpid(),
        "tid":  threading.current_thread().name,
    }
    # Capturar chat_id si está en json payload
    j = kwargs.get("json", {})
    if isinstance(j, dict):
        entry["chat_id"] = j.get("chat_id", "?")
        entry["text_preview"] = str(j.get("text", ""))[:60]

    with _lock:
        _call_log.append(entry)
        idx = len(_call_log)

    print(f"\n[TRACE] ===== POST #{idx} =====", flush=True)
    print(f"[TRACE] timestamp : {ts}", flush=True)
    print(f"[TRACE] url       : {url}", flush=True)
    print(f"[TRACE] chat_id   : {entry.get('chat_id','?')}", flush=True)
    print(f"[TRACE] text[:60] : {entry.get('text_preview','')}", flush=True)
    print(f"[TRACE] caller    : {entry['file']} in {entry['func']}", flush=True)
    print(f"[TRACE] pid/tid   : {entry['pid']} / {entry['tid']}", flush=True)
    print(f"[TRACE] stack     :", flush=True)
    for frame in traceback.extract_stack()[:-1]:
        print(f"[TRACE]   {frame.filename}:{frame.lineno} in {frame.name}", flush=True)

    resp = _original_post(url, **kwargs)

    print(f"[TRACE] response  : status={resp.status_code}", flush=True)
    if resp.ok:
        result = resp.json().get("result", {})
        msg_id = result.get("message_id", "?")
        print(f"[TRACE] message_id: {msg_id}", flush=True)
    else:
        print(f"[TRACE] error     : {resp.text[:100]}", flush=True)

    return resp

requests.post = _traced_post

# ─── También parchear urllib3 por si requests usa Session internamente ────────
_original_send = requests.adapters.HTTPAdapter.send

def _traced_send(self, request, **kwargs):
    if "telegram" in request.url:
        print(f"\n[TRACE-URLLIB3] HTTPAdapter.send → {request.method} {request.url[:80]}", flush=True)
    return _original_send(self, request, **kwargs)

requests.adapters.HTTPAdapter.send = _traced_send

# ─── Verificar variables de entorno que podrían causar retries ────────────────
print("\n[TRACE] ===== ENV CHECK =====", flush=True)
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "RUNNER_NAME"]:
    val = os.environ.get(key, "(no definido)")
    # Ocultar credenciales si hay en la URL
    if "://" in val and "@" in val:
        val = val.split("@")[-1]  # Solo mostrar host:port
    print(f"[TRACE] {key:25s} = {val}", flush=True)

# ─── Verificar urllib3 retry config ──────────────────────────────────────────
print("\n[TRACE] ===== URLLIB3 RETRY CONFIG =====", flush=True)
s = requests.Session()
for prefix in ("https://", "http://"):
    adapter = s.get_adapter(prefix)
    retry = adapter.max_retries
    print(f"[TRACE] adapter({prefix}) max_retries = {retry}", flush=True)

# ─── Ahora ejecutar el heartbeat real ────────────────────────────────────────
print("\n[TRACE] ===== EJECUTANDO ovc_heartbeat.py =====\n", flush=True)

# Importar y ejecutar heartbeat — como si fuera python ovc_heartbeat.py
# Usamos exec para simular ejecución directa del script
heartbeat_path = os.path.join(os.path.dirname(__file__) or ".", "ovc_heartbeat.py")
with open(heartbeat_path, "r", encoding="utf-8") as f:
    code = f.read()

exec(compile(code, heartbeat_path, "exec"), {"__name__": "__main__", "__file__": heartbeat_path})

# ─── Resumen final ────────────────────────────────────────────────────────────
print(f"\n[TRACE] ===== RESUMEN =====", flush=True)
print(f"[TRACE] Total llamadas POST a Telegram: {len(_call_log)}", flush=True)
for i, c in enumerate(_call_log, 1):
    print(f"[TRACE]   #{i}: {c['ts']} → chat={c.get('chat_id','?')} | {c.get('text_preview','')[:40]}", flush=True)

if len(_call_log) > 1:
    print(f"\n[TRACE] *** RÁFAGA DETECTADA: {len(_call_log)} llamadas en 1 run ***", flush=True)
elif len(_call_log) == 1:
    print(f"\n[TRACE] OK — 1 sola llamada, sin ráfaga en el código.", flush=True)
    print(f"[TRACE] Si ves múltiples mensajes en Telegram = duplicado del CLIENTE, no del bot.", flush=True)
else:
    print(f"\n[TRACE] 0 llamadas — heartbeat abortado por anti-duplicado.", flush=True)
