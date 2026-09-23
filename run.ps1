$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot "logitrack-run.log"
Start-Transcript -Path $log -Force | Out-Null

Write-Host "=============================================="
Write-Host " LogiTrack - arranque automatico"
Write-Host "=============================================="

Write-Host "`n=== 1. Docker disponible? ==="
docker version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker no responde. Abre Docker Desktop, espera a que el icono quede verde y vuelve a ejecutar este archivo."
    Stop-Transcript | Out-Null
    exit 1
}

Write-Host "`n=== 2. Construyendo y levantando los contenedores ==="
docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: fallo 'docker compose up'. Revisa el mensaje de arriba."
    Stop-Transcript | Out-Null
    exit 1
}

Write-Host "`n=== 3. Esperando a que los servicios queden listos (hasta 5 min) ==="
$deadline = (Get-Date).AddMinutes(5)
$ready = $false
do {
    Start-Sleep -Seconds 6
    $ready = $true
    foreach ($url in @("http://localhost:8001/ready", "http://localhost:8006/ready")) {
        try {
            $r = Invoke-RestMethod -Uri $url -TimeoutSec 4
            Write-Host ("  {0} -> {1}" -f $url, $r.status)
            if ($r.status -ne "ready") { $ready = $false }
        } catch {
            Write-Host ("  {0} -> todavia no responde" -f $url)
            $ready = $false
        }
    }
} while (-not $ready -and (Get-Date) -lt $deadline)

Write-Host "`n--- estado de los contenedores ---"
docker compose ps

if (-not $ready) {
    Write-Host "`nTIMEOUT: los servicios no quedaron listos. Ultimos logs:"
    docker compose logs --tail=60
    Stop-Transcript | Out-Null
    exit 1
}

Write-Host "`n=== 4. Dependencias de Python para los scripts ==="
$py = $null
if (Get-Command python -ErrorAction SilentlyContinue) { $py = "python" }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $py = "py" }

if ($null -eq $py) {
    Write-Host "AVISO: Python no esta en el PATH. Los contenedores YA estan corriendo:"
    Write-Host "  Fleet:       http://localhost:8001/docs"
    Write-Host "  Maintenance: http://localhost:8006/docs"
    Write-Host "  RabbitMQ:    http://localhost:15672  (logitrack / logitrack)"
    Write-Host "Solo faltan seed.py y demo_e2e.py, que necesitan Python instalado."
    Stop-Transcript | Out-Null
    exit 0
}

& $py -m pip install --quiet --disable-pip-version-check requests pika

Write-Host "`n=== 5. Datos iniciales (seed) ==="
& $py scripts\seed.py

Write-Host "`n=== 6. Prueba end-to-end ==="
& $py scripts\demo_e2e.py

Write-Host "`n=============================================="
Write-Host " Listo. Abre en el navegador:"
Write-Host "   Fleet:       http://localhost:8001/docs"
Write-Host "   Maintenance: http://localhost:8006/docs"
Write-Host "   RabbitMQ:    http://localhost:15672  (logitrack / logitrack)"
Write-Host "=============================================="

Stop-Transcript | Out-Null
