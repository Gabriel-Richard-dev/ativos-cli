#!/usr/bin/env sh
# Instala o comando `ativos` no Linux (e macOS) usando uv, ou pipx como alternativa.
# Uso: ./install.sh        (dentro da pasta do projeto)
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"

if command -v uv >/dev/null 2>&1; then
    echo "Instalando ativos-cli com uv..."
    uv tool install --force --reinstall "$DIR"
    uv tool update-shell >/dev/null 2>&1 || true
elif command -v pipx >/dev/null 2>&1; then
    echo "Instalando ativos-cli com pipx..."
    pipx install --force "$DIR"
    pipx ensurepath >/dev/null 2>&1 || true
else
    echo "Nem uv nem pipx foram encontrados."
    echo "Instale o uv (recomendado) e rode este script de novo:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo
echo "Pronto. Abra um novo terminal e execute: ativos --help"
