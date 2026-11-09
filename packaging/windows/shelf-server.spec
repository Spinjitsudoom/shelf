# PyInstaller recipe for Shelf Server on Windows. Run from the repository root:
#   pyinstaller --noconfirm packaging/windows/shelf-server.spec
# It makes dist/Shelf Server/ with two programs: "Shelf Server.exe" (the tray icon people
# start) and shelf-server.exe (the server it runs without a window). ffmpeg goes in
# dist/Shelf Server/ffmpeg/ separately (see the release workflow).
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = SPECPATH + "/../.."

server = Analysis(
    [ROOT + "/packaging/windows/server_entry.py"],
    pathex=[ROOT + "/src"],
    datas=collect_data_files("shelf"),  # the web app (shelf/web)
    hiddenimports=collect_submodules("shelf") + collect_submodules("uvicorn"),
    excludes=["tkinter", "essentia"],
)
tray = Analysis(
    [ROOT + "/packaging/windows/tray.py"],
    datas=[(ROOT + "/desktop/build/icon.png", ".")],
    hiddenimports=["pystray._win32"],
    excludes=["tkinter"],
)

server_exe = EXE(
    PYZ(server.pure), server.scripts, [], exclude_binaries=True,
    name="shelf-server", icon=ROOT + "/desktop/build/icon.ico", console=True,
)
tray_exe = EXE(
    PYZ(tray.pure), tray.scripts, [], exclude_binaries=True,
    name="Shelf Server", icon=ROOT + "/desktop/build/icon.ico", console=False,
)
COLLECT(
    server_exe, server.binaries, server.datas,
    tray_exe, tray.binaries, tray.datas,
    name="Shelf Server",
)
