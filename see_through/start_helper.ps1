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

if ($PythonExe.ToLower().EndsWith("pythonw.exe")) {
    $process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList "run.py" `
        -WorkingDirectory $AppHome `
        -PassThru
}
else {
    $process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList "run.py" `
        -WorkingDirectory $AppHome `
        -RedirectStandardOutput $StartupLog `
        -RedirectStandardError $StartupErrLog `
        -PassThru
}

Write-Output $process.Id
