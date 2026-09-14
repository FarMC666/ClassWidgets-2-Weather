"""Qt network backend exposed to the weather widget QML."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from weather_core import (
    WeatherDataError,
    build_snapshot,
    clamp_refresh_minutes,
    normalize_api_host,
    normalize_location_results,
    qweather_language,
    valid_coordinates,
)


JsonCallback = Callable[[dict[str, Any] | None, str | None], None]


class WeatherBackend(QObject):
    weatherUpdated = Signal(str, dict)
    weatherFailed = Signal(str, str, bool)
    locationSearchFinished = Signal(str, list)
    locationSearchFailed = Signal(str, str)
    credentialsTested = Signal(bool, str)
    globalConfigChanged = Signal()
    instanceStatusChanged = Signal(str, dict)
    languageChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._callbacks: dict[QNetworkReply, JsonCallback] = {}
        self._reply_timers: dict[QNetworkReply, QTimer] = {}
        self._config: Any = None
        self._save_config: Callable[[], Any] | None = None
        self._instances: dict[str, dict[str, Any]] = {}
        self._weather_cache: dict[str, dict[str, Any]] = {}
        self._weather_inflight: dict[str, dict[str, Any]] = {}
        self._location_searches: dict[str, dict[str, Any]] = {}
        self._auto_location: dict[str, Any] | None = None
        self._auto_inflight = False
        self._available_icons: set[str] = set()
        self._language = "zh_CN"
        self._tr = str
        self._generation = 0

        self._scheduler = QTimer(self)
        self._scheduler.setInterval(30_000)
        self._scheduler.timeout.connect(self._tick)
        self._scheduler.start()

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return self._language

    def set_language(self, language: str, translate: Callable[[str], str]) -> None:
        self._tr = translate
        if language == self._language:
            return
        self._language = language
        self._cancel_pending_requests()
        self._weather_cache.clear()
        self._location_searches.clear()
        self.languageChanged.emit()
        # Clear displayed provider text before any new request can fail.
        for instance_id in self._instances:
            self.weatherUpdated.emit(instance_id, {})
        self._reconfigure_all()

    def _localized_get(self, path: str, callback: JsonCallback) -> None:
        """Ignore responses from an old language/credential generation."""
        generation = self._generation

        def finished(payload, error):
            if generation == self._generation:
                code = str((payload or {}).get("code") or "200")
                if not error and code != "200":
                    if path.startswith("/geo/") and code == "404":
                        payload = {"location": []}
                    else:
                        error = self._friendly_error(int(code) if code.isdigit() else 0, code)
                        payload = None
                callback(payload, error)

        self._qweather_get(path, finished)

    def bind_config(self, config: Any, save_config: Callable[[], Any]) -> None:
        self._config = config
        self._save_config = save_config
        self.globalConfigChanged.emit()

    def set_icon_directory(self, path: Path) -> None:
        if path.is_dir():
            self._available_icons = {item.stem for item in path.glob("*.svg")}

    @Property(dict, notify=globalConfigChanged)
    def globalConfig(self) -> dict[str, str]:
        return {
            "api_host": str(getattr(self._config, "api_host", "") or ""),
            "api_key": str(getattr(self._config, "api_key", "") or ""),
        }

    def _credentials(self) -> tuple[str, str]:
        host = str(getattr(self._config, "api_host", "") or "").strip()
        key = str(getattr(self._config, "api_key", "") or "").strip()
        if not host or not key:
            raise ValueError(self._tr("请先在插件设置中配置和风天气 API Host 和 API KEY"))
        return normalize_api_host(host), key

    @Slot(str, str, result=bool)
    def saveCredentials(self, api_host: str, api_key: str) -> bool:
        try:
            host = normalize_api_host(api_host)
            key = (api_key or "").strip()
            if not key:
                raise ValueError(self._tr("请填写和风天气 API KEY"))
        except ValueError as error:
            self.credentialsTested.emit(False, self._tr(str(error)))
            return False
        self._config.api_host = host
        self._config.api_key = key
        if self._save_config:
            self._save_config()
        self._cancel_pending_requests()
        self._weather_cache.clear()
        self.globalConfigChanged.emit()
        self.credentialsTested.emit(True, self._tr("设置已保存"))
        self._reconfigure_all()
        return True

    @Slot()
    def testCredentials(self) -> None:
        try:
            self._credentials()
        except ValueError as error:
            self.credentialsTested.emit(False, self._tr(str(error)))
            return

        path = f"/weather/v1/current/39.92/116.41?localTime=true&lang={qweather_language(self._language)}"

        def finished(payload: dict[str, Any] | None, error: str | None) -> None:
            if error:
                self.credentialsTested.emit(False, error)
                return
            condition = payload.get("condition") if isinstance(payload, dict) else None
            if not isinstance(condition, dict):
                self.credentialsTested.emit(False, self._tr("认证成功，但实时天气响应格式异常"))
                return
            self.credentialsTested.emit(True, self._tr("连接成功，可以获取和风天气数据"))

        self._localized_get(path, finished)

    @staticmethod
    def _variant_map(value: Any) -> dict[str, Any]:
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _normalized_settings(value: Any) -> dict[str, Any]:
        raw = WeatherBackend._variant_map(value)
        mode = str(raw.get("location_mode") or "auto")
        if mode not in {"auto", "custom"}:
            mode = "auto"
        return {
            "location_mode": mode,
            "custom_name": str(raw.get("custom_name") or "").strip(),
            "custom_adm": str(raw.get("custom_adm") or "").strip(),
            "custom_label": str(raw.get("custom_label") or "").strip(),
            "custom_id": str(raw.get("custom_id") or "").strip(),
            "custom_country": str(raw.get("custom_country") or "").strip(),
            "refresh_minutes": clamp_refresh_minutes(raw.get("refresh_minutes", 30)),
        }

    @Slot(str, dict)
    def subscribe(self, instance_id: str, settings: dict[str, Any]) -> None:
        if not instance_id:
            return
        normalized = self._normalized_settings(settings)
        old = self._instances.get(instance_id)
        signature = (
            normalized["location_mode"],
            normalized["custom_name"],
            normalized["custom_adm"],
            normalized["custom_id"],
            normalized["custom_country"],
        )
        state = old or {"location": None, "next_due": 0.0, "signature": None}
        changed_location = state.get("signature") != signature
        state.update(settings=normalized, signature=signature)
        if changed_location:
            for context in self._weather_inflight.values():
                context["waiters"].discard(instance_id)
            state["location"] = None
            state["next_due"] = 0.0
        self._instances[instance_id] = state
        if state.get("location"):
            self._request_weather(instance_id)
        elif normalized["location_mode"] == "custom":
            self._resolve_custom(instance_id)
        else:
            self._bind_auto(instance_id)

    @Slot(str)
    def unsubscribe(self, instance_id: str) -> None:
        self._instances.pop(instance_id, None)

    @Slot(str)
    def refresh(self, instance_id: str) -> None:
        state = self._instances.get(instance_id)
        if not state:
            return
        if state.get("location"):
            self._request_weather(instance_id, force=True)
        elif state["settings"]["location_mode"] == "custom":
            self._resolve_custom(instance_id)
        else:
            self._bind_auto(instance_id)

    @Slot(str)
    def relocate(self, instance_id: str) -> None:
        state = self._instances.get(instance_id)
        if not state:
            return
        self._ensure_auto_location(force=True)

    @Slot(str, result=dict)
    def getInstanceStatus(self, instance_id: str) -> dict[str, Any]:
        state = self._instances.get(instance_id, {})
        location = state.get("location") or {}
        cache = self._weather_cache.get(str(location.get("key") or ""), {})
        snapshot = cache.get("snapshot") or {}
        updated_at = str(snapshot.get("updatedAt") or "")
        if updated_at:
            try:
                updated_at = (
                    datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    .astimezone()
                    .strftime("%Y-%m-%d %H:%M")
                )
            except ValueError:
                pass
        return {
            "location": str(location.get("label") or self._tr("尚未定位")),
            "updatedAt": updated_at or self._tr("尚未更新"),
        }

    @Slot(str, str)
    def searchLocations(self, request_id: str, query: str) -> None:
        query = (query or "").strip()
        self._location_searches[request_id] = {"done": False, "results": [], "error": ""}
        while len(self._location_searches) > 32:
            self._location_searches.pop(next(iter(self._location_searches)))
        if len(query) < 2:
            self._location_searches[request_id] = {
                "done": True,
                "results": [],
                "error": self._tr("请输入至少两个字符"),
            }
            self.locationSearchFailed.emit(request_id, self._tr("请输入至少两个字符"))
            return
        try:
            path = "/geo/v2/city/lookup?" + urlencode(
                {"location": query, "number": 20, "lang": qweather_language(self._language)}
            )
            self._localized_get(
                path,
                lambda payload, error: self._finish_location_search(request_id, payload, error),
            )
        except ValueError as error:
            self._location_searches[request_id] = {
                "done": True,
                "results": [],
                "error": self._tr(str(error)),
            }
            self.locationSearchFailed.emit(request_id, self._tr(str(error)))

    @Slot(str, result=dict)
    def getLocationSearch(self, request_id: str) -> dict[str, Any]:
        return dict(
            self._location_searches.get(
                request_id, {"done": False, "results": [], "error": ""}
            )
        )

    def _finish_location_search(
        self, request_id: str, payload: dict[str, Any] | None, error: str | None
    ) -> None:
        if error:
            self._location_searches[request_id] = {
                "done": True,
                "results": [],
                "error": error,
            }
            self.locationSearchFailed.emit(request_id, error)
            return
        results = normalize_location_results(payload or {})
        if not results:
            self._location_searches[request_id] = {
                "done": True,
                "results": [],
                "error": self._tr("没有找到匹配地区"),
            }
            self.locationSearchFailed.emit(request_id, self._tr("没有找到匹配地区"))
            return
        self._location_searches[request_id] = {
            "done": True,
            "results": results,
            "error": "",
        }
        self.locationSearchFinished.emit(request_id, results)

    def _bind_auto(self, instance_id: str) -> None:
        if self._auto_location:
            self._set_instance_location(instance_id, self._auto_location)
            return
        self._ensure_auto_location()

    def _ensure_auto_location(self, force: bool = False) -> None:
        if self._auto_inflight:
            return
        if self._auto_location and not force:
            for instance_id, state in self._instances.items():
                if state["settings"]["location_mode"] == "auto":
                    self._set_instance_location(instance_id, self._auto_location)
            return
        self._auto_inflight = True
        url = (
            "https://ipwho.is/?fields=success,message,latitude,longitude,city,region,country,country_code"
        )
        generation = self._generation
        self._get_json(url, lambda payload, error: self._finish_ip_location(payload, error)
                       if generation == self._generation else None, authenticated=False)

    def _finish_ip_location(
        self, payload: dict[str, Any] | None, error: str | None
    ) -> None:
        if error or not payload or not payload.get("success"):
            self._auto_inflight = False
            self._fail_auto(error or str((payload or {}).get("message") or self._tr("IP 定位失败")))
            return
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
            if not valid_coordinates(latitude, longitude):
                raise ValueError("Invalid coordinates")
        except (KeyError, TypeError, ValueError):
            self._auto_inflight = False
            self._fail_auto(self._tr("IP 定位结果缺少有效坐标"))
            return
        fallback_label = " · ".join(
            part for part in [str(payload.get("city") or ""), str(payload.get("region") or ""),
                              str(payload.get("country") or payload.get("country_code") or "")] if part
        ) or self._tr("自动定位")
        short_name = str(payload.get("city") or payload.get("region") or
                         payload.get("country") or payload.get("country_code") or
                         self._tr("自动定位"))
        location = self._location(latitude, longitude, fallback_label, short_name)
        try:
            path = "/geo/v2/city/lookup?" + urlencode(
                {"location": f"{longitude:.2f},{latitude:.2f}", "number": 1, "lang": qweather_language(self._language)}
            )
            self._localized_get(
                path,
                lambda geo, geo_error: self._finish_auto_geo(location, geo, geo_error),
            )
        except ValueError:
            self._finish_auto_geo(location, None, self._tr("尚未配置天气服务"))

    def _finish_auto_geo(
        self,
        fallback: dict[str, Any],
        payload: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        location = dict(fallback)
        fallback_label = str(location.get("label") or self._tr("自动定位"))
        fallback_label = str(location.get("baseLabel") or fallback_label)
        location["baseLabel"] = fallback_label
        location["label"] = self._tr("{location}（IP 近似）").format(location=fallback_label)
        if not error:
            candidates = normalize_location_results(payload or {})
            if candidates:
                candidate = candidates[0]
                label_parts: list[str] = []
                for part in (candidate["adm2"] or candidate["name"], candidate["adm1"], candidate["country"]):
                    if part and part not in label_parts:
                        label_parts.append(part)
                label = " · ".join(label_parts) or candidate["name"]
                location = self._location(
                    fallback["latitude"],
                    fallback["longitude"],
                    self._tr("{location}（IP 近似）").format(location=label),
                    candidate["adm2"] or candidate["name"],
                )
                location["baseLabel"] = label
        self._auto_inflight = False
        self._auto_location = location
        for instance_id, state in list(self._instances.items()):
            if state["settings"]["location_mode"] == "auto":
                self._set_instance_location(instance_id, location)

    def _fail_auto(self, message: str) -> None:
        for instance_id, state in self._instances.items():
            if state["settings"]["location_mode"] == "auto":
                location = state.get("location") or self._auto_location or {}
                cache = self._weather_cache.get(str(location.get("key") or ""), {})
                self.weatherFailed.emit(
                    instance_id,
                    self._tr("定位失败：{message}，请改用手动选区").format(message=message),
                    bool(cache.get("snapshot")),
                )

    def _resolve_custom(self, instance_id: str) -> None:
        state = self._instances.get(instance_id)
        if not state:
            return
        settings = state["settings"]
        name = settings["custom_name"]
        adm = settings["custom_adm"]
        location_id = settings["custom_id"]
        if not name and not location_id:
            self.weatherFailed.emit(instance_id, self._tr("请在小组件设置中选择地区"), False)
            return
        params: dict[str, Any] = {
            "location": location_id or name,
            "number": 20,
            "lang": qweather_language(self._language),
        }
        if adm and not location_id:
            params["adm"] = adm
        signature = state["signature"]
        try:
            self._localized_get(
                "/geo/v2/city/lookup?" + urlencode(params),
                lambda payload, error: self._finish_custom_location(
                    instance_id, signature, payload, error
                ),
            )
        except ValueError as error:
            self.weatherFailed.emit(instance_id, self._tr(str(error)), False)

    def _finish_custom_location(
        self,
        instance_id: str,
        signature: tuple[str, ...],
        payload: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        state = self._instances.get(instance_id)
        if not state or state.get("signature") != signature:
            return
        if error:
            self.weatherFailed.emit(instance_id, error, False)
            return
        candidates = normalize_location_results(payload or {})
        location_id = state["settings"]["custom_id"]
        if location_id:
            candidates = [item for item in candidates if item["id"] == location_id]
        elif state["settings"]["custom_country"]:
            candidates = [item for item in candidates
                          if item["country"] == state["settings"]["custom_country"]]
        if not candidates:
            self.weatherFailed.emit(instance_id, self._tr("无法解析已选择的地区，请重新搜索"), False)
            return
        name = state["settings"]["custom_name"]
        adm = state["settings"]["custom_adm"]
        matches = [item for item in candidates if item["name"] == name
                   and (not adm or adm in {item["adm"], item["adm1"], item["adm2"]})]
        if location_id or len(candidates) == 1:
            selected = candidates[0]
        elif len(matches) == 1:
            selected = matches[0]
        else:
            self.weatherFailed.emit(instance_id, self._tr("地区名称存在歧义，请重新搜索并选择准确城市"), False)
            return
        self._set_instance_location(
            instance_id,
            self._location(selected["latitude"], selected["longitude"], selected["label"], selected["name"]),
        )

    @staticmethod
    def _location(latitude: float, longitude: float, label: str, short_name: str = "") -> dict[str, Any]:
        latitude = round(float(latitude), 2)
        longitude = round(float(longitude), 2)
        return {
            "latitude": latitude,
            "longitude": longitude,
            "label": label,
            "shortName": short_name or label.split(" · ", 1)[0],
            "key": f"{latitude:.2f},{longitude:.2f}",
        }

    def _set_instance_location(self, instance_id: str, location: dict[str, Any]) -> None:
        state = self._instances.get(instance_id)
        if not state:
            return
        state["location"] = dict(location)
        state["next_due"] = 0.0
        self.instanceStatusChanged.emit(instance_id, self.getInstanceStatus(instance_id))
        self._request_weather(instance_id)

    def _snapshot_for_instance(self, instance_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Keep display names instance-specific while weather caches share coordinates."""
        location = self._instances.get(instance_id, {}).get("location") or {}
        result = dict(snapshot)
        result["location"] = location.get("baseLabel") or location.get("label") or snapshot.get("location", "")
        result["locationName"] = location.get("shortName") or result["location"].split(" · ", 1)[0]
        return result

    def _request_weather(self, instance_id: str, force: bool = False) -> None:
        state = self._instances.get(instance_id)
        if not state or not state.get("location"):
            return
        try:
            self._credentials()
        except ValueError as error:
            self.weatherFailed.emit(instance_id, self._tr(str(error)), False)
            return
        location = state["location"]
        key = location["key"]
        now = time.monotonic()
        cached = self._weather_cache.get(key)
        interval = state["settings"]["refresh_minutes"] * 60
        if cached and not force and now - cached["fetched"] < interval:
            self.weatherUpdated.emit(instance_id, self._snapshot_for_instance(instance_id, cached["snapshot"]))
            state["next_due"] = cached["fetched"] + interval
            self.instanceStatusChanged.emit(instance_id, self.getInstanceStatus(instance_id))
            return
        inflight = self._weather_inflight.get(key)
        if inflight:
            inflight["waiters"].add(instance_id)
            return

        lat = location["latitude"]
        lon = location["longitude"]
        context = {
            "location": dict(location),
            "pending": {"current", "daily", "alerts"},
            "payloads": {},
            "errors": {},
            "waiters": {instance_id},
        }
        self._weather_inflight[key] = context
        paths = {
            "current": f"/weather/v1/current/{lat:.2f}/{lon:.2f}?localTime=true&lang={qweather_language(self._language)}",
            "daily": f"/weather/v1/daily/{lat:.2f}/{lon:.2f}?days=1&localTime=true&lang={qweather_language(self._language)}",
            "alerts": f"/weatheralert/v1/current/{lat:.2f}/{lon:.2f}?localTime=true&lang={qweather_language(self._language)}",
        }
        for kind, path in paths.items():
            self._localized_get(
                path,
                lambda payload, error, item=kind, cache_key=key: self._weather_part_finished(
                    cache_key, item, payload, error
                ),
            )

    def _weather_part_finished(
        self,
        key: str,
        kind: str,
        payload: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        context = self._weather_inflight.get(key)
        if not context:
            return
        context["pending"].discard(kind)
        if kind == "alerts" and not error:
            data = payload or {}
            metadata = data.get("metadata") or {}
            if not isinstance(data.get("alerts", data.get("warning")), list) and not (
                isinstance(metadata, dict) and metadata.get("zeroResult") is True
            ):
                error = self._tr("预警响应格式无效")
        if error:
            context["errors"][kind] = error
        elif payload is not None:
            context["payloads"][kind] = payload
        if context["pending"]:
            return
        self._weather_inflight.pop(key, None)
        self._finalize_weather(key, context)

    def _finalize_weather(self, key: str, context: dict[str, Any]) -> None:
        waiters = set(context["waiters"])
        errors = context["errors"]
        cached = self._weather_cache.get(key)
        required_error = errors.get("current") or errors.get("daily")
        if required_error:
            self._publish_failure(waiters, required_error, cached)
            return
        try:
            snapshot = build_snapshot(
                context["payloads"]["current"],
                context["payloads"]["daily"],
                context["payloads"].get("alerts", {}),
                context["location"]["label"],
                datetime.now(timezone.utc),
                language=qweather_language(self._language),
                tr=self._tr,
            )
        except (KeyError, WeatherDataError, TypeError, ValueError) as error:
            self._publish_failure(waiters, self._tr("天气数据解析失败：{error}").format(error=error), cached)
            return

        alert_error = errors.get("alerts")
        if alert_error:
            snapshot["warningAvailable"] = False
            snapshot["warningStatus"] = "unavailable"
            old_alert = (cached or {}).get("snapshot", {}).get("alert")
            if old_alert:
                snapshot["alert"] = dict(old_alert)
                snapshot["alertStale"] = True
            for instance_id in waiters:
                self.weatherFailed.emit(instance_id, self._tr("预警数据暂不可用：{error}").format(error=alert_error), True)

        code = str(snapshot.get("conditionCode") or "999")
        if self._available_icons and code not in self._available_icons:
            snapshot["conditionCode"] = "999"

        fetched = time.monotonic()
        self._weather_cache[key] = {"snapshot": snapshot, "fetched": fetched}
        recipients = {
            instance_id
            for instance_id, state in self._instances.items()
            if (state.get("location") or {}).get("key") == key
        } | waiters
        for instance_id in recipients:
            state = self._instances.get(instance_id)
            if not state:
                continue
            state["next_due"] = fetched + state["settings"]["refresh_minutes"] * 60
            self.weatherUpdated.emit(instance_id, self._snapshot_for_instance(instance_id, snapshot))
            self.instanceStatusChanged.emit(instance_id, self.getInstanceStatus(instance_id))

    def _publish_failure(
        self,
        instance_ids: set[str],
        message: str,
        cached: dict[str, Any] | None,
    ) -> None:
        now = time.monotonic()
        for instance_id in instance_ids:
            state = self._instances.get(instance_id)
            has_cache = bool(cached and cached.get("snapshot"))
            if has_cache:
                stale = dict(cached["snapshot"])
                stale["stale"] = True
                self.weatherUpdated.emit(instance_id, self._snapshot_for_instance(instance_id, stale))
            self.weatherFailed.emit(instance_id, message, has_cache)
            if state:
                state["next_due"] = now + min(
                    300, state["settings"]["refresh_minutes"] * 60
                )

    def _tick(self) -> None:
        now = time.monotonic()
        for instance_id, state in list(self._instances.items()):
            if state.get("location") and now >= float(state.get("next_due") or 0):
                self._request_weather(instance_id)

    def _reconfigure_all(self) -> None:
        auto_instances: list[str] = []
        for instance_id, state in list(self._instances.items()):
            state["location"] = None
            state["next_due"] = 0.0
            if state["settings"]["location_mode"] == "custom":
                self._resolve_custom(instance_id)
            else:
                auto_instances.append(instance_id)
        if not auto_instances:
            return
        if not self._auto_location:
            self._ensure_auto_location()
            return

        # Re-resolve the existing IP coordinate after credentials change without
        # making another request to the IP location service.
        self._auto_inflight = True
        fallback = dict(self._auto_location)
        path = "/geo/v2/city/lookup?" + urlencode(
            {
                "location": f"{fallback['longitude']:.2f},{fallback['latitude']:.2f}",
                "number": 1,
                "lang": qweather_language(self._language),
            }
        )
        try:
            self._localized_get(
                path,
                lambda payload, error: self._finish_auto_geo(fallback, payload, error),
            )
        except ValueError as error:
            self._finish_auto_geo(fallback, None, self._tr(str(error)))

    def _qweather_get(self, path: str, callback: JsonCallback) -> None:
        host, _ = self._credentials()
        self._get_json(f"https://{host}{path}", callback, authenticated=True)

    def _get_json(
        self, url: str, callback: JsonCallback, authenticated: bool
    ) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"ClassWidgets-Weather/0.2.0")
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(15_000)
        if authenticated:
            _, api_key = self._credentials()
            request.setRawHeader(b"X-QW-Api-Key", api_key.encode("utf-8"))
        reply = self._network.get(request)
        self._callbacks[reply] = callback
        reply.finished.connect(lambda current=reply: self._finish_reply(current))

        # QNetworkRequest.setTransferTimeout() only covers transfer inactivity on
        # some Qt/network backends.  Keep an absolute deadline as well so DNS,
        # proxy and connection stalls cannot leave the settings page spinning.
        timeout = QTimer(reply)
        timeout.setSingleShot(True)
        timeout.setInterval(15_000)
        timeout.timeout.connect(lambda current=reply: self._timeout_reply(current))
        self._reply_timers[reply] = timeout
        timeout.start()

    def _timeout_reply(self, reply: QNetworkReply) -> None:
        callback = self._callbacks.pop(reply, None)
        timeout = self._reply_timers.pop(reply, None)
        if timeout is not None:
            timeout.stop()
            timeout.deleteLater()
        if callback is None:
            return
        try:
            reply.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            reply.abort()
        except RuntimeError:
            pass
        reply.deleteLater()
        callback(None, self._tr("天气服务连接超时"))

    def _finish_reply(self, reply: QNetworkReply) -> None:
        callback = self._callbacks.pop(reply, None)
        timeout = self._reply_timers.pop(reply, None)
        if timeout is not None:
            timeout.stop()
            timeout.deleteLater()
        if callback is None:
            reply.deleteLater()
            return
        status_value = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        try:
            status = int(status_value) if status_value is not None else 0
        except (TypeError, ValueError):
            status = 0
        raw = bytes(reply.readAll())
        error_code = reply.error()
        network_error = error_code != QNetworkReply.NetworkError.NoError
        timed_out = error_code in {
            QNetworkReply.NetworkError.TimeoutError,
            QNetworkReply.NetworkError.OperationCanceledError,
        }
        error_text = reply.errorString()
        reply.deleteLater()
        if network_error or status >= 400:
            callback(
                None,
                self._tr("天气服务连接超时")
                if timed_out and not status
                else self._friendly_error(status, error_text),
            )
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(self._tr("JSON 根节点不是对象"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            callback(None, self._tr("服务响应无法解析：{error}").format(error=error))
            return
        callback(payload, None)

    def _friendly_error(self, status: int, fallback: str) -> str:
        if status == 401:
            return self._tr("认证失败，请检查 API Host 和 API KEY")
        if status == 403:
            return self._tr("请求被拒绝，请检查凭据权限和 API Host")
        if status == 429:
            return self._tr("请求过于频繁或免费额度已用尽")
        if status:
            return self._tr("天气服务返回 HTTP {status}").format(status=status)
        lowered = (fallback or "").lower()
        if "timeout" in lowered or "timed out" in lowered:
            return self._tr("天气服务连接超时")
        return self._tr("网络请求失败：{error}").format(error=fallback or self._tr("未知错误"))

    def shutdown(self) -> None:
        self._scheduler.stop()
        try:
            self._scheduler.timeout.disconnect(self._tick)
        except (RuntimeError, TypeError):
            pass
        self._cancel_pending_requests()
        self._instances.clear()

    def _cancel_pending_requests(self) -> None:
        self._generation += 1
        for timeout in list(self._reply_timers.values()):
            timeout.stop()
            timeout.deleteLater()
        self._reply_timers.clear()
        for reply in list(self._callbacks):
            try:
                reply.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                reply.abort()
            except RuntimeError:
                pass
            reply.deleteLater()
        self._callbacks.clear()
        self._weather_inflight.clear()
        self._auto_inflight = False
        for request_id, state in list(self._location_searches.items()):
            if not state["done"]:
                self._finish_location_search(request_id, None, self._tr("搜索已取消，请重新搜索"))
