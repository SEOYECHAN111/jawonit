$ErrorActionPreference = "Stop"
Write-Host "자원잇다 v51.12 실행 준비" -ForegroundColor Green
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
