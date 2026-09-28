# -*- mode: python ; coding: utf-8 -*-

import os

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('C:/Users/Yae_S/AppData/Roaming/kimi-desktop/daimon-bundle/runtime/python/cpython-3.12/DLLs/libssl-3-x64.dll', '.'), ('C:/Users/Yae_S/AppData/Roaming/kimi-desktop/daimon-bundle/runtime/python/cpython-3.12/DLLs/libcrypto-3-x64.dll', '.')],
    datas=[('src/net/sakurain/influxdbstudio/resources', 'net/sakurain/influxdbstudio/resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt modules this app never imports (app only uses QtCore/QtGui/QtWidgets)
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
        'PySide6.QtNetwork', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'PySide6.QtSvg', 'PySide6.QtSvgWidgets', 'PySide6.QtPdf',
        'PySide6.QtPdfWidgets', 'PySide6.QtVirtualKeyboard', 'PySide6.QtDBus',
        'PySide6.QtPrintSupport', 'PySide6.QtSql', 'PySide6.QtTest',
        'PySide6.QtConcurrent', 'PySide6.QtHelp', 'PySide6.QtUiTools',
        'PySide6.QtWebChannel', 'PySide6.QtWebSockets', 'PySide6.QtXml',
        'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
        'PySide6.QtLocation', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtNfc', 'PySide6.QtPositioning', 'PySide6.QtBluetooth',
        'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSensors',
        'PySide6.QtSerialPort', 'PySide6.QtSerialBus', 'PySide6.QtSpatialAudio',
        'PySide6.QtStateMachine', 'PySide6.QtTextToSpeech', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebView',
        'PySide6.QtQuick3D', 'PySide6.QtQuickControls2', 'PySide6.QtQuickEffects',
        'PySide6.QtQuickTest', 'PySide6.QtQuickTimeline', 'PySide6.QtLabsPlatform',
        'PySide6.QtShaderTools', 'PySide6.QtHttpServer', 'PySide6.QtDesigner',
    ],
    noarchive=False,
    optimize=0,
)

# Drop binaries/plugins/translations the trimmed Qt set does not need.
_DROP_SUBSTRINGS = [
    'opengl32sw.dll', 'libEGL.dll', 'libGLESv2.dll', 'd3dcompiler',
    'Qt6Qml', 'Qt6Quick', 'Qt6Pdf', 'Qt6OpenGL', 'Qt6VirtualKeyboard',
    'Qt6Network', 'Qt6Svg', 'Qt6DBus', 'Qt6ShaderTools', 'Qt6Multimedia',
    'Qt63D', 'Qt6Charts', 'Qt6Graphs', 'Qt6WebEngine', 'Qt6Location',
    'Qt6Positioning', 'Qt6Sensors', 'Qt6Serial', 'Qt6Scxml', 'Qt6Sql',
    'Qt6Test', 'Qt6Help', 'Qt6Designer', 'Qt6UiTools', 'Qt6Concurrent',
    'Qt6RemoteObjects', 'Qt6StateMachine', 'Qt6TextToSpeech', 'Qt6Bluetooth',
    'Qt6Nfc', 'Qt6SpatialAudio', 'Qt6HttpServer', 'Qt6Labs',
    'qdirect2d.dll',
]
# Qt translation files: keep only Chinese (app default language).
_KEEP_QM = ('qtbase_zh_CN', 'qt_zh_CN')


def _keep_binary(dest):
    d = dest.replace('/', os.sep).replace('\\', '/')
    if any(s in d for s in _DROP_SUBSTRINGS):
        return False
    if '/plugins/imageformats/' in d:
        return False  # icons are PNG/ICO (built into QtGui)
    if '/plugins/tls/' in d:
        return False  # no QtNetwork in the trimmed build
    if '/plugins/sqldrivers/' in d or '/plugins/mediaservice/' in d:
        return False
    return True


def _keep_data(dest):
    d = dest.replace('/', os.sep).replace('\\', '/')
    if '/translations/' in d:
        base = os.path.basename(d)
        return any(base.startswith(k) for k in _KEEP_QM)
    return True


a.binaries = [b for b in a.binaries if _keep_binary(b[1])]
a.datas = [d for d in a.datas if _keep_data(d[1])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='InfluxDBManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='installer/version.txt',
    icon=['sakurain.ico'],
)
