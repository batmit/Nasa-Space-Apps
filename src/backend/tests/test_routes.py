"""Public HTTP boundary: validation, delegation, and dependency failures."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.backend.integration.localizacao import LocalizacaoError
from src.backend.models.embrapa import CulturaEmbrapa
from src.backend.main import app
from src.backend.models.recomendacao import LocalizacaoSelecionada, Municipio
from src.backend.modules.routes import obter_localizador, obter_servico_recomendacao


@pytest.fixture
def client():
    previous = app.dependency_overrides.copy()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("path,params,method", [
    ("/api/v1/localizacao/buscar", {"consulta": "Ouro Preto MG"}, "buscar_localizacao"),
    ("/api/v1/localizacao/reversa", {"latitude": -20, "longitude": -43}, "resolver_localizacao"),
])
@pytest.mark.parametrize("invalid,status", [(True, 422), (False, 502)])
def test_location_errors_have_public_status(client, path, params, method, invalid, status):
    source = Mock()
    getattr(source, method).side_effect = LocalizacaoError("Localização indisponível", entrada_invalida=invalid)
    app.dependency_overrides[obter_localizador] = lambda: source

    response = client.get(path, params=params)

    assert response.status_code == status
    assert response.json() == {"detail": "Localização indisponível"}
    getattr(source, method).assert_called_once()


@pytest.mark.parametrize("params", [
    {}, {"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": -181},
    {"latitude": "nan", "longitude": 0}, {"latitude": 0, "longitude": "inf"},
])
def test_invalid_coordinates_do_not_call_location_source(client, params):
    source = Mock()
    app.dependency_overrides[obter_localizador] = lambda: source
    assert client.get("/api/v1/localizacao/reversa", params=params).status_code == 422
    source.resolver_localizacao.assert_not_called()


def test_location_search_trims_and_serializes_response(client):
    source = Mock()
    location = LocalizacaoSelecionada(regiao_nome="Ouro Preto, MG", latitude=-20, longitude=-43)
    source.buscar_localizacao.return_value = location
    app.dependency_overrides[obter_localizador] = lambda: source
    response = client.get("/api/v1/localizacao/buscar", params={"consulta": " Ouro Preto MG "})
    assert response.status_code == 200
    assert response.json() == location.model_dump()
    source.buscar_localizacao.assert_called_once_with("Ouro Preto MG")


def test_culture_options_are_fetched_before_full_recommendation(client, monkeypatch):
    location = Mock()
    location.resolver_municipio.return_value = Municipio(codigo_ibge=3146107, nome="Viçosa", uf="MG")
    app.dependency_overrides[obter_localizador] = lambda: location
    catalog = Mock()
    catalog.listar_culturas_municipio.return_value = [
        CulturaEmbrapa(id=57, nome="MILHO 1ª SAFRA", cultivo="SEQUEIRO", possui_zoneamento=True),
        CulturaEmbrapa(id=58, nome="MILHO 2ª SAFRA", cultivo="SEQUEIRO", possui_zoneamento=True),
        CulturaEmbrapa(id=59, nome="MILHO IRRIGADO", cultivo="IRRIGADO", possui_zoneamento=True),
    ]
    monkeypatch.setenv("EMBRAPA_ACCESS_TOKEN", "teste")
    monkeypatch.setattr("src.backend.modules.routes.EmbrapaClient", lambda: catalog)
    response = client.post("/api/v1/culturas/opcoes", json={
        "latitude": -20.75, "longitude": -42.88, "cultura_desejada": "milho",
        "forma_irrigacao": "sem_irrigacao",
    })
    assert response.status_code == 200
    assert [option["id"] for option in response.json()["opcoes"]] == [57, 58]
    location.resolver_municipio.assert_called_once_with(-20.75, -42.88)
    catalog.listar_culturas_municipio.assert_called_once_with(3146107)


@pytest.mark.parametrize("change", [
    {"latitude": 91}, {"longitude": -181}, {"ph": -1}, {"ph": 15},
    {"tipo_solo": "inventado"}, {"forma_irrigacao": "inventada"},
    {"cultura_desejada": " "}, {"restricoes": "x" * 2001}, {"extra": True},
])
def test_invalid_recommendation_never_calls_service(client, change):
    source = Mock()
    app.dependency_overrides[obter_servico_recomendacao] = lambda: source
    data = dict(
        regiao_nome="Ouro Preto, MG", latitude=-20, longitude=-43,
        ph=5.5, tipo_solo="argiloso", forma_irrigacao="sem_irrigacao",
        cultura_desejada="milho", historico_area="monocultura_pousio",
        objetivo="recuperar_solo", restricoes="",
    )
    response = client.post("/api/v1/recomendar", json=data | change)
    assert response.status_code == 422
    source.recomendar.assert_not_called()


def test_invalid_server_configuration_is_service_unavailable(client, monkeypatch):
    # Override the dependency wrapper to keep its lru_cache isolated per test.
    app.dependency_overrides[obter_localizador] = obter_localizador.__wrapped__
    monkeypatch.setenv("NOMINATIM_BASE_URL", "http://invalid.example")
    response = client.get("/api/v1/localizacao/buscar", params={"consulta": "Ouro Preto MG"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Localização não configurada no servidor."}
