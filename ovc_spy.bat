@echo off
chcp 65001 > nul
title OVC SPY — Captura flujo completo Bookitit
color 0E

echo ================================================================
echo   OVC SPY — Captura COMPLETA del flujo de red del widget
echo   Usa Playwright (browser real) — NO requiere proxy manual
echo   Captura: URLs, headers, cookies, tokens, JSONP, SIDs, PKs
echo ================================================================
echo.
echo Opciones de CAPTURA UNICA:
echo   1. Espiar LEGA     (Legalizaciones)
echo   2. Espiar PASAPORTE
echo   3. Espiar LMD      (Ley Memoria Democratica)
echo   4. Espiar URL personalizada
echo   5. Espiar LEGA con browser VISIBLE (ver que pasa en pantalla)
echo.
echo Opciones MODO CONTINUO (loop infinito, Ctrl+C para detener):
echo   6. LEGA continuo   (cada 5 min, sin alerta Telegram)
echo   7. LEGA continuo   (cada 5 min, CON alerta Telegram al detectar cita)
echo   8. PASAPORTE continuo + alerta Telegram
echo.
echo Inteligencia competitiva AVC:
echo   9. AVC Intel — un solo scrape del canal AVC
echo   A. AVC Intel — modo continuo (cada 10 min)
echo.
set /p OPCION="Elige opcion (1-9 / A): "

cd /d "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"

if /i "%OPCION%"=="1" (
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py
)
if /i "%OPCION%"=="2" (
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py "https://www.citaconsular.es/es/hosteds/widgetdefault/22091b5b8d43b89fb226cabb272a844f9/"
)
if /i "%OPCION%"=="3" (
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py "https://www.citaconsular.es/es/hosteds/widgetdefault/28330379fc95acafd31ee9e8938c278ff/"
)
if /i "%OPCION%"=="4" (
    set /p URL_CUSTOM="Pega la URL del widget: "
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py "%URL_CUSTOM%"
)
if /i "%OPCION%"=="5" (
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py --visible
)
if /i "%OPCION%"=="6" (
    echo Iniciando modo CONTINUO LEGA — sin alertas. Ctrl+C para detener.
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py --continuo --intervalo 300
)
if /i "%OPCION%"=="7" (
    echo Iniciando modo CONTINUO LEGA — CON alertas Telegram. Ctrl+C para detener.
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py --continuo --intervalo 300 --alerta
)
if /i "%OPCION%"=="8" (
    echo Iniciando PASAPORTE continuo — CON alertas Telegram. Ctrl+C para detener.
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py "https://www.citaconsular.es/es/hosteds/widgetdefault/22091b5b8d43b89fb226cabb272a844f9/" --continuo --intervalo 300 --alerta
)
if /i "%OPCION%"=="9" (
    echo Ejecutando AVC Intel — scrape unico...
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_avc_intel.py
)
if /i "%OPCION%"=="A" (
    echo Iniciando AVC Intel CONTINUO — cada 10 min. Ctrl+C para detener.
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_avc_intel.py --continuo --intervalo 600
)

echo.
echo Resultados guardados en: logs\
pause
