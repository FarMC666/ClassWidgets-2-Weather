"""Pure parsing and validation helpers for the weather plugin.

This module deliberately has no Qt dependency so provider payload handling can
be tested without a running ClassWidgets process.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Iterable
from urllib.parse import urlsplit


MIN_REFRESH_MINUTES = 15
MAX_REFRESH_MINUTES = 360


def qweather_language(locale: str) -> str:
    """Map Qt/BCP 47 locales to documented QWeather codes; fall back to English."""
    parts = str(locale or "").lower().replace("_", "-").split("-")
    base = parts[0]
    if base == "zh":
        if "hant" in parts or ("hans" not in parts and any(p in parts for p in ("tw", "hk", "mo"))):
            return "zh-hant"
        return "zh"
    if base == "lzh":
        return "zh"
    base = {"no": "nb", "iw": "he", "in": "id", "tl": "fil"}.get(base, base)
    supported = "en de es fr it ja ko ru hi th ar pt bn ms nl el la sv id pl tr cs et vi fil fi he is nb".split()
    return base if base in supported else "en"


def valid_coordinates(latitude: Any, longitude: Any) -> bool:
    try:
        lat, lon = float(latitude), float(longitude)
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
    except (TypeError, ValueError):
        return False


SEVERITY_RANK = {
    "unknown": 0,
    "minor": 1,
    "moderate": 2,
    "severe": 3,
    "extreme": 4,
}

COLOR_RANK = {
    "white": 0,
    "gray": 1,
    "green": 2,
    "blue": 3,
    "yellow": 4,
    "amber": 5,
    "orange": 6,
    "red": 7,
    "purple": 8,
    "black": 9,
}

COLOR_ZH = {
    "white": "白色",
    "gray": "灰色",
    "green": "绿色",
    "blue": "蓝色",
    "yellow": "黄色",
    "amber": "琥珀色",
    "orange": "橙色",
    "red": "红色",
    "purple": "紫色",
    "black": "黑色",
}


class WeatherDataError(ValueError):
    """Raised when a provider response cannot produce required UI data."""


def clamp_refresh_minutes(value: Any) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = 30
    return max(MIN_REFRESH_MINUTES, min(MAX_REFRESH_MINUTES, minutes))


def normalize_api_host(value: str) -> str:
    """Return a safe QWeather API hostname or raise ``ValueError``.

    Accepting only QWeather's dedicated host suffix prevents accidentally
    sending a user's API key to an arbitrary endpoint.
    """

    raw = (value or "").strip()
    if not raw:
        raise ValueError("请填写和风天气 API Host")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https":
        raise ValueError("API Host 必须使用 HTTPS")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("API Host 不能包含账号、密码或端口")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("API Host 只能填写域名，不能包含路径或参数")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host.endswith(".qweatherapi.com"):
        raise ValueError("请填写控制台分配的 *.qweatherapi.com 专属域名")
    return host


def _as_number(value: Any, field: str, tr=str) -> float:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise WeatherDataError(tr("天气数据缺少有效字段：{field}").format(field=field)) from error


def _rounded_temperature(value: Any, field: str, tr=str) -> int:
    number = _as_number(value, field, tr)
    return int(number + 0.5) if number >= 0 else int(number - 0.5)


def _attributions(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        raw = metadata.get("attributions")
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
    refer = payload.get("refer")
    if isinstance(refer, dict):
        raw = refer.get("sources")
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
    return values


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_current(payload: dict[str, Any], tr=str) -> dict[str, Any]:
    """Normalize QWeather v1 current data, with a v7 compatibility fallback."""

    condition = payload.get("condition")
    temperature = payload.get("temperature")
    if isinstance(condition, dict) and temperature is not None:
        text = str(condition.get("text") or tr("未知天气"))
        code = str(condition.get("code") or "999")
        value = _rounded_temperature(temperature, "temperature.value", tr)
    else:
        now = payload.get("now")
        if not isinstance(now, dict):
            raise WeatherDataError(tr("实时天气响应格式无效"))
        text = str(now.get("text") or tr("未知天气"))
        code = str(now.get("icon") or "999")
        value = _rounded_temperature(now.get("temp"), "now.temp", tr)
    return {
        "temperature": value,
        "conditionText": text,
        "conditionCode": code,
        "sources": _attributions(payload),
    }


def parse_daily(payload: dict[str, Any], tr=str) -> dict[str, Any]:
    """Normalize the first day in QWeather v1 or v7 daily data."""

    days = payload.get("days")
    if not isinstance(days, list):
        days = payload.get("daily")
    if not isinstance(days, list) or not days or not isinstance(days[0], dict):
        raise WeatherDataError(tr("每日预报响应中没有当天数据"))
    day = days[0]
    max_value = day.get("temperatureMax", day.get("tempMax"))
    min_value = day.get("temperatureMin", day.get("tempMin"))
    return {
        "temperatureMax": _rounded_temperature(max_value, "temperatureMax.value", tr),
        "temperatureMin": _rounded_temperature(min_value, "temperatureMin.value", tr),
        "sources": _attributions(payload),
    }


def _message_code(alert: dict[str, Any]) -> str:
    message_type = alert.get("messageType")
    if isinstance(message_type, dict):
        return str(message_type.get("code") or "").lower()
    return str(message_type or "").lower()


def _supersedes(alert: dict[str, Any]) -> list[str]:
    message_type = alert.get("messageType")
    if not isinstance(message_type, dict):
        return []
    values = message_type.get("supersedes")
    return [str(value) for value in values] if isinstance(values, list) else []


def _event_name(alert: dict[str, Any], tr=str) -> str:
    event_type = alert.get("eventType")
    if isinstance(event_type, dict):
        return str(event_type.get("name") or tr("天气"))
    return str(alert.get("typeName") or alert.get("type") or tr("天气"))


def _color_code(alert: dict[str, Any]) -> str:
    color = alert.get("color")
    if isinstance(color, dict):
        return str(color.get("code") or "").lower()
    return str(alert.get("level") or "").lower()


def _display_alert_name(event_name: str, color_code: str, tr=str) -> str:
    base = event_name.strip()
    if base.endswith(("预警", "預警")):
        base = base[:-2]
    color = tr(COLOR_ZH[color_code]) if color_code in COLOR_ZH else ""
    return tr("{event}{color}预警").format(event=base, color=color)


def select_alert(
    payload: dict[str, Any], now: datetime | None = None, language: str = "zh", tr=str
) -> dict[str, Any] | None:
    """Select the highest-priority active alert from a QWeather response."""

    raw_alerts = payload.get("alerts", payload.get("warning", []))
    if not isinstance(raw_alerts, list):
        return None
    alerts = [item for item in raw_alerts if isinstance(item, dict)]
    superseded_ids = {item_id for alert in alerts for item_id in _supersedes(alert)}
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    active: list[dict[str, Any]] = []
    for alert in alerts:
        if _message_code(alert) == "cancel":
            continue
        if str(alert.get("id") or "") in superseded_ids:
            continue
        expires = _parse_datetime(alert.get("expireTime", alert.get("endTime")))
        if expires is not None and expires <= current_time:
            continue
        active.append(alert)
    if not active:
        return None

    def priority(alert: dict[str, Any]) -> tuple[int, int, float]:
        severity = str(alert.get("severity") or "unknown").lower()
        color = _color_code(alert)
        issued = _parse_datetime(alert.get("issuedTime", alert.get("pubTime")))
        timestamp = issued.timestamp() if issued else 0.0
        return SEVERITY_RANK.get(severity, 0), COLOR_RANK.get(color, 0), timestamp

    selected = max(active, key=priority)
    event_name = _event_name(selected, tr)
    color_code = _color_code(selected)
    return {
        "id": str(selected.get("id") or ""),
        "name": (_display_alert_name(event_name, color_code, tr)
                 if language.startswith("zh") and any("\u4e00" <= c <= "\u9fff" for c in event_name)
                 else str(selected.get("headline") or selected.get("title") or event_name)),
        "eventName": event_name,
        "senderName": str(selected.get("senderName") or ""),
        "severity": str(selected.get("severity") or "unknown").lower(),
        "colorCode": color_code,
        "headline": str(selected.get("headline") or selected.get("title") or ""),
        "description": str(selected.get("description") or selected.get("text") or ""),
        "instruction": str(selected.get("instruction") or ""),
        "issuedTime": str(selected.get("issuedTime") or selected.get("pubTime") or ""),
        "effectiveTime": str(selected.get("effectiveTime") or selected.get("startTime") or ""),
        "expireTime": str(selected.get("expireTime") or selected.get("endTime") or ""),
        "sources": _attributions(payload),
    }


def build_snapshot(
    current_payload: dict[str, Any],
    daily_payload: dict[str, Any],
    alert_payload: dict[str, Any],
    location_label: str,
    fetched_at: datetime | None = None,
    language: str = "zh",
    tr=str,
) -> dict[str, Any]:
    current = parse_current(current_payload, tr)
    daily = parse_daily(daily_payload, tr)
    alert = select_alert(alert_payload, fetched_at, language, tr)
    when = fetched_at or datetime.now(timezone.utc)
    sources = _unique(
        [*current["sources"], *daily["sources"], *_attributions(alert_payload)]
    )
    return {
        "location": location_label,
        "temperature": current["temperature"],
        "conditionText": current["conditionText"],
        "conditionCode": current["conditionCode"],
        "temperatureMax": daily["temperatureMax"],
        "temperatureMin": daily["temperatureMin"],
        "alert": alert,
        "sources": sources,
        "updatedAt": when.astimezone(timezone.utc).isoformat(),
        "stale": False,
        "alertStale": False,
        "warningAvailable": True,
        "warningStatus": "available" if alert else "no_data",
    }


def normalize_location_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact, QML-safe GeoAPI location candidates."""

    locations = payload.get("location", [])
    if not isinstance(locations, list):
        return []
    results: list[dict[str, Any]] = []
    for item in locations:
        if not isinstance(item, dict):
            continue
        try:
            latitude = float(item["lat"])
            longitude = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not valid_coordinates(latitude, longitude):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        adm2 = str(item.get("adm2") or "").strip()
        adm1 = str(item.get("adm1") or "").strip()
        country = str(item.get("country") or "").strip()
        parts = _unique([name, adm2, adm1, country])
        results.append(
            {
                "name": name,
                "id": str(item.get("id") or "").strip(),
                "country": country,
                "adm": adm2 or adm1,
                "adm2": adm2,
                "adm1": adm1,
                "label": " · ".join(parts),
                "latitude": latitude,
                "longitude": longitude,
            }
        )
    return results
