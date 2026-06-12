# 자원잇다 v35 Detailed Disposal Guide

이 버전은 v34 Business Operable을 기반으로 배출 안내표 1,000개 항목을 상세화했습니다.

- 품목별 6단계 이상 배출 방법
- 배출 경로 / 포장법 / 사진 촬영 기준
- 즉시수거·묶음수거·관리자 검토 전환 기준
- 위험품·저장매체·사업장폐기물 확인 항목
- 관리자 품목 기준 수정 API

기존 Render 배포 방식은 동일합니다.

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port $PORT
```

# v34 검증 보고서

## 검사 항목

- Python 문법 검사: `python -m py_compile main.py`
- JavaScript 문법 검사: `node --check static/js/app.js`
- FastAPI 주요 API 스모크 테스트
- 배출 안내표 1,000개 데이터 존재 확인
- 보호자료 1~98번 PDF 세트 존재 확인
- 내부 HTML 링크 및 이미지 경로 확인
- ZIP 무결성 검사

## 확인된 핵심 API

- `POST /api/auth/login`
- `POST /api/auth/signup`
- `PATCH /api/me`
- `POST /api/pickup/submit`
- `POST /api/disposal/guide`
- `GET /api/disposal/items`
- `GET /api/bidrooms`
- `POST /api/bidrooms`
- `GET /api/admin/review-queue`
- `GET /api/admin/pickups`
- `PATCH /api/admin/pickups/{pickup_id}`
- `GET /api/admin/settlement/summary`
- `GET /api/admin/export/operations`
- `GET /api/protected/forms`
- `GET /api/protected/forms/{form_id}`

## 운영 전 남는 실제 외부 계약 항목

- PG 계약 및 웹훅 검증
- OpenAI/OCR/지도/문자/사업자검증 API 키 발급
- 실제 DB(Postgres) 연결
- 보호파일 저장소 연결
- 법무 검토 및 사업자 정보 확정
