# AgroBit

**Sistema de apoio ao planejamento de rotação de culturas com dados da NASA e da Embrapa.**

O AgroBit reúne informações sobre clima, zoneamento agrícola e manejo para ajudar a analisar uma área antes do plantio. A pessoa informa onde fica a propriedade, a cultura desejada e as condições da área; a aplicação apresenta orientações com suas fontes, avisos e pontos que ainda precisam de avaliação técnica.

## Problema e solução

Planejar uma rotação de culturas exige considerar clima, solo, irrigação, histórico de uso e condições locais de plantio. Essas informações estão espalhadas por diferentes fontes e nem sempre permitem uma resposta definitiva para uma propriedade.

O AgroBit organiza os dados em uma consulta: identifica o município, resume o histórico climático da NASA POWER, consulta as janelas do Zoneamento Agrícola de Risco Climático (ZARC) e reúne referências da Embrapa. Quando faltam dados ou uma integração está indisponível, o resultado mostra a pendência em vez de tratar a informação como validada.

## O que a aplicação faz

1. Permite localizar a área por busca, GPS, coordenadas ou seleção no mapa.
2. Recebe cultura, solo, pH, irrigação, histórico da área, objetivo e restrições.
3. Oferece as opções de cultura ZARC do município para seleção explícita, quando a Agritec está configurada.
4. Apresenta indicadores climáticos, janelas ZARC, orientações de manejo, referências e pendências.
5. Permite exportar o resultado em JSON.

Com uma chave configurada, o Gemini também pode resumir o contexto e sugerir até três ações associadas às evidências reunidas. Sem essa integração, as orientações gerais continuam disponíveis. O formulário inclui um **modo de demonstração de sensor**, que usa dados hipotéticos e não se conecta a um dispositivo físico.

## Tecnologias e fontes

| Área | Tecnologias e serviços |
| --- | --- |
| Backend | Python, FastAPI |
| Frontend | HTML, CSS e JavaScript, com Tailwind CSS, Leaflet e Lucide |
| Dados climáticos | NASA POWER |
| Zoneamento e referências | Agritec/ZARC e RespondeAgro, da Embrapa |
| Localização e mapas | Nominatim/OpenStreetMap, IBGE e camada de satélite Esri |
| AI | Gemini Agent SDK |
| Testes e deploy | pytest, Node.js, Playwright e Vercel |

## Executar localmente

