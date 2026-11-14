"""Offline contract tests for NASA POWER requests and the on-disk raw cache."""

import copy
import io
import json
from datetime import datetime, timezone
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from src.backend.integration import nasa_power


QUERY = (-20.385, -43.503, "20250101", "20250102")
EXPECTED_PARAMETERS = "T2M,T2M_MAX,T2M_MIN,RH2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """Never use the real network or the application's raw data directory."""
    monkeypatch.setattr(nasa_power, "RAW_DIR", tmp_path / "raw")
    network = Mock(side_effect=AssertionError("Unexpected HTTP request"))
    monkeypatch.setattr(nasa_power, "urlopen", network)
    return network


@pytest.fixture
def payload():
    return {
        "properties": {
            "parameter": {
                name: {"20250101": 12.5, "20250102": -999}
                for name in EXPECTED_PARAMETERS.split(",")
            }
        },
        "header": {"fill_value": -999, "title": "Dados climáticos"},
    }


def respond(network, payload):
    # A new stream per call mirrors urlopen's context manager and read behavior.
    network.side_effect = lambda *args, **kwargs: io.BytesIO(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )


def cache_files():
    directories = list(nasa_power.RAW_DIR.iterdir())
    assert len(directories) == 1
    return directories[0] / "response.json", directories[0] / "metadata.json"


def test_first_request_returns_and_persists_raw_data(isolated_environment, payload):
    network = isolated_environment
    respond(network, payload)
    before = datetime.now(timezone.utc)

    result = nasa_power.request_NASA_API(*QUERY)

    after = datetime.now(timezone.utc)
    assert result == payload
    network.assert_called_once()
    args, kwargs = network.call_args
    assert kwargs == {"timeout": 30}
    url = urlsplit(args[0])
    assert (url.scheme, url.netloc, url.path) == (
        "https", "power.larc.nasa.gov", "/api/temporal/daily/point"
    )
    assert parse_qs(url.query) == {
        "latitude": ["-20.385"], "longitude": ["-43.503"],
        "start": ["20250101"], "end": ["20250102"],
        "parameters": [EXPECTED_PARAMETERS], "community": ["AG"],
        "format": ["JSON"], "time-standard": ["LST"],
    }
    response, metadata = cache_files()
    assert json.loads(response.read_text(encoding="utf-8")) == payload
    saved = json.loads(metadata.read_text(encoding="utf-8"))
    assert saved["source"] == "NASA POWER"
    assert saved["url"] == nasa_power.URL
    assert saved["request_url"] == args[0]
    assert saved["params"] == {
        key: float(values[0]) if key in ("latitude", "longitude") else values[0]
        for key, values in parse_qs(url.query).items()
    }
    assert before <= datetime.fromisoformat(saved["fetched_at"]) <= after
    assert len(saved["query_id"]) == 64
    assert response.parent.name == f"20250101_20250102_{saved['query_id']}"
    assert sorted(p.name for p in response.parent.iterdir()) == [
        "metadata.json", "response.json"
    ]


def test_identical_request_uses_cache(isolated_environment, payload):
    respond(isolated_environment, payload)
    nasa_power.request_NASA_API(*QUERY)
    isolated_environment.reset_mock(side_effect=True)
    isolated_environment.side_effect = AssertionError("Cache must prevent HTTP")

    assert nasa_power.request_NASA_API(*QUERY) == payload
    isolated_environment.assert_not_called()


@pytest.mark.parametrize("index,value", [
    (0, -21.0), (1, -44.0), (2, "20241231"), (3, "20250103")
])
def test_different_queries_have_separate_caches(isolated_environment, payload, index, value):
    respond(isolated_environment, payload)
    nasa_power.request_NASA_API(*QUERY)
    original, _ = cache_files()
    original_bytes = original.read_bytes()
    changed = list(QUERY)
    changed[index] = value

    nasa_power.request_NASA_API(*changed)

    assert isolated_environment.call_count == 2
    assert len(list(nasa_power.RAW_DIR.iterdir())) == 2
    assert original.read_bytes() == original_bytes


