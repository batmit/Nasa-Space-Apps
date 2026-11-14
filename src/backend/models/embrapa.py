"""Contratos e erros das fontes Embrapa, independentes do transporte HTTP."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsultaZoneamento(BaseModel):
    """Entrada da consulta; IDs da Embrapa e do IBGE, não nomes livres."""

    model_config = ConfigDict(extra="forbid")

    codigo_ibge: int = Field(ge=1000000, le=9999999, strict=True)
    id_cultura: int = Field(gt=0, strict=True)


class _ModeloEmbrapa(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class CulturaEmbrapa(_ModeloEmbrapa):
    """Opção do catálogo, preservando diferenças de safra e cultivo."""

    id: int = Field(gt=0)
    nome: str
    nome_completo: str | None = Field(default=None, alias="nomeCompleto")
    safra: str | None = None
    cultivo: str | None = None
    clima: str | None = None
    possui_zoneamento: bool = Field(alias="hasZoneamento")


class JanelaPlantio(_ModeloEmbrapa):
    """Período ZARC; os anos da safra não definem datas exatas de plantio."""

    municipio: str
    uf: str
    cultura: str
    cultura_nome_completo: str = Field(alias="culturaNomeCompleto")
    cultura_safra: str = Field(alias="culturaSafra")
    cultura_cultivo: str = Field(alias="culturaCultivo")
    cultura_clima: str = Field(alias="culturaClima")
    ciclo: str
    solo: str
    dia_inicio: int = Field(ge=1, le=31, alias="diaIni")
    mes_inicio: int = Field(ge=1, le=12, alias="mesIni")
    dia_fim: int = Field(ge=1, le=31, alias="diaFim")
    mes_fim: int = Field(ge=1, le=12, alias="mesFim")
    safra_inicio: int = Field(alias="safraIni")
    safra_fim: int = Field(alias="safraFim")
    risco: Literal[20, 30, 40]
    portaria: str


class ResultadoZoneamento(BaseModel):
    """Saída para o futuro serviço que combinará Embrapa e NASA."""

    fonte: Literal["Embrapa Agritec v2 / ZARC"] = "Embrapa Agritec v2 / ZARC"
    consulta: ConsultaZoneamento
    janelas: list[JanelaPlantio]


class EmbrapaError(RuntimeError):
    """Falha externa, separada dos erros de validação da entrada local."""

    def __init__(self, mensagem: str, status_code: int | None = None, *, categoria: str = "api"):
        super().__init__(mensagem)
        self.status_code = status_code
        self.categoria = categoria


