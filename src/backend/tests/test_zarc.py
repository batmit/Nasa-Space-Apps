"""Regressões para cultura municipal, seleção explícita, solo e falhas externas."""

import gzip
import io
import json
from unittest.mock import Mock, patch

import pytest

from src.backend.integration.embrapa import EmbrapaClient
from src.backend.models.embrapa import ConsultaZoneamento, CulturaEmbrapa, EmbrapaError, JanelaPlantio, ResultadoZoneamento
from src.backend.models.recomendacao import DadosAgricultor, Municipio, RecomendacaoResponse
from src.backend.services.zoneamento import adicionar_zoneamento
from src.backend.services.manejo import gerar_orientacoes


def dados(**extras):
    return DadosAgricultor(**(dict(
        regiao_nome="Ouro Preto, MG", latitude=-20.3856, longitude=-43.5035,
        cultura_desejada="milho", tipo_solo="argiloso", ph=5.5,
        forma_irrigacao="sem_irrigacao", historico_area="monocultura_pousio", objetivo="recuperar_solo",
    ) | extras))


def cultura(id=1, nome="MILHO SEQUEIRO", cultivo="SEQUEIRO"):
    return CulturaEmbrapa(id=id, nome=nome, cultivo=cultivo, hasZoneamento=True)


def janela(**extras):
    return JanelaPlantio(**(dict(
        municipio="Ouro Preto", uf="MG", cultura="MILHO", culturaNomeCompleto="MILHO SEQUEIRO",
        culturaSafra="não informado", culturaCultivo="SEQUEIRO", culturaClima="Não se aplica",
        ciclo="GRUPO I", solo="AD3", diaIni=1, mesIni=11, diaFim=30, mesFim=11,
        safraIni=2026, safraFim=2027, risco=20, portaria="Portaria de teste",
    ) | extras))


def executar(entrada=None, culturas=None, janelas=None, erro=None):
    entrada = entrada or dados()
    response = RecomendacaoResponse(status="dados_insuficientes", dados_informados=entrada,
                                   municipio=Municipio(codigo_ibge=3146107, nome="Ouro Preto", uf="MG"))
    source = Mock()
    source.listar_culturas_municipio.return_value = [cultura()] if culturas is None else culturas
    source.consultar_zoneamento.return_value = ResultadoZoneamento(
        consulta=ConsultaZoneamento(codigo_ibge=3146107, id_cultura=1),
        janelas=[janela()] if janelas is None else janelas,
    )
    if erro:
        source.listar_culturas_municipio.side_effect = erro
    adicionar_zoneamento(entrada, response, source)
    return response, source


def test_textura_nao_vira_classe_ad_e_janela_nao_e_perdida():
    result, source = executar()
    source.listar_culturas_municipio.assert_called_once_with(3146107)
    source.listar_culturas.assert_not_called()
    assert result.status_zarc == "classe_solo_pendente"
    assert not result.janelas_confirmadas
    assert result.janelas_condicionais[0].solo == "AD3"
    assert result.janelas_condicionais[0].condicao
    assert result.diagnostico_zarc.total_recebidas == 1
    assert result.diagnostico_zarc.solos_disponiveis == ["AD3"]
    orientacoes = gerar_orientacoes(dados(), result)
    assert any(item.tema == "validar_solo_zarc" for item in orientacoes)
    assert not any(item.tema == "epoca_plantio" for item in orientacoes)


def test_classe_ad_explicita_confirma_apenas_mesma_classe():
    result, _ = executar(dados(tipo_solo="AD3"), janelas=[janela(), janela(solo="AD1")])
    assert result.status_zarc == "disponivel"
    assert [j.solo for j in result.janelas] == ["AD3"]
    assert result.model_dump()["janelas_confirmadas"] == result.model_dump()["janelas"]
    assert not result.janelas_condicionais
    assert result.diagnostico_zarc.descartadas_solo == 1


def test_confirmadas_e_condicionais_sao_separadas():
    result, _ = executar(janelas=[janela(), janela(solo="ARGILOSO"), janela(solo="ARENOSO"),
                                 janela(risco=30), janela(culturaCultivo="IRRIGADO")])
    assert result.status_zarc == "parcial"
    assert [j.solo for j in result.janelas] == ["ARGILOSO"]
    assert [j.solo for j in result.janelas_condicionais] == ["AD3"]
    d = result.diagnostico_zarc
    assert (d.total_recebidas, d.descartadas_solo, d.descartadas_risco, d.descartadas_modalidade) == (5, 1, 1, 1)


