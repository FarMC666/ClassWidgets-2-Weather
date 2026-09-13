import sys
import types
import unittest
from enum import IntEnum
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit


class _BoundSignal:
    def __init__(self):
        self.emissions = []
        self.callbacks = []

    def emit(self, *args):
        self.emissions.append(args)
        for callback in list(self.callbacks):
            callback(*args)

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback=None):
        if callback is None:
            self.callbacks.clear()
        elif callback in self.callbacks:
            self.callbacks.remove(callback)


class _Signal:
    def __init__(self, *_args):
        self.name = ""

    def __set_name__(self, _owner, name):
        self.name = name

    def __get__(self, instance, _owner):
        if instance is None:
            return self
        key = "_test_signal_" + self.name
        if key not in instance.__dict__:
            instance.__dict__[key] = _BoundSignal()
        return instance.__dict__[key]


class _QObject:
    def __init__(self, parent=None):
        self.parent = parent


class _QTimer:
    def __init__(self, _parent=None):
        self.timeout = _BoundSignal()
        self.running = False

    def setInterval(self, _value):
        pass

    def setSingleShot(self, _value):
        pass

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def deleteLater(self):
        pass


class _QUrl:
    def __init__(self, value):
        self.value = value


def _property(*_args, **_kwargs):
    return property


def _slot(*_args, **_kwargs):
    return lambda function: function


class _NetworkError(IntEnum):
    NoError = 0
    TimeoutError = 4
    OperationCanceledError = 5


class _QNetworkReply:
    NetworkError = _NetworkError


class _QNetworkRequest:
    HttpStatusCodeAttribute = 0

    def __init__(self, _url):
        pass


class _QNetworkAccessManager:
    def __init__(self, _parent=None):
        pass


if "PySide6" not in sys.modules:
    pyside = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtnetwork = types.ModuleType("PySide6.QtNetwork")
    qtcore.QObject = _QObject
    qtcore.Property = _property
    qtcore.QTimer = _QTimer
    qtcore.QUrl = _QUrl
    qtcore.Signal = _Signal
    qtcore.Slot = _slot
    qtnetwork.QNetworkAccessManager = _QNetworkAccessManager
    qtnetwork.QNetworkReply = _QNetworkReply
    qtnetwork.QNetworkRequest = _QNetworkRequest
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtNetwork"] = qtnetwork

from weather_backend import WeatherBackend


CURRENT = {
    "condition": {"text": "多云", "code": "101"},
    "temperature": {"value": 23},
}
DAILY = {
    "days": [
        {
            "temperatureMax": {"value": 29},
            "temperatureMin": {"value": 20},
        }
    ]
}
ALERTS = {
    "metadata": {"attributions": ["QWeather"]},
    "alerts": [
        {
            "id": "warning-1",
            "senderName": "测试气象台",
            "messageType": {"code": "alert", "supersedes": []},
            "eventType": {"name": "暴雨"},
            "severity": "severe",
            "color": {"code": "orange"},
            "issuedTime": "2099-01-01T00:00:00+08:00",
            "expireTime": "2099-01-02T00:00:00+08:00",
        }
    ],
}


class BackendHarness(WeatherBackend):
    def __init__(self):
        self.requests = []
        super().__init__()

    def _qweather_get(self, path, callback):
        self.requests.append((path, callback))


def finish_batch(requests, errors=None):
    errors = errors or {}
    payload_by_path = {
        "/weather/v1/current/": CURRENT,
        "/weather/v1/daily/": DAILY,
        "/weatheralert/v1/current/": ALERTS,
    }
    for path, callback in list(requests):
        kind = next(prefix for prefix in payload_by_path if path.startswith(prefix))
        error = errors.get(kind)
        callback(None if error else payload_by_path[kind], error)


class WeatherBackendCoordinationTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()
        self.backend.bind_config(
            SimpleNamespace(api_host="test.qweatherapi.com", api_key="not-a-real-key"),
            lambda: None,
        )
        self.location = self.backend._location(39.92, 116.41, "北京市")
        self.backend._auto_location = self.location

    def tearDown(self):
        self.backend.shutdown()

    def test_same_coordinate_merges_requests_and_reuses_cache(self):
        settings = {"location_mode": "auto", "refresh_minutes": 30}
        self.backend.subscribe("a", settings)
        self.backend.subscribe("b", settings)

        self.assertEqual(len(self.backend.requests), 3)
        self.assertEqual(
            self.backend._weather_inflight[self.location["key"]]["waiters"],
            {"a", "b"},
        )

        finish_batch(self.backend.requests)
        recipients = {args[0] for args in self.backend.weatherUpdated.emissions}
        self.assertEqual(recipients, {"a", "b"})

        request_count = len(self.backend.requests)
        self.backend.subscribe("c", settings)
        self.assertEqual(len(self.backend.requests), request_count)
        self.assertEqual(self.backend.weatherUpdated.emissions[-1][0], "c")

    def test_required_failure_keeps_last_snapshot_as_stale(self):
        settings = {"location_mode": "auto", "refresh_minutes": 30}
        self.backend.subscribe("a", settings)
        finish_batch(self.backend.requests)
        cached_before = self.backend._weather_cache[self.location["key"]]["snapshot"]

        start = len(self.backend.requests)
        self.backend.refresh("a")
        finish_batch(
            self.backend.requests[start:],
            {"/weather/v1/current/": "天气服务连接超时"},
        )

        stale = self.backend.weatherUpdated.emissions[-1][1]
        failure = self.backend.weatherFailed.emissions[-1]
        self.assertTrue(stale["stale"])
        self.assertTrue(failure[2])
        self.assertEqual(
            self.backend._weather_cache[self.location["key"]]["snapshot"],
            cached_before,
        )

    def test_alert_failure_preserves_previous_alert(self):
        settings = {"location_mode": "auto", "refresh_minutes": 30}
        self.backend.subscribe("a", settings)
        finish_batch(self.backend.requests)

        start = len(self.backend.requests)
        self.backend.refresh("a")
        finish_batch(
            self.backend.requests[start:],
            {"/weatheralert/v1/current/": "预警服务不可用"},
        )

        snapshot = self.backend.weatherUpdated.emissions[-1][1]
        self.assertEqual(snapshot["alert"]["id"], "warning-1")
        self.assertTrue(snapshot["alertStale"])
        self.assertFalse(snapshot["warningAvailable"])

    def test_readable_http_errors(self):
        self.assertIn("认证失败", self.backend._friendly_error(401, ""))
        self.assertIn("请求被拒绝", self.backend._friendly_error(403, ""))
        self.assertIn("额度", self.backend._friendly_error(429, ""))

    def test_foreign_ip_is_accepted_with_geo_failure_fallback(self):
        self.backend._auto_location = None
        self.backend._instances["a"] = {
            "settings": {"location_mode": "auto", "refresh_minutes": 30},
            "location": None,
            "next_due": 0.0,
        }
        self.backend._auto_inflight = True

        self.backend._finish_ip_location(
            {
                "success": True,
                "country_code": "US",
                "latitude": 34.05,
                "longitude": -118.24,
                "city": "Los Angeles",
            },
            None,
        )

        path, callback = self.backend.requests[-1]
        self.assertNotIn("range", parse_qs(urlsplit(path).query))
        callback(None, "Geo service unavailable")
        self.assertFalse(self.backend._auto_inflight)
        self.assertEqual(self.backend._auto_location["longitude"], -118.24)
        self.assertIn("Los Angeles", self.backend._auto_location["label"])
        self.assertIn("IP 近似", self.backend._auto_location["label"])
        self.assertEqual(len(self.backend.requests), 4)

    def test_global_search_and_credentials_use_host_language(self):
        for locale, lang in [("en_US", "en"), ("ja_JP", "ja"), ("zh_HK", "zh-hant")]:
            self.backend.set_language(locale, str)
            self.backend.searchLocations("search", "東京")
            params = parse_qs(urlsplit(self.backend.requests[-1][0]).query)
            self.assertEqual(params["lang"], [lang])
            self.assertEqual(params["location"], ["東京"])
            self.assertNotIn("range", params)
            self.backend.testCredentials()
            self.assertIn("lang=" + lang, self.backend.requests[-1][0])

    def test_location_id_survives_restart_and_translated_name(self):
        settings = {"location_mode": "custom", "custom_id": "GB-LONDON",
                    "custom_name": "伦敦", "custom_adm": "英格兰", "custom_country": "英国"}
        self.backend.set_language("en_US", str)
        self.backend.subscribe("london", settings)
        path, callback = self.backend.requests[-1]
        params = parse_qs(urlsplit(path).query)
        self.assertEqual(params["location"], ["GB-LONDON"])
        self.assertNotIn("adm", params)
        callback({"location": [
            {"id": "CA-LONDON", "name": "London", "country": "Canada", "lat": 42.98, "lon": -81.25},
            {"id": "GB-LONDON", "name": "London", "country": "United Kingdom", "lat": 51.51, "lon": -0.13}
        ]}, None)
        self.assertEqual(self.backend._instances["london"]["location"]["key"], "51.51,-0.13")
        for path, _ in self.backend.requests[-3:]:
            self.assertIn("/51.51/-0.13?", path)
            self.assertIn("lang=en", path)

    def test_legacy_settings_still_resolve_and_preserve_credentials(self):
        old = {"location_mode": "custom", "custom_name": "海淀", "custom_adm": "北京",
               "custom_label": "海淀 · 北京", "refresh_minutes": 45}
        self.backend.subscribe("legacy", old)
        params = parse_qs(urlsplit(self.backend.requests[-1][0]).query)
        self.assertEqual(params["location"], ["海淀"])
        self.assertEqual(params["adm"], ["北京"])
        self.backend.requests[-1][1]({"location": [
            {"id": "101010200", "name": "海淀", "adm1": "北京", "lat": 39.96, "lon": 116.30}
        ]}, None)
        self.assertEqual(self.backend._instances["legacy"]["location"]["key"], "39.96,116.30")
        self.assertEqual(self.backend._instances["legacy"]["settings"]["refresh_minutes"], 45)
        self.assertEqual(self.backend.globalConfig["api_key"], "not-a-real-key")
        self.assertNotIn("custom_id", old)

    def test_ambiguous_legacy_location_does_not_choose_first_city(self):
        self.backend.subscribe("ambiguous", {"location_mode": "custom", "custom_name": "London"})
        self.backend.requests[-1][1]({"location": [
            {"name": "London", "country": "Canada", "lat": 42.98, "lon": -81.25},
            {"name": "London", "country": "United Kingdom", "lat": 51.51, "lon": -0.13}
        ]}, None)
        self.assertIsNone(self.backend._instances["ambiguous"]["location"])
        self.assertIn("歧义", self.backend.weatherFailed.emissions[-1][1])

    def test_language_change_invalidates_cache_and_all_old_callbacks(self):
        self.backend.subscribe("a", {"location_mode": "auto"})
        finish_batch(self.backend.requests)
        self.backend.refresh("a")
        old_weather = self.backend.requests[-3:]
        self.backend.searchLocations("old-search", "London")
        old_search = self.backend.requests[-1][1]
        self.backend.set_language("en_US", str)
        self.assertFalse(self.backend._weather_cache)
        self.assertEqual(self.backend.weatherUpdated.emissions[-1], ("a", {}))
        geo_path, geo_callback = self.backend.requests[-1]
        self.assertIn("lang=en", geo_path)
        geo_callback({"location": [{"name": "Beijing", "country": "China", "lat": 39.92, "lon": 116.41}]}, None)
        new_weather = self.backend.requests[-3:]
        finish_batch(old_weather)
        old_search({"location": [{"name": "旧地区", "lat": 0, "lon": 0}]}, None)
        self.assertFalse(self.backend._weather_cache)
        self.assertFalse(self.backend.getLocationSearch("old-search")["done"])
        self.assertEqual(len(self.backend._weather_inflight[self.location["key"]]["pending"]), 3)
        finish_batch(new_weather)
        self.assertIn("Beijing", self.backend.weatherUpdated.emissions[-1][1]["location"])

    def test_invalid_global_coordinates_are_rejected(self):
        for latitude, longitude in [(91, 0), (0, -181), (float("nan"), 0), (0, float("inf"))]:
            self.backend._auto_inflight = True
            self.backend._finish_ip_location({"success": True, "country_code": "US",
                                              "latitude": latitude, "longitude": longitude}, None)
            self.assertFalse(self.backend._auto_inflight)
            self.assertEqual(self.backend.requests, [])

    def test_alert_zero_result_failure_and_malformed_response_are_distinct(self):
        for payload, error, available, status in [
            ({"metadata": {"zeroResult": True}, "alerts": []}, None, True, "no_data"),
            (None, "HTTP 404", False, "unavailable"),
            ({"unexpected": []}, None, False, "unavailable"),
        ]:
            self.backend._weather_cache.clear()
            self.backend.subscribe("a", {"location_mode": "auto"})
            for path, callback in self.backend.requests[-3:]:
                if "weatheralert" in path:
                    callback(payload, error)
                else:
                    callback(CURRENT if "/current/" in path else DAILY, None)
            snapshot = self.backend.weatherUpdated.emissions[-1][1]
            self.assertEqual(snapshot["temperature"], 23)
            self.assertEqual(snapshot["warningAvailable"], available)
            self.assertEqual(snapshot["warningStatus"], status)

    def test_geo_api_body_error_codes_are_not_reported_as_no_matches(self):
        for code, expected in [("401", "认证"), ("403", "拒绝"), ("429", "额度"), ("404", "匹配")]:
            self.backend.searchLocations(code, "London")
            self.backend.requests[-1][1]({"code": code}, None)
            self.assertIn(expected, self.backend.getLocationSearch(code)["error"])

    def test_auto_location_uses_city_label_and_keeps_ip_coordinates(self):
        fallback = self.backend._location(30.30, 120.10, "Hangzhou · Zhejiang")
        self.backend._instances["a"] = {
            "settings": {"location_mode": "auto", "refresh_minutes": 30},
            "location": None,
            "next_due": 0.0,
        }

        self.backend._finish_auto_geo(
            fallback,
            {
                "location": [
                    {
                        "name": "拱墅",
                        "adm1": "浙江省",
                        "adm2": "杭州",
                        "lat": "30.32",
                        "lon": "120.17",
                    }
                ]
            },
            None,
        )

        location = self.backend._instances["a"]["location"]
        self.assertEqual(location["label"], "杭州 · 浙江省（IP 近似）")
        self.assertEqual(location["latitude"], 30.30)
        self.assertEqual(location["longitude"], 120.10)

    def test_absolute_timeout_finishes_callback_once(self):
        class FakeReply:
            def __init__(self):
                self.finished = _BoundSignal()
                self.aborted = False
                self.deleted = False

            def abort(self):
                self.aborted = True

            def deleteLater(self):
                self.deleted = True

        reply = FakeReply()
        timer = _QTimer()
        timer.start()
        results = []
        self.backend._callbacks[reply] = lambda payload, error: results.append((payload, error))
        self.backend._reply_timers[reply] = timer

        self.backend._timeout_reply(reply)
        self.backend._timeout_reply(reply)

        self.assertEqual(results, [(None, "天气服务连接超时")])
        self.assertTrue(reply.aborted)
        self.assertTrue(reply.deleted)
        self.assertFalse(timer.running)

    def test_location_search_result_can_be_polled(self):
        self.backend._finish_location_search(
            "search-1",
            {
                "location": [
                    {
                        "name": "杭州",
                        "adm1": "浙江省",
                        "adm2": "杭州",
                        "lat": "30.27",
                        "lon": "120.15",
                    }
                ]
            },
            None,
        )

        state = self.backend.getLocationSearch("search-1")
        self.assertTrue(state["done"])
        self.assertEqual(state["error"], "")
        self.assertEqual(state["results"][0]["name"], "杭州")

    def test_cancel_pending_search_finishes_signals_and_polling(self):
        self.backend.searchLocations("search-1", "杭州")
        self.assertFalse(self.backend.getLocationSearch("search-1")["done"])

        self.backend.saveCredentials("new.qweatherapi.com", "new-test-key")

        state = self.backend.getLocationSearch("search-1")
        self.assertTrue(state["done"])
        self.assertIn("取消", state["error"])
        self.assertEqual(self.backend.locationSearchFailed.emissions[-1],
                         ("search-1", state["error"]))


if __name__ == "__main__":
    unittest.main()
