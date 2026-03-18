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
echo Opciones:
echo   1. Espiar LEGA     (Legalizaciones)
echo   2. Espiar PASAPORTE
echo   3. Espiar LMD      (Ley Memoria Democratica)
echo   4. Espiar URL personalizada
echo   5. Espiar LEGA con browser VISIBLE (ver que pasa en pantalla)
echo.
set /p OPCION="Elige opcion (1-5): "

cd /d "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"

if "%OPCION%"=="1" (
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py
)
if "%OPCION%"=="2" (
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py "https://www.citaconsular.es/es/hosteds/widgetdefault/22091b5b8d43b89fb226cabb272a844f9/"
)
if "%OPCION%"=="3" (
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py "https://www.citaconsular.es/es/hosteds/widgetdefault/28330379fc95acafd31ee9e8938c278ff/"
)
if "%OPCION%"=="4" (
    set /p URL_CUSTOM="Pega la URL del widget: "
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py "%URL_CUSTOM%"
)
if "%OPCION%"=="5" (
    C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py --visible
)

echo.
echo Resultados guardados en: logs\ovc_spy_*.txt y logs\ovc_spy_*.json
pause
