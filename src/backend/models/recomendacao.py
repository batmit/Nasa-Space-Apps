"""Contratos públicos do fluxo de orientação ao produtor."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from .clima import PrevisaoChuva, ResumoClimatico
from .gemini import StructuredGeminiOutput


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
    id_cultura: int | None = Field(default=None, gt=0, strict=True)
    tipo_solo: TipoSolo
    tipo_solo_informado: TipoSolo | None = None
    ph: float = Field(ge=0, le=14)
    forma_irrigacao: FormaIrrigacao
    historico_area: str = Field(min_length=1, max_length=200)
    objetivo: str = Field(min_length=1, max_length=200)
    restricoes: str = Field(default="", max_length=2000)
    modo_demonstracao: bool = False


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


class ConsultaOpcoesCultura(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    cultura_desejada: str = Field(min_length=1, max_length=100)
    forma_irrigacao: FormaIrrigacao


class OpcoesCulturaResponse(BaseModel):
    municipio: Municipio
    opcoes: list[OpcaoCultura]


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


class JanelaCondicional(JanelaRecomendada):
    condicao: str


class DiagnosticoZarc(BaseModel):
    etapa: str = "configuracao"
    codigo_ibge: int | None = None
    id_cultura: int | None = None
    risco_consultado: Literal[20] = 20
    total_recebidas: int = 0
    descartadas_risco: int = 0
    descartadas_modalidade: int = 0
    descartadas_solo: int = 0
    solos_disponiveis: list[str] = Field(default_factory=list)


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


class EstimativaEstabelecimento(BaseModel):
    """Probabilidade calibrada de estabelecimento, fornecida por modelo próprio."""
    alvo: Literal["estabelecimento"] = "estabelecimento"
    probabilidade_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    metodo: str = Field(min_length=1, max_length=200)
    validacao: str = Field(min_length=1, max_length=300)


class RecomendacaoResponse(BaseModel):
    status: Literal["orientacao_condicional", "dados_insuficientes"]
    explicacao_ia: StructuredGeminiOutput | None = None
    status_ia: Literal["nao_configurado", "disponivel", "indisponivel"] = "nao_configurado"
    dados_informados: DadosAgricultor
    municipio: Municipio
    cultura: OpcaoCultura | None = None
    opcoes_cultura: list[OpcaoCultura] = Field(default_factory=list)
    janelas: list[JanelaRecomendada] = Field(default_factory=list)
    janelas_condicionais: list[JanelaCondicional] = Field(default_factory=list)
    status_zarc: Literal[
        "nao_configurado", "cultura_ambigua", "cultura_nao_encontrada", "cultura_invalida",
        "modalidade_indisponivel", "sem_dados", "sem_dados_compativeis", "classe_solo_pendente",
        "disponivel", "parcial", "falha_autenticacao", "limite_consultas", "falha_conexao",
        "resposta_invalida", "falha_api",
    ] = "nao_configurado"
    mensagem_zarc: str = "Zoneamento ainda não consultado."
    diagnostico_zarc: DiagnosticoZarc = Field(default_factory=DiagnosticoZarc)
    orientacoes: list[Orientacao] = Field(default_factory=list)
    referencias: list[ReferenciaTecnica] = Field(default_factory=list)
    pendencias: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    restricoes_avaliadas: bool = False
    analise_climatica_realizada: bool = False
    resumo_climatico: ResumoClimatico | None = None
    previsao_chuva: PrevisaoChuva | None = None
    estimativa_estabelecimento: EstimativaEstabelecimento | None = None
    fontes: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def janelas_confirmadas(self) -> list[JanelaRecomendada]:
        """Alias público; janelas permanece compatível com clientes existentes."""
        return self.janelas
