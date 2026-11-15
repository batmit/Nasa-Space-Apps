"""Deterministic agronomic rules, independent of external sources."""

from datetime import date

import pytest

from src.backend.models.clima import MesClimatico, ResumoClimatico
from src.backend.models.recomendacao import DadosAgricultor, Municipio, RecomendacaoResponse
from src.backend.services.manejo import gerar_orientacoes


@pytest.fixture
def farmer():
    return DadosAgricultor(
        regiao_nome="Ouro Preto, MG", latitude=-20, longitude=-43,
        cultura_desejada="milho", tipo_solo="argiloso", ph=5.5,
        forma_irrigacao="sem_irrigacao", historico_area="monocultura_pousio",
        objetivo="maximizar_rendimento",
    )


def recommendation(farmer, climate=None):
    return RecomendacaoResponse(
        status="dados_insuficientes", dados_informados=farmer,
        municipio=Municipio(codigo_ibge=3146107, nome="Ouro Preto", uf="MG"),
        resumo_climatico=climate,
    )


def climate(*, dry_days=15, complete_years=2):
    return ResumoClimatico(
        data_inicio=date(2023, 1, 1), data_fim=date(2025, 12, 31),
        dias_esperados=1096, cobertura_pct={}, maior_sequencia_dias_sem_chuva=dry_days,
        meses=[MesClimatico(mes=month, precipitacao_media_mm=month * 10,
                            anos_chuva_completos=complete_years) for month in range(1, 13)],
    )


@pytest.mark.parametrize("irrigation,expected", [
    ("sem_irrigacao", "cultivo é de sequeiro"),
    ("gotejamento", "manejo da irrigação"),
])
def test_water_guidance_matches_irrigation_and_cites_observation(farmer, irrigation, expected):
    farmer.forma_irrigacao = irrigation
    rules = gerar_orientacoes(farmer, recommendation(farmer, climate()))
    water = next(rule for rule in rules if rule.tema == "conservacao_agua")
    assert expected in water.texto
    assert any("15 dias" in evidence for evidence in water.evidencias)
    assert water.url_fonte.startswith("https://www.embrapa.br/")


@pytest.mark.parametrize("days", [0, None])
def test_no_dry_spell_claim_without_observation(farmer, days):
    rules = gerar_orientacoes(farmer, recommendation(farmer, climate(dry_days=days)))
    assert "conservacao_agua" not in {rule.tema for rule in rules}


def test_seasonality_requires_twelve_months_with_two_complete_years(farmer):
    summary = climate()
    rules = gerar_orientacoes(farmer, recommendation(farmer, summary))
    seasonal = next(rule for rule in rules if rule.tema == "planejamento_climatico")
    assert "mês 12" in seasonal.texto
    assert "mês 01" in seasonal.texto
    assert "Aguarde a confirmação de uma janela ZARC" in seasonal.texto
    summary.meses[0].anos_chuva_completos = 1
    rules = gerar_orientacoes(farmer, recommendation(farmer, summary))
    assert "planejamento_climatico" not in {rule.tema for rule in rules}
    summary.meses.pop(0)
    rules = gerar_orientacoes(farmer, recommendation(farmer, summary))
    assert "planejamento_climatico" not in {rule.tema for rule in rules}


def test_eighteen_month_window_does_not_imply_two_observations_for_every_month(farmer):
    summary = climate(complete_years=1)
    summary.data_inicio = date(2025, 5, 1)
    summary.data_fim = date(2026, 10, 31)
    summary.dias_esperados = (summary.data_fim - summary.data_inicio).days + 1
    for month in summary.meses:
        if 5 <= month.mes <= 10:
            month.anos_chuva_completos = 2
    rules = gerar_orientacoes(farmer, recommendation(farmer, summary))
    assert "planejamento_climatico" not in {rule.tema for rule in rules}
    assert "conservacao_agua" in {rule.tema for rule in rules}


@pytest.mark.parametrize("goal,expected", [
    ("recuperar_solo", ["cobertura_solo"]),
    ("conservar_agua", ["cobertura_solo"]),
    ("maximizar_rendimento", []),
])
def test_soil_cover_guidance_depends_on_goal_without_inventing_climate(farmer, goal, expected):
    farmer.objetivo = goal
    rules = gerar_orientacoes(farmer, recommendation(farmer))
    assert [rule.tema for rule in rules] == expected
