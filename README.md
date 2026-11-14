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

O frontend chama `/api/v1/recomendar`. A tela mostra janelas ZARC, referências,
avisos e pendências. Não existem respostas simuladas de contingência: falhas
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
- `src/backend/integration/nasa_power.py`: integração independente, ainda fora deste fluxo.

Conforme as funcionalidades crescerem, as rotas poderão ser separadas em
arquivos por módulo, mantendo a inicialização em `main.py`.

## Endpoints

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/api/v1/health` | Verificar se a API está respondendo. |
| GET | `/api/v1/localizacao/buscar?consulta=Ouro%20Preto%20MG` | Buscar um ponto e identificar seu município. |
| GET | `/api/v1/localizacao/reversa?latitude=-20.3856&longitude=-43.5035` | Identificar o município do ponto selecionado. |
| POST | `/api/v1/recomendar` | Consultar janelas ZARC e referências técnicas. |

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
O contrato atual recebe `historico_area` e `objetivo`.
O risco ZARC é fixado internamente em 20%.

- `regiao_nome`: nome de região informado pelo frontend (até 200 caracteres).
  As coordenadas determinam o município consultado. Divergência do nome/UF
  informado gera aviso; não substitui o município obtido na geocodificação.
- `historico_area` e `objetivo`: textos obrigatórios de até 200 caracteres,
  aceitando os códigos do frontend, como `monocultura_pousio` e `recuperar_solo`.
  São preservados em `dados_informados` e utilizados como termos de busca na
  RespondeAgro. Não representam diagnóstico ou validação de práticas.
- `tipo_solo`: `arenoso`, `argiloso`, `textura_media`, `raso`, ou `AD1` a `AD6`.
  Textura não é convertida automaticamente em classe de disponibilidade de água.
  A opção de terra mista da interface envia `textura_media`. `raso` descreve
  profundidade, sem informar textura ou classe AD; normalmente gera pendência
  por ausência de uma janela diretamente correspondente.
- `forma_irrigacao`: `sem_irrigacao`, `gotejamento`, `aspersao`, `pivo_central`,
  `microaspersao`, `superficie` ou `outra`.
- `ph`: número entre 0 e 14; preservado como contexto. Sem método de medição e
  análise completa, o sistema não calcula dose de calcário ou fertilizante.
- `restricoes`: texto opcional de até 2.000 caracteres. É registrado como
  pendência de avaliação técnica, sem interpretação automática nesta versão.

A resposta contém `status`, município, cultura selecionada, janelas com solo,
ciclo, safra e portaria, orientações, referências, pendências e avisos.
`orientacao_condicional` indica que há janelas compatíveis; não significa que
todas as condições da propriedade foram validadas. `dados_insuficientes` indica
ausência de janelas compatíveis ou cultura não identificada de forma unívoca.
Nomes ambíguos retornam opções para selecionar pelo nome completo, sem escolher
um ID arbitrário. Catálogos sem correspondência não comprovam inaptidão.

Sem data de plantio, apresentamos as janelas e os anos de safra retornados,
sem afirmar que se pode plantar hoje. O histórico resumido da área não informa
espécies e datas; não validamos uma sequência de rotação. A RespondeAgro retorna referências de publicações, não prescrições
personalizadas; textos são devolvidos sem marcação HTML.

`analise_climatica_realizada` permanece `false`: não há leitura nem alteração
da integração NASA. O serviço recebe dependências por interfaces (`Protocol`),
permitindo testar ou substituir as fontes sem acoplar as rotas aos clientes.

Falhas de Agritec/localização retornam HTTP 502; localização não identificável,
422; configuração ausente, 503. Falha apenas na RespondeAgro preserva os demais
resultados e acrescenta um aviso. Não há chamadas externas ao importar a API.

## Verificação

Com as dependências de `requirements.txt` instaladas:

```bash
python -m pip install httpx
python -m unittest discover -s tests -v
node --test tests/frontend.test.mjs
```

Os testes usam fontes simuladas e não consomem requisições das APIs.
Os testes JavaScript usam o runner nativo do Node, sem pacotes npm adicionais.

## Referências das integrações

- [Agritec v2](https://www.agroapi.cnptia.embrapa.br/store/api-docs/agroapi/Agritec/v2)
- [RespondeAgro v1](https://www.agroapi.cnptia.embrapa.br/store/api-docs/agroapi/RespondeAgro/v1)
- [Política Nominatim](https://operations.osmfoundation.org/policies/nominatim/)
- [Localidades IBGE](https://servicodados.ibge.gov.br/api/docs/localidades)
