# 자원잇다 v51.08 final audit fixed

실행:
```powershell
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

확인:
- http://127.0.0.1:8000/
- http://127.0.0.1:8000/admin-dashboard.html
- http://127.0.0.1:8000/partner-dashboard.html
- http://127.0.0.1:8000/route.html

계정:
- admin / 1234
- partner / 1234
- company / 1234
- personal / 1234
