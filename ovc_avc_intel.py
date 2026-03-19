#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ovc_avc_intel.py — Inteligencia competitiva sobre AVC (Asesor Virtual Cubano)

OBJETIVO: Entender cómo AVC logra detectar citas cuando OVC no puede.
  - ¿Qué IP/método usa? ¿Residencial? ¿Bot? ¿Humano?
  - ¿Con qué frecuencia chequea?
  - ¿Qué herramientas muestra en sus screenshots?
  - ¿A qué horas detecta citas?

ACLARACIÓN: Este script NO depende de AVC para detectar citas.
Únicamente monitorea su canal público para análisis técnico.
Regla OVC: "no depender de AVC para alertas" — este script solo recolecta
inteligencia competitiva, no alimenta el bot de alertas.

USO:
  python -X utf8 ovc_avc_intel.py [--continuo] [--intervalo 600]
  python -X utf8 ovc_avc_intel.py --analizar   # solo analiza posts ya guardados

SALIDA:
  logs/avc_intel_TIMESTAMP.json   — posts capturados
  logs/avc_intel_TIMESTAMP.txt    — análisis técnico
  logs/avc_intel_continuo_*.log   — log de monitoreo continuo
"""

import sys
import json
import re
import os
import time
import random
import argparse
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent / "logs"
BASE_DIR.mkdir(exist_ok=True)

AVC_CHANNEL_URL  = "https://t.me/s/AsesorVirtualC"  # Web preview canal público
AVC_CHANNEL_ID   = "@AsesorVirtualC"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID      = os.getenv("ADMIN_CHAT_ID", "")

# Keywords que indican detección de cita en un post de AVC
KEYWORDS_CITA = [
    "disponible", "hay cita", "cita disponible", "abrieron", "hay hueco",
    "corre", "entra ya", "rápido", "urgente", "fecha disponible",
    "legalizacion", "legalización", "pasaporte", "matrimonio", "nacimiento",
    "LEGA", "LMD",
]

# Keywords de herramientas técnicas que AVC podría mencionar
KEYWORDS_TECH = [
    "bot", "script", "automatico", "automático", "monitor", "alerta",
    "python", "playwright", "selenium", "proxy", "vpn", "residencial",
    "ip", "servidor", "github", "api", "webhook",
]

HEADERS_SCRAPE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── Scraper t.me/s/channelname ────────────────────────────────────────────────

def scrape_canal_telegram(channel_url: str) -> list:
    """
    Scrapea el web preview público de un canal Telegram.
    Retorna lista de posts: {ts, texto, fotos, tiene_cita, tiene_tech, raw_html}
    """
    posts = []
    try:
        r = requests.get(channel_url, headers=HEADERS_SCRAPE, timeout=20)
        if r.status_code != 200:
            print(f"  [WARN] HTTP {r.status_code} al scrapear {channel_url}")
            return posts

        html = r.text

        # Pre-extraer mapa msg_id → timestamp desde el HTML completo
        # El <time datetime="..."> está en el footer, fuera del bloque de texto,
        # por eso la extracción dentro del bloque falla frecuentemente.
        ts_por_id: dict = {}
        for m in re.finditer(
            r'data-post="[^/]+/(\d+)".*?datetime="([^"]+)"',
            html, re.DOTALL
        ):
            ts_por_id[m.group(1)] = m.group(2)

        # Extraer bloques de mensajes individuales
        # t.me/s/ usa estructura: <div class="tgme_widget_message_wrap">
        bloques = re.findall(
            r'<div class="tgme_widget_message_wrap[^"]*".*?</div>\s*</div>\s*</div>',
            html, re.DOTALL
        )

        for bloque in bloques:
            post = _parsear_post(bloque, ts_por_id)
            if post:
                posts.append(post)

        # Si no encontramos con regex anterior, intentar parseo alternativo
        if not posts:
            posts = _parsear_posts_alternativo(html)

        print(f"  [INTEL] {len(posts)} posts encontrados en {channel_url}")

    except Exception as e:
        print(f"  [INTEL] Error scrapeando canal: {e}")

    return posts


def _parsear_post(bloque: str, ts_por_id: dict | None = None) -> dict | None:
    """Parsea un bloque HTML de mensaje Telegram."""
    try:
        # ID del mensaje
        msg_id_m = re.search(r'data-post="[^/]+/(\d+)"', bloque)
        msg_id = msg_id_m.group(1) if msg_id_m else ""

        # Timestamp: primero en el bloque, luego en el mapa pre-extraído
        ts_m = re.search(r'datetime="([^"]+)"', bloque)
        ts_raw = ts_m.group(1) if ts_m else ""
        if not ts_raw and ts_por_id and msg_id:
            ts_raw = ts_por_id.get(msg_id, "")

        # Texto del mensaje
        texto_m = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            bloque, re.DOTALL
        )
        texto_raw = texto_m.group(1) if texto_m else ""
        # Limpiar HTML básico
        texto = re.sub(r'<[^>]+>', ' ', texto_raw).strip()
        texto = re.sub(r'\s+', ' ', texto)

        # Fotos adjuntas
        fotos = re.findall(r'<a[^>]+style="[^"]*background-image:url\(\'([^\']+)\'\)', bloque)
        fotos += re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', bloque)

        # Análisis de contenido
        texto_lower = texto.lower()
        tiene_cita = any(kw.lower() in texto_lower for kw in KEYWORDS_CITA)
        # Para keywords cortas (<=3 chars) exigir palabra completa para evitar
        # falsos positivos: "ip" en "equipo", "api" en "apicultura", etc.
        import re as _re
        def _kw_match(kw, texto):
            if len(kw) <= 3:
                return bool(_re.search(r'\b' + _re.escape(kw) + r'\b', texto))
            return kw in texto
        tiene_tech = any(_kw_match(kw.lower(), texto_lower) for kw in KEYWORDS_TECH)

        # Hora del post (para análisis de horario)
        hora = ""
        if ts_raw:
            try:
                dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                hora = dt.strftime("%H:%M")
            except Exception:
                pass

        return {
            "msg_id":    msg_id,
            "ts":        ts_raw,
            "hora":      hora,
            "texto":     texto[:500],
            "fotos":     fotos[:3],
            "tiene_cita": tiene_cita,
            "tiene_tech": tiene_tech,
            "raw_size":  len(bloque),
        }
    except Exception:
        return None


def _parsear_posts_alternativo(html: str) -> list:
    """Parseo alternativo si la estructura HTML cambió."""
    posts = []
    # Buscar patrones de texto y timestamp directamente
    segmentos = re.split(r'<div class="tgme_widget_message["\s]', html)
    for seg in segmentos[1:]:  # skip first (before first message)
        ts_m   = re.search(r'datetime="([^"]+)"', seg)
        text_m = re.search(r'<div class="[^"]*text[^"]*"[^>]*>(.*?)</div>', seg, re.DOTALL)

        if not ts_m:
            continue

        ts_raw  = ts_m.group(1)
        texto   = ""
        if text_m:
            texto = re.sub(r'<[^>]+>', ' ', text_m.group(1)).strip()
            texto = re.sub(r'\s+', ' ', texto)

        texto_lower = texto.lower()
        posts.append({
            "msg_id":    "",
            "ts":        ts_raw,
            "hora":      ts_raw[11:16] if len(ts_raw) > 15 else "",
            "texto":     texto[:500],
            "fotos":     [],
            "tiene_cita": any(kw.lower() in texto_lower for kw in KEYWORDS_CITA),
            "tiene_tech": any(kw.lower() in texto_lower for kw in KEYWORDS_TECH),
            "raw_size":  len(seg),
        })
    return posts


# ── Análisis técnico de los posts ─────────────────────────────────────────────

def analizar_patron_avc(posts: list) -> dict:
    """
    Analiza los posts para determinar el perfil técnico de AVC.
    Busca pistas sobre: IP, método, frecuencia, horario, herramientas.
    """
    if not posts:
        return {}

    analisis = {
        "total_posts":     len(posts),
        "posts_con_cita":  [],
        "posts_con_tech":  [],
        "horas_deteccion": [],
        "frecuencia_min":  None,
        "patron_horario":  {},
        "claves_tech":     [],
        "hipotesis_metodo": "",
    }

    # Agrupar posts con cita
    cita_posts = [p for p in posts if p["tiene_cita"]]
    tech_posts = [p for p in posts if p["tiene_tech"]]

    analisis["posts_con_cita"] = len(cita_posts)
    analisis["posts_con_tech"] = len(tech_posts)

    # Extraer horas de detección
    for p in cita_posts:
        if p.get("hora"):
            analisis["horas_deteccion"].append(p["hora"])

    # Distribución por hora del día
    hora_dist = {}
    for p in posts:
        if p.get("hora"):
            h = p["hora"][:2]  # "HH"
            hora_dist[h] = hora_dist.get(h, 0) + 1
    analisis["patron_horario"] = hora_dist

    # Frecuencia entre posts (detectar si es bot o humano)
    timestamps = []
    for p in posts:
        if p.get("ts"):
            try:
                dt = datetime.fromisoformat(p["ts"].replace("Z", "+00:00"))
                timestamps.append(dt)
            except Exception:
                pass

    if len(timestamps) >= 2:
        timestamps.sort()
        intervalos = [(timestamps[i+1] - timestamps[i]).total_seconds() / 60
                      for i in range(len(timestamps) - 1)]
        if intervalos:
            analisis["frecuencia_min"] = {
                "min":    round(min(intervalos), 1),
                "max":    round(max(intervalos), 1),
                "promedio": round(sum(intervalos) / len(intervalos), 1),
            }

    # Keywords técnicos mencionados
    todos_textos = " ".join(p["texto"] for p in tech_posts).lower()
    mencionados  = [kw for kw in KEYWORDS_TECH if kw in todos_textos]
    analisis["claves_tech"] = mencionados

    # Hipótesis del método basada en análisis
    freq = analisis.get("frecuencia_min", {})
    if freq:
        prom = freq.get("promedio", 999)
        if prom < 5:
            hipotesis = "BOT AUTOMATIZADO — posts muy frecuentes (<5 min) → probablemente loop automatizado con IP residencial o proxy"
        elif prom < 30:
            hipotesis = "BOT SEMI-AUTO — posts cada 5-30 min → posible script con cron o bot de monitoreo"
        elif prom < 120:
            hipotesis = "VERIFICACION MANUAL FRECUENTE — posts cada 30-120 min → humano revisando periódicamente"
        else:
            hipotesis = "VERIFICACION MANUAL ESPORADICA — posts muy separados → humano revisando de vez en cuando"
    else:
        hipotesis = "INSUFICIENTES DATOS — pocas muestras para determinar frecuencia"

    if "vpn" in todos_textos or "proxy" in todos_textos:
        hipotesis += " | Menciona VPN/proxy en sus posts"
    if "residencial" in todos_textos:
        hipotesis += " | Menciona IP residencial"

    analisis["hipotesis_metodo"] = hipotesis

    return analisis


def _guardar_intel(posts: list, analisis: dict, ts: str):
    """Guarda posts y análisis a JSON y TXT."""
    out_json = BASE_DIR / f"avc_intel_{ts}.json"
    out_txt  = BASE_DIR / f"avc_intel_{ts}.txt"

    resultado = {
        "ts":      ts,
        "canal":   AVC_CHANNEL_URL,
        "posts":   posts,
        "analisis": analisis,
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2, default=str)

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(f"OVC AVC INTEL — Análisis canal {AVC_CHANNEL_ID}\n")
        f.write(f"Capturado: {ts}\n")
        f.write("=" * 80 + "\n\n")

        f.write("RESUMEN ANALISIS TECNICO\n")
        f.write("-" * 40 + "\n")
        f.write(f"Total posts analizados : {analisis.get('total_posts', 0)}\n")
        f.write(f"Posts con cita         : {analisis.get('posts_con_cita', 0)}\n")
        f.write(f"Posts con tech keywords: {analisis.get('posts_con_tech', 0)}\n")
        f.write(f"Keywords tech vistos   : {analisis.get('claves_tech', [])}\n")

        freq = analisis.get("frecuencia_min", {})
        if freq:
            f.write(f"\nFRECUENCIA DE POSTS:\n")
            f.write(f"  Min entre posts: {freq.get('min')} min\n")
            f.write(f"  Max entre posts: {freq.get('max')} min\n")
            f.write(f"  Promedio       : {freq.get('promedio')} min\n")

        f.write(f"\nPATRON HORARIO (hora UTC → num posts):\n")
        for h, n in sorted(analisis.get("patron_horario", {}).items()):
            barra = "█" * n
            f.write(f"  {h}h: {barra} ({n})\n")

        f.write(f"\nHIPOTESIS METODO AVC:\n")
        f.write(f"  {analisis.get('hipotesis_metodo', 'sin datos')}\n")

        f.write(f"\nHORAS DE DETECCION DE CITAS (UTC):\n")
        for h in analisis.get("horas_deteccion", []):
            f.write(f"  {h}\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("POSTS COMPLETOS\n")
        f.write("=" * 80 + "\n\n")

        for p in posts:
            cita_flag = " 🚨CITA" if p.get("tiene_cita") else ""
            tech_flag = " 🔧TECH" if p.get("tiene_tech") else ""
            f.write(f"[{p.get('ts','?')}]{cita_flag}{tech_flag}\n")
            f.write(f"  {p.get('texto','(sin texto)')}\n")
            if p.get("fotos"):
                f.write(f"  FOTOS: {p['fotos']}\n")
            f.write("\n")

    return out_json, out_txt


def _imprimir_analisis(analisis: dict):
    """Imprime el análisis en consola."""
    print(f"\n{'═'*65}")
    print(f"  OVC AVC INTEL — RESULTADO")
    print(f"{'═'*65}")
    print(f"  Posts analizados   : {analisis.get('total_posts', 0)}")
    print(f"  Posts con cita     : {analisis.get('posts_con_cita', 0)}")
    print(f"  Posts tech keywords: {analisis.get('posts_con_tech', 0)}")
    print(f"  Keywords tech      : {analisis.get('claves_tech', [])}")

    freq = analisis.get("frecuencia_min", {})
    if freq:
        print(f"\n  FRECUENCIA:")
        print(f"    Mín : {freq.get('min')} min  |  Máx : {freq.get('max')} min  |  Prom: {freq.get('promedio')} min")

    print(f"\n  PATRON HORARIO (hora UTC):")
    for h, n in sorted(analisis.get("patron_horario", {}).items()):
        barra = "█" * min(n, 20)
        print(f"    {h}h: {barra} ({n})")

    print(f"\n  🔍 HIPÓTESIS MÉTODO AVC:")
    print(f"    {analisis.get('hipotesis_metodo', 'sin datos suficientes')}")

    horas_cita = analisis.get("horas_deteccion", [])
    if horas_cita:
        print(f"\n  ⏰ HORAS DETECCIÓN CITAS (UTC): {horas_cita}")
    print(f"{'═'*65}\n")


# ── Modo continuo ─────────────────────────────────────────────────────────────

def monitorear_avc_continuo(intervalo_s: int):
    """
    Monitorea el canal AVC continuamente.
    Guarda cada captura en logs/ y muestra análisis actualizado.
    """
    log_file = BASE_DIR / f"avc_intel_continuo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    ciclo    = 0
    posts_vistos: set = set()  # msg_ids ya procesados

    print(f"\n{'█'*65}")
    print(f"  OVC AVC INTEL — MODO CONTINUO")
    print(f"  Canal: {AVC_CHANNEL_URL}")
    print(f"  Intervalo: {intervalo_s}s | Log: {log_file.name}")
    print(f"  Ctrl+C para detener")
    print(f"{'█'*65}\n")

    def _log(msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linea = f"[{ts}] {msg}"
        print(linea)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(linea + "\n")

    try:
        while True:
            ciclo += 1
            ts_run = datetime.now().strftime("%Y%m%d_%H%M%S")
            print(f"\n{'─'*65}")
            print(f"  CICLO #{ciclo} — {ts_run}")

            posts = scrape_canal_telegram(AVC_CHANNEL_URL)

            # Posts nuevos desde el último ciclo
            posts_nuevos = [p for p in posts
                            if p.get("msg_id") and p["msg_id"] not in posts_vistos]

            for p in posts_nuevos:
                posts_vistos.add(p["msg_id"])
                if p.get("tiene_cita"):
                    _log(f"🚨 AVC NUEVO POST CON CITA: [{p.get('hora','?')}] {p['texto'][:120]}")
                elif p.get("tiene_tech"):
                    _log(f"🔧 AVC NUEVO POST TECH: [{p.get('hora','?')}] {p['texto'][:120]}")

            if not posts_nuevos:
                _log(f"CICLO #{ciclo} — sin posts nuevos ({len(posts)} posts totales)")

            # Analizar y guardar
            if posts:
                analisis = analizar_patron_avc(posts)
                _guardar_intel(posts, analisis, ts_run)
                _imprimir_analisis(analisis)

            # Sleep con jitter
            jitter  = int(random.gauss(0, intervalo_s * 0.1))
            sleep_t = max(60, intervalo_s + jitter)
            print(f"\n  ⏳ Próximo ciclo en {sleep_t}s...")
            time.sleep(sleep_t)

    except KeyboardInterrupt:
        print(f"\n\n[AVC INTEL] Detenido. Ciclos: {ciclo} | Log: {log_file}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="OVC AVC Intel — inteligencia competitiva")
    ap.add_argument("--continuo",  action="store_true", help="Monitoreo continuo")
    ap.add_argument("--intervalo", type=int, default=600, help="Segundos entre scrapes (default: 600)")
    ap.add_argument("--analizar",  action="store_true", help="Solo analizar posts ya guardados")
    args = ap.parse_args()

    if args.continuo:
        monitorear_avc_continuo(args.intervalo)
    else:
        # Un solo scrape + análisis
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"\nOVC AVC INTEL — scrape único de {AVC_CHANNEL_URL}")
        posts = scrape_canal_telegram(AVC_CHANNEL_URL)

        if not posts:
            print("  [WARN] No se encontraron posts. El canal puede requerir autenticación.")
            print("  Intentando URL alternativa...")
            # Alternativa: algunos canales usan /c/channelid
            posts = scrape_canal_telegram("https://t.me/s/AsesorVirtualCubano")

        analisis = analizar_patron_avc(posts)
        out_json, out_txt = _guardar_intel(posts, analisis, ts)
        _imprimir_analisis(analisis)

        print(f"  JSON: {out_json}")
        print(f"  TXT:  {out_txt}")
