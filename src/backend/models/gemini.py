"""Contrato de orientação independente do SDK do provedor."""
from pydantic import BaseModel, ConfigDict, Field


class AcoesRecomendadasGemini(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str = Field(min_length=1, max_length=220, description="Uma ação prática em uma frase curta")
    evidencias: list[str] = Field(min_length=1, max_length=20, description="IDs das evidências fornecidas")


class StructuredGeminiOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    resumo: str = Field(min_length=1, max_length=360, description="Situação da área e principal condição, em até duas frases")
    actions: list[AcoesRecomendadasGemini] = Field(max_length=3)


class OrientacaoIAError(RuntimeError):
    """A geração não forneceu orientação utilizável."""
