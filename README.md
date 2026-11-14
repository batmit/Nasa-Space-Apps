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

## Organização do backend

- `src/backend/main.py`: inicialização do FastAPI e registro das rotas.
- `src/backend/modules/routes.py`: endpoints e modelos de entrada e saída.
- `src/backend/integration/`: espaço para os clientes Google Maps e NASA POWER.
- `src/backend/data/`: dados brutos e tratados.

Conforme as funcionalidades crescerem, as rotas poderão ser separadas em
arquivos por módulo, mantendo a inicialização em `main.py`.

## Endpoints

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/api/v1/health` | Verificar se a API está respondendo. |
| POST | `/api/v1/recomendar` | Retornar uma recomendação demonstrativa. |

Exemplo:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recomendar \
  -H 'Content-Type: application/json' \
  -d '{"latitude": -20.385, "longitude": -43.503, "cultura": "milho"}'
```

O endpoint de recomendação retorna uma resposta fixa com `simulacao: true`.
As coordenadas são validadas, mas ainda não são utilizadas para consultas
climáticas ou avaliação agronômica.
