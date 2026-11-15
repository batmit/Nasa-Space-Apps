# Nasa-Space-Apps

AgroOrbit — planejamento de rotação de culturas com dados climáticos.

## Executar a API

Na raiz do repositório:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn src.backend.main:app --reload
```

Documentação interativa: http://127.0.0.1:8000/docs

No PowerShell, ative o ambiente com `.\.venv\Scripts\Activate.ps1`.
Interface integrada: **http://127.0.0.1:8000/**. Abra pelo servidor, não pelo
arquivo `index.html`: os módulos JavaScript e as chamadas usam a mesma origem.
As dependências visuais (Tailwind, Leaflet, Lucide, fontes e mapas) usam CDN e
precisam de conexão à internet.

## Interface integrada

O layout importado de `agroorbit-frontend-v4-unificado.zip` mantém o fluxo de
três etapas: localização, informações da área e resultado.

- `src/frontend/app.js`: navegação, mapa, controles e estado da consulta.
- `src/frontend/api.js`: construção do JSON, comunicação HTTP e erros.
- `src/frontend/results.js`: apresentação de `RecomendacaoResponse` como texto.
- `src/frontend/styles.css`: estilos do layout e dos resultados.

O frontend consulta `/api/v1/culturas/opcoes` para o agricultor escolher a opção ZARC do município antes de chamar `/api/v1/recomendar`. A tela mostra janelas ZARC,
avisos, pendências, indicadores NASA e orientações de manejo com evidências. Não existem respostas simuladas de contingência: falhas
mostram uma mensagem e permitem repetir a consulta. Doses de calcário, impactos
percentuais e séries NASA fictícias do protótipo foram removidos.

A busca e a geocodificação reversa passam pelo backend, com o mesmo cliente,
cache e limite de Nominatim usado na recomendação. Não são feitas requisições
diretas do JavaScript ao Nominatim. A camada padrão carrega os tiles de
`https://tile.openstreetmap.org/{z}/{x}/{y}.png`, sem chave CARTO. A camada de
satélite usa Esri. A atribuição dos provedores permanece visível no mapa.
O servidor público de tiles OpenStreetMap atende uso interativo moderado;
não há download em lote ou recursos offline. Para maior escala, use um
provedor contratado ou hospedagem própria conforme a política do serviço.

## Organização do backend

- `src/backend/main.py`: inicialização do FastAPI e registro das rotas.
- `src/backend/modules/routes.py`: endpoints e composição das dependências.
- `src/backend/models/recomendacao.py`: contratos de entrada e saída.
- `src/backend/models/embrapa.py`: contratos das fontes, sem dependência de HTTP.
- `src/backend/services/recomendacao.py`: seleção de cultura, filtros e orientações.
- `src/backend/integration/embrapa.py`: clientes Agritec e RespondeAgro.
- `src/backend/integration/localizacao.py`: coordenadas → município OpenStreetMap → código IBGE.
- `src/backend/integration/nasa_power.py`: coleta NASA POWER e cache dos dados brutos.
- `src/backend/services/clima.py`: qualidade dos dados e resumo dos últimos 18 meses completos.
- `src/backend/services/manejo.py`: regras de orientação com evidências e referências.
- `src/backend/services/zoneamento.py`: catálogo municipal, seleção e classificação das janelas ZARC.

Conforme as funcionalidades crescerem, as rotas poderão ser separadas em
arquivos por módulo, mantendo a inicialização em `main.py`.

## Endpoints

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/api/v1/health` | Verificar se a API está respondendo. |
| GET | `/api/v1/localizacao/buscar?consulta=Ouro%20Preto%20MG` | Buscar um ponto e identificar seu município. |
| GET | `/api/v1/localizacao/reversa?latitude=-20.3856&longitude=-43.5035` | Identificar o município do ponto selecionado. |
| POST | `/api/v1/culturas/opcoes` | Listar opções ZARC por coordenadas, cultura e irrigação antes da recomendação. |
| POST | `/api/v1/recomendar` | Combinar histórico NASA, janelas ZARC e orientações de manejo. |

Exemplo:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recomendar \
  -H 'Content-Type: application/json' \
  -d '{"regiao_nome": "Araçatuba, SP", "historico_area": "monocultura_pousio", "objetivo": "recuperar_solo", "latitude": -21.2, "longitude": -50.4, "cultura_desejada": "milho", "tipo_solo": "argiloso", "ph": 5.5, "forma_irrigacao": "sem_irrigacao", "restricoes": "Pouca água disponível."}'
```

## Configuração das fontes

Configure no ambiente do backend, sem expor tokens ao frontend:

