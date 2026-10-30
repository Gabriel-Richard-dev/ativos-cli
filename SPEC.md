# ATIVOS-CLI — Especificação Técnica Completa

**Versão:** 1.0.0  
**Tipo:** Aplicação CLI (Command-Line Interface)  
**Linguagem:** Python 3.11+  
**Plataformas:** Windows 10/11 e Linux  
**Fonte de dados:** fiis.com.br (o Status Invest foi descartado; ver seção 2)  
**Persistência:** SQLite local  
**Interface:** Rich + Typer + prompt_toolkit

## 1. Visão geral

O ATIVOS-CLI é uma ferramenta de linha de comando para consultar, acompanhar e organizar ativos financeiros, com foco inicial em Fundos de Investimento Imobiliário (FIIs).

A aplicação utilizará Scrapy para coletar dados públicos do fiis.com.br e apresentará os resultados em uma interface de terminal moderna, limpa e intuitiva.

O principal objetivo é facilitar o acompanhamento das datas-base de rendimentos, permitindo que o usuário consulte ativos individualmente, pesquise por nomes aproximados e mantenha uma carteira local atualizada.

O sistema deverá funcionar nativamente no Windows e Linux, sem depender de navegador gráfico, Docker, WSL ou serviços externos para persistência.

### Objetivos principais

- Consultar a data-base de rendimentos (`datacom`).
- Consultar o rendimento por cota.
- Consultar a cotação-base.
- Pesquisar ativos por ticker ou nome aproximado.
- Manter uma carteira local de ativos.
- Atualizar os dados da carteira sob demanda.
- Permitir inclusão e remoção de ativos pelo teclado.
- Exibir os resultados em tabelas organizadas e visualmente agradáveis.
- Preservar os últimos dados válidos quando uma consulta falhar.
- Oferecer comandos adequados tanto para uso interativo quanto para scripts.

## 2. Fonte de dados

O site utilizado para a coleta será:

`https://fiis.com.br/{ticker}/`

Exemplo:

`https://fiis.com.br/mxrf11/`

O ticker deverá ser normalizado antes de compor a URL.

> **Mudança de fonte (29/10/2026).** A fonte prevista originalmente era o Status Invest
> (`https://statusinvest.com.br/fundos-imobiliarios/{ticker}`). Na Fase 1, verificou-se que o site
> responde HTTP 403 com um desafio anti-bot do Cloudflare a qualquer acesso automatizado.
> Contornar essa proteção não é compatível com as políticas de acesso do site, e por isso a
> fonte passou a ser o fiis.com.br. Esse site responde normalmente, o `robots.txt` permite o
> acesso (`Allow: /`) e a página de cada fundo traz os campos necessários em JSON estruturado.
>
> Campos utilizados (objeto `dataLayer_content.pagePostTerms.meta`):
>
> | Campo | Origem no fiis.com.br |
> |---|---|
> | Data-base | `pr_database` (próximo rendimento) ou `ur_data_base` (último), o mais recente |
> | Rendimento | `pr_valor` / `ur_valor` |
> | Cotação-base | `pr_cotacaobase` / `ur_cotacao_base` |
> | Data de pagamento | `pr_datapagamento` / `ur_data_pagamento` |
> | Nome | `nome_pregao` |
> | Catálogo | índice `data-island="search"`, presente em todas as páginas |
>
> Ticker inexistente responde HTTP 404. A coleta respeita o `robots.txt`, faz uma requisição
> por vez com 1 s de intervalo e se identifica como `ativos-cli`.

A implementação deverá verificar a estrutura real das páginas para identificar os seletores e os campos responsáveis pelas informações desejadas.

Caso os dados sejam carregados por JavaScript ou não estejam presentes no HTML inicial, a implementação deverá investigar alternativas técnicas compatíveis com as políticas de acesso do site, sem presumir que um seletor ou endpoint permanecerá estável.

A aplicação deverá identificar claramente erros de extração e não apresentar valores fictícios como se fossem dados reais.

## 3. Comandos da CLI

O comando principal da aplicação será `ativos`.

