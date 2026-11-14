"""Orquestra fontes injetáveis e produz orientações condicionais verificáveis."""

import unicodedata
from typing import Protocol

from ..models.embrapa import EmbrapaError
from ..models.recomendacao import (
    DadosAgricultor, Municipio, RecomendacaoResponse, ReferenciaTecnica,
)

from ..models.clima import ClimaError, ResumoClimatico
from .manejo import gerar_orientacoes
from .zoneamento import FonteZoneamento, adicionar_zoneamento


class FonteClima(Protocol):
    def obter_resumo(self, latitude: float, longitude: float) -> ResumoClimatico: ...


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
                 localizador: LocalizadorMunicipio, clima: FonteClima | None = None):
        self._zoneamento = zoneamento
        self._referencias = referencias
        self._localizador = localizador
        self._clima = clima

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
        regiao = dados.regiao_nome.rsplit(",", 1)
        nome_compativel = _normalizar(regiao[0]) == _normalizar(municipio.nome)
        uf_compativel = len(regiao) == 1 or _normalizar(regiao[1]) == _normalizar(municipio.uf)
        if not nome_compativel or not uf_compativel:
            resposta.avisos.append(
                f"A região informada ({dados.regiao_nome}) difere do município identificado "
                f"pelas coordenadas ({municipio.nome}, {municipio.uf}). Confira o ponto no mapa; "
                "as consultas utilizam as coordenadas."
            )
        if dados.restricoes:
            resposta.pendencias.append(
                "As restrições em texto foram registradas, mas sua compatibilidade com as opções exige avaliação técnica."
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
        adicionar_zoneamento(dados, resposta, self._zoneamento)
        if not resposta.janelas:
            resposta.pendencias.append("A época de plantio da cultura desejada não foi validada nesta consulta.")
        self._adicionar_referencias(dados, resposta)
        resposta.orientacoes = gerar_orientacoes(dados, resposta)
        if resposta.janelas or resposta.janelas_condicionais or resposta.analise_climatica_realizada:
            resposta.status = "orientacao_condicional"
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
