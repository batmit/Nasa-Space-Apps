"""Qualidade do histórico, regras de manejo e contrato NASA → serviço → HTTP."""

from datetime import date, timedelta
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from src.backend.main import app
from src.backend.models.clima import ClimaError
from src.backend.models.recomendacao import DadosAgricultor, Municipio
from src.backend.models.embrapa import (
    ConsultaZoneamento, CulturaEmbrapa, EmbrapaError, JanelaPlantio, ResultadoZoneamento,
)
from src.backend.modules.routes import obter_servico_recomendacao
from src.backend.services.clima import NasaClimaService, resumir_clima
from src.backend.services.recomendacao import RecomendacaoService


INICIO, FIM = date(2023, 1, 1), date(2025, 12, 31)
ENTRADA = dict(
    regiao_nome="Ouro Preto, MG", latitude=-20.3856, longitude=-43.5035,
    cultura_desejada="milho", tipo_solo="argiloso", ph=5.5,
    forma_irrigacao="sem_irrigacao", historico_area="monocultura_pousio",
    objetivo="recuperar_solo", restricoes="Pouca água disponível.",
)


def payload_periodo(inicio, fim):
    dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
    values = {
        "T2M": ("C", 20.0), "T2M_MIN": ("C", 10.0), "T2M_MAX": ("C", 30.0),
        "RH2M": ("%", 70.0), "ALLSKY_SFC_SW_DWN": ("kW-hr/m^2/day", 4.0),
        "PRECTOTCORR": ("mm/day", 0.0),
    }
    data = {
        "header": {"fill_value": -999},
        "parameters": {key: {"units": unit} for key, (unit, _) in values.items()},
        "properties": {"parameter": {
            key: {dia.strftime("%Y%m%d"): value for dia in dias} for key, (_, value) in values.items()
        }},
    }
    for dia in dias:
        if dia.month == 1:
            data["properties"]["parameter"]["PRECTOTCORR"][dia.strftime("%Y%m%d")] = 10.0
    return data


@pytest.fixture
def payload():
    return payload_periodo(INICIO, FIM)


def test_resumo_soma_chuva_por_ano_e_converte_radiacao(payload):
    result = resumir_clima(payload, INICIO, FIM)
    assert result.dias_esperados == 1096  # Inclui o ano bissexto.
    assert result.precipitacao_media_anual_mm == 310.0
    assert result.anos_chuva_completos == 3
    assert result.meses[0].precipitacao_media_mm == 310.0
    assert result.meses[0].anos_chuva_completos == 3
    assert result.radiacao_media_mj_m2_dia == 14.4
    assert result.umidade_relativa_ar_pct == 70.0
    assert result.maior_sequencia_dias_sem_chuva == 335


def test_lacunas_nao_viram_totais_de_chuva_ou_valores_zero(payload):
    payload["properties"]["parameter"]["PRECTOTCORR"]["20230101"] = -999
    result = resumir_clima(payload, INICIO, FIM)
    assert result.anos_chuva_completos == 2
    assert result.meses[0].anos_chuva_completos == 2
    assert result.meses[0].precipitacao_media_mm == 310.0
    assert result.cobertura_pct["PRECTOTCORR"] < 100


def test_dia_ausente_interrompe_contagem_da_sequencia_seca(payload):
    for key in payload["properties"]["parameter"]["PRECTOTCORR"]:
        payload["properties"]["parameter"]["PRECTOTCORR"][key] = 0
    payload["properties"]["parameter"]["PRECTOTCORR"]["20240702"] = -999
    result = resumir_clima(payload, INICIO, FIM)
    assert result.maior_sequencia_dias_sem_chuva == (date(2024, 7, 2) - INICIO).days


@pytest.mark.parametrize("parametro", ["T2M", "PRECTOTCORR"])
def test_cobertura_insuficiente_nao_gera_analise(payload, parametro):
    for key in list(payload["properties"]["parameter"][parametro])[:120]:
        payload["properties"]["parameter"][parametro][key] = -999
    with pytest.raises(ClimaError, match="90%"):
        resumir_clima(payload, INICIO, FIM)


def test_unidade_desconhecida_nao_e_rotulada_incorretamente(payload):
    payload["parameters"]["ALLSKY_SFC_SW_DWN"]["units"] = "desconhecida"
    result = resumir_clima(payload, INICIO, FIM)
    assert result.radiacao_media_mj_m2_dia is None
    payload["parameters"]["T2M"]["units"] = "F"
    with pytest.raises(ClimaError, match="Unidades"):
        resumir_clima(payload, INICIO, FIM)


def test_umidade_invalida_nao_e_exibida_como_dado_valido(payload):
    for key in payload["properties"]["parameter"]["RH2M"]:
        payload["properties"]["parameter"]["RH2M"][key] = 150
    assert resumir_clima(payload, INICIO, FIM).umidade_relativa_ar_pct is None


@pytest.mark.parametrize("hoje,inicio,fim", [
    (date(2026, 11, 15), date(2025, 5, 1), date(2026, 10, 31)),
    (date(2026, 11, 1), date(2025, 5, 1), date(2026, 10, 31)),
    (date(2027, 1, 1), date(2025, 7, 1), date(2026, 12, 31)),
    (date(2024, 3, 1), date(2022, 9, 1), date(2024, 2, 29)),
])
def test_nasa_consulta_dezoito_meses_completos_sem_incluir_mes_atual(hoje, inicio, fim):
    with patch("src.backend.services.clima.request_NASA_API", return_value=payload_periodo(inicio, fim)) as request:
        resumo = NasaClimaService(hoje=hoje).obter_resumo(-20, -43)
    request.assert_called_once_with(-20, -43, inicio.strftime("%Y%m%d"), fim.strftime("%Y%m%d"))
    assert resumo.data_inicio == inicio
    assert resumo.data_fim == fim
    assert resumo.dias_esperados == (fim - inicio).days + 1
    assert resumo.cobertura_pct["PRECTOTCORR"] == 100
    assert len(resumo.meses) == 12
    assert sum(mes.anos_chuva_completos for mes in resumo.meses) == 18
    assert {mes.anos_chuva_completos for mes in resumo.meses} == {1, 2}
    assert any(f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}" in aviso for aviso in resumo.avisos)
    assert not any("três anos" in aviso for aviso in resumo.avisos)


