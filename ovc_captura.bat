@echo off
chcp 65001 > nul
title OVC CAPTURADOR — Interceptor de tráfico Bookitit/citaconsular
color 0A

echo ================================================================
echo   OVC CAPTURADOR — Monitor completo de flujo de red
echo   Intercepta TODO el trafico hacia Bookitit y citaconsular.es
echo   Puerto proxy: 8888
echo ================================================================
echo.
echo INSTRUCCIONES:
echo  1. Esta ventana va a abrir el proxy en 127.0.0.1:8888
echo  2. Configura Chrome: Ajustes ^> Proxy ^> 127.0.0.1:8888
echo  3. Navega a la URL del widget de LEGA (o cualquier tramite)
echo  4. Selecciona un servicio en el widget (si puedes)
echo  5. Cuando termines: Ctrl+C aqui para detener y guardar
echo.
echo Logs se guardan en: logs\ovc_flujo_*.json y logs\ovc_flujo_*.txt
echo.
echo Presiona ENTER para iniciar el proxy...
pause > nul

cd /d "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"

:: Verificar si el certificado de mitmproxy esta instalado
echo [INFO] Iniciando proxy mitmproxy en 127.0.0.1:8888...
echo [INFO] Si Chrome muestra advertencia SSL, instala el certificado:
echo [INFO] Navega a http://mitm.it en Chrome (con proxy activo) e instala el cert
echo.

C:\Users\aemes\anaconda3\Scripts\mitmdump.exe ^
  --listen-host 127.0.0.1 ^
  --listen-port 8888 ^
  --scripts ovc_capturador.py ^
  --set console_eventlog_verbosity=warn ^
  --showhost

echo.
echo [INFO] Proxy detenido. Revisa los logs en la carpeta logs\
echo [INFO] Archivo JSON: logs\ovc_flujo_*.json
echo [INFO] Archivo TXT:  logs\ovc_flujo_*.txt
pause