- `EMBRAPA_ACCESS_TOKEN`: token de uma aplicação inscrita na Agritec.
- `EMBRAPA_RESPONDEAGRO_TOKEN`: token da RespondeAgro. Se omitido, utiliza o
  mesmo token acima, que deve ter inscrição nas duas APIs.
- `NOMINATIM_USER_AGENT`: identificação da aplicação, preferencialmente com
  contato do responsável (padrão: `AgroOrbit/0.1`).
- `NOMINATIM_BASE_URL`: provedor de geocodificação, com HTTPS. Padrão:
  `https://nominatim.openstreetmap.org`.

A NASA POWER não exige token. Sem os tokens Embrapa, o serviço retorna as
orientações climáticas disponíveis e informa que a janela ZARC e as referências
Agritec/RespondeAgro não foram validadas; não inventa respostas dessas APIs.

Os clientes são criados na primeira consulta e compartilhados no processo.
Reinicie o servidor depois de alterar a configuração.

O Nominatim público tem cache local e limite de uma requisição por segundo
por processo. Execute este MVP com **um worker e uma instância**. Para escalar,
substitua o provedor por um serviço próprio/contratado. Exiba na interface a
atribuição **© OpenStreetMap contributors** com link para
https://www.openstreetmap.org/copyright. A geocodificação pode ser imprecisa em
divisas; a resposta expõe o município identificado para conferência.

## Contrato e comportamento

Não são aceitos os campos antigos `prioridade`, `historico` nem `risco`.
O contrato atual recebe `historico_area` e `objetivo`. `id_cultura` é opcional:
a interface o acrescenta após a escolha explícita de uma opção do catálogo.
O servidor confere se esse ID corresponde ao município, cultura e modalidade.
O risco ZARC é fixado internamente em 20%.

- `regiao_nome`: nome de região informado pelo frontend (até 200 caracteres).
  As coordenadas determinam o município consultado. Divergência do nome/UF
  informado gera aviso; não substitui o município obtido na geocodificação.
- `historico_area` e `objetivo`: textos obrigatórios de até 200 caracteres,
  aceitando os códigos do frontend, como `monocultura_pousio` e `recuperar_solo`.
  São preservados em `dados_informados` e utilizados como termos de busca na
  RespondeAgro. Objetivos de recuperar solo/conservar água também acionam
  orientações gerais de cobertura, com referência técnica. Não representam
  diagnóstico ou seleção automática de uma espécie de rotação.
- `tipo_solo`: `arenoso`, `argiloso`, `textura_media`, `raso`, ou `AD1` a `AD6`.
  Textura não é convertida automaticamente em classe de disponibilidade de água.
  A opção de terra mista da interface envia `textura_media`. `raso` descreve
  profundidade, sem informar textura ou classe AD; janelas de classes
  conhecidas ficam condicionadas à confirmação da classificação do solo.
  O formulário oferece uma opção avançada para informar AD1–AD6 somente
  quando a classe já for conhecida por avaliação técnica.
- `forma_irrigacao`: `sem_irrigacao`, `gotejamento`, `aspersao`, `pivo_central`,
  `microaspersao`, `superficie` ou `outra`.
- `ph`: número entre 0 e 14; preservado como contexto. Sem método de medição e
  análise completa, o sistema não calcula dose de calcário ou fertilizante.
- `restricoes`: texto opcional de até 2.000 caracteres. É registrado como
  pendência de avaliação técnica, sem interpretação automática nesta versão.

A resposta contém `status`, município, cultura selecionada, janelas com solo,
ciclo, safra e portaria, orientações, referências, pendências e avisos.
`orientacao_condicional` indica que existe histórico climático utilizável ou
janelas ZARC compatíveis ou condicionais para fundamentar orientações. Não significa aptidão da
cultura ou que todas as condições da propriedade foram validadas.
`dados_insuficientes` indica ausência dessas bases. Pendências descrevem
explicitamente o que não foi validado, mesmo quando há orientações disponíveis.
Nomes ambíguos retornam opções para escolha explícita, sem selecionar um ID
arbitrário. Catálogos sem correspondência não comprovam inaptidão.

Sem data de plantio, apresentamos as janelas e os anos de safra retornados,
sem afirmar que se pode plantar hoje. O histórico resumido da área não informa
espécies e datas; não validamos uma sequência de rotação. A RespondeAgro retorna referências de publicações, não prescrições
personalizadas; textos são devolvidos sem marcação HTML.

## Consulta e diagnóstico ZARC