def test_force_refresh_updates_response_and_metadata(isolated_environment, payload):
    respond(isolated_environment, payload)
    nasa_power.request_NASA_API(*QUERY)
    response, metadata = cache_files()
    saved = json.loads(metadata.read_text(encoding="utf-8"))
    saved["fetched_at"] = "2000-01-01T00:00:00+00:00"
    metadata.write_text(json.dumps(saved))
    updated = copy.deepcopy(payload)
    updated["properties"]["parameter"]["T2M"]["20250101"] = 25
    respond(isolated_environment, updated)

    assert nasa_power.request_NASA_API(*QUERY, force_refresh=True) == updated

    assert isolated_environment.call_count == 2
    assert json.loads(response.read_text(encoding="utf-8")) == updated
    assert json.loads(metadata.read_text(encoding="utf-8"))["fetched_at"] != saved["fetched_at"]


@pytest.mark.parametrize("bad_date", [
    "2025-01-01", "2025011", "abcdefgh", "２０２５０１０１",
    "20250230", "20250229", "20251301", "", None, 20250101,
])
@pytest.mark.parametrize("position", [2, 3], ids=["start", "end"])
def test_invalid_dates_fail_before_io(isolated_environment, bad_date, position):
    query = list(QUERY)
    query[position] = bad_date
    with pytest.raises(ValueError):
        nasa_power.request_NASA_API(*query)
    isolated_environment.assert_not_called()
    assert not nasa_power.RAW_DIR.exists()


def test_reversed_dates_fail_before_io(isolated_environment):
    with pytest.raises(ValueError):
        nasa_power.request_NASA_API(*QUERY[:2], "20250102", "20250101")
    isolated_environment.assert_not_called()
    assert not nasa_power.RAW_DIR.exists()


@pytest.mark.parametrize("start,end", [
    ("20240229", "20240301"), ("20250101", "20250101")
])
def test_valid_boundary_dates_are_accepted(isolated_environment, payload, start, end):
    respond(isolated_environment, payload)
    assert nasa_power.request_NASA_API(*QUERY[:2], start, end) == payload
    isolated_environment.assert_called_once()


@pytest.mark.parametrize("failure", [
    HTTPError(nasa_power.URL, 429, "Too Many Requests", {}, None),
    HTTPError(nasa_power.URL, 503, "Unavailable", {}, None),
    URLError("Connection refused"), TimeoutError("Timed out"),
    ValueError("Invalid JSON"), UnicodeError("Invalid encoding"),
], ids=["http-429", "http-503", "connection", "timeout", "json", "encoding"])
@pytest.mark.parametrize("existing_cache", [False, True], ids=["first-request", "refresh"])
def test_api_failures_do_not_modify_cache(isolated_environment, payload, failure, existing_cache):
    if existing_cache:
        respond(isolated_environment, payload)
        nasa_power.request_NASA_API(*QUERY)
    before = {p: p.read_bytes() for p in nasa_power.RAW_DIR.rglob("*.json")}
    isolated_environment.side_effect = failure

    with pytest.raises(nasa_power.NasaPowerError) as caught:
        nasa_power.request_NASA_API(*QUERY, force_refresh=existing_cache)

    assert caught.value.__cause__ is failure
    assert {p: p.read_bytes() for p in nasa_power.RAW_DIR.rglob("*.json")} == before
    if isinstance(failure, HTTPError):
        assert str(failure.code) in str(caught.value)


@pytest.mark.parametrize("body", [
    b'{invalid', b'\xff', b'null', b'[]', b'{}',
    b'{"properties": []}', b'{"properties": {"parameter": []}}',
], ids=["malformed-json", "invalid-utf8", "null", "array", "missing-properties",
        "invalid-properties", "invalid-series"])
def test_invalid_response_is_not_saved(isolated_environment, body):
    isolated_environment.side_effect = lambda *a, **kw: io.BytesIO(body)
    with pytest.raises(nasa_power.NasaPowerError):
        nasa_power.request_NASA_API(*QUERY)
    assert not nasa_power.RAW_DIR.exists()


@pytest.mark.parametrize("parameter", EXPECTED_PARAMETERS.split(","))
@pytest.mark.parametrize("invalid_value", [None, {}, []], ids=["missing", "empty", "wrong-type"])
def test_every_requested_series_is_required(isolated_environment, payload, parameter, invalid_value):
    series = payload["properties"]["parameter"]
    if invalid_value is None:
        del series[parameter]
    else:
        series[parameter] = invalid_value
    respond(isolated_environment, payload)
    with pytest.raises(nasa_power.NasaPowerError):
        nasa_power.request_NASA_API(*QUERY)
    assert not nasa_power.RAW_DIR.exists()


