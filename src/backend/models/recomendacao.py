"""Contratos públicos do fluxo de orientação ao produtor."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .clima import ResumoClimatico


class TipoSolo(str, Enum):
    ARENOSO = "arenoso"
    ARGILOSO = "argiloso"
    TEXTURA_MEDIA = "textura_media"
    RASO = "raso"
    AD1 = "AD1"
    AD2 = "AD2"
    AD3 = "AD3"
    AD4 = "AD4"
    AD5 = "AD5"
    AD6 = "AD6"


class FormaIrrigacao(str, Enum):
    SEM_IRRIGACAO = "sem_irrigacao"
    GOTEJAMENTO = "gotejamento"
    ASPERSAO = "aspersao"
    PIVO_CENTRAL = "pivo_central"
    MICROASPERSAO = "microaspersao"
    SUPERFICIE = "superficie"
    OUTRA = "outra"


class DadosAgricultor(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", allow_inf_nan=False)

    regiao_nome: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    cultura_desejada: str = Field(min_length=1, max_length=100)
    tipo_solo: TipoSolo
    ph: float = Field(ge=0, le=14)
    forma_irrigacao: FormaIrrigacao
    historico_area: str = Field(min_length=1, max_length=200)
    objetivo: str = Field(min_length=1, max_length=200)
    restricoes: str = Field(default="", max_length=2000)


class Municipio(BaseModel):
    codigo_ibge: int = Field(ge=1000000, le=9999999)
    nome: str
    uf: str


class LocalizacaoSelecionada(BaseModel):
    regiao_nome: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class OpcaoCultura(BaseModel):
    id: int
    nome: str
    cultivo: str | None = None


class JanelaRecomendada(BaseModel):
    cultura: str
    solo: str
    ciclo: str
    dia_inicio: int
    mes_inicio: int
    dia_fim: int
    mes_fim: int
    safra_inicio: int
    safra_fim: int
    risco: int
    portaria: str


class ReferenciaTecnica(BaseModel):
    id: str
    pergunta: str
    resposta: str
    livro: str
    capitulo: str | None = None
    ano: int | None = None
    url_publicacao: str | None = None


class Orientacao(BaseModel):
    tema: str
    texto: str
    fonte: str
    evidencias: list[str] = Field(default_factory=list)
    url_fonte: str | None = None


class RecomendacaoResponse(BaseModel):
    status: Literal["orientacao_condicional", "dados_insuficientes"]
    dados_informados: DadosAgricultor
    municipio: Municipio
    cultura: OpcaoCultura | None = None
    opcoes_cultura: list[OpcaoCultura] = Field(default_factory=list)
    janelas: list[JanelaRecomendada] = Field(default_factory=list)
    orientacoes: list[Orientacao] = Field(default_factory=list)
    referencias: list[ReferenciaTecnica] = Field(default_factory=list)
    pendencias: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    restricoes_avaliadas: bool = False
    analise_climatica_realizada: bool = False
    resumo_climatico: ResumoClimatico | None = None
    fontes: list[str] = Field(default_factory=list)