O catálogo é consultado por município em
`GET /municipios/{codigoIBGE}/culturas`. O catálogo global continua disponível
no cliente para outros usos, mas não é usado para selecionar a cultura neste
fluxo. Nomes completos identificados de forma única são aceitos. Correspondências
mais amplas, como `milho` para safras diferentes, são oferecidas como opções,
mesmo quando existe apenas uma opção com nome mais específico. O frontend
preserva o ID da opção selecionada; IDs de outro município, modalidade ou
cultura são recusados na seleção. Nenhum ID é escolhido arbitrariamente.

O contrato de resposta acrescenta:

- `status_zarc` e `mensagem_zarc`: resultado específico da consulta, independente
  do sucesso da NASA ou do status geral de recomendação.
- `janelas_confirmadas`: períodos que correspondem exatamente ao solo e à
  modalidade informados, sempre no risco de 20%. A palavra "confirmadas" se
  refere aos filtros; não constitui validação completa da propriedade.
- `janelas_condicionais`: períodos que dependem da confirmação de uma outra
  classificação de solo. Cada item inclui `condicao` e mantém solo, ciclo,
  safra, risco e portaria originais.
- `diagnostico_zarc`: etapa, município, cultura selecionada, risco consultado,
  quantidade recebida, descartes por filtro e solos disponíveis.

`janelas` é mantido como alias de `janelas_confirmadas`, sem duplicar o estado
interno. Janelas condicionais não são misturadas às confirmadas nem usadas para
recomendar uma época de plantio validada. Textura não é convertida em AD, classes
AD diferentes não são tratadas como equivalentes e o risco não é aumentado
para conseguir resultados.

Estados de resultado: `disponivel`, `parcial`, `classe_solo_pendente`,
`cultura_ambigua`, `cultura_nao_encontrada`, `cultura_invalida`,
`modalidade_indisponivel`, `sem_dados`, `sem_dados_compativeis`,
`nao_configurado`, `falha_autenticacao`, `limite_consultas`, `falha_conexao`,
`resposta_invalida` e `falha_api`.

O transporte AgroAPI aceita JSON simples ou gzip. Erros de autenticação, limite,
conexão e formato são preservados no diagnóstico, sem virar uma lista vazia.
A interface mostra os dois grupos, permite revisar o solo e exibe contagens
para distinguir ausência de dados de janelas descartadas pelos filtros.

## NASA e recomendações

A consulta inicial do frontend continua com dez campos; a escolha de uma
opção específica pode acrescentar `id_cultura`. O backend escolhe
os 18 meses completos anteriores ao mês atual (em novembro de 2026:
01/05/2025 a 31/10/2026), sem incluir o mês em andamento, e chama a
função existente `request_NASA_API`. O cache em
`src/backend/data/raw/nasa_power/` é reutilizado, fica fora do Git e mantém
`response.json` e `metadata.json` para cada consulta. Dados em cache
não têm expiração automática; `force_refresh=True` permite atualizar a coleta.

`analise_climatica_realizada` é `true` somente quando o resumo foi calculado
com unidades reconhecidas e pelo menos 90% dos dias válidos em chuva e
temperatura média. `resumo_climatico` inclui período, cobertura por parâmetro,
médias mensais, chuva média anual, temperaturas, radiação e sequência máxima
de dias com precipitação inferior a 1 mm/dia. Valores ausentes não viram zero.
Totais de chuva exigem meses/anos completos; um total incompleto é omitido.
Uma janela de 18 meses pode não conter um ano civil completo; nesse caso, a
chuva média anual fica ausente e um aviso explica a limitação. A quantidade de
observações completas de cada mês permanece explícita em `anos_chuva_completos`.
Radiação é normalizada para **MJ/m²/dia** e a umidade é **relativa do ar a 2 m**,
não umidade das raízes. Lacunas e limitações são apresentadas na resposta.

As regras de manejo são separadas da coleta e explicam seus fundamentos:

- Janelas compatíveis → orientar o planejamento dentro das condições ZARC.
- Sequências sem chuva observadas → orientar conservação de água e cobertura,
  distinguindo sequeiro de cultivo irrigado, sem calcular lâmina de irrigação.
- Médias mensais válidas com pelo menos duas observações completas para cada
  um dos 12 meses → contextualizar a sazonalidade em relação às janelas
  disponíveis; não ampliar a janela oficial nem prever as próximas chuvas.
  A janela padrão de 18 meses não atende a esse requisito, portanto essa
  orientação é omitida; os indicadores mensais continuam disponíveis.
- Objetivo de recuperação/conservação → orientar cobertura e planejamento da
  diversificação, sem recomendar uma espécie sem validação local.

Os itens em `orientacoes` possuem texto, fonte, evidências e link quando
aplicável. O histórico recente de 18 meses não é uma normal climatológica,
uma previsão de safra ou uma projeção de mudanças climáticas. Não há cálculo
de dose de calcário/adubo nem garantia de produtividade, lucro ou aptidão.
Restrições livres continuam registradas para avaliação técnica.

