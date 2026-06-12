# 자원잇다 v51.08 v50base Windows-safe 안정화본

이 패키지는 사용자가 제공한 `jawonitda_final_fullstack_v50_20_checked_stable.zip` 기본구조를 바탕으로 다시 만든 실행 안정화본입니다.

## 핵심 수정
- v50.20 기본구조 유지
- Windows PowerShell `Expand-Archive` 오류 원인이 될 수 있는 깨진/모지바케 파일명 제거
- `main.py`, `requirements.txt`가 압축 해제 직후 루트에 보이도록 구성
- 예전 상단바/운영센터/모두·개인·기관·업체 잔상 방지
- 상단 메뉴를 박스형 버튼이 아니라 글씨형 링크로 고정
- 푸터 자원잇다 로고 확대 및 사업자 정보 고정
- `/admin-dashboard.html`, `/partner-dashboard.html`, `/company-dashboard.html`, `/my-requests.html` 주소 호환
- 데모 로그인 간소화: `admin / 1234`, `partner / 1234`, `company / 1234`, `personal / 1234`, `agency / 1234`

## 실행
```powershell
cd $env:USERPROFILE\Downloads
Expand-Archive -Path ".\jawonitda_final_fullstack_v51_07_v50base_windows_fixed.zip" -DestinationPath ".\jawonitda-v51-06-v50base" -Force
cd .\jawonitda-v51-06-v50base
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## 접속
- 홈: http://127.0.0.1:8000/
- 관리자: http://127.0.0.1:8000/admin-dashboard.html
- 업체센터: http://127.0.0.1:8000/partner-dashboard.html
- 기업센터: http://127.0.0.1:8000/company-dashboard.html
- 수거동선: http://127.0.0.1:8000/route.html

## Render
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Root Directory: 비워둠
