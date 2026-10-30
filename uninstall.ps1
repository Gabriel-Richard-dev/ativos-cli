# Desinstala o comando `ativos` (instalado com uv ou pipx) no Windows.
# Uso (PowerShell, dentro da pasta do projeto):
#   powershell -ExecutionPolicy Bypass -File .\uninstall.ps1             remove o comando, mantém os dados
#   powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge      remove também os dados (pede confirmação)
#   powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge -Yes remove os dados sem perguntar
param(
    [switch]$Purge,
    [switch]$Yes
)
$ErrorActionPreference = "Stop"

# Mesmo local usado pela aplicação (platformdirs), respeitando ATIVOS_DATA_DIR.
$DataDir = if ($env:ATIVOS_DATA_DIR) { $env:ATIVOS_DATA_DIR } else { Join-Path $env:LOCALAPPDATA "ativos-cli" }

$Removed = $false
if (Get-Command uv -ErrorAction SilentlyContinue) {
    if (uv tool list 2>$null | Select-String -Pattern "^ativos-cli " -Quiet) {
        Write-Host "Removendo ativos-cli (uv)..."
        uv tool uninstall ativos-cli
        $Removed = $true
    }
}
if (Get-Command pipx -ErrorAction SilentlyContinue) {
    if (pipx list --short 2>$null | Select-String -Pattern "^ativos-cli " -Quiet) {
        Write-Host "Removendo ativos-cli (pipx)..."
        pipx uninstall ativos-cli
        $Removed = $true
    }
}
if (-not $Removed) {
    Write-Host "O comando ativos não está instalado via uv nem pipx."
}

if ($Purge) {
    if (-not (Test-Path $DataDir)) {
        Write-Host "Nenhum dado local encontrado em $DataDir."
    }
    else {
        if (-not $Yes) {
            $answer = Read-Host "Apagar carteira e histórico em $DataDir? [s/N]"
            if ($answer -notmatch '^[sSyY]$') {
                Write-Host "Dados mantidos."
                exit 0
            }
        }
        Remove-Item -Recurse -Force $DataDir
        Write-Host "Dados locais apagados."
    }
}
elseif (Test-Path $DataDir) {
    Write-Host "Sua carteira e o histórico foram mantidos em $DataDir."
    Write-Host "Para apagá-los também: .\uninstall.ps1 -Purge"
}