### 3.1. Abrir a carteira

```bash
ativos
```

Comportamento:

1. Carregar a carteira armazenada no SQLite.
2. Consultar os dados atualizados de cada ativo.
3. Exibir os resultados em uma tabela única.
4. Indicar quais ativos foram atualizados e quais apresentaram falha.
5. Permitir navegar, pesquisar, adicionar e remover ativos.
6. Preservar os últimos dados válidos em caso de falha.

Se a carteira estiver vazia, a aplicação deverá exibir uma mensagem amigável e oferecer a opção de pesquisar e adicionar um ativo.

### 3.2. Consultar um ativo

```bash
ativos MXRF11
```

O comando deverá:

1. Validar o ticker.
2. Consultar a página correspondente no fiis.com.br.
3. Extrair os campos prioritários.
4. Normalizar os valores.
5. Exibir o resultado em uma tabela com uma linha para o ativo.
6. Perguntar se o usuário deseja adicionar o ativo à carteira, quando estiver em modo interativo.

Se o ativo já estiver na carteira, a aplicação deverá informar isso sem criar duplicatas.

### 3.3. Pesquisar por nome ou ticker aproximado

```bash
ativos search mxrf
ativos search "maxi renda"
ativos search kncr
```

A pesquisa deverá:

1. Normalizar o termo informado.
2. Pesquisar em um catálogo local de ativos.
3. Comparar o termo com tickers e nomes.
4. Ordenar os resultados por relevância.
5. Apresentar os resultados em uma tabela.
6. Permitir selecionar um ativo e abrir sua consulta.
7. Permitir adicionar diretamente um resultado à carteira.

A pesquisa aproximada deverá utilizar um catálogo local atualizado por uma rotina própria. A aplicação não deverá depender exclusivamente de abrir páginas individuais para descobrir quais ativos existem.

Caso o catálogo ainda não exista ou esteja desatualizado, o sistema deverá informar essa limitação e oferecer uma forma de atualizá-lo quando disponível.

### 3.4. Adicionar e remover ativos

```bash
ativos add MXRF11
ativos remove MXRF11
```

A inclusão deverá validar o ativo e impedir duplicatas.

A remoção deverá solicitar confirmação em modo interativo, especialmente quando o ativo possuir histórico de consultas armazenado.

A remoção da carteira não deverá apagar automaticamente o histórico, a menos que o usuário solicite explicitamente essa operação.

### 3.5. Atualização explícita

```bash
ativos refresh
ativos refresh MXRF11
```

- Sem ticker: atualiza todos os ativos da carteira.
- Com ticker: atualiza apenas o ativo informado.

O sistema deverá mostrar o progresso da operação e um resumo de sucesso e falhas.

### 3.6. Ajuda

```bash
ativos --help
ativos --version
```

A CLI deverá documentar os comandos disponíveis e apresentar exemplos de utilização.

## 4. Interface visual

A interface deverá ser inteiramente baseada em terminal, com visual moderno e discreto.

### 4.1. Diretrizes de design

- Utilizar Rich para tabelas, painéis, mensagens e indicadores de progresso.
- Utilizar cores com moderação.
- Priorizar legibilidade e alinhamento.
- Evitar excesso de bordas, ícones ou elementos decorativos.
- Adaptar a largura das tabelas ao terminal.
- Preservar a compatibilidade com terminais que ofereçam suporte limitado a cores.
- Não depender de uma interface gráfica ou de um navegador controlado manualmente.

A aplicação deverá usar um tema visual consistente em todas as telas.

### 4.2. Consulta individual

Ao executar `ativos MXRF11`, a aplicação deverá apresentar uma tabela compacta, contendo uma linha por ativo.

Exemplo ilustrativo:

```text
╭────────────────────────────────────────────────────────────────╮
│  ATIVOS-CLI                                      CONSULTA       │
│  fiis.com.br                                                    │
╰────────────────────────────────────────────────────────────────╯

  MXRF11 — Maxi Renda

┏━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Ativo  ┃ Data-base  ┃ Rendimento ┃ Cotação-base ┃
┡━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ MXRF11 │ 30/10/2026 │ R$ 0,10    │ R$ 9,01      │
└────────┴────────────┴────────────┴──────────────┘

  Adicionar MXRF11 à carteira?

  [S] Sim    [N] Não
```

