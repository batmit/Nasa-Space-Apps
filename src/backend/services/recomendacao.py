"""Orquestra fontes injetáveis e produz orientações condicionais verificáveis."""

import unicodedata
from typing import Protocol

from ..models.embrapa import EmbrapaError
from ..models.recomendacao import (
    DadosAgricultor, Municipio, RecomendacaoResponse, ReferenciaTecnica,
)

from ..models.gemini import OrientacaoIAError, StructuredGeminiOutput
from ..models.clima import ClimaError, PrevisaoChuva, PrevisaoChuvaError, ResumoClimatico
from .manejo import gerar_orientacoes
from .zoneamento import FonteZoneamento, adicionar_zoneamento


class FonteOrientacaoIA(Protocol):
    def gerar(self, contexto: dict) -> StructuredGeminiOutput: ...


def montar_contexto_ia(resposta: RecomendacaoResponse) -> dict:
    """Snapshot JSON das fontes já consultadas; não faz chamadas externas."""
    contexto = resposta.model_dump(
        mode="json", exclude={"explicacao_ia", "status_ia", "janelas_confirmadas", "estimativa_demonstrativa_pct"},
    )
    # JSON pointers evitam duplicar os dados e consumir tokens desnecessários.
    evidencias = {"usuario": "/dados_informados", "usuario:ph": "/dados_informados/ph"}
    if resposta.dados_informados.restricoes:
        evidencias["usuario:restricoes"] = "/dados_informados/restricoes"
    if resposta.resumo_climatico is not None:
        evidencias["nasa:resumo"] = "/resumo_climatico"
        if resposta.resumo_climatico.projecao_chuva is not None:
            evidencias["previsao:chuva"] = "/resumo_climatico/projecao_chuva"
    if resposta.previsao_chuva is not None:
        evidencias["previsao:chuva"] = "/previsao_chuva"
    if resposta.estimativa_estabelecimento is not None:
        evidencias["modelo:estabelecimento"] = "/estimativa_estabelecimento"
    for i in range(len(resposta.janelas)):
        evidencias[f"zarc:janela:{i}"] = f"/janelas/{i}"
    for i in range(len(resposta.janelas_condicionais)):
        evidencias[f"zarc:condicional:{i}"] = f"/janelas_condicionais/{i}"
    for i in range(len(resposta.referencias)):
        evidencias[f"embrapa:referencia:{i}"] = f"/referencias/{i}"
    contexto["evidencias_contexto"] = evidencias
    return contexto


class FonteClima(Protocol):
    def obter_resumo(self, latitude: float, longitude: float) -> ResumoClimatico: ...


class FontePrevisaoChuva(Protocol):
    def obter_previsao(self, latitude: float, longitude: float) -> PrevisaoChuva: ...


class FonteReferencias(Protocol):
    def buscar_referencias(self, termos: list[str]) -> list[ReferenciaTecnica]: ...


class LocalizadorMunicipio(Protocol):
    def resolver_municipio(self, latitude: float, longitude: float) -> Municipio: ...


def _normalizar(texto: str) -> str:
    return " ".join("".join(
        c for c in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(c)
    ).split())