Falhas da NASA, Agritec ou RespondeAgro preservam as demais fontes e aparecem
em avisos/pendências. Localização não identificável retorna 422 e falhas de
rede na localização, 502. Configuração inválida no servidor retorna 503.
O serviço recebe dependências por `Protocol`; testes podem substituir as
fontes sem acessar a rede. Não há consultas externas ao importar a API.

## Verificação

Os testes ficam junto da aplicação que verificam:

- `src/backend/tests/`: pytest para NASA POWER/cache, resumo climático, regras de recomendação, adaptadores e contratos HTTP.
- `src/frontend/tests/frontend.test.mjs`: testes unitários do contrato HTTP e da apresentação dos resultados com o runner nativo do Node.
- `src/frontend/tests/wizard.spec.js`: testes de comportamento no Chromium com Playwright (navegação, localização, validação, envio, carregamento, erros, repetição e exportação).

Execute a partir da raiz do repositório (Python 3.12 e Node 22 ou superior):

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q

npm --prefix src/frontend ci
cd src/frontend
npx playwright install chromium
npm test
```

Os testes usam fontes simuladas e não consomem requisições das APIs.
Os testes unitários JavaScript usam o runner nativo do Node. Para executar também
os testes de navegador (Playwright), a partir da raiz do repositório:

```bash
npm --prefix src/frontend ci
npm --prefix src/frontend exec -- playwright install chromium
npm --prefix src/frontend test
```

Para executar apenas o cenário de seleção de cultura ambígua:

```bash
npm --prefix src/frontend run test:browser -- --grep "ambiguous culture"
```

O `package.json` fica em `src/frontend`; `npm test` na raiz não é configurado.

## Referências das integrações

- [Agritec v2](https://www.agroapi.cnptia.embrapa.br/store/api-docs/agroapi/Agritec/v2)
- [RespondeAgro v1](https://www.agroapi.cnptia.embrapa.br/store/api-docs/agroapi/RespondeAgro/v1)
- [Política Nominatim](https://operations.osmfoundation.org/policies/nominatim/)
- [Localidades IBGE](https://servicodados.ibge.gov.br/api/docs/localidades)
- [NASA POWER — dados diários](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
- [Embrapa — rotação e cobertura do solo](https://www.embrapa.br/web/agencia-de-informacao-tecnologica/cultivos/milho/producao/rotacao-de-culturas)

### Orientação personalizada com Gemini (opcional)

Instale `requirements.txt` e configure `GEMINI_API_KEY` no ambiente do servidor.
O código não carrega arquivos `.env` automaticamente. Nunca coloque a chave no
frontend ou no Git. `GEMINI_MODEL` permite substituir o modelo padrão
`gemini-3.1-flash-lite`. Reinicie o servidor ao alterar essas variáveis.

Após reunir as fontes, `RecomendacaoService` envia um snapshot JSON com todos
os campos do formulário (cultura, solo, pH, histórico, irrigação, objetivo,
restrições e localização), o resumo NASA com período/cobertura/avisos,
referências Embrapa, janelas ZARC confirmadas e condicionais, diagnóstico,
orientações existentes e pendências. Quando há classe ZARC, a descrição original
do solo é preservada em `tipo_solo_informado`. O histórico NASA bruto continua
no fluxo existente; a IA recebe os indicadores calculados, não a série diária.

A resposta de `/api/v1/recomendar` inclui `explicacao_ia` (`resumo`, `actions`)
e `status_ia`: `nao_configurado`, `disponivel` ou `indisponivel`. A interface
mostra a explicação como conteúdo principal em “Sua orientação personalizada”:
um resumo de até 360 caracteres e até três ações de até 220 caracteres cada.
As orientações gerais aparecem apenas quando a personalização não está disponível.
As pendências ZARC continuam acessíveis e os dados técnicos ficam recolhidos.
Sem chave, a tela usa as orientações gerais; em falhas, informa a indisponibilidade. A explicação
também permanece no JSON exportado. Cada ação cita IDs de `evidencias_contexto`; IDs desconhecidos
invalidam a geração. Essa checagem não comprova a correção agronômica do texto.

A integração usa cliente injetável, saída estruturada e timeout HTTP de 30 s,
sem estado de conversa armazenado (`store=False`). Sem chave, não chama Gemini;
em falhas de geração, preserva os resultados existentes e informa um aviso.
A geração não altera a validação de restrições, cálculos climáticos ou filtros
ZARC. Testes sem rede: `python -m pytest src/backend/tests/test_gemini_api.py`.
