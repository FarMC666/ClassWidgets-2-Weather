import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

PluginPage {
    id: root

    property var pluginBackend: PluginBackendBridge.get_backend("com.farmc.classwidgets.weather")
    property string resultMessage: ""
    property bool resultSuccess: false

    function loadConfig() {
        if (!pluginBackend)
            return
        var config = pluginBackend.getWeatherConfig()
        apiHost.text = config.api_host || ""
        apiKey.text = config.api_key || ""
    }

    function saveCredentials(testAfterSave) {
        if (!pluginBackend) {
            resultSuccess = false
            resultMessage = "天气插件后端尚未就绪，请重新打开设置页"
            return
        }
        if (pluginBackend.saveWeatherCredentials(apiHost.text, apiKey.text) && testAfterSave)
            pluginBackend.testWeatherCredentials()
    }

    Component.onCompleted: Qt.callLater(loadConfig)

    Connections {
        target: root.pluginBackend

        function onCredentialsTested(success, message) {
            root.resultSuccess = success
            root.resultMessage = message
        }
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth

        ColumnLayout {
            width: parent.width
            spacing: 12

            Label {
                Layout.fillWidth: true
                text: "和风天气服务"
                font.pixelSize: 24
                font.weight: Font.DemiBold
                color: Colors.proxy.textColor
            }

            Label {
                Layout.fillWidth: true
                text: "请填写和风天气控制台分配的专属 API Host 与 API KEY。密钥仅保存在 ClassWidgets 本地配置中。"
                wrapMode: Text.Wrap
                opacity: 0.75
                color: Colors.proxy.textSecondaryColor
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_globe_20_regular"
                title: "API Host"
                description: "仅接受 HTTPS 的 *.qweatherapi.com 专属域名"

                TextField {
                    id: apiHost
                    Layout.preferredWidth: 300
                    placeholderText: "abc123.qweatherapi.com"
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_key_20_regular"
                title: "API KEY"
                description: "不会写入日志或发布包"

                TextField {
                    id: apiKey
                    Layout.preferredWidth: 300
                    placeholderText: "输入 API KEY"
                    echoMode: TextInput.Password
                    selectByMouse: true
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Button {
                    text: "保存"
                    enabled: apiHost.text.trim().length > 0 && apiKey.text.length > 0
                    onClicked: root.saveCredentials(false)
                }
                Button {
                    text: "保存并测试连接"
                    enabled: apiHost.text.trim().length > 0 && apiKey.text.length > 0
                    onClicked: root.saveCredentials(true)
                }
                Item { Layout.fillWidth: true }
            }

            Label {
                Layout.fillWidth: true
                visible: root.resultMessage.length > 0
                text: root.resultMessage
                color: root.resultSuccess ? "#14804A" : "#C42B1C"
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: "打开和风天气控制台"
                    onClicked: Qt.openUrlExternally("https://console.qweather.com/")
                }
                Button {
                    text: "查看申请与认证说明"
                    onClicked: Qt.openUrlExternally("https://dev.qweather.com/docs/configuration/authentication/")
                }
                Item { Layout.fillWidth: true }
            }

            Label {
                Layout.fillWidth: true
                text: "定位说明：自动定位使用 ipwho.is 返回的公网 IP 近似坐标；VPN、代理和运营商出口可能导致偏差。可在小组件设置中切换为自定义地区。"
                wrapMode: Text.Wrap
                opacity: 0.65
                color: Colors.proxy.textSecondaryColor
            }
        }
    }
}
