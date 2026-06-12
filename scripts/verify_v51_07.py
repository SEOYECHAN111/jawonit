from pathlib import Path
import sys, zipfile, subprocess
base=Path(__file__).resolve().parents[1]
need=['main.py','requirements.txt','static/js/app.js','static/css/styles.css','static/admin-dashboard.html']
missing=[x for x in need if not (base/x).exists()]
if missing:
    print('MISSING',missing); sys.exit(1)
subprocess.run([sys.executable,'-m','py_compile',str(base/'main.py')],check=True)
print('v51.08 package structure OK')
