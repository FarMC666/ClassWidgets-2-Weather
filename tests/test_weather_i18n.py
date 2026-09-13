"""Catalog coverage, locale mapping and native Qt translation integration."""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from xml.etree import ElementTree as ET

from weather_core import COLOR_ZH, normalize_location_results, qweather_language, select_alert

ROOT = Path(__file__).resolve().parents[1]


class InternationalWeatherTests(unittest.TestCase):
    def test_locale_aliases_and_fallback(self):
        cases = {"zh_CN": "zh", "zh-Hans-SG": "zh", "zh_HK": "zh-hant",
                 "zh_TW": "zh-hant", "zh-MO": "zh-hant", "zh-Hant": "zh-hant",
                 "zh-Hans-HK": "zh", "en_GB": "en", "ja_JP": "ja", "pt_BR": "pt",
                 "nb_NO": "nb", "no_NO": "nb", "iw_IL": "he", "in_ID": "id",
                 "fil_PH": "fil", "lzh": "zh", "zh_SIMPLIFIED": "zh", "ta": "en",
                 "xx_YY": "en", "": "en"}
        for locale, expected in cases.items():
            with self.subTest(locale=locale):
                self.assertEqual(qweather_language(locale), expected)

    def test_global_candidates_keep_country_and_stable_id(self):
        locations = [
            {"name": "London", "id": "gb", "country": "United Kingdom", "lat": "51.51", "lon": "-0.13"},
            {"name": "London", "id": "ca", "country": "Canada", "lat": "42.98", "lon": "-81.25"},
            {"name": "São Paulo", "id": "br", "country": "Brazil", "lat": "-23.55", "lon": "-46.63"},
            {"name": "東京", "id": "jp", "country": "日本", "lat": "35.68", "lon": "139.69"},
            {"name": "Bad", "lat": "nan", "lon": 0},
            {"name": "Bad", "lat": 0, "lon": "inf"},
            {"name": "Bad", "lat": -91, "lon": 0},
        ]
        results = normalize_location_results({"location": locations})
        self.assertEqual(len(results), 4)
        self.assertNotEqual(results[0]["label"], results[1]["label"])
        self.assertEqual(results[2]["id"], "br")
        self.assertEqual(results[3]["country"], "日本")

    def test_foreign_alerts_keep_provider_headline_and_optional_color(self):
        for language, name, headline in [("en", "wind", "Strong Wind Warning - Orange"),
                                          ("ja", "大雨", "大雨警報"),
                                          ("zh", "wind", "Strong Wind Warning")]:
            for color in ({"code": "orange"}, None):
                selected = select_alert({"alerts": [{"eventType": {"name": name}, "headline": headline,
                                                       "severity": "severe", "color": color}]}, language=language)
                self.assertEqual(selected["name"], headline)
        selected = select_alert({"alerts": [{"eventType": {"name": "Flood Watch"}}]}, language="en")
        self.assertEqual(selected["name"], "Flood Watch")

    def test_catalogs_cover_all_user_messages_and_preserve_placeholders(self):
        required = set(COLOR_ZH.values())
        for filename in ("weather_backend.py", "weather_core.py", "main.py"):
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                value = node.args[0]
                if name in {"_tr", "tr", "translate", "ValueError"} and isinstance(value, ast.Constant):
                    if isinstance(value.value, str) and re.search(r"[\u4e00-\u9fff]", value.value):
                        required.add(value.value)
        for path in (ROOT / "qml").glob("*.qml"):
            for source in re.findall(r'qsTranslate\("Weather", ("(?:[^"\\]|\\.)*")\)', path.read_text(encoding="utf-8")):
                required.add(ast.literal_eval(source))
        placeholder = re.compile(r"%\d+|\{\w+\}")
        for path in (ROOT / "locales").glob("*.ts"):
            messages = ET.parse(path).findall(".//message")
            translations = {m.findtext("source"): m.findtext("translation") for m in messages}
            self.assertFalse(required - translations.keys(), (path.name, required - translations.keys()))
            for source, target in translations.items():
                self.assertTrue(target, (path.name, source))
                self.assertEqual(sorted(placeholder.findall(source)), sorted(placeholder.findall(target)))

    def test_native_qt_language_switch_and_plugin_lifecycle(self):
        result = subprocess.run([sys.executable, str(ROOT / "tests/qt_weather_i18n.py")],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"})
        if result.returncode == 77:
            self.skipTest("Install PySide6 and RinUI to run native translation tests")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
