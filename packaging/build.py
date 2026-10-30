"""Gera o executável `ativos` (ou `ativos.exe`) em dist/ com o PyInstaller.

Uso: uv run --with pyinstaller python packaging/build.py
O executável só roda no sistema em que foi gerado (Linux gera Linux, Windows gera .exe).
"""

from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent

PyInstaller.__main__.run(
    [
        str(ROOT / "packaging" / "entry.py"),
        "--name=ativos",
        "--onefile",
        "--console",
        "--noconfirm",
        "--clean",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build'}",
        f"--specpath={ROOT / 'build'}",
        # O Scrapy carrega middlewares, extensões e o reactor do Twisted por nome,
        # então o PyInstaller não os enxerga sozinho.
        "--collect-all=scrapy",
        "--collect-submodules=twisted",
        "--collect-submodules=ativos_cli",
        "--collect-data=tldextract",
        # O Scrapy lê a versão das dependências pelos metadados dos pacotes.
        "--recursive-copy-metadata=scrapy",
    ]
)
