"""Seleção municipal e classificação das janelas ZARC, sem inferir classes AD."""

import unicodedata
from typing import Protocol

from ..models.embrapa import ConsultaZoneamento, CulturaEmbrapa, EmbrapaError, ResultadoZoneamento
from ..models.recomendacao import (
    ConsultaOpcoesCultura, DadosAgricultor, FormaIrrigacao, JanelaCondicional,
    JanelaRecomendada, OpcaoCultura, RecomendacaoResponse,
)


class FonteZoneamento(Protocol):
    def listar_culturas_municipio(self, codigo_ibge: int) -> list[CulturaEmbrapa]: ...
    def consultar_zoneamento(self, consulta: ConsultaZoneamento) -> ResultadoZoneamento: ...


def _normalizar(texto: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", texto.casefold())
                            if not unicodedata.combining(c)).split())


def _nomes(cultura: CulturaEmbrapa) -> set[str]:
    nomes = {_normalizar(cultura.nome), _normalizar(cultura.nome_completo or "")}
    return nomes | {nome.removesuffix(" sequeiro").removesuffix(" irrigado") for nome in nomes}


def _opcao(cultura: CulturaEmbrapa) -> OpcaoCultura:
    return OpcaoCultura(id=cultura.id, nome=cultura.nome_completo or cultura.nome, cultivo=cultura.cultivo)


def opcoes_para_consulta(consulta: ConsultaOpcoesCultura,
                        culturas: list[CulturaEmbrapa]) -> list[OpcaoCultura]:
    """Oferece somente IDs ZARC do município, cultura e modalidade informados."""
    desejada = _normalizar(consulta.cultura_desejada)
    modalidade = "sequeiro" if consulta.forma_irrigacao == FormaIrrigacao.SEM_IRRIGACAO else "irrigado"
    candidatas = [c for c in culturas if c.possui_zoneamento
                  and _normalizar(c.cultivo or "") == modalidade
                  and any(nome == desejada or nome.startswith(desejada + " ") for nome in _nomes(c))]
    return [_opcao(c) for c in candidatas]


def _informar(resposta: RecomendacaoResponse, status: str, mensagem: str) -> None:
    resposta.status_zarc = status
    resposta.mensagem_zarc = mensagem
    if status != "disponivel":
        resposta.pendencias.append(mensagem)


def _selecionar(dados: DadosAgricultor, resposta: RecomendacaoResponse,
                culturas: list[CulturaEmbrapa], modalidade: str) -> CulturaEmbrapa | None:
    desejada = _normalizar(dados.cultura_desejada)
    disponiveis = [c for c in culturas if c.possui_zoneamento]
    compativeis = [c for c in disponiveis if _normalizar(c.cultivo or "") == modalidade.casefold()]
    if dados.id_cultura is not None:
        selecionadas = [c for c in compativeis if c.id == dados.id_cultura]
        if len(selecionadas) != 1 or not any(
            nome == desejada or nome.startswith(desejada + " ") for nome in _nomes(selecionadas[0])
        ):
            _informar(resposta, "cultura_invalida", "A opção selecionada não corresponde à cultura, ao município ou à modalidade. Selecione novamente no catálogo local.")
            return None
        return selecionadas[0]

    candidatas = [c for c in compativeis if any(
        nome == desejada or nome.startswith(desejada + " ") for nome in _nomes(c)
    )]
    if len(candidatas) == 1:
        return candidatas[0]
    if candidatas:
        resposta.opcoes_cultura = [_opcao(c) for c in candidatas]
        _informar(resposta, "cultura_ambigua", "Selecione uma das opções de cultura do município para confirmar a safra e a modalidade. Nenhum ID foi escolhido automaticamente.")
    elif any(desejada in _nomes(c) or any(nome.startswith(desejada + " ") for nome in _nomes(c)) for c in disponiveis):
        _informar(resposta, "modalidade_indisponivel", "A cultura não possui opção ZARC local para a modalidade de irrigação informada.")
    else:
        _informar(resposta, "cultura_nao_encontrada", "A cultura informada não foi encontrada no catálogo ZARC deste município.")
    return None


