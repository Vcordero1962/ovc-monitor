#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Test — Prueba acceso directo a Bookitit sin pasar por citaconsular.es
Objetivo: verificar si app.bookitit.com expone el mismo endpoint sin Imperva

Ejecutar via: gh workflow run ovc_test_bookitit.yml
"""

import os
import time
import requests

PK  = os.environ.get("PK",  "28db94e270580be60f6e00285a7d8141f")
SID = os.environ.get("SID", "bkt873048")

HEADERS_CHROME = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

JSONP_PARAMS = f"?callback=jQuery321&type=default&publickey={PK}&lang=es&services[]={SID}&version=5&src=https%3A%2F%2Fwww.citaconsular.es%2F&_=1710000000000"

endpoints = [
    # Opcion A: endpoint JSONP directo en Bookitit (sin pasar por citaconsular.es)
    ("A - app.bookitit.com JSONP",
     f"https://app.bookitit.com/onlinebookings/main/{JSONP_PARAMS}"),

    ("B - www.bookitit.com JSONP",
     f"https://www.bookitit.com/onlinebookings/main/{JSONP_PARAMS}"),

    # Opcion C: widget directo en Bookitit
    ("C - app.bookitit.com widget",
     f"https://app.bookitit.com/es/hosteds/widgetdefault/{PK}/{SID}"),

    # Referencia: el endpoint original con Imperva (para comparar)
    ("D - citaconsular.es JSONP (con Imperva - referencia)",
     f"https://www.citaconsular.es/onlinebookings/main/{JSONP_PARAMS}"),

    ("E - citaconsular.es widget (con Imperva - referencia)",
     f"https://www.citaconsular.es/es/hosteds/widgetdefault/{PK}/{SID}"),
]

print("=" * 70)
print("OVC TEST — Acceso directo Bookitit vs citaconsular.es (con Imperva)")
print("=" * 70)

# Test 1: requests simple (sin TLS spoofing)
print("\n[METODO 1] requests simple")
print("-" * 50)
session = requests.Session()
for nombre, url in endpoints:
    try:
        r = session.get(url, headers=HEADERS_CHROME, timeout=15, allow_redirects=True)
        contenido = r.text[:300].replace('\n', ' ')
        tiene_citas = "No hay horas" in r.text or "Huecos" in r.text or "agendas" in r.text or "bkt_init" in r.text
        bloqueado = len(r.text) < 500 and ("captcha" in r.text.lower() or "incapsula" in r.text.lower() or r.status_code in [403, 429])
        estado = "BLOQUEADO" if bloqueado else ("UTIL (tiene datos citas)" if tiene_citas else "RESPONDE (sin datos citas)")
        print(f"  {nombre}")
        print(f"    Status: {r.status_code} | Chars: {len(r.text)} | Estado: {estado}")
        print(f"    Preview: {contenido[:120]}")
    except Exception as e:
        print(f"  {nombre}")
        print(f"    ERROR: {e}")
    time.sleep(1)

# Test 2: curl_cffi con TLS spoofing Chrome
print("\n[METODO 2] curl_cffi impersonate=chrome124")
print("-" * 50)
try:
    from curl_cffi import requests as cffi_requests
    session2 = cffi_requests.Session()
    for nombre, url in endpoints:
        try:
            r = session2.get(url, impersonate="chrome124", headers=HEADERS_CHROME, timeout=15)
            tiene_citas = "No hay horas" in r.text or "Huecos" in r.text or "agendas" in r.text or "bkt_init" in r.text
            bloqueado = len(r.text) < 500 and ("captcha" in r.text.lower() or "incapsula" in r.text.lower() or r.status_code in [403, 429])
            estado = "BLOQUEADO" if bloqueado else ("UTIL (tiene datos citas)" if tiene_citas else "RESPONDE (sin datos citas)")
            print(f"  {nombre}")
            print(f"    Status: {r.status_code} | Chars: {len(r.text)} | Estado: {estado}")
            print(f"    Preview: {r.text[:120].replace(chr(10), ' ')}")
        except Exception as e:
            print(f"  {nombre}")
            print(f"    ERROR: {e}")
        time.sleep(1)
except ImportError:
    print("  curl_cffi no disponible")

print("\n" + "=" * 70)
print("CONCLUSION:")
print("  Si A o B muestran 'UTIL' o 'RESPONDE' con status 200 → sin Imperva!")
print("  Si D/E muestran 'BLOQUEADO' y A/B no → Bookitit directo es la solucion.")
print("=" * 70)
