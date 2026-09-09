"""Arma la ventana de la app: crea la API y abre ui/index.html con PyWebView."""
from __future__ import annotations

import webview

from akx.api import API
from akx.constants import APP_NAME
from akx.paths import UI_INDEX


def main():
    api = API()
    webview.create_window(
        APP_NAME,
        url=str(UI_INDEX),
        js_api=api,
        width=1240,
        height=820,
        min_size=(1020, 660),
        background_color="#0A0A0A",
    )
    webview.start(debug=False)
