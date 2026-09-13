import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

SettingsLayout {
    id: root

    property string widget_id: "com.farmc.classwidgets.weather.widget"
    property var weatherBackend: null
    property string requestId: ""
    property var searchResults: []
    property string searchMessage: ""
    property bool searching: false
    property bool locationSelectionPending: false
    property bool initializing: true
    property string actionKind: ""
    property string actionMessage: ""
    property var instanceStatus: ({"location": qsTranslate("Weather", "尚未定位"), "updatedAt": qsTranslate("Weather", "尚未更新")})

    function resolveWeatherBackend() {
        // Widget dialogs share the widgets window, which exposes WidgetsModel
        // but does not inject the global settings window's PluginBackendBridge.
        if (typeof WidgetsModel !== "undefined" && WidgetsModel) {
            var definitions = WidgetsModel.definitionsList || []
            for (var i = 0; i < definitions.length; ++i) {
                var definition = definitions[i]
                if (definition.id === root.widget_id && definition.backend_obj)
                    return definition.backend_obj
            }
        }
        if (typeof PluginBackendBridge !== "undefined" && PluginBackendBridge) {
            var plugin = PluginBackendBridge.get_backend("com.farmc.classwidgets.weather")
            if (plugin && plugin.weatherBackend)
                return plugin.weatherBackend
        }
        return null
    }

    function updateSettings(changes) {
        var updated = Object.assign({}, root.settings || {})
        for (var key in changes)
            updated[key] = changes[key]
        root.settings = updated
    }

    function saveLocationMode(mode) {
        updateSettings({"location_mode": mode})
    }

    function finishSearch(targetRequestId, results, message) {
        if (!root.searching || targetRequestId !== root.requestId)
            return
        searchTimeout.stop()
        root.searching = false
        root.searchResults = results || []
        root.searchMessage = message || (root.searchResults.length
                             ? qsTranslate("Weather", "请选择准确地区") : qsTranslate("Weather", "没有匹配地区"))
    }

    function searchLocations() {
        if (!root.weatherBackend)
            return
        root.requestId = root.instanceId + "-" + Date.now()
        root.searching = true
        root.searchMessage = qsTranslate("Weather", "正在搜索…")
        root.searchResults = []
        // Start before calling Python: it can fail or finish synchronously.
        searchTimeout.restart()
        try {
            root.weatherBackend.searchLocations(root.requestId, locationQuery.text)
        } catch (error) {
            finishSearch(root.requestId, [], qsTranslate("Weather", "无法启动地区搜索，请重新加载天气插件后重试"))
        }
    }

    function updateInstanceStatus() {
        if (!root.weatherBackend || !root.instanceId || root.locationSelectionPending)
            return
        try {
            var status = root.weatherBackend.getInstanceStatus(root.instanceId)
            if (status && status.location && status.updatedAt)
                root.instanceStatus = status
            else
                root.actionMessage = qsTranslate("Weather", "暂时无法读取当前状态，请重新加载天气插件")
        } catch (error) {
            root.actionMessage = qsTranslate("Weather", "暂时无法读取当前状态，请重新加载天气插件")
        }
    }

    function runInstanceAction(kind) {
        if (!root.weatherBackend || !root.instanceId) {
            root.actionMessage = qsTranslate("Weather", "操作失败：未找到小组件实例")
            return
        }
        root.weatherBackend.subscribe(root.instanceId, root.settings || {})
        root.actionKind = kind
        root.actionMessage = kind === "relocate" ? qsTranslate("Weather", "正在重新检测公网 IP 位置…") : qsTranslate("Weather", "正在刷新天气…")
        if (kind === "relocate")
            root.weatherBackend.relocate(root.instanceId)
        else
            root.weatherBackend.refresh(root.instanceId)
    }

    function initializeBackend() {
        root.weatherBackend = resolveWeatherBackend()
        var settings = root.settings || {}
        locationMode.currentIndex = settings.location_mode === "custom" ? 1 : 0
        refreshInterval.value = settings.refresh_minutes || 30
        root.initializing = false
        if (root.weatherBackend && instanceId) {
            root.actionMessage = ""
            root.weatherBackend.subscribe(instanceId, root.settings || {})
            updateInstanceStatus()
        } else if (!root.weatherBackend) {
            root.actionMessage = qsTranslate("Weather", "天气后端尚未就绪，正在等待小组件加载…")
        }
    }

    Component.onCompleted: Qt.callLater(initializeBackend)
    onInstanceIdChanged: {
        if (!root.initializing)
            Qt.callLater(initializeBackend)
    }

    Timer {
        interval: 1000
        repeat: true
        running: !root.weatherBackend
        onTriggered: root.initializeBackend()
    }

    Timer {
        id: searchTimeout
        interval: 20000
        repeat: false
        onTriggered: {
            root.finishSearch(root.requestId, [], qsTranslate("Weather", "搜索超时，请检查网络、VPN 或 API Host 后重试"))
        }
    }

    Timer {
        interval: 250
        repeat: true
        running: root.searching && !!root.weatherBackend
        onTriggered: {
            try {
                var state = root.weatherBackend.getLocationSearch(root.requestId)
                if (state && state.done)
                    root.finishSearch(root.requestId, state.results, state.error)
            } catch (error) {
                root.finishSearch(root.requestId, [], qsTranslate("Weather", "无法读取搜索结果，请重新加载天气插件后重试"))
            }
        }
    }

    Timer {
        interval: 1000
        repeat: true
        running: !!root.weatherBackend && !!root.instanceId
        triggeredOnStart: true
        onTriggered: {
            root.updateInstanceStatus()
        }
    }

    Connections {
        target: root.weatherBackend

        function onLanguageChanged() {
            searchTimeout.stop()
            root.searching = false
            root.searchResults = []
            root.searchMessage = ""
            root.actionMessage = ""
            root.actionKind = ""
            if (root.locationSelectionPending) {
                root.searchMessage = qsTranslate("Weather", "已选择：%1（点击确定后生效）").arg((root.settings || {}).custom_label || "")
                root.instanceStatus = ({"location": (root.settings || {}).custom_label || "",
                                        "updatedAt": qsTranslate("Weather", "保存后自动刷新")})
            } else {
                root.updateInstanceStatus()
            }
        }

        function onLocationSearchFinished(targetRequestId, results) {
            root.finishSearch(targetRequestId, results, "")
        }

        function onLocationSearchFailed(targetRequestId, message) {
            root.finishSearch(targetRequestId, [], message)
        }

        function onInstanceStatusChanged(targetInstanceId, status) {
            if (targetInstanceId !== root.instanceId || root.locationSelectionPending)
                return
            root.instanceStatus = status
            if (root.actionKind === "relocate") {
                root.actionMessage = qsTranslate("Weather", "位置检测完成：%1").arg(status.location || qsTranslate("Weather", "尚未定位"))
                root.actionKind = ""
            }
        }

        function onWeatherUpdated(targetInstanceId, data) {
            if (targetInstanceId !== root.instanceId || root.locationSelectionPending)
                return
            root.updateInstanceStatus()
            if (root.actionKind === "refresh") {
                root.actionMessage = qsTranslate("Weather", "天气刷新完成")
                root.actionKind = ""
            } else if (!root.actionKind && data && !data.stale) {
                root.actionMessage = data.warningAvailable === false ? qsTranslate("Weather", "预警数据暂不可用") : ""
            }
        }

        function onWeatherFailed(targetInstanceId, message, hasCachedData) {
            if (targetInstanceId !== root.instanceId || root.locationSelectionPending)
                return
            root.actionMessage = message
            root.actionKind = ""
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_location_20_regular"
        title: qsTranslate("Weather", "定位方式")
        description: qsTranslate("Weather", "自动定位使用公网 IP 推测位置；也可手动选择全球城市")

        ComboBox {
            id: locationMode
            model: [qsTranslate("Weather", "自动定位"), qsTranslate("Weather", "自定义地区")]
            onActivated: root.saveLocationMode(currentIndex === 1 ? "custom" : "auto")
        }
    }

    SettingCard {
        Layout.fillWidth: true
        visible: locationMode.currentIndex === 1
        icon.name: "ic_fluent_search_20_regular"
        title: qsTranslate("Weather", "搜索地区")
        description: (root.settings || {}).custom_label || qsTranslate("Weather", "输入全球城市或地区名称")

        RowLayout {
            TextField {
                id: locationQuery
                Layout.preferredWidth: 190
                placeholderText: qsTranslate("Weather", "例如：北京、London、東京")
                onAccepted: searchButton.clicked()
            }
            Button {
                id: searchButton
                text: root.searching ? qsTranslate("Weather", "重试") : qsTranslate("Weather", "搜索")
                enabled: root.weatherBackend && locationQuery.text.trim().length >= 2
                onClicked: root.searchLocations()
            }
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: locationMode.currentIndex === 1 && (root.searchMessage || root.searchResults.length)
        spacing: 4

        Label {
            text: root.searchMessage
            opacity: 0.7
            color: Colors.proxy.textSecondaryColor
        }

        Repeater {
            id: locationResults
            model: root.searchResults
            delegate: Button {
                required property var modelData
                Layout.fillWidth: true
                text: modelData.label
                onClicked: {
                    root.updateSettings({
                        "custom_name": modelData.name,
                        "custom_adm": modelData.adm,
                        "custom_label": modelData.label,
                        "custom_id": modelData.id || "",
                        "custom_country": modelData.country || ""
                    })
                    root.locationSelectionPending = true
                    root.searchMessage = qsTranslate("Weather", "已选择：%1（点击确定后生效）").arg(modelData.label)
                    root.searchResults = []
                    root.instanceStatus = ({
                        "location": modelData.label,
                        "updatedAt": qsTranslate("Weather", "保存后自动刷新")
                    })
                }
            }
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_timer_20_regular"
        title: qsTranslate("Weather", "刷新间隔")
        description: qsTranslate("Weather", "15–360 分钟，默认 30 分钟")

        SpinBox {
            id: refreshInterval
            from: 15
            to: 360
            stepSize: 15
            editable: true
            value: 30
            onValueChanged: {
                if (!root.initializing)
                    root.updateSettings({"refresh_minutes": value})
            }
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_weather_cloudy_20_regular"
        title: qsTranslate("Weather", "当前状态")
        description: qsTranslate("Weather", "地区：%1\n最近更新：%2").arg(root.instanceStatus.location || qsTranslate("Weather", "尚未定位"))
                     .arg(root.instanceStatus.updatedAt || qsTranslate("Weather", "尚未更新"))
                     + (root.actionMessage ? "\n" + root.actionMessage : "")

        RowLayout {
            Button {
                text: qsTranslate("Weather", "立即刷新")
                enabled: !!root.weatherBackend
                onClicked: root.runInstanceAction("refresh")
            }
            Button {
                text: qsTranslate("Weather", "重新检测位置")
                visible: locationMode.currentIndex === 0
                enabled: !!root.weatherBackend
                onClicked: root.runInstanceAction("relocate")
            }
        }
    }
}
