## 服务守护脚本：监控 video_analyze 服务，崩溃自动重启。
## 用法：powershell -File watchdog.ps1

$ServiceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HealthUrl = "http://127.0.0.1:9001/api/video-analyze/health"
$CheckInterval = 10   # 每 10 秒检查一次
$StartWait = 5        # 启动后等几秒再检查

$process = $null

function Start-Service {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 启动服务..." -ForegroundColor Green
    $script:process = Start-Process -FilePath "python" `
        -ArgumentList "app.py" `
        -WorkingDirectory $ServiceDir `
        -PassThru -NoNewWindow
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 服务已启动, PID=$($script:process.Id)"
    Start-Sleep -Seconds $StartWait
}

function Test-Health {
    try {
        $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 5 -ErrorAction Stop
        return $resp.code -eq 200
    } catch {
        return $false
    }
}

# 首次启动
Start-Service

# 持续监控
while ($true) {
    Start-Sleep -Seconds $CheckInterval

    $alive = -not $process.HasExited
    $healthy = Test-Health

    if (-not $alive -or -not $healthy) {
        if (-not $alive) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 服务进程已退出!" -ForegroundColor Red
        } else {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 健康检查失败，强制重启" -ForegroundColor Yellow
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
        Start-Service
    }
}
