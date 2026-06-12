# API 연결 가이드

모든 API 키는 `.env` 또는 Render Environment Variables에만 입력합니다. 프론트엔드 HTML/JS에는 키를 넣지 않습니다.

## OpenAI
- 환경변수: `OPENAI_API_KEY`, `OPENAI_MODEL`
- 사용 위치: `/api/intake/auto-fill`
- 용도: 기관·기업 서류 초안 자동작성
- 원칙: 공식 제출본이 아니라 담당자 검토용 초안

## OCR / Vision
- 환경변수: `OCR_API_KEY`, `OCR_API_URL`, `VISION_API_KEY`
- 사용 위치: `/api/ocr/analyze`, `/api/vision/classify`
- 용도: 공문/목록표/사진에서 품목·수량·주소 후보 추출

## 지도 / 노선
- 환경변수: `KAKAO_REST_API_KEY`, `KAKAO_MAP_JS_KEY`, `NAVER_MAP_CLIENT_ID`, `ROUTE_API_URL`
- 사용 위치: `/api/route/optimize`
- 용도: 주소 좌표화, 업체 위치, 최단거리/수익성/시간창 노선 계산

## 결제
- 환경변수: `TOSS_CLIENT_KEY`, `TOSS_SECRET_KEY`, `PORTONE_API_KEY`
- 사용 위치: `/api/payments/prepare`
- 운영 시 필요한 것: 결제 승인 검증, 웹훅 서명 검증, 환불 API 연동

## 파일 저장소
- 환경변수: `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- 기본 구조: 로컬 `storage/uploads`
- 운영 권장: S3 호환 비공개 버킷 + 서명 URL
