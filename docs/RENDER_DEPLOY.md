# Render Web Service 배포

## 1. GitHub 업로드
저장소는 반드시 Private으로 만들고 `main.py`, `requirements.txt`, `static`, `protected`가 보이게 업로드합니다.

## 2. Render 설정
- New → Web Service
- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## 3. Environment Variables
`.env.example`의 값을 Render Environment Variables에 입력합니다.

최소 권장:
```
PYTHON_VERSION=3.11.9
SECRET_KEY=긴랜덤문자열
PUBLIC_BASE_URL=https://서비스주소.onrender.com
```

API 실제 연결 시 추가:
```
OPENAI_API_KEY=...
KAKAO_REST_API_KEY=...
TOSS_SECRET_KEY=...
```

## 4. 배포 후 테스트
```
/api/health
/api/admin/api-status?token=demo-admin
/login.html
```
