from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .modules.routes import router

app = FastAPI(
    title="AgroOrbit API",
    description="API para análise climática e comparação de rotações de culturas.",
    version="0.1.0",
)

app.include_router(router, prefix="/api/v1")

# API e interface compartilham origem; as rotas da API são registradas primeiro.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "frontend", html=True), name="frontend")
