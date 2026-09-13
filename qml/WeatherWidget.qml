import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
import RinUI
import ClassWidgets.Theme

Widget {
    id: root

    property var snapshot: ({})
    property string errorMessage: ""
    property bool detailsExpanded: false
    readonly property var alertData: snapshot.alert || null
    readonly property bool hasAlert: alertData !== null && !!alertData.name
    readonly property string conditionCode: snapshot.conditionCode || "999"
    readonly property color primaryTextColor: Colors.proxy.textColor
    readonly property color secondaryTextColor: Colors.proxy.textSecondaryColor

    text: ""
    implicitWidth: miniMode ? 250 : 230
    height: miniMode ? 56 : (detailsExpanded && hasAlert ? 240 : 100)

    function subscribeNow() {
        if (backend && instanceId)
            backend.subscribe(instanceId, settings || {})
    }

    function readableTime(value) {
        if (!value)
            return qsTranslate("Weather", "未提供")
        var date = new Date(value)
        if (isNaN(date.getTime()))
            return value
        return Qt.formatDateTime(date, "yyyy-MM-dd HH:mm")
    }

    function sourceText() {
        var parts = []
        if (alertData && alertData.senderName)
            parts.push(alertData.senderName)
        if (alertData && alertData.sources)
            parts = parts.concat(alertData.sources)
        return parts.length ? parts.join(" · ") : "QWeather"
    }

    function summaryText() {
        if (hasAlert)
            return alertData.name
        if (snapshot.temperatureMax !== undefined)
            return qsTranslate("Weather", "最高 %1°  最低 %2°").arg(snapshot.temperatureMax).arg(snapshot.temperatureMin)
        return errorMessage || qsTranslate("Weather", "正在获取天气…")
    }

    Component.onCompleted: subscribeNow()
    Component.onDestruction: {
        if (backend && instanceId)
            backend.unsubscribe(instanceId)
    }
    onSettingsChanged: subscribeNow()
    onInstanceIdChanged: subscribeNow()
    onMiniModeChanged: {
        if (miniMode)
            detailsExpanded = false
    }

    Connections {
        target: root.backend

        function onWeatherUpdated(targetInstanceId, data) {
            if (targetInstanceId !== root.instanceId)
                return
            root.snapshot = data || {}
            root.errorMessage = data && data.warningAvailable === false
                              ? qsTranslate("Weather", "预警数据暂不可用") : ""
            if (!root.hasAlert)
                root.detailsExpanded = false
        }

        function onWeatherFailed(targetInstanceId, message, hasCachedData) {
            if (targetInstanceId !== root.instanceId)
                return
            root.errorMessage = message
            if (!hasCachedData)
                root.snapshot = ({})
        }
    }

    Item {
        anchors.fill: parent

        RowLayout {
            anchors.fill: parent
            visible: root.miniMode
            spacing: 8

            Item {
                Layout.preferredWidth: 30
                Layout.preferredHeight: 30

                Image {
                    id: miniIconSource
                    anchors.fill: parent
                    source: Qt.resolvedUrl("../assets/icons/" + root.conditionCode + ".svg")
                    sourceSize: Qt.size(width, height)
                    fillMode: Image.PreserveAspectFit
                    visible: false
                }
                ColorOverlay {
                    anchors.fill: miniIconSource
                    source: miniIconSource
                    color: root.primaryTextColor
                }
            }

            Title {
                text: root.snapshot.temperature !== undefined
                      ? root.snapshot.temperature + "°" : "--°"
                px: 25
                color: root.primaryTextColor
            }

            Text {
                Layout.fillWidth: true
                text: root.hasAlert ? root.alertData.name
                                    : (root.snapshot.conditionText || root.errorMessage || qsTranslate("Weather", "加载中…"))
                color: root.primaryTextColor
                font.pixelSize: 16
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            Text {
                objectName: "miniWeatherAttribution"
                text: "QWeather"
                color: root.secondaryTextColor
                font.pixelSize: 9
                opacity: 0.85
                TapHandler {
                    gesturePolicy: TapHandler.WithinBounds
                    onTapped: Qt.openUrlExternally("https://www.qweather.com/")
                }
            }
        }

        ColumnLayout {
            anchors.fill: parent
            visible: !root.miniMode
            spacing: 1

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Item {
                    Layout.preferredWidth: 36
                    Layout.preferredHeight: 26

                    Image {
                        id: normalIconSource
                        anchors.fill: parent
                        source: Qt.resolvedUrl("../assets/icons/" + root.conditionCode + ".svg")
                        sourceSize: Qt.size(width, height)
                        fillMode: Image.PreserveAspectFit
                        visible: false
                    }
                    ColorOverlay {
                        anchors.fill: normalIconSource
                        source: normalIconSource
                        color: root.primaryTextColor
                    }
                }

                Title {
                    text: root.snapshot.temperature !== undefined
                          ? root.snapshot.temperature + "°" : "--°"
                    px: 25
                    color: root.primaryTextColor
                }

                Text {
                    Layout.fillWidth: true
                    text: root.snapshot.conditionText || root.errorMessage || qsTranslate("Weather", "正在获取天气…")
                    color: root.primaryTextColor
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }

                Text {
                    visible: !!root.snapshot.stale || root.snapshot.warningAvailable === false
                    text: root.snapshot.stale ? qsTranslate("Weather", "已过期") : qsTranslate("Weather", "预警待更新")
                    color: root.secondaryTextColor
                    font.pixelSize: 9
                }
            }

            Item {
                objectName: "weatherAlertToggle"
                Layout.fillWidth: true
                Layout.preferredHeight: 18

                Text {
                    anchors.fill: parent
                    visible: !root.hasAlert
                    text: root.summaryText()
                    color: root.secondaryTextColor
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                Text {
                    anchors.fill: parent
                    visible: root.hasAlert
                    text: (root.alertData ? root.alertData.name : "")
                          + (root.detailsExpanded ? qsTranslate("Weather", "  收起详情") : qsTranslate("Weather", "  查看详情 ›"))
                    color: root.primaryTextColor
                    font.pixelSize: 13
                    font.weight: Font.Bold
                    elide: Text.ElideRight
                }

                TapHandler {
                    enabled: root.hasAlert
                    // Take the press exclusively so the host's passive tap
                    // handler does not also hide the widget bar.
                    gesturePolicy: TapHandler.WithinBounds
                    onTapped: root.detailsExpanded = !root.detailsExpanded
                }
            }

            ScrollView {
                id: detailsView
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.detailsExpanded && root.hasAlert
                clip: true
                contentWidth: availableWidth
                ScrollBar.vertical.policy: ScrollBar.AlwaysOff
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    width: detailsView.availableWidth
                    spacing: 6

                    Text {
                        Layout.fillWidth: true
                        text: root.alertData ? root.alertData.headline : ""
                        color: root.primaryTextColor
                        font.pixelSize: 14
                        font.weight: Font.Bold
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.alertData ? root.alertData.description : ""
                        color: root.primaryTextColor
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: root.alertData && !!root.alertData.instruction
                        text: qsTranslate("Weather", "防御指南：%1").arg(root.alertData ? root.alertData.instruction : "")
                        color: root.primaryTextColor
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: qsTranslate("Weather", "发布时间：%1").arg(root.readableTime(root.alertData ? root.alertData.issuedTime : ""))
                        color: root.secondaryTextColor
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: qsTranslate("Weather", "有效期：%1 至 %2").arg(root.readableTime(root.alertData ? root.alertData.effectiveTime : ""))
                              .arg(root.readableTime(root.alertData ? root.alertData.expireTime : ""))
                        color: root.secondaryTextColor
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: qsTranslate("Weather", "来源：%1").arg(root.sourceText())
                        color: root.secondaryTextColor
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: root.snapshot.location || ""
                    color: root.secondaryTextColor
                    font.pixelSize: 9
                    elide: Text.ElideRight
                }
                Text {
                    objectName: "weatherAttribution"
                    text: "QWeather"
                    color: root.secondaryTextColor
                    font.pixelSize: 9
                    font.underline: qweatherHover.hovered
                    HoverHandler { id: qweatherHover }
                    TapHandler {
                        gesturePolicy: TapHandler.WithinBounds
                        onTapped: Qt.openUrlExternally("https://www.qweather.com/")
                    }
                }
            }
        }
    }
}