def adicionar_zoneamento(dados: DadosAgricultor, resposta: RecomendacaoResponse,
                        fonte: FonteZoneamento | None) -> None:
    diagnostico = resposta.diagnostico_zarc
    diagnostico.codigo_ibge = resposta.municipio.codigo_ibge
    if fonte is None:
        _informar(resposta, "nao_configurado", "O zoneamento Agritec não está configurado no servidor; a janela de plantio ainda precisa ser validada.")
        return
    modalidade = "SEQUEIRO" if dados.forma_irrigacao == FormaIrrigacao.SEM_IRRIGACAO else "IRRIGADO"
    try:
        diagnostico.etapa = "catalogo_municipal"
        culturas = fonte.listar_culturas_municipio(resposta.municipio.codigo_ibge)
        resposta.fontes.append("Embrapa Agritec v2 / ZARC")
        diagnostico.etapa = "selecao_cultura"
        cultura = _selecionar(dados, resposta, culturas, modalidade)
        if cultura is None:
            return
        resposta.cultura = _opcao(cultura)
        diagnostico.id_cultura = cultura.id
        diagnostico.etapa = "consulta_zoneamento"
        resultado = fonte.consultar_zoneamento(ConsultaZoneamento(
            codigo_ibge=resposta.municipio.codigo_ibge, id_cultura=cultura.id,
        ))
    except EmbrapaError as exc:
        status = ("falha_autenticacao" if exc.status_code in (401, 403) else
                  "limite_consultas" if exc.status_code == 429 else
                  "falha_conexao" if exc.categoria == "conexao" else
                  "resposta_invalida" if exc.categoria == "resposta_invalida" else "falha_api")
        _informar(resposta, status, f"Zoneamento Embrapa indisponível: {exc}")
        return
    diagnostico.total_recebidas = len(resultado.janelas)
    diagnostico.etapa = "filtros"
    if not resultado.janelas:
        _informar(resposta, "sem_dados", "A Agritec retornou uma lista vazia para este município, cultura e risco de 20%. Isso não comprova inaptidão da cultura.")
        return
    solo = _normalizar(dados.tipo_solo.value.replace("_", " "))
    classes_ad = {f"ad{i}" for i in range(1, 7)}
    texturas = {"arenoso", "argiloso", "textura media"}
    for janela in resultado.janelas:
        if janela.risco != 20:
            diagnostico.descartadas_risco += 1
            continue
        if _normalizar(janela.cultura_cultivo) != modalidade.casefold():
            diagnostico.descartadas_modalidade += 1
            continue
        if janela.solo not in diagnostico.solos_disponiveis:
            diagnostico.solos_disponiveis.append(janela.solo)
        solo_janela = _normalizar(janela.solo)
        campos = JanelaRecomendada(
            cultura=janela.cultura_nome_completo, solo=janela.solo, ciclo=janela.ciclo,
            dia_inicio=janela.dia_inicio, mes_inicio=janela.mes_inicio,
            dia_fim=janela.dia_fim, mes_fim=janela.mes_fim,
            safra_inicio=janela.safra_inicio, safra_fim=janela.safra_fim,
            risco=janela.risco, portaria=janela.portaria,
        )
        if solo != "raso" and solo == solo_janela:
            resposta.janelas.append(campos)
        elif ((solo in texturas and solo_janela in classes_ad)
              or (solo in classes_ad and solo_janela in texturas)
              or (solo == "raso" and solo_janela in classes_ad | texturas)):
            resposta.janelas_condicionais.append(JanelaCondicional(
                **campos.model_dump(),
                condicao=f"Confirmar a classificação {janela.solo} do solo antes de usar esta janela. O solo informado ({dados.tipo_solo.value}) não permite estabelecer essa equivalência automaticamente.",
            ))
        else:
            diagnostico.descartadas_solo += 1
    diagnostico.etapa = "concluido"
    if resposta.janelas and resposta.janelas_condicionais:
        _informar(resposta, "parcial", "Há janelas compatíveis com o solo informado e outras que dependem da confirmação da classificação do solo.")
    elif resposta.janelas:
        _informar(resposta, "disponivel", "Janelas compatíveis com os filtros informados. Confira ciclo, safra, portaria e condições atuais antes do plantio.")
    elif resposta.janelas_condicionais:
        _informar(resposta, "classe_solo_pendente", "Há janelas disponíveis, mas a classificação do solo precisa ser confirmada. As janelas condicionais não validam o plantio na propriedade.")
    else:
        _informar(resposta, "sem_dados_compativeis", "A Agritec retornou janelas, mas nenhuma passou pelos filtros de solo, modalidade e risco de 20%. Confira as classificações disponíveis no diagnóstico.")
