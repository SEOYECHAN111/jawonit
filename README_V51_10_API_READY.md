# 자원잇다 v51.11 API-ready 안정화본

v50.20 기본구조를 유지하면서 버튼, 관리자, 푸터, 업체센터, 수거동선, 문의/공지, API 연결 대기 구조를 점검한 버전입니다.

## 실행
```powershell
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## 데모 계정
- admin / 1234
- partner / 1234
- company / 1234
- personal / 1234
- agency / 1234

## API 연결 준비
- `/api-readiness.html`
- `/api/integrations/status`
- `/api/model/diagnose`
- `/api/maps/geocode`
- `/api/payments/checkout`
- `/api/notifications/send`

실제 AI 모델, OCR, 지도, 결제, 문자 API 키를 Render Environment Variables에 등록하면 safe-mock에서 실제 연동 대기 상태로 전환됩니다.
