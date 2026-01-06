# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Bay State Scraper sidecar binary

from pathlib import Path
import platform

block_cipher = None

# Determine output name based on platform
system = platform.system().lower()
if system == "darwin":
    target_triple = "aarch64-apple-darwin" if platform.machine() == "arm64" else "x86_64-apple-darwin"
elif system == "linux":
    target_triple = "x86_64-unknown-linux-gnu"
elif system == "windows":
    target_triple = "x86_64-pc-windows-msvc"
else:
    target_triple = "unknown"

a = Analysis(
    ["sidecar_bridge.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("scrapers/configs/*.yaml", "scrapers/configs"),
    ],
    hiddenimports=[
        "playwright",
        "playwright.sync_api",
        "playwright.async_api",
        "playwright_stealth",
        "httpx",
        "pyyaml",
        "yaml",
        "pydantic",
        "pydantic_settings",
        "rich",
        "structlog",
        "pandas",
        "openpyxl",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f"scraper-sidecar-{target_triple}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
