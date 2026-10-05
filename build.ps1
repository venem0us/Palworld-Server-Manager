$ErrorActionPreference = 'Stop'
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller==6.22.2
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean PalworldManager.spec