@pytest.mark.parametrize("damage", ["invalid-json", "invalid-encoding", "invalid-series", "missing-response", "missing-metadata"])
def test_damaged_cache_is_refetched(isolated_environment, payload, damage):
    respond(isolated_environment, payload)
    nasa_power.request_NASA_API(*QUERY)
    response, metadata = cache_files()
    if damage == "invalid-json":
        response.write_text("{")
    elif damage == "invalid-encoding":
        response.write_bytes(b'\xff')
    elif damage == "invalid-series":
        response.write_text('{}')
    else:
        (response if damage == "missing-response" else metadata).unlink()

    assert nasa_power.request_NASA_API(*QUERY) == payload

    assert isolated_environment.call_count == 2
    assert json.loads(response.read_text(encoding="utf-8")) == payload
    assert json.loads(metadata.read_text(encoding="utf-8"))["source"] == "NASA POWER"


@pytest.mark.parametrize("stage", ["write", "replace"])
def test_failed_file_update_preserves_original_and_removes_temp(monkeypatch, tmp_path, stage):
    target = tmp_path / "response.json"
    target.write_text('{"original": true}')
    before = target.read_bytes()
    failure = OSError("Disk failure")
    if stage == "write":
        def fail_write(payload, stream, **kwargs):
            stream.write('{"partial":')
            raise failure
        monkeypatch.setattr(nasa_power.json, "dump", fail_write)
    else:
        monkeypatch.setattr(nasa_power.os, "replace", Mock(side_effect=failure))

    with pytest.raises(OSError) as caught:
        nasa_power._write_json(target, {"updated": True})

    assert caught.value is failure
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_request_propagates_storage_failure(monkeypatch, isolated_environment, payload):
    respond(isolated_environment, payload)
    failure = PermissionError("Read-only storage")
    monkeypatch.setattr(nasa_power, "_write_json", Mock(side_effect=failure))
    with pytest.raises(PermissionError) as caught:
        nasa_power.request_NASA_API(*QUERY)
    assert caught.value is failure
    assert list(nasa_power.RAW_DIR.rglob("*.json")) == []


@pytest.mark.parametrize("latitude,longitude", [
    (-91, 0), (91, 0), (0, -181), (0, 181),
    (float("nan"), 0), (0, float("nan")),
    (float("inf"), 0), (0, float("-inf")),
])
def test_invalid_coordinates_are_rejected_before_io(isolated_environment, payload, latitude, longitude):
    respond(isolated_environment, payload)
    with pytest.raises(ValueError):
        nasa_power.request_NASA_API(latitude, longitude, *QUERY[2:])
    isolated_environment.assert_not_called()
    assert not nasa_power.RAW_DIR.exists()


@pytest.mark.parametrize("latitude,longitude", [(-90, -180), (90, 180), (0, 0)])
def test_coordinate_boundaries_are_accepted(isolated_environment, payload, latitude, longitude):
    respond(isolated_environment, payload)
    assert nasa_power.request_NASA_API(latitude, longitude, *QUERY[2:]) == payload
    isolated_environment.assert_called_once()


def test_corrupt_metadata_triggers_refetch(isolated_environment, payload):
    respond(isolated_environment, payload)
    nasa_power.request_NASA_API(*QUERY)
    _, metadata = cache_files()
    metadata.write_text("{invalid")

    assert nasa_power.request_NASA_API(*QUERY) == payload

    assert isolated_environment.call_count == 2
    assert json.loads(metadata.read_text(encoding="utf-8"))["source"] == "NASA POWER"


def test_metadata_write_failure_preserves_previous_cache_pair(
    monkeypatch, isolated_environment, payload
):
    respond(isolated_environment, payload)
    nasa_power.request_NASA_API(*QUERY)
    response, metadata = cache_files()
    before = {p: p.read_bytes() for p in (response, metadata)}
    updated = copy.deepcopy(payload)
    updated["properties"]["parameter"]["T2M"]["20250101"] = 25
    respond(isolated_environment, updated)
    real_write = nasa_power._write_json

    def fail_metadata(path, data):
        if path.name == "metadata.json":
            raise OSError("Metadata write failed")
        real_write(path, data)

    monkeypatch.setattr(nasa_power, "_write_json", fail_metadata)
    with pytest.raises(OSError, match="Metadata write failed"):
        nasa_power.request_NASA_API(*QUERY, force_refresh=True)

    assert {p: p.read_bytes() for p in (response, metadata)} == before
    assert list(response.parent.glob("*.tmp")) == []
