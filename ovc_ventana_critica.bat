@echo off
chcp 65001 > nul
title OVC - Ventana Critica (IP Residencial)
echo ============================================================
echo   OVC - Check Unico en Ventana Critica
echo   IP: residencial local (bypassa Imperva)
echo   Modo: SITIO_DIRECTO=0  BOOKITIT_POST=1
echo   Una sola ejecucion - NO loop continuo
echo ============================================================
echo.

cd /d "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"

:: Marca de tiempo para el log
for /f "tokens=1-2 delims=T" %%a in ("%DATE%T%TIME%") do set TSTAMP=%%a_%%b
set TSTAMP=%TSTAMP::=-%
set TSTAMP=%TSTAMP: =0%
set LOGFILE=logs\ventana_critica_%TSTAMP%.log

if not exist logs mkdir logs

echo [%DATE% %TIME%] Iniciando check ventana critica... >> "%LOGFILE%"
echo [%DATE% %TIME%] Iniciando check ventana critica...

:: Configuracion para IP residencial:
:: - Playwright ACTIVADO (headless, sin ventana visible) — IP residencial bypassa Imperva
:: - Con Bookitit POST como fallback (HTTP puro)
:: - Sin CF Worker (sus IPs datacenter siguen bloqueadas)
:: - Sin proxy (usamos IP residencial directa)
set PYTHONUTF8=1
set SITIO_DIRECTO_ENABLED=1
set PLAYWRIGHT_PROXY_ENABLED=0
set BOOKITIT_POST_ENABLED=1
set CF_WORKER_ENABLED=0
set HTTP_PROXY_URL=

:: Ejecutar UNA SOLA VEZ (ovc_once.py ya tiene jitter 10-90s anti-deteccion)
C:\Users\aemes\anaconda3\python.exe -X utf8 -B ovc_once.py >> "%LOGFILE%" 2>&1

set EXIT_CODE=%ERRORLEVEL%
echo [%DATE% %TIME%] Finalizado con codigo: %EXIT_CODE% >> "%LOGFILE%"
echo [%DATE% %TIME%] Finalizado con codigo: %EXIT_CODE%
echo Log guardado en: %LOGFILE%

exit /b %EXIT_CODE%
