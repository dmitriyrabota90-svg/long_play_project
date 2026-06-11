from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode


SOURCE_CODE = "open_meteo_historical_weather"
COLLECTOR_NAME = "open_meteo_historical_weather"
PARSER_VERSION = "open_meteo_weather_v1"
ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
REQUEST_TIMEOUT = 30.0
MAX_DAYS_PER_RUN = 45

HEADERS = {
    "User-Agent": "commodity-dataset-builder/0.1 (+https://github.com/dmitriyrabota90-svg/long_play_project)",
    "Accept": "application/json,*/*",
    "Accept-Language": "en,ru;q=0.9",
}

OPEN_METEO_DAILY_VARIABLES: tuple[str, ...] = (
    "temperature_2m_mean",
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "relative_humidity_2m_mean",
    "wind_speed_10m_mean",
    "wind_speed_10m_max",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration",
)

OPEN_METEO_VARIABLE_MAPPING = {
    "temperature_2m_mean": "temperature_2m_mean",
    "temperature_2m_min": "temperature_2m_min",
    "temperature_2m_max": "temperature_2m_max",
    "precipitation_sum": "precipitation_sum",
    "snowfall_sum": "snowfall_sum",
    "relative_humidity_2m_mean": "relative_humidity_mean",
    "wind_speed_10m_mean": "wind_speed_mean",
    "wind_speed_10m_max": "wind_speed_max",
    "shortwave_radiation_sum": "shortwave_radiation",
    "et0_fao_evapotranspiration": "evapotranspiration",
}

CORE_WEATHER_FIELDS: tuple[str, ...] = (
    "temperature_2m_mean",
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
)

HIGH_MEDIUM_PRIORITIES = {"high", "medium"}


@dataclass(frozen=True)
class OpenMeteoRequest:
    latitude: str
    longitude: str
    from_date: date
    to_date: date
    daily_variables: tuple[str, ...] = OPEN_METEO_DAILY_VARIABLES


def open_meteo_params(request: OpenMeteoRequest) -> dict[str, str]:
    return {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "start_date": request.from_date.isoformat(),
        "end_date": request.to_date.isoformat(),
        "daily": ",".join(request.daily_variables),
        "timezone": "UTC",
    }


def open_meteo_url(request: OpenMeteoRequest) -> str:
    return f"{ENDPOINT}?{urlencode(open_meteo_params(request))}"

