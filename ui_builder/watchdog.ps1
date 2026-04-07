# ui_builder watchdog
# 调用 LLM 前请在系统或本脚本中设置: $env:LLM_API_KEY = "你的密钥"
# 可选: $env:LLM_API_URL = "https://aikey.elex-tech.com/v1"
# 可选: $env:LLM_MODEL = "gemini-2.5-pro"

$ServiceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HealthUrl = "http://127.0.0.1:9002/api/ui-builder/health"
$CheckInterval = 10
$StartWait = 5
$Process = $null

function Start-Service {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting ui_builder..."
    $script:Process = Start-Process -FilePath "python" `
        -ArgumentList "app.py" `
        -WorkingDirectory $ServiceDir `
        -PassThru -NoNewWindow
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] PID: $($script:Process.Id)"
    Start-Sleep -Seconds $StartWait
}

function Test-Health {
    try {
        $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 5
        return ($resp.code -eq 200)
    } catch {
        return $false
    }
}

Start-Service

while ($true) {
    Start-Sleep -Seconds $CheckInterval

    if ($Process.HasExited) {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Process exited (code $($Process.ExitCode)), restarting..."
        Start-Service
        continue
    }

    if (-not (Test-Health)) {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Health check failed, restarting..."
        try { Stop-Process -Id $Process.Id -Force } catch {}
        Start-Sleep -Seconds 2
        Start-Service
    }
}
