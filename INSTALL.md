# Manual de instalação

Este guia instala o comando `ativos` no Linux e no Windows. O jeito recomendado usa o
[uv](https://docs.astral.sh/uv/), que baixa o Python certo e instala o programa num
ambiente isolado, sem mexer no Python do sistema.

Requisitos: conexão com a internet e o [Git](https://git-scm.com/) (ou baixe o projeto
como ZIP pelo GitHub). O Python 3.11+ é instalado pelo uv se você ainda não tiver.

---

## Linux

### 1. Instale o uv (se ainda não tiver)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Feche e abra o terminal para o comando `uv` ficar disponível. Confira com `uv --version`.

### 2. Baixe o projeto

```sh
git clone https://github.com/Gabriel-Richard-dev/ativos-cli.git
cd ativos-cli
```

### 3. Instale

```sh
./install.sh
```

Se aparecer "Permissão negada", rode `sh install.sh`.

### 4. Teste

Abra um novo terminal e execute:

```sh
ativos --help
ativos MXRF11
```

---

## Windows

Use o **PowerShell** (menu Iniciar → "PowerShell").

### 1. Instale o uv (se ainda não tiver)

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Feche e abra o PowerShell. Confira com `uv --version`.

### 2. Baixe o projeto

Com Git:

```powershell
git clone https://github.com/Gabriel-Richard-dev/ativos-cli.git
cd ativos-cli
```

Sem Git: no GitHub, clique em **Code → Download ZIP**, extraia e abra o PowerShell
dentro da pasta extraída.

### 3. Instale

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### 4. Teste

Abra um novo PowerShell e execute:

```powershell
ativos --help
ativos MXRF11
```

---

## Sem os scripts (Linux e Windows)

Os scripts só automatizam um destes comandos, rodados dentro da pasta do projeto:

```sh
uv tool install .      # com uv
pipx install .         # ou com pipx, se preferir
```

Também dá para instalar direto do GitHub, sem clonar:

```sh
uv tool install git+https://github.com/Gabriel-Richard-dev/ativos-cli.git
```

## Atualizar

Dentro da pasta do projeto:

```sh
git pull
./install.sh                                              # Linux
powershell -ExecutionPolicy Bypass -File .\install.ps1    # Windows
```

Se instalou direto do GitHub: `uv tool upgrade ativos-cli`.

## Desinstalar

```sh
./uninstall.sh                                                   # Linux, mantém carteira e histórico
./uninstall.sh --purge                                           # Linux, apaga também os dados
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1         # Windows, mantém os dados
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge  # Windows, apaga também os dados
```

Os dados ficam em `~/.local/share/ativos-cli/` (Linux) ou
`%LOCALAPPDATA%\ativos-cli\` (Windows).

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `ativos: command not found` / "não é reconhecido como comando" | Abra um novo terminal. Se continuar, rode `uv tool update-shell` e abra outro terminal |
| `uv: command not found` | Refaça o passo 1 e abra um novo terminal |
| Windows: "a execução de scripts foi desabilitada" | Use exatamente o comando com `-ExecutionPolicy Bypass` mostrado acima |
| Linux: "Permissão negada" no `./install.sh` | `sh install.sh` |
| Acentos ou cores estranhas | Use o Windows Terminal; ou defina `NO_COLOR=1` |
