# 자원잇다 v51.12 구조오류 최종수정본

이 패키지는 v50.20 기본구조를 유지하면서 v51.10 API-ready 기능을 반영하고, v51.11 NOTICE 닫기 기능을 구조적으로 다시 안정화한 버전입니다.

## 주요 수정
- Windows PowerShell Expand-Archive 안전 ZIP 구조
- 최상위에 main.py / requirements.txt 바로 노출
- 정적 페이지/이미지/CSS/JS 요청이 많을 때 429가 500으로 터지던 구조 오류 수정
- 상단 NOTICE X 닫기 지속 저장(localStorage)
- 예전 상단바/운영센터/모두·개인·기관·업체 잔상 제거
- 홈/관리자/업체센터/기업센터/수거동선/고객센터/공지/정책 페이지 링크 점검
- 관리자, 업체, 수거동선, 문의, 공지, API-ready safe-mock 엔드포인트 점검

## 실행
```powershell
cd $env:USERPROFILE\Downloads
Remove-Item -Recurse -Force .\jawonitda-v51-12-final -ErrorAction SilentlyContinue
Expand-Archive -Path ".\jawonitda_final_fullstack_v51_12_structural_final.zip" -DestinationPath ".\jawonitda-v51-12-final" -Force
cd .\jawonitda-v51-12-final
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## 데모 계정
- 관리자: admin / 1234
- 수거업체: partner / 1234
- 기업회원: company / 1234
- 개인회원: personal / 1234
- 기관회원: agency / 1234
