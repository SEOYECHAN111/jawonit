from pathlib import Path
import sys, zipfile
root = Path(__file__).resolve().parents[1]
required = ['main.py','requirements.txt','render.yaml','static/index.html','static/js/app.js','static/css/styles.css','static/dashboards/admin.html','static/dashboards/partner.html']
missing = [p for p in required if not (root/p).exists()]
if missing:
    print('MISSING:', missing)
    sys.exit(1)
print('OK: required files exist')