def test_dezoito_meses_nao_transformam_chuva_parcial_em_media_anual():
    inicio, fim = date(2025, 5, 1), date(2026, 10, 31)
    resumo = resumir_clima(payload_periodo(inicio, fim), inicio, fim)
    assert resumo.anos_chuva_completos == 0
    assert resumo.precipitacao_media_anual_mm is None
    assert any("média anual não foi calculada" in aviso for aviso in resumo.avisos)
    assert any("menos de duas observações" in aviso for aviso in resumo.avisos)


def test_dezoito_meses_preservam_total_do_ano_civil_completo_quando_existente():
    inicio, fim = date(2025, 7, 1), date(2026, 12, 31)
    resumo = resumir_clima(payload_periodo(inicio, fim), inicio, fim)
    assert resumo.anos_chuva_completos == 1
    assert resumo.precipitacao_media_anual_mm == 310


def test_falha_de_cache_da_nasa_e_tratada_como_fonte_indisponivel():
    with patch("src.backend.services.clima.request_NASA_API", side_effect=PermissionError()):
        with pytest.raises(ClimaError):
            NasaClimaService().obter_resumo(-20, -43)


def service(payload):
    localizador = Mock()
    localizador.resolver_municipio.return_value = Municipio(codigo_ibge=3146107, nome="Ouro Preto", uf="MG")
    clima = Mock()
    clima.obter_resumo.return_value = resumir_clima(payload, INICIO, FIM)
    return RecomendacaoService(None, None, localizador, clima), clima


def test_http_gera_orientacoes_com_nasa_e_avisa_ausencia_de_zoneamento(payload):
    servico, _ = service(payload)
    app.dependency_overrides[obter_servico_recomendacao] = lambda: servico
    try:
        response = TestClient(app).post("/api/v1/recomendar", json=ENTRADA)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["analise_climatica_realizada"]
    assert data["resumo_climatico"]["precipitacao_media_anual_mm"] == 310
    assert {"conservacao_agua", "planejamento_climatico", "cobertura_solo"} <= {o["tema"] for o in data["orientacoes"]}
    assert data["orientacoes"][0]["evidencias"]
    assert data["janelas"] == []
    assert data["pendencias"]
    assert "NASA POWER" in data["fontes"]
    assert not data["restricoes_avaliadas"]


def test_erro_embrapa_preserva_recomendacoes_climaticas(payload):
    servico, _ = service(payload)
    zoneamento = Mock()
    zoneamento.listar_culturas_municipio.side_effect = EmbrapaError("HTTP 401", 401)
    servico._zoneamento = zoneamento
    result = servico.recomendar(DadosAgricultor(**ENTRADA))
    assert result.analise_climatica_realizada
    assert any("indisponível" in item for item in result.pendencias)
    assert any(item.tema == "conservacao_agua" for item in result.orientacoes)


def test_erro_nasa_nao_fabrica_dados(payload):
    servico, clima = service(payload)
    clima.obter_resumo.side_effect = ClimaError("sem cobertura")
    result = servico.recomendar(DadosAgricultor(**ENTRADA))
    assert result.status == "dados_insuficientes"
    assert result.resumo_climatico is None
    assert not result.analise_climatica_realizada
    assert "NASA POWER" not in result.fontes
    assert any("sem cobertura" in aviso for aviso in result.avisos)


def test_cruzamento_nasa_e_embrapa_produz_janela_e_justificativa(payload):
    servico, clima = service(payload)
    zoneamento = Mock()
    zoneamento.listar_culturas_municipio.return_value = [CulturaEmbrapa(
        id=1, nome="MILHO SEQUEIRO", cultivo="SEQUEIRO", hasZoneamento=True,
    )]
    zoneamento.consultar_zoneamento.return_value = ResultadoZoneamento(
        consulta=ConsultaZoneamento(codigo_ibge=3146107, id_cultura=1),
        janelas=[JanelaPlantio(
            municipio="Ouro Preto", uf="MG", cultura="MILHO", culturaNomeCompleto="MILHO SEQUEIRO",
            culturaSafra="não informado", culturaCultivo="SEQUEIRO", culturaClima="Não se aplica",
            ciclo="GRUPO I", solo="ARGILOSO", diaIni=1, mesIni=11, diaFim=30, mesFim=11,
            safraIni=2026, safraFim=2027, risco=20, portaria="Portaria de teste",
        )],
    )
    servico._zoneamento = zoneamento
    result = servico.recomendar(DadosAgricultor(**ENTRADA))
    assert len(result.janelas) == 1
    assert result.analise_climatica_realizada
    assert any(item.tema == "epoca_plantio" for item in result.orientacoes)
    assert any("NASA POWER + Embrapa" in item.fonte for item in result.orientacoes)
    clima.obter_resumo.side_effect = ClimaError("offline")
    result = servico.recomendar(DadosAgricultor(**ENTRADA))
    assert len(result.janelas) == 1
    assert not result.analise_climatica_realizada
    assert result.status == "orientacao_condicional"
