@echo off
title OVC NOCTURNO - Monitor Citas Consulado
echo ============================================
echo   OVC NOCTURNO - Ventana Critica Medianoche
echo   Intervalo: 2-3 minutos (modo agresivo)
echo ============================================

cd /d "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"

:: Sobreescribir intervalos para modo nocturno agresivo
set INTERVALO_MIN=120
set INTERVALO_MAX=180

C:\Users\aemes\anaconda3\python.exe -B ovc_monitor.py
pause
