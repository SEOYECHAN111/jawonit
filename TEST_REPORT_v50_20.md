# 자원잇다 v50.20 기능 검토 보고

## 검토 결과
- 총 125개 항목 자동 점검
- 성공: 125개
- 실패: 0개

## 검토 범위
1. 정적 페이지 50개 전부 200 OK
2. 로그인 5개 계정 확인
   - brans911 / brans911!
   - personal / personal123!
   - partner / partner123!
   - agency / agency123!
   - samsung / samsung123!
3. 핵심 공개 API
   - /api/health
   - /api/bootstrap
   - /api/notices
   - /api/projects
   - /api/disposal/items
   - /api/disposal/guide
   - /api/pickup/eligibility
   - /api/inquiries
4. 사진/파일 관련 API
   - /api/uploads
   - /api/vision/classify
   - /api/ocr/analyze
   - /api/v50/photo-first/analyze
5. 수거/판매/프로젝트 흐름
   - /api/pickup/submit
   - /api/recovery/sale-prompt
   - /api/recovery/quick-action
   - /api/projects/apply
6. 관리자 기능
   - 관리자 overview/users/inquiries/pickups/settlement/audit/api-status/api-config 등 확인
   - 공지 등록, 캠페인 등록, 가격 시뮬레이션, API 테스트 확인
7. 회생 모델 계열
   - v47, v48, v49, v50 API 기본 호출 확인

## 추가 안정화
- 새로고침 후 과거 상단바가 다시 보이는 문제를 CSS + JS MutationObserver로 이중 차단
- 최종 메뉴 고정
- 최종 푸터 고정
- 공지 페이지 데이터 정리
- 일부 과거 API 템플릿 ID, 필수값 누락 시 422/404가 뜨는 부분 보강

## 주의
- OCR/지도/결제/문자/OpenAI API는 실제 키가 없으면 safe-mock 모드로 동작합니다.
- 실제 창업·상용화 전 개인정보, 폐기물 운반, 자동차 부품/해체, 전자상거래 약관은 법무 검토가 필요합니다.
