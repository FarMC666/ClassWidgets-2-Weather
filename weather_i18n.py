"""Qt catalogs and the public ClassWidgets locale configuration bridge.

The host uses QTranslator and sets QLocale's default. No plugin-specific
language setting is persisted: locale.language remains the source of truth.
"""

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QObject, QTranslator, Signal


def translate(source: str) -> str:
    return QCoreApplication.translate("Weather", source)


class WeatherTranslations(QObject):
    languageChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._translator = None
        self._configs = None
        self.language = ""

    def bind(self, configs) -> None:
        self._configs = configs
        if configs is not None:
            configs.configChanged.connect(self.sync)
        self.sync()

    def sync(self, *_args) -> None:
        language = str(self._configs.locale.language if self._configs is not None
                       else QLocale().name())
        if language == self.language:
            return
        from weather_core import qweather_language

        lang = qweather_language(language)
        catalog = {"zh": "zh_CN", "zh-hant": "zh_HK", "ja": "ja_JP"}.get(lang, "en_US")
        translator = QTranslator(self)
        path = Path(__file__).parent / "locales" / (catalog + ".qm")
        if not translator.load(str(path)):
            raise RuntimeError(f"Cannot load weather translations: {path}")
        app = QCoreApplication.instance()
        if app is not None:
            if self._translator is not None:
                app.removeTranslator(self._translator)
            app.installTranslator(translator)
        old = self._translator
        self._translator = translator
        if old is not None:
            old.deleteLater()
        self.language = language
        self.languageChanged.emit(language)

    def shutdown(self) -> None:
        if self._configs is not None:
            self._configs.configChanged.disconnect(self.sync)
            self._configs = None
        if self._translator is not None:
            app = QCoreApplication.instance()
            if app is not None:
                app.removeTranslator(self._translator)
            self._translator.deleteLater()
            self._translator = None
