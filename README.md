# ClassWidgets 2 天气插件

一个适用于 ClassWidgets 2 的天气小组件，使用和风天气 API v1 展示实时温度、天气现象、当天最高/最低温和有效天气预警。

## 功能

- 默认每 30 分钟刷新，可按小组件实例设置为 15–360 分钟。
- 使用 `ipwho.is` 在每次 ClassWidgets 启动时进行一次公网 IP 近似定位。
- 可通过和风天气 GeoAPI 搜索并保存中国区县；重启后会根据名称和上级行政区重新解析。
- 同一坐标的多个实例共享缓存并合并正在进行的请求。
- 有预警时以优先级最高的一条预警替换最高/最低温一行；点击可展开详情。
- 点击预警详情或 QWeather 来源链接不会触发小组件栏的轻触行为，其他区域仍遵循软件中的轻触设置。
- 网络失败时保留当前会话内最近一次成功数据，并标记为已过期。
- 迷你模式显示天气图标、温度和天气现象（有预警时显示预警名称）。

## 配置

1. 在[和风天气控制台](https://console.qweather.com/)创建项目，取得专属 API Host 和 API KEY。
2. 打开 ClassWidgets 的“天气”插件设置页，填写 Host 与 Key，选择“保存并测试连接”。
3. 添加“天气”小组件；在该实例的设置中选择自动定位或搜索自定义地区。

API Host 必须为控制台分配的 HTTPS `*.qweatherapi.com` 域名。API KEY 由 ClassWidgets 配置系统保存在本地，本插件不会把它写入日志；请勿将真实密钥加入源码或发布包。

## 数据、网络与隐私

- 天气、预报、预警和地区搜索来自 [QWeather / 和风天气](https://www.qweather.com/)。
- 自动定位会向 [ipwho.is](https://ipwho.is/) 发送常规 HTTPS 请求；该服务根据请求方公网 IP 返回近似位置。本插件不主动提交 API KEY、精确设备位置或其他身份信息给该服务。
- IP 定位可能受 VPN、代理或运营商出口影响，只按城市显示“IP 近似”结果，不承诺区县精度。检测到境外公网 IP 时自动定位会停止并提示关闭 VPN 或改用自定义地区，避免误显示境外城市天气。
- 天气数据仅在内存中缓存到本次 ClassWidgets 会话结束。

## 开发与测试

需要 Python 3.9+、PySide6 与 ClassWidgets SDK `~=0.6.0`。纯数据解析测试不依赖 Qt：

```powershell
python -m unittest discover -s tests -v
```

安装 PySide6 和 RinUI 后，同一命令还会运行真实 QML 设置页回归测试，在只有 `WidgetsModel`、没有 `PluginBackendBridge` 的小组件窗口环境中覆盖状态读取、立即刷新、延迟绑定实例、搜索成功／失败／超时和未保存的地区选择；未安装时自动跳过该项。

交互回归测试会发送实际鼠标和触摸事件，检查预警详情及来源链接不会触发宿主隐藏，同时保留普通区域点击和右键菜单。

打包：

```powershell
cw-plugin-pack .
```

## 发布

本项目没有直接套用 ClassWidgets 2 官方插件模板，版本由维护者手动发布：

1. 使用 ClassWidgets SDK 生成 `.cwplugin` 和 `.zip` 安装包。
2. 在 [GitHub Releases](https://github.com/FarMC666/ClassWidgets-2-Weather/releases) 创建对应版本并上传安装包。
3. 在[插件广场控制台](https://plaza.cw.rinlit.cn/console)填写仓库及版本信息，提交审核。

```powershell
cw-plugin-pack .
cw-plugin-pack --format zip .
```

## 图标与署名

插件图标为项目自有图标。小组件中的天气状态图标来自 [QWeather Icons](https://github.com/qwd/Icons)，随插件本地打包并按主题文字颜色着色。图标仓库许可见 `assets/icons/LICENSE-QWEATHER-ICONS`；额外署名说明见 [NOTICE](NOTICE)。天气数据界面始终显示可点击的 `QWeather` 来源标注，预警详情同时展示接口提供的来源信息。

## 许可证

插件代码版权归 FarMC 所有。第三方资源的版权及许可不因随插件分发而改变，详见 [NOTICE](NOTICE)。
