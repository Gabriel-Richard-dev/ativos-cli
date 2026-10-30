# Instala o comando `ativos` no Windows usando uv, ou pipx como alternativa.
# Uso (PowerShell, dentro da pasta do projeto):
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
$Dir = $PSScriptRoot

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Instalando ativos-cli com uv..."
    uv tool install --force --reinstall "$Dir"
    uv tool update-shell | Out-Null
}
elseif (Get-Command pipx -ErrorAction SilentlyContinue) {
    Write-Host "Instalando ativos-cli com pipx..."
    pipx install --force "$Dir"
    pipx ensurepath | Out-Null
}
else {
    Write-Host "Nem uv nem pipx foram encontrados."
    Write-Host "Instale o uv (recomendado) e rode este script de novo:"
    Write-Host '  powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    exit 1
}

Write-Host ""
Write-Host "Pronto. Abra um novo terminal e execute: ativos --help"
