"""Janela desktop nativa do simulador (sem navegador, sem barra de URL).

    python desktop/main.py

Usa PyWebView (no Windows, o motor Edge WebView2 — Chromium, WebGL/GPU ligado) para abrir uma janela
nativa carregando `static/index.html`, que desenha o mapa com MapLibre GL. Toda a lógica de negócio
(raio, técnicos, CMU) continua em Python (`malha.assign`/`malha.costs`) — o JS só chama `api.simular(...)`
pela ponte do PyWebView a cada slider e repinta o mapa.
"""
import logging
import sys
from pathlib import Path

import webview

from api import Api

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

if getattr(sys, "frozen", False):
    _exe_root = Path(sys.executable).resolve().parent
    _resource_root = _exe_root / "_internal" if (_exe_root / "_internal").is_dir() else _exe_root
    STATIC = _resource_root / "desktop" / "static"
else:
    STATIC = Path(__file__).resolve().parent / "static"


def main():
    api = Api()
    webview.create_window(
        "Malha Logística SP (Ógea × PagResolve)",
        str(STATIC / "index.html"),
        js_api=api,
        width=1440, height=900, min_size=(1000, 640),
        background_color="#0b0e14",
    )
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
