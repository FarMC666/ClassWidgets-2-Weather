"""Exercise the real settings page in Qt, isolated from the backend test doubles."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WeatherQmlTests(unittest.TestCase):
    def test_widget_clicks_do_not_trigger_host_hide(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests/qml_widget_clicks.py")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode == 77:
            self.skipTest("Install PySide6 and RinUI to run the QML integration test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_settings_in_real_qml_engine(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--qt-checks"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode == 77:
            self.skipTest("Install PySide6 and RinUI to run the QML integration test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def qt_checks():
    import ast
    import importlib.util
    import json
    import tempfile
    import time
    from types import SimpleNamespace

    if not importlib.util.find_spec("PySide6") or not importlib.util.find_spec("RinUI"):
        return 77

    from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
    from PySide6.QtTest import QTest

    sys.path.insert(0, str(ROOT))
    from weather_backend import WeatherBackend

    # Load the actual plugin class with a minimal host base. All Qt methods,
    # properties and signal forwarding come from main.py, not test doubles.
    class PluginBase(QObject):
        def __init__(self, api):
            super().__init__()

    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    plugin_class = next(node for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == "Plugin")
    namespace = dict(QObject=QObject, Property=Property, Signal=Signal, Slot=Slot,
                     CW2Plugin=PluginBase, PluginAPI=object, WeatherBackend=WeatherBackend,
                     WeatherConfig=lambda: SimpleNamespace(api_host="", api_key=""))
    exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "main.py", "exec"), namespace)
    app = QGuiApplication([])
    plugin = namespace["Plugin"](None)
    backend = plugin.backend
    backend.bind_config(plugin.config, lambda: None)
    requests = []
    backend._qweather_get = lambda path, callback: requests.append(callback)

    class WidgetsModel(QObject):
        definitionChanged = Signal()

        @Property("QVariantList", notify=definitionChanged)
        def definitionsList(self):
            return [{"id": "com.farmc.classwidgets.weather.widget", "backend_obj": backend}]

    widgets_model = WidgetsModel()
    with tempfile.TemporaryDirectory() as temp:
        # SettingsLayout is the host's ColumnLayout with settings and instanceId.
        module = Path(temp) / "ClassWidgets" / "Plugins"
        module.mkdir(parents=True)
        (module / "qmldir").write_text("module ClassWidgets.Plugins\nSettingsLayout 1.0 SettingsLayout.qml\n")
        (module / "SettingsLayout.qml").write_text(
            'import QtQuick\nimport QtQuick.Layouts\nColumnLayout { '
            'property var settings: null; property string instanceId: "" }'
        )
        engine = QQmlEngine()
        engine.addImportPath(temp)
        rinui = importlib.util.find_spec("RinUI")
        engine.addImportPath(str(Path(rinui.origin).parent.parent))
        # The actual widgets window has WidgetsModel, but NO plugin bridge.
        # Supplying a bridge here hides the production ReferenceError.
        engine.rootContext().setContextProperty("WidgetsModel", widgets_model)
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "qml/WeatherWidgetSettings.qml")))
        page = component.createWithInitialProperties({"width": 600, "settings": {"location_mode": "custom"}})
        assert page is not None, [error.toString() for error in component.errors()]

        def evaluate(source):
            expression = QQmlExpression(engine.contextForObject(page), page, source)
            value, _ = expression.evaluate()
            assert not expression.hasError(), expression.error().toString()
            return value

        QTest.qWait(30)
        assert evaluate("typeof PluginBackendBridge") == "undefined"
        assert page.property("weatherBackend") is backend
        # The host can assign the instance after Component.onCompleted.
        page.setProperty("instanceId", "test")
        QTest.qWait(30)
        assert "test" in backend._instances
        assert "选择地区" in page.property("actionMessage")

        backend._instances["test"]["location"] = backend._location(30.27, 120.15, "杭州")
        backend._weather_cache["30.27,120.15"] = {
            "fetched": time.monotonic(),
            "snapshot": {"updatedAt": "2026-09-12T10:00:00+08:00"},
        }
        evaluate("updateInstanceStatus()")
        assert page.property("instanceStatus")["location"] == "杭州"
        assert page.property("instanceStatus")["updatedAt"] != "尚未更新"

        # Refresh must use the existing widget instance and publish the new
        # weather back into this same settings page without any plugin bridge.
        plugin.config.api_host = "test.qweatherapi.com"
        plugin.config.api_key = "test-key"
        weather_requests = []
        backend._qweather_get = lambda path, callback: weather_requests.append((path, callback))
        evaluate("runInstanceAction('refresh')")
        assert len(weather_requests) == 3
        assert page.property("actionKind") == "refresh"
        for path, callback in weather_requests:
            fixture = ("alerts_none.json" if "weatheralert" in path else
                       "daily_v1.json" if "/daily/" in path else "current_v1.json")
            callback(json.loads((ROOT / "tests/fixtures" / fixture).read_text(encoding="utf-8")), None)
        assert page.property("actionKind") == ""
        assert page.property("actionMessage") == "天气刷新完成"
        assert backend._weather_cache["30.27,120.15"]["snapshot"]["temperature"] == 23
        backend._qweather_get = lambda path, callback: requests.append(callback)

        evaluate("locationQuery.text = '杭州'; searchLocations()")
        assert evaluate("searchButton.enabled")
        assert page.property("searching")
        requests.pop()({"location": [{"name": "杭州", "lat": "30.27", "lon": "120.15"}]}, None)
        assert not page.property("searching")
        assert evaluate("searchResults[0].name") == "杭州"
        assert not evaluate("searchTimeout.running")

        # Polling still completes if a completion signal is missed.
        evaluate("searchLocations()")
        backend.blockSignals(True)
        requests.pop()(None, "网络错误")
        backend.blockSignals(False)
        QTest.qWait(300)
        assert not page.property("searching")
        assert page.property("searchMessage") == "网络错误"

        # A synchronous failure must also stop the deadline timer.
        backend._qweather_get = lambda path, callback: callback(None, "认证失败")
        evaluate("searchLocations()")
        assert page.property("searchMessage") == "认证失败"
        assert not evaluate("searchTimeout.running")

        # A missing method used to throw before starting the timeout, leaving
        # '正在搜索' indefinitely. Keep the same QML page to test this path.
        evaluate("weatherBackend = ({}); searchLocations()")
        assert not page.property("searching")
        assert "无法启动" in page.property("searchMessage")
        evaluate("updateInstanceStatus()")
        assert page.property("instanceStatus")["location"] == "杭州"
        assert "无法读取" in page.property("actionMessage")

        evaluate("weatherBackend = resolveWeatherBackend()")
        backend._qweather_get = lambda path, callback: requests.append(callback)
        evaluate("searchLocations(); searchTimeout.triggered()")
        assert "超时" in page.property("searchMessage")
        requests.pop()(None, "late response")
        assert "超时" in page.property("searchMessage")

        # Live status signals must not overwrite an unsaved region selection.
        evaluate("locationSelectionPending = true; instanceStatus = ({location:'待保存',updatedAt:'保存后自动刷新'})")
        backend.instanceStatusChanged.emit("test", {"location": "旧地区", "updatedAt": "旧时间"})
        assert evaluate("instanceStatus.location") == "待保存"
        backend.shutdown()
        page.deleteLater()
        app.processEvents()
    return 0


if __name__ == "__main__":
    if "--qt-checks" in sys.argv:
        sys.exit(qt_checks())
    unittest.main()
