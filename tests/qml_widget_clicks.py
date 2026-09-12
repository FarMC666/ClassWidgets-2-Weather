"""Send real pointer events through the widget and the host's ancestor handlers."""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile


def main():
    if not importlib.util.find_spec("PySide6") or not importlib.util.find_spec("RinUI"):
        return 77

    from PySide6.QtCore import QObject, QPointF, QUrl, Qt, Slot
    from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication
    from PySide6.QtQuick import QQuickItem, QQuickView
    from PySide6.QtTest import QTest

    app = QGuiApplication([])
    # Windows offscreen runs can lack font discovery in a sandbox. Load an
    # installed font explicitly so the link text has a real hit-test area.
    if sys.platform == "win32" and not QFontDatabase.families():
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"))
    root = Path(__file__).resolve().parents[1]

    class Links(QObject):
        def __init__(self):
            super().__init__()
            self.urls = []

        @Slot(QUrl)
        def opened(self, url):
            self.urls.append(url.toString())

    links = Links()
    QDesktopServices.setUrlHandler("https", links, "opened")
    with tempfile.TemporaryDirectory() as temp:
        module = Path(temp) / "ClassWidgets/Theme"
        module.mkdir(parents=True)
        (module / "qmldir").write_text("module ClassWidgets.Theme\nWidget 1.0 Widget.qml\nTitle 1.0 Title.qml\n")
        # Only theme visuals are replaced. Pointer handlers and the complete
        # weather widget are real QML, loaded unchanged from the plugin.
        (module / "Widget.qml").write_text(
            'import QtQuick\nItem { property bool miniMode: false; property var backend: null; '
            'property var settings: ({}); property string instanceId: ""; property string text: "" }'
        )
        (module / "Title.qml").write_text('import QtQuick\nText { property int px: 25; font.pixelSize: px }')
        harness = Path(temp) / "Harness.qml"
        widget_url = QUrl.fromLocalFile(str(root / "qml/WeatherWidget.qml")).toString()
        harness.write_text('''import QtQuick
Item {
    width: 320; height: 400
    property int hideCount: 0
    property int menuCount: 0
    // MainInterface.qml's hideTapHandler uses this default passive policy.
    TapHandler { onTapped: parent.hideCount++ }
    Item {
        anchors.fill: parent
        TapHandler { acceptedButtons: Qt.RightButton; onTapped: menuCount++ }
        Loader {
            objectName: "loader"
            width: 300
            source: "''' + widget_url + '''"
            TapHandler {} // WidgetLoader's pressed-animation handler.
        }
    }
}''', encoding="utf-8")
        view = QQuickView()
        view.engine().addImportPath(temp)
        view.engine().addImportPath(str(Path(importlib.util.find_spec("RinUI").origin).parent.parent))
        view.setSource(QUrl.fromLocalFile(str(harness)))
        assert view.status() == QQuickView.Status.Ready, [e.toString() for e in view.errors()]
        view.show()
        QTest.qWait(80)
        host = view.rootObject()
        loader = host.findChild(QQuickItem, "loader")
        widget = loader.property("item")
        widget.setProperty("snapshot", {
            "temperature": 23, "conditionText": "多云", "location": "测试地区",
            "alert": {"name": "暴雨预警", "headline": "测试预警", "description": "预警详情"},
        })
        QTest.qWait(30)

        def position(name):
            item = widget.findChild(QQuickItem, name)
            assert item and item.isVisible() and item.width() > 0 and item.height() > 0, (
                name, item and (item.isVisible(), item.width(), item.height(), item.property("text"))
            )
            return item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()

        def click(name, button=Qt.MouseButton.LeftButton):
            QTest.mouseClick(view, button, Qt.KeyboardModifier.NoModifier, position(name))
            QTest.qWait(30)

        click("weatherAlertToggle")
        assert widget.property("detailsExpanded")
        assert host.property("hideCount") == 0, "Opening alert details also triggered host hide"
        click("weatherAlertToggle")
        assert not widget.property("detailsExpanded")
        assert host.property("hideCount") == 0
        click("weatherAttribution")
        assert links.urls == ["https://www.qweather.com/"]
        assert host.property("hideCount") == 0
        click("weatherAttribution", Qt.MouseButton.RightButton)
        assert host.property("menuCount") == 1
        assert len(links.urls) == 1

        touch_device = QTest.createTouchDevice()

        def touch(name):
            point = position(name)
            QTest.touchEvent(view, touch_device).press(0, point, view).commit()
            QTest.touchEvent(view, touch_device).release(0, point, view).commit()
            QTest.qWait(30)

        touch("weatherAlertToggle")
        assert widget.property("detailsExpanded")
        assert host.property("hideCount") == 0
        touch("weatherAlertToggle")
        assert not widget.property("detailsExpanded")
        touch("weatherAttribution")
        assert len(links.urls) == 2
        assert host.property("hideCount") == 0

        # Other widget space still invokes the user's configured host action.
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         widget.mapToScene(QPointF(20, 10)).toPoint())
        assert host.property("hideCount") == 1
        widget.setProperty("miniMode", True)
        QTest.qWait(30)
        click("miniWeatherAttribution")
        assert len(links.urls) == 3
        assert host.property("hideCount") == 1
        widget.setProperty("miniMode", False)
        widget.setProperty("snapshot", {"temperature": 23, "temperatureMax": 29, "temperatureMin": 20})
        QTest.qWait(30)
        click("weatherAlertToggle")
        assert not widget.property("detailsExpanded")
        assert host.property("hideCount") == 2
        view.close()
    QDesktopServices.unsetUrlHandler("https")
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
