"""Native catalogs, all three QML pages and the actual plugin lifecycle."""

import ast
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if not importlib.util.find_spec("PySide6") or not importlib.util.find_spec("RinUI"):
        return 77
    from PySide6.QtCore import QObject, Property, QLocale, QTranslator, Signal, Slot, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
    from PySide6.QtTest import QTest
    from weather_backend import WeatherBackend
    from weather_i18n import WeatherTranslations, translate

    app = QGuiApplication([])
    # Release packages contain .qm files; catch stale/missing compiled catalogs.
    for path in (ROOT / "locales").glob("*.ts"):
        catalog = QTranslator()
        assert catalog.load(str(path.with_suffix(".qm"))), path
        for message in ET.parse(path).findall(".//message"):
            assert catalog.translate("Weather", message.findtext("source")) == message.findtext("translation"), (path, message.findtext("source"))

    class Configs(QObject):
        configChanged = Signal()
        locale = SimpleNamespace(language="en_US")

    class Base(QObject):
        def __init__(self, api):
            super().__init__()
            self.api, self.PATH = api, ROOT
            self.meta = {"id": "com.farmc.classwidgets.weather"}

        def on_load(self):
            self.pid = self.meta["id"]
            self.api.set_current_plugin(self)

        def on_unload(self):
            pass

    class Api:
        def __init__(self):
            self.current_plugin = None
            self.configs = Configs()
            self.globalconfig = SimpleNamespace(configs=self.configs)
            self.config = SimpleNamespace(register_plugin_model=lambda *args: None, save=lambda: None)
            self.widgets = SimpleNamespace(register=self.register_widget)
            self.ui = SimpleNamespace(register_settings_page=self.register_page,
                                      unregister_settings_page=self.unregister_page)
            self.definitions, self.pages = {}, {}

        def set_current_plugin(self, plugin):
            self.current_plugin = plugin

        def register_widget(self, **kwargs):
            assert self.current_plugin is plugin
            self.definitions[kwargs["widget_id"]] = kwargs

        def register_page(self, **kwargs):
            assert self.current_plugin is plugin
            self.pages[kwargs["qml_path"]] = kwargs

        def unregister_page(self, path):
            assert self.current_plugin is plugin
            self.pages.pop(path, None)

    api = Api()
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Plugin")
    namespace = dict(QObject=QObject, Property=Property, Signal=Signal, Slot=Slot, Path=Path,
                     CW2Plugin=Base, PluginAPI=object, WeatherBackend=WeatherBackend,
                     WeatherTranslations=WeatherTranslations, translate=translate,
                     WeatherConfig=lambda: SimpleNamespace(api_host="", api_key=""))
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "main.py", "exec"), namespace)
    plugin = namespace["Plugin"](api)
    plugin.on_load()
    backend = plugin.backend
    assert translate("天气") == "Weather"
    assert backend.language == "en_US"

    class Bridge(QObject):
        @Slot(str, result=QObject)
        def get_backend(self, _pid):
            return plugin

    class Widgets(QObject):
        changed = Signal()

        @Property("QVariantList", notify=changed)
        def definitionsList(self):
            return [{"id": "com.farmc.classwidgets.weather.widget", "backend_obj": backend}]

    bridge, widgets = Bridge(), Widgets()
    with tempfile.TemporaryDirectory() as temp:
        module = Path(temp) / "ClassWidgets/Plugins"
        module.mkdir(parents=True)
        (module / "qmldir").write_text("module ClassWidgets.Plugins\nSettingsLayout 1.0 SettingsLayout.qml\nPluginPage 1.0 PluginPage.qml\n")
        (module / "SettingsLayout.qml").write_text('import QtQuick\nimport QtQuick.Layouts\nColumnLayout { property var settings: ({}); property string instanceId: "" }')
        (module / "PluginPage.qml").write_text('import QtQuick\nItem {}')
        theme = Path(temp) / "ClassWidgets/Theme"
        theme.mkdir(parents=True)
        (theme / "qmldir").write_text("module ClassWidgets.Theme\nWidget 1.0 Widget.qml\nTitle 1.0 Title.qml\n")
        (theme / "Widget.qml").write_text('import QtQuick\nItem { property bool miniMode: false; property bool hide: false; property var backend: null; property var settings: ({}); property string instanceId: ""; property string text: "" }')
        (theme / "Title.qml").write_text('import QtQuick\nText { property int px: 25; font.pixelSize: px }')
        engine = QQmlEngine()
        engine.addImportPath(temp)
        engine.addImportPath(str(Path(importlib.util.find_spec("RinUI").origin).parent.parent))
        engine.rootContext().setContextProperty("PluginBackendBridge", bridge)
        engine.rootContext().setContextProperty("WidgetsModel", widgets)
        # The host calls engine.retranslate after its AppTranslator updates locale.
        api.configs.configChanged.connect(engine.retranslate)
        components, pages = [], []
        for filename in ("PluginSettings.qml", "WeatherWidgetSettings.qml", "WeatherWidget.qml"):
            component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "qml" / filename)))
            page = component.createWithInitialProperties({"width": 700})
            assert page is not None, [e.toString() for e in component.errors()]
            components.append(component)
            pages.append(page)
        QTest.qWait(40)
        settings, widget = pages[1:]

        def evaluate(page, source):
            expression = QQmlExpression(engine.contextForObject(page), page, source)
            result, _ = expression.evaluate()
            assert not expression.hasError(), expression.error().toString()
            return result

        for locale, weather, search, saved, high in [
            ("en_US", "Weather", "Search", "Settings saved", "High 25°  Low 10°"),
            ("ja_JP", "天気", "検索", "設定を保存しました", "最高 25°  最低 10°"),
            ("zh_HK", "天氣", "搜尋", "設定已儲存", "最高 25°  最低 10°"),
            ("zh_CN", "天气", "搜索", "设置已保存", "最高 25°  最低 10°"),
            ("xx_YY", "Weather", "Search", "Settings saved", "High 25°  Low 10°"),
        ]:
            api.current_plugin = "another-plugin"
            api.configs.locale.language = locale
            QLocale.setDefault(QLocale(locale))
            api.configs.configChanged.emit()
            QTest.qWait(10)
            assert api.current_plugin == "another-plugin"
            assert backend.language == locale
            assert translate("天气") == weather
            assert api.definitions["com.farmc.classwidgets.weather.widget"]["name"] == weather
            assert len(api.pages) == 1
            assert api.pages["qml/PluginSettings.qml"]["title"] == weather
            assert evaluate(settings, "searchButton.text") == search
            assert translate("设置已保存") == saved
            evaluate(widget, "snapshot = ({temperatureMax:25,temperatureMin:10})")
            assert evaluate(widget, "summaryText()") == high
            assert backend.saveCredentials("example.com", "key") is False
            assert pages[0].property("resultMessage") == translate("请填写控制台分配的 *.qweatherapi.com 专属域名")

        # A selection must persist its stable identity, including after retranslation.
        evaluate(settings, 'locationMode.currentIndex = 1; searchResults = [{id:"JP-TOKYO",name:"東京",adm:"東京都",country:"日本",label:"東京 · 日本"}]')
        QTest.qWait(10)
        assert evaluate(settings, 'locationResults.itemAt(0).text') == "東京 · 日本"
        evaluate(settings, 'locationResults.itemAt(0).clicked()')
        chosen = settings.property("settings").toVariant()
        assert chosen["custom_id"] == "JP-TOKYO" and chosen["custom_country"] == "日本"
        api.configs.locale.language = "ja_JP"
        api.configs.configChanged.emit()
        assert settings.property("locationSelectionPending")
        assert "確定後" in settings.property("searchMessage")
        assert settings.property("settings").toVariant()["custom_id"] == "JP-TOKYO"

        # Language changes also work before credentials are configured, and do
        # not repeat IP detection when a session coordinate already exists.
        backend._auto_location = backend._location(-33.87, 151.21, "Sydney")
        backend.subscribe("unconfigured", {"location_mode": "auto"})
        api.configs.locale.language = "en_US"
        api.configs.configChanged.emit()
        assert backend.getInstanceStatus("unconfigured")["location"] == "Sydney (approximate IP location)"
        assert not backend._auto_inflight
        assert "Configure" in translate("请先在插件设置中配置和风天气 API Host 和 API KEY")

        # Unloading removes the translator and disconnects from host changes.
        plugin.on_unload()
        assert api.current_plugin == "another-plugin"
        assert translate("天气") == "天气"
        api.configs.locale.language = "en_US"
        api.configs.configChanged.emit()
        assert translate("天气") == "天气"
        for page in pages:
            page.deleteLater()
        app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
