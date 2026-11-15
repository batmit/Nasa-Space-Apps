"""Qualidade do histórico, regras de manejo e contrato NASA → serviço → HTTP."""

import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from src.backend.main import app
from src.backend.models.clima import ClimaError
from src.backend.integration.gemini_api import GeminiClient
from src.backend.models.recomendacao import DadosAgricultor, Municipio
from src.backend.models.embrapa import (
    ConsultaZoneamento, CulturaEmbrapa, EmbrapaError, JanelaPlantio, ResultadoZoneamento,
)
from src.backend.modules.routes import obter_servico_recomendacao
from src.backend.services.clima import NasaClimaService, resumir_clima, projetar_chuva
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
    assert result.precipitacao_ultimos_12_meses_mm == 310.0
    assert result.anos_chuva_completos == 3
    assert result.meses[0].precipitacao_media_mm == 310.0
    assert result.meses[0].anos_chuva_completos == 3
    assert result.radiacao_media_mj_m2_dia == 14.4
    assert result.umidade_relativa_ar_pct == 70.0
    assert result.maior_sequencia_dias_sem_chuva == 335


def test_projecao_usa_mes_do_ano_e_preserva_lacunas():
    inicio, fim = date(2025, 5, 1), date(2026, 10, 31)
    resumo = resumir_clima(payload_periodo(inicio, fim), inicio, fim)
    projecao = projetar_chuva(resumo, date(2026, 11, 15))
    assert (projecao.meses[0].ano, projecao.meses[0].mes) == (2026, 12)
    assert projecao.meses[1].precipitacao_estimada_mm == 310
    assert projecao.total_estimado_mm == 310
    resumo.meses[0].precipitacao_media_mm = None
    incompleta = projetar_chuva(resumo, date(2026, 11, 15))
    assert incompleta.meses[1].precipitacao_estimada_mm is None
    assert incompleta.total_estimado_mm is None


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
    assert resumo.precipitacao_ultimos_12_meses_mm == 310
    assert any("média anual não foi calculada" in aviso for aviso in resumo.avisos)
    assert any("menos de duas observações" in aviso for aviso in resumo.avisos)


def test_chuva_12_meses_estima_lacuna_pequena_e_sinaliza_resultado():
    inicio, fim = date(2025, 5, 1), date(2026, 10, 31)
    dados = payload_periodo(inicio, fim)
    dados["properties"]["parameter"]["PRECTOTCORR"]["20260101"] = -999
    resumo = resumir_clima(dados, inicio, fim)
    assert resumo.cobertura_pct["PRECTOTCORR"] > 90
    assert resumo.precipitacao_ultimos_12_meses_mm == 310
    assert resumo.precipitacao_ultimos_12_meses_estimada
    assert any("estimada" in aviso for aviso in resumo.avisos)


def test_chuva_12_meses_nao_estima_mes_com_cobertura_insuficiente():
    inicio, fim = date(2025, 5, 1), date(2026, 10, 31)
    dados = payload_periodo(inicio, fim)
    for dia in range(1, 5):
        dados["properties"]["parameter"]["PRECTOTCORR"][f"202601{dia:02d}"] = -999
    resumo = resumir_clima(dados, inicio, fim)
    assert resumo.precipitacao_ultimos_12_meses_mm is None
    assert not resumo.precipitacao_ultimos_12_meses_estimada
    assert any("menos de 90%" in aviso for aviso in resumo.avisos)


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
    assert data["resumo_climatico"]["precipitacao_ultimos_12_meses_mm"] == 310
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


@pytest.mark.parametrize("falha_gemini", [False, True])
def test_http_encadeia_nasa_embrapa_gemini_e_preserva_fontes_na_falha(falha_gemini):
    localizador = Mock()
    localizador.resolver_municipio.return_value = Municipio(codigo_ibge=3146107, nome="Ouro Preto", uf="MG")
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
    referencias = Mock()
    referencias.buscar_referencias.return_value = []
    sdk = Mock()
    saida = {
        "resumo": "Planeje a lavoura considerando a chuva sazonal e a janela do município.",
        "actions": [{"description": "Confirme o solo antes de plantar.", "evidencias": ["usuario"]}],
        "analise_ph": {"valor_informado": 5.5, "interpretacao": "pH informado de 5,5.",
                       "orientacao": "Confirme o método de medição.", "evidencias": ["usuario:ph"]},
        "analise_restricoes": {"texto_informado": "Pouca água disponível.",
                               "impacto": "A água disponível pode limitar o estabelecimento.",
                               "orientacao": "Planeje o uso da água.", "evidencias": ["usuario:restricoes"]},
        "sugestao_rotacao": {"orientacao": "Considere cobertura antes da próxima cultura.",
                             "probabilidade_estabelecimento_pct": 64,
                             "justificativa": "Estimativa exploratória baseada na chuva projetada e no manejo informado.",
                             "evidencias": ["usuario", "previsao:chuva"]},
    }
    sdk.interactions.create.return_value = SimpleNamespace(output_text="{}" if falha_gemini else json.dumps(saida))
    servico = RecomendacaoService(zoneamento, referencias, localizador,
                                  NasaClimaService(hoje=date(2026, 11, 15)), GeminiClient(sdk))
    inicio, fim = date(2025, 5, 1), date(2026, 10, 31)
    with patch("src.backend.services.clima.request_NASA_API", return_value=payload_periodo(inicio, fim)) as nasa:
        app.dependency_overrides[obter_servico_recomendacao] = lambda: servico
        try:
            response = TestClient(app).post("/api/v1/recomendar", json={**ENTRADA, "id_cultura": 1})
        finally:
            app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    nasa.assert_called_once_with(ENTRADA["latitude"], ENTRADA["longitude"], "20250501", "20261031")
    zoneamento.consultar_zoneamento.assert_called_once()
    referencias.buscar_referencias.assert_called_once()
    contexto = json.loads(sdk.interactions.create.call_args.kwargs["input"].split("\n", 1)[1])
    assert contexto["dados_informados"]["objetivo"] == "recuperar_solo"
    assert contexto["resumo_climatico"]["projecao_chuva"]["meses"][1]["precipitacao_estimada_mm"] == 310
    assert contexto["evidencias_contexto"]["previsao:chuva"] == "/resumo_climatico/projecao_chuva"
    assert data["resumo_climatico"]["projecao_chuva"]["total_estimado_mm"] == 310
    assert data["janelas"]
    assert data["status_ia"] == ("indisponivel" if falha_gemini else "disponivel")
    if falha_gemini:
        assert data["explicacao_ia"] is None
    else:
        assert data["explicacao_ia"]["sugestao_rotacao"]["probabilidade_estabelecimento_pct"] == 64