def test_raso_nao_e_tratado_como_textura_confirmada():
    result, _ = executar(dados(tipo_solo="raso"), janelas=[janela(), janela(solo="ARGILOSO")])
    assert not result.janelas
    assert len(result.janelas_condicionais) == 2


def test_risco_nao_e_aumentado_para_retornar_janela():
    result, source = executar(janelas=[janela(risco=30), janela(risco=40)])
    assert result.status_zarc == "sem_dados_compativeis"
    assert not result.janelas and not result.janelas_condicionais
    assert source.consultar_zoneamento.call_count == 1
    assert result.diagnostico_zarc.risco_consultado == 20


def test_safras_sao_oferecidas_sem_id_arbitrario():
    opcoes = [cultura(10, "MILHO PRIMEIRA SAFRA SEQUEIRO"), cultura(20, "MILHO SEGUNDA SAFRA SEQUEIRO")]
    result, source = executar(culturas=opcoes)
    assert result.status_zarc == "cultura_ambigua"
    assert [c.id for c in result.opcoes_cultura] == [10, 20]
    source.consultar_zoneamento.assert_not_called()
    result, source = executar(dados(cultura_desejada=opcoes[1].nome, id_cultura=20), culturas=opcoes)
    assert result.cultura.id == 20
    assert source.consultar_zoneamento.call_args.args[0].id_cultura == 20


def test_nomes_iguais_podem_ser_resolvidos_por_id():
    result, _ = executar(dados(id_cultura=2), culturas=[cultura(1), cultura(2)])
    assert result.cultura.id == 2


def test_id_de_outro_municipio_ou_cultura_nao_e_aceito():
    for entrada in (dados(id_cultura=99), dados(id_cultura=1, cultura_desejada="soja")):
        result, source = executar(entrada)
        assert result.status_zarc == "cultura_invalida"
        source.consultar_zoneamento.assert_not_called()


def test_modalidade_indisponivel_nao_e_trocada_automaticamente():
    result, source = executar(dados(forma_irrigacao="gotejamento"))
    assert result.status_zarc == "modalidade_indisponivel"
    source.consultar_zoneamento.assert_not_called()


def test_lista_vazia_e_diferente_de_janelas_descartadas():
    result, _ = executar(janelas=[])
    assert result.status_zarc == "sem_dados"
    assert result.diagnostico_zarc.total_recebidas == 0
    result, _ = executar(dados(tipo_solo="AD3"), janelas=[janela(solo="AD1")])
    assert result.status_zarc == "sem_dados_compativeis"
    assert result.diagnostico_zarc.total_recebidas == 1


@pytest.mark.parametrize("erro,status", [
    (EmbrapaError("negado", 401), "falha_autenticacao"),
    (EmbrapaError("negado", 403), "falha_autenticacao"),
    (EmbrapaError("limite", 429), "limite_consultas"),
    (EmbrapaError("rede", categoria="conexao"), "falha_conexao"),
    (EmbrapaError("contrato", categoria="resposta_invalida"), "resposta_invalida"),
    (EmbrapaError("erro", 500), "falha_api"),
])
def test_falha_externa_e_identificada_sem_fabricar_janelas(erro, status):
    result, _ = executar(erro=erro)
    assert result.status_zarc == status
    assert result.diagnostico_zarc.etapa == "catalogo_municipal"
    assert not result.janelas and not result.janelas_condicionais


@pytest.mark.parametrize("encoding", ["", "gzip"])
def test_cliente_consulta_catalogo_municipal_e_le_gzip(encoding):
    payload = {"data": [{"id": 1, "nome": "MILHO", "cultivo": "SEQUEIRO", "hasZoneamento": True}]}
    body = json.dumps(payload).encode()
    response = io.BytesIO(gzip.compress(body) if encoding else body)
    response.headers = {"Content-Encoding": encoding}
    with patch("src.backend.integration.embrapa.urlopen", return_value=response) as request:
        result = EmbrapaClient("teste").listar_culturas_municipio(3146107)
    assert result[0].id == 1
    assert request.call_args.args[0].full_url.endswith("municipios/3146107/culturas")


def test_gzip_corrompido_tem_diagnostico_de_resposta_invalida():
    response = io.BytesIO(b"corrompido")
    response.headers = {"Content-Encoding": "gzip"}
    with patch("src.backend.integration.embrapa.urlopen", return_value=response):
        with pytest.raises(EmbrapaError) as result:
            EmbrapaClient("teste").listar_culturas_municipio(3146107)
    assert result.value.categoria == "resposta_invalida"


