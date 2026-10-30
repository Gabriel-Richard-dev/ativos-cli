# Manual de instalação

Há dois jeitos de instalar o comando `ativos`:

- **Instalador ou executável pronto** (mais fácil): não precisa de Python, uv nem Git.
- **A partir do código** com o [uv](https://docs.astral.sh/uv/): bom para quem vai
  mexer no projeto ou quer sempre a versão mais recente do código.

---

## Instalador ou executável pronto

Baixe na página de
**[Releases](https://github.com/Gabriel-Richard-dev/ativos-cli/releases/latest)**.

### Windows: instalador

1. Baixe `ativos-setup-X.Y.Z.exe` e execute.
2. Se aparecer "O Windows protegeu o computador", clique em **Mais informações →
   Executar assim mesmo** (o instalador não é assinado digitalmente).
3. Avance até concluir. O instalador não pede administrador e põe o `ativos` no PATH.
4. Abra um **novo** PowerShell ou Prompt de Comando e rode `ativos MXRF11`.

Para desinstalar: **Configurações → Aplicativos → ATIVOS-CLI → Desinstalar**. A
carteira e o histórico ficam em `%LOCALAPPDATA%\ativos-cli\`; apague a pasta se quiser.

Também há o `ativos-windows-x86_64.exe` avulso, sem instalação: renomeie para
`ativos.exe` e coloque numa pasta que esteja no PATH (ou rode de onde estiver).

### Linux: executável

```sh
curl -L -o ativos https://github.com/Gabriel-Richard-dev/ativos-cli/releases/latest/download/ativos-linux-x86_64
chmod +x ativos
mkdir -p ~/.local/bin && mv ativos ~/.local/bin/
ativos MXRF11
```

Se `ativos` não for encontrado, adicione `~/.local/bin` ao PATH e abra um novo terminal.
O executável é para x86_64 e distros de 2022 em diante (glibc 2.35+). Para desinstalar,
apague `~/.local/bin/ativos`.

Na primeira execução de cada comando o executável demora um pouco mais para abrir,
porque descompacta seus arquivos internos.

---

# Instalação a partir do código

O uv baixa o Python certo e instala o programa num ambiente isolado, sem mexer no
Python do sistema.

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

Instalador ou executável: baixe a versão nova na página de Releases e instale por cima.

A partir do código, dentro da pasta do projeto:

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

---

## Gerar o executável e o instalador (para quem desenvolve)

```sh
uv run --with pyinstaller python packaging/build.py   # gera dist/ativos ou dist/ativos.exe
iscc /DAppVersion=1.0.0 packaging\ativos.iss          # Windows, com Inno Setup 6: dist/ativos-setup-1.0.0.exe
```

O executável só roda no sistema em que foi gerado. Por isso quem gera os arquivos das
Releases é o GitHub Actions (`.github/workflows/release.yml`): ao enviar uma tag
`vX.Y.Z` (igual à `version` do `pyproject.toml`), ele compila no Linux e no Windows,
monta o instalador e publica tudo na Release.

```sh
git tag v1.0.0 && git push origin v1.0.0
```
