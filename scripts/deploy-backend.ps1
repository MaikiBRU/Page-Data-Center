# Despliega el backend desde Windows, en un solo comando.
#
#   .\scripts\deploy-backend.ps1
#
# Se conecta por SSH a la instancia y ejecuta scripts/deploy-backend.sh alli,
# que respalda la base, trae el commit, reconstruye y verifica.
#
# Existe porque la forma "manual" son dos comandos encadenados con una ruta
# relativa a la clave, y falla si no se corre exactamente desde el directorio
# donde esta el .pem.

[CmdletBinding()]
param(
    # Ruta a la clave privada de EC2. Por defecto la busca junto al proyecto.
    [string]$Clave = "$PSScriptRoot\..\..\data-center-api-key.pem",

    [string]$Host_ = "3.15.143.154",
    [string]$Usuario = "ubuntu",

    # Directorio de la aplicacion en el servidor.
    [string]$DirRemoto = "data-center",

    # Solo comprueba el estado, sin desplegar.
    [switch]$SoloVerificar
)

$ErrorActionPreference = "Stop"

function Fallo($mensaje) {
    Write-Host $mensaje -ForegroundColor Red
    exit 1
}

# --- la clave -----------------------------------------------------------
$Clave = [System.IO.Path]::GetFullPath($Clave)
if (-not (Test-Path $Clave)) {
    Fallo @"
No se encuentra la clave privada en:
  $Clave

Pasa la ruta correcta:
  .\scripts\deploy-backend.ps1 -Clave 'C:\ruta\a\data-center-api-key.pem'
"@
}

# OpenSSH de Windows rechaza una clave que otros usuarios puedan leer. Se
# corrige sobre una copia temporal para no alterar el archivo original.
$Temporal = Join-Path $env:TEMP ("dc-key-" + [guid]::NewGuid().ToString("N") + ".pem")
Copy-Item $Clave $Temporal
icacls $Temporal /inheritance:r | Out-Null
icacls $Temporal /grant:r "$($env:USERNAME):(R)" | Out-Null

try {
    Write-Host "==> Conectando a $Usuario@$Host_" -ForegroundColor Cyan

    $comando = if ($SoloVerificar) {
        "cd $DirRemoto && git log --oneline -1 && curl -s -o /dev/null -w 'health=%{http_code}\n' http://127.0.0.1:8000/health"
    } else {
        "cd $DirRemoto && git fetch -q origin codex/public-clean && git reset --hard -q origin/codex/public-clean && chmod +x scripts/deploy-backend.sh && ./scripts/deploy-backend.sh"
    }

    & ssh -i $Temporal -o StrictHostKeyChecking=accept-new "$Usuario@$Host_" $comando
    $codigo = $LASTEXITCODE

    if ($codigo -ne 0) {
        Fallo "`nEl despliegue fallo (codigo $codigo). El script remoto deja la version anterior en pie y muestra como volver atras."
    }

    Write-Host "`n==> Comprobando desde fuera" -ForegroundColor Cyan
    foreach ($ruta in @("/health", "/demo/config")) {
        $r = curl.exe -s -o NUL -w "%{http_code}" --max-time 25 "https://api-datacenter.aaronbrumat.com.ar$ruta"
        $color = if ($r -eq "200") { "Green" } else { "Red" }
        Write-Host ("  {0,-16} {1}" -f $ruta, $r) -ForegroundColor $color
    }
    # En produccion la documentacion y el registro publico no deben existir.
    foreach ($ruta in @("/docs", "/openapi.json")) {
        $r = curl.exe -s -o NUL -w "%{http_code}" --max-time 25 "https://api-datacenter.aaronbrumat.com.ar$ruta"
        $color = if ($r -eq "404") { "Green" } else { "Red" }
        Write-Host ("  {0,-16} {1} (se espera 404)" -f $ruta, $r) -ForegroundColor $color
    }

    Write-Host "`nListo." -ForegroundColor Green
}
finally {
    Remove-Item $Temporal -Force -ErrorAction SilentlyContinue
}
