# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 설정.

실행: just package
(직접 실행 시: uv run pyinstaller build/nhfutures.spec --distpath desktop/dist --workpath desktop/build --noconfirm)
"""
import os
import tomllib

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

# SPECPATH는 PyInstaller가 주입하는 이 파일의 디렉터리 경로입니다.
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

# 실행 파일 아이콘. 없으면 PyInstaller 기본 아이콘을 사용합니다.
_icon_path = os.path.join(SPECPATH, "nh-api.ico")
ICON = _icon_path if os.path.exists(_icon_path) else None

# 실행 파일의 버전 정보. Windows 는 알림과 작업 관리자에 앱 이름으로
# 「파일 설명」을 보이고, 비어 있으면 파일 이름(「NH FUTURES API.exe」)을 보입니다.
APP_NAME = "NH FUTURES API"
with open(os.path.join(ROOT, "pyproject.toml"), "rb") as _f:
    _version = tomllib.load(_f)["project"]["version"]
_numbers = tuple((list(map(int, _version.split(".")[:4])) + [0, 0, 0, 0])[:4])
VERSION = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_numbers, prodvers=_numbers),
    kids=[
        StringFileInfo([
            StringTable("041204B0", [
                StringStruct("FileDescription", APP_NAME),
                StringStruct("ProductName", APP_NAME),
                StringStruct("InternalName", APP_NAME),
                StringStruct("OriginalFilename", APP_NAME + ".exe"),
                StringStruct("FileVersion", _version),
                StringStruct("ProductVersion", _version),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [0x0412, 1200])]),
    ],
)

a = Analysis(
    [os.path.join(ROOT, "desktop", "main.py")],
    pathex=[ROOT],
    binaries=[],
    # 프론트엔드 빌드 산출물을 번들에 포함합니다. (just build 가 먼저 실행되어야 합니다)
    datas=[(os.path.join(ROOT, "backend", "static"), os.path.join("backend", "static"))]
    # 알림 영역 아이콘이 실행 중에 읽는 파일입니다(desktop/notify.py).
    + ([(ICON, "build")] if ICON else []),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NH FUTURES API",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 콘솔 창 없이 실행합니다.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
    version=VERSION,
)
