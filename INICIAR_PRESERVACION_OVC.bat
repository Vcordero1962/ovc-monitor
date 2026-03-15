@echo off
title OVC — Sistema de Preservacion y Sentinel
echo =================================================
echo   OVC — PRESERVACION DEL ENTORNO
echo   Orquestador de Vigilancia Consular
echo =================================================
echo.

set OVC_DIR=M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)
set SENTINEL_DIR=%OVC_DIR%\ovc_sentinel

echo [1/4] Verificando Git status...
cd /D "%OVC_DIR%"
git status --short
if errorlevel 1 (
    echo [WARN] Git no disponible o no es repo. Verificar.
) else (
    echo [OK] Git operativo.
)
echo.

echo [2/4] Verificando estado del bot en GitHub Actions...
where gh >nul 2>&1
if errorlevel 1 (
    echo [WARN] gh CLI no encontrado. Instalar: https://cli.github.com/
    echo        Saltando verificacion de GitHub Actions.
) else (
    echo [INFO] Ultimos runs del bot:
    gh run list --repo Vcordero1962/ovc-monitor --limit 3 2>nul
    if errorlevel 1 (
        echo [WARN] No se pudo consultar GitHub Actions. Verificar GITHUB_TOKEN en .env
    )
)
echo.

echo [3/4] Verificando Docker...
docker ps >nul 2>&1
if errorlevel 1 (
    echo [WARN] Docker no responde. Inicia Docker Desktop primero.
    echo        El sentinel NO estara activo hasta que Docker este corriendo.
    goto fin
)
echo [OK] Docker activo.
echo.

echo [4/4] Verificando sentinel OVC...
docker ps --filter "name=ovc-sentinel" --format "{{.Names}}\t{{.Status}}" | find "ovc-sentinel" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Sentinel no esta corriendo. Iniciando...
    cd /D "%SENTINEL_DIR%"
    docker-compose up -d
    if errorlevel 1 (
        echo [ERROR] No se pudo iniciar el sentinel.
        echo         Verifica que ovc_sentinel/docker-compose.yml existe.
    ) else (
        timeout /t 5 /nobreak >nul
        echo [OK] Sentinel iniciado.
        docker logs ovc-sentinel --tail 10
    )
) else (
    echo [OK] Sentinel ya corriendo:
    docker ps --filter "name=ovc-sentinel" --format "  {{.Names}} — {{.Status}}"
    echo.
    echo [INFO] Ultimos logs del sentinel:
    docker logs ovc-sentinel --tail 15
)

:fin
echo.
echo =================================================
echo   ESTADO FINAL
echo =================================================
echo.
echo   Bot GitHub Actions : verificar arriba
echo   Sentinel Docker    : docker ps ^| grep ovc-sentinel
echo   Logs sentinel      : docker logs ovc-sentinel --tail 50 -f
echo   Logs bot Actions   : gh run list --repo Vcordero1962/ovc-monitor
echo.
echo   Grupo Telegram     : OVC Alertas Consulado (-5127911137)
echo   Heartbeat          : cada 4h (0,4,8,12,16,20 Miami)
echo.
cd /D "%OVC_DIR%"
echo [LISTO] Directorio actual: %CD%
echo.
pause
