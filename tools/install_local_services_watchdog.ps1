# 同じWindows利用者で実行。サービス本体の再起動は行わない。
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repoRoot 'text-processing-bridge\.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe がありません' }
$service = Get-ScheduledTask -TaskName 'minutes-pipeline-local-services'
$settings = $service.Settings
$settings.StartWhenAvailable = $true
Set-ScheduledTask -TaskName $service.TaskName -Settings $settings | Out-Null
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"' + (Join-Path $PSScriptRoot 'local_services_watchdog.py') + '" --fix') -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$watchSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'minutes-pipeline-local-services-watchdog' -Action $action -Trigger $trigger -Settings $watchSettings -Principal $principal -Description '1分ごとに停止中のローカルサービスだけを起動。無効化したサービスは保守停止として尊重する。' -Force | Out-Null
# 詳細履歴の有効化は管理者権限が必要な場合がある。監視ログはこれと独立して残す。
& wevtutil.exe sl Microsoft-Windows-TaskScheduler/Operational /e:true
if ($LASTEXITCODE -ne 0) { Write-Warning 'Windowsのタスク詳細履歴は有効化できませんでした。監視ログには状態と終了コードを記録します。' }
Write-Output 'ローカルサービスの停止監視を登録しました（1分ごと、黒い窓なし）。'
