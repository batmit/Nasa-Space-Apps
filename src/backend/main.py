from fastapi import FastAPI

from .modules.routes import router

app = FastAPI(
    title="AgroOrbit API",
    description="API para análise climática e comparação de rotações de culturas.",
    version="0.1.0",
)

app.include_router(router, prefix="/api/v1")