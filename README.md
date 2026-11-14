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

## Integração contínua

O workflow `.github/workflows/ci.yml` executa a cada push em `back-end` e
na abertura, reabertura ou atualização de pull requests para `main` ou `back-end`.
Utiliza Python 3.12, verifica a sintaxe do backend e a importação do FastAPI,
e executa os testes de `test/` com pytest.

Para executar os testes localmente, na raiz do repositório:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest test/ -q
```

Crie testes com nomes `test_*.py`. O HTTPX está incluído para testes da API
com o `TestClient` do FastAPI. Enquanto não houver testes, o pytest retorna
código 5, aceito pelo CI; falhas nos testes ou na coleta continuam bloqueando o job.
O arquivo `test/.gitkeep` mantém a pasta presente no checkout do Git.

Os arquivos do frontend estão vazios; ainda não há build ou testes de interface.
Este workflow faz integração contínua, sem implantação automática. Para impedir
merges com falhas, configure o check `tests` como obrigatório nas regras de
proteção de `main` e `back-end` no GitHub.