Os valores são apenas ilustrativos.

Requisitos:

- A data-base deverá receber destaque visual, preferencialmente em ciano.
- O ticker poderá receber destaque moderado.
- Rendimento e cotação-base deverão permanecer em texto normal, sem negrito.
- Os valores deverão ser obtidos na consulta real.
- Campos indisponíveis deverão aparecer como `N/D`.
- O horário da última atualização poderá aparecer abaixo da tabela.
- O prompt de inclusão deverá ser exibido apenas quando fizer sentido no contexto.

### 4.3. Visualização da carteira

Ao executar `ativos`, todos os ativos salvos deverão ser apresentados em uma tabela única.

Exemplo ilustrativo:

```text
╭──────────────────────────────────────────────────────────────────────────────╮
│  ATIVOS-CLI                                             MINHA CARTEIRA       │
│  Acompanhamento de rendimentos e datas-base                                 │
╰──────────────────────────────────────────────────────────────────────────────╯

  Ativos: 3     Atualização: concluída

┏━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Ativo  ┃ Data-base  ┃ Rendimento ┃ Cotação-base ┃ Status     ┃
┡━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ MXRF11 │ 30/10/2026 │ R$ 0,10    │ R$ 9,01      │ Atualizado │
│ KNCR11 │ 29/10/2026 │ R$ 1,15    │ R$ 105,92    │ Atualizado │
│ XPML11 │ 15/10/2026 │ R$ 0,92    │ R$ 109,80    │ Em cache   │
└────────┴────────────┴────────────┴──────────────┴────────────┘

  [↑/↓] Navegar  [Enter] Detalhes  [A] Adicionar  [R] Remover
  [/] Pesquisar  [U] Atualizar  [Q] Sair
```

Os valores são ilustrativos.

Requisitos:

- Exibir uma linha por ativo.
- Priorizar as colunas ticker, data-base, rendimento e cotação-base.
- Manter o rendimento e a cotação-base em texto normal, sem negrito.
- Indicar claramente se os dados foram atualizados, estão em cache ou não estão disponíveis.
- Evitar colunas secundárias que tornem a tabela excessivamente larga.
- Em terminais pequenos, ocultar informações secundárias ou ajustar a tabela sem comprometer os campos prioritários.

A data-base deverá ser apresentada como a informação visualmente mais importante.

### 4.4. Pesquisa de ativos

Os resultados deverão ser exibidos em tabela.

Exemplo:

```text
  Resultados para: "maxi renda"

┏━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ # ┃ Ticker ┃ Nome               ┃
┡━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ 1 │ MXRF11 │ Maxi Renda         │
└───┴────────┴────────────────────┘

  Digite o número do ativo para selecioná-lo.
  [Q] Voltar
```

A tabela deverá apresentar somente as informações necessárias à identificação e seleção dos resultados.

### 4.5. Detalhes do ativo

A tela de detalhes deverá apresentar:

- Ticker.
- Nome.
- Data-base.
- Rendimento por cota.
- Cotação-base.
- Data e hora da última consulta bem-sucedida.
- Origem dos dados.
- Situação da última coleta.

A aplicação poderá adicionar outras informações no futuro, sem retirar a prioridade da data-base.

## 5. Navegação pelo teclado

A interface interativa deverá utilizar prompt_toolkit para capturar entradas e gerenciar a navegação quando suportado pelo terminal.

| Tecla | Ação |
|---|---|
| `↑` / `↓` | Navegar pelos ativos |
| `Enter` | Abrir detalhes |
| `A` | Adicionar ativo |
| `R` | Remover ativo |
| `U` | Atualizar dados |
| `/` | Pesquisar |
| `Q` | Sair ou voltar |
| `Esc` | Cancelar ou voltar |

A interface deverá fornecer alternativas textuais em terminais sem suporte adequado à captura de teclas.

