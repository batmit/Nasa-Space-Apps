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


class ResumoClimatico(BaseModel):
    fonte: Literal["NASA POWER"] = "NASA POWER"
    data_inicio: date
    data_fim: date
    dias_esperados: int
    cobertura_pct: dict[str, float]
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
    avisos: list[str] = Field(default_factory=list)


class ClimaError(RuntimeError):
    """A fonte não forneceu dados com qualidade suficiente para análise."""
