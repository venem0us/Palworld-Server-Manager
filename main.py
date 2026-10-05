import sys,traceback
from pathlib import Path
if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--self-test':
        directory=Path(sys.argv[2]);directory.mkdir(parents=True,exist_ok=True)
        (directory/'started.txt').write_text('Packaged self-test started')
        try:
            from palmanager.selftest import run
            code=run(sys.argv[2])
        except Exception:
            (directory/'error.txt').write_text(traceback.format_exc());code=1
        sys.exit(code)
    from palmanager.ui import launch
    sys.exit(launch())
