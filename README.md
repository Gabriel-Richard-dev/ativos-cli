# ATIVOS-CLI

Acompanhe pelo terminal a **data-com**, o **rendimento por cota** e a
**cotação-base** dos seus Fundos Imobiliários (FIIs). Os dados vêm do
[fiis.com.br](https://fiis.com.br) e ficam salvos localmente em SQLite.

```text
$ ativos
  Ativo    Data-com     Rendimento   Rend. %   Cotação-base   Pagamento
  ──────────────────────────────────────────────────────────────────────
  MXRF11   30/10/2026   R$ 0,095     1,071%    R$ 8,87        16/11/2026
  XPLG11   30/10/2026   R$ 0,82      0,912%    R$ 89,86       16/11/2026
```

## Instalação

**Mais fácil:** baixe o instalador do Windows (`ativos-setup-X.Y.Z.exe`) ou o
executável do Linux na página de
[Releases](https://github.com/Gabriel-Richard-dev/ativos-cli/releases/latest).
Não precisa de Python.

Passo a passo completo para Linux e Windows no **[manual de instalação](INSTALL.md)**.
A partir do código:

```sh
git clone https://github.com/Gabriel-Richard-dev/ativos-cli.git
cd ativos-cli
./install.sh                                              # Linux
powershell -ExecutionPolicy Bypass -File .\install.ps1    # Windows (PowerShell)
```

Os scripts usam o [uv](https://docs.astral.sh/uv/) (ou o pipx, se não houver uv).
Depois, abra um novo terminal e execute `ativos --help`.

Se você vai mexer no código, instale em modo editável para o comando acompanhar as
mudanças sem reinstalar: `uv tool install --editable --force .`

## Desinstalação

**Linux**

```sh
./uninstall.sh              # remove o comando e mantém carteira e histórico
./uninstall.sh --purge      # remove também os dados locais (pede confirmação)
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1          # mantém os dados
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge   # apaga também os dados
```

Os scripts detectam se o comando foi instalado com uv ou pipx. Para apagar os dados
sem confirmação, acrescente `-y` (Linux) ou `-Yes` (Windows).

## Uso

```sh
ativos                       # atualiza a carteira e mostra a tabela
ativos MXRF11                # consulta um ativo
ativos MXRF11 --detalhes     # consulta com todos os detalhes
ativos mxrf                  # sem ticker completo, pesquisa (o mesmo que `ativos search mxrf`)
ativos search "maxi renda"   # pesquisa por nome ou ticker aproximado
ativos add KNCR11            # adiciona à carteira
ativos remove KNCR11         # remove da carteira (mantém o histórico)
ativos remove KNCR11 --purge # remove e apaga o histórico
ativos refresh               # o mesmo que `ativos`, saindo com código 1 se algo falhar
ativos refresh MXRF11        # atualiza só um ativo
ativos history MXRF11        # histórico de consultas gravadas
ativos catalog update        # baixa a lista de fundos usada na pesquisa
ativos catalog status
```

Todos os comandos só imprimem o resultado no terminal, numa tabela simples. Em
terminais com menos de 76 colunas, a coluna Pagamento é omitida. `Rend. %` é o
rendimento em % da cotação-base (o dividend yield do mês), como o site informa,
cortado em 3 casas decimais (sem arredondar) já na coleta, então o `--json` e o
histórico também guardam 3 casas.

A tabela só mostra rendimentos com data-com no mês atual (ou depois). Se a data-com
mais recente de um ativo for de um mês anterior, a linha dele aparece com traços (`—`)
até sair a do mês. O `--json` continua trazendo o último dado, seja de que mês for.

### Em scripts

`show`, `refresh` e `search` aceitam `--json`. O `refresh` sai com código 1 se algum
ativo falhar. O único prompt é a confirmação do `remove`; pule com `-y` ou desligue
com `ATIVOS_NO_INPUT=1`.

## De onde vêm os dados

Os rendimentos vêm das fontes oficiais da B3:

| Campo exibido | Fonte | Observação |
|---|---|---|
| Data-com, Rendimento, Pagamento | Aviso aos Cotistas "Rendimentos e Amortizações" no [FundosNet](https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM) | XML estruturado publicado pelo próprio fundo; sai antes de qualquer site |
| Cotação-base | Arquivo diário de cotações da B3 (COTAHIST) | Preço de fechamento na data-com. A B3 publica o arquivo na manhã seguinte; até lá, vale a cotação do momento do [serviço de cotações da B3](https://cotacao.b3.com.br) (atraso de 15 min), marcada com `*` como provisória |
| Rend. % | Calculado | Rendimento ÷ cotação-base × 100, cortado em 3 casas (sem arredondar); com `*` quando a cotação é provisória |

O [fiis.com.br](https://fiis.com.br) só é usado para descobrir o nome e o CNPJ de cada
fundo (uma vez por fundo; o CNPJ localiza os avisos no FundosNet) e para a lista de
fundos da pesquisa.

**Cache e desempenho:** CNPJ, avisos já lidos (um aviso publicado não muda) e os
arquivos de cotações ficam em cache no diretório de dados (`cache/`). Numa atualização
com cache, sobra uma requisição por fundo (a busca dos avisos). Até 4 fundos são
consultados em paralelo.

**Boas práticas de acesso:** intervalo mínimo entre requisições ao mesmo site (0,25 s
no fiis.com.br e 0,1 s nos servidores da B3), no máximo 2 novas tentativas em caso de
falha, e identificação como `ativos-cli`. Só consulta quando você pede. O Status
Invest bloqueia acesso automatizado (Cloudflare) e por isso não é usado.

## Cache e falhas

- Toda consulta é gravada no histórico, com sucesso ou falha.
- Uma falha nunca apaga o último dado válido. A tabela mostra o dado anterior e,
  abaixo dela, o ativo que falhou com o motivo.
- Na consulta de um ativo, dados lidos do banco vêm com um aviso de quando foram
  coletados (e se têm mais de 24 horas).
- Remover da carteira mantém o histórico, exceto com `--purge`.

O banco fica no diretório de dados do usuário:

- Linux: `~/.local/share/ativos-cli/ativos.db`
- Windows: `%LOCALAPPDATA%\ativos-cli\ativos.db`

Use `ATIVOS_DATA_DIR` para escolher outro local.

## Solução de problemas

| Sintoma | O que fazer |
|---|---|
| `ativos: command not found` | Abra um novo terminal, ou rode `uv tool update-shell` / `pipx ensurepath` |
| "Catálogo ainda não foi baixado" | `ativos catalog update` |
| "Estrutura da página mudou" | O site mudou o layout. Os dados em cache continuam disponíveis; abra uma issue |
| "Limite de requisições atingido" | Espere alguns minutos e tente de novo |
| Cores estranhas ou ausentes | Defina `NO_COLOR=1` para saída sem cores |
| Quer ver o erro completo | `ativos --debug ...` (ou `ATIVOS_DEBUG=1`) |

## Desenvolvimento

```sh
uv sync                    # cria o ambiente com as dependências de dev
uv run ativos              # roda a partir do código
uv run pytest              # testes offline (fixtures HTML, sem internet)
uv run pytest -m network   # testes de integração com o site real
uv run ruff check . && uv run ruff format .
```

Estrutura:

```text
src/ativos_cli/
├── main.py            # entrada do comando (atalho `ativos TICKER`)
├── cli.py             # comandos Typer
├── config.py          # caminhos, URLs, limites de acesso
├── models/            # modelos Pydantic
├── services/          # regras de negócio, cache e pesquisa
├── scraper/           # FundosNet, cotações da B3, fiis.com.br (CNPJ e catálogo) e HTTP
├── repositories/      # SQLite: carteira, snapshots, catálogo
├── ui/                # tema, tabelas, prompts e tela da carteira
└── utils/             # datas e valores monetários
packaging/             # executável (PyInstaller) e instalador do Windows (Inno Setup)
.github/workflows/     # testes no Linux e no Windows; build das Releases
```


## Licença

MIT
