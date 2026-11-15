"""Contrato de orientação independente do SDK do provedor."""
from pydantic import BaseModel, ConfigDict, Field


class AcoesRecomendadasGemini(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str = Field(min_length=1, max_length=220, description="Uma ação prática em uma frase curta")
    evidencias: list[str] = Field(min_length=1, max_length=20, description="IDs das evidências fornecidas")


class AnalisePhGemini(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    valor_informado: float = Field(ge=0, le=14)
    interpretacao: str = Field(min_length=1, max_length=600, description="Interprete o pH para o cenário e cultura, distinguindo evidência de informação ausente")
    orientacao: str = Field(min_length=1, max_length=600, description="Próximo passo ligado ao valor informado, sem prescrever doses")
    evidencias: list[str] = Field(min_length=1, max_length=20)


class AnaliseRestricoesGemini(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    texto_informado: str = Field(min_length=1, max_length=2000, description="Copie integralmente as restrições informadas, sem resumir")
    impacto: str = Field(min_length=1, max_length=1200, description="Explique como cada limite informado muda ou impede as opções, ou qual esclarecimento específico falta")
    orientacao: str = Field(min_length=1, max_length=1200, description="Adapte as ações aos limites de água, orçamento, equipamento ou mercado efetivamente informados")
    evidencias: list[str] = Field(min_length=1, max_length=20)


class StructuredGeminiOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    resumo: str = Field(min_length=1, max_length=360, description="Situação da área e principal condição, em até duas frases")
    actions: list[AcoesRecomendadasGemini] = Field(max_length=3)
    analise_ph: AnalisePhGemini
    analise_restricoes: AnaliseRestricoesGemini | None = Field(description="Obrigatória quando há restrições; null somente quando não foram informadas")


class OrientacaoIAError(RuntimeError):
    """A geração não forneceu orientação utilizável."""
