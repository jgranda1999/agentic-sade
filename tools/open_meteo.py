"""
Open-Meteo Forecast API v1 — URL construction, fetch, and RawConditions mapping.

We use the free Forecast API for US lat/lon: hourly wind/gust/visibility and
daily sunrise/sunset over a configurable horizon. Docs:
https://open-meteo.com/en/docs
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from models import RawConditions, SpatialConstraints, WeatherDayForecast

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Hourly: wind at 10 m, gusts, horizontal visibility (meters), precipitation (mm).
HOURLY_VARIABLES: tuple[str, ...] = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "visibility",
    "precipitation",
)

# Daily: local sunrise/sunset instants (strings; interpretation depends on timezone param).
DAILY_VARIABLES: tuple[str, ...] = (
    "sunrise",
    "sunset",
)


def build_forecast_url(
    latitude: float,
    longitude: float,
    *,
    forecast_days: int = 7,
    timezone: str = "auto",
    wind_speed_unit: str = "kn",
) -> str:
    """
    Return the GET URL for Open-Meteo v1 forecast at the given coordinates.

    Parameters
    ----------
    latitude, longitude
        WGS84 decimal degrees (US-only callers still use normal CONUS coords).
    forecast_days
        1–16 per Open-Meteo; we default to 7.
    timezone
        ``\"auto\"`` lets Open-Meteo infer the zone from coordinates (typical for US).
        Use an IANA name (e.g. ``\"America/Denver\"``) if you need a fixed zone.
    wind_speed_unit
        ``\"kn\"`` matches ManufacturerFC wind limits in knots; other values: kmh, ms, mph, bft.
    """
    params: dict[str, str | int | float] = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(HOURLY_VARIABLES),
        "daily": ",".join(DAILY_VARIABLES),
        "forecast_days": forecast_days,
        "timezone": timezone,
        "wind_speed_unit": wind_speed_unit,
    }
    return f"{OPEN_METEO_FORECAST_URL}?{urlencode(params)}"


DEFAULT_TIMEOUT_S = 30.0


def fetch_forecast_json(
    latitude: float,
    longitude: float,
    *,
    forecast_days: int = 7,
    timezone: str = "auto",
    wind_speed_unit: str = "kn",
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """
    GET the Open-Meteo forecast for ``latitude`` / ``longitude`` and return the JSON object.

    Raises ``httpx.HTTPStatusError`` if the response is not successful.
    """
    url = build_forecast_url(
        latitude,
        longitude,
        forecast_days=forecast_days,
        timezone=timezone,
        wind_speed_unit=wind_speed_unit,
    )
    with httpx.Client(timeout=timeout_s) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


METERS_PER_NM = 1852.0

# WMO-style hourly precipitation intensity (mm/h) → category
_PRECIP_LIGHT_MAX_MM = 2.5
_PRECIP_MODERATE_MAX_MM = 10.0

_DAWN_HOURS = 1.0
_DUSK_HOURS = 1.0


def _visibility_m_to_nm(m: float | None) -> float | None:
    if m is None:
        return None
    return float(m) / METERS_PER_NM


def _precip_mm_to_category(mm: float | None) -> Literal["none", "light", "moderate", "heavy"]:
    if mm is None or mm < 0.05:
        return "none"
    if mm < _PRECIP_LIGHT_MAX_MM:
        return "light"
    if mm < _PRECIP_MODERATE_MAX_MM:
        return "moderate"
    return "heavy"


def _parse_local_datetime(iso: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _entry_time_to_local(entry_time_iso: str, tz: ZoneInfo) -> datetime:
    s = entry_time_iso.replace("Z", "+00:00") if entry_time_iso.endswith("Z") else entry_time_iso
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _light_conditions_solar(
    when: datetime,
    sunrise: datetime,
    sunset: datetime,
) -> Literal["daylight", "dusk", "dawn", "night"]:
    dawn_before = timedelta(hours=_DAWN_HOURS)
    dusk_after = timedelta(hours=_DUSK_HOURS)
    if when < sunrise:
        if when >= sunrise - dawn_before:
            return "dawn"
        return "night"
    if when >= sunset:
        if when < sunset + dusk_after:
            return "dusk"
        return "night"
    return "daylight"


def raw_conditions_from_forecast_json(
    forecast: dict[str, Any],
    entry_time_iso: str,
) -> RawConditions:
    """
    Map an Open-Meteo ``forecast`` JSON object into ``RawConditions``.

    Uses the hourly step closest to ``entry_time`` (in the response timezone) for
    wind, gust, visibility, and precipitation. Builds ``forecast_by_day`` from
    daily sunrise/sunset and per-day max wind/gust and min visibility.
    """
    tz_name = forecast.get("timezone") or "UTC"
    tz = ZoneInfo(tz_name)

    hourly = forecast["hourly"]
    daily = forecast["daily"]
    times_h = hourly["time"]
    hourly_local = [_parse_local_datetime(t, tz) for t in times_h]
    entry_local = _entry_time_to_local(entry_time_iso, tz)
    idx = min(
        range(len(hourly_local)),
        key=lambda i: abs((hourly_local[i] - entry_local).total_seconds()),
    )

    w = hourly["wind_speed_10m"][idx]
    g = hourly["wind_gusts_10m"][idx]
    vis_m = hourly["visibility"][idx]
    pr_mm = hourly["precipitation"][idx]

    wind = float(w) if w is not None else 0.0
    gust = float(g) if g is not None else wind
    vis_nm = _visibility_m_to_nm(vis_m)
    if vis_nm is None:
        vis_nm = 10.0

    spatial = SpatialConstraints(
        airspace_class="Class E",
        no_fly_zones=[],
        restricted_areas=[],
    )

    # Entry-day sunrise/sunset for light_conditions (match daily row to entry date)
    entry_date = entry_local.date().isoformat()
    day_i = None
    for i, d in enumerate(daily["time"]):
        if d == entry_date:
            day_i = i
            break
    if day_i is None:
        # Fall back to first day if entry date is outside the returned window
        day_i = 0

    sr = _parse_local_datetime(daily["sunrise"][day_i], tz)
    ss = _parse_local_datetime(daily["sunset"][day_i], tz)
    light = _light_conditions_solar(entry_local, sr, ss)

    forecast_by_day: list[WeatherDayForecast] = []
    for i, date_str in enumerate(daily["time"]):
        indices = [j for j, t in enumerate(times_h) if t.startswith(date_str)]
        winds: list[float] = []
        gusts: list[float] = []
        vis_nms: list[float] = []
        for j in indices:
            ww = hourly["wind_speed_10m"][j]
            gg = hourly["wind_gusts_10m"][j]
            vv = hourly["visibility"][j]
            if ww is not None:
                winds.append(float(ww))
            if gg is not None:
                gusts.append(float(gg))
            elif ww is not None:
                gusts.append(float(ww))
            vnm = _visibility_m_to_nm(vv)
            if vnm is not None:
                vis_nms.append(vnm)

        forecast_by_day.append(
            WeatherDayForecast(
                date=date_str,
                sunrise=daily["sunrise"][i],
                sunset=daily["sunset"][i],
                max_wind_speed_kt=max(winds) if winds else None,
                max_wind_gust_kt=max(gusts) if gusts else None,
                min_visibility_nm=min(vis_nms) if vis_nms else None,
            )
        )

    return RawConditions(
        wind=wind,
        wind_gust=gust,
        precipitation=_precip_mm_to_category(pr_mm),
        visibility=vis_nm,
        light_conditions=light,
        spatial_constraints=spatial,
        forecast_by_day=forecast_by_day,
    )
