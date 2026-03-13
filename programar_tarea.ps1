$batPath = "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)\ovc_nocturno.bat"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""
$trigger = New-ScheduledTaskTrigger -Once -At "23:45"
Register-ScheduledTask -TaskName "OVC Monitor Nocturno" -Action $action -Trigger $trigger -Force
Write-Host "Tarea programada para las 11:45 PM de hoy." -ForegroundColor Green
