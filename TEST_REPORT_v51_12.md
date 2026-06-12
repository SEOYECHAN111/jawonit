# TEST REPORT v51.12

## 패키지 검사
- ZIP 무결성 검사: 정상
- ZIP 압축 해제 테스트: 정상
- Windows unsafe 파일명: 0개
- __pycache__ / .pyc / 임시 DB 제거: 완료

## 문법 검사
- main.py py_compile: 정상
- static/js/app.js node --check: 정상

## 서버 실행 검사
- uvicorn main:app 실행: 정상
- /api/health: 200 OK

## 페이지 검사
- static HTML 전체 56개: 200 OK
- 내부 CSS/JS/이미지/정책/HTML 참조 60개: 200 OK
- /, /index.html, /admin-dashboard.html, /partner-dashboard.html, /company-dashboard.html, /my-requests.html, /api-readiness.html, /docs.html, /docs: 정상

## 계정 검사
- admin / 1234: 정상
- partner / 1234: 정상
- company / 1234: 정상
- personal / 1234: 정상
- agency / 1234: 정상

## API 검사
- 관리자 API: 정상
- 업체센터 API: 정상
- 수거동선 API: 정상
- 고객센터 문의 API: 정상
- 공지 저장 API: 정상
- 배출안내 API: 정상
- 사진 업로드 분석 API: 정상
- API-ready safe-mock 엔드포인트: 정상
- v47/v48/v50 호환 API 일부: 정상

## 구조 오류 수정
- 기존 미들웨어에서 많은 정적 요청이 발생하면 HTTPException(429)이 500으로 노출되던 문제 수정
- 정적/페이지 GET 요청은 rate bucket에서 제외
- rate limit 초과 시 JSONResponse 429로 정상 반환
- NOTICE 닫기 상태를 localStorage에 저장하고 새로고침 후 유지
