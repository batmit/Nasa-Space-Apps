"""Contrato de orientação independente do SDK do provedor."""
from pydantic import BaseModel, ConfigDict, Field


class AcoesRecomendadasGemini(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str = Field(min_length=1, max_length=2000, description="Ação recomendada")
    evidencias: list[str] = Field(min_length=1, max_length=20, description="IDs das evidências fornecidas")


class StructuredGeminiOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    resumo: str = Field(min_length=1, max_length=4000)
    actions: list[AcoesRecomendadasGemini] = Field(max_length=10)


class OrientacaoIAError(RuntimeError):
    """A geração não forneceu orientação utilizável."""
