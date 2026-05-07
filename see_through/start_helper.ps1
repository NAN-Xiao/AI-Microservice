param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [Parameter(Mandatory = $true)]
    [string]$AppHome,
    [Parameter(Mandatory = $true)]
    [string]$StartupLog,
    [Parameter(Mandatory = $true)]
    [string]$StartupErrLog
)

$process = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList "run.py" `
    -WorkingDirectory $AppHome `
    -RedirectStandardOutput $StartupLog `
    -RedirectStandardError $StartupErrLog `
    -PassThru

Write-Output $process.Id
