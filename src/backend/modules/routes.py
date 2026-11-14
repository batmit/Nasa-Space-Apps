from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()

class DadosAgricultor(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    cultura: str = Field(min_length=1, max_length=100)

# Sujeito a mudança
class RecomendacaoResponse(BaseModel):
    cultura: str
    recomendacao: str
    simulacao: bool


@router.get("/health", tags=["Status"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/recomendar",
    tags=["Rotações"],
    response_model=RecomendacaoResponse,
    summary="Obter uma recomendação demonstrativa",
    description=(
        "Retorna uma resposta fixa para testar a integração. "
        "Ainda não consulta APIs externas nem aplica critérios agronômicos."
    ),
)
def recomendar(dados: DadosAgricultor) -> RecomendacaoResponse:
    return RecomendacaoResponse(
        cultura=dados.cultura,
        recomendacao="Avaliar rotação com leguminosas",
        simulacao=True,
    )
