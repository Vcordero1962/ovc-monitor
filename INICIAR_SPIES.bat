@echo off
chcp 65001 > nul
title OVC — Iniciando Spies
color 0A

echo ================================================================
echo   OVC — INICIANDO SPIES EN SEGUNDO PLANO
echo ================================================================
echo.

cd /d "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"

:: Anti-suspension: mantiene el PC despierto mientras los spies corren
:: Usa SetThreadExecutionState via PowerShell (sin admin requerido)
echo [0/2] Activando modo anti-suspension (PC no dormira mientras spies esten activos)...
start "OVC_ANTI_SLEEP" /min powershell -WindowStyle Hidden -Command ^
  "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class OvcSleep { [DllImport(\"kernel32.dll\")] public static extern uint SetThreadExecutionState(uint e); }'; while($true) { [OvcSleep]::SetThreadExecutionState([uint32]0x80000003); Start-Sleep -Seconds 60; }"
echo     OK — sistema no se suspendera automaticamente

echo.
echo [1/2] Iniciando OVC SPY CONTINUO (LEGA, cada 5 min, alerta Telegram)...
start "OVC_SPY_CONTINUO" /min C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_spy.py --continuo --intervalo 300 --alerta
echo     OK — ventana minimizada en la barra de tareas

echo.
echo [2/2] Iniciando AVC INTEL CONTINUO (canal AVC, cada 10 min)...
start "AVC_INTEL_CONTINUO" /min C:\Users\aemes\anaconda3\python.exe -X utf8 ovc_avc_intel.py --continuo --intervalo 600
echo     OK — ventana minimizada en la barra de tareas

echo.
echo ================================================================
echo   AMBOS SPIES CORRIENDO EN SEGUNDO PLANO
echo.
echo   OVC SPY   : logs\ovc_spy_continuo_*.log
echo   AVC INTEL : logs\avc_intel_continuo_*.log
echo   ANTI-SLEEP: activo (ventana OVC_ANTI_SLEEP en barra de tareas)
echo.
echo   Para detenerlos: cerrar sus ventanas en la barra de tareas
echo   o Administrador de Tareas ^> python.exe / powershell.exe ^> Finalizar tarea
echo.
echo   IMPORTANTE: OVC_ANTI_SLEEP se debe cerrar junto con los spies
echo   para restaurar la suspension normal del sistema.
echo ================================================================
echo.
pause
