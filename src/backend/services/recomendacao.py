"""Orquestra fontes injetáveis e produz orientações condicionais verificáveis."""

import unicodedata
from typing import Protocol

from ..models.embrapa import (
    ConsultaZoneamento, CulturaEmbrapa, EmbrapaError, ResultadoZoneamento,
)
from ..models.recomendacao import (
    DadosAgricultor, FormaIrrigacao, JanelaRecomendada, Municipio,
    OpcaoCultura, RecomendacaoResponse, ReferenciaTecnica,
)

from ..models.clima import ClimaError, ResumoClimatico
from .manejo import gerar_orientacoes


class FonteClima(Protocol):
    def obter_resumo(self, latitude: float, longitude: float) -> ResumoClimatico: ...


class FonteZoneamento(Protocol):
    def listar_culturas(self) -> list[CulturaEmbrapa]: ...
    def consultar_zoneamento(self, consulta: ConsultaZoneamento) -> ResultadoZoneamento: ...


class FonteReferencias(Protocol):
    def buscar_referencias(self, termos: list[str]) -> list[ReferenciaTecnica]: ...


class LocalizadorMunicipio(Protocol):
    def resolver_municipio(self, latitude: float, longitude: float) -> Municipio: ...


def _normalizar(texto: str) -> str:
    return " ".join("".join(
        c for c in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(c)
    ).split())


def _opcao(cultura: CulturaEmbrapa) -> OpcaoCultura:
    return OpcaoCultura(id=cultura.id, nome=cultura.nome_completo or cultura.nome, cultivo=cultura.cultivo)


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
        if self._zoneamento is not None:
            try:
                self._adicionar_zoneamento(dados, resposta)
            except EmbrapaError as exc:
                resposta.pendencias.append(f"Zoneamento Embrapa indisponível: {exc}")
        else:
            resposta.pendencias.append("O zoneamento Agritec não está configurado no servidor; a janela de plantio ainda precisa ser validada.")
        if not resposta.janelas:
            resposta.pendencias.append("A época de plantio da cultura desejada não foi validada nesta consulta.")
        self._adicionar_referencias(dados, resposta)
        resposta.orientacoes = gerar_orientacoes(dados, resposta)
        if resposta.janelas or resposta.analise_climatica_realizada:
            resposta.status = "orientacao_condicional"
        return resposta

    def _adicionar_zoneamento(self, dados: DadosAgricultor, resposta: RecomendacaoResponse) -> None:
        desejada = _normalizar(dados.cultura_desejada)
        modalidade = "SEQUEIRO" if dados.forma_irrigacao == FormaIrrigacao.SEM_IRRIGACAO else "IRRIGADO"
        culturas = self._zoneamento.listar_culturas()
        resposta.fontes.append("Embrapa Agritec v2 / ZARC")
        candidatas = []
        for cultura in culturas:
            if not cultura.possui_zoneamento or _normalizar(cultura.cultivo or "") != modalidade.casefold():
                continue
            nomes = {_normalizar(cultura.nome), _normalizar(cultura.nome_completo or "")}
            nomes_base = {nome.removesuffix(" sequeiro").removesuffix(" irrigado") for nome in nomes}
            if desejada in nomes or desejada in nomes_base:
                candidatas.append(cultura)
        if len(candidatas) != 1:
            resposta.opcoes_cultura = [_opcao(c) for c in candidatas]
            if candidatas:
                resposta.pendencias.append("Há mais de uma cultura compatível; informe o nome completo de uma das opções.")
            else:
                resposta.pendencias.append("Cultura e modalidade de cultivo não identificadas no catálogo com zoneamento disponível.")
            return

        cultura = candidatas[0]
        resposta.cultura = _opcao(cultura)
        resultado = self._zoneamento.consultar_zoneamento(ConsultaZoneamento(
            codigo_ibge=resposta.municipio.codigo_ibge, id_cultura=cultura.id,
        ))
        solo = dados.tipo_solo.value.upper().replace("_", " ")
        for janela in resultado.janelas:
            if (_normalizar(janela.solo) != _normalizar(solo)
                    or _normalizar(janela.cultura_cultivo) != modalidade.casefold()
                    or janela.risco != 20):
                continue
            resposta.janelas.append(JanelaRecomendada(
                cultura=janela.cultura_nome_completo, solo=janela.solo, ciclo=janela.ciclo,
                dia_inicio=janela.dia_inicio, mes_inicio=janela.mes_inicio,
                dia_fim=janela.dia_fim, mes_fim=janela.mes_fim,
                safra_inicio=janela.safra_inicio, safra_fim=janela.safra_fim,
                risco=janela.risco, portaria=janela.portaria,
            ))
        if not resposta.janelas:
            resposta.pendencias.append(
                "Não foram encontradas janelas para a combinação consultada. Isso não comprova inaptidão da cultura. Não convertemos textura do solo automaticamente em classes AD1–AD6."
            )

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
