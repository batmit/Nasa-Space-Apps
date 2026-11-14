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

O endpoint de recomendação retorna uma resposta fixa com `simulacao: true`.
As coordenadas são validadas, mas ainda não são utilizadas para consultas
climáticas ou avaliação agronômica.
