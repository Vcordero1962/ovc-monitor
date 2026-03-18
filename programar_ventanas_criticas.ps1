# programar_ventanas_criticas.ps1
# Programa 2 checks diarios en ventanas criticas desde IP residencial.
#
# Ventana 1: 02:55 AM Miami (= 8 AM Madrid CET, hora apertura oficina)
# Ventana 2: 05:55 PM Miami (= ~11 PM Madrid CET, cierre del dia)
#
# IMPORTANTE: Solo UNA ejecucion por ventana (NO loop continuo).
# ovc_once.py ya lleva jitter 10-90s para anti-deteccion.
#
# Ejecutar con: PowerShell -ExecutionPolicy Bypass -File programar_ventanas_criticas.ps1

$batPath = "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)\ovc_ventana_critica.bat"
$taskBase = "OVC Ventana Critica"

# --- Eliminar tareas antiguas si existen ---
$oldTasks = @("OVC Monitor Nocturno", "OVC Ventana Critica Manana", "OVC Ventana Critica Tarde")
foreach ($t in $oldTasks) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Host "Tarea eliminada: $t" -ForegroundColor Yellow
    }
}

# --- Accion comun: ejecutar el BAT ---
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"

# --- Configuracion comun ---
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

# --- Ventana 1: 02:55 AM (= 8 AM Madrid CET) ---
$trigger1 = New-ScheduledTaskTrigger -Daily -At "02:55"
Register-ScheduledTask `
    -TaskName "OVC Ventana Critica Manana" `
    -Action $action `
    -Trigger $trigger1 `
    -Settings $settings `
    -Description "OVC check diario 02:55 AM Miami = 08:00 AM Madrid (apertura consulado)" `
    -Force | Out-Null
Write-Host "Ventana 1 programada: 02:55 AM Miami (8 AM Madrid)" -ForegroundColor Green

# --- Ventana 2: 05:55 PM (= ~11 PM Madrid CET, liberan slots del dia siguiente) ---
$trigger2 = New-ScheduledTaskTrigger -Daily -At "17:55"
Register-ScheduledTask `
    -TaskName "OVC Ventana Critica Tarde" `
    -Action $action `
    -Trigger $trigger2 `
    -Settings $settings `
    -Description "OVC check diario 05:55 PM Miami = ~11 PM Madrid (liberacion nocturna)" `
    -Force | Out-Null
Write-Host "Ventana 2 programada: 05:55 PM Miami (~11 PM Madrid)" -ForegroundColor Green

Write-Host ""
Write-Host "=== Configuracion activa ===" -ForegroundColor Cyan
Write-Host "  Checks por dia: 2 (una ejecucion por ventana)"
Write-Host "  Requests por check: ~21 HTTP (7 servicios x GET+POST+JSONP)"
Write-Host "  Jitter inicial: 10-90 seg (anti-deteccion automatico)"
Write-Host "  Modo: BOOKITIT_POST solo (sin Playwright, sin proxy)"
Write-Host "  Logs: M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)\logs\"
Write-Host ""
Write-Host "Tareas activas:" -ForegroundColor Cyan
Get-ScheduledTask | Where-Object { $_.TaskName -like "OVC*" } | Format-Table TaskName, State -AutoSize