Requer Python 3.12. Na raiz do repositório:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn src.backend.main:app --reload
```

No PowerShell, ative o ambiente com `.\.venv\Scripts\Activate.ps1`. Abra a interface em **http://127.0.0.1:8000/** e a documentação interativa da API em **http://127.0.0.1:8000/docs**. O frontend é servido pelo FastAPI; não abra `index.html` diretamente. Tailwind, Leaflet, Lucide, fontes e mapas são carregados de serviços externos e exigem conexão à internet.

### Configuração opcional

Configure as variáveis no ambiente do servidor, sem expor tokens no frontend. O projeto não carrega `.env` automaticamente.

| Variável | Finalidade |
| --- | --- |
| `EMBRAPA_ACCESS_TOKEN` | Habilita o catálogo de culturas e as janelas ZARC da Agritec. |
| `EMBRAPA_RESPONDEAGRO_TOKEN` | Token da RespondeAgro; se omitido, usa o token Agritec. |
| `GEMINI_API_KEY` | Habilita a orientação personalizada por IA. |
| `GEMINI_MODEL` | Substitui o modelo Gemini padrão. |
| `NOMINATIM_USER_AGENT` | Identifica a aplicação nas consultas de localização. |
| `NOMINATIM_BASE_URL` | Substitui o endereço padrão do Nominatim. |

A NASA POWER não exige token. Sem acesso à Embrapa, a consulta ainda pode apresentar dados climáticos e orientações gerais, mas informa que as janelas ZARC e referências correspondentes não foram verificadas. Reinicie o servidor após mudar as variáveis.

## API

A API usa o prefixo `/api/v1` e compartilha a origem com a interface. O contrato completo de entrada e saída está disponível em `/docs`.

| Método | Rota | Função |
| --- | --- | --- |
| `GET` | `/health` | Verifica se a API responde. |
| `GET` | `/localizacao/buscar` | Busca uma localidade pelo texto informado. |
| `GET` | `/localizacao/reversa` | Identifica a localidade de coordenadas. |
| `POST` | `/culturas/opcoes` | Lista opções ZARC para município, cultura e irrigação. |
| `POST` | `/recomendar` | Reúne clima, zoneamento e orientações. |

O formulário envia localização, cultura, solo, pH, irrigação, histórico, objetivo e restrições. Quando há uma escolha no catálogo ZARC, também envia `id_cultura`. A resposta distingue janelas compatíveis das condicionadas à confirmação do solo e inclui fontes, avisos e pendências. Falhas de uma fonte não apagam os resultados disponíveis das demais.

## Como interpretar o resultado

- O histórico da NASA POWER cobre os **18 meses completos anteriores à consulta**. A projeção de chuva repete médias mensais desse período; não é uma previsão meteorológica validada.
- As janelas ZARC são filtradas por município, cultura, modalidade e solo, com risco de 20%. Uma janela compatível não valida todas as condições da propriedade nem afirma que é possível plantar hoje.
- Textura do solo não é convertida automaticamente em classe de disponibilidade de água (AD1–AD6). Quando a classificação necessária não é conhecida, a janela aparece como condicional.
- O modo de sensor usa um cenário teórico. A referência visual de 50% para estabelecimento, quando exibida sem uma estimativa da IA, é demonstrativa e não representa probabilidade calculada para a área.
- As orientações não substituem avaliação agronômica, não validam uma sequência completa de rotação e não garantem produtividade, lucro ou aptidão para plantio. O sistema não calcula doses de corretivos ou fertilizantes.

## Estrutura do projeto

```text
src/
├── backend/
│   ├── integration/   # NASA POWER, Embrapa, Gemini e localização
│   ├── models/        # contratos de entrada e saída
│   ├── modules/       # rotas HTTP
│   ├── services/      # clima, zoneamento, manejo e recomendação
│   └── tests/
└── frontend/
    ├── index.html     # interface em três etapas
    ├── app.js         # navegação e estado da consulta
    ├── api.js         # comunicação com o backend
    ├── results.js     # apresentação dos resultados
    └── tests/
```

## Testes

Os testes usam fontes simuladas e não consomem chamadas das APIs externas. Para executar a partir da raiz:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q

npm --prefix src/frontend ci
cd src/frontend
npx playwright install chromium
npm test
```

Os testes de navegador usam Chromium; os demais testes do frontend usam o runner nativo do Node.js. Recomenda-se Node.js 22 ou superior.

## Uso de IA generativa no desenvolvimento

Este projeto foi desenvolvido com o auxílio de ferramentas de IA Generativa (Codex). A tecnologia foi utilizada como copiloto de desenvolvimento ("vibe coding") para acelerar a ideação, estruturação da arquitetura do back-end em Python/FastAPI, construção da interface front-end com TailwindCSS/Vanilla JS e integração com as APIs oficiais da NASA POWER e Embrapa.

## Referências

- [NASA POWER — API de dados diários](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
- [Embrapa Agritec v2](https://www.agroapi.cnptia.embrapa.br/store/api-docs/agroapi/Agritec/v2)
- [Embrapa RespondeAgro v1](https://www.agroapi.cnptia.embrapa.br/store/api-docs/agroapi/RespondeAgro/v1)
- [IBGE — API de localidades](https://servicodados.ibge.gov.br/api/docs/localidades)
- [Nominatim — política de uso](https://operations.osmfoundation.org/policies/nominatim/)
- [OpenStreetMap — direitos autorais e atribuição](https://www.openstreetmap.org/copyright)
