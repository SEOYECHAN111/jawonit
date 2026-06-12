# 자원잇다 v35 상세 배출 안내표 운영 설계

## 목적
개인 회원이 품목명을 입력하거나 사진을 촬영하면, 자원잇다가 1,000개 품목 기준표에서 가장 가까운 품목을 찾아 아래 정보를 즉시 표시한다.

- 배출 경로
- 6단계 이상 상세 배출 방법
- 포장 및 사진 촬영 기준
- 즉시수거 가능 기준
- 묶음수거/캠페인/관리자 검토 전환 기준
- 금지사항
- 법적·업무 확인사항
- 지역별 배출 기준 차이 안내

## 즉시수거 판정 기준
기본 판정 공식은 다음 기준 중 하나 이상을 충족하면 즉시수거 매칭 후보가 된다.

```text
무게 기준 충족 OR 예상가치 기준 충족 OR 수량 기준 충족 OR 대형품 포함
```

단, 위험·특수 품목, 개인정보 저장매체, 냉매/배터리 포함품, 사업장폐기물 의심품, 건설폐기물 가능 품목은 기준을 충족해도 관리자 검토를 우선한다.

## 데이터 필드
`static/data/disposal_items.json`은 각 품목별로 다음 필드를 가진다.

- id
- name
- category
- material
- recyclableStatus
- disposalChannel
- instantPickup
- minWeightKg
- minValueKrw
- countThreshold
- disposalType
- preparation
- disposalMethod
- steps
- do
- dont
- caution
- packaging
- photoGuide
- pickupRule
- feeNote
- legalNote
- adminCheck
- localDifference
- aiPhotoHints
- keywords

## 관리자 운영
관리자는 `/dashboards/admin.html#disposal`에서 품목 검색 후 기준표를 확인한다. API로는 `PATCH /api/admin/disposal/items/{item_id}`를 통해 품목별 문구와 기준값을 수정할 수 있다.

## API
- `GET /api/disposal/items?q=책상&category=가구·목재&limit=80`
- `POST /api/disposal/guide`
- `POST /api/pickup/submit`

## 실제 사업화 시 추가 연결
- 사진 AI 분류 API: 사진에서 품목명 추론
- OCR API: 공문/목록표에서 품목 자동 추출
- 지도 API: 지역별 배출 장소/수거 가능 지역 확인
- 문자/알림톡 API: 수거 접수·배차·완료 알림
- 결제 API: 유상처리·플랜 결제
