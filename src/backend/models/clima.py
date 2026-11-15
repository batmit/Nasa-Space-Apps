"""Resumo climático independente do formato bruto da NASA POWER."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class MesClimatico(BaseModel):
    mes: int = Field(ge=1, le=12)
    precipitacao_media_mm: float | None = None
    anos_chuva_completos: int = 0
    temperatura_media_c: float | None = None
    umidade_relativa_ar_pct: float | None = None
    radiacao_media_mj_m2_dia: float | None = None


class MesProjetado(BaseModel):
    ano: int
    mes: int = Field(ge=1, le=12)
    precipitacao_estimada_mm: float | None = None
    meses_historicos_utilizados: int = Field(ge=0)


class ProjecaoChuva(BaseModel):
    metodo: Literal["media_por_mes_do_ano"] = "media_por_mes_do_ano"
    meses: list[MesProjetado]
    total_estimado_mm: float | None = None
    aviso: str = (
        "Projeção sazonal baseada nos últimos 18 meses. "
        "É uma hipótese de repetição do padrão recente, não uma previsão meteorológica validada."
    )


class ResumoClimatico(BaseModel):
    fonte: Literal["NASA POWER"] = "NASA POWER"
    data_inicio: date
    data_fim: date
    dias_esperados: int
    cobertura_pct: dict[str, float]
    precipitacao_ultimos_12_meses_mm: float | None = None
    precipitacao_ultimos_12_meses_estimada: bool = False
    precipitacao_media_anual_mm: float | None = None
    anos_chuva_completos: int = 0
    temperatura_media_c: float | None = None
    temperatura_minima_c: float | None = None
    temperatura_maxima_c: float | None = None
    umidade_relativa_ar_pct: float | None = None
    radiacao_media_mj_m2_dia: float | None = None
    maior_sequencia_dias_sem_chuva: int | None = None
    criterio_dia_sem_chuva_mm: float = 1.0
    meses: list[MesClimatico]
    projecao_chuva: ProjecaoChuva | None = None
    avisos: list[str] = Field(default_factory=list)


class PrevisaoChuva(BaseModel):
    """Contrato mínimo para adaptar a saída do futuro modelo de chuva."""
    fonte: str = Field(min_length=1, max_length=100)
    data_inicio: date
    data_fim: date
    resumo: str = Field(min_length=1, max_length=600)
    precipitacao_prevista_mm: float | None = Field(default=None, ge=0)


class ClimaError(RuntimeError):
    """A fonte não forneceu dados com qualidade suficiente para análise."""


class PrevisaoChuvaError(RuntimeError):
    """O modelo de chuva não forneceu previsão utilizável."""
