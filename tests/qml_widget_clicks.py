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
    if sys.platform == "win32":
        chinese_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
        if chinese_font.exists():
            QFontDatabase.addApplicationFont(str(chinese_font))
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
        # Preserve the host's content-slot insets and inherited height behavior.
        # A plain Item misses both padding overflow and the theme's rebound.
        (module / "Widget.qml").write_text(
            'import QtQuick\nItem { property bool miniMode: false; property bool hide: false; property var backend: null; '
            'property var settings: ({}); property string instanceId: ""; property string text: ""; '
            'default property alias content: viewport.data; '
            'Item { id: viewport; anchors.fill: parent; anchors.leftMargin: 24; anchors.rightMargin: 24; '
            'anchors.topMargin: 16; anchors.bottomMargin: 18 } '
            'Behavior on height { NumberAnimation { duration: 400; easing.type: Easing.OutBack } } }'
        )
        (module / "Title.qml").write_text('import QtQuick\nText { property int px: 28; font.pixelSize: px; font.weight: 600 }')
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
            width: item ? item.implicitWidth : 230
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
        QTest.qWait(250)
        host = view.rootObject()
        loader = host.findChild(QQuickItem, "loader")
        widget = loader.property("item")
        widget.setProperty("snapshot", {
            "temperature": 23, "conditionText": "多云", "location": "测试地区",
            "alert": {"name": "暴雨预警", "headline": "测试预警", "description": "预警详情"},
        })
        QTest.qWait(30)
        assert widget.height() == 100, "An active alert must not increase collapsed height"

        def position(name):
            item = widget.findChild(QQuickItem, name)
            assert item and item.isVisible() and item.width() > 0 and item.height() > 0, (
                name, item and (item.isVisible(), item.width(), item.height(), item.property("text"))
            )
            return item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()

        def click(name, button=Qt.MouseButton.LeftButton):
            QTest.mouseClick(view, button, Qt.KeyboardModifier.NoModifier, position(name))
            QTest.qWait(450)

        click("weatherAlertToggle")
        assert widget.property("detailsExpanded")
        assert host.property("hideCount") == 0, "Opening alert details also triggered host hide"
        click("weatherAlertToggle")
        assert not widget.property("detailsExpanded")
        assert widget.height() == 100
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
            QTest.qWait(450)

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
                         widget.mapToScene(QPointF(30, 20)).toPoint())
        assert host.property("hideCount") == 1
        widget.setProperty("miniMode", True)
        QTest.qWait(30)
        click("miniWeatherAttribution")
        assert widget.height() == 56
        assert widget.implicitWidth() == 250
        assert len(links.urls) == 3
        assert host.property("hideCount") == 1
        widget.setProperty("miniMode", False)
        widget.setProperty("snapshot", {"temperature": 23, "temperatureMax": 29, "temperatureMin": 20})
        QTest.qWait(30)
        click("weatherAlertToggle")
        assert not widget.property("detailsExpanded")
        assert host.property("hideCount") == 2

        # Both source links must stop taking taps while the host is collapsed,
        # and resume after it is pulled out. Events can reach the host instead.
        for mini, link in [(False, "weatherAttribution"), (True, "miniWeatherAttribution")]:
            widget.setProperty("miniMode", mini)
            QTest.qWait(450)
            widget.setProperty("hide", True)
            before_urls = len(links.urls)
            before_hide = host.property("hideCount")
            click(link)
            touch(link)
            assert len(links.urls) == before_urls, "A hidden source link opened the browser"
            assert host.property("hideCount") == before_hide + 2, "Hidden links blocked host taps"
            # Hiding during a press must cancel its activation as well.
            widget.setProperty("hide", False)
            point = position(link)
            QTest.touchEvent(view, touch_device).press(0, point, view).commit()
            widget.setProperty("hide", True)
            QTest.touchEvent(view, touch_device).release(0, point, view).commit()
            QTest.qWait(450)
            assert len(links.urls) == before_urls
            widget.setProperty("hide", False)
            before_hide = host.property("hideCount")
            click(link)
            touch(link)
            assert len(links.urls) == before_urls + 2
            assert host.property("hideCount") == before_hide

        widget.setProperty("miniMode", False)
        assert widget.implicitWidth() == 230
        location = widget.findChild(QQuickItem, "weatherLocation")
        attribution = widget.findChild(QQuickItem, "weatherAttribution")
        footer = widget.findChild(QQuickItem, "weatherLocationFooter")
        summary = widget.findChild(QQuickItem, "weatherAlertToggle")
        assert widget.findChild(QQuickItem, "weatherLocationToggle") is None
        assert widget.findChild(QQuickItem, "weatherLocationDetails") is None
        for width in (230, 180):
            loader.setWidth(width)
            for name, full in [
                ("余杭区", "余杭区 · 杭州 · 浙江"),
                ("Los Angeles", "Los Angeles · California · United States"),
                ("Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch", "Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch · Wales · United Kingdom"),
                ("一个用来验证超长中文地名显示效果的城市" * 3, "一个用来验证超长中文地名显示效果的城市" * 3 + " · 省份 · 国家"),
                ("", "余杭区·杭州·浙江"),
            ]:
                widget.setProperty("snapshot", {"temperature": 22, "conditionText": "Cloudy",
                    "temperatureMax": 30, "temperatureMin": 19, "locationName": name, "location": full})
                QTest.qWait(450)
                assert widget.height() == 100
                assert location.property("text") == (name or "余杭区")
                assert location.property("lineCount") == 1
                assert abs(location.mapToItem(widget, QPointF(0, 0)).x()
                           - summary.mapToItem(widget, QPointF(0, 0)).x()) < 0.1
                assert location.mapToItem(footer, QPointF(location.width(), 0)).x() + 7 <= attribution.x()
                assert attribution.x() + attribution.width() <= footer.width() + 1
                assert footer.mapToItem(widget, QPointF(0, footer.height())).y() <= widget.height()
                if len(name) > 30:
                    assert location.property("truncated"), name
                assert "IP" not in location.property("text")
                assert "≈" not in location.property("text")

        before_hide = host.property("hideCount")
        click("weatherLocation")
        touch("weatherLocation")
        assert host.property("hideCount") == before_hide + 2
        assert widget.height() == 100
        assert not widget.property("detailsExpanded")

        preview_dir = os.environ.get("WEATHER_QML_PREVIEW_DIR")
        if preview_dir:
            Path(preview_dir).mkdir(parents=True, exist_ok=True)
            loader.setWidth(230)
            widget.setProperty("snapshot", {"temperature": 22, "conditionText": "多云",
                "temperatureMax": 30, "temperatureMin": 19, "locationName": "余杭区",
                "location": "余杭区 · 杭州 · 浙江"})
            QTest.qWait(450)
            view.grabWindow().save(str(Path(preview_dir) / "location-collapsed.png"))
        view.close()
    QDesktopServices.unsetUrlHandler("https")
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