def test_nome_generico_nao_oculta_outra_safra_do_catalogo():
    result, source = executar(culturas=[cultura(1), cultura(2, "MILHO SEGUNDA SAFRA SEQUEIRO")])
    assert result.status_zarc == "cultura_ambigua"
    assert [c.id for c in result.opcoes_cultura] == [1, 2]
    source.consultar_zoneamento.assert_not_called()


@pytest.mark.parametrize("informada", [f"AD{i}" for i in range(1, 7)])
@pytest.mark.parametrize("retornada", [f"AD{i}" for i in range(1, 7)])
def test_matriz_classes_ad_nao_inventa_equivalencias(informada, retornada):
    result, _ = executar(dados(tipo_solo=informada), janelas=[janela(solo=retornada)])
    assert len(result.janelas_confirmadas) == int(informada == retornada)
    assert not result.janelas_condicionais
    assert result.diagnostico_zarc.descartadas_solo == int(informada != retornada)


@pytest.mark.parametrize("textura", ["arenoso", "argiloso", "textura_media", "raso"])
@pytest.mark.parametrize("classe", [f"AD{i}" for i in range(1, 7)])
def test_textura_nunca_confirma_classe_ad(textura, classe):
    result, _ = executar(dados(tipo_solo=textura), janelas=[janela(solo=classe)])
    assert result.status_zarc == "classe_solo_pendente"
    assert not result.janelas_confirmadas
    assert len(result.janelas_condicionais) == 1


def test_cultura_sem_zoneamento_nao_e_consultada():
    opcao = cultura()
    opcao.possui_zoneamento = False
    result, source = executar(culturas=[opcao])
    assert result.status_zarc == "cultura_nao_encontrada"
    source.consultar_zoneamento.assert_not_called()


def test_erro_na_segunda_etapa_nao_produz_janelas():
    entrada = dados(tipo_solo="AD3")
    result = RecomendacaoResponse(status="dados_insuficientes", dados_informados=entrada,
        municipio=Municipio(codigo_ibge=3146107, nome="Ouro Preto", uf="MG"))
    fonte = Mock()
    fonte.listar_culturas_municipio.return_value = [cultura()]
    fonte.consultar_zoneamento.side_effect = EmbrapaError("negado", 401)
    adicionar_zoneamento(entrada, result, fonte)
    assert result.status_zarc == "falha_autenticacao"
    assert result.diagnostico_zarc.etapa == "consulta_zoneamento"
    assert not result.janelas_confirmadas and not result.janelas_condicionais


def test_transporte_e_saida_preservam_evidencia_recebida_sem_recalcular():
    # Dados sintéticos de contrato: este teste não comprova cobertura real em Ouro Preto.
    original = janela()
    payload = {"data": [original.model_dump(by_alias=True)]}
    response = io.BytesIO(json.dumps(payload).encode())
    response.headers = {}
    with patch("src.backend.integration.embrapa.urlopen", return_value=response) as request:
        returned = EmbrapaClient("segredo-de-teste").consultar_zoneamento(
            ConsultaZoneamento(codigo_ibge=3146107, id_cultura=1))
    from urllib.parse import parse_qs, urlsplit
    url = urlsplit(request.call_args.args[0].full_url)
    assert url.path == "/agritec/v2/zoneamento"
    assert parse_qs(url.query) == {"codigoIBGE": ["3146107"], "idCultura": ["1"], "risco": ["20"]}
    assert "segredo-de-teste" not in url.query
    result, _ = executar(dados(tipo_solo="AD3"), janelas=returned.janelas)
    emitted = result.janelas_confirmadas[0]
    for field in ("solo", "ciclo", "dia_inicio", "mes_inicio", "dia_fim", "mes_fim",
                  "safra_inicio", "safra_fim", "risco", "portaria"):
        assert getattr(emitted, field) == getattr(original, field)


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": [{}]}, {"data": [{"risco": 10}]}])
def test_zoneamento_incompativel_nao_e_confundido_com_lista_vazia(payload):
    response = io.BytesIO(json.dumps(payload).encode())
    response.headers = {}
    with patch("src.backend.integration.embrapa.urlopen", return_value=response):
        with pytest.raises(EmbrapaError) as error:
            EmbrapaClient("teste").consultar_zoneamento(ConsultaZoneamento(codigo_ibge=3146107, id_cultura=1))
    assert error.value.categoria == "resposta_invalida"
