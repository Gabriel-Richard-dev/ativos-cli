#!/usr/bin/env sh
# Desinstala o comando `ativos` (instalado com uv ou pipx).
# Uso: ./uninstall.sh            remove o comando e mantém carteira e histórico
#      ./uninstall.sh --purge    remove também os dados locais (pede confirmação)
#      ./uninstall.sh --purge -y remove os dados sem perguntar
set -eu

PURGE=0
YES=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        -y|--yes) YES=1 ;;
        -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Opção desconhecida: $arg" >&2; exit 2 ;;
    esac
done

# Mesmo local usado pela aplicação (platformdirs), respeitando ATIVOS_DATA_DIR.
DATA_DIR="${ATIVOS_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/ativos-cli}"

REMOVED=0
if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q '^ativos-cli '; then
    echo "Removendo ativos-cli (uv)..."
    uv tool uninstall ativos-cli
    REMOVED=1
fi
if command -v pipx >/dev/null 2>&1 && pipx list --short 2>/dev/null | grep -q '^ativos-cli '; then
    echo "Removendo ativos-cli (pipx)..."
    pipx uninstall ativos-cli
    REMOVED=1
fi
if [ "$REMOVED" -eq 0 ]; then
    echo "O comando ativos não está instalado via uv nem pipx."
fi

if [ "$PURGE" -eq 1 ]; then
    if [ ! -d "$DATA_DIR" ]; then
        echo "Nenhum dado local encontrado em $DATA_DIR."
    else
        if [ "$YES" -eq 0 ]; then
            printf "Apagar carteira e histórico em %s? [s/N] " "$DATA_DIR"
            read -r answer || answer=""
            case "$answer" in
                s|S|y|Y) ;;
                *) echo "Dados mantidos."; exit 0 ;;
            esac
        fi
        rm -rf "$DATA_DIR"
        echo "Dados locais apagados."
    fi
elif [ -d "$DATA_DIR" ]; then
    echo "Sua carteira e o histórico foram mantidos em $DATA_DIR."
    echo "Para apagá-los também: ./uninstall.sh --purge"
fi
