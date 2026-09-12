"""ClassWidgets 2 weather plugin entry point."""

from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot
from pydantic import Field

from ClassWidgets.SDK import CW2Plugin, ConfigBaseModel, PluginAPI

from weather_backend import WeatherBackend


class WeatherConfig(ConfigBaseModel):
    api_host: str = ""
    api_key: str = Field(default="", repr=False)


class Plugin(CW2Plugin):
    credentialsTested = Signal(bool, str)
    weatherUpdated = Signal(str, dict)
    weatherFailed = Signal(str, str, bool)
    locationSearchFinished = Signal(str, list)
    locationSearchFailed = Signal(str, str)
    instanceStatusChanged = Signal(str, dict)

    def __init__(self, api: PluginAPI):
        super().__init__(api)
        self.config = WeatherConfig()
        self.backend = WeatherBackend(self)
        self.backend.credentialsTested.connect(self.credentialsTested.emit)
        self.backend.weatherUpdated.connect(self.weatherUpdated.emit)
        self.backend.weatherFailed.connect(self.weatherFailed.emit)
        self.backend.locationSearchFinished.connect(self.locationSearchFinished.emit)
        self.backend.locationSearchFailed.connect(self.locationSearchFailed.emit)
        self.backend.instanceStatusChanged.connect(self.instanceStatusChanged.emit)

    @Property(QObject, constant=True)
    def weatherBackend(self) -> QObject:
        return self.backend

    @Slot(result=dict)
    def getWeatherConfig(self) -> dict:
        return self.backend.globalConfig

    @Slot(str, str, result=bool)
    def saveWeatherCredentials(self, api_host: str, api_key: str) -> bool:
        return self.backend.saveCredentials(api_host, api_key)

    @Slot()
    def testWeatherCredentials(self) -> None:
        self.backend.testCredentials()

    @Slot(str, str)
    def searchWeatherLocations(self, request_id: str, query: str) -> None:
        self.backend.searchLocations(request_id, query)

    @Slot(str, result=dict)
    def getWeatherLocationSearch(self, request_id: str) -> dict:
        return self.backend.getLocationSearch(request_id)

    @Slot(str, result=dict)
    def getWeatherInstanceStatus(self, instance_id: str) -> dict:
        return self.backend.getInstanceStatus(instance_id)

    @Slot(str, dict)
    def subscribeWeatherInstance(self, instance_id: str, settings: dict) -> None:
        self.backend.subscribe(instance_id, settings)

    @Slot(str)
    def refreshWeather(self, instance_id: str) -> None:
        self.backend.refresh(instance_id)

    @Slot(str)
    def relocateWeather(self, instance_id: str) -> None:
        self.backend.relocate(instance_id)

    def on_load(self):
        super().on_load()
        if not self.pid:
            return
        self.api.config.register_plugin_model(self.pid, self.config)
        self.backend.bind_config(self.config, self.api.config.save)
        self.backend.set_icon_directory(Path(self.PATH) / "assets" / "icons")
        self.api.widgets.register(
            widget_id="com.farmc.classwidgets.weather.widget",
            name="天气",
            qml_path="qml/WeatherWidget.qml",
            backend_obj=self.backend,
            settings_qml="qml/WeatherWidgetSettings.qml",
            default_settings={
                "location_mode": "auto",
                "custom_name": "",
                "custom_adm": "",
                "custom_label": "",
                "refresh_minutes": 30,
            },
        )
        self.api.ui.register_settings_page(
            qml_path="qml/PluginSettings.qml",
            title="天气",
            icon="ic_fluent_weather_sunny_20_regular",
        )

    def on_unload(self):
        self.backend.shutdown()
        try:
            self.api.ui.unregister_settings_page("qml/PluginSettings.qml")
        except Exception:
            pass
        super().on_unload()