A navegação por teclado não deverá impedir o uso tradicional por argumentos de linha de comando.

## 6. Campos extraídos

### 6.1. Data-base (`datacom`)

Campo prioritário do projeto.

Deverá representar a data-base associada ao rendimento, também conhecida como data com.

O parser deverá distinguir essa data da data de pagamento e de outras datas exibidas no site.

Quando a relação entre rendimento e data-base não puder ser estabelecida com segurança, a aplicação deverá informar que o dado é indisponível ou ambíguo.

### 6.2. Rendimento (`rendimento`)

Valor monetário do rendimento por cota divulgado para o ativo.

O sistema deverá preservar a precisão do valor e associá-lo à data-base correspondente sempre que a fonte disponibilizar essa relação.

### 6.3. Cotação-base (`cotacao_base`)

Preço de referência da cota conforme o campo definido na fonte consultada.

O parser deverá distinguir a cotação-base da cotação atual, do fechamento anterior e de valores históricos.

A implementação deverá documentar qual campo da fonte está sendo utilizado como cotação-base: no fiis.com.br, `pr_cotacaobase` / `ur_cotacao_base` (ver seção 2), distinto da cotação atual (`valor`).

## 7. Arquitetura técnica

A aplicação deverá separar as responsabilidades em camadas.

### CLI

Responsável por:

- Interpretar comandos.
- Validar argumentos.
- Controlar a navegação.
- Exibir tabelas.
- Solicitar confirmações.

### Service

Responsável por:

- Coordenar consultas.
- Atualizar os dados.
- Gerenciar operações da carteira.
- Aplicar regras de negócio.
- Coordenar o uso do cache.

### Scraper

Responsável por:

- Consultar o fiis.com.br.
- Extrair os campos.
- Tratar erros HTTP.
- Implementar tentativas limitadas.
- Respeitar limites de acesso.

### Parser

Responsável por:

- Interpretar os dados extraídos.
- Normalizar datas.
- Normalizar valores monetários.
- Validar campos.
- Identificar dados ausentes.

### Repository

Responsável por:

- Persistir a carteira.
- Recuperar ativos.
- Armazenar snapshots.
- Consultar o histórico.
- Gerenciar dados em cache.

### UI

Responsável por:

- Renderizar tabelas.
- Exibir painéis.
- Apresentar estados de carregamento.
- Controlar mensagens e prompts.
- Adaptar a interface à largura do terminal.

### Fluxo principal

```text
Usuário
   |
   v
Typer / CLI
   |
   v
AssetService
   |
   +------> Repository / SQLite
   |
   v
Scrapy Runner (subprocesso)
   |
   v
fiis.com.br
   |
   v
Parser e validação
   |
   v
Persistência dos resultados
   |
   v
Rich / Interface de terminal
```

O Scrapy deverá ser integrado por uma camada de serviço que controle o ciclo de vida do crawler. A CLI não deverá executar a lógica de scraping diretamente.

## 8. Tecnologias

| Componente | Tecnologia |
|---|---|
| Linguagem | Python 3.11+ |
| Coleta de dados | Scrapy |
| Comandos CLI | Typer |
| Renderização visual | Rich |
| Navegação interativa | prompt_toolkit |
| Persistência | SQLite |
| Validação de modelos | Pydantic |
| Testes | pytest |
| Qualidade de código | Ruff |
| Empacotamento | pyproject.toml |

As dependências deverão ser compatíveis com Windows e Linux.

O projeto deverá evitar dependências desnecessárias, especialmente aquelas que exijam navegador gráfico.

## 9. Persistência de dados

A aplicação deverá utilizar SQLite para manter os dados localmente.

O banco deverá ser armazenado no diretório de dados do usuário, respeitando os padrões de cada sistema operacional.

### 9.1. Tabela `assets`

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER | Identificador interno |
| `ticker` | TEXT | Ticker único |
| `name` | TEXT | Nome do ativo |
| `asset_type` | TEXT | Tipo do ativo |
| `created_at` | TEXT | Data de inclusão |

