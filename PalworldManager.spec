# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
root = Path(SPECPATH)
a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(path),'palmanager') for path in (root/'palmanager').glob('*.py')]+collect_data_files('tzdata'),
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=0,
)
# Qt links against Windows' native ICU ABI. Do not bundle a same-named ICU
# from unrelated tools on PATH (for example Poppler), whose exports differ.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='PalworldManager',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
