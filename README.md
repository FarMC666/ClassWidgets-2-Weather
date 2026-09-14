# ClassWidgets 2 天气插件

一个适用于 ClassWidgets 2 的天气小组件，使用和风天气 API v1 展示实时温度、天气现象、当天最高/最低温和有效天气预警。

## 功能

- 默认每 30 分钟刷新，可按小组件实例设置为 15–360 分钟。
- 使用 `ipwho.is` 在每次 ClassWidgets 启动时进行一次公网 IP 近似定位。
- 可通过和风天气 GeoAPI 搜索全球城市和地区，结果包含国家及行政区以区分同名城市；新选择保存 Location ID，重启或切换语言后仍解析同一地点。
- 小组件底栏仅显示最末级地区名称（例如“余杭区 · 杭州 · 浙江”显示“余杭区”），超长时单行省略；完整位置见设置页。QWeather 来源链接固定在右侧，组件栏隐藏时禁用点击。
- 界面支持简体中文、繁体中文、英文和日文，跟随 ClassWidgets 语言；其他界面语言回退英文。城市名称、天气现象和预警内容按宿主语言向 QWeather 请求。
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
- IP 定位可能受 VPN、代理或运营商出口影响，结果按城市显示，不承诺区县精度；设置页标明“IP 近似”。全球有效坐标均可用于定位；结果不准确时可改用自定义地区。GeoAPI 反向查询失败时仍保留 IP 服务的近似坐标和城市信息。
- 天气数据仅在内存中缓存到本次 ClassWidgets 会话结束。

## 全球覆盖与配置兼容

继续使用 QWeather `/geo/v2/city/lookup`、`/weather/v1/current`、`/weather/v1/daily` 和 `/weatheralert/v1/current`。GeoAPI 查询不设置 `range`，按[官方城市搜索文档](https://dev.qweather.com/en/docs/api/geoapi/city-lookup/)搜索全球城市；天气按经纬度请求，温度保持摄氏度，日预报仍使用目标地点的当地日期。界面中的更新时间、预警时间沿用设备本地时区。

[预警覆盖](https://dev.qweather.com/en/docs/api/warning/alert-coverage/)与全球天气覆盖不同，受国家、发布机构和服务权限影响。成功返回空列表或 `metadata.zeroResult` 表示没有返回预警数据，不能据此判断该地区一定有预警覆盖或没有灾害；插件不会显示“当地安全”等结论。预警请求失败或格式无效时，正常天气仍显示，并标记预警暂不可用；已有预警按原逻辑保留并标记待更新。非中文预警使用接口标题或事件名称，避免附加中文颜色和“预警”后缀。服务端文本可能按 QWeather 的[语言回退规则](https://dev.qweather.com/en/docs/resource/language/)返回当地语言或英文。

原有 `api_host`、`api_key`、`location_mode`、`custom_name`、`custom_adm`、`custom_label` 和 `refresh_minutes` 保持兼容，无需迁移配置。新选择仅增加可选的 `custom_id`、`custom_country`。旧配置仍按名称和行政区查询；如果全球查询存在无法唯一确定的同名结果，会提示重新选择，不会静默切换城市。

## 国际化实现

插件使用 Qt 翻译系统，自动跟随 ClassWidgets 的语言设置，无需单独配置语言。

翻译文件位于 `locales/`，QML 使用 `qsTranslate`，Python 使用 `QCoreApplication.translate`，上下文统一为 `Weather`。切换宿主语言会刷新注册标题、取消旧请求、清除旧语言缓存并重新请求地点与天气；不会为了更换语言再次检测已取得的公网 IP 坐标。繁体中文地区映射为 QWeather `zh-hant`，其他语言按官方支持代码映射，未支持的代码回退 `en`。

修改 `.ts` 后请重新生成并一同提交 `.qm`；SDK 打包会包含这些文件：

```powershell
pyside6-lrelease locales/zh_CN.ts locales/zh_HK.ts locales/en_US.ts locales/ja_JP.ts
```

## 开发与测试

需要 Python 3.9+、PySide6 与 ClassWidgets SDK `~=0.6.0`。纯数据解析测试不依赖 Qt：

```powershell
python -m unittest discover -s tests -v
```

安装 PySide6 和 RinUI 后，同一命令还会运行真实 QML 设置页回归测试，在只有 `WidgetsModel`、没有 `PluginBackendBridge` 的小组件窗口环境中覆盖状态读取、立即刷新、延迟绑定实例、搜索成功／失败／超时和未保存的地区选择；未安装时自动跳过该项。

交互回归测试会发送实际鼠标和触摸事件，检查预警详情及来源链接不会触发宿主隐藏，同时保留普通区域点击和右键菜单。

国际化与全球地区测试覆盖翻译完整性、占位符与编译目录一致性、三个真实 QML 页面的语言切换、插件注册与卸载、海外 IP、无效坐标、同名城市与 Location ID、旧配置、旧语言回调隔离、GeoAPI 错误码及预警空数据／请求失败。测试使用离线响应，不需要真实 API KEY。

打包：

```powershell
cw-plugin-pack .
```

## 发布

版本由维护者手动发布：

1. 使用 ClassWidgets SDK 生成 `.cwplugin` 和 `.zip` 安装包。
2. 在 [GitHub Releases](https://github.com/FarMC666/ClassWidgets-2-Weather/releases) 创建对应版本并上传安装包。
3. 在[插件广场控制台](https://plaza.cw.rinlit.cn/console)填写仓库及版本信息，提交审核。

```powershell
cw-plugin-pack .
cw-plugin-pack --format zip .
```

## 图标与署名

插件图标为项目自有图标。小组件中的天气状态图标来自 [QWeather Icons](https://github.com/qwd/Icons)，随插件本地打包并按主题文字颜色着色。图标仓库许可见 `assets/icons/LICENSE-QWEATHER-ICONS`；额外署名说明见 [NOTICE](NOTICE)。天气数据界面显示 `QWeather` 来源标注，组件栏展开时可点击访问；预警详情同时展示接口提供的来源信息。

## 许可证

插件代码版权归 FarMC 所有。第三方资源的版权及许可不因随插件分发而改变，详见 [NOTICE](NOTICE)。
