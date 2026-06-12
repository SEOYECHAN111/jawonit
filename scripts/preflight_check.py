from pathlib import Path
import py_compile, zipfile, sys
root = Path(__file__).resolve().parents[1]
required = ['main.py','requirements.txt','render.yaml','static/js/app.js','static/css/styles.css','static/index.html']
missing = [p for p in required if not (root/p).exists()]
if missing:
    raise SystemExit('MISSING: ' + ', '.join(missing))
py_compile.compile(str(root/'main.py'), doraise=True)
print('OK: main.py / requirements.txt / static files exist and main.py compiles')
print('Next: python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000')
