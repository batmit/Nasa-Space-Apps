import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
RAW_DIR = (
    Path("/tmp") if os.getenv("VERCEL") else Path(__file__).resolve().parents[1] / "data" / "raw"
) / "nasa_power"
PARAMETERS = "T2M,T2M_MAX,T2M_MIN,RH2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN"


class NasaPowerError(RuntimeError):
    """Falha na consulta ou resposta incompatível com a série solicitada."""


def _validate_response(payload: object) -> dict:
    """Confere a estrutura mínima sem modificar os valores originais."""
    if not isinstance(payload, dict):
        raise NasaPowerError("A NASA POWER não retornou um objeto JSON.")

    properties = payload.get("properties")
    series = properties.get("parameter") if isinstance(properties, dict) else None
    if not isinstance(series, dict) or any(
        not isinstance(series.get(parameter), dict) or not series[parameter]
        for parameter in PARAMETERS.split(",")
    ):
        raise NasaPowerError("A resposta não contém as séries diárias solicitadas.")
    return payload


def _write_json(path: Path, payload: dict) -> None:
    """Substitui o arquivo apenas depois de concluir a escrita."""
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, indent=2, allow_nan=False)
            temporary.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def request_NASA_API(latitude: float, longitude: float, start: str, end: str, *, force_refresh: bool = False) -> dict:
    latitude, longitude = float(latitude), float(longitude)
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("Latitude deve estar entre -90 e 90 e ser finita.")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("Longitude deve estar entre -180 e 180 e ser finita.")

    for value in (start, end):
        if (
            not isinstance(value, str)
            or len(value) != 8
            or not value.isascii()
            or not value.isdigit()
        ):
            raise ValueError("As datas devem estar no formato YYYYMMDD.")
        datetime.strptime(value, "%Y%m%d")
    if start > end:
        raise ValueError("A data inicial deve ser anterior ou igual à final.")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start": start,
        "end": end,
        "parameters": PARAMETERS,
        "community": "AG",
        "format": "JSON",
        "time-standard": "LST",
    }

    identity = json.dumps({
        "url": URL,
        "params": params
    }, sort_keys=True)

    query_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    query_dir = RAW_DIR / f"{start}_{end}_{query_hash}"
    response_path = query_dir / "response.json"
    metadata_path = query_dir / "metadata.json"

    if not force_refresh and response_path.is_file() and metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict) or metadata.get("query_id") != query_hash or metadata.get("params") != params:
                raise NasaPowerError("Metadados de cache incompatíveis com a consulta.")
            return _validate_response(json.loads(response_path.read_text(encoding="utf-8")))
        except (ValueError, UnicodeError, NasaPowerError):
            # Uma coleta local inválida pode ser recuperada com uma nova consulta.
            pass

    request_url = f"{URL}?{urlencode(params)}"
    try:
        with urlopen(request_url, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise NasaPowerError(f"NASA POWER retornou HTTP {exc.code}.") from exc
    except (URLError, TimeoutError) as exc:
        raise NasaPowerError("Não foi possível consultar a NASA POWER.") from exc
    except (ValueError, UnicodeError) as exc:
        raise NasaPowerError("A NASA POWER retornou um JSON inválido.") from exc

    payload = _validate_response(payload)
    metadata = {
        "source": "NASA POWER",
        "url": URL,
        "request_url": request_url,
        "params": params,
        "query_id": query_hash,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    query_dir.mkdir(parents=True, exist_ok=True)
    # Se a atualização dos metadados falhar, não deixe a resposta antiga e nova
    # associadas a metadados inconsistentes. Cada arquivo é substituído atomicamente.
    anterior = None
    if response_path.is_file():
        try:
            anterior = json.loads(response_path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            pass
    try:
        _write_json(response_path, payload)
        _write_json(metadata_path, metadata)
    except OSError:
        if anterior is not None:
            try:
                _write_json(response_path, anterior)
            except (OSError, ValueError):
                metadata_path.unlink(missing_ok=True)
        else:
            response_path.unlink(missing_ok=True)
        raise
    return payload