### 9.2. Tabela `asset_snapshots`

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER | Identificador interno |
| `asset_id` | INTEGER | Referência ao ativo |
| `datacom` | TEXT | Data-base normalizada |
| `rendimento` | TEXT | Valor monetário decimal |
| `cotacao_base` | TEXT | Cotação decimal |
| `source_url` | TEXT | URL consultada |
| `fetched_at` | TEXT | Momento da consulta |
| `status` | TEXT | Resultado da coleta |

### 9.3. Catálogo de pesquisa

O sistema deverá manter um catálogo de ativos que permita pesquisar por ticker e nome aproximado sem precisar consultar individualmente cada página a cada pesquisa.

O catálogo deverá possuir uma rotina de atualização própria e distinguir ativos conhecidos de ativos cuja página foi efetivamente validada.

### 9.4. Precisão

Valores monetários deverão ser tratados por meio de `Decimal`, evitando erros de precisão associados ao uso de ponto flutuante binário.

As datas deverão ser armazenadas em formato ISO (`YYYY-MM-DD`) quando determinadas com segurança.

O sistema deverá preservar o histórico de consultas bem-sucedidas para permitir auditoria e comparação posterior.

## 10. Cache e atualização

A aplicação deverá armazenar os últimos dados válidos e registrar o horário de atualização.

Requisitos:

- Consultar os ativos sob demanda.
- Permitir atualização manual.
- Exibir dados em cache durante consultas ou após falhas.
- Identificar dados potencialmente desatualizados.
- Não substituir dados válidos por resultados vazios de uma coleta com falha.
- Manter separados os estados de sucesso, falha e cache.
- Permitir configurar futuramente um TTL.

Na primeira versão, a execução de `ativos` deverá atualizar os ativos salvos. O cache poderá ser exibido durante o processamento, desde que seu estado fique explícito.

A aplicação não deverá confundir uma consulta bem-sucedida com uma simples recuperação de dados locais.

## 11. Tratamento de erros

A aplicação deverá tratar:

- Ticker inválido.
- Ativo inexistente.
- Falha de conexão.
- Timeout.
- Respostas HTTP inesperadas.
- Limitação de requisições.
- Alteração na estrutura da página.
- Campos ausentes.
- Erros de parsing.
- Falha no banco local.
- Terminal sem suporte a determinados recursos interativos.

As falhas de um ativo não deverão interromper a atualização dos demais.

Mensagens de erro deverão ser curtas e úteis, com detalhes técnicos adicionais disponíveis em modo de depuração.

O sistema deverá preservar os últimos dados válidos e indicar quando eles forem exibidos como fallback.

## 12. Organização do projeto

```text
ativos-cli/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── src/
│   └── ativos_cli/
│       ├── __init__.py
│       ├── main.py
│       ├── cli.py
│       ├── config.py
│       ├── models/
│       │   └── asset.py
│       ├── services/
│       │   ├── asset_service.py
│       │   └── search_service.py
│       ├── scraper/
│       │   ├── runner.py
│       │   ├── pipelines.py
│       │   └── spiders/
│       │       └── statusinvest.py
│       ├── repositories/
│       │   ├── asset_repository.py
│       │   └── database.py
│       ├── ui/
│       │   ├── wallet.py
│       │   ├── tables.py
│       │   ├── prompts.py
│       │   └── theme.py
│       └── utils/
│           ├── dates.py
│           └── money.py
└── tests/
    ├── test_cli.py
    ├── test_parser.py
    ├── test_asset_service.py
    ├── test_repository.py
    ├── test_search.py
    └── fixtures/
        └── statusinvest_fii.html
```

A estrutura poderá ser ajustada durante a implementação, mantendo as responsabilidades separadas.

## 13. Compatibilidade

O projeto deverá funcionar nativamente em:

- Windows 10 e Windows 11.
- Linux em distribuições modernas.

Requisitos:

- Instalação por `pip` ou ferramenta compatível com `pyproject.toml`.
- Comando instalado chamado `ativos`.
- Banco de dados em diretório local apropriado ao sistema.
- Tratamento correto de caminhos e permissões.
- Suporte a terminais com diferentes capacidades.
- Documentação de instalação e solução de problemas.
- Nenhuma dependência obrigatória de Docker, WSL ou interface gráfica.