class RecomendacaoService:
    def __init__(self, zoneamento: FonteZoneamento | None, referencias: FonteReferencias | None,
                 localizador: LocalizadorMunicipio, clima: FonteClima | None = None,
                 orientacao_ia: FonteOrientacaoIA | None = None,
                 previsao_chuva: FontePrevisaoChuva | None = None):
        self._zoneamento = zoneamento
        self._referencias = referencias
        self._localizador = localizador
        self._clima = clima
        self._orientacao_ia = orientacao_ia
        self._previsao_chuva = previsao_chuva

    def recomendar(self, dados: DadosAgricultor) -> RecomendacaoResponse:
        municipio = self._localizador.resolver_municipio(dados.latitude, dados.longitude)
        resposta = RecomendacaoResponse(
            status="dados_insuficientes", dados_informados=dados, municipio=municipio,
            fontes=["OpenStreetMap / Nominatim", "IBGE"],
            avisos=[
                "Município identificado por geocodificação reversa; confira o local, especialmente próximo a divisas.",
                "Sem data de plantio, as janelas indicam períodos da safra informada, não autorização para plantar hoje.",
                "O histórico resumido da área não informa espécies e datas; não é possível validar uma sequência de rotação.",
                "O pH isolado não determina dose de calcário ou adubo; é necessária análise de solo completa e método de medição.",
            ],
        )
        if dados.modo_demonstracao:
            resposta.avisos.append(
                "Cenário demonstrativo: dados de solo e manejo são teóricos e não representam medições da propriedade."
            )
        regiao = dados.regiao_nome.rsplit(",", 1)
        nome_compativel = _normalizar(regiao[0]) == _normalizar(municipio.nome)
        uf_compativel = len(regiao) == 1 or _normalizar(regiao[1]) == _normalizar(municipio.uf)
        if not nome_compativel or not uf_compativel:
            resposta.avisos.append(
                f"A região informada ({dados.regiao_nome}) difere do município identificado "
                f"pelas coordenadas ({municipio.nome}, {municipio.uf}). Confira o ponto no mapa; "
                "as consultas utilizam as coordenadas."
            )
        if self._clima is not None:
            try:
                resposta.resumo_climatico = self._clima.obter_resumo(dados.latitude, dados.longitude)
            except ClimaError as exc:
                resposta.avisos.append(f"Análise climática indisponível: {exc}")
            else:
                resposta.analise_climatica_realizada = True
                resposta.fontes.append("NASA POWER")
                resposta.avisos.extend(resposta.resumo_climatico.avisos)
        else:
            resposta.avisos.append("Fonte climática não configurada para esta consulta.")
        if self._previsao_chuva is not None:
            try:
                resposta.previsao_chuva = self._previsao_chuva.obter_previsao(dados.latitude, dados.longitude)
            except PrevisaoChuvaError:
                resposta.avisos.append("Não foi possível obter a previsão de chuva para esta consulta.")
            else:
                resposta.fontes.append(resposta.previsao_chuva.fonte)
        adicionar_zoneamento(dados, resposta, self._zoneamento)
        if not resposta.janelas:
            resposta.pendencias.append("A época de plantio da cultura desejada não foi validada nesta consulta.")
        self._adicionar_referencias(dados, resposta)
        resposta.orientacoes = gerar_orientacoes(dados, resposta)
        if resposta.janelas or resposta.janelas_condicionais or resposta.analise_climatica_realizada:
            resposta.status = "orientacao_condicional"
        if self._orientacao_ia is not None:
            try:
                resposta.explicacao_ia = self._orientacao_ia.gerar(montar_contexto_ia(resposta))
            except OrientacaoIAError:
                resposta.status_ia = "indisponivel"
                resposta.avisos.append("Orientação por IA indisponível; os resultados das fontes foram preservados.")
            else:
                resposta.status_ia = "disponivel"
        if dados.restricoes and resposta.explicacao_ia is None:
            resposta.pendencias.append(
                "Confira as restrições informadas com assistência técnica antes de seguir orientações gerais."
            )
        return resposta

    def _adicionar_referencias(self, dados: DadosAgricultor, resposta: RecomendacaoResponse) -> None:
        if self._referencias is None:
            resposta.avisos.append("RespondeAgro não configurada; referências de busca indisponíveis.")
            return
        # Contexto orienta a busca editorial, sem ser convertido em diagnóstico.
        termos = [
            dados.cultura_desejada, "solo", "manejo", "irrigação", "rotação de culturas",
            dados.objetivo.replace("_", " "), dados.historico_area.replace("_", " "),
        ]
        try:
            resposta.referencias = self._referencias.buscar_referencias(termos)
        except EmbrapaError:
            resposta.avisos.append("A RespondeAgro está indisponível; os demais resultados foram preservados.")
        else:
            resposta.fontes.append("Embrapa RespondeAgro")
            if not resposta.referencias:
                resposta.avisos.append("Nenhuma referência técnica foi encontrada para a busca.")
            else:
                resposta.avisos.append("Referências são resultados de busca; sua aplicabilidade à propriedade ainda precisa ser avaliada.")
