import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from weather_core import (
    WeatherDataError,
    build_snapshot,
    clamp_refresh_minutes,
    normalize_api_host,
    normalize_location_results,
    select_alert,
)


NOW = datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc)
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class ConfigurationTests(unittest.TestCase):
    def test_refresh_interval_is_clamped(self):
        self.assertEqual(clamp_refresh_minutes(1), 15)
        self.assertEqual(clamp_refresh_minutes(30), 30)
        self.assertEqual(clamp_refresh_minutes(999), 360)
        self.assertEqual(clamp_refresh_minutes("bad"), 30)

    def test_api_host_is_normalized_and_restricted(self):
        self.assertEqual(
            normalize_api_host("HTTPS://ABC123.QWEATHERAPI.COM/"),
            "abc123.qweatherapi.com",
        )
        with self.assertRaises(ValueError):
            normalize_api_host("http://abc123.qweatherapi.com")
        with self.assertRaises(ValueError):
            normalize_api_host("https://example.com")
        with self.assertRaises(ValueError):
            normalize_api_host("https://abc.qweatherapi.com/weather")


class SnapshotTests(unittest.TestCase):
    def test_v1_snapshot(self):
        snapshot = build_snapshot(
            fixture("current_v1.json"),
            fixture("daily_v1.json"),
            fixture("alerts_none.json"),
            "海淀区 · 北京市",
            NOW,
        )
        self.assertEqual(snapshot["temperature"], 23)
        self.assertEqual(snapshot["conditionText"], "局部多云")
        self.assertEqual(snapshot["temperatureMax"], 29)
        self.assertEqual(snapshot["temperatureMin"], 20)
        self.assertIsNone(snapshot["alert"])
        self.assertEqual(snapshot["sources"], ["QWeather"])

    def test_v7_compatibility_fixture(self):
        snapshot = build_snapshot(
            {"now": {"text": "晴", "icon": "100", "temp": "-2.6"}},
            {"daily": [{"tempMax": "2", "tempMin": "-8"}]},
            {"warning": []},
            "哈尔滨市 · 黑龙江省",
            NOW,
        )
        self.assertEqual(snapshot["temperature"], -3)
        self.assertEqual(snapshot["conditionCode"], "100")

    def test_missing_required_weather_field(self):
        with self.assertRaises(WeatherDataError):
            build_snapshot({}, {"days": []}, {}, "测试", NOW)


class AlertTests(unittest.TestCase):
    def alert(self, alert_id, severity, color, issued="2026-09-10T00:00:00Z", **extra):
        value = {
            "id": alert_id,
            "messageType": {"code": "alert", "supersedes": []},
            "eventType": {"name": "暴雨"},
            "severity": severity,
            "color": {"code": color},
            "issuedTime": issued,
            "senderName": "测试气象台",
            "expireTime": "2026-09-10T12:00:00Z",
            "headline": "暴雨预警",
            "description": "预计出现强降雨。",
            "instruction": "远离低洼区域。",
        }
        value.update(extra)
        return value

    def test_highest_severity_wins_before_color(self):
        payload = {
            "alerts": [
                self.alert("red", "moderate", "red"),
                self.alert("orange", "extreme", "orange"),
            ]
        }
        selected = select_alert(payload, NOW)
        self.assertEqual(selected["id"], "orange")
        self.assertEqual(selected["name"], "暴雨橙色预警")
        self.assertEqual(selected["senderName"], "测试气象台")

    def test_color_then_latest_issue_time_break_ties(self):
        payload = {
            "alerts": [
                self.alert("blue", "severe", "blue", "2026-09-10T00:30:00Z"),
                self.alert("orange-old", "severe", "orange", "2026-09-09T23:00:00Z"),
                self.alert("orange-new", "severe", "orange", "2026-09-10T00:10:00Z"),
            ]
        }
        self.assertEqual(select_alert(payload, NOW)["id"], "orange-new")

    def test_cancel_expired_and_superseded_are_ignored(self):
        old = self.alert("old", "extreme", "red")
        replacement = self.alert(
            "new",
            "minor",
            "blue",
            messageType={"code": "update", "supersedes": ["old"]},
        )
        cancelled = self.alert(
            "cancel", "extreme", "black", messageType={"code": "cancel"}
        )
        expired = self.alert(
            "expired", "extreme", "purple", expireTime="2026-09-09T12:00:00Z"
        )
        self.assertEqual(
            select_alert({"alerts": [old, replacement, cancelled, expired]}, NOW)["id"],
            "new",
        )


class LocationTests(unittest.TestCase):
    def test_location_labels_disambiguate_same_names(self):
        results = normalize_location_results(
            {
                "location": [
                    {"name": "鼓楼区", "adm2": "南京市", "adm1": "江苏省", "lat": "32.06", "lon": "118.77"},
                    {"name": "鼓楼区", "adm2": "福州市", "adm1": "福建省", "lat": "26.08", "lon": "119.30"},
                    {"name": "无坐标"},
                ]
            }
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["label"], "鼓楼区 · 南京市 · 江苏省")
        self.assertEqual(results[1]["adm"], "福州市")


if __name__ == "__main__":
    unittest.main()