A implementação deverá ser testada nas duas plataformas.

## 14. Testes automatizados

A suíte de testes deverá validar:

- Extração da data-base.
- Extração do rendimento.
- Extração da cotação-base.
- Normalização de datas e valores.
- Tratamento de campos ausentes.
- Tickers inválidos.
- Ativos inexistentes.
- Pesquisa aproximada.
- Inclusão e remoção de ativos.
- Persistência da carteira.
- Histórico de snapshots.
- Cache e recuperação após falhas.
- Atualização parcial da carteira.
- Respostas HTTP inesperadas.
- Alterações na estrutura HTML.
- Renderização dos comandos principais.
- Compatibilidade de caminhos e persistência.

Os testes de parsing deverão utilizar arquivos HTML de exemplo (*fixtures*) e respostas simuladas, evitando depender da internet durante a execução normal da suíte.

Os testes de integração com o site deverão ser separados dos testes unitários.

15. Critérios de aceitação

A versão 1.0 será considerada concluída quando:

ativos abrir a carteira e atualizar seus ativos.

ativos MXRF11 consultar e apresentar os dados em tabela.

A tabela individual possuir uma linha para o ativo.

A carteira apresentar todos os ativos em uma tabela única.

A data-base receber destaque visual.

Rendimento e cotação-base aparecerem sem negrito.

ativos search "nome aproximado" retornar resultados relevantes.

O usuário conseguir adicionar e remover ativos pelo teclado.

Os dados persistirem após o encerramento da aplicação.

Falhas não apagarem os últimos dados válidos.

Os dados em cache e os atualizados forem identificados corretamente.

O sistema não apresentar dados fictícios como resultados reais.

A aplicação funcionar no Windows e Linux.

Os testes principais passarem sem depender de acesso à internet.

16. Fora do escopo da primeira versão

Não fazem parte da versão inicial:

Compra ou venda de ativos.

Integração com corretoras.

Autenticação financeira.

Recomendações de investimento.

Projeções de rentabilidade futura.

Sincronização em nuvem.

Interface gráfica.

Monitoramento em segundo plano.

Notificações automáticas de novas datas-base.

Essas funcionalidades poderão ser avaliadas em versões futuras.

17. Plano de implementação

A implementação deverá seguir esta ordem:

Fase 1 — Prova de conceito do scraper

Inspecionar a página real da fonte de dados (fiis.com.br).

Identificar os campos correspondentes à data-base, ao rendimento e à cotação-base.

Implementar a extração e a normalização.

Validar os resultados com fixtures.

Fase 2 — Persistência

Criar o banco SQLite.

Implementar os repositórios.

Salvar os ativos e os snapshots.

Implementar o catálogo de pesquisa.

Fase 3 — Comandos básicos

Implementar ativos.

Implementar ativos TICKER.

Implementar ativos search TERMO.

Implementar inclusão, remoção e atualização explícita.

Fase 4 — Interface visual

Criar o tema visual com Rich.

Implementar a tabela individual.

Implementar a tabela da carteira.

Implementar a tabela de pesquisa.

Integrar a navegação por teclado.

Fase 5 — Robustez

Implementar cache e tratamento de falhas.

Adicionar logging e modo de depuração.

Executar os testes automatizados.

Validar Windows e Linux.

18. Resultado esperado

O ATIVOS-CLI deverá oferecer uma experiência de terminal profissional, leve e confiável para acompanhamento de ativos financeiros.

A data-base será a informação prioritária, enquanto rendimento e cotação-base permanecerão disponíveis em formato compacto e legível.

A carteira deverá permitir identificar rapidamente os ativos, consultar suas informações e atualizar os dados sem navegar manualmente pelo site.

A implementação deverá privilegiar a precisão dos dados, a consistência visual, a persistência local e a compatibilidade entre sistemas operacionais.


19. Se possivel uma forma simples de instalar essa CLI no windows e no linux 


