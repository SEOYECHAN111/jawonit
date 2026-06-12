# 자원잇다 v49 양식 기반 문서발급 엔진

이 버전은 OCR/AI로 문서를 매번 작성하는 구조가 아니라, 미리 만든 양식 템플릿에 구조화 데이터를 넣어 PDF/HTML 문서를 발급합니다.

## 핵심
- 견적서, 인보이스, 정산서, 수거확인서, 파기확인서, 데이터삭제 확인서, 자동차 부품 출처확인서, 엔진·미션 재생 위탁서, 노후차 회생 프로젝트 정산서, 아파트 캠페인 보고서, 수집품 위탁판매 확인서 지원
- `/document-center.html`에서 미리보기/발급/10장 발급/100장 샘플 발급 가능
- `/api/v49/documents/batch-issue`는 최대 100장 발급
- PDF 생성은 서버 내부 ReportLab 기반이므로 OCR/AI API 비용이 들지 않음
- 사진은 증빙자료이고, 법적/실무 문서 원본은 구조화 데이터 + 템플릿 PDF를 기준으로 함

## 주요 API
- GET `/api/v49/document-templates`
- POST `/api/v49/documents/preview`
- POST `/api/v49/documents/issue`
- POST `/api/v49/documents/batch-issue`
- POST `/api/v49/documents/sample-100`
- GET `/api/v49/documents`
- GET `/api/v49/documents/{id}/pdf`
- GET `/api/v49/documents/verify/{verify_code}`
