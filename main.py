from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shutil
import time
import html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
BASE = Path(__file__).parent
STATIC = BASE / 'static'
PROTECTED = BASE / 'protected' / 'forms'
STORAGE = BASE / 'storage'
UPLOADS = STORAGE / 'uploads'
DB_PATH = STORAGE / 'db.json'
AUDIT_LOG = STORAGE / 'audit.log'
API_VAULT_PATH = STORAGE / 'api_keys.json'
for p in (STORAGE, UPLOADS, PROTECTED):
    p.mkdir(parents=True, exist_ok=True)

APP_VERSION = '51.12.0'
APP_NAME = os.getenv('APP_NAME', '자원잇다')
APP_ENV = os.getenv('APP_ENV', 'production')
SECRET_KEY = os.getenv('SECRET_KEY', 'CHANGE_ME_BEFORE_LAUNCH')
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '20'))
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.pdf', '.doc', '.docx', '.hwp', '.hwpx', '.xls', '.xlsx', '.csv', '.txt', '.zip'}

PLAN_RANK = {
    'Free': 0,
    'Basic': 1,
    'Standard': 2,
    'Plus': 3,
    'Gold': 4,
    'Pro': 4,
    'ESG Plus': 4,
    'Enterprise': 5,
    'Admin': 99,
}
ROLE_LABEL = {
    'personal': '개인',
    'partner': '업체',
    'agency': '기관',
    'enterprise': '기업',
    'admin': '관리자',
}
API_MAP = {
    'OpenAI GPT 문서작성': 'OPENAI_API_KEY',
    'OpenAI 모델명': 'OPENAI_MODEL',
    'OCR 문서분석': 'OCR_API_KEY',
    'OCR API URL': 'OCR_API_URL',
    '이미지 분류 API': 'VISION_API_KEY',
    'Kakao 지도 REST': 'KAKAO_REST_API_KEY',
    'Kakao JS 지도': 'KAKAO_MAP_JS_KEY',
    'Naver 지도 Client': 'NAVER_MAP_CLIENT_ID',
    '외부 최적노선 API': 'ROUTE_API_URL',
    'Toss Secret': 'TOSS_SECRET_KEY',
    'PortOne API': 'PORTONE_API_KEY',
    '문자/알림톡': 'SOLAPI_API_KEY',
    '사업자 검증': 'BIZNO_API_KEY',
    'S3 Bucket': 'S3_BUCKET',
    'AWS Access Key': 'AWS_ACCESS_KEY_ID',
}


def load_api_vault() -> Dict[str, str]:
    if not API_VAULT_PATH.exists():
        return {}
    try:
        data = json.loads(API_VAULT_PATH.read_text(encoding='utf-8'))
        return {str(k): str(v) for k, v in data.items() if v}
    except Exception:
        return {}

def save_api_vault(data: Dict[str, str]) -> None:
    API_VAULT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def allowed_api_envs() -> set[str]:
    return set(API_MAP.values()) | {'OPENAI_MODEL'}

def get_config_value(env: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(env)
    if value:
        return value
    return load_api_vault().get(env) or default

def mask_secret(value: Optional[str]) -> str:
    if not value:
        return ''
    if len(value) <= 8:
        return '•' * len(value)
    return value[:4] + '•' * max(4, len(value)-8) + value[-4:]

FORM_ACCESS = {
    'pre': {'file': '01_pre_onbid_forms.pdf', 'roles': ['agency', 'admin'], 'min_plan': 'Basic', 'title': '온비드 공고 전 사전생성 서류'},
    'attach': {'file': '02_onbid_attachments.pdf', 'roles': ['agency', 'admin'], 'min_plan': 'Basic', 'title': '온비드 공고 첨부용 서류'},
    'joint': {'file': '03_joint_proxy_bid.pdf', 'roles': ['partner', 'admin'], 'min_plan': 'Standard', 'title': '공동·대리입찰 준비 서류'},
    'internal': {'file': '04_internal_reports.pdf', 'roles': ['agency', 'admin'], 'min_plan': 'Standard', 'title': '기관 내부보고서 서류'},
    'room': {'file': '05_participation_room.pdf', 'roles': ['partner', 'agency', 'admin'], 'min_plan': 'Basic', 'title': '참여방·검토용 서류'},
    'workbid': {'file': '06_internal_work_bid.pdf', 'roles': ['partner', 'enterprise', 'admin'], 'min_plan': 'Basic', 'title': '내부 작업입찰 서류'},
    'post': {'file': '07_post_award_management.pdf', 'roles': ['partner', 'agency', 'admin'], 'min_plan': 'Plus', 'title': '낙찰 후 사후관리 서류'},
    'report': {'file': '08_resource_performance.pdf', 'roles': ['enterprise', 'agency', 'admin'], 'min_plan': 'Standard', 'title': '자원순환·성과보고 서류'},
    'audit': {'file': '09_admin_audit.pdf', 'roles': ['admin'], 'min_plan': 'Admin', 'title': '관리자·감사용 서류'},
}

app = FastAPI(
    title='자원잇다 Resource Recovery Operating System API v51.12 structural stable',
    version=APP_VERSION,
    description='v50.20 기본구조를 유지하면서 버튼·관리자·푸터·수거동선·NOTICE·압축·정적페이지·API-ready 구조까지 점검한 안정화 API.',
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

class Login(BaseModel):
    id: str
    password: str

class Signup(BaseModel):
    role: str = Field(pattern='^(personal|partner|agency|enterprise)$')
    id: str
    password: str
    name: str
    displayName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    documents: List[str] = Field(default_factory=list)
    memo: Optional[str] = None

class AdminDecision(BaseModel):
    decision: str = Field(pattern='^(approve|reject|hold)$')
    memo: Optional[str] = None

class DisposalPatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    material: Optional[str] = None
    minWeightKg: Optional[float] = None
    minValueKrw: Optional[float] = None
    countThreshold: Optional[int] = None
    preparation: Optional[str] = None
    disposalMethod: Optional[str] = None
    disposalChannel: Optional[str] = None
    packaging: Optional[str] = None
    photoGuide: Optional[str] = None
    caution: Optional[str] = None
    pickupRule: Optional[str] = None
    legalNote: Optional[str] = None
    adminCheck: Optional[str] = None
    localDifference: Optional[str] = None

class BidroomPatch(BaseModel):
    status: Optional[str] = None
    visibility: Optional[str] = None
    memo: Optional[str] = None

class PickupStatusPatch(BaseModel):
    status: str
    partner_id: Optional[str] = None
    memo: Optional[str] = None

class ApiConfigTest(BaseModel):
    service: str
    dry_run: bool = True

class ApiKeyUpdate(BaseModel):
    env: str
    value: str = ''

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    displayName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    password: Optional[str] = None

class PickupEligibility(BaseModel):
    item: Optional[str] = None
    material: Optional[str] = None
    weight: float = 0
    value: float = 0
    count: int = 0
    bulky: bool = False
    address: Optional[str] = None

class Intake(BaseModel):
    role: str = 'agency'
    organization: Optional[str] = None
    purpose: Optional[str] = None
    items: Optional[str] = None
    location: Optional[str] = None
    dates: Optional[str] = None
    amount: Optional[str] = None
    memo: Optional[str] = None
    requested_forms: List[str] = Field(default_factory=list)

class RouteRequest(BaseModel):
    stops: List[str] = Field(default_factory=list)
    mode: str = 'shortest'
    start: Optional[str] = None
    vehicle_count: int = 1
    time_window: Optional[str] = None

class PriceSim(BaseModel):
    material: Optional[str] = None
    market_price: float
    qty: float
    refund_rate: float = 0.68
    logistics: float = 0
    risk: float = 0
    fee_rate: float = 0.1
    min_margin: float = 0

class PriceRuleUpdate(BaseModel):
    market_price: Optional[float] = None
    refund_rate: Optional[float] = None
    logistics: Optional[float] = None
    risk: Optional[float] = None
    min_margin: Optional[float] = None
    memo: Optional[str] = None

class Inquiry(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    category: Optional[str] = '일반문의'
    body: str

class InquiryAnswer(BaseModel):
    answer: str

class UserPatch(BaseModel):
    status: Optional[str] = None
    plan: Optional[str] = None
    trustScore: Optional[int] = None
    memo: Optional[str] = None
    displayName: Optional[str] = None

class NoticeCreate(BaseModel):
    title: str
    type: str = '공지'
    body: str = ''
    file: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None

class CampaignCreate(BaseModel):
    title: str
    period: str
    goal: str
    reward: Optional[str] = None
    status: str = '진행중'
    body: Optional[str] = None

class PaymentPrepareRequest(BaseModel):
    user_id: str
    plan: str
    amount: int
    provider: str = 'toss'

class NotificationRequest(BaseModel):
    to: str
    message: str
    channel: str = 'sms'

class DisposalGuideRequest(BaseModel):
    item: Optional[str] = None
    material: Optional[str] = None
    photo_filename: Optional[str] = None
    weight: float = 0
    value: float = 0
    count: int = 0
    bulky: bool = False
    address: Optional[str] = None

class PickupSubmit(BaseModel):
    item: str
    material: Optional[str] = None
    weight: float = 0
    value: float = 0
    count: int = 0
    bulky: bool = False
    address: str
    preferred_date: Optional[str] = None
    memo: Optional[str] = None

class BidroomCreate(BaseModel):
    title: str
    type: str = '자원잇다 내부 작업입찰'
    region: str = ''
    items: str = ''
    volume: str = ''
    deadline: str = ''
    body: str = ''
    visibility: str = 'plan-gated'

class QuickRecoveryRequest(BaseModel):
    action: str = Field(pattern='^(sell|pickup)$')
    item: str = '관리자 검토 필요'
    category: Optional[str] = None
    model: Optional[str] = None
    condition: Optional[str] = 'unknown'
    estimated_low: int = 0
    estimated_high: int = 0
    address: Optional[str] = None
    phone: Optional[str] = None
    memo: Optional[str] = None

class SalePromptRequest(BaseModel):
    item: str = '관리자 검토 필요'
    category: Optional[str] = None
    model: Optional[str] = None
    condition: Optional[str] = 'unknown'
    estimated_low: int = 0
    estimated_high: int = 0
    memo: Optional[str] = None

class ProjectApplication(BaseModel):
    project_id: str = 'used-car-parts-share'
    company: str
    contact: str
    phone: Optional[str] = None
    region: Optional[str] = None
    role: str = '부품 매입/판매 파트너'
    license_status: Optional[str] = None
    memo: Optional[str] = None

# ----------------- persistence -----------------
def hash_password(pw: str) -> str:
    salt = os.getenv('PASSWORD_SALT', 'jawonitda-demo-salt').encode()
    return hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, 120_000).hex()

def now_id(prefix: str) -> str:
    return f'{prefix}-{int(time.time()*1000)}'

def default_plan_for_role(role: str) -> str:
    return {'personal':'Free','partner':'Free','agency':'Free','enterprise':'Free'}.get(role, 'Free')

def required_documents_for_role(role: str) -> List[str]:
    return {
        'personal': ['본인 이름', '휴대폰 번호', '기본 수거지역'],
        'partner': ['사업자등록증', '폐기물/재활용 관련 허가·신고자료', '차량등록증', '보험증권', '장비·인력 현황표', '작업 가능 품목표'],
        'agency': ['기관 확인자료', '담당부서 정보', '담당자 재직/위임 확인자료', '공문 또는 내부 요청자료'],
        'enterprise': ['사업자등록증', '사업장 정보', 'ESG·총무·시설 담당자 정보', '정기수거 희망 품목표'],
    }.get(role, [])

def default_db() -> Dict[str, Any]:
    users = {
        'admin': {'id': 'admin', 'password_hash': hash_password('1234'), 'role': 'admin', 'plan': 'Admin', 'status': 'approved', 'name': '관리자', 'displayName': '관리자님', 'email': '', 'phone': '', 'address': '', 'trustScore': 100, 'memo': '관리자 데모'},
        'brans911': {'id': 'brans911', 'password_hash': hash_password('brans911!'), 'role': 'admin', 'plan': 'Admin', 'status': 'approved', 'name': '관리자', 'displayName': '관리자님', 'email': '', 'phone': '', 'address': '', 'trustScore': 100, 'memo': '기존 관리자 데모'},
        'personal': {'id': 'personal', 'password_hash': hash_password('1234'), 'role': 'personal', 'plan': 'Free', 'status': 'approved', 'name': '김예찬', 'displayName': '김예찬님', 'email': 'personal@example.com', 'phone': '010-0000-0000', 'address': '광주 서구', 'trustScore': 70, 'memo': '개인 데모'},
        'partner': {'id': 'partner', 'password_hash': hash_password('1234'), 'role': 'partner', 'plan': 'Gold', 'status': 'approved', 'name': '광주그린자원', 'displayName': '광주그린자원님', 'email': 'partner@example.com', 'phone': '062-000-0000', 'address': '광주 북구', 'trustScore': 94, 'memo': '수거업체 데모'},
        'agency': {'id': 'agency', 'password_hash': hash_password('1234'), 'role': 'agency', 'plan': 'Pro', 'status': 'approved', 'name': '광주광역시청', 'displayName': '광주광역시청님', 'email': 'agency@example.com', 'phone': '062-120', 'address': '광주 서구', 'trustScore': 90, 'memo': '기관 데모'},
        'company': {'id': 'company', 'password_hash': hash_password('1234'), 'role': 'enterprise', 'plan': 'ESG Plus', 'status': 'approved', 'name': '기업회원', 'displayName': '기업회원님', 'email': 'company@example.com', 'phone': '02-0000-0000', 'address': '광주 광산구', 'trustScore': 92, 'memo': '기업 데모'},
        'samsung': {'id': 'samsung', 'password_hash': hash_password('samsung123!'), 'role': 'enterprise', 'plan': 'ESG Plus', 'status': 'approved', 'name': '삼성전자', 'displayName': '삼성전자님', 'email': 'samsung@example.com', 'phone': '02-0000-0000', 'address': '수원시', 'trustScore': 95, 'memo': '기존 기업 데모'},
    }
    return {
        'users': users,
        'inquiries': [{'id': 'inq-demo-1', 'name': '데모문의', 'phone': '010-0000-0000', 'email': '', 'category': '오류 신고', 'body': '버튼 클릭과 관리자 화면이 정상 작동하는지 확인 요청', 'status': 'open', 'created_at': time.time()}],
        'notices': [
            {'id': 'notice-1', 'type': '공지', 'title': '자원잇다 v50.17 중간배포 안정화 안내', 'date': '2026-06-12', 'file': '배포안내', 'url': '', 'body': '새로고침 시 이전 화면이 보이는 캐시 문제를 줄이고, 공지자료 화면과 배출 안내표 연결을 안정화했습니다.'},
            {'id': 'notice-2', 'type': '수정', 'title': '배출 안내표·품목 검색 오류 수정', 'date': '2026-06-12', 'file': '기능수정', 'url': '', 'body': '품목 검색, 사진 선택 후 안내표 생성, 수정요청 접수 흐름을 재검토했습니다. 내부 등급 모델은 추후 팀원 모델과 연동 예정입니다.'},
            {'id': 'notice-3', 'type': '안내', 'title': '내부 가치등급 모델 연동 예정', 'date': '2026-06-12', 'file': '로드맵', 'url': '', 'body': 'S급 중고판매, A급 수리재판매, B급 부품회수, C급 원자재회수, D급 폐기, E급 보안위험 분류 모델을 별도 모듈로 연결할 예정입니다.'},
        ],
        'campaigns': [
            {'id': 'camp-1', 'title': '우리동네 PET 묶음수거 캠페인', 'period': '상시', 'goal': 'PET 500kg 회수', 'reward': '참여 인증 뱃지', 'status': '진행중', 'body': '기준 미달 수거건을 묶어 지역별 캠페인으로 연결합니다.'},
            {'id': 'camp-2', 'title': '학교 불용가구 새활용 캠페인', 'period': '월간', 'goal': '책걸상 200개 재사용', 'reward': '기관 성과보고서', 'status': '예정', 'body': '학교·기관 불용가구를 지역 파트너와 연결합니다.'},
        ],
        'projects': [
            {'id': 'used-market-lite', 'type': '판매', 'title': '자원잇다 중고형 판매 실험', 'status': '모집중', 'summary': '사진 분석 결과가 S/A급이면 당근마켓 같은 중고거래 형식의 판매글 초안을 만들고, 판매 성공 시 건당 약 1,000원 플랫폼 수수료를 받는 실험입니다.', 'fee': 1000, 'roles': ['중고판매 대행 파트너', '검수 파트너', '지역 거래 지원 파트너'], 'legal_note': '실거래·배송·환불·하자책임은 운영 전 별도 약관과 법무 검토가 필요합니다.'},
            {'id': 'used-car-parts-share', 'type': '프로젝트', 'title': '중고차 매입·부품 소매 수익분배 프로젝트', 'status': '파트너 모집중', 'summary': '자원잇다가 저가 중고차 후보를 확보하면, 허가·자격이 있는 자동차해체재활용/정비/부품판매 파트너가 검수·부품화·소매판매를 수행하고 판매수익에서 비용과 수수료를 제외한 금액을 약정 비율로 분배하는 모델입니다.', 'fee': 0, 'roles': ['자동차해체재활용업체', '정비·재제조 업체', '부품 소매 판매업체', '물류·보관 파트너'], 'legal_note': '자원잇다가 직접 차량 해체·폐차·촉매 거래를 수행하지 않으며, 관련 허가 보유 파트너와 계약 후 진행합니다.'},
        ],
        'quick_actions': [],
        'pickup_requests': [
            {'id': 'pickup-demo-1', 'user': 'personal', 'item': '폐노트북 8대', 'material': '전산장비', 'weight': 24, 'value': 180000, 'count': 8, 'address': '광주 서구 치평동', 'preferred_date': '이번 주 오후', 'memo': '저장장치 확인 필요', 'status': 'received', 'message': '즉시수거 검토 대상', 'created_at': time.time()},
        ],
        'project_applications': [],
        'partners': [
            {'id': 'p1', 'name': '광주그린자원', 'region': '광주 북구', 'materials': '폐가전·고철·플라스틱', 'vehicles': '1톤 2대 / 2.5톤 1대', 'plan': 'Gold', 'score': 94, 'eta': '평균 38분'},
            {'id': 'p2', 'name': '서구순환물류', 'region': '광주 서구', 'materials': '사무가구·폐지·PET', 'vehicles': '1톤 3대', 'plan': 'Plus', 'score': 89, 'eta': '평균 45분'},
            {'id': 'p3', 'name': '광산리사이클', 'region': '광주 광산구', 'materials': '고철·비철·전산장비', 'vehicles': '3.5톤 1대', 'plan': 'Standard', 'score': 84, 'eta': '평균 52분'},
        ],
        'price_rules': {
            'steel': {'material': '고철·철제류', 'market_price': 260, 'refund_rate': 0.68, 'logistics': 15000, 'risk': 3000, 'min_margin': 10000, 'memo': '시세 변동 큼. 월 1회 이상 조정'},
            'aluminum': {'material': '알루미늄', 'market_price': 1400, 'refund_rate': 0.70, 'logistics': 12000, 'risk': 3000, 'min_margin': 12000, 'memo': '분리도 확인'},
            'copper': {'material': '동·구리류', 'market_price': 8300, 'refund_rate': 0.76, 'logistics': 10000, 'risk': 5000, 'min_margin': 20000, 'memo': '도난품 리스크 확인'},
            'pet': {'material': 'PET·플라스틱', 'market_price': 250, 'refund_rate': 0.55, 'logistics': 16000, 'risk': 4000, 'min_margin': 8000, 'memo': '묶음수거 권장'},
            'paper': {'material': '폐지·박스', 'market_price': 90, 'refund_rate': 0.50, 'logistics': 13000, 'risk': 2000, 'min_margin': 5000, 'memo': '물기/오염 확인'},
            'ewaste': {'material': '전산장비·소형가전', 'market_price': 1800, 'refund_rate': 0.64, 'logistics': 18000, 'risk': 8000, 'min_margin': 18000, 'memo': '개인정보 저장매체 확인 필수'},
        },
        'orders': [],
        'audit': [],
    }

def normalize_notices_for_v5017(data: Dict[str, Any]) -> None:
    # v50.17: old demo notices used blank dates and text-only attachment labels,
    # which made the public notice page look broken after refresh/redeploy.
    defaults = default_db().get('notices', [])
    notices = data.get('notices') or []
    old_demo = (
        not notices
        or all(str(n.get('date','')).startswith('____') for n in notices[:2])
        or any('베타 운영 안내' in str(n.get('title','')) for n in notices)
    )
    if old_demo:
        data['notices'] = defaults
        return
    for n in notices:
        if not n.get('id'):
            n['id'] = now_id('notice')
        if not n.get('date') or str(n.get('date')).startswith('____'):
            n['date'] = datetime.now().strftime('%Y-%m-%d')
        n.setdefault('type', '공지')
        n.setdefault('file', '공지')
        n.setdefault('url', '')
        n.setdefault('body', '')


def normalize_notices_for_v5019(data: Dict[str, Any]) -> None:
    """Keep public notices from falling back to old demo/blank rows after refresh or redeploy."""
    current_defaults = [
        {'id': 'notice-5019-1', 'type': '배포', 'title': '자원잇다 v50.20 웹 안정화 배포', 'date': '2026-06-12', 'file': '배포안내', 'url': '', 'body': '새로고침 시 이전 상단바가 다시 보이는 문제를 줄이고, 최종 메뉴·푸터·공지자료 화면을 고정했습니다.'},
        {'id': 'notice-5019-2', 'type': '기능', 'title': '사진 분석 후 중고형 판매·수거 신청 연결', 'date': '2026-06-12', 'file': '기능안내', 'url': '', 'body': '분석 결과에서 중고형 판매글 생성, 판매 접수 저장, 자원 수거 신청으로 바로 이동할 수 있습니다.'},
        {'id': 'notice-5019-3', 'type': '프로젝트', 'title': '중고차 부품 소매 수익분배 프로젝트 모집', 'date': '2026-06-12', 'file': '프로젝트', 'url': '/projects.html', 'body': '허가·자격 보유 파트너를 대상으로 검수, 부품화, 소매판매, 정산 참여 신청 흐름을 추가했습니다.'},
        {'id': 'notice-5019-4', 'type': '고지', 'title': '실제 운영 전 허가·법무 검토 필요', 'date': '2026-06-12', 'file': '업무범위', 'url': '/policies/scope.html', 'body': '자원잇다는 중간배포 MVP이며, 무허가 폐기물 운반·차량 직접 해체·공식 공공입찰 대행을 수행하지 않습니다.'},
    ]
    notices = data.get('notices') or []
    bad_or_old = (
        not notices
        or any(str(n.get('date','')).startswith('____') for n in notices)
        or any('베타 운영 안내' in str(n.get('title','')) for n in notices)
        or any('v50.17' in str(n.get('title','')) or 'v50.18' in str(n.get('title','')) for n in notices[:3])
    )
    if bad_or_old:
        # Preserve custom admin notices that are not old demo/version rows.
        custom = [n for n in notices if n.get('id') and not any(x in str(n.get('title','')) for x in ['베타 운영 안내','v50.17','v50.18'])]
        data['notices'] = current_defaults + custom[:20]
        return
    seen = set()
    cleaned = []
    for n in notices:
        n.setdefault('id', now_id('notice'))
        n.setdefault('type', '공지')
        n.setdefault('date', datetime.now().strftime('%Y-%m-%d'))
        n.setdefault('file', '공지')
        n.setdefault('url', '')
        n.setdefault('body', '')
        key = n.get('id') or n.get('title')
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(n)
    data['notices'] = cleaned[:50]

def load_db() -> Dict[str, Any]:
    if not DB_PATH.exists():
        DB_PATH.write_text(json.dumps(default_db(), ensure_ascii=False, indent=2), encoding='utf-8')
    data = json.loads(DB_PATH.read_text(encoding='utf-8'))
    # self-heal missing keys after upgrades
    base = default_db()
    for k, v in base.items():
        data.setdefault(k, v)
    normalize_notices_for_v5017(data)
    normalize_notices_for_v5019(data)
    return data

def save_db(db: Dict[str, Any]) -> None:
    tmp = DB_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(DB_PATH)

def audit(action: str, actor: str = 'system', detail: Optional[Dict[str, Any]] = None) -> None:
    record = {'ts': time.time(), 'action': action, 'actor': actor, 'detail': detail or {}}
    with AUDIT_LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    db = load_db()
    db.setdefault('audit', []).append(record)
    db['audit'] = db['audit'][-500:]
    save_db(db)

# ----------------- auth -----------------
def sign_token(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip('=')
    sig = hmac.new(SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f'jwi.{body}.{sig}'

def verify_token(token: str) -> Dict[str, Any]:
    if token.startswith('demo-'):
        demo_map = {'demo-admin': 'brans911', 'demo-personal': 'personal', 'demo-partner': 'partner', 'demo-agency': 'agency', 'demo-enterprise': 'samsung'}
        uid = demo_map.get(token)
        if not uid: raise HTTPException(401, '유효하지 않은 토큰입니다.')
        return user_public(load_db()['users'][uid])
    try:
        _, body, sig = token.split('.', 2)
        expected = hmac.new(SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(expected, sig):
            raise ValueError('bad signature')
        raw = base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))
        payload = json.loads(raw)
        if payload.get('exp', 0) < time.time():
            raise HTTPException(401, '토큰이 만료되었습니다.')
        user = load_db()['users'].get(payload.get('id'))
        if not user:
            raise HTTPException(401, '사용자를 찾을 수 없습니다.')
        return user_public(user)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, '로그인이 필요합니다.')

def user_public(u: Dict[str, Any]) -> Dict[str, Any]:
    d = {k: v for k, v in u.items() if k != 'password_hash'}
    d.setdefault('displayName', f"{d.get('name','회원')}님")
    d['roleLabel'] = ROLE_LABEL.get(d.get('role'), d.get('role'))
    return d

def current_user(request: Request) -> Dict[str, Any]:
    auth = request.headers.get('authorization', '')
    token = auth.removeprefix('Bearer ').strip() or request.query_params.get('token', '')
    if not token:
        raise HTTPException(401, '로그인이 필요합니다.')
    return verify_token(token)

def require_admin(request: Request) -> Dict[str, Any]:
    u = current_user(request)
    if u['role'] != 'admin':
        raise HTTPException(403, '관리자 권한이 필요합니다.')
    return u

def allowed_form(u: Dict[str, Any], form_id: str) -> Dict[str, Any]:
    info = FORM_ACCESS.get(form_id)
    if not info:
        raise HTTPException(404, '존재하지 않는 보호자료입니다.')
    if u['role'] not in info['roles']:
        raise HTTPException(403, '해당 역할에서 사용할 수 없는 보호자료입니다.')
    if PLAN_RANK.get(u.get('plan', 'Free'), 0) < PLAN_RANK.get(info['min_plan'], 99):
        raise HTTPException(403, f"{info['min_plan']} 이상 플랜에서 이용할 수 있습니다.")
    if u.get('status') != 'approved' and u['role'] != 'admin':
        raise HTTPException(403, '승인 완료 회원만 이용할 수 있습니다.')
    return info

# ----------------- utilities/API connectors -----------------
RATE_BUCKET: Dict[str, List[float]] = {}

def safe_filename(name: str) -> str:
    stem = re.sub(r'[^a-zA-Z0-9가-힣_.-]', '_', name or 'upload.bin')
    return stem[:120]

async def openai_chat(messages: List[Dict[str, Any]], max_tokens: int = 1400) -> Optional[str]:
    key = get_config_value('OPENAI_API_KEY')
    if not key:
        return None
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={'model': get_config_value('OPENAI_MODEL', 'gpt-4o-mini'), 'messages': messages, 'temperature': 0.2, 'max_tokens': max_tokens},
        )
    if r.status_code >= 400:
        raise HTTPException(502, 'OpenAI API 오류: ' + r.text[:300])
    return r.json()['choices'][0]['message']['content']

def calculate_price(data: PriceSim) -> Dict[str, Any]:
    total = data.market_price * data.qty
    customer = max(0, total * data.refund_rate - data.logistics - data.risk)
    fee = customer * data.fee_rate
    profit = total - customer - data.logistics - data.risk + fee
    recommended = '기본 단가 적용 가능'
    if profit < data.min_margin:
        recommended = '단가 낮춤 또는 묶음수거/처리비 안내 권장'
    if customer <= 0:
        recommended = '고객 매입가 0원 또는 유상 처리 안내 검토'
    return {
        'total_market_value': round(total),
        'recommended_customer_purchase_price': round(customer),
        'jawonitda_fee': round(fee),
        'expected_profit': round(profit),
        'decision': recommended,
        'formula': '추천매입가=max(0, 시세×수량×환급률-물류비-처리리스크비), 예상이익=총시세-추천매입가-물류비-리스크비+중계수수료',
    }


def disposal_catalog() -> List[Dict[str, Any]]:
    path = STATIC / 'data' / 'disposal_items.json'
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding='utf-8'))

def match_disposal_item(query: str = '', category: str = '', limit: int = 50) -> List[Dict[str, Any]]:
    q = (query or '').lower().replace(' ', '')
    category = (category or '').strip()
    rows = []
    for item in disposal_catalog():
        hay = ' '.join([item.get('id',''), item.get('name',''), item.get('category',''), item.get('material',''), item.get('customerSummary',''), ' '.join(item.get('keywords', []))]).lower().replace(' ', '')
        if category and item.get('category') != category:
            continue
        if q and q not in hay:
            continue
        rows.append(item)
        if len(rows) >= limit:
            break
    return rows

def guide_for_item(item: Dict[str, Any], weight: float = 0, value: float = 0, count: int = 0, bulky: bool = False) -> Dict[str, Any]:
    reasons = []
    if weight >= float(item.get('minWeightKg', 0)) and item.get('minWeightKg', 0) > 0:
        reasons.append(f"무게 기준 충족: {weight}kg")
    if value >= float(item.get('minValueKrw', 0)) and item.get('minValueKrw', 0) > 0:
        reasons.append(f"가치 기준 충족: {value:,.0f}원")
    if count >= int(item.get('countThreshold', 0)) and item.get('countThreshold', 0) > 0:
        reasons.append(f"수량 기준 충족: {count}개")
    if bulky:
        reasons.append('대형품 포함')
    instant = bool(item.get('instantPickup')) and bool(reasons)
    next_step = '즉시수거 매칭 가능' if instant else ('관리자 검토 또는 전용수거 안내' if not item.get('instantPickup') else '묶음수거 대기 또는 캠페인 참여')
    return {
        'item': item,
        'eligible': instant,
        'next': next_step,
        'reasons': reasons or ['기준 미달 또는 관리자 확인 필요'],
        'display_table': {
            '품목명': item.get('name'),
            '분류': item.get('category'),
            '재질': item.get('material'),
            '고객 안내 요약': item.get('customerSummary'),
            '배출유형': item.get('disposalType'),
            '위험도': item.get('riskLevel'),
            '즉시수거 기준': item.get('pickupRule'),
            '배출 경로': item.get('disposalChannel'),
            '배출 장소': item.get('dischargePlace'),
            '가정 배출': item.get('householdMethod'),
            '아파트·상가 배출': item.get('apartmentMethod'),
            '사업장 배출': item.get('businessMethod'),
            '기관 물품 처리': item.get('agencyMethod'),
            '배출 준비': item.get('preparation'),
            '상세 배출 방법': item.get('disposalMethod'),
            '단계별 배출 절차': item.get('disposalStepsDetailed'),
            '사진 체크리스트': item.get('photoChecklist'),
            '포장/사진 기준': f"{item.get('packaging','')} / {item.get('photoGuide','')}",
            '주의사항': item.get('caution'),
            '금지사항': ' / '.join(item.get('dont', [])),
            '요금/매입 안내': item.get('feeDecisionGuide') or item.get('feeNote'),
            '운영 처리': item.get('operatorDecision'),
            '법적·업무 확인': item.get('legalNote'),
            '관리자 확인': item.get('adminCheck'),
            '지역별 차이': item.get('localDifference'),
        }
    }



# ============================================================
# v50.5 photo classification safety patch
# - Do not default to the first catalog item when a photo is ambiguous.
# - Detect obvious e-waste/laptop internal photos in safe-mock mode.
# - When confidence is low, return 관리자 검토 instead of wrong items like PET bottle.
# ============================================================

def v505_unknown_disposal_item(reason: str = '사진만으로 품목을 확정하기 어렵습니다.') -> Dict[str, Any]:
    return {
        'id': 'NEEDS-ADMIN-REVIEW',
        'name': '관리자 검토 필요',
        'category': '사진판정 보류',
        'material': '사진 확인 필요',
        'customerSummary': reason + ' 품목명, 수량, 무게, 개인정보 저장매체 여부를 함께 입력하면 정확도가 올라갑니다.',
        'disposalType': '관리자 검토',
        'riskLevel': '낮음~보통',
        'instantPickup': False,
        'pickupRule': '사진판정 보류: 관리자 확인 후 즉시수거/묶음수거/캠페인 전환',
        'disposalChannel': '관리자 확인',
        'dischargePlace': '현장 또는 사진 추가 확인',
        'householdMethod': '품목명과 사진을 추가로 등록하세요.',
        'apartmentMethod': '관리사무소 배출 전 등록 여부를 확인하세요.',
        'businessMethod': '사업장/기관 물품은 담당자 확인 후 처리하세요.',
        'agencyMethod': '불용자산 여부와 저장매체 포함 여부를 확인하세요.',
        'preparation': '정면, 측면, 모델명, 파손 부위, 전체 크기 사진을 추가하세요.',
        'disposalMethod': '관리자 검토 후 배출 안내표를 확정합니다.',
        'disposalStepsDetailed': [
            {'step': 1, 'title': '추가 사진 확인', 'detail': '전체 사진과 모델명/라벨 사진을 추가합니다.', 'check': '사진이 흐리거나 일부만 보이면 판정 보류'},
            {'step': 2, 'title': '품목명 직접 입력', 'detail': '예: 노트북, 모니터, 책상, 의자, 배터리 등', 'check': '자동판정이 불확실하면 직접 입력 우선'},
            {'step': 3, 'title': '관리자 검토', 'detail': '위험물·저장매체·대형폐기물 여부를 확인합니다.', 'check': '오판정 방지'}
        ],
        'photoChecklist': ['전체 모습', '모델명/라벨', '파손 부위', '크기 비교 사진'],
        'separationChecklist': ['개인정보 저장매체 여부', '배터리 여부', '유리/날카로운 부품 여부'],
        'beforeDischargeChecklist': ['품목명 직접 입력', '수량·무게 확인', '관리자 검토 요청'],
        'routeOptions': [{'channel': '관리자 검토', 'condition': '사진판정 불확실', 'action': '추가 정보 확인 후 안내'}],
        'instantPickupCases': ['품목·무게·가치가 확인된 경우'],
        'bundleCases': ['소량 또는 품목 불확실한 경우'],
        'dont': ['불확실한 품목을 자동으로 일반 재활용품으로 확정하지 않기', '배터리·저장매체 포함품을 무단 배출하지 않기'],
        'do': ['품목명을 직접 입력하기', '사진을 2~3장 추가하기', '저장매체·배터리 여부 표시하기'],
        'caution': '사진판정 보류 상태입니다. 잘못된 품목 안내를 피하기 위해 관리자 확인이 필요합니다.',
        'adminCheck': '사진판정 보류: 품목명/저장매체/배터리/위험물 여부 확인',
    }

def v505_visual_features(path: Path) -> Dict[str, float]:
    try:
        from PIL import Image
        img = Image.open(path).convert('RGB')
        img.thumbnail((160, 160))
        pix = list(img.getdata())
        if not pix:
            return {}
        n = len(pix)
        dark = sum(1 for r,g,b in pix if (r+g+b)/3 < 75) / n
        white = sum(1 for r,g,b in pix if (r+g+b)/3 > 220) / n
        green = sum(1 for r,g,b in pix if g > 70 and g > r*1.10 and g > b*1.03) / n
        blue = sum(1 for r,g,b in pix if b > 95 and b > r*1.15 and b > g*0.85) / n
        red = sum(1 for r,g,b in pix if r > 120 and r > g*1.15 and r > b*1.15) / n
        gray = sum(1 for r,g,b in pix if abs(r-g)<18 and abs(g-b)<18 and 70 <= (r+g+b)/3 <= 210) / n
        # very cheap edge estimate from downscaled image
        small = img.resize((64, 64)).convert('L')
        vals = list(small.getdata())
        edge = 0
        total = 0
        for y in range(63):
            row = y*64
            for x in range(63):
                v = vals[row+x]
                if abs(v-vals[row+x+1]) > 24 or abs(v-vals[row+64+x]) > 24:
                    edge += 1
                total += 1
        return {'dark': dark, 'white': white, 'green': green, 'blue': blue, 'red': red, 'gray': gray, 'edge': edge/max(total,1)}
    except Exception:
        return {}

def v505_infer_photo_item(filename: str = '', path: Optional[Path] = None) -> Dict[str, Any]:
    name = (filename or '').lower().replace(' ', '')
    # 확실한 파일명 키워드 우선
    keyword_map = [
        (['노트북','laptop','notebook','맥북','그램','lggram'], '노트북', 0.98, '파일명 키워드'),
        (['컴퓨터','desktop','pc본체','본체','computer'], '컴퓨터 본체', 0.96, '파일명 키워드'),
        (['모니터','monitor','display'], '모니터', 0.96, '파일명 키워드'),
        (['휴대폰','스마트폰','phone','iphone','galaxy'], '스마트폰', 0.96, '파일명 키워드'),
        (['tv','텔레비전','티비'], 'TV', 0.95, '파일명 키워드'),
        (['pet병','생수병','bottle','pet'], '생수병', 0.92, '파일명 키워드'),
        (['박스','box','carton'], '택배박스', 0.92, '파일명 키워드'),
        (['의자','chair'], '의자', 0.92, '파일명 키워드'),
        (['책상','desk'], '책상', 0.92, '파일명 키워드'),
        (['캔','can'], '캔', 0.90, '파일명 키워드'),
    ]
    for keys, item, conf, reason in keyword_map:
        if any(k.lower().replace(' ','') in name for k in keys):
            return {'item': item, 'confidence': conf, 'reason': reason, 'features': {}}

    features = v505_visual_features(path) if path else {}
    dark = features.get('dark', 0)
    green = features.get('green', 0)
    white = features.get('white', 0)
    edge = features.get('edge', 0)
    gray = features.get('gray', 0)
    blue = features.get('blue', 0)

    # 노트북 내부/전자기판: 검은 배터리·팬 + 초록 PCB + 복잡한 엣지
    if green >= 0.035 and dark >= 0.16 and edge >= 0.18:
        return {'item': '노트북', 'confidence': 0.86, 'reason': '초록 회로기판/검은 배터리·팬/복잡한 내부 부품 패턴', 'features': features}
    # 컴퓨터 본체/전산장비 내부
    if green >= 0.045 and edge >= 0.22:
        return {'item': '컴퓨터 본체', 'confidence': 0.78, 'reason': '회로기판과 전산장비 내부 패턴', 'features': features}
    # 화면 캡처/UI처럼 흰 영역이 압도적이면 품목 확정 금지
    if white >= 0.72 and dark <= 0.12:
        return {'item': '', 'confidence': 0.20, 'reason': '화면 캡처 또는 문서 이미지로 보이며 실제 물품 사진이 아닐 가능성', 'features': features}
    # 플라스틱병류는 사진만으로 과도 판정하지 않음. 파란/투명 계열만 약하게.
    if blue >= 0.16 and white >= 0.25 and edge < 0.18:
        return {'item': '생수병', 'confidence': 0.62, 'reason': '투명/푸른 플라스틱병 추정 패턴', 'features': features}
    # 회색/검정+엣지 많으면 전자제품 관리자 검토로 유도
    if (dark >= 0.18 or gray >= 0.35) and edge >= 0.20:
        return {'item': '노트북', 'confidence': 0.66, 'reason': '전자제품/전산장비로 보이는 복잡한 부품 패턴', 'features': features}
    return {'item': '', 'confidence': 0.0, 'reason': 'safe-mock에서 확정 가능한 품목 단서가 부족함', 'features': features}

def v505_guide_from_inference(inference: Dict[str, Any], data: DisposalGuideRequest) -> Dict[str, Any]:
    query = inference.get('item') or data.item or data.material or ''
    matches = match_disposal_item(query, '', 1) if query else []
    if matches:
        guide = guide_for_item(matches[0], data.weight, data.value, data.count, data.bulky)
    else:
        guide = guide_for_item(v505_unknown_disposal_item(inference.get('reason') or '품목 확정 불가'), data.weight, data.value, data.count, data.bulky)
    guide['vision'] = inference
    guide['mode'] = 'real-ready' if get_config_value('VISION_API_KEY') else 'safe-mock-plus'
    guide['note'] = '현재는 safe-mock-plus입니다. 오판정을 피하기 위해 확신이 낮으면 관리자 검토로 보냅니다. VISION_API_KEY 연결 시 실제 사진분류로 전환하세요.'
    return guide


@app.middleware('http')
async def security_headers(request: Request, call_next):
    # v51.12 structural fix:
    # Previous versions rate-limited every static/page request. When a browser opened
    # many pages/resources or an audit crawler checked links, the middleware raised
    # HTTPException inside BaseHTTPMiddleware, which sometimes surfaced as 500 instead
    # of a clean 429. Now rate limiting is applied only to mutating requests and API
    # calls, static/page requests are not counted, and 429 is returned as JSONResponse.
    path = request.url.path or '/'
    should_rate_limit = path.startswith('/api/') or request.method not in ('GET', 'HEAD', 'OPTIONS')
    if should_rate_limit:
        ip = request.client.host if request.client else 'unknown'
        now = time.time()
        bucket = [t for t in RATE_BUCKET.get(ip, []) if now - t < 60]
        limit = int(os.getenv('RATE_LIMIT_PER_MINUTE', '1200'))
        if len(bucket) >= limit:
            return JSONResponse({'detail': '요청이 너무 많습니다. 잠시 후 다시 시도하세요.'}, status_code=429)
        bucket.append(now)
        RATE_BUCKET[ip] = bucket
    res = await call_next(request)
    res.headers['X-Content-Type-Options'] = 'nosniff'
    res.headers['X-Frame-Options'] = 'DENY'
    res.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    res.headers['Permissions-Policy'] = 'camera=(self), geolocation=(self), microphone=()'
    if request.method == 'GET' or path.startswith('/api/'):
        res.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
        res.headers['Pragma'] = 'no-cache'
        res.headers['Expires'] = '0'
        res.headers['Surrogate-Control'] = 'no-store'
    return res

# ----------------- public/system endpoints -----------------
@app.get('/api/health')
def health():
    return {'ok': True, 'app': APP_NAME, 'version': APP_VERSION, 'environment': APP_ENV}

@app.get('/api/bootstrap')
def bootstrap():
    db = load_db()
    return {
        'app': APP_NAME,
        'version': APP_VERSION,
        'publicMenu': ['홈', '배출안내', '폐자원가치', '폐자원회생', '프로젝트', '요금제', '공지', '고객센터'],
        'plans': json.loads((STATIC / 'data' / 'plans.json').read_text(encoding='utf-8')) if (STATIC / 'data' / 'plans.json').exists() else {},
        'notices': db.get('notices', [])[:5],
        'campaigns': db.get('campaigns', [])[:5],
    }

@app.post('/api/auth/login')
def login(data: Login):
    db = load_db()
    user = db['users'].get(data.id)
    if not user or not hmac.compare_digest(user['password_hash'], hash_password(data.password)):
        raise HTTPException(401, '아이디 또는 비밀번호가 올바르지 않습니다.')
    payload = {'id': data.id, 'role': user['role'], 'exp': time.time() + 60 * 60 * 24 * 7}
    token = sign_token(payload)
    public = user_public(user)
    public['token'] = token
    audit('login', data.id, {'role': user['role']})
    return public

@app.post('/api/auth/signup')
def signup(data: Signup):
    if not re.fullmatch(r'[A-Za-z0-9_]{4,30}', data.id or ''):
        raise HTTPException(400, '아이디는 영문/숫자/밑줄 4~30자로 입력하세요.')
    if len(data.password or '') < 8:
        raise HTTPException(400, '비밀번호는 8자 이상이어야 합니다.')
    db = load_db()
    if data.id in db['users']:
        raise HTTPException(409, '이미 사용 중인 아이디입니다.')
    status = 'approved' if data.role == 'personal' else 'pending_review'
    row = {
        'id': data.id,
        'password_hash': hash_password(data.password),
        'role': data.role,
        'plan': default_plan_for_role(data.role),
        'status': status,
        'name': data.name,
        'displayName': data.displayName or f'{data.name}님',
        'email': data.email or '',
        'phone': data.phone or '',
        'address': data.address or '',
        'trustScore': 50 if data.role != 'personal' else 70,
        'memo': data.memo or '',
        'required_documents': required_documents_for_role(data.role),
        'submitted_documents': data.documents,
        'created_at': time.time(),
    }
    db['users'][data.id] = row
    save_db(db)
    audit('signup', data.id, {'role': data.role, 'status': status})
    public = user_public(row)
    public['token'] = sign_token({'id': data.id, 'role': row['role'], 'exp': time.time() + 60 * 60 * 24 * 7})
    public['message'] = '가입이 완료되었습니다.' if status == 'approved' else '가입 신청이 접수되었습니다. 관리자 승인 후 유료 기능을 사용할 수 있습니다.'
    return public

@app.get('/api/me')
def me(request: Request):
    return current_user(request)

@app.patch('/api/me')
def update_me(data: ProfileUpdate, request: Request):
    u = current_user(request)
    db = load_db()
    row = db['users'][u['id']]
    for k in ['name', 'displayName', 'email', 'phone', 'address']:
        v = getattr(data, k)
        if v is not None:
            row[k] = v
    if data.password:
        if len(data.password) < 8:
            raise HTTPException(400, '비밀번호는 8자 이상이어야 합니다.')
        row['password_hash'] = hash_password(data.password)
    save_db(db)
    audit('profile_update', u['id'], {'fields': [k for k in data.model_dump(exclude_none=True).keys() if k != 'password']})
    out = user_public(row)
    out['token'] = request.headers.get('authorization', '').removeprefix('Bearer ').strip() or request.query_params.get('token', '')
    return out

# ----------------- user-facing service endpoints -----------------
@app.post('/api/pickup/eligibility')
def pickup_eligibility(data: PickupEligibility):
    reasons = []
    if data.weight >= 20:
        reasons.append('예상 무게 20kg 이상')
    if data.value >= 10000:
        reasons.append('예상 매입가치 10,000원 이상')
    if data.count >= 5:
        reasons.append('동일/유사 품목 5개 이상')
    if data.bulky:
        reasons.append('대형품 포함')
    eligible = bool(reasons)
    return {
        'eligible': eligible,
        'next': '즉시 수거 매칭' if eligible else '묶음수거 대기 또는 캠페인 참여',
        'reasons': reasons or ['기준 미달'],
        'criteria': {'min_weight_kg': 20, 'min_value_krw': 10000, 'min_count': 5, 'bulky_allowed': True},
    }

@app.post('/api/uploads')
async def upload_file(request: Request, file: UploadFile = File(...), purpose: str = 'general'):
    u = current_user(request)
    ext = Path(file.filename or '').suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f'허용되지 않은 파일 형식입니다: {ext}')
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f'업로드 파일은 {MAX_UPLOAD_MB}MB 이하만 가능합니다.')
    folder = UPLOADS / u['id']
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time())}_{safe_filename(file.filename or 'upload.bin')}"
    path = folder / name
    with path.open('wb') as f:
        shutil.copyfileobj(file.file, f)
    audit('file_upload', u['id'], {'filename': name, 'purpose': purpose, 'size': size})
    return {'ok': True, 'filename': name, 'size': size, 'purpose': purpose, 'note': '운영환경에서는 S3 등 보호 저장소로 연결하세요.'}

@app.post('/api/vision/classify')
async def classify_image(request: Request, file: UploadFile = File(...)):
    u = current_user(request)
    ext = Path(file.filename or '').suffix.lower()
    if ext not in {'.jpg','.jpeg','.png','.webp'}:
        raise HTTPException(400, '사진 파일만 업로드할 수 있습니다.')
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f'파일은 {MAX_UPLOAD_MB}MB 이하만 업로드할 수 있습니다.')
    tmp = UPLOADS / f"vision_{int(time.time()*1000)}_{safe_filename(file.filename or 'photo.jpg')}"
    tmp.write_bytes(content)
    inference = v505_infer_photo_item(file.filename or tmp.name, tmp)
    audit('vision_classify', u['id'], {'filename': file.filename, 'inferred': inference.get('item'), 'confidence': inference.get('confidence')})
    label = inference.get('item') or '관리자 검토 필요'
    weight_map = {'노트북': 1.8, '컴퓨터 본체': 7.0, '모니터': 4.0, '스마트폰': 0.2, '생수병': 0.03}
    return {
        'mode': 'real-ready' if get_config_value('VISION_API_KEY') else 'safe-mock-plus',
        'items': [
            {'label': label, 'confidence': inference.get('confidence', 0), 'estimated_weight_kg': weight_map.get(label, 0), 'reason': inference.get('reason')},
        ],
        'next': '품목이 확실하면 배출 안내표로 연결하고, 확신이 낮으면 관리자 검토로 보냅니다.',
        'features': inference.get('features', {}),
    }


@app.post('/api/ocr/analyze')
async def ocr_analyze(request: Request, file: UploadFile = File(...)):
    u = current_user(request)
    key = get_config_value('OCR_API_KEY')
    audit('ocr_analyze', u['id'], {'filename': file.filename, 'real': bool(key)})
    return {
        'mode': 'real-ready' if key else 'safe-mock',
        'extracted': {
            'document_type': '공문/목록표 추정',
            'organization': u.get('name'),
            'items': '책상, 의자, 폐가전, 전산장비 등',
            'dates': '담당자 확인 필요',
        },
        'note': 'OCR_API_KEY/OCR_API_URL 입력 시 실제 OCR 결과로 전환하세요.',
    }

@app.post('/api/intake/auto-fill')
async def auto_fill(data: Intake, request: Request):
    u = current_user(request)
    if u['role'] not in ['agency', 'enterprise', 'admin']:
        raise HTTPException(403, '기관·기업·관리자만 AI 서류작성 기능을 사용할 수 있습니다.')
    if PLAN_RANK.get(u.get('plan', 'Free'), 0) < 1 and u['role'] != 'admin':
        raise HTTPException(403, 'Basic 이상 플랜에서 사용할 수 있습니다.')
    prompt = f'''
자원잇다 기관/기업 서류 자동작성 초안을 작성하세요. 공식 제출본이 아니라 담당자 검토용 초안입니다.
입력값:
- 계정명: {u.get('name')}
- 조직명: {data.organization}
- 역할: {data.role}
- 목적: {data.purpose}
- 품목/자산: {data.items}
- 소재지/보관장소: {data.location}
- 일정: {data.dates}
- 금액/예정가격: {data.amount}
- 메모: {data.memo}
출력 형식:
1. 핵심요약
2. 자동으로 채울 수 있는 필드
3. 담당자가 반드시 확인해야 하는 필드
4. 추천 생성 서류
5. 법적·업무 검토
6. 다음 조치
금지: 자원잇다가 온비드 공식 입찰 제출, 보증금 납부, 개찰, 낙찰 대행을 한다고 표현하지 말 것.
'''
    text = await openai_chat([
        {'role': 'system', 'content': '너는 공공기관·기업용 행정서류 작성 보조자다. 사실을 단정하지 말고 담당자 검토용 초안으로 작성한다.'},
        {'role': 'user', 'content': prompt},
    ])
    if not text:
        text = '''[safe-mock AI 초안]
1. 핵심요약: 입력된 품목·장소·목적을 기준으로 공고 전 준비서류와 첨부자료가 필요합니다.
2. 자동으로 채울 수 있는 필드: 기관명, 공고명, 담당부서, 품목명, 보관장소, 수량, 예정가격, 현장확인 일정.
3. 담당자 확인 필드: 불용/대부 가능 여부, 권리관계, 폐기물 해당성, 개인정보·저장매체 제거, 최종 예정가격.
4. 추천 생성 서류: 공고작성 사전 체크리스트, 물건정보 입력표, 사진대장, 현장확인 안내문, 내부 검토보고서, 성과보고서.
5. 법적·업무 검토: 공식 공고·입찰·개찰·낙찰·계약은 온비드 및 기관 최종 공고문을 우선합니다.
6. 다음 조치: 사진과 목록표를 업로드하고 담당자 검토 후 PDF 생성 단계로 이동하세요.'''
    audit('auto_fill', u['id'], data.model_dump())
    return {'mode': 'real' if get_config_value('OPENAI_API_KEY') else 'safe-mock', 'draft': text, 'forms': data.requested_forms or ['pre', 'attach', 'internal', 'report']}

@app.post('/api/route/optimize')
def route_optimize(data: RouteRequest, request: Request):
    # v51.08: 수거동선 버튼은 발표/중간배포에서 비로그인 상태로 눌러도
    # 401 오류가 아니라 데모 계산값을 보여주도록 안전 처리합니다.
    demo_mode = False
    try:
        u = current_user(request)
    except HTTPException:
        u = {'id': 'route-demo', 'role': 'partner', 'plan': 'Gold', 'status': 'approved'}
        demo_mode = True
    # role/plan gate: 로그인 사용자는 실제 권한 적용, 비로그인 데모는 safe-mock 허용
    if not demo_mode:
        if u['role'] == 'partner' and PLAN_RANK.get(u.get('plan', 'Free'), 0) < PLAN_RANK['Plus']:
            raise HTTPException(403, '업체 Plus 이상 플랜에서 사용할 수 있습니다.')
        if u['role'] == 'enterprise' and PLAN_RANK.get(u.get('plan', 'Free'), 0) < PLAN_RANK['ESG Plus']:
            raise HTTPException(403, '기업 ESG Plus 이상 플랜에서 사용할 수 있습니다.')
        if u['role'] not in ['partner', 'enterprise', 'admin']:
            raise HTTPException(403, '최적노선 권한이 없습니다.')
    stops = data.stops or ['광주 서구 치평동', '광주 북구 용봉동', '광주 광산구 수완동']
    base = max(1, len(stops)) * 8.7
    factors = {'shortest': 0.88, 'profit': 1.06, 'time': 0.96, 'balanced': 0.94}
    factor = factors.get(data.mode, 0.94)
    distance = round(base * factor, 1)
    minutes = round(distance * (2.15 if data.mode == 'time' else 2.4))
    expected_profit = round(25000 * len(stops) * (1.18 if data.mode == 'profit' else 1.0) - distance * 780)
    co2 = round(distance * 0.31, 1)
    return {
        'mode': data.mode,
        'recommended_route': [data.start or '차고지'] + stops,
        'distance_km': distance,
        'estimated_minutes': minutes,
        'expected_profit_krw': expected_profit,
        'estimated_co2_kg': co2,
        'score': min(100, max(10, round(100 - distance * 0.35 + (10 if data.mode == 'profit' else 0)))),
        'note': ('비로그인 데모 계산입니다. 실제 운영은 업체/기업/관리자 권한으로 기록됩니다. ' if demo_mode else '') + 'ROUTE_API_URL 입력 시 실제 도로·시간창 기반 계산으로 전환됩니다.',
        'demo_mode': demo_mode,
    }

@app.post('/api/inquiries')
def create_inquiry(data: Inquiry):
    db = load_db()
    item = data.model_dump()
    item.update({'id': now_id('inq'), 'status': 'open', 'created_at': time.time(), 'answer': ''})
    db.setdefault('inquiries', []).append(item)
    save_db(db)
    audit('inquiry_created', item.get('name') or 'guest', {'id': item['id']})
    return {'ok': True, 'id': item['id'], 'message': '문의가 접수되었습니다.'}

@app.post('/api/payments/prepare')
def payment_prepare(data: PaymentPrepareRequest, request: Request):
    u = current_user(request)
    order_id = now_id('order')
    db = load_db()
    db.setdefault('orders', []).append({'id': order_id, 'user': u['id'], 'plan': data.plan, 'amount': data.amount, 'provider': data.provider, 'status': 'prepared', 'created_at': time.time()})
    save_db(db)
    audit('payment_prepare', u['id'], {'order_id': order_id, 'plan': data.plan, 'amount': data.amount})
    return {'order_id': order_id, 'status': 'prepared', 'provider': data.provider, 'mode': 'real-ready' if get_config_value('TOSS_SECRET_KEY') or get_config_value('PORTONE_API_KEY') else 'safe-mock', 'next': 'PG 키 입력 후 결제창 호출/웹훅 검증을 연결하세요.'}


@app.get('/api/disposal/items')
def disposal_items(q: str = '', category: str = '', limit: int = 80):
    limit = max(1, min(int(limit or 80), 300))
    rows = match_disposal_item(q, category, limit)
    return {'total_catalog': len(disposal_catalog()), 'count': len(rows), 'items': rows}


@app.get('/api/disposal/categories')
def disposal_categories():
    catalog = disposal_catalog()
    counts: Dict[str, int] = {}
    for row in catalog:
        counts[row.get('category','기타')] = counts.get(row.get('category','기타'), 0) + 1
    return {'total': len(catalog), 'categories': [{'name': k, 'count': v} for k, v in sorted(counts.items())]}

@app.get('/api/disposal/items/{item_id}')
def disposal_item_detail(item_id: str):
    rows = match_disposal_item(item_id, '', 1)
    if not rows:
        raise HTTPException(404, '품목을 찾을 수 없습니다.')
    return guide_for_item(rows[0])

@app.post('/api/disposal/guide')
def disposal_guide(data: DisposalGuideRequest):
    query = data.item or data.material or ''
    if not data.item and data.photo_filename:
        inference = v505_infer_photo_item(data.photo_filename, None)
        if inference.get('item') and inference.get('confidence', 0) >= 0.75:
            query = inference['item']
        else:
            guide = v505_guide_from_inference(inference, data)
            audit('disposal_guide_uncertain_photo', 'system', {'filename': data.photo_filename, 'reason': inference.get('reason')})
            return guide

    matches = match_disposal_item(query, '', 1) if query else []
    if not matches and data.material:
        matches = match_disposal_item('', data.material or '', 1)
    if not matches:
        guide = guide_for_item(v505_unknown_disposal_item('입력값과 일치하는 배출표를 찾지 못했습니다.'), data.weight, data.value, data.count, data.bulky)
        guide['mode'] = 'real-ready' if get_config_value('VISION_API_KEY') else 'safe-mock-plus'
        guide['note'] = '일치하는 품목이 없어 관리자 검토로 전환했습니다. 품목명을 더 구체적으로 입력하세요.'
        return guide
    guide = guide_for_item(matches[0], data.weight, data.value, data.count, data.bulky)
    guide['mode'] = 'real-ready' if get_config_value('VISION_API_KEY') else 'safe-mock-plus'
    guide['note'] = 'VISION_API_KEY 연결 시 사진에서 품목을 자동 분류하고 이 배출표와 매칭합니다.'
    return guide


@app.post('/api/pickup/submit')
def pickup_submit(data: PickupSubmit, request: Request):
    u = current_user(request)
    if u['role'] not in ['personal', 'admin']:
        raise HTTPException(403, '개인 회원 수거신청 기능입니다.')
    guide_req = DisposalGuideRequest(item=data.item, material=data.material, weight=data.weight, value=data.value, count=data.count, bulky=data.bulky, address=data.address)
    guide = disposal_guide(guide_req)
    db = load_db()
    row = data.model_dump()
    row.update({'id': now_id('pickup'), 'user': u['id'], 'status': 'instant_matching' if guide['eligible'] else 'bundle_waiting', 'guide': guide, 'created_at': time.time()})
    db.setdefault('pickup_requests', []).append(row)
    save_db(db)
    audit('pickup_submit', u['id'], {'id': row['id'], 'status': row['status']})
    return {'ok': True, 'request': row, 'message': '즉시수거 매칭으로 접수되었습니다.' if guide['eligible'] else '기준 미달로 묶음수거 대기 또는 캠페인 참여로 전환됩니다.'}

@app.get('/api/bidrooms')
def list_bidrooms(request: Request):
    u = current_user(request)
    if u['role'] not in ['partner', 'agency', 'enterprise', 'admin']:
        raise HTTPException(403, '입찰방은 업체·기관·기업·관리자 업무공간입니다.')
    if u['role'] != 'admin' and PLAN_RANK.get(u.get('plan','Free'),0) < PLAN_RANK['Basic']:
        raise HTTPException(403, 'Basic 이상 플랜에서 입찰방을 사용할 수 있습니다.')
    db = load_db()
    defaults = [
        {'id':'bid-001','title':'광주 서구 폐가구 월간 수거 파트너 모집','type':'기업 정기수거 작업입찰','region':'광주 서구','items':'책상·의자·파티션','volume':'월 120건 / 약 8.5톤','deadline':'____년 __월 __일','status':'open','owner':'system','visibility':'plan-gated','body':'Plus 이상 업체 우선 추천. 가격, 처리량, 차량·인력, 고객평가를 함께 봅니다.'},
        {'id':'bid-002','title':'○○학교 불용 책걸상 반출 작업','type':'기관 온비드 전후업무 참여방','region':'광주 북구','items':'책상 100개, 의자 200개','volume':'약 12톤','deadline':'____년 __월 __일','status':'open','owner':'system','visibility':'approved-only','body':'공식 매각공고와 별개로 반출·운반 작업업체를 선정하는 내부 작업제안방입니다.'},
        {'id':'bid-003','title':'전산장비 저장매체 파기 포함 수거','type':'비공개 입찰','region':'광주 광산구','items':'PC·노트북·복합기','volume':'월 40대','deadline':'____년 __월 __일','status':'private','owner':'system','visibility':'gold-only','body':'저장매체 파기증빙 가능 업체만 참여 가능합니다.'},
    ]
    rooms = db.setdefault('bidrooms', defaults)
    # Hide private rooms from lower plans
    filtered = []
    for r in rooms:
        if r.get('visibility') == 'gold-only' and u['role'] != 'admin' and PLAN_RANK.get(u.get('plan','Free'),0) < PLAN_RANK['Gold']:
            filtered.append({**r, 'locked': True, 'body': 'Gold 이상 플랜에서 세부내용 열람 가능'})
        else:
            filtered.append(r)
    return {'items': filtered}

@app.post('/api/bidrooms')
def create_bidroom(data: BidroomCreate, request: Request):
    u = current_user(request)
    if u['role'] not in ['agency', 'enterprise', 'admin']:
        raise HTTPException(403, '입찰방 생성은 기관·기업·관리자만 가능합니다. 업체는 참여 기능을 사용합니다.')
    if u['role'] != 'admin' and PLAN_RANK.get(u.get('plan','Free'),0) < PLAN_RANK['Standard']:
        raise HTTPException(403, '기관·기업 Standard 이상 플랜에서 입찰방을 생성할 수 있습니다.')
    db = load_db()
    item = data.model_dump()
    item.update({'id': now_id('bid'), 'owner': u['id'], 'ownerName': u.get('name'), 'status': 'open', 'created_at': time.time()})
    db.setdefault('bidrooms', []).insert(0, item)
    save_db(db)
    audit('bidroom_create', u['id'], {'id': item['id'], 'type': item['type']})
    return item

@app.get('/api/admin/operations-detail')
def admin_operations_detail(request: Request):
    require_admin(request)
    db = load_db()
    pickup = db.get('pickup_requests', [])
    bidrooms = db.get('bidrooms', [])
    catalog = disposal_catalog()
    return {
        'pickup_instant': sum(1 for x in pickup if x.get('status') == 'instant_matching'),
        'pickup_bundle_waiting': sum(1 for x in pickup if x.get('status') == 'bundle_waiting'),
        'bidrooms_open': sum(1 for x in bidrooms if x.get('status') == 'open'),
        'bidrooms_private': sum(1 for x in bidrooms if x.get('visibility') == 'gold-only'),
        'disposal_catalog_items': len(catalog),
        'danger_items': sum(1 for x in catalog if x.get('category') == '위험·특수'),
        'protected_documents': len(FORM_ACCESS),
        'recommended_actions': ['업체 승인대기 확인', '배출 안내표 위험품목 검토', 'Gold 비공개 입찰방 참여업체 확인', '묶음수거 대기건 캠페인 전환']
    }


@app.get('/api/partners')
def list_partners(region: str = '', material: str = ''):
    db = load_db()
    rows = db.get('partners', [])
    if region:
        rows = [x for x in rows if region in x.get('region','')]
    if material:
        rows = [x for x in rows if material in x.get('materials','')]
    return {'items': rows}

@app.get('/api/campaigns')
def list_campaigns():
    return {'items': load_db().get('campaigns', [])}

@app.post('/api/campaigns/{campaign_id}/join')
def join_campaign(campaign_id: str, request: Request):
    u = current_user(request)
    db = load_db()
    target = next((x for x in db.get('campaigns', []) if x.get('id') == campaign_id), None)
    if not target:
        raise HTTPException(404, '캠페인을 찾을 수 없습니다.')
    entry = {'id': now_id('join'), 'campaign_id': campaign_id, 'user': u['id'], 'displayName': u.get('displayName'), 'created_at': time.time()}
    db.setdefault('campaign_joins', []).append(entry)
    save_db(db)
    audit('campaign_join', u['id'], {'campaign_id': campaign_id})
    return {'ok': True, 'message': '캠페인 참여가 접수되었습니다.', 'entry': entry}

# ----------------- protected forms -----------------
@app.get('/api/protected/forms')
def list_forms(request: Request):
    u = current_user(request)
    items = []
    for fid, info in FORM_ACCESS.items():
        permitted = True
        reason = '사용 가능'
        try:
            allowed_form(u, fid)
        except HTTPException as e:
            permitted = False
            reason = str(e.detail)
        items.append({**info, 'id': fid, 'permitted': permitted, 'reason': reason})
    return {'user': u, 'items': items}

@app.get('/api/protected/forms/{form_id}')
def download_form(form_id: str, request: Request):
    u = current_user(request)
    info = allowed_form(u, form_id)
    file_path = PROTECTED / info['file']
    if not file_path.exists():
        raise HTTPException(404, '보호자료 파일이 서버에 없습니다.')
    audit('protected_form_download', u['id'], {'form_id': form_id})
    return FileResponse(file_path, media_type=mimetypes.guess_type(str(file_path))[0] or 'application/pdf', filename=info['file'])

# ----------------- admin endpoints -----------------
@app.get('/api/admin/overview')
def admin_overview(request: Request):
    require_admin(request)
    db = load_db()
    users = list(db.get('users', {}).values())
    return {
        'users_total': len(users),
        'pending_users': sum(1 for u in users if u.get('status') != 'approved'),
        'inquiries_open': sum(1 for x in db.get('inquiries', []) if x.get('status') != 'answered'),
        'orders_total': len(db.get('orders', [])),
        'partners_active': len(db.get('partners', [])),
        'forms_protected': len(FORM_ACCESS),
        'api_configured': sum(1 for v in API_MAP.values() if get_config_value(v)),
    }

@app.get('/api/admin/users')
def admin_users(request: Request):
    require_admin(request)
    return {'items': [user_public(u) for u in load_db().get('users', {}).values()]}

@app.patch('/api/admin/users/{user_id}')
def admin_patch_user(user_id: str, data: UserPatch, request: Request):
    admin = require_admin(request)
    db = load_db()
    user = db.get('users', {}).get(user_id)
    if not user:
        raise HTTPException(404, '사용자를 찾을 수 없습니다.')
    for k, v in data.model_dump(exclude_none=True).items():
        user[k] = v
    save_db(db)
    audit('admin_user_patch', admin['id'], {'target': user_id, 'fields': data.model_dump(exclude_none=True)})
    return user_public(user)

@app.get('/api/admin/inquiries')
def admin_inquiries(request: Request):
    require_admin(request)
    return {'items': load_db().get('inquiries', [])}

@app.post('/api/admin/inquiries/{inquiry_id}/answer')
def admin_answer_inquiry(inquiry_id: str, data: InquiryAnswer, request: Request):
    admin = require_admin(request)
    db = load_db()
    for item in db.get('inquiries', []):
        if item['id'] == inquiry_id:
            item['answer'] = data.answer
            item['status'] = 'answered'
            item['answered_at'] = time.time()
            save_db(db)
            audit('inquiry_answered', admin['id'], {'id': inquiry_id})
            return item
    raise HTTPException(404, '문의를 찾을 수 없습니다.')

@app.get('/api/admin/price-rules')
def admin_price_rules(request: Request):
    require_admin(request)
    return {'items': load_db().get('price_rules', {})}

@app.patch('/api/admin/price-rules/{rule_id}')
def admin_update_price_rule(rule_id: str, data: PriceRuleUpdate, request: Request):
    admin = require_admin(request)
    db = load_db()
    rule = db.setdefault('price_rules', {}).setdefault(rule_id, {})
    for k, v in data.model_dump(exclude_none=True).items():
        rule[k] = v
    save_db(db)
    audit('price_rule_update', admin['id'], {'rule_id': rule_id, 'fields': data.model_dump(exclude_none=True)})
    return rule

@app.post('/api/admin/price/simulate')
def price_simulate(data: PriceSim, request: Request):
    admin = require_admin(request)
    result = calculate_price(data)
    audit('price_simulate', admin['id'], {'input': data.model_dump(), 'result': result})
    return result

@app.get('/api/admin/api-status')
def api_status(request: Request):
    require_admin(request)
    vault = load_api_vault()
    services = {}
    for name, env in API_MAP.items():
        raw = os.getenv(env)
        val = raw or vault.get(env)
        services[name] = {
            'configured': bool(val),
            'mode': 'real-ready' if val else 'safe-mock',
            'env': env,
            'source': 'render-env' if raw else ('admin-vault' if vault.get(env) else 'missing'),
            'masked': mask_secret(val),
        }
    return {'services': services, 'message': 'Render 환경변수 또는 관리자 API 저장소에 키가 있으면 real-ready로 전환됩니다. 원문 키는 프론트에 노출하지 않습니다.'}

@app.get('/api/admin/api-config')
def admin_api_config(request: Request):
    return api_status(request)

@app.post('/api/admin/api-config')
def admin_save_api_config(data: ApiKeyUpdate, request: Request):
    admin = require_admin(request)
    env = data.env.strip()
    if env not in allowed_api_envs():
        raise HTTPException(400, '허용되지 않은 API 환경변수입니다.')
    vault = load_api_vault()
    if data.value.strip():
        vault[env] = data.value.strip()
        message = f'{env} 저장 완료: 즉시 real-ready 상태로 반영됩니다.'
        action = 'api_key_saved'
    else:
        vault.pop(env, None)
        message = f'{env} 관리자 저장값 삭제 완료. Render 환경변수가 있으면 계속 적용됩니다.'
        action = 'api_key_deleted'
    save_api_vault(vault)
    audit(action, admin['id'], {'env': env, 'source': 'admin-vault'})
    return {'ok': True, 'env': env, 'configured': bool(get_config_value(env)), 'masked': mask_secret(get_config_value(env)), 'message': message}

@app.get('/api/admin/audit')
def admin_audit(request: Request, limit: int = 100):
    require_admin(request)
    lines = []
    if AUDIT_LOG.exists():
        lines = AUDIT_LOG.read_text(encoding='utf-8').splitlines()[-limit:]
    return {'items': [json.loads(x) for x in lines if x.strip()]}

@app.get('/api/notices')
def public_notices(limit: int = 50):
    db = load_db()
    items = db.get('notices', [])[:max(1, min(limit, 100))]
    return {'items': items, 'version': APP_VERSION}

@app.post('/api/admin/notices')
def admin_create_notice(data: NoticeCreate, request: Request):
    admin = require_admin(request)
    db = load_db()
    item = data.model_dump()
    item.update({
        'id': now_id('notice'),
        'date': data.date or datetime.now().strftime('%Y-%m-%d'),
        'file': data.file or '공지',
        'url': data.url or '',
    })
    db.setdefault('notices', []).insert(0, item)
    save_db(db)
    audit('notice_create', admin['id'], {'id': item['id']})
    return item

@app.post('/api/admin/campaigns')
def admin_create_campaign(data: CampaignCreate, request: Request):
    admin = require_admin(request)
    db = load_db()
    item = data.model_dump()
    item.update({'id': now_id('camp')})
    db.setdefault('campaigns', []).insert(0, item)
    save_db(db)
    audit('campaign_create', admin['id'], {'id': item['id']})
    return item


@app.get('/api/admin/review-queue')
def admin_review_queue(request: Request):
    require_admin(request)
    db = load_db()
    items = [user_public(u) for u in db.get('users', {}).values() if u.get('status') != 'approved']
    return {'items': items, 'required_documents_by_role': {r: required_documents_for_role(r) for r in ['personal','partner','agency','enterprise']}}

@app.post('/api/admin/users/{user_id}/decision')
def admin_user_decision(user_id: str, data: AdminDecision, request: Request):
    admin = require_admin(request)
    db = load_db()
    user = db.get('users', {}).get(user_id)
    if not user:
        raise HTTPException(404, '사용자를 찾을 수 없습니다.')
    if data.decision == 'approve':
        user['status'] = 'approved'
        if user.get('role') in ['partner', 'agency', 'enterprise'] and user.get('plan') == 'Free':
            user['memo'] = (user.get('memo','') + ' / 승인완료: 요금제 선택 필요').strip(' /')
    elif data.decision == 'reject':
        user['status'] = 'rejected'
    else:
        user['status'] = 'hold'
    if data.memo:
        user['memo'] = data.memo
    save_db(db)
    audit('admin_user_decision', admin['id'], {'target': user_id, 'decision': data.decision})
    return user_public(user)

@app.get('/api/admin/pickups')
def admin_pickups(request: Request):
    require_admin(request)
    return {'items': load_db().get('pickup_requests', [])}

@app.patch('/api/admin/pickups/{pickup_id}')
def admin_patch_pickup(pickup_id: str, data: PickupStatusPatch, request: Request):
    admin = require_admin(request)
    db = load_db()
    for row in db.get('pickup_requests', []):
        if row.get('id') == pickup_id:
            row['status'] = data.status
            row['partner_id'] = data.partner_id or row.get('partner_id')
            row['admin_memo'] = data.memo or row.get('admin_memo','')
            row['updated_at'] = time.time()
            save_db(db)
            audit('admin_pickup_patch', admin['id'], {'pickup_id': pickup_id, 'status': data.status})
            return row
    raise HTTPException(404, '수거신청을 찾을 수 없습니다.')

@app.patch('/api/admin/bidrooms/{bid_id}')
def admin_patch_bidroom(bid_id: str, data: BidroomPatch, request: Request):
    admin = require_admin(request)
    db = load_db()
    for row in db.setdefault('bidrooms', []):
        if row.get('id') == bid_id:
            for k, v in data.model_dump(exclude_none=True).items():
                row[k] = v
            row['updated_at'] = time.time()
            save_db(db)
            audit('admin_bidroom_patch', admin['id'], {'bid_id': bid_id})
            return row
    raise HTTPException(404, '입찰방을 찾을 수 없습니다.')

@app.delete('/api/admin/bidrooms/{bid_id}')
def admin_delete_bidroom(bid_id: str, request: Request):
    admin = require_admin(request)
    db = load_db()
    before = len(db.setdefault('bidrooms', []))
    db['bidrooms'] = [x for x in db['bidrooms'] if x.get('id') != bid_id]
    if len(db['bidrooms']) == before:
        raise HTTPException(404, '입찰방을 찾을 수 없습니다.')
    save_db(db)
    audit('admin_bidroom_delete', admin['id'], {'bid_id': bid_id})
    return {'ok': True}

@app.patch('/api/admin/disposal/items/{item_id}')
def admin_patch_disposal_item(item_id: str, data: DisposalPatch, request: Request):
    admin = require_admin(request)
    path = STATIC / 'data' / 'disposal_items.json'
    items = disposal_catalog()
    for row in items:
        if row.get('id') == item_id:
            for k, v in data.model_dump(exclude_none=True).items():
                row[k] = v
            if data.minWeightKg is not None or data.minValueKrw is not None or data.countThreshold is not None:
                row['pickupRule'] = f"예상 무게 {row.get('minWeightKg',20)}kg 이상 또는 예상 매입가치 {int(row.get('minValueKrw',10000)):,}원 이상 또는 동일·유사 품목 {row.get('countThreshold',5)}개 이상"
            path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
            audit('admin_disposal_patch', admin['id'], {'item_id': item_id})
            return row
    raise HTTPException(404, '품목을 찾을 수 없습니다.')

@app.get('/api/admin/settlement/summary')
def admin_settlement_summary(request: Request):
    require_admin(request)
    db = load_db()
    orders = db.get('orders', [])
    pickups = db.get('pickup_requests', [])
    return {
        'prepared_payments': len([x for x in orders if x.get('status') == 'prepared']),
        'estimated_subscription_revenue': sum(int(x.get('amount') or 0) for x in orders),
        'pickup_requests_total': len(pickups),
        'instant_matching': sum(1 for x in pickups if x.get('status') == 'instant_matching'),
        'bundle_waiting': sum(1 for x in pickups if x.get('status') == 'bundle_waiting'),
        'note': '실제 정산은 PG 웹훅 검증·세금계산서·수수료 규칙 연결 후 확정합니다.'
    }

@app.post('/api/admin/api-test')
def admin_api_test(data: ApiConfigTest, request: Request):
    require_admin(request)
    env = API_MAP.get(data.service)
    if not env:
        raise HTTPException(404, '등록되지 않은 API 서비스입니다.')
    raw = os.getenv(env)
    val = get_config_value(env)
    configured = bool(val)
    source = 'render-env' if raw else ('admin-vault' if load_api_vault().get(env) else 'missing')
    return {'service': data.service, 'env': env, 'configured': configured, 'source': source, 'mode': 'real-ready' if configured else 'safe-mock', 'result': '키 설정 확인 완료. 실제 호출은 해당 기능 실행 시 수행됩니다.' if configured else '키 미설정: 데모모드로 동작'}

@app.get('/api/admin/export/operations')
def admin_export_operations(request: Request):
    require_admin(request)
    db = load_db()
    return {
        'generated_at': time.time(),
        'users': [user_public(u) for u in db.get('users', {}).values()],
        'pickup_requests': db.get('pickup_requests', []),
        'bidrooms': db.get('bidrooms', []),
        'inquiries': db.get('inquiries', []),
        'campaigns': db.get('campaigns', []),
        'notices': db.get('notices', []),
        'price_rules': db.get('price_rules', {}),
    }

@app.get('/api/admin/compliance-checklist')
def compliance_checklist(request: Request):
    require_admin(request)
    return {
        'items': [
            {'area': '개인정보', 'check': '개인정보 처리방침, 처리위탁, 보유기간, 파기절차, 권리행사 절차 확인', 'status': '운영 전 최종 검토 필요'},
            {'area': '전자상거래', 'check': '환불정책, 청약철회 제한, 디지털 보호자료 다운로드 제한 조건 표시', 'status': '초안 반영'},
            {'area': '온비드', 'check': '공식 입찰 제출·보증금 납부·개찰·낙찰 대행 표현 금지', 'status': '반영'},
            {'area': '폐기물', 'check': '수집·운반·처리 허가 및 건설폐기물/지정폐기물 여부 확인', 'status': '업체 심사 필요'},
            {'area': '보안', 'check': '관리자 비밀번호 변경, SECRET_KEY 교체, HTTPS, 백업, 감사로그 확인', 'status': '출시 전 필수'},
        ]
    }



# ----------------- v37 final business operating layer -----------------
class ProposalCreate(BaseModel):
    bidroom_id: Optional[str] = None
    title: str = '작업 제안서'
    price: int = 0
    schedule: str = ''
    vehicle: str = ''
    method: str = ''
    safety_plan: str = ''
    data_security: str = ''
    recycle_plan: str = ''
    attachments: List[str] = Field(default_factory=list)
    memo: str = ''

class ProposalDecision(BaseModel):
    status: str = Field(pattern='^(submitted|shortlisted|selected|rejected|hold)$')
    memo: Optional[str] = None

class DispatchRecommendRequest(BaseModel):
    pickup_id: Optional[str] = None
    region: Optional[str] = None
    item: Optional[str] = None
    weight: float = 0
    value: float = 0
    count: int = 0
    mode: str = 'balanced'

class OperationMemo(BaseModel):
    target_type: str
    target_id: str
    memo: str

class DisposalFeedback(BaseModel):
    item_id: Optional[str] = None
    item_name: Optional[str] = None
    feedback_type: str = '수정요청'
    body: str
    photo_filename: Optional[str] = None


def final_seed_db(db: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the demo database business-operable even after upgrades."""
    db.setdefault('pickup_requests', [])
    if not db['pickup_requests']:
        db['pickup_requests'] = [
            {'id':'pickup-demo-1','user':'personal','item':'컴퓨터 본체','material':'폐가전·전산장비','weight':23,'value':35000,'count':3,'bulky':False,'address':'광주 서구 치평동','preferred_date':'이번 주 금요일 오후','memo':'하드디스크 제거 필요','status':'admin_review','partner_id':'','created_at':time.time()-86400},
            {'id':'pickup-demo-2','user':'personal','item':'택배박스','material':'종이·박스','weight':38,'value':9000,'count':45,'bulky':False,'address':'광주 북구 용봉동','preferred_date':'다음 주 월요일 오전','memo':'지하주차장 보관','status':'instant_matching','partner_id':'','created_at':time.time()-3600},
        ]
    db.setdefault('bidrooms', [])
    if not db['bidrooms']:
        db['bidrooms'] = [
            {'id':'bid-demo-1','owner':'agency','owner_role':'agency','title':'○○학교 불용 책걸상 반출·재활용 작업','type':'기관 온비드 전후업무 참여방','region':'광주 서구','items':'책상 120개, 의자 240개, 철제 캐비닛 12개','volume':'약 9.2톤 / 2일 작업','deadline':'____년 __월 __일','body':'공식 매각·입찰은 온비드에서 진행하고, 자원잇다는 현장확인·반출작업·성과보고 전후업무를 관리합니다.','visibility':'plan-gated','status':'open','created_at':time.time()-172800},
            {'id':'bid-demo-2','owner':'samsung','owner_role':'enterprise','title':'사업장 월간 폐플라스틱·폐지 정기수거 작업','type':'기업 정기수거 작업입찰','region':'수원·화성','items':'PP 박스, PET 포장재, 택배박스, 파렛트 랩','volume':'월 15~25톤','deadline':'____년 __월 __일','body':'월별 물량 변동에 따른 단가표, 차량투입 계획, ESG 성과자료 제공 가능 업체 제안 요청.','visibility':'plan-gated','status':'open','created_at':time.time()-43200},
        ]
    db.setdefault('proposals', [])
    if not db['proposals']:
        db['proposals'] = [
            {'id':'prop-demo-1','bidroom_id':'bid-demo-1','partner_id':'partner','partner_name':'광주그린자원님','title':'책걸상 반출·분류·재활용 제안','price':1280000,'schedule':'현장확인 1일 + 반출 2일','vehicle':'2.5톤 1대, 1톤 2대','method':'층별 집하 후 철재/목재/플라스틱 분리, 재사용 가능품 선별','safety_plan':'작업구역 라바콘·안전장갑·운반동선 분리','data_security':'저장매체 없음 확인, 발견 시 즉시 관리자 보고','recycle_plan':'철재 고철, 목재 재사용/연료화 가능성 검토, 플라스틱 선별','memo':'학교 방학 기간 작업 권장','status':'submitted','score':86,'created_at':time.time()-7200},
        ]
    db.setdefault('operation_memos', [])
    db.setdefault('dispatches', [])
    db.setdefault('disposal_feedback', [])
    return db


def load_operating_db() -> Dict[str, Any]:
    db = load_db()
    db = final_seed_db(db)
    save_db(db)
    return db


def proposal_score(row: Dict[str, Any]) -> int:
    score = 40
    if row.get('price', 0) > 0: score += 10
    if row.get('schedule'): score += 8
    if row.get('vehicle'): score += 8
    if len(row.get('method','')) > 20: score += 10
    if len(row.get('safety_plan','')) > 10: score += 8
    if len(row.get('data_security','')) > 8: score += 8
    if len(row.get('recycle_plan','')) > 10: score += 8
    return min(score, 100)


def recommend_partner_for(region: str = '', item: str = '', mode: str = 'balanced') -> Dict[str, Any]:
    db = load_operating_db()
    partners = db.get('partners', [])
    scored = []
    r = (region or '').replace(' ', '')
    i = (item or '').replace(' ', '')
    for ptn in partners:
        score = int(ptn.get('score', 70))
        if r and any(part.replace(' ', '') in r or r in part.replace(' ', '') for part in [ptn.get('region','')]): score += 12
        if i and i in (ptn.get('materials','').replace(' ', '')): score += 10
        if ptn.get('plan') in ['Gold','Plus']: score += 6
        if mode == 'profit': score += 3 if '고철' in ptn.get('materials','') or '전산' in ptn.get('materials','') else 0
        if mode == 'speed': score += 3 if '38' in str(ptn.get('eta','')) else 0
        scored.append({**ptn, 'dispatch_score': min(score, 100), 'reason': '지역·품목·신뢰점수·요금제·평균응답시간 기준 자동 추천'})
    scored.sort(key=lambda x: x['dispatch_score'], reverse=True)
    return {'mode': mode, 'recommended': scored[0] if scored else None, 'candidates': scored[:5]}


@app.get('/api/admin/command-center')
def admin_command_center(request: Request):
    require_admin(request)
    db = load_operating_db()
    users = list(db.get('users', {}).values())
    pickups = db.get('pickup_requests', [])
    bidrooms = db.get('bidrooms', [])
    proposals = db.get('proposals', [])
    inquiries = db.get('inquiries', [])
    api_services = {k: bool(os.getenv(v)) for k, v in API_MAP.items()}
    stages = {
        '회원심사대기': sum(1 for u in users if u.get('status') != 'approved'),
        '즉시수거매칭': sum(1 for p in pickups if p.get('status') == 'instant_matching'),
        '관리자검토수거': sum(1 for p in pickups if p.get('status') in ['admin_review','bundle_waiting']),
        '진행입찰방': sum(1 for b in bidrooms if b.get('status') == 'open'),
        '제안서접수': sum(1 for p in proposals if p.get('status') == 'submitted'),
        '미답변문의': sum(1 for q in inquiries if q.get('status') != 'answered'),
    }
    recommended_actions = []
    if stages['회원심사대기']:
        recommended_actions.append('심사대기 회원의 증빙자료를 확인하고 승인·보류·반려 처리')
    if stages['관리자검토수거']:
        recommended_actions.append('관리자 검토 수거건은 위험품·저장매체·대형폐기물 여부 확인 후 배차')
    if stages['제안서접수']:
        recommended_actions.append('입찰방 제안서는 가격·일정·안전·보안·재활용계획 기준으로 평가')
    if not all(api_services.values()):
        recommended_actions.append('Render 환경변수에 미설정 API 키 입력 후 실연동 전환')
    return {
        'kpi': {
            '전체회원': len(users),
            '승인회원': sum(1 for u in users if u.get('status') == 'approved'),
            '수거신청': len(pickups),
            '입찰방': len(bidrooms),
            '제안서': len(proposals),
            '문의': len(inquiries),
            'API실연동': sum(1 for v in api_services.values() if v),
            'API전체': len(api_services),
        },
        'stages': stages,
        'recent_pickups': pickups[-8:][::-1],
        'recent_bidrooms': bidrooms[-8:][::-1],
        'recent_proposals': proposals[-8:][::-1],
        'recommended_actions': recommended_actions,
        'business_status': 'demo-operable' if not all(api_services.values()) else 'api-connected',
    }


@app.get('/api/operations/workflow-map')
def workflow_map():
    return {
        'personal_flow': ['품목 검색/사진촬영', '배출 안내표 확인', '무게·가치·수량 기준 판정', '즉시수거/묶음수거/캠페인/관리자검토', '배차', '수거완료', '정산·성과기록'],
        'agency_enterprise_flow': ['회원가입·증빙심사', '입찰방/서류작성', '자료 업로드', '업체 제안 접수', '제안 비교·선정', '작업관리', '성과보고'],
        'partner_flow': ['업체가입·허가자료 심사', '요금제 선택', '입찰방 열람', '제안서 제출', '작업배정', '수거/반출', '정산·평가'],
        'admin_flow': ['회원심사', '배출표·단가관리', '입찰방 관리', '제안서 평가', '배차추천', '문의답변', 'API상태·감사로그·정산관리'],
    }


@app.post('/api/pickup/photo-guide')
async def pickup_photo_guide(request: Request, photo: UploadFile = File(...)):
    u = current_user(request)
    ext = Path(photo.filename or '').suffix.lower()
    if ext not in {'.jpg','.jpeg','.png','.webp'}:
        raise HTTPException(400, '사진 파일만 업로드할 수 있습니다.')
    content = await photo.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f'파일은 {MAX_UPLOAD_MB}MB 이하만 업로드할 수 있습니다.')
    name = f"{int(time.time())}_{safe_filename(photo.filename or 'photo.jpg')}"
    dest = UPLOADS / name
    dest.write_bytes(content)

    inference = v505_infer_photo_item(photo.filename or name, dest)
    data = DisposalGuideRequest(item=inference.get('item') or None, photo_filename=photo.filename or name)
    guide = v505_guide_from_inference(inference, data)
    audit('pickup_photo_guide', u['id'], {'file': name, 'inferred': inference.get('item'), 'confidence': inference.get('confidence'), 'reason': inference.get('reason')})
    return {
        'ok': True,
        'file': name,
        'guide': guide,
        'mode': 'safe-mock-plus' if not get_config_value('VISION_API_KEY') else 'real-ready',
        'message': '확신이 낮은 사진은 잘못된 품목으로 확정하지 않고 관리자 검토로 보냅니다.'
    }



@app.post('/api/bidrooms/{bid_id}/proposals')
def create_proposal(bid_id: str, data: ProposalCreate, request: Request):
    u = current_user(request)
    if u['role'] not in ['partner', 'admin']:
        raise HTTPException(403, '업체 회원만 제안서를 제출할 수 있습니다.')
    if u['role'] != 'admin' and (u.get('status') != 'approved' or PLAN_RANK.get(u.get('plan','Free'),0) < PLAN_RANK['Basic']):
        raise HTTPException(403, '승인된 Basic 이상 업체만 제안서를 제출할 수 있습니다.')
    db = load_operating_db()
    bid = next((b for b in db.get('bidrooms', []) if b.get('id') == bid_id), None)
    if not bid:
        raise HTTPException(404, '입찰방을 찾을 수 없습니다.')
    row = data.model_dump()
    row.update({'id': now_id('prop'), 'bidroom_id': bid_id, 'partner_id': u['id'], 'partner_name': u.get('displayName', u.get('name')), 'status': 'submitted', 'created_at': time.time()})
    row['score'] = proposal_score(row)
    db.setdefault('proposals', []).append(row)
    save_db(db)
    audit('proposal_create', u['id'], {'bidroom_id': bid_id, 'proposal_id': row['id'], 'score': row['score']})
    return {'ok': True, 'proposal': row, 'message': '제안서가 접수되었습니다. 관리자가 가격·일정·안전·보안·재활용계획 기준으로 검토합니다.'}


@app.get('/api/bidrooms/{bid_id}/proposals')
def list_proposals(bid_id: str, request: Request):
    u = current_user(request)
    if u['role'] not in ['partner', 'agency', 'enterprise', 'admin']:
        raise HTTPException(403, '입찰방 제안서 접근 권한이 없습니다.')
    db = load_operating_db()
    bid = next((b for b in db.get('bidrooms', []) if b.get('id') == bid_id), None)
    if not bid:
        raise HTTPException(404, '입찰방을 찾을 수 없습니다.')
    rows = [p for p in db.get('proposals', []) if p.get('bidroom_id') == bid_id]
    if u['role'] == 'partner':
        rows = [p for p in rows if p.get('partner_id') == u['id']]
    return {'bidroom': bid, 'items': sorted(rows, key=lambda x: x.get('score',0), reverse=True)}


@app.patch('/api/admin/proposals/{proposal_id}')
def admin_patch_proposal(proposal_id: str, data: ProposalDecision, request: Request):
    admin = require_admin(request)
    db = load_operating_db()
    for row in db.get('proposals', []):
        if row.get('id') == proposal_id:
            row['status'] = data.status
            row['admin_memo'] = data.memo or row.get('admin_memo','')
            row['updated_at'] = time.time()
            save_db(db)
            audit('proposal_decision', admin['id'], {'proposal_id': proposal_id, 'status': data.status})
            return row
    raise HTTPException(404, '제안서를 찾을 수 없습니다.')


@app.post('/api/admin/dispatch/recommend')
def admin_dispatch_recommend(data: DispatchRecommendRequest, request: Request):
    require_admin(request)
    db = load_operating_db()
    pickup = None
    if data.pickup_id:
        pickup = next((p for p in db.get('pickup_requests', []) if p.get('id') == data.pickup_id), None)
        if not pickup:
            raise HTTPException(404, '수거신청을 찾을 수 없습니다.')
    region = data.region or (pickup or {}).get('address','')
    item = data.item or (pickup or {}).get('item','')
    rec = recommend_partner_for(region, item, data.mode)
    if pickup and rec.get('recommended'):
        row = {'id': now_id('dispatch'), 'pickup_id': pickup['id'], 'partner_id': rec['recommended']['id'], 'partner_name': rec['recommended']['name'], 'score': rec['recommended']['dispatch_score'], 'status': 'recommended', 'created_at': time.time()}
        db.setdefault('dispatches', []).append(row)
        save_db(db)
        rec['dispatch_record'] = row
    return rec


@app.post('/api/operations/memo')
def operation_memo(data: OperationMemo, request: Request):
    u = current_user(request)
    if u['role'] not in ['admin','agency','enterprise','partner']:
        raise HTTPException(403, '업무 메모 권한이 없습니다.')
    db = load_operating_db()
    row = data.model_dump()
    row.update({'id': now_id('memo'), 'actor': u['id'], 'created_at': time.time()})
    db.setdefault('operation_memos', []).append(row)
    save_db(db)
    audit('operation_memo', u['id'], {'target_type': data.target_type, 'target_id': data.target_id})
    return row


@app.post('/api/disposal/feedback')
def disposal_feedback(data: DisposalFeedback, request: Request):
    u = current_user(request)
    db = load_operating_db()
    row = data.model_dump()
    row.update({'id': now_id('fb'), 'user': u['id'], 'status': 'received', 'created_at': time.time()})
    db.setdefault('disposal_feedback', []).append(row)
    save_db(db)
    audit('disposal_feedback', u['id'], {'id': row['id']})
    return {'ok': True, 'feedback': row, 'message': '배출 안내표 수정요청이 접수되었습니다. 관리자가 검토 후 반영합니다.'}


@app.get('/api/admin/final-readiness')
def final_readiness(request: Request):
    require_admin(request)
    db = load_operating_db()
    checks = [
        {'area':'SECRET_KEY', 'ok': SECRET_KEY != 'CHANGE_ME_BEFORE_LAUNCH', 'action':'Render 환경변수 SECRET_KEY를 강한 랜덤값으로 교체'},
        {'area':'관리자 비밀번호', 'ok': True, 'action':'첫 배포 후 관리자 비밀번호 즉시 변경'},
        {'area':'API 키', 'ok': any(get_config_value(v) for v in API_MAP.values()), 'action':'OpenAI/OCR/지도/결제/문자 API 키를 Render 환경변수에 입력'},
        {'area':'회원심사', 'ok': len([u for u in db.get('users',{}).values() if u.get('status')!='approved']) == 0, 'action':'업체·기관·기업 증빙자료 심사 처리'},
        {'area':'보호자료', 'ok': all((PROTECTED / info['file']).exists() for info in FORM_ACCESS.values()), 'action':'1~98번 보호서류 누락 확인'},
        {'area':'배출안내표', 'ok': len(disposal_catalog()) >= 1000, 'action':'1,000개 품목 유지 및 지역별 기준 검토'},
        {'area':'법률/허가', 'ok': False, 'action':'폐기물 수집·운반·처리 허가, 개인정보 파기, 전자상거래 고지는 실제 사업 전 전문가 검토'},
    ]
    return {'ready_score': round(sum(1 for c in checks if c['ok']) / len(checks) * 100), 'checks': checks, 'note':'코드와 운영흐름은 사업화 시연 가능 수준이며, 실제 영업 전 허가·법률·PG 심사·개인정보 위탁계약은 별도 완료해야 합니다.'}



# ----------------- v38 true final release endpoints -----------------
def core_counts() -> Dict[str, Any]:
    db = load_operating_db()
    return {
        'users': len(db.get('users', {})),
        'pending_reviews': len([u for u in db.get('users', {}).values() if u.get('status') == 'pending_review']),
        'pickup_requests': len(db.get('pickup_requests', [])),
        'bidrooms': len(db.get('bidrooms', [])),
        'proposals': len(db.get('proposals', [])),
        'dispatches': len(db.get('dispatches', [])),
        'inquiries': len(db.get('inquiries', [])),
        'disposal_items': len(disposal_catalog()),
        'protected_form_sets': sum(1 for info in FORM_ACCESS.values() if (PROTECTED / info['file']).exists()),
        'price_rules': len(db.get('price_rules', {})),
    }

@app.get('/api/final/system-check')
def final_system_check():
    counts = core_counts()
    required_static = [
        STATIC / 'index.html', STATIC / 'pickup.html', STATIC / 'bidrooms.html',
        STATIC / 'dashboards' / 'admin.html', STATIC / 'data' / 'disposal_items.json',
        STATIC / 'js' / 'app.js', STATIC / 'css' / 'styles.css'
    ]
    env_required_for_real = ['SECRET_KEY', 'OPENAI_API_KEY', 'OCR_API_KEY', 'VISION_API_KEY', 'KAKAO_REST_API_KEY', 'TOSS_SECRET_KEY', 'SOLAPI_API_KEY']
    return {
        'ok': True,
        'version': APP_VERSION,
        'release_name': '자원잇다 v47 RESOURCE RECOVERY FULL MODEL',
        'mode': 'real-ready' if any(get_config_value(k) for k in env_required_for_real[1:]) else 'safe-mock',
        'counts': counts,
        'static_files_ok': all(p.exists() for p in required_static),
        'protected_forms_ok': counts['protected_form_sets'] == len(FORM_ACCESS),
        'disposal_catalog_ok': counts['disposal_items'] >= 1000,
        'env_status': {k: bool(get_config_value(k)) and get_config_value(k) not in ['change-this-before-production','CHANGE_ME_BEFORE_LAUNCH'] for k in env_required_for_real},
        'business_scope': {
            'personal_pickup': '사진 또는 품목명으로 배출 안내표를 조회하고 즉시수거/묶음수거/캠페인/관리자검토로 분기합니다.',
            'agency_enterprise_bidroom': '기관·기업은 내부 작업입찰방과 온비드 전후업무 참여방을 생성합니다.',
            'partner_proposal': '업체는 승인·플랜 조건에 따라 제안서를 제출하고 자동 점수화됩니다.',
            'admin_control': '관리자는 회원심사, 품목기준, 수거배차, 입찰방, 제안서, 정산, 문의, API 상태를 통합 관리합니다.',
            'onbid_boundary': '공식 온비드 입찰 제출·보증금·개찰·낙찰·계약 체결은 자원잇다 대행 범위가 아닙니다.'
        },
        'final_notice': '배포 가능한 최종 코드 구조입니다. 실제 영업 전 폐기물 관련 허가, 개인정보 파기 계약, PG 심사, 약관·환불정책 법무 검토는 별도 완료해야 합니다.'
    }

@app.get('/api/final/user-journeys')
def final_user_journeys():
    return {
        'personal': [
            '회원가입/로그인', '품목 검색 또는 사진 업로드', '1,000개 배출 안내표 자동 매칭',
            '배출방법·금지사항·포장방법·사진기준 확인', '무게·가치·수량·대형품 기준 입력',
            '즉시수거/묶음수거/캠페인/관리자검토 자동 분기', '관리자 또는 업체 배차', '수거완료 및 정산/성과 반영'
        ],
        'agency': [
            '기관 가입신청', '관리자 승인', '온비드 전후업무 참여방 생성', 'AI 서류 초안 생성',
            '보호자료 다운로드', '업체 제안 비교', '공식 온비드는 기관 담당자가 직접 진행', '사후관리·성과보고'
        ],
        'enterprise': [
            '기업 가입신청', '관리자 승인', '정기수거 작업입찰방 생성', '업체 제안서 접수',
            '가격·일정·안전·보안·재활용계획 비교', '수거/정산/ESG 성과 관리'
        ],
        'partner': [
            '업체 가입신청', '사업자/허가/차량/보험 검토', '입찰방 열람', '작업 제안서 제출',
            '선정 후 배차·작업·완료보고', '정산·신뢰점수 반영'
        ],
        'admin': [
            '최종 사업 관제판 확인', '회원심사/플랜관리', '배출표 1,000개 관리', '수거·배차 관리',
            '입찰방·제안서 평가', '단가·수익 계산', '문의답변', 'API 연동센터', '출시준비도 점검'
        ]
    }

@app.get('/api/admin/final-control-system')
def admin_final_control_system(request: Request):
    require_admin(request)
    db = load_operating_db()
    counts = core_counts()
    modules = [
        {'module':'회원·승인', 'path':'/api/admin/users', 'status':'active', 'detail':'개인 자동승인, 업체·기관·기업 심사대기, 승인/보류/반려 처리'},
        {'module':'배출 안내표 1,000개', 'path':'/api/disposal/items', 'status':'active', 'detail':'가정/아파트·상가/사업장/기관 처리방법, 사진기준, 즉시수거 기준, 관리자 검토 기준'},
        {'module':'개인 수거', 'path':'/api/pickup/submit', 'status':'active', 'detail':'즉시수거/묶음수거/캠페인/관리자검토 분기 및 관리자 상태 변경'},
        {'module':'입찰방', 'path':'/api/bidrooms', 'status':'active', 'detail':'기관 온비드 전후업무, 기업 정기수거, 내부 작업입찰방 생성·관리'},
        {'module':'업체 제안서', 'path':'/api/bidrooms/{bid_id}/proposals', 'status':'active', 'detail':'가격·일정·차량·안전·보안·재활용계획 자동 점수화'},
        {'module':'자동 배차', 'path':'/api/admin/dispatch/recommend', 'status':'active', 'detail':'지역·품목·업체점수·플랜 기반 후보 추천'},
        {'module':'단가·수익', 'path':'/api/admin/price/simulate', 'status':'active', 'detail':'시세·물류비·위험비·수수료 기반 추천 매입가와 예상이익 계산'},
        {'module':'보호자료', 'path':'/api/protected/forms', 'status':'active', 'detail':'1~98번 PDF 세트, 역할·플랜·승인상태 조건 다운로드'},
        {'module':'문의·공지·캠페인', 'path':'/api/admin/inquiries', 'status':'active', 'detail':'고객센터 문의답변, 공지자료, 캠페인 등록'},
        {'module':'API 연동센터', 'path':'/api/admin/api-status', 'status':'real-ready', 'detail':'OpenAI/OCR/Vision/지도/노선/결제/문자/사업자검증/S3 환경변수 연결'},
    ]
    risk_queue = []
    if SECRET_KEY in ['CHANGE_ME_BEFORE_LAUNCH', 'change-this-before-production']:
        risk_queue.append('SECRET_KEY를 Render 환경변수에서 강한 랜덤값으로 교체해야 합니다.')
    if counts['pending_reviews']:
        risk_queue.append(f"승인대기 회원 {counts['pending_reviews']}건을 심사해야 합니다.")
    if counts['protected_form_sets'] < len(FORM_ACCESS):
        risk_queue.append('보호자료 PDF 세트 일부가 누락되어 있습니다.')
    if counts['disposal_items'] < 1000:
        risk_queue.append('배출 안내표가 1,000개 미만입니다.')
    return {
        'release': 'v43 FINAL MOBILE BUSINESS READY',
        'counts': counts,
        'modules': modules,
        'risk_queue': risk_queue or ['코드상 필수 구조는 준비되었습니다. 실제 영업 전 허가·법률·PG·개인정보 위탁계약을 완료하세요.'],
        'recommended_next_actions': [
            'GitHub Private 저장소에 업로드', 'Render Web Service로 배포', 'SECRET_KEY/PASSWORD_SALT 교체',
            '관리자 비밀번호 변경', '실제 API 키 입력', 'PG·문자·지도 테스트 결제/발송', '폐기물 허가·개인정보 파기 계약 확인'
        ],
        'sample_business_numbers': {
            'personal_pickup_min_weight_kg': 20,
            'personal_pickup_min_value_krw': 10000,
            'partner_basic_plan_krw': 30000,
            'partner_standard_plan_krw': 100000,
            'partner_plus_plan_krw': 200000,
            'partner_gold_plan_krw': 300000,
        }
    }

@app.get('/api/admin/disposal/export.csv')
def admin_disposal_export_csv(request: Request):
    require_admin(request)
    rows = disposal_catalog()
    headers = ['id','name','category','material','disposalChannel','householdMethod','apartmentMethod','businessMethod','agencyMethod','pickupRule','caution','adminCheck','localDifference']
    lines = [','.join(headers)]
    def esc(v: Any) -> str:
        text = str(v if v is not None else '').replace('"','""').replace('\n',' ')
        return f'"{text}"'
    for r in rows:
        lines.append(','.join(esc(r.get(h,'')) for h in headers))
    csv = '\ufeff' + '\n'.join(lines)
    return Response(content=csv, media_type='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename="jawonitda_disposal_guide_v38.csv"'})



# ----------------- v47 full resource recovery operating model -----------------
class V47RecoveryAnalyze(BaseModel):
    source_type: str = 'personal'
    item: str = ''
    region: str = ''
    quantity: int = 1
    weight: float = 0
    expected_value: float = 0
    memo: Optional[str] = None
    has_storage: bool = False
    is_auto_part: bool = False
    is_collector_candidate: bool = False

class V47PartnerRegister(BaseModel):
    name: str
    partner_type: str
    region: str = '광주 전역'
    items: str = ''
    phone: Optional[str] = None
    license_memo: Optional[str] = None

class V47AutoProject(BaseModel):
    vehicle_price: float = 0
    transport_cost: float = 0
    admin_cost: float = 0
    dismantle_cost: float = 0
    reserve_cost: float = 0
    engine_value: float = 0
    transmission_value: float = 0
    catalyst_value: float = 0
    metal_value: float = 0
    parts_value: float = 0
    sale_fee_rate: float = 0.08

class V47EngineProject(BaseModel):
    core_price: float = 0
    disassembly_cost: float = 0
    parts_cost: float = 0
    assembly_cost: float = 0
    logistics_cost: float = 0
    sale_price: float = 0
    commission_rate: float = 0.12

class V47CollectorScreen(BaseModel):
    item: str = ''
    brand: Optional[str] = None
    condition: str = '상태 불명'
    estimated_price: float = 0
    memo: Optional[str] = None

class V47ApartmentCampaign(BaseModel):
    households: int = 0
    days: int = 7
    expected_items: int = 0
    campaign_fee: float = 0
    transaction_fee: float = 0
    report_fee: float = 0
    operating_cost: float = 0

V47_KEYWORDS = {
    'collector': ['레트로','게임기','닌텐도','플스','카메라','필름','오디오','LP','턴테이블','피규어','프라모델','한정판','만년필','우표','동전','기념주화','애플','빈티지','절판'],
    'auto': ['엔진','미션','촉매','휠','타이어','배터리','ECU','라이트','범퍼','문짝','터보','발전기','스타터','라디에이터','DPF','와이어','하네스','노후차','그랜저','제네시스','쏘렌토','싼타페'],
    'electronics': ['PC','컴퓨터','노트북','모니터','서버','프린터','복합기','휴대폰','태블릿','공유기','전자칠판','SSD','HDD'],
    'office': ['책상','의자','캐비닛','파티션','회의테이블','학원','병원','사무실','PC방'],
    'metal': ['전선','구리','알루미늄','고철','스테인리스','기판','PCB','모터'],
    'blocked': ['음식물','종량제','의료폐기물','주사기','석면','위험물','기름','오일','출처불명','도난']
}

def _has_any(text: str, keys: List[str]) -> bool:
    t = (text or '').lower()
    return any(k.lower() in t for k in keys)

def v47_analyze_logic(data: V47RecoveryAnalyze) -> Dict[str, Any]:
    text = ' '.join([data.item or '', data.memo or '', data.source_type or ''])
    flags: List[str] = []
    routes: List[str] = []
    partners: List[str] = []
    revenue: List[str] = []
    grade = 'C'
    summary = '원자재 또는 동별 묶음 입찰 대상으로 보입니다.'
    minimum = '혼합 물량 예상 가치 5만원 이상 또는 동별 묶음대기'
    if _has_any(text, V47_KEYWORDS['blocked']):
        grade = 'D'; summary = '거래 제한 또는 전문처리 검토 대상입니다.'
        routes = ['전문 허가업체 확인', '관리자 보류', '일반 입찰 금지']
        partners = ['전문처리 허가업체', '관리자 검토']
        flags += ['생활폐기물·위험물·의료폐기물·출처불명품은 자원잇다 일반 입찰 대상이 아닙니다.']
        revenue = ['전문처리 연결 수수료 가능하나 법률·허가 확인 우선']
        return {'grade':grade,'summary':summary,'routes':routes,'partner_targets':partners,'compliance_flags':flags,'minimum_bundle':minimum,'revenue_points':revenue,'next_action':'거래 보류 후 관리자와 허가업체가 처리 가능 범위를 확인'}
    if data.is_collector_candidate or _has_any(text, V47_KEYWORDS['collector']):
        grade = 'S'; summary = '수집가치 회생 후보입니다. 고철·폐기 전 전문 판매경로를 먼저 확인해야 합니다.'
        routes += ['수집가 입찰방', '전문점 위탁판매', '중고 플랫폼 판매대행']
        partners += ['수집품 전문점', '레트로/오디오/카메라 커뮤니티', '위탁판매 파트너']
        revenue += ['위탁판매 10~20%', '전문업체 연결 5~10%', '감별 리포트']
        minimum = '예상 판매가 3만원 이상이면 개별 검토'
    if data.is_auto_part or _has_any(text, V47_KEYWORDS['auto']):
        grade = 'S' if grade != 'D' else grade
        summary = '자동차 부품 또는 노후차 회생 후보입니다. 출처확인 후 전문 파트너 입찰이 필요합니다.'
        routes += ['자동차 부품 입찰', '엔진·미션 코어 입찰', '재제조업체 사전견적', '관허폐차장 연계']
        partners += ['정비소·공업사', '관허폐차장', '자동차해체재활용업체', '엔진·미션 재제조업체', '중고부품업체', '촉매·배터리 전문업체']
        flags += ['차량 직접 해체 금지', '말소 전 임의탈거 부품 거래 금지', '개인 촉매·출처불명 고가부품 거래 금지']
        revenue += ['거래액 3~7% 중개수수료', '재생엔진 위탁판매 8~15%', '노후차 프로젝트 순이익 배분']
        minimum = '자동차 부품 예상 회생가치 10만원 이상 또는 파트너 사전입찰 필요'
    if _has_any(text, V47_KEYWORDS['electronics']):
        if grade == 'C': grade = 'A'
        summary = '폐전자기기·전산장비 회생 후보입니다. 중고·부품·보안삭제·기판재활용 순서로 판단합니다.'
        routes += ['중고판매', '부품판매', '데이터삭제/파기증명', '기판·금속 재활용']
        partners += ['중고PC 업체', '컴퓨터 수리점', '데이터삭제 업체', '전자폐기물 재활용업체']
        revenue += ['대량 패키지', '거래 수수료', '데이터삭제 연계']
        minimum = 'PC/모니터 5대 이상, 노트북 3대 이상, 휴대폰 20대 이상 권장'
    if _has_any(text, V47_KEYWORDS['office']):
        if grade == 'C': grade = 'A'
        routes += ['사무실 불용자산 대량 입찰', '중고가구 판매', '철거·이사업체 연계']
        partners += ['중고가구 업체', '이사업체', '철거업체', '사무가구 매입업체']
        revenue += ['대량 불용자산 패키지 25~50만원', '처리 리포트 5~10만원']
    if _has_any(text, V47_KEYWORDS['metal']):
        routes += ['금속·원자재 입찰', 'kg 단가 검수', '동별 묶음수거']
        partners += ['고물상', '금속매입업체', '재활용업체']
        revenue += ['거래액 3~7%', '동별 묶음 입찰권']
        minimum = '전선·금속 20kg 이상 권장'
    if data.has_storage:
        flags += ['저장매체 포함 가능: 데이터삭제·파기증명 파트너 확인 필요']
        partners += ['데이터삭제·보안폐기 업체']
    if data.source_type == 'apartment':
        flags += ['아파트는 재활용장 무단 회수가 아니라 배출 전 QR 등록·관리사무소 협의 방식으로 운영']
        routes += ['아파트 배출 전 회생 캠페인', '동별/단지별 묶음입찰']
        revenue += ['캠페인 운영비 30~70만원', '관리사무소 회생 리포트']
    if data.quantity <= 1 and data.expected_value < 30000 and grade not in ['S','D']:
        flags += ['단건 저가 물량은 즉시수거보다 동별 대기물량으로 묶는 것이 안전']
        routes += ['동별 대기물량 적립']
    routes = list(dict.fromkeys(routes or ['동별 묶음입찰', '관리자 검토']))
    partners = list(dict.fromkeys(partners or ['지역 재활용 파트너']))
    flags = list(dict.fromkeys(flags or ['최종 가격은 업체 입찰 및 현장 검수 후 확정']))
    revenue = list(dict.fromkeys(revenue or ['거래 성사 수수료', '입찰권']))
    return {'grade': grade, 'summary': summary, 'routes': routes, 'partner_targets': partners, 'compliance_flags': flags, 'minimum_bundle': minimum, 'revenue_points': revenue, 'next_action': '사진·수량·위치·출처자료를 보완한 뒤 해당 파트너에게 입찰 알림'}

@app.get('/api/v47/catalog')
def v47_catalog():
    return {
        'version': '47.0.0',
        'categories': ['폐전자기기','사무 불용자산','아파트 배출 전 캠페인','자동차 부품','노후차 프로젝트','엔진·미션 재생','수집가치 회생','원자재·전문처리'],
        'grades': {'S':'수집가치·고가부품','A':'중고판매','B':'부품·재제조','C':'원자재','D':'전문처리·거래제한'},
        'minimum_bundle': {'PC/모니터':'5대 이상','노트북':'3대 이상','휴대폰':'20대 이상','소형가전':'20개 이상','전선·금속':'20kg 이상','자동차부품':'예상가치 10만원 이상','수집품':'예상 판매가 3만원 이상'},
    }

@app.post('/api/v47/recovery/analyze')
def v47_recovery_analyze(data: V47RecoveryAnalyze):
    return {'ok': True, 'version':'47.0.0', 'analysis': v47_analyze_logic(data)}

@app.post('/api/v47/intake/register')
def v47_intake_register(data: V47RecoveryAnalyze):
    db = load_operating_db()
    analysis = v47_analyze_logic(data)
    row = data.model_dump()
    row.update({'id': now_id('v47-intake'), 'analysis': analysis, 'status': 'analysis_ready', 'created_at': time.time()})
    db.setdefault('recovery_intakes', []).append(row)
    save_db(db)
    audit('v47_intake_register', 'public', {'id': row['id'], 'grade': analysis['grade']})
    return {'ok': True, 'intake': row, 'analysis': analysis}

@app.post('/api/v47/partner/register')
def v47_partner_register(data: V47PartnerRegister):
    db = load_operating_db()
    row = data.model_dump()
    row.update({'id': now_id('v47-partner'), 'status':'pending_review', 'created_at': time.time(), 'trust_score': 60})
    db.setdefault('v47_partners', []).append(row)
    save_db(db)
    audit('v47_partner_register', 'public', {'id': row['id'], 'type': row['partner_type']})
    return {'ok': True, 'partner': row, 'next_steps': ['사업자등록증·허가/등록 자료 확인', '취급 품목과 가능 지역 검토', '초기 3개월 무료 파트너 등록 후 거래 성사 수수료 적용']}

@app.post('/api/v47/auto/project-simulate')
def v47_auto_project_simulate(data: V47AutoProject):
    total_cost = data.vehicle_price + data.transport_cost + data.admin_cost + data.dismantle_cost + data.reserve_cost
    gross_recovery = data.engine_value + data.transmission_value + data.catalyst_value + data.metal_value + data.parts_value
    sale_fee = gross_recovery * data.sale_fee_rate
    net_profit = gross_recovery - sale_fee - total_cost
    roi = round((net_profit / total_cost * 100), 1) if total_cost else 0
    decision = '진행 가능 후보' if net_profit >= 700000 and roi >= 25 else 'A안 사전입찰만 권장'
    track = 'B안 직접매입 프로젝트 검토' if decision == '진행 가능 후보' else 'A안 중개형으로 먼저 파트너 견적 확보'
    return {'total_cost': round(total_cost), 'total_recovery': round(gross_recovery), 'sale_fee': round(sale_fee), 'net_profit': round(net_profit), 'roi': roi, 'decision': decision, 'recommended_track': track, 'checklist': ['압류·저당·체납 확인', '침수·사고·시동·미션 상태 확인', '촉매 장착 여부 확인', '관허폐차장 입고 가능 여부 확인', '파트너 사전입찰 3곳 이상 확보']}

@app.post('/api/v47/engine/remanufacture-simulate')
def v47_engine_simulate(data: V47EngineProject):
    total_cost = data.core_price + data.disassembly_cost + data.parts_cost + data.assembly_cost + data.logistics_cost
    gross_profit = data.sale_price - total_cost
    commission = data.sale_price * data.commission_rate
    margin_rate = round((gross_profit / data.sale_price * 100), 1) if data.sale_price else 0
    if gross_profit <= 0:
        model = '직접 프로젝트 금지, 코어 중개만 권장'
    elif margin_rate < 20:
        model = '위탁판매 또는 중개형 권장'
    else:
        model = '전문업체 보증 조건으로 프로젝트 검토 가능'
    return {'total_cost': round(total_cost), 'sale_price': round(data.sale_price), 'gross_profit': round(gross_profit), 'platform_commission': round(commission), 'margin_rate': margin_rate, 'recommended_model': model, 'notice': '초기에는 자원잇다가 직접 품질보증하지 말고 재제조업체 보증·검사표 기준으로 판매해야 합니다.'}

@app.post('/api/v47/collector/screen')
def v47_collector_screen(data: V47CollectorScreen):
    text = ' '.join([data.item or '', data.brand or '', data.memo or '', data.condition or ''])
    score = 40
    if _has_any(text, V47_KEYWORDS['collector']): score += 25
    if any(x in data.condition for x in ['미개봉','박스','작동']): score += 15
    if data.estimated_price >= 100000: score += 15
    if data.estimated_price < 30000: score -= 10
    grade = 'S' if score >= 75 else 'A' if score >= 55 else 'B'
    commission = data.estimated_price * (0.18 if grade == 'S' else 0.12)
    channels = ['수집가 입찰방', '전문점 위탁판매'] if grade == 'S' else ['중고 플랫폼 판매대행', '전문점 매입문의']
    cautions = ['도난·가품·문화재 의심품 거래 금지', '정품/구성품/작동 여부는 관리자 검토 후 표시', '고가품은 위탁판매 동의서 필요']
    return {'grade': grade, 'score': min(score,100), 'summary': '수집가치 우선 검토 대상' if grade=='S' else '중고판매 또는 전문점 문의 대상', 'channels': channels, 'estimated_commission': round(commission), 'cautions': cautions}

@app.post('/api/v47/apartment/campaign-simulate')
def v47_apartment_simulate(data: V47ApartmentCampaign):
    revenue = data.campaign_fee + data.transaction_fee + data.report_fee
    net = revenue - data.operating_cost
    item_rate = round((data.expected_items / data.households * 100), 1) if data.households else 0
    decision = '진행 권장' if net >= 150000 and data.expected_items >= 30 else '미니 캠페인 또는 사전 수요조사 권장'
    return {'revenue': round(revenue), 'operating_cost': round(data.operating_cost), 'net_profit': round(net), 'item_rate': item_rate, 'decision': decision, 'operating_rules': ['재활용장 무단 회수 금지', '관리사무소 협의 및 게시문 승인', '입주민 배출 전 QR 등록', '기존 재활용 계약 품목 침범 금지', '수익금 처리방식 문서화']}

@app.get('/api/v47/admin/command')
def v47_admin_command():
    db = load_operating_db()
    intakes = db.get('recovery_intakes', [])
    partners = db.get('v47_partners', [])
    grade_counts: Dict[str, int] = {}
    for row in intakes:
        g = row.get('analysis',{}).get('grade','-')
        grade_counts[g] = grade_counts.get(g,0)+1
    return {'kpi': {'회생등록': len(intakes), 'v47파트너': len(partners), 'S등급후보': grade_counts.get('S',0), '거래제한D': grade_counts.get('D',0), '자동차후보': sum(1 for x in intakes if x.get('is_auto_part')), '수집품후보': sum(1 for x in intakes if x.get('is_collector_candidate'))}, 'grade_counts': grade_counts, 'recent_intakes': intakes[-10:][::-1], 'recent_partners': partners[-10:][::-1]}

@app.get('/api/v47/system-check')
def v47_system_check():
    required = ['resource-register.html','recovery-model.html','auto-recovery.html','aged-car-project.html','engine-remanufacture.html','collector-market.html','apartment-recovery.html','partner-network.html']
    return {'ok': all((STATIC/p).exists() for p in required), 'version':'47.0.0', 'pages': {p:(STATIC/p).exists() for p in required}, 'api': ['recovery/analyze','intake/register','partner/register','auto/project-simulate','engine/remanufacture-simulate','collector/screen','apartment/campaign-simulate','admin/command'], 'business_scope': '광주 전역 자원회생 지역운영사 풀모델'}



# ----------------- v48 real operations layer: case -> risk -> bundle -> bid -> settlement -> report -----------------
from enum import Enum

V48_STATUS = [
    'received', 'risk_screen', 'bundle_wait', 'bid_open', 'awarded',
    'pickup_scheduled', 'inspected', 'settled', 'reported', 'blocked'
]

V48_STATUS_LABEL = {
    'received': '접수완료',
    'risk_screen': '위험·권한검토',
    'bundle_wait': '동별 묶음대기',
    'bid_open': '입찰진행',
    'awarded': '낙찰·업체확정',
    'pickup_scheduled': '수거일정확정',
    'inspected': '현장검수완료',
    'settled': '정산완료',
    'reported': '리포트발행',
    'blocked': '거래보류',
}

V48_RESTRICTED_WORDS = ['음식물','종량제','의료폐기물','주사기','석면','기름','오일','위험물','출처불명','도난','개인 촉매','말소 전','무단']
V48_AUTO_HIGH_RISK = ['촉매','배터리','에어백','고전압','엔진','미션','차량','노후차']
V48_DATA_RISK = ['HDD','SSD','서버','휴대폰','노트북','PC','컴퓨터','하드','저장장치']

class V48CaseCreate(BaseModel):
    case_type: str = '일반 자원회생'
    source: str = '개인'
    title: str = ''
    region_gu: str = '광주 서구'
    dong: str = ''
    address: Optional[str] = None
    item_text: str = ''
    quantity: int = 1
    estimated_value: float = 0
    estimated_weight: float = 0
    has_storage: bool = False
    auto_related: bool = False
    collector_candidate: bool = False
    owner_confirmed: bool = False
    partner_required: Optional[str] = None
    memo: Optional[str] = None

class V48BidCreate(BaseModel):
    case_id: str
    partner_name: str
    partner_type: str = '일반 파트너'
    amount: float = 0
    recovery_route: str = '중고/재활용 검수 후 확정'
    pickup_plan: str = ''
    compliance_memo: str = ''
    settlement_type: str = '거래액 수수료'

class V48Award(BaseModel):
    bid_id: str
    memo: Optional[str] = None

class V48StatusPatch(BaseModel):
    status: str
    memo: Optional[str] = None
    schedule: Optional[str] = None
    inspected_amount: Optional[float] = None
    final_recovery_route: Optional[str] = None

class V48Settlement(BaseModel):
    case_id: Optional[str] = None
    gross_sales: float = 0
    partner_cost: float = 0
    logistics_cost: float = 0
    platform_direct_cost: float = 0
    campaign_fee: float = 0
    report_fee: float = 0
    commission_rate: float = 0.07
    revenue_share_rate: float = 0.0

class V48PartnerDueDiligence(BaseModel):
    name: str = '미입력 업체'
    partner_type: str = '재활용/중고/자동차/수집품'
    region: str = '광주 전역'
    has_biz_registration: bool = False
    has_required_permit: bool = False
    has_insurance: bool = False
    can_handle_data_destruction: bool = False
    can_handle_auto_parts: bool = False
    can_handle_hazard: bool = False
    accepts_no_unverified_catalyst: bool = True
    memo: Optional[str] = None

class V48LaunchTask(BaseModel):
    owner: str = '운영자'
    title: str
    category: str = '영업'
    due: Optional[str] = None
    status: str = 'todo'
    memo: Optional[str] = None


def v48_seed_db(db: Dict[str, Any]) -> Dict[str, Any]:
    db.setdefault('v48_cases', [])
    db.setdefault('v48_bids', [])
    db.setdefault('v48_settlements', [])
    db.setdefault('v48_partner_due_diligence', [])
    db.setdefault('v48_launch_tasks', [])
    if not db['v48_launch_tasks']:
        db['v48_launch_tasks'] = [
            {'id':'task-1','category':'법무/범위','title':'생활폐기물 전체 수거가 아니라 배출 전 회생·중개 서비스라는 문구 전체 페이지 반영','owner':'대표/운영책임자','due':'D+1','status':'doing','memo':'약관·푸터·아파트 페이지에 반복 고지'},
            {'id':'task-2','category':'파트너','title':'광주 관허폐차장·정비소·중고부품·재제조 파트너 30곳 리스트 확보','owner':'자동차 담당','due':'D+7','status':'todo','memo':'촉매/배터리는 출처확인 가능 업체만'},
            {'id':'task-3','category':'파트너','title':'중고PC·고물상·중고가구·데이터삭제 업체 50곳 전화','owner':'업체 영업','due':'D+7','status':'todo','memo':'3개월 무료등록 + 성사수수료 구조'},
            {'id':'task-4','category':'물량','title':'학원·병원·사무실·PC방 대량 불용자산 후보 50곳 연락','owner':'고객 영업','due':'D+14','status':'todo','memo':'월 300 목표 핵심'},
            {'id':'task-5','category':'아파트','title':'관리사무소 15곳에 배출 전 QR 회생 캠페인 제안','owner':'캠페인 담당','due':'D+14','status':'todo','memo':'기존 재활용 계약 침범 금지'},
            {'id':'task-6','category':'시스템','title':'접수→위험검토→입찰→정산→리포트 샘플 5건 실제 입력','owner':'개발/운영','due':'D+21','status':'todo','memo':'투자/심사 시연 데이터'},
            {'id':'task-7','category':'자동차','title':'엔카·정비소 후보 차량 20대 회생가치 사전입찰표 작성','owner':'자동차 담당','due':'D+21','status':'todo','memo':'B안 직접매입은 1대 이하'},
            {'id':'task-8','category':'수익','title':'업체 입찰권·대량패키지·아파트캠페인·자동차중개 수익표 확정','owner':'대표','due':'D+30','status':'todo','memo':'월300/월1000 모델'},
        ]
    if not db['v48_cases']:
        demo = {
            'id': 'case-demo-1', 'case_type':'대량 전산장비', 'source':'학원', 'title':'상무지구 학원 PC·모니터 교체 물량',
            'region_gu':'광주 서구', 'dong':'치평동', 'address':'광주 서구 치평동', 'item_text':'데스크탑 PC 18대, 모니터 20대, 노트북 3대, 공유기 4대',
            'quantity':45, 'estimated_value':650000, 'estimated_weight':380, 'has_storage':True, 'auto_related':False, 'collector_candidate':False,
            'owner_confirmed':True, 'memo':'HDD/SSD 포함 가능. 데이터삭제 파트너 필요.', 'created_at':time.time()-3600,
        }
        analysis = v48_case_decision(demo)
        demo.update({'status':analysis['next_status'], 'analysis':analysis, 'history':[{'ts':time.time()-3600,'status':'received','memo':'데모 접수'}]})
        db['v48_cases'].append(demo)
    return db


def v48_db() -> Dict[str, Any]:
    db = load_operating_db()
    db = v48_seed_db(db)
    save_db(db)
    return db


def v48_text(row: Dict[str, Any]) -> str:
    return ' '.join(str(row.get(k,'')) for k in ['case_type','source','title','region_gu','dong','item_text','memo','partner_required']).lower()


def v48_case_decision(row: Dict[str, Any]) -> Dict[str, Any]:
    text = v48_text(row)
    flags: List[str] = []
    required_docs: List[str] = ['등록자 연락처/소유 확인', '사진 3장 이상', '주소·동 정보']
    partner_targets: List[str] = []
    next_status = 'bid_open'
    grade = 'C'
    route = '동별 묶음입찰 또는 원자재 회생'
    minimum = '예상가치 5만원 이상 또는 동별 묶음대기'

    if any(w.lower() in text for w in V48_RESTRICTED_WORDS):
        return {
            'grade':'D', 'route':'거래보류·전문처리 검토', 'risk_level':'높음', 'next_status':'blocked',
            'flags':['생활폐기물·위험물·의료폐기물·출처불명·무단탈거 의심 품목은 일반 입찰 금지'],
            'required_docs':['관리자 검토 메모','허가업체 처리 가능 여부','등록자 소유/출처 확인'],
            'partner_targets':['전문처리 허가업체','관리자'], 'minimum':minimum,
            'operator_memo':'일반 수거/입찰로 열지 말고 위험 검토 후 처리 범위 확정'
        }
    if row.get('collector_candidate') or any(w.lower() in text for w in V47_KEYWORDS['collector']):
        grade='S'; route='수집가치 회생·위탁판매'; next_status='risk_screen'
        flags.append('가품·도난품·문화재 의심품 여부 확인 필요')
        required_docs += ['정품/구성품/작동 여부 사진', '위탁판매 동의']
        partner_targets += ['수집품 전문점','레트로/오디오/카메라 커뮤니티','위탁판매 파트너']
        minimum='예상 판매가 3만원 이상이면 개별 검토'
    if row.get('auto_related') or any(w.lower() in text for w in V48_AUTO_HIGH_RISK):
        grade='S'; route='자동차 부품·노후차 회생 사전입찰'; next_status='risk_screen'
        flags += ['차량 직접 해체 금지', '관허폐차장/정비소/부품업체 출처 확인 필요', '개인 촉매·출처불명 고가부품 거래 금지']
        required_docs += ['사업자 또는 차량/부품 출처자료', '차종·연식·차대번호 일부 또는 정비/폐차 증빙', '촉매·배터리 여부 체크']
        partner_targets += ['관허폐차장','정비소·공업사','중고부품업체','엔진·미션 재제조업체','촉매·배터리 전문업체']
        minimum='자동차 부품 예상 회생가치 10만원 이상 또는 파트너 사전입찰 필요'
    if row.get('has_storage') or any(w.lower() in text for w in [x.lower() for x in V48_DATA_RISK]):
        if grade == 'C': grade = 'A'; route='전산장비 중고/부품/보안삭제 회생'
        flags.append('저장매체 가능성: 데이터삭제·파기증명 파트너 확인 필요')
        required_docs += ['저장매체 포함 여부', '데이터삭제 필요 여부', '파기증명 필요 여부']
        partner_targets += ['중고PC 업체','데이터삭제 업체','전자폐기물 재활용업체']
    if row.get('estimated_value',0) < 50000 and row.get('quantity',1) < 5 and grade not in ['S','D']:
        next_status = 'bundle_wait'
        flags.append('단건 저가 물량은 즉시 입찰보다 동별 묶음대기 권장')
    if grade not in ['S','D'] and (row.get('quantity',0) >= 5 or row.get('estimated_value',0) >= 50000):
        next_status = 'bid_open'
    if not row.get('owner_confirmed'):
        flags.append('소유자/관리주체 확인 전 낙찰·수거 진행 금지')
        if next_status == 'bid_open': next_status='risk_screen'
        required_docs.append('소유자 또는 관리주체 동의')
    risk_level = '높음' if any('금지' in f or '촉매' in f or '출처' in f for f in flags) else '보통' if flags else '낮음'
    return {
        'grade':grade, 'route':route, 'risk_level':risk_level, 'next_status':next_status,
        'flags':list(dict.fromkeys(flags or ['최종 가격은 입찰 및 현장검수 후 확정'])),
        'required_docs':list(dict.fromkeys(required_docs)),
        'partner_targets':list(dict.fromkeys(partner_targets or ['지역 재활용 파트너','중고/수거업체'])),
        'minimum':minimum,
        'operator_memo':'위험 플래그와 필수자료가 채워진 뒤 상태를 다음 단계로 이동'
    }


def v48_recommend_bundles(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for c in cases:
        if c.get('status') in ['reported','blocked','settled']:
            continue
        key = f"{c.get('region_gu','광주')} {c.get('dong','동 미지정')}"
        buckets.setdefault(key, []).append(c)
    out=[]
    for k, rows in buckets.items():
        value=sum(float(r.get('estimated_value') or 0) for r in rows)
        qty=sum(int(r.get('quantity') or 0) for r in rows)
        weight=sum(float(r.get('estimated_weight') or 0) for r in rows)
        readiness='입찰 가능' if value>=50000 or qty>=10 or weight>=50 else '대기 유지'
        out.append({'bundle_key':k,'case_count':len(rows),'quantity':qty,'estimated_value':round(value),'estimated_weight':round(weight,1),'readiness':readiness,'case_ids':[r['id'] for r in rows]})
    return sorted(out, key=lambda x:(x['readiness']!='입찰 가능', -x['estimated_value'], -x['quantity']))


def v48_settlement_calc(data: V48Settlement) -> Dict[str, Any]:
    commission = data.gross_sales * data.commission_rate
    share = max(data.gross_sales - data.partner_cost - data.logistics_cost - data.platform_direct_cost, 0) * data.revenue_share_rate
    platform_revenue = commission + share + data.campaign_fee + data.report_fee
    net_profit = platform_revenue - data.platform_direct_cost
    partner_net = data.partner_cost + max(data.gross_sales - data.partner_cost - data.logistics_cost, 0) * (1-data.revenue_share_rate)
    return {
        'gross_sales':round(data.gross_sales), 'commission':round(commission), 'revenue_share':round(share),
        'campaign_fee':round(data.campaign_fee), 'report_fee':round(data.report_fee),
        'platform_revenue':round(platform_revenue), 'platform_direct_cost':round(data.platform_direct_cost),
        'platform_net_profit':round(net_profit), 'partner_expected_net':round(partner_net),
        'decision':'수익성 양호' if net_profit>=50000 else '수수료·캠페인비 보강 필요'
    }


@app.get('/api/v48/catalog')
def v48_catalog():
    return {
        'version':'48.0.0',
        'status_flow': V48_STATUS_LABEL,
        'core_operations':['접수','위험검토','동별묶음','입찰','낙찰','수거일정','현장검수','정산','리포트'],
        'must_not_do':['생활폐기물 전체 수거','무허가 폐기물 운반·보관','재활용장 무단회수','차량 직접해체','말소 전 부품탈거','개인 촉매 거래','출처불명 고가부품 거래'],
        'launch_rule':'직접 처리보다 검증된 파트너와 계약하고, 자원잇다는 접수·입찰·정산·리포트 운영사 역할부터 시작'
    }

@app.post('/api/v48/cases')
def v48_create_case(data: V48CaseCreate):
    db = v48_db()
    row = data.model_dump()
    row['id'] = now_id('case')
    row['created_at'] = time.time()
    row['analysis'] = v48_case_decision(row)
    row['status'] = row['analysis']['next_status']
    row['history'] = [{'ts':time.time(),'status':'received','memo':'접수 생성'}, {'ts':time.time(),'status':row['status'],'memo':'자동 위험·회생경로 판정'}]
    db.setdefault('v48_cases', []).append(row)
    save_db(db)
    audit('v48_case_create', 'public', {'id':row['id'], 'status':row['status'], 'grade':row['analysis']['grade']})
    return {'ok':True, 'case':row, 'analysis':row['analysis']}

@app.get('/api/v48/cases')
def v48_list_cases(status: Optional[str]=None, region: Optional[str]=None):
    db = v48_db()
    rows = db.get('v48_cases', [])
    if status:
        rows=[r for r in rows if r.get('status')==status]
    if region:
        rows=[r for r in rows if region in (r.get('region_gu','')+r.get('dong',''))]
    return {'items':rows[::-1], 'count':len(rows)}

@app.get('/api/v48/dashboard')
def v48_dashboard():
    db = v48_db()
    cases = db.get('v48_cases', [])
    bids = db.get('v48_bids', [])
    settlements = db.get('v48_settlements', [])
    status_counts: Dict[str,int] = {s:0 for s in V48_STATUS}
    grade_counts: Dict[str,int] = {}
    for c in cases:
        status_counts[c.get('status','received')] = status_counts.get(c.get('status','received'),0)+1
        g = c.get('analysis',{}).get('grade','-')
        grade_counts[g] = grade_counts.get(g,0)+1
    sales = sum(float(s.get('platform_revenue',0)) for s in settlements)
    return {
        'kpi': {
            '전체 케이스':len(cases), '입찰진행':status_counts.get('bid_open',0), '위험검토':status_counts.get('risk_screen',0),
            '동별묶음대기':status_counts.get('bundle_wait',0), '거래보류':status_counts.get('blocked',0),
            '입찰제안':len(bids), '플랫폼매출':round(sales)
        },
        'status_counts':status_counts, 'grade_counts':grade_counts,
        'bundles':v48_recommend_bundles(cases)[:10],
        'recent_cases':cases[-12:][::-1], 'recent_bids':bids[-12:][::-1],
        'tasks':db.get('v48_launch_tasks', [])
    }

@app.post('/api/v48/bids')
def v48_create_bid(data: V48BidCreate):
    db = v48_db()
    cases = db.get('v48_cases', [])
    case = next((c for c in cases if c.get('id')==data.case_id), None)
    if not case:
        raise HTTPException(404, '케이스를 찾을 수 없습니다.')
    if case.get('status') in ['blocked','reported']:
        raise HTTPException(400, '거래보류 또는 리포트 발행 완료 케이스에는 입찰할 수 없습니다.')
    bid = data.model_dump()
    bid['id'] = now_id('bid')
    bid['created_at'] = time.time()
    bid['status'] = 'submitted'
    db.setdefault('v48_bids', []).append(bid)
    if case.get('status') in ['received','bundle_wait']:
        case['status']='bid_open'
    case.setdefault('history', []).append({'ts':time.time(),'status':'bid_open','memo':f"입찰 접수: {bid['partner_name']} {round(bid['amount'])}원"})
    save_db(db)
    audit('v48_bid_create', 'public', {'case_id':data.case_id, 'bid_id':bid['id']})
    return {'ok':True, 'bid':bid, 'case':case, 'recommended_award': v48_best_bid(db, data.case_id)}


def v48_best_bid(db: Dict[str,Any], case_id: str) -> Optional[Dict[str,Any]]:
    bids=[b for b in db.get('v48_bids', []) if b.get('case_id')==case_id and b.get('status') in ['submitted','awarded']]
    if not bids: return None
    return sorted(bids, key=lambda x: float(x.get('amount') or 0), reverse=True)[0]

@app.post('/api/v48/cases/{case_id}/award')
def v48_award_case(case_id: str, data: V48Award):
    db = v48_db()
    case = next((c for c in db.get('v48_cases', []) if c.get('id')==case_id), None)
    bid = next((b for b in db.get('v48_bids', []) if b.get('id')==data.bid_id and b.get('case_id')==case_id), None)
    if not case or not bid:
        raise HTTPException(404, '케이스 또는 입찰을 찾을 수 없습니다.')
    for b in db.get('v48_bids', []):
        if b.get('case_id')==case_id: b['status']='not_selected'
    bid['status']='awarded'
    case['status']='awarded'
    case['awarded_bid_id']=bid['id']
    case['awarded_partner']=bid['partner_name']
    case.setdefault('history', []).append({'ts':time.time(),'status':'awarded','memo':data.memo or f"{bid['partner_name']} 낙찰"})
    save_db(db)
    audit('v48_award_case','admin',{'case_id':case_id,'bid_id':bid['id']})
    return {'ok':True,'case':case,'bid':bid}

@app.patch('/api/v48/cases/{case_id}/status')
def v48_patch_case_status(case_id: str, data: V48StatusPatch):
    if data.status not in V48_STATUS:
        raise HTTPException(400, '허용되지 않은 상태입니다.')
    db = v48_db()
    case = next((c for c in db.get('v48_cases', []) if c.get('id')==case_id), None)
    if not case:
        raise HTTPException(404, '케이스를 찾을 수 없습니다.')
    case['status']=data.status
    if data.schedule: case['schedule']=data.schedule
    if data.inspected_amount is not None: case['inspected_amount']=data.inspected_amount
    if data.final_recovery_route: case['final_recovery_route']=data.final_recovery_route
    case.setdefault('history', []).append({'ts':time.time(),'status':data.status,'memo':data.memo or V48_STATUS_LABEL.get(data.status,data.status)})
    save_db(db)
    audit('v48_case_status','admin',{'case_id':case_id,'status':data.status})
    return {'ok':True,'case':case}

@app.post('/api/v48/settlement/simulate')
def v48_simulate_settlement(data: V48Settlement):
    return v48_settlement_calc(data)

@app.post('/api/v48/cases/{case_id}/settle')
def v48_settle_case(case_id: str, data: V48Settlement):
    db = v48_db()
    case = next((c for c in db.get('v48_cases', []) if c.get('id')==case_id), None)
    if not case:
        raise HTTPException(404, '케이스를 찾을 수 없습니다.')
    result = v48_settlement_calc(data)
    result.update({'id':now_id('settle'), 'case_id':case_id, 'created_at':time.time()})
    db.setdefault('v48_settlements', []).append(result)
    case['status']='settled'
    case['settlement_id']=result['id']
    case.setdefault('history', []).append({'ts':time.time(),'status':'settled','memo':f"정산 완료: 플랫폼 순이익 {result['platform_net_profit']}원"})
    save_db(db)
    audit('v48_case_settle','admin',{'case_id':case_id,'settlement_id':result['id']})
    return {'ok':True,'settlement':result,'case':case}

@app.get('/api/v48/cases/{case_id}/report')
def v48_case_report(case_id: str):
    db = v48_db()
    case = next((c for c in db.get('v48_cases', []) if c.get('id')==case_id), None)
    if not case:
        raise HTTPException(404, '케이스를 찾을 수 없습니다.')
    bids=[b for b in db.get('v48_bids', []) if b.get('case_id')==case_id]
    settlement=next((s for s in db.get('v48_settlements', []) if s.get('case_id')==case_id), None)
    analysis=case.get('analysis',{})
    bid_lines = [f"- {b.get('partner_name')} / {round(float(b.get('amount') or 0))}원 / {b.get('recovery_route')} / {b.get('status')}" for b in bids]
    if not bid_lines:
        bid_lines = ['- 입찰 내역 없음']
    doc_lines = [f"- {x}" for x in analysis.get('required_docs', [])] or ['- 필수자료 미등록']
    lines = [
        f"자원잇다 회생 결과 리포트 - {case.get('title') or case.get('item_text')}",
        f"지역: {case.get('region_gu','')} {case.get('dong','')}",
        f"현재 상태: {V48_STATUS_LABEL.get(case.get('status'), case.get('status'))}",
        f"회생등급: {analysis.get('grade','-')} / 경로: {analysis.get('route','-')}",
        f"위험검토: {analysis.get('risk_level','-')}",
        '',
        '필수 확인자료:',
        *doc_lines,
        '',
        '입찰 내역:',
        *bid_lines,
        '',
        '정산:',
        f"- 플랫폼 매출: {settlement.get('platform_revenue') if settlement else '정산 전'}원" if settlement else '- 정산 전',
        f"- 플랫폼 순이익: {settlement.get('platform_net_profit') if settlement else '정산 전'}원" if settlement else '- 정산 전',
        '',
        '주의: 본 리포트는 자원회생 운영 기록이며, 폐기물 처리·자동차 해체·공식 공공입찰을 자원잇다가 직접 수행했다는 의미가 아닙니다.'
    ]
    return {'case':case, 'bids':bids, 'settlement':settlement, 'report_text':'\n'.join(lines)}

@app.post('/api/v48/partners/due-diligence')
def v48_partner_due_diligence(data: V48PartnerDueDiligence):
    db = v48_db()
    score = 40
    if data.has_biz_registration: score += 15
    if data.has_required_permit: score += 15
    if data.has_insurance: score += 10
    if data.can_handle_data_destruction: score += 8
    if data.can_handle_auto_parts: score += 6
    if data.accepts_no_unverified_catalyst: score += 6
    if data.can_handle_hazard and not data.has_required_permit: score -= 15
    status = 'approved_candidate' if score >= 75 else 'limited_candidate' if score >= 55 else 'hold'
    row = data.model_dump()
    row.update({'id':now_id('dd'), 'score':min(score,100), 'status':status, 'created_at':time.time(), 'required_followups':[]})
    if not data.has_biz_registration: row['required_followups'].append('사업자등록증 확인')
    if data.can_handle_hazard and not data.has_required_permit: row['required_followups'].append('위험/폐기물 처리 허가 확인 전 제한')
    if data.can_handle_auto_parts and not data.accepts_no_unverified_catalyst: row['required_followups'].append('출처불명 촉매 거래 금지 서약 필요')
    db.setdefault('v48_partner_due_diligence', []).append(row)
    save_db(db)
    return {'ok':True,'partner_check':row}

@app.get('/api/v48/launch/tasks')
def v48_launch_tasks():
    db=v48_db()
    return {'items':db.get('v48_launch_tasks', [])}

@app.post('/api/v48/launch/tasks')
def v48_add_launch_task(data: V48LaunchTask):
    db=v48_db()
    row=data.model_dump(); row.update({'id':now_id('task'), 'created_at':time.time()})
    db.setdefault('v48_launch_tasks', []).append(row)
    save_db(db)
    return {'ok':True,'task':row}

@app.get('/api/v48/system-check')
def v48_system_check():
    required_pages = ['index.html','operations.html','real-launch.html','partner-verify.html','settlement-center.html','legal-risk-gate.html','resource-register.html','auto-recovery.html','aged-car-project.html','engine-remanufacture.html','collector-market.html','apartment-recovery.html']
    return {
        'ok': all((STATIC/p).exists() for p in required_pages),
        'version':'48.0.0',
        'pages':{p:(STATIC/p).exists() for p in required_pages},
        'api':['/api/v48/cases','/api/v48/bids','/api/v48/dashboard','/api/v48/settlement/simulate','/api/v48/partners/due-diligence','/api/v48/launch/tasks'],
        'ready_for_actual_mvp':'접수·위험검토·묶음·입찰·정산·리포트까지 데모DB에서 실제 흐름 가능. 실영업 전 법률/세무/허가/계약 검토 필요.'
    }



# ----------------- v49 template-based document engine -----------------
# 목표: OCR/AI를 매번 쓰지 않고, 자원잇다가 보유한 양식 템플릿에 구조화 데이터만 넣어
# 견적서·인보이스·정산서·확인서·자동차 출처확인서 등을 PDF/HTML로 발급한다.
# PDF 생성은 서버 내부 ReportLab으로 처리하므로 100장 발급도 API 사용료가 거의 들지 않는다.

V49_DOCUMENT_TEMPLATE_SEED = [
    {
        'id': 'quote', 'title': '견적서', 'prefix': 'Q', 'category': '일반 거래',
        'description': '대량 불용자산, 자동차 부품, 수집품 위탁 등 거래 전 견적 산출용 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'line_items'],
        'default_notice': '본 견적은 등록 정보 기준의 예상 견적이며, 최종 금액은 현장 검수 및 낙찰 조건에 따라 달라질 수 있습니다.',
    },
    {
        'id': 'invoice', 'title': '인보이스', 'prefix': 'INV', 'category': '일반 거래',
        'description': '입찰권, 캠페인비, 정산 수수료, 문서 발급비 등 청구용 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'line_items'],
        'default_notice': '세금계산서 발행 또는 별도 회계처리는 실제 사업자 정보와 세무 검토 후 진행해야 합니다.',
    },
    {
        'id': 'settlement', 'title': '정산서', 'prefix': 'SET', 'category': '정산',
        'description': '입찰 낙찰 후 총거래액, 파트너 지급액, 플랫폼 수수료, 순이익을 정리하는 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'line_items'],
        'default_notice': '정산 금액은 최종 검수 사진, 계량표, 입찰조건, 수거완료 확인을 기준으로 확정됩니다.',
    },
    {
        'id': 'pickup_confirmation', 'title': '수거 확인서', 'prefix': 'PU', 'category': '운영 확인',
        'description': '수거일, 품목, 수량, 현장검수 결과를 기록하는 확인서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.pickup_date', 'fields.pickup_address'],
        'default_notice': '자원잇다는 중개·운영 플랫폼이며 실제 수거·운반·처리는 선택된 파트너가 수행합니다.',
    },
    {
        'id': 'recovery_report', 'title': '자원회생 결과 보고서', 'prefix': 'REP', 'category': '리포트',
        'description': '재사용, 부품화, 재생, 원자재화, 전문처리 결과를 정리하는 보고서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.recovery_route'],
        'default_notice': '본 보고서는 회생 운영 기록이며, 공공기관 공식 처리증명 또는 법정 증명서를 대체하지 않습니다.',
    },
    {
        'id': 'data_erasure', 'title': '데이터삭제 요청/확인서', 'prefix': 'DER', 'category': '보안',
        'description': 'PC·노트북·서버·휴대폰 등 저장매체 보안삭제 연계용 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.device_list', 'fields.erasure_partner'],
        'default_notice': '데이터삭제·파기 결과의 최종 책임과 증명은 실제 작업을 수행한 전문업체의 확인서 기준으로 처리됩니다.',
    },
    {
        'id': 'destruction_certificate', 'title': '파기확인서', 'prefix': 'DST', 'category': '보안/전문처리',
        'description': '저장매체, 보안품목, 전문처리 품목의 파기 작업 확인용 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.destruction_method', 'fields.partner_name'],
        'default_notice': '파기확인서는 파트너 작업증빙과 함께 보관해야 하며, 실제 법정 증명 필요 시 전문업체 원본 확인서를 첨부해야 합니다.',
    },
    {
        'id': 'auto_origin', 'title': '자동차 부품 출처확인서', 'prefix': 'AUTO-ORG', 'category': '자동차',
        'description': '엔진·미션·촉매·휠 등 자동차 부품의 출처와 제한사항을 기록하는 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.part_name', 'fields.source_type', 'fields.source_partner'],
        'default_notice': '출처 불명 촉매, 말소 전 임의 탈거 부품, 도난 의심 부품은 거래할 수 없습니다. 자원잇다는 차량을 직접 해체하지 않습니다.',
    },
    {
        'id': 'remanufacture_order', 'title': '엔진·미션 재생 위탁서', 'prefix': 'REM', 'category': '자동차 재생',
        'description': '엔진·미션 코어의 분해·검수·재제조 위탁 범위를 기록하는 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.core_type', 'fields.vehicle_model', 'fields.reman_partner'],
        'default_notice': '재생·재제조 품질보증은 실제 작업업체의 보증조건에 따르며, 자원잇다는 입찰·정산·기록관리 역할을 수행합니다.',
    },
    {
        'id': 'aged_car_project', 'title': '노후차 회생 프로젝트 정산서', 'prefix': 'CAR-SET', 'category': '자동차 프로젝트',
        'description': 'A안 사전입찰 또는 B안 직접매입 프로젝트의 비용·회수액·수익분배를 기록하는 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.vehicle_model', 'fields.project_type'],
        'default_notice': '차량 매입형 프로젝트는 압류·저당·말소·탁송·해체비·보관비를 사전 검토한 뒤 진행해야 합니다.',
    },
    {
        'id': 'apartment_campaign_report', 'title': '아파트 회생 캠페인 결과보고서', 'prefix': 'APT-REP', 'category': '아파트',
        'description': '관리사무소 협의형 배출 전 회생 캠페인 결과를 정리하는 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.campaign_period', 'fields.apartment_name'],
        'default_notice': '본 캠페인은 생활폐기물 수거 대행이 아니라 배출 전 재사용 가능 물품·소형가전 회생 운영입니다.',
    },
    {
        'id': 'collector_consignment', 'title': '수집가치 위탁판매 확인서', 'prefix': 'COL', 'category': '수집품',
        'description': '레트로·오디오·카메라·피규어·희귀부품 등의 위탁판매 조건을 기록하는 문서',
        'required': ['issuer.name', 'recipient.name', 'project.title', 'fields.item_name', 'fields.sale_channel'],
        'default_notice': '가품, 도난 의심품, 문화재 의심품, 거래제한 품목은 위탁판매 대상에서 제외됩니다.',
    },
]

V49_DEFAULT_ISSUER = {
    'name': '자원잇다',
    'biz_no': '000-00-00000',
    'address': '광주광역시 전역 자원회생 운영센터',
    'phone': '010-0000-0000',
    'email': 'hello@jawonitda.local',
    'manager': '운영담당자',
}

class V49Party(BaseModel):
    name: str = ''
    biz_no: Optional[str] = ''
    address: Optional[str] = ''
    phone: Optional[str] = ''
    email: Optional[str] = ''
    manager: Optional[str] = ''

class V49Project(BaseModel):
    title: str = ''
    region: Optional[str] = ''
    case_id: Optional[str] = ''
    category: Optional[str] = ''
    memo: Optional[str] = ''

class V49LineItem(BaseModel):
    name: str
    spec: Optional[str] = ''
    qty: float = 1
    unit: Optional[str] = '건'
    unit_price: float = 0
    taxable: bool = True
    memo: Optional[str] = ''

class V49DocumentPayload(BaseModel):
    template_id: str
    issuer: Optional[V49Party] = None
    recipient: V49Party = Field(default_factory=V49Party)
    project: V49Project = Field(default_factory=V49Project)
    fields: Dict[str, Any] = Field(default_factory=dict)
    line_items: List[V49LineItem] = Field(default_factory=list)
    memo: Optional[str] = ''
    issue_count: int = 1
    created_by: Optional[str] = 'admin'

class V49TemplateUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    default_notice: Optional[str] = None
    required: Optional[List[str]] = None


def v49_now_date() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def v49_generated_dir() -> Path:
    d = STORAGE / 'generated_documents'
    d.mkdir(parents=True, exist_ok=True)
    return d


def v49_db() -> Dict[str, Any]:
    db = load_db()
    if not db.get('v49_document_templates'):
        db['v49_document_templates'] = V49_DOCUMENT_TEMPLATE_SEED
    db.setdefault('v49_documents', [])
    db.setdefault('v49_document_counters', {})
    db.setdefault('v49_document_audit', [])
    save_db(db)
    return db


def v49_get_template(template_id: str) -> Dict[str, Any]:
    # v50.20: 이전 화면/테스트에서 쓰던 예전 템플릿 id도 안전하게 매핑합니다.
    alias = {
        'pre_checklist': 'pickup_confirmation',
        'pre': 'pickup_confirmation',
        'attach': 'recovery_report',
        'internal': 'recovery_report',
        'report': 'recovery_report',
    }
    template_id = alias.get(template_id, template_id)
    db = v49_db()
    template = next((t for t in db.get('v49_document_templates', []) if t.get('id') == template_id), None)
    if not template:
        raise HTTPException(404, '문서 템플릿을 찾을 수 없습니다.')
    return template


def v49_deep_get(data: Dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split('.'):
        if part == 'line_items':
            return data.get('line_items')
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def v49_validate_payload(template: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    missing = []
    warnings = []
    for key in template.get('required', []):
        value = v49_deep_get(payload, key)
        if value in (None, '', [], {}):
            missing.append(key)
    # money check
    items = payload.get('line_items') or []
    if items:
        for i, item in enumerate(items, 1):
            if float(item.get('qty') or 0) <= 0:
                warnings.append(f'{i}번 품목 수량이 0 이하입니다.')
            if float(item.get('unit_price') or 0) < 0:
                warnings.append(f'{i}번 품목 단가가 음수입니다.')
    # special gates
    template_id = template.get('id')
    fields = payload.get('fields') or {}
    if template_id in ('auto_origin', 'remanufacture_order', 'aged_car_project'):
        src = str(fields.get('source_type') or fields.get('source_partner') or '').strip()
        if not src:
            warnings.append('자동차 부품/노후차 문서는 출처 확인값이 필요합니다.')
        if fields.get('is_catalyst') and fields.get('seller_type') == '개인':
            missing.append('fields.business_source_for_catalyst')
            warnings.append('촉매는 개인 등록을 제한하고 사업자 출처 확인이 필요합니다.')
    if template_id in ('data_erasure', 'destruction_certificate'):
        if not fields.get('device_list') and not fields.get('destruction_method'):
            warnings.append('저장매체 또는 파기 대상 식별정보가 부족합니다.')
    if template_id == 'apartment_campaign_report':
        if not fields.get('manager_approval'):
            warnings.append('아파트 캠페인은 관리사무소 협의/승인 여부를 기록해야 합니다.')
    if template_id == 'collector_consignment':
        if fields.get('authenticity_risk'):
            warnings.append('가품/도난/문화재 의심품은 위탁판매 보류가 필요합니다.')
    return {'ok': not missing, 'missing': missing, 'warnings': warnings}


def v49_totals(line_items: List[Dict[str, Any]]) -> Dict[str, int]:
    supply = 0
    vat = 0
    for item in line_items:
        amount = float(item.get('qty') or 0) * float(item.get('unit_price') or 0)
        supply += amount
        if item.get('taxable', True):
            vat += amount * 0.1
    return {'supply_amount': round(supply), 'vat': round(vat), 'total_amount': round(supply + vat)}


def v49_next_doc_no(db: Dict[str, Any], template: Dict[str, Any]) -> str:
    year = datetime.now().strftime('%Y')
    key = f"{template.get('prefix','DOC')}-{year}"
    counters = db.setdefault('v49_document_counters', {})
    counters[key] = int(counters.get(key, 0)) + 1
    return f"{key}-{counters[key]:06d}"


def v49_escape(x: Any) -> str:
    return html.escape('' if x is None else str(x))


def v49_document_html(record: Dict[str, Any]) -> str:
    template = record.get('template', {})
    issuer = record.get('issuer', {})
    recipient = record.get('recipient', {})
    project = record.get('project', {})
    fields = record.get('fields', {})
    items = record.get('line_items', [])
    totals = record.get('totals', {})
    notice = template.get('default_notice', '')
    rows = ''
    if items:
        for idx, item in enumerate(items, 1):
            amount = round(float(item.get('qty') or 0) * float(item.get('unit_price') or 0))
            rows += f"""
            <tr><td>{idx}</td><td>{v49_escape(item.get('name'))}</td><td>{v49_escape(item.get('spec'))}</td><td class='right'>{item.get('qty')}</td><td>{v49_escape(item.get('unit'))}</td><td class='right'>{round(float(item.get('unit_price') or 0)):,}</td><td class='right'>{amount:,}</td><td>{v49_escape(item.get('memo'))}</td></tr>
            """
    else:
        rows = "<tr><td colspan='8' class='muted'>금액 품목이 없는 확인서형 문서입니다.</td></tr>"
    field_rows = ''.join([f"<tr><th>{v49_escape(k)}</th><td>{v49_escape(v)}</td></tr>" for k, v in fields.items()]) or "<tr><td colspan='2' class='muted'>추가 필드 없음</td></tr>"
    verify_url = f"/api/v49/documents/verify/{record.get('verify_code')}"
    return f"""<!doctype html>
<html lang='ko'><head><meta charset='utf-8'><title>{v49_escape(template.get('title'))} {v49_escape(record.get('doc_no'))}</title>
<style>
@page {{ size: A4; margin: 16mm; }}
* {{ box-sizing:border-box; }} body {{ font-family: 'Malgun Gothic', 'NanumGothic', Arial, sans-serif; color:#15231b; margin:0; background:#fff; font-size:12px; }}
.doc {{ max-width: 820px; margin: 0 auto; padding: 26px; }}
.header {{ display:flex; justify-content:space-between; align-items:flex-start; border-bottom:3px solid #143d2b; padding-bottom:16px; margin-bottom:18px; }}
.brand {{ font-size:22px; font-weight:900; color:#143d2b; letter-spacing:-.4px; }}
.title {{ text-align:right; }} .title h1 {{ margin:0 0 6px; font-size:28px; }} .title .no {{ color:#667; font-weight:700; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:14px 0; }}
.box {{ border:1px solid #d6e2dc; border-radius:12px; padding:12px; background:#fbfdfb; }}
.box h3 {{ margin:0 0 8px; font-size:14px; color:#143d2b; }}
table {{ width:100%; border-collapse:collapse; margin:10px 0; }} th,td {{ border:1px solid #dce6e1; padding:7px 8px; vertical-align:top; }} th {{ background:#eef7f0; color:#143d2b; }} .right {{ text-align:right; }} .muted {{ color:#667; }}
.total {{ margin-left:auto; width:360px; }} .total th {{ text-align:left; }} .total td {{ text-align:right; font-weight:800; }}
.notice {{ margin-top:16px; padding:12px; border-left:4px solid #27915e; background:#f4fbf6; line-height:1.55; }}
.sign {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:18px; }} .stamp {{ height:70px; border:1px dashed #9ab; display:flex; align-items:center; justify-content:center; color:#789; border-radius:10px; }}
.footer {{ margin-top:22px; padding-top:10px; border-top:1px solid #e3ece7; color:#667; font-size:11px; display:flex; justify-content:space-between; gap:12px; }}
.badge {{ display:inline-block; padding:4px 9px; border-radius:999px; background:#143d2b; color:#fff; font-size:11px; }}
@media print {{ .no-print {{ display:none; }} .doc {{ padding:0; }} }}
</style></head><body><div class='doc'>
<div class='header'><div><div class='brand'>자원잇다</div><div class='muted'>광주 전역 자원회생 운영 문서</div><div style='margin-top:8px'><span class='badge'>{v49_escape(template.get('category'))}</span></div></div><div class='title'><h1>{v49_escape(template.get('title'))}</h1><div class='no'>{v49_escape(record.get('doc_no'))}</div><div>발행일: {v49_escape(record.get('issued_at'))}</div></div></div>
<div class='grid'><div class='box'><h3>발행자</h3><div><b>{v49_escape(issuer.get('name'))}</b></div><div>사업자번호: {v49_escape(issuer.get('biz_no'))}</div><div>주소: {v49_escape(issuer.get('address'))}</div><div>연락처: {v49_escape(issuer.get('phone'))}</div><div>담당: {v49_escape(issuer.get('manager'))}</div></div>
<div class='box'><h3>수신자</h3><div><b>{v49_escape(recipient.get('name'))}</b></div><div>사업자번호: {v49_escape(recipient.get('biz_no'))}</div><div>주소: {v49_escape(recipient.get('address'))}</div><div>연락처: {v49_escape(recipient.get('phone'))}</div><div>담당: {v49_escape(recipient.get('manager'))}</div></div></div>
<div class='box'><h3>프로젝트</h3><div><b>{v49_escape(project.get('title'))}</b></div><div>지역: {v49_escape(project.get('region'))} / 분류: {v49_escape(project.get('category'))}</div><div>케이스ID: {v49_escape(project.get('case_id'))}</div><div>메모: {v49_escape(project.get('memo'))}</div></div>
<h3>품목/금액</h3><table><thead><tr><th>No</th><th>품목</th><th>규격</th><th>수량</th><th>단위</th><th>단가</th><th>금액</th><th>비고</th></tr></thead><tbody>{rows}</tbody></table>
<table class='total'><tr><th>공급가액</th><td>{int(totals.get('supply_amount',0)):,}원</td></tr><tr><th>부가세</th><td>{int(totals.get('vat',0)):,}원</td></tr><tr><th>합계</th><td>{int(totals.get('total_amount',0)):,}원</td></tr></table>
<h3>추가 확인 필드</h3><table>{field_rows}</table>
<div class='notice'><b>안내</b><br>{v49_escape(notice)}<br>{v49_escape(record.get('memo'))}</div>
<div class='sign'><div class='box'><h3>발행 승인</h3><div class='stamp'>전자직인/승인란</div></div><div class='box'><h3>검증 정보</h3><div>검증코드: <b>{v49_escape(record.get('verify_code'))}</b></div><div>조회경로: {v49_escape(verify_url)}</div><div>상태: {v49_escape(record.get('status'))}</div></div></div>
<div class='footer'><div>본 문서는 자원잇다 템플릿 엔진으로 발급되었습니다.</div><div>재발행/수정 시 이력 보관 필요</div></div>
</div></body></html>"""


V49_FONT_CACHE = {'name': None, 'path': None, 'registered': False}

def v49_find_font() -> Tuple[str, Optional[str]]:
    candidates = [
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        'C:/Windows/Fonts/malgun.ttf',
        'C:/Windows/Fonts/Malgun.ttf',
        '/System/Library/Fonts/AppleSDGothicNeo.ttc',
    ]
    for p in candidates:
        if Path(p).exists():
            return 'JW_KR', p
    return 'Helvetica', None




def v49_register_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if V49_FONT_CACHE.get('name'):
        return V49_FONT_CACHE['name']
    font_name, font_path = v49_find_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        except Exception:
            font_name = 'Helvetica'
    V49_FONT_CACHE['name'] = font_name
    V49_FONT_CACHE['path'] = font_path
    V49_FONT_CACHE['registered'] = bool(font_path and font_name != 'Helvetica')
    return font_name

def v49_pdf(record: Dict[str, Any], pdf_path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    font_name = v49_register_font()
    bold_name = font_name
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    normal = ParagraphStyle('normal', fontName=font_name, fontSize=9, leading=13, textColor=colors.HexColor('#17251d'))
    small = ParagraphStyle('small', fontName=font_name, fontSize=8, leading=11, textColor=colors.HexColor('#5c6b62'))
    h1 = ParagraphStyle('h1', fontName=bold_name, fontSize=20, leading=25, alignment=TA_RIGHT, textColor=colors.HexColor('#143d2b'))
    h2 = ParagraphStyle('h2', fontName=bold_name, fontSize=11, leading=15, textColor=colors.HexColor('#143d2b'), spaceBefore=8, spaceAfter=4)
    right = ParagraphStyle('right', fontName=font_name, fontSize=9, leading=13, alignment=TA_RIGHT)
    center = ParagraphStyle('center', fontName=font_name, fontSize=9, leading=13, alignment=TA_CENTER)
    def P(x, style=normal):
        return Paragraph(v49_escape(x).replace('\n','<br/>'), style)
    template = record.get('template', {})
    issuer = record.get('issuer', {})
    recipient = record.get('recipient', {})
    project = record.get('project', {})
    fields = record.get('fields', {})
    totals = record.get('totals', {})
    story = []
    header = Table([
        [P('자원잇다\n광주 전역 자원회생 운영 문서', normal), P(f"{template.get('title')}\n{record.get('doc_no')}\n발행일 {record.get('issued_at')}", h1)]
    ], colWidths=[85*mm, 95*mm])
    header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),1.5,colors.HexColor('#143d2b')),('BOTTOMPADDING',(0,0),(-1,-1),9)]))
    story += [header, Spacer(1, 7*mm)]
    def party_box(title, d):
        data = [[P(title, h2)], [P(f"{d.get('name','')}\n사업자번호: {d.get('biz_no','')}\n주소: {d.get('address','')}\n연락처: {d.get('phone','')}\n담당: {d.get('manager','')}")]]
        t=Table(data, colWidths=[86*mm])
        t.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.6,colors.HexColor('#d6e2dc')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef7f0')),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),6)]))
        return t
    parties = Table([[party_box('발행자', issuer), party_box('수신자', recipient)]], colWidths=[90*mm,90*mm])
    parties.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [parties, Spacer(1,5*mm)]
    proj = Table([[P('프로젝트', h2)], [P(f"{project.get('title','')}\n지역: {project.get('region','')} / 분류: {project.get('category','')}\n케이스ID: {project.get('case_id','')}\n메모: {project.get('memo','')}")]], colWidths=[180*mm])
    proj.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.6,colors.HexColor('#d6e2dc')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef7f0')),('PADDING',(0,0),(-1,-1),6)]))
    story += [proj, Spacer(1,4*mm), P('품목/금액', h2)]
    item_rows = [[P('No', center),P('품목', center),P('규격', center),P('수량', center),P('단위', center),P('단가', center),P('금액', center),P('비고', center)]]
    for idx,item in enumerate(record.get('line_items', []) or [], 1):
        amount = round(float(item.get('qty') or 0)*float(item.get('unit_price') or 0))
        item_rows.append([P(idx, center),P(item.get('name')),P(item.get('spec')),P(item.get('qty'), right),P(item.get('unit')),P(f"{round(float(item.get('unit_price') or 0)):,}", right),P(f"{amount:,}", right),P(item.get('memo'))])
    if len(item_rows)==1:
        item_rows.append([P('-', center),P('금액 품목이 없는 확인서형 문서입니다.'),'','','','','',''])
    table = Table(item_rows, colWidths=[10*mm,36*mm,26*mm,15*mm,14*mm,22*mm,25*mm,32*mm], repeatRows=1)
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#dce6e1')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef7f0')),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),4)]))
    story += [table, Spacer(1,3*mm)]
    total = Table([[P('공급가액'),P(f"{int(totals.get('supply_amount',0)):,}원", right)],[P('부가세'),P(f"{int(totals.get('vat',0)):,}원", right)],[P('합계'),P(f"{int(totals.get('total_amount',0)):,}원", right)]], colWidths=[40*mm,40*mm], hAlign='RIGHT')
    total.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.HexColor('#dce6e1')),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#eef7f0')),('PADDING',(0,0),(-1,-1),5)]))
    story += [total, Spacer(1,4*mm), P('추가 확인 필드', h2)]
    field_rows = [[P('항목', center),P('내용', center)]]
    for k,v in fields.items():
        field_rows.append([P(k),P(v)])
    if len(field_rows)==1: field_rows.append([P('-'),P('추가 필드 없음')])
    ft=Table(field_rows, colWidths=[45*mm,135*mm], repeatRows=1)
    ft.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#dce6e1')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef7f0')),('PADDING',(0,0),(-1,-1),5),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [ft, Spacer(1,4*mm)]
    notice = f"안내: {template.get('default_notice','')}\n{record.get('memo','')}"
    nt=Table([[P(notice)]], colWidths=[180*mm])
    nt.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.6,colors.HexColor('#8ec9a5')),('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f4fbf6')),('PADDING',(0,0),(-1,-1),7)]))
    story += [nt, Spacer(1,5*mm)]
    verify = Table([[P('발행 승인', h2),P('검증 정보', h2)],[P('전자직인/승인란\n\n'),P(f"검증코드: {record.get('verify_code')}\n상태: {record.get('status')}\n문서번호: {record.get('doc_no')}")]], colWidths=[88*mm,88*mm])
    verify.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#dce6e1')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef7f0')),('PADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [verify, Spacer(1,4*mm), P('본 문서는 자원잇다 템플릿 엔진으로 발급되었습니다. 재발행/수정 시 이력 보관이 필요합니다.', small)]
    doc.build(story)


def v49_make_record(payload: V49DocumentPayload, sequence_suffix: Optional[int]=None, generate_pdf: bool=True) -> Dict[str, Any]:
    db = v49_db()
    template = v49_get_template(payload.template_id)
    issuer = (payload.issuer.model_dump() if payload.issuer else V49_DEFAULT_ISSUER.copy())
    recipient = payload.recipient.model_dump()
    project = payload.project.model_dump()
    line_items = [x.model_dump() for x in payload.line_items]
    if sequence_suffix is not None:
        project['title'] = f"{project.get('title') or template.get('title')} #{sequence_suffix:03d}"
    base_payload = {'issuer':issuer, 'recipient':recipient, 'project':project, 'fields':payload.fields, 'line_items':line_items}
    validation = v49_validate_payload(template, base_payload)
    if not validation['ok']:
        raise HTTPException(400, {'message':'필수값이 부족합니다.', 'validation':validation})
    doc_no = v49_next_doc_no(db, template)
    save_db(db)  # counter persist before PDF generation/batch loop
    verify_code = hashlib.sha256(f"{doc_no}-{time.time()}-{SECRET_KEY}".encode()).hexdigest()[:16].upper()
    totals = v49_totals(line_items)
    record = {
        'id': 'doc-' + re.sub(r'[^a-zA-Z0-9]+', '-', doc_no).lower().strip('-'), 'doc_no': doc_no, 'template_id': template['id'], 'template': template,
        'issuer': issuer, 'recipient': recipient, 'project': project, 'fields': payload.fields, 'line_items': line_items,
        'totals': totals, 'memo': payload.memo or '', 'status': 'issued', 'issued_at': v49_now_date(),
        'created_at': time.time(), 'created_by': payload.created_by or 'admin', 'verify_code': verify_code,
        'validation': validation, 'html_file': '', 'pdf_file': '', 'reissue_count': 0,
    }
    outdir = v49_generated_dir()
    safe_no = re.sub(r'[^A-Za-z0-9_.-]', '_', doc_no)
    html_path = outdir / f'{safe_no}.html'
    pdf_path = outdir / f'{safe_no}.pdf'
    html_path.write_text(v49_document_html(record), encoding='utf-8')
    if generate_pdf:
        v49_pdf(record, pdf_path)
    record['html_file'] = html_path.name
    record['pdf_file'] = pdf_path.name
    record['pdf_ready'] = bool(generate_pdf and pdf_path.exists())
    db = v49_db()
    db.setdefault('v49_documents', []).append(record)
    db['v49_documents'] = db['v49_documents'][-2000:]
    db.setdefault('v49_document_audit', []).append({'ts':time.time(), 'action':'issue', 'doc_no':doc_no, 'template_id':template['id'], 'created_by':record['created_by']})
    save_db(db)
    audit('v49_document_issue', record['created_by'], {'doc_no':doc_no, 'template_id':template['id']})
    return record


@app.get('/api/v49/document-templates')
def v49_templates():
    db = v49_db()
    return {'ok': True, 'templates': db.get('v49_document_templates', [])}

@app.patch('/api/v49/document-templates/{template_id}')
def v49_update_template(template_id: str, data: V49TemplateUpdate):
    db = v49_db()
    t = next((x for x in db.get('v49_document_templates', []) if x.get('id')==template_id), None)
    if not t:
        raise HTTPException(404, '템플릿을 찾을 수 없습니다.')
    patch = data.model_dump(exclude_unset=True)
    t.update(patch)
    save_db(db)
    return {'ok': True, 'template': t}

@app.post('/api/v49/documents/validate')
def v49_validate_document(data: V49DocumentPayload):
    template = v49_get_template(data.template_id)
    issuer = (data.issuer.model_dump() if data.issuer else V49_DEFAULT_ISSUER.copy())
    payload = {'issuer':issuer, 'recipient':data.recipient.model_dump(), 'project':data.project.model_dump(), 'fields':data.fields, 'line_items':[x.model_dump() for x in data.line_items]}
    validation = v49_validate_payload(template, payload)
    return {'ok': validation['ok'], 'template': template, 'validation': validation, 'totals': v49_totals(payload['line_items'])}

@app.post('/api/v49/documents/preview')
def v49_preview_document(data: V49DocumentPayload):
    template = v49_get_template(data.template_id)
    issuer = (data.issuer.model_dump() if data.issuer else V49_DEFAULT_ISSUER.copy())
    recipient = data.recipient.model_dump(); project=data.project.model_dump(); line_items=[x.model_dump() for x in data.line_items]
    record = {'id':'preview','doc_no':'PREVIEW-000000','template_id':template['id'],'template':template,'issuer':issuer,'recipient':recipient,'project':project,'fields':data.fields,'line_items':line_items,'totals':v49_totals(line_items),'memo':data.memo or '', 'status':'preview','issued_at':v49_now_date(),'verify_code':'PREVIEW'}
    validation = v49_validate_payload(template, {'issuer':issuer,'recipient':recipient,'project':project,'fields':data.fields,'line_items':line_items})
    return {'ok': True, 'validation': validation, 'totals': record['totals'], 'html': v49_document_html(record)}

@app.post('/api/v49/documents/issue')
def v49_issue_document(data: V49DocumentPayload):
    record = v49_make_record(data)
    return {'ok': True, 'document': {k:v for k,v in record.items() if k not in ('template','issuer','recipient','fields','line_items')}, 'html_url': f"/api/v49/documents/{record['id']}/html", 'pdf_url': f"/api/v49/documents/{record['id']}/pdf"}

@app.post('/api/v49/documents/batch-issue')
def v49_batch_issue(data: V49DocumentPayload):
    count = max(1, min(int(data.issue_count or 1), 100))
    db = v49_db()
    template = v49_get_template(data.template_id)
    issuer = (data.issuer.model_dump() if data.issuer else V49_DEFAULT_ISSUER.copy())
    recipient = data.recipient.model_dump()
    base_project = data.project.model_dump()
    line_items = [x.model_dump() for x in data.line_items]
    records = []
    outdir = v49_generated_dir()
    for i in range(1, count+1):
        project = dict(base_project)
        if count > 1:
            project['title'] = f"{project.get('title') or template.get('title')} #{i:03d}"
        base_payload = {'issuer':issuer, 'recipient':recipient, 'project':project, 'fields':data.fields, 'line_items':line_items}
        validation = v49_validate_payload(template, base_payload)
        if not validation['ok']:
            raise HTTPException(400, {'message':'필수값이 부족합니다.', 'validation':validation, 'sequence':i})
        doc_no = v49_next_doc_no(db, template)
        verify_code = hashlib.sha256(f"{doc_no}-{time.time()}-{SECRET_KEY}".encode()).hexdigest()[:16].upper()
        totals = v49_totals(line_items)
        record = {
            'id': 'doc-' + re.sub(r'[^a-zA-Z0-9]+', '-', doc_no).lower().strip('-'), 'doc_no': doc_no, 'template_id': template['id'], 'template': template,
            'issuer': issuer, 'recipient': recipient, 'project': project, 'fields': data.fields, 'line_items': line_items,
            'totals': totals, 'memo': data.memo or '', 'status': 'issued', 'issued_at': v49_now_date(),
            'created_at': time.time(), 'created_by': data.created_by or 'admin', 'verify_code': verify_code,
            'validation': validation, 'html_file': '', 'pdf_file': '', 'reissue_count': 0, 'pdf_ready': False,
        }
        safe_no = re.sub(r'[^A-Za-z0-9_.-]', '_', doc_no)
        html_path = outdir / f'{safe_no}.html'
        pdf_path = outdir / f'{safe_no}.pdf'
        html_path.write_text(v49_document_html(record), encoding='utf-8')
        record['html_file'] = html_path.name
        record['pdf_file'] = pdf_path.name
        records.append(record)
    db.setdefault('v49_documents', []).extend(records)
    db['v49_documents'] = db['v49_documents'][-2000:]
    db.setdefault('v49_document_audit', []).append({'ts':time.time(), 'action':'batch_issue', 'count':count, 'template_id':template['id'], 'created_by':data.created_by or 'admin'})
    save_db(db)
    audit('v49_document_batch_issue', data.created_by or 'admin', {'count':count, 'template_id':template['id']})
    return {'ok': True, 'count': len(records), 'documents': [{'id':r['id'], 'doc_no':r['doc_no'], 'pdf_url':f"/api/v49/documents/{r['id']}/pdf", 'html_url':f"/api/v49/documents/{r['id']}/html", 'pdf_ready':r.get('pdf_ready', False)} for r in records], 'note':'템플릿 기반 발급이므로 100장 발급도 OCR/AI API 비용 없이 처리됩니다. 대량 발급 PDF는 속도를 위해 최초 다운로드 시 자동 생성됩니다.'}

@app.get('/api/v49/documents')
def v49_list_documents(limit: int = 100):
    db = v49_db()
    rows = list(reversed(db.get('v49_documents', [])))[0:max(1,min(limit,500))]
    return {'ok': True, 'documents': [{k:v for k,v in r.items() if k not in ('template','fields','line_items')} for r in rows]}

@app.get('/api/v49/documents/{doc_id}/html')
def v49_document_html_endpoint(doc_id: str):
    db = v49_db()
    r = next((x for x in db.get('v49_documents', []) if x.get('id')==doc_id), None)
    if not r:
        raise HTTPException(404, '문서를 찾을 수 없습니다.')
    path = v49_generated_dir() / r.get('html_file','')
    if not path.exists():
        raise HTTPException(404, 'HTML 파일이 없습니다.')
    return Response(path.read_text(encoding='utf-8'), media_type='text/html; charset=utf-8')

@app.get('/api/v49/documents/{doc_id}/pdf')
def v49_document_pdf_endpoint(doc_id: str):
    db = v49_db()
    r = next((x for x in db.get('v49_documents', []) if x.get('id')==doc_id), None)
    if not r:
        raise HTTPException(404, '문서를 찾을 수 없습니다.')
    path = v49_generated_dir() / r.get('pdf_file','')
    if not path.exists():
        # batch-issued documents create PDFs lazily on first download to keep 100장 발급 fast and cheap.
        v49_pdf(r, path)
        r['pdf_ready'] = True
        db = v49_db()
        target = next((x for x in db.get('v49_documents', []) if x.get('id')==doc_id), None)
        if target:
            target['pdf_ready'] = True
            save_db(db)
    return FileResponse(path, media_type='application/pdf', filename=r.get('pdf_file'))

@app.get('/api/v49/documents/verify/{verify_code}')
def v49_verify_document(verify_code: str):
    db = v49_db()
    r = next((x for x in db.get('v49_documents', []) if x.get('verify_code')==verify_code), None)
    if not r:
        raise HTTPException(404, '검증코드와 일치하는 문서가 없습니다.')
    return {'ok': True, 'doc_no': r.get('doc_no'), 'template': r.get('template',{}).get('title'), 'issued_at': r.get('issued_at'), 'status': r.get('status'), 'project': r.get('project'), 'totals': r.get('totals')}

@app.post('/api/v49/documents/sample-100')
def v49_sample_100():
    payload = V49DocumentPayload(
        template_id='invoice',
        recipient=V49Party(name='광주그린자원', biz_no='123-45-67890', address='광주광역시 북구', phone='062-000-0000', manager='입찰담당'),
        project=V49Project(title='동별 묶음 입찰권 자동발급 샘플', region='광주 전역', category='입찰권/문서발급'),
        line_items=[V49LineItem(name='자원잇다 문서/입찰 자동발급 테스트', spec='템플릿 기반 100장', qty=1, unit='식', unit_price=30000)],
        fields={'발급방식':'양식 템플릿 + 구조화 데이터', 'OCR비용':'사용 안 함', 'AI비용':'사용 안 함', '대량발급':'최대 100장 테스트'},
        memo='샘플 API는 100장 대량 발급 성능 확인용입니다.',
        issue_count=100,
        created_by='system-sample'
    )
    return v49_batch_issue(payload)

@app.get('/api/v49/system-check')
def v49_system_check():
    pages = ['document-center.html','dashboards/documents.html','operations.html','resource-register.html','auto-recovery.html']
    return {
        'ok': all((STATIC/p).exists() for p in pages),
        'version':'49.0.0',
        'document_engine':'template-based-pdf-html',
        'cost_model':'PDF/HTML generation is server-side. OCR/AI is optional and not required for batch document issue.',
        'templates':[t['id'] for t in v49_db().get('v49_document_templates', [])],
        'pages':{p:(STATIC/p).exists() for p in pages},
        'api':['/api/v49/document-templates','/api/v49/documents/preview','/api/v49/documents/issue','/api/v49/documents/batch-issue','/api/v49/documents/sample-100'],
    }




# ============================================================
# v50.2 Admin editable document template manager
# - Admin can edit template metadata
# - Admin can upload/replace/download template source files
# - HTML/TXT uploaded templates can be used for HTML preview rendering
# ============================================================

TEMPLATE_STORAGE = STORAGE / 'document_templates'
TEMPLATE_STORAGE.mkdir(parents=True, exist_ok=True)

def v502_template_safe_id(value: str) -> str:
    value = re.sub(r'[^a-zA-Z0-9_-]+', '-', (value or '').strip()).strip('-').lower()
    return value[:60] or f'template-{int(time.time())}'

def v502_template_meta(t: Dict[str, Any]) -> Dict[str, Any]:
    file_name = t.get('custom_template_file') or ''
    path = TEMPLATE_STORAGE / file_name if file_name else None
    meta = dict(t)
    meta['has_uploaded_file'] = bool(path and path.exists())
    meta['uploaded_file_size'] = path.stat().st_size if path and path.exists() else 0
    meta['download_url'] = f"/api/v50/document-templates/{t.get('id')}/download" if meta['has_uploaded_file'] else ''
    meta['editable_in_browser'] = (t.get('custom_template_type') in ('html','txt'))
    return meta

def v502_template_audit(action: str, template_id: str, extra: Dict[str, Any] | None = None) -> None:
    db = v49_db()
    db.setdefault('v50_template_audit', []).append({
        'ts': time.time(),
        'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': action,
        'template_id': template_id,
        'extra': extra or {},
    })
    db['v50_template_audit'] = db['v50_template_audit'][-500:]
    save_db(db)

@app.get('/api/v50/document-templates')
def v502_template_list():
    db = v49_db()
    return {
        'ok': True,
        'templates': [v502_template_meta(t) for t in db.get('v49_document_templates', [])],
        'allowed_ext': sorted(ALLOWED_EXT),
        'help': {
            'html': 'HTML 템플릿은 {{doc_no}}, {{recipient.name}}, {{project.title}}, {{line_items_table}}, {{fields_table}}, {{total_amount}} 같은 치환값을 사용할 수 있습니다.',
            'pdf_docx_hwp': 'PDF/DOCX/HWP/HWPX는 원본 양식 보관·다운로드·관리용으로 저장됩니다. 실제 PDF 자동발급은 자원잇다 기본 엔진 또는 HTML 템플릿을 사용합니다.'
        }
    }

@app.post('/api/v50/document-templates/create')
async def v502_template_create(
    template_id: str = Form(...),
    title: str = Form(...),
    description: str = Form(''),
    prefix: str = Form('DOC'),
    default_notice: str = Form(''),
    required: str = Form('recipient.name,project.title,line_items'),
    file: UploadFile | None = File(None)
):
    db = v49_db()
    tid = v502_template_safe_id(template_id)
    if any(t.get('id') == tid for t in db.get('v49_document_templates', [])):
        raise HTTPException(400, '이미 존재하는 템플릿 ID입니다.')
    required_list = [x.strip() for x in (required or '').split(',') if x.strip()]
    template = {
        'id': tid,
        'title': title.strip() or tid,
        'description': description.strip(),
        'prefix': re.sub(r'[^A-Z0-9_-]+', '', (prefix or 'DOC').upper())[:12] or 'DOC',
        'default_notice': default_notice.strip(),
        'required': required_list or ['recipient.name','project.title','line_items'],
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'is_admin_custom': True,
    }
    db.setdefault('v49_document_templates', []).append(template)
    save_db(db)
    v502_template_audit('create', tid, {'title': title})
    if file and file.filename:
        return await v502_template_upload(tid, title=title, description=description, default_notice=default_notice, required=required, file=file)
    return {'ok': True, 'template': v502_template_meta(template)}

@app.post('/api/v50/document-templates/{template_id}/metadata')
async def v502_template_update_metadata(
    template_id: str,
    title: str = Form(''),
    description: str = Form(''),
    default_notice: str = Form(''),
    required: str = Form(''),
    prefix: str = Form('')
):
    db = v49_db()
    t = next((x for x in db.get('v49_document_templates', []) if x.get('id') == template_id), None)
    if not t:
        raise HTTPException(404, '템플릿을 찾을 수 없습니다.')
    if title.strip():
        t['title'] = title.strip()
    t['description'] = description.strip()
    t['default_notice'] = default_notice.strip()
    if required.strip():
        t['required'] = [x.strip() for x in required.split(',') if x.strip()]
    if prefix.strip():
        t['prefix'] = re.sub(r'[^A-Z0-9_-]+', '', prefix.upper())[:12] or t.get('prefix','DOC')
    t['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    save_db(db)
    v502_template_audit('metadata_update', template_id, {'title': t.get('title')})
    return {'ok': True, 'template': v502_template_meta(t)}

@app.post('/api/v50/document-templates/{template_id}/upload')
async def v502_template_upload(
    template_id: str,
    title: str = Form(''),
    description: str = Form(''),
    default_notice: str = Form(''),
    required: str = Form(''),
    file: UploadFile = File(...)
):
    db = v49_db()
    t = next((x for x in db.get('v49_document_templates', []) if x.get('id') == template_id), None)
    if not t:
        raise HTTPException(404, '템플릿을 찾을 수 없습니다.')
    original = file.filename or ''
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f'허용되지 않는 확장자입니다: {ext}')
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f'파일은 {MAX_UPLOAD_MB}MB 이하만 업로드할 수 있습니다.')
    safe = v502_template_safe_id(template_id)
    stored_name = f"{safe}_{int(time.time())}{ext}"
    path = TEMPLATE_STORAGE / stored_name
    path.write_bytes(content)
    old_file = t.get('custom_template_file')
    if old_file and old_file != stored_name:
        old_path = TEMPLATE_STORAGE / old_file
        if old_path.exists():
            try:
                old_path.unlink()
            except Exception:
                pass
    if title.strip():
        t['title'] = title.strip()
    if description.strip():
        t['description'] = description.strip()
    if default_notice.strip():
        t['default_notice'] = default_notice.strip()
    if required.strip():
        t['required'] = [x.strip() for x in required.split(',') if x.strip()]
    t['custom_template_original_name'] = original
    t['custom_template_file'] = stored_name
    t['custom_template_ext'] = ext
    t['custom_template_type'] = 'html' if ext in ('.html', '.htm') else ('txt' if ext == '.txt' else ext.lstrip('.'))
    t['custom_template_size'] = len(content)
    t['custom_template_uploaded_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    t['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    t['is_admin_custom'] = True
    save_db(db)
    v502_template_audit('upload', template_id, {'filename': original, 'size': len(content)})
    return {'ok': True, 'template': v502_template_meta(t), 'message': '템플릿 양식이 교체되었습니다.'}

@app.get('/api/v50/document-templates/{template_id}/download')
def v502_template_download(template_id: str):
    t = v49_get_template(template_id)
    file_name = t.get('custom_template_file')
    if not file_name:
        raise HTTPException(404, '업로드된 템플릿 파일이 없습니다.')
    path = TEMPLATE_STORAGE / file_name
    if not path.exists():
        raise HTTPException(404, '템플릿 파일을 찾을 수 없습니다.')
    return FileResponse(path, filename=t.get('custom_template_original_name') or file_name, media_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')

@app.post('/api/v50/document-templates/{template_id}/reset')
def v502_template_reset(template_id: str):
    db = v49_db()
    t = next((x for x in db.get('v49_document_templates', []) if x.get('id') == template_id), None)
    if not t:
        raise HTTPException(404, '템플릿을 찾을 수 없습니다.')
    old_file = t.get('custom_template_file')
    if old_file:
        old_path = TEMPLATE_STORAGE / old_file
        if old_path.exists():
            try:
                old_path.unlink()
            except Exception:
                pass
    for k in ['custom_template_original_name','custom_template_file','custom_template_ext','custom_template_type','custom_template_size','custom_template_uploaded_at']:
        t.pop(k, None)
    t['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    save_db(db)
    v502_template_audit('reset_upload', template_id)
    return {'ok': True, 'template': v502_template_meta(t), 'message': '업로드 양식을 제거하고 기본 엔진으로 되돌렸습니다.'}

def v502_deep_value(record: Dict[str, Any], dotted: str) -> Any:
    cur: Any = record
    for part in dotted.split('.'):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return ''
    return '' if cur is None else cur

def v502_render_html_template(record: Dict[str, Any]) -> Optional[str]:
    template = record.get('template', {})
    file_name = template.get('custom_template_file')
    if not file_name or template.get('custom_template_type') not in ('html','txt'):
        return None
    path = TEMPLATE_STORAGE / file_name
    if not path.exists():
        return None
    raw = path.read_text(encoding='utf-8', errors='replace')
    fields = record.get('fields', {})
    items = record.get('line_items', [])
    totals = record.get('totals', {})
    line_items_table = ''.join(
        f"<tr><td>{i}</td><td>{v49_escape(item.get('name'))}</td><td>{v49_escape(item.get('spec'))}</td><td>{item.get('qty')}</td><td>{v49_escape(item.get('unit'))}</td><td class='right'>{round(float(item.get('unit_price') or 0)):,}</td><td class='right'>{round(float(item.get('qty') or 0)*float(item.get('unit_price') or 0)):,}</td></tr>"
        for i, item in enumerate(items, 1)
    ) or "<tr><td colspan='7'>품목 없음</td></tr>"
    fields_table = ''.join(f"<tr><th>{v49_escape(k)}</th><td>{v49_escape(v)}</td></tr>" for k,v in fields.items()) or "<tr><td colspan='2'>추가 필드 없음</td></tr>"
    repl = {
        'doc_no': record.get('doc_no',''),
        'template_id': template.get('id',''),
        'template_title': template.get('title',''),
        'title': template.get('title',''),
        'issued_at': record.get('issued_at',''),
        'verify_code': record.get('verify_code',''),
        'memo': record.get('memo',''),
        'default_notice': template.get('default_notice',''),
        'line_items_table': line_items_table,
        'fields_table': fields_table,
        'supply_amount': f"{int(totals.get('supply_amount') or 0):,}",
        'vat': f"{int(totals.get('vat') or 0):,}",
        'total_amount': f"{int(totals.get('total_amount') or 0):,}",
    }
    # dotted values: issuer.name, recipient.name, project.title, totals.total_amount, fields.xxx
    def repl_func(m):
        key = m.group(1).strip()
        if key in repl:
            return str(repl[key])
        if key.startswith('fields.'):
            return v49_escape(fields.get(key.split('.',1)[1], ''))
        value = v502_deep_value(record, key)
        return v49_escape(value)
    body = re.sub(r'\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}', repl_func, raw)
    if '<html' not in body.lower():
        body = f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{v49_escape(template.get('title'))}</title><style>body{{font-family:'Malgun Gothic',Arial,sans-serif;line-height:1.55;padding:28px;color:#15231b}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #dce6e1;padding:8px}}th{{background:#eef7f0}}</style></head><body>{body}</body></html>"""
    return body

# Override v49_document_html so uploaded HTML templates can actually affect generated HTML.
_V49_DEFAULT_DOCUMENT_HTML = v49_document_html

def v49_document_html(record: Dict[str, Any]) -> str:  # type: ignore[no-redef]
    custom = v502_render_html_template(record)
    if custom:
        return custom
    return _V49_DEFAULT_DOCUMENT_HTML(record)





# ============================================================
# v50.7 Electronics recovery value calculator API
# ============================================================

ELECTRONICS_VALUE_FILE = STATIC / 'data' / 'electronics_value_v50.json'

def v507_electronics_data() -> Dict[str, Any]:
    try:
        return json.loads(ELECTRONICS_VALUE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'categories': [], 'condition_factors': {}, 'age_factors': {}, 'storage_factors': {}, 'security_factors': {}, 'quantity_rules': {}}

def v507_norm(s: Any) -> str:
    return re.sub(r'\s+', ' ', str(s or '').lower()).strip()

def v507_pick_factor(mapping: Dict[str, Any], text: str, default: float = 1.0) -> Tuple[float, str]:
    norm = v507_norm(text)
    best = (default, 'default')
    for key, value in (mapping or {}).items():
        if key == 'unknown':
            continue
        if v507_norm(key) and v507_norm(key) in norm:
            try:
                score = float(value)
            except Exception:
                score = default
            if score > best[0] or best[1] == 'default':
                best = (score, key)
    if best[1] == 'default' and 'unknown' in mapping:
        try:
            return float(mapping.get('unknown') or default), 'unknown'
        except Exception:
            return default, 'unknown'
    return best

def v507_match_category(data: Dict[str, Any], category: str = '', brand: str = '', model: str = '', memo: str = '') -> Dict[str, Any]:
    cats = data.get('categories', [])
    if category:
        found = next((c for c in cats if c.get('id') == category), None)
        if found:
            return found
    text = v507_norm(' '.join([category, brand, model, memo]))
    for c in cats:
        for a in c.get('aliases', []):
            if v507_norm(a) and v507_norm(a) in text:
                return c
    return cats[0] if cats else {}

class V507ElectronicsValuePayload(BaseModel):
    category: Optional[str] = ''
    brand: Optional[str] = ''
    model: Optional[str] = ''
    condition: str = 'unknown'
    age: str = 'unknown'
    storage: str = 'unknown'
    security: str = 'unknown'
    quantity: int = 1
    memo: Optional[str] = ''
    owner: bool = False
    sim_removed: bool = False
    data_confirm: bool = False
    not_stolen: bool = False

@app.get('/api/v50/electronics/catalog')
def v507_electronics_catalog():
    data = v507_electronics_data()
    return {'ok': True, 'catalog': data}

@app.post('/api/v50/electronics/value')
def v507_electronics_value(payload: V507ElectronicsValuePayload):
    data = v507_electronics_data()
    cat = v507_match_category(data, payload.category or '', payload.brand or '', payload.model or '', payload.memo or '')
    if not cat:
        raise HTTPException(404, '전자기기 품목 데이터가 없습니다.')
    qty = max(1, min(int(payload.quantity or 1), 999))
    brand_model_text = ' '.join([payload.brand or '', payload.model or '', payload.memo or ''])
    brand_factor, brand_hit = v507_pick_factor(cat.get('brand_tiers', {}), brand_model_text, 1.0)
    family_factor, family_hit = v507_pick_factor(cat.get('family_tiers', {}), brand_model_text, 1.0)
    cond = data.get('condition_factors', {}).get(payload.condition) or data.get('condition_factors', {}).get('unknown', {'factor': 0.32, 'label': '상태 모름'})
    age = data.get('age_factors', {}).get(payload.age) or data.get('age_factors', {}).get('unknown', {'factor': 0.45, 'label': '연식 모름'})
    storage_factor = float(data.get('storage_factors', {}).get(str(payload.storage), data.get('storage_factors', {}).get('unknown', 1.0)))
    security = data.get('security_factors', {}).get(payload.security) or data.get('security_factors', {}).get('unknown', {'factor': 0.75, 'label': '확인 필요', 'risk': '관리자 검토'})
    base = float(cat.get('base_value') or 0)
    raw = base * brand_factor * family_factor * float(cond.get('factor') or 1) * float(age.get('factor') or 1) * storage_factor * float(security.get('factor') or 1)
    min_v = float(cat.get('min_value') or 0)
    max_v = float(cat.get('max_value') or raw)
    unit_mid = max(min_v, min(max_v, raw))
    if payload.condition in ('dead', 'power_issue') and unit_mid < float(cat.get('urban_mining') or 0):
        unit_mid = max(unit_mid, float(cat.get('urban_mining') or 0))
    low = max(0, int(unit_mid * 0.65))
    high = max(low, int(unit_mid * 1.35))
    total_low, total_high = low * qty, high * qty
    route = '관리자 검토'
    qrules = data.get('quantity_rules', {})
    if payload.not_stolen is False and cat.get('id') in ('smartphone','tablet','laptop','storage','server'):
        route = '소유 확인 후 관리자 검토'
    elif cat.get('security_level') in ('매우 높음','높음') and payload.data_confirm is False:
        route = '데이터삭제 확인 후 검수'
    elif total_high >= int(qrules.get('single_pickup_min_value') or 100000):
        route = '즉시수거/파트너 견적 후보'
    elif qty >= int(qrules.get('bundle_min_count') or 10) or total_high >= int(qrules.get('bundle_min_estimated_total') or 50000):
        route = '묶음수거/캠페인 전환'
    else:
        route = '동별 묶음대기'
    warnings = []
    if cat.get('security_level') in ('매우 높음','높음'):
        warnings.append('저장매체·계정·개인정보 삭제 확인이 필요합니다.')
    if payload.owner is False:
        warnings.append('본인 소유 또는 처분 권한 확인이 필요합니다.')
    if payload.security == 'locked':
        warnings.append('잠금해제 불가 기기는 거래 제한 또는 관리자 검토 대상입니다.')
    if '배터리' in (payload.memo or '') or cat.get('id') == 'battery':
        warnings.append('배터리 부풀음·누액·파손은 전문 파트너 검토가 필요합니다.')
    result = {
        'ok': True,
        'category': {'id': cat.get('id'), 'name': cat.get('name'), 'route': cat.get('route'), 'security_level': cat.get('security_level')},
        'input': payload.model_dump(),
        'estimate': {'unit_low': low, 'unit_high': high, 'total_low': total_low, 'total_high': total_high, 'currency': 'KRW', 'is_fixed_price': False},
        'value_breakdown': {
            'base_value': int(base),
            'brand_factor': brand_factor, 'brand_hit': brand_hit,
            'family_factor': family_factor, 'family_hit': family_hit,
            'condition': cond,
            'age': age,
            'storage_factor': storage_factor,
            'security': security,
            'urban_mining_floor': int(cat.get('urban_mining') or 0)
        },
        'decision': {'route': route, 'requires_admin_review': '관리자' in route or bool(warnings)},
        'checklist': cat.get('checklist', []),
        'warnings': warnings,
        'notice': data.get('notice'),
        'urban_mining': v5011_urban_mining_analysis(cat.get('id') or '', cat.get('name') or '', payload.condition or 'unknown', qty, payload.memo or '')
    }
    return result





# ============================================================
# v50.8 final full-stack production backend integration
# - /api/v1/electronics/* 운영용 모델DB/가치평가 API
# - /api/v1/resources/* 운영용 자원등록 API
# - /api/v1/admin/* 운영용 관리자 대시보드 API
# ============================================================
try:
    from app.database import Base as PROD_Base, engine as PROD_engine, SessionLocal as PROD_SessionLocal
    from app.seed import seed as prod_seed
    from app.routers import electronics as prod_electronics, resources as prod_resources, admin as prod_admin

    @app.on_event('startup')
    def v508_production_backend_startup():
        PROD_Base.metadata.create_all(bind=PROD_engine)
        db = PROD_SessionLocal()
        try:
            prod_seed(db)
        finally:
            db.close()

    app.include_router(prod_electronics.router)
    app.include_router(prod_resources.router)
    app.include_router(prod_admin.router)

    @app.get('/api/v1/production-health')
    def v508_production_health():
        return {'ok': True, 'message': 'production backend integrated', 'stack': 'FastAPI + SQLAlchemy + PostgreSQL/SQLite + Object Storage + Valuation Engine'}
except Exception as v508_prod_error:
    print('[v50.8] production backend integration skipped:', v508_prod_error)

    # v51.09 structural fallback:
    # If SQLAlchemy or the production submodule is not installed yet, the public
    # production-backend.html page must still not break with 404/405.
    # These safe-mock endpoints keep the page and button tests usable until
    # the real production backend dependency is installed by requirements.txt.
    @app.get('/api/v1/production-health')
    def v5109_prod_fallback_health():
        return {'ok': True, 'mode': 'safe-mock-fallback', 'message': 'production backend fallback active', 'reason': str(v508_prod_error)}

    @app.get('/api/v1/admin/dashboard')
    def v5109_prod_fallback_dashboard():
        db = load_db()
        return {'ok': True, 'mode': 'safe-mock-fallback', 'counts': {'categories': len(disposal_catalog()), 'manufacturers': 0, 'models': 0, 'variants': 0, 'submissions': len(db.get('quick_actions', [])) + len(db.get('pickup_requests', [])), 'unmatched': 0}, 'recent_unmatched': []}

    @app.get('/api/v1/electronics/catalog')
    def v5109_prod_fallback_catalog():
        return {'ok': True, 'mode': 'safe-mock-fallback', 'categories': [{'code': 'smartphone', 'name': '폐휴대폰'}, {'code': 'laptop', 'name': '폐노트북'}, {'code': 'desktop', 'name': '데스크탑/전산장비'}], 'manufacturers': [{'name': '삼성'}, {'name': '애플'}, {'name': 'LG'}], 'models': [], 'rules': []}

    @app.get('/api/v1/electronics/unmatched')
    def v5109_prod_fallback_unmatched():
        return {'ok': True, 'mode': 'safe-mock-fallback', 'items': []}

    @app.post('/api/v1/electronics/models')
    def v5109_prod_fallback_models(data: Dict[str, Any]):
        return {'ok': True, 'mode': 'safe-mock-fallback', 'model': {'id': now_id('model'), **data}}

    @app.post('/api/v1/electronics/variants')
    def v5109_prod_fallback_variants(data: Dict[str, Any]):
        return {'ok': True, 'mode': 'safe-mock-fallback', 'variant': {'id': now_id('variant'), **data}}

    @app.post('/api/v1/electronics/valuate')
    def v5109_prod_fallback_valuate(data: Dict[str, Any]):
        text = ' '.join(str(data.get(k, '')) for k in ['item_text','manufacturer_text','model_text','condition_code','age_code'])
        low, high = (8000, 45000)
        if any(k in text.lower() for k in ['iphone','아이폰','갤럭시','s21','휴대폰','스마트폰']):
            low, high = (15000, 90000)
        elif any(k in text.lower() for k in ['노트북','laptop','그램','macbook']):
            low, high = (30000, 180000)
        return {'ok': True, 'mode': 'safe-mock-fallback', 'estimated_low': low, 'estimated_high': high, 'route': '중고판매/부품회수/도시광산 관리자 검토', 'matched_confidence': 0.62, 'requires_admin_review': True, 'warnings': ['운영용 DB가 아직 safe-mock fallback입니다. requirements 설치 후 실제 모델DB로 전환됩니다.']}

    @app.post('/api/v1/resources/submit')
    async def v5109_prod_fallback_resource_submit(
        user_id: str = Form(''), item_text: str = Form(''), category_code: str = Form(''),
        manufacturer_text: str = Form(''), model_text: str = Form(''), condition_code: str = Form('unknown'),
        age_code: str = Form('unknown'), security_code: str = Form('unknown'), quantity: int = Form(1),
        memo: str = Form(''), photo: UploadFile | None = File(None)
    ):
        photo_url = None
        if photo and photo.filename:
            safe = f"prod_{int(time.time()*1000)}_{safe_filename(photo.filename)}"
            dest = UPLOADS / safe
            with dest.open('wb') as f:
                shutil.copyfileobj(photo.file, f)
            photo_url = f'/uploads/{safe}'
        valuation = v5109_prod_fallback_valuate({'item_text': item_text, 'manufacturer_text': manufacturer_text, 'model_text': model_text, 'condition_code': condition_code, 'age_code': age_code})
        return {'ok': True, 'mode': 'safe-mock-fallback', 'submission_id': now_id('sub'), 'photo_url': photo_url, 'valuation': valuation}




# ============================================================
# v50.10 Photo-first friendly intake API
# ============================================================

def v5010_label_to_electronics_category(label: str, fallback_text: str = '') -> str:
    text = v507_norm(' '.join([label or '', fallback_text or '']))
    rules = [
        ('smartphone', ['휴대폰','스마트폰','핸드폰','아이폰','갤럭시','iphone','galaxy','phone']),
        ('laptop', ['노트북','랩탑','맥북','그램','갤럭시북','laptop','macbook']),
        ('desktop', ['데스크탑','컴퓨터 본체','pc 본체','본체','desktop','computer']),
        ('monitor', ['모니터','디스플레이','display','lcd','oled']),
        ('tablet', ['태블릿','아이패드','갤럭시탭','tablet','ipad']),
        ('server', ['서버','nas','랙서버','스위치','라우터']),
        ('storage', ['ssd','hdd','하드','외장하드','저장장치','usb']),
        ('pc_parts', ['그래픽카드','gpu','ram','cpu','메인보드','파워']),
        ('printer', ['프린터','복합기','스캐너']),
        ('camera_audio', ['카메라','렌즈','오디오','스피커','게임기']),
        ('wearable_small', ['워치','이어폰','헤드폰','에어팟','버즈']),
        ('battery', ['배터리','보조배터리','리튬']),
    ]
    for cat, keys in rules:
        if any(k in text for k in keys):
            return cat
    return ''

@app.post('/api/v50/photo-first/analyze')
async def v5010_photo_first_analyze(
    request: Request,
    photo: UploadFile = File(None),
    item_text: str = Form(''),
    model_text: str = Form(''),
    brand_text: str = Form(''),
    condition: str = Form('unknown'),
    age: str = Form('unknown'),
    storage: str = Form('unknown'),
    security: str = Form('unknown'),
    quantity: int = Form(1),
    memo: str = Form(''),
    owner: bool = Form(False),
    data_confirm: bool = Form(False),
    not_stolen: bool = Form(False),
):
    inferred = {'item': '', 'confidence': 0, 'reason': '사진 없이 입력정보 기반으로 분석', 'features': {}}
    saved_url = None
    if photo and photo.filename:
        ext = Path(photo.filename or '').suffix.lower()
        if ext not in {'.jpg','.jpeg','.png','.webp'}:
            raise HTTPException(400, '사진은 jpg, png, webp만 업로드할 수 있습니다.')
        content = await photo.read()
        if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f'파일은 {MAX_UPLOAD_MB}MB 이하만 업로드할 수 있습니다.')
        photo_name = f"photo_first_{int(time.time()*1000)}_{safe_filename(photo.filename or 'photo.jpg')}"
        tmp = UPLOADS / photo_name
        tmp.write_bytes(content)
        saved_url = f"/uploads/{photo_name}"
        inferred = v505_infer_photo_item(photo.filename or photo_name, tmp)

    label = inferred.get('item') or item_text or '관리자 검토 필요'
    category = v5010_label_to_electronics_category(label, ' '.join([item_text, model_text, brand_text, memo]))
    electronics_result = None
    if category:
        payload = V507ElectronicsValuePayload(
            category=category,
            brand=brand_text or '',
            model=model_text or item_text or label,
            condition=condition or 'unknown',
            age=age or 'unknown',
            storage=storage or 'unknown',
            security=security or 'unknown',
            quantity=max(1, min(int(quantity or 1), 999)),
            memo=memo or '',
            owner=bool(owner),
            sim_removed=False,
            data_confirm=bool(data_confirm),
            not_stolen=bool(not_stolen),
        )
        try:
            electronics_result = v507_electronics_value(payload)
        except Exception as e:
            electronics_result = {'ok': False, 'error': str(e)}

    urban_mining = v5011_urban_mining_analysis(category, label, condition, quantity, memo) if category else {'available': False}
    if electronics_result and electronics_result.get('ok') and urban_mining.get('available'):
        electronics_result['urban_mining'] = urban_mining

    route = '관리자 검토'
    if electronics_result and electronics_result.get('ok'):
        route = electronics_result.get('decision', {}).get('route') or route
    elif inferred.get('confidence', 0) < 0.55:
        route = '사진/모델명 추가 후 관리자 검토'
    else:
        route = '배출 안내표 확인 후 접수'

    return {
        'ok': True,
        'mode': 'photo-first',
        'photo_url': saved_url,
        'inferred': inferred,
        'label': label,
        'electronics_category': category,
        'electronics': electronics_result,
        'urban_mining': urban_mining,
        'route': route,
        'notice': '사진 분석과 예상가치는 확정 매입가가 아니라 접수 전 안내입니다. 최종 금액은 파트너 검수와 데이터삭제 확인 후 달라질 수 있습니다.'
    }





# ============================================================
# v50.11 Urban mining + reusable parts detail engine
# ============================================================

def v5011_urban_mining_analysis(category: str, label: str = '', condition: str = 'unknown', quantity: int = 1, memo: str = '') -> Dict[str, Any]:
    qty = max(1, min(int(quantity or 1), 999))
    cat = v507_norm(category or label or '')
    laptop_parts = [
        {'name':'SSD/HDD 저장장치', 'location':'노트북 내부 저장장치 슬롯', 'reuse':'데이터삭제 후 중고부품 또는 물리파기', 'low':3000, 'high':30000, 'note':'개인정보 포함 가능성이 가장 높음'},
        {'name':'RAM 메모리', 'location':'메모리 슬롯 또는 온보드', 'reuse':'호환 모델이면 중고부품', 'low':3000, 'high':25000, 'note':'온보드는 분리 가치 낮음'},
        {'name':'액정/디스플레이 패널', 'location':'상판 화면부', 'reuse':'파손 없으면 수리부품', 'low':5000, 'high':60000, 'note':'화면 파손이면 가치 급감'},
        {'name':'메인보드', 'location':'키보드 하단 초록 회로기판', 'reuse':'수리부품 또는 PCB 도시광산', 'low':8000, 'high':70000, 'note':'CPU/GPU 온보드 모델은 부품가치 상승'},
        {'name':'배터리팩', 'location':'검은 리튬이온 배터리', 'reuse':'상태 양호 시 부품, 부풀음은 전문처리', 'low':0, 'high':20000, 'note':'부풀음·누액은 판매보다 안전처리 우선'},
        {'name':'쿨링팬/힌지/키보드', 'location':'팬, 힌지, 키보드부', 'reuse':'수리부품', 'low':1000, 'high':20000, 'note':'모델 호환성이 중요'},
        {'name':'충전기/어댑터', 'location':'별도 구성품', 'reuse':'정품이면 중고부품', 'low':3000, 'high':25000, 'note':'사진에 없으면 0원 처리'},
    ]
    laptop_materials = [
        {'material':'금 Au', 'where':'메인보드 접점, 커넥터, 일부 칩 패키지', 'amount':'약 0.02~0.15g 추정', 'recovery':'PCB 정련업체 회수', 'note':'1대 단독 회수보다 묶음 처리에서 의미 있음'},
        {'material':'은 Ag', 'where':'납땜, 접점, 회로부', 'amount':'약 0.2~1.0g 추정', 'recovery':'PCB 정련업체 회수', 'note':'모델·세대별 편차 큼'},
        {'material':'팔라듐 Pd', 'where':'적층세라믹콘덴서, 일부 전자부품', 'amount':'흔적량~0.05g 추정', 'recovery':'전문 정련', 'note':'정확량은 분해·정련 전 알 수 없음'},
        {'material':'구리 Cu', 'where':'메인보드 배선, 히트파이프, 케이블, 코일', 'amount':'약 50~250g 추정', 'recovery':'비철 회수', 'note':'노트북 크기와 히트싱크 구조에 따라 차이'},
        {'material':'알루미늄/마그네슘', 'where':'하판·상판 케이스, 방열판', 'amount':'약 300~900g 추정', 'recovery':'금속 회수', 'note':'그램/맥북류는 케이스 재질 영향 큼'},
        {'material':'리튬·코발트·니켈 계열', 'where':'리튬이온 배터리팩', 'amount':'배터리 화학계·용량에 따라 g 단위 변동', 'recovery':'배터리 전문 처리', 'note':'안전·화재 위험 때문에 일반 보관 금지'},
        {'material':'희토류 Nd 등', 'where':'스피커 자석, 진동모터, 일부 팬/자석 부품', 'amount':'약 0.1~2g 수준 추정', 'recovery':'소량은 단독 경제성 낮음', 'note':'희토류는 “존재”하지만 개별 1대 수익은 작음'},
    ]
    templates = {
        'laptop': {
            'title':'폐노트북 도시광산·부품 분석',
            'parts': laptop_parts,
            'materials': laptop_materials,
            'part_low': 23000, 'part_high': 220000,
            'material_low': 1500, 'material_high': 12000,
            'summary':'노트북은 금속 원재료보다 SSD/RAM/액정/메인보드 같은 재사용 부품 가치가 먼저입니다. 다만 메인보드·배터리·자석에는 금·은·팔라듐·구리·리튬계 금속·희토류가 포함될 수 있습니다.'
        },
        'smartphone': {
            'title':'폐휴대폰 도시광산·부품 분석',
            'parts': [
                {'name':'메인보드', 'location':'기기 내부 PCB', 'reuse':'부품폰/정련', 'low':2000, 'high':50000, 'note':'계정잠금·침수 여부 중요'},
                {'name':'디스플레이', 'location':'전면 화면', 'reuse':'수리부품', 'low':0, 'high':120000, 'note':'파손 없으면 가치 큼'},
                {'name':'카메라 모듈', 'location':'후면/전면 카메라', 'reuse':'수리부품', 'low':1000, 'high':40000, 'note':'고급기종일수록 상승'},
                {'name':'배터리', 'location':'내부 리튬이온 배터리', 'reuse':'전문처리', 'low':0, 'high':8000, 'note':'부풀음은 안전처리'}
            ],
            'materials': [
                {'material':'금 Au', 'where':'메인보드 접점·칩', 'amount':'약 0.01~0.05g 추정', 'recovery':'전문 정련', 'note':'수십~수백 대 묶음에서 의미'},
                {'material':'은 Ag/팔라듐 Pd', 'where':'회로·콘덴서', 'amount':'흔적량~소량', 'recovery':'전문 정련', 'note':'모델별 편차 큼'},
                {'material':'구리 Cu', 'where':'회로·코일·케이블', 'amount':'수 g~수십 g 추정', 'recovery':'비철 회수', 'note':'개별가치는 작음'},
                {'material':'리튬·코발트·니켈', 'where':'배터리', 'amount':'배터리 화학계에 따라 변동', 'recovery':'배터리 전문 처리', 'note':'안전처리 우선'},
                {'material':'희토류', 'where':'스피커·진동모터 자석', 'amount':'극소량', 'recovery':'묶음 처리', 'note':'단독 수익성 낮음'}
            ],
            'part_low': 5000, 'part_high': 220000,
            'material_low': 500, 'material_high': 5000,
            'summary':'휴대폰은 고급기종일수록 디스플레이·카메라·보드 부품가치가 크고, 도시광산 가치는 묶음 회수에서 의미가 커집니다.'
        },
        'desktop': {
            'title':'폐데스크탑 도시광산·부품 분석',
            'parts': [
                {'name':'그래픽카드 GPU', 'location':'PCIe 슬롯', 'reuse':'중고부품', 'low':0, 'high':700000, 'note':'RTX 등 고급 GPU면 핵심가치'},
                {'name':'CPU', 'location':'메인보드 소켓', 'reuse':'중고부품', 'low':3000, 'high':300000, 'note':'세대·등급 중요'},
                {'name':'RAM', 'location':'메모리 슬롯', 'reuse':'중고부품', 'low':2000, 'high':80000, 'note':'DDR4/DDR5 구분'},
                {'name':'SSD/HDD', 'location':'저장장치 베이', 'reuse':'데이터삭제 후 부품', 'low':2000, 'high':100000, 'note':'개인정보 확인 필수'},
                {'name':'파워/케이스/쿨러', 'location':'본체 내부', 'reuse':'부품/고철', 'low':1000, 'high':50000, 'note':'상태별 차이'}
            ],
            'materials': [
                {'material':'금 Au', 'where':'메인보드·CPU 접점·카드 접점', 'amount':'약 0.05~0.3g 추정', 'recovery':'PCB/CPU 정련', 'note':'부품세대별 편차 큼'},
                {'material':'구리 Cu', 'where':'파워, 케이블, 코일, 방열부', 'amount':'수백 g~1kg+ 추정', 'recovery':'비철 회수', 'note':'데스크탑은 구리 회수 비중 큼'},
                {'material':'알루미늄/철', 'where':'케이스·방열판', 'amount':'kg 단위', 'recovery':'금속 회수', 'note':'중량은 크지만 단가는 낮음'}
            ],
            'part_low': 25000, 'part_high': 900000,
            'material_low': 3000, 'material_high': 25000,
            'summary':'데스크탑은 도시광산보다 CPU·GPU·RAM·SSD 같은 중고부품 가치가 훨씬 크게 나올 수 있습니다.'
        }
    }
    key = 'laptop' if 'laptop' in cat or '노트북' in cat else 'smartphone' if 'smartphone' in cat or '휴대폰' in cat else 'desktop' if 'desktop' in cat or '컴퓨터' in cat or '본체' in cat else ''
    if not key:
        return {'available': False}
    t = templates[key].copy()
    # 상태별 현실 보정
    cond_factor = {'excellent':1.0, 'good':0.85, 'minor_damage':0.65, 'screen_broken':0.55, 'power_issue':0.45, 'dead':0.30, 'unknown':0.65}.get(condition or 'unknown', 0.65)
    part_low = int(t['part_low'] * cond_factor) * qty
    part_high = int(t['part_high'] * cond_factor) * qty
    material_low = int(t['material_low']) * qty
    material_high = int(t['material_high']) * qty
    t.update({
        'available': True,
        'category_key': key,
        'quantity': qty,
        'part_resale_low': part_low,
        'part_resale_high': part_high,
        'material_recovery_low': material_low,
        'material_recovery_high': material_high,
        'combined_low': part_low + material_low,
        'combined_high': part_high + material_high,
        'basis': '사진 기반 품목 추정 + 일반적인 부품/원재료 회수 가능성. 실제 함량과 가격은 모델·연식·상태·분해검수·시세에 따라 달라집니다.'
    })
    return t





# v50.12 enhanced urban mining for broader appliances
def v5011_urban_mining_analysis(category: str, label: str = '', condition: str = 'unknown', quantity: int = 1, memo: str = '') -> Dict[str, Any]:
    qty = max(1, min(int(quantity or 1), 999))
    cat = v507_norm(category or label or '')
    templates = {
        'laptop': {
            'title':'폐노트북 도시광산·부품 분석',
            'parts': [
                {'name':'SSD/HDD 저장장치','location':'노트북 내부 저장장치 슬롯','reuse':'데이터삭제 후 중고부품 또는 물리파기','low':3000,'high':30000,'note':'개인정보 포함 가능성이 가장 높음'},
                {'name':'RAM 메모리','location':'메모리 슬롯 또는 온보드','reuse':'호환 모델이면 중고부품','low':3000,'high':25000,'note':'온보드는 분리 가치 낮음'},
                {'name':'액정/디스플레이 패널','location':'상판 화면부','reuse':'파손 없으면 수리부품','low':5000,'high':60000,'note':'화면 파손이면 가치 급감'},
                {'name':'메인보드','location':'키보드 하단 초록 회로기판','reuse':'수리부품 또는 PCB 도시광산','low':8000,'high':70000,'note':'CPU/GPU 온보드 모델은 부품가치 상승'},
                {'name':'배터리팩','location':'검은 리튬이온 배터리','reuse':'상태 양호 시 부품, 부풀음은 전문처리','low':0,'high':20000,'note':'부풀음·누액은 판매보다 안전처리 우선'},
                {'name':'쿨링팬/힌지/키보드','location':'팬, 힌지, 키보드부','reuse':'수리부품','low':1000,'high':20000,'note':'모델 호환성이 중요'},
                {'name':'충전기/어댑터','location':'별도 구성품','reuse':'정품이면 중고부품','low':3000,'high':25000,'note':'사진에 없으면 0원 처리'},
            ],
            'materials': [
                {'material':'금 Au','where':'메인보드 접점, 커넥터, 일부 칩 패키지','amount':'약 0.02~0.15g 추정','recovery':'PCB 정련업체 회수','note':'1대 단독 회수보다 묶음 처리에서 의미 있음'},
                {'material':'은 Ag','where':'납땜, 접점, 회로부','amount':'약 0.2~1.0g 추정','recovery':'PCB 정련업체 회수','note':'모델·세대별 편차 큼'},
                {'material':'팔라듐 Pd','where':'적층세라믹콘덴서, 일부 전자부품','amount':'흔적량~0.05g 추정','recovery':'전문 정련','note':'정확량은 분해·정련 전 알 수 없음'},
                {'material':'구리 Cu','where':'메인보드 배선, 히트파이프, 케이블, 코일','amount':'약 50~250g 추정','recovery':'비철 회수','note':'노트북 크기와 구조에 따라 차이'},
                {'material':'리튬·코발트·니켈','where':'배터리팩','amount':'배터리 화학계·용량에 따라 변동','recovery':'배터리 전문 처리','note':'안전처리 우선'},
                {'material':'희토류 Nd 등','where':'스피커 자석, 팬·모터 자석','amount':'약 0.1~2g 수준 추정','recovery':'소량은 단독 경제성 낮음','note':'희토류는 존재하지만 묶음 회수 의미가 큼'},
            ],
            'part_low':23000,'part_high':220000,'material_low':1500,'material_high':12000,
            'summary':'노트북은 금속 원재료보다 SSD/RAM/액정/메인보드 같은 재사용 부품 가치가 먼저입니다.'
        },
        'smartphone': {
            'title':'폐휴대폰 도시광산·부품 분석',
            'parts': [
                {'name':'메인보드','location':'기기 내부 PCB','reuse':'부품폰/정련','low':2000,'high':50000,'note':'계정잠금·침수 여부 중요'},
                {'name':'디스플레이','location':'전면 화면','reuse':'수리부품','low':0,'high':120000,'note':'파손 없으면 가치 큼'},
                {'name':'카메라 모듈','location':'후면/전면 카메라','reuse':'수리부품','low':1000,'high':40000,'note':'고급기종일수록 상승'},
                {'name':'배터리','location':'내부 리튬이온 배터리','reuse':'전문처리','low':0,'high':8000,'note':'부풀음은 안전처리'}
            ],
            'materials': [
                {'material':'금 Au','where':'메인보드 접점·칩','amount':'약 0.01~0.05g 추정','recovery':'전문 정련','note':'수십~수백 대 묶음에서 의미'},
                {'material':'은 Ag/팔라듐 Pd','where':'회로·콘덴서','amount':'흔적량~소량','recovery':'전문 정련','note':'모델별 편차 큼'},
                {'material':'구리 Cu','where':'회로·코일·케이블','amount':'수 g~수십 g 추정','recovery':'비철 회수','note':'개별가치는 작음'},
                {'material':'리튬·코발트·니켈','where':'배터리','amount':'배터리 화학계에 따라 변동','recovery':'배터리 전문 처리','note':'안전처리 우선'},
                {'material':'희토류','where':'스피커·진동모터 자석','amount':'극소량','recovery':'묶음 처리','note':'단독 수익성 낮음'}
            ],
            'part_low':5000,'part_high':220000,'material_low':500,'material_high':5000,
            'summary':'휴대폰은 디스플레이·카메라·보드 부품 가치가 크고, 도시광산 가치는 묶음 회수에서 의미가 커집니다.'
        },
        'desktop': {
            'title':'폐데스크탑 도시광산·부품 분석',
            'parts': [
                {'name':'그래픽카드 GPU','location':'PCIe 슬롯','reuse':'중고부품','low':0,'high':700000,'note':'고급 GPU면 핵심가치'},
                {'name':'CPU','location':'메인보드 소켓','reuse':'중고부품','low':3000,'high':300000,'note':'세대·등급 중요'},
                {'name':'RAM','location':'메모리 슬롯','reuse':'중고부품','low':2000,'high':80000,'note':'DDR4/DDR5 구분'},
                {'name':'SSD/HDD','location':'저장장치 베이','reuse':'데이터삭제 후 부품','low':2000,'high':100000,'note':'개인정보 확인 필수'},
                {'name':'파워/케이스/쿨러','location':'본체 내부','reuse':'부품/고철','low':1000,'high':50000,'note':'상태별 차이'}
            ],
            'materials': [
                {'material':'금 Au','where':'메인보드·CPU 접점·카드 접점','amount':'약 0.05~0.3g 추정','recovery':'PCB/CPU 정련','note':'부품세대별 편차 큼'},
                {'material':'구리 Cu','where':'파워, 케이블, 코일, 방열부','amount':'수백 g~1kg+ 추정','recovery':'비철 회수','note':'데스크탑은 구리 회수 비중 큼'},
                {'material':'알루미늄/철','where':'케이스·방열판','amount':'kg 단위','recovery':'금속 회수','note':'중량은 크지만 단가는 낮음'}
            ],
            'part_low':25000,'part_high':900000,'material_low':3000,'material_high':25000,
            'summary':'데스크탑은 도시광산보다 CPU·GPU·RAM·SSD 같은 중고부품 가치가 훨씬 크게 나올 수 있습니다.'
        },
        'refrigerator': {
            'title':'폐냉장고 도시광산·부품 분석',
            'parts': [
                {'name':'압축기','location':'하단 후면','reuse':'금속 회수 또는 재생부품','low':5000,'high':50000,'note':'상태·규격에 따라 다름'},
                {'name':'선반·문짝 부속','location':'내부/도어','reuse':'재사용 가능 부품','low':0,'high':20000,'note':'일반적으로 부품가치 크지 않음'}
            ],
            'materials': [
                {'material':'구리 Cu','where':'배관, 모터 코일, 압축기 일부','amount':'수백 g~수 kg 추정','recovery':'비철 회수','note':'냉매 제거 후 해체'},
                {'material':'알루미늄','where':'열교환 핀','amount':'kg 단위 추정','recovery':'비철 회수','note':'구리와 혼합되어 처리'},
                {'material':'철','where':'외장, 내부 프레임','amount':'수십 kg','recovery':'고철 회수','note':'중량은 크지만 단가 낮음'}
            ],
            'part_low':3000,'part_high':70000,'material_low':5000,'material_high':40000,
            'summary':'냉장고는 재사용 부품보다 압축기·구리관·알루미늄·철 같은 금속 회수 비중이 더 큽니다.'
        },
        'washing_machine': {
            'title':'폐세탁기 도시광산·부품 분석',
            'parts': [
                {'name':'모터','location':'본체 하부','reuse':'재생부품 또는 금속 회수','low':5000,'high':40000,'note':'정상작동 시 부품가치 가능'},
                {'name':'제어보드','location':'상단 제어부','reuse':'수리부품 또는 PCB 처리','low':1000,'high':20000,'note':'침수·부식 여부 중요'}
            ],
            'materials': [
                {'material':'구리 Cu','where':'모터 코일, 배선','amount':'수백 g~1kg 수준','recovery':'비철 회수','note':'모터 해체 시 가치'},
                {'material':'스테인리스/철','where':'드럼·외장','amount':'kg 단위','recovery':'고철 회수','note':'중량가전 특성'}
            ],
            'part_low':3000,'part_high':50000,'material_low':4000,'material_high':30000,
            'summary':'세탁기는 모터와 금속 회수 가치가 핵심입니다.'
        },
        'aircon': {
            'title':'폐에어컨 도시광산·부품 분석',
            'parts': [
                {'name':'실외기 컴프레서','location':'실외기 내부','reuse':'재생부품 또는 금속 회수','low':10000,'high':80000,'note':'운반과 냉매처리 필요'},
                {'name':'실내기 보드','location':'실내기 제어부','reuse':'수리부품 또는 PCB 처리','low':1000,'high':20000,'note':'모델 의존성 큼'}
            ],
            'materials': [
                {'material':'구리 Cu','where':'배관, 코일, 모터','amount':'1~5kg+ 추정','recovery':'비철 회수','note':'에어컨은 구리 비중이 큼'},
                {'material':'알루미늄','where':'열교환 핀','amount':'kg 단위','recovery':'비철 회수','note':'구리와 혼합'},
                {'material':'철','where':'프레임·케이스','amount':'kg 단위','recovery':'고철 회수','note':'중량 큼'}
            ],
            'part_low':5000,'part_high':90000,'material_low':10000,'material_high':80000,
            'summary':'에어컨은 구리배관과 실외기 중심의 금속 회수 가치가 큽니다.'
        },
        'tv': {
            'title':'폐TV 도시광산·부품 분석',
            'parts': [
                {'name':'패널','location':'전면 화면','reuse':'정상일 때 수리부품','low':0,'high':50000,'note':'파손 시 가치 급감'},
                {'name':'메인보드/전원보드','location':'후면 내부','reuse':'수리부품 또는 PCB 처리','low':1000,'high':30000,'note':'모델별 차이'}
            ],
            'materials': [
                {'material':'구리/알루미늄','where':'보드, 스피커, 방열부','amount':'소량~중량','recovery':'금속 회수','note':'대형제품은 분해인건비 고려'},
                {'material':'희토류/자석류','where':'스피커 자석 등','amount':'소량','recovery':'묶음 회수','note':'단독경제성 낮음'}
            ],
            'part_low':2000,'part_high':50000,'material_low':1000,'material_high':10000,
            'summary':'TV는 대형 제품일수록 운반과 파손 리스크를 함께 봐야 합니다.'
        }
    }
    if 'laptop' in cat or '노트북' in cat: key='laptop'
    elif 'smartphone' in cat or '휴대폰' in cat or 'phone' in cat: key='smartphone'
    elif 'desktop' in cat or '컴퓨터' in cat or '본체' in cat: key='desktop'
    elif 'refrigerator' in cat or '냉장고' in cat: key='refrigerator'
    elif 'washing_machine' in cat or '세탁기' in cat: key='washing_machine'
    elif 'aircon' in cat or '에어컨' in cat: key='aircon'
    elif cat == 'tv' or 'tv' in cat or '텔레비전' in cat: key='tv'
    else: return {'available': False}
    t = templates[key].copy()
    cond_factor = {'excellent':1.0,'good':0.85,'minor_damage':0.65,'screen_broken':0.55,'power_issue':0.45,'dead':0.30,'unknown':0.65}.get(condition or 'unknown', 0.65)
    part_low = int(t['part_low'] * cond_factor) * qty
    part_high = int(t['part_high'] * cond_factor) * qty
    material_low = int(t['material_low']) * qty
    material_high = int(t['material_high']) * qty
    t.update({
        'available': True,
        'category_key': key,
        'quantity': qty,
        'part_resale_low': part_low,
        'part_resale_high': part_high,
        'material_recovery_low': material_low,
        'material_recovery_high': material_high,
        'combined_low': part_low + material_low,
        'combined_high': part_high + material_high,
        'basis': '사진·품목 기반 추정치입니다. 실제 함량과 금액은 모델·연식·상태·분해검수·시세·운반비에 따라 달라집니다.'
    })
    return t



# ============================================================
# v50.18 quick recovery commerce + project recruitment layer
# - 사진분석 결과에서 바로 중고형 판매글 생성 또는 수거신청으로 연결
# - 프로젝트 메뉴: 중고차/부품 소매 수익분배 파트너 모집
# ============================================================

def v5018_condition_label(value: Optional[str]) -> str:
    return {
        'excellent': '정상 작동/상태 좋음',
        'good': '사용 가능/생활기스',
        'screen_broken': '화면 파손',
        'minor_damage': '일부 파손',
        'power_issue': '전원 불량',
        'dead': '완전 고장',
        'unknown': '상태 확인 필요',
    }.get(value or 'unknown', value or '상태 확인 필요')

def v5018_money(n: int) -> str:
    try:
        return f"{int(n):,}원"
    except Exception:
        return '가격협의'

def v5018_price_band(low: int = 0, high: int = 0) -> Tuple[str, int]:
    low = max(0, int(low or 0)); high = max(0, int(high or 0))
    if high <= 0:
        return '가격협의', 0
    if low <= 0 or low > high:
        low = int(high * 0.65)
    return f"{v5018_money(low)} ~ {v5018_money(high)}", int((low + high) / 2)

def v5018_sale_prompt(data: SalePromptRequest) -> Dict[str, Any]:
    price_text, mid = v5018_price_band(data.estimated_low, data.estimated_high)
    item = (data.item or '품목 확인 필요').strip()
    model = (data.model or '').strip()
    condition_label = v5018_condition_label(data.condition)
    title_core = f"{model} {item}".strip() if model else item
    suggested_title = f"[자원잇다 검수예정] {title_core} 판매/부품용"
    prompt = f"""중고거래 판매글 초안

제목: {suggested_title}

본문:
- 품목: {item}
- 모델/브랜드: {model or '사진·라벨 확인 필요'}
- 상태: {condition_label}
- 예상 거래가: {price_text}
- 확인 필요: 전원 작동, 외관 파손, 구성품, 저장장치/개인정보 삭제 여부
- 거래 방식: 직거래 또는 파트너 검수 후 거래
- 안내: 사진 기반 1차 분석 결과이며 최종 가격은 실물 검수 후 달라질 수 있습니다.

구매자에게 숨기면 안 되는 내용:
1. 고장·파손·잠금·침수 여부
2. 배터리 부풀음 또는 안전 위험
3. 저장장치 포함 여부와 데이터 삭제 여부
4. 구성품 누락 여부

자원잇다 운영 메모:
- 판매 성공 또는 파트너 매칭 성공 시 플랫폼 수수료 예시: 건당 1,000원
- 법적 책임이 생길 수 있으므로 확정 판매 전 소유권과 하자 고지를 확인하세요.
""".strip()
    return {
        'ok': True,
        'route': 'used-market-lite',
        'title': suggested_title,
        'price_text': price_text,
        'recommended_mid_price': mid,
        'platform_fee_krw': 1000,
        'prompt': prompt,
        'checklist': ['소유권 확인', '하자·파손 고지', '저장장치/개인정보 삭제 확인', '사진 3장 이상 첨부', '최종가격은 실물검수 후 확정'],
        'next': '판매글을 복사해 중고형 판매로 진행하거나, 수거신청으로 전환할 수 있습니다.',
    }

@app.post('/api/recovery/sale-prompt')
def recovery_sale_prompt(data: SalePromptRequest):
    return v5018_sale_prompt(data)

@app.post('/api/recovery/quick-action')
def recovery_quick_action(data: QuickRecoveryRequest, request: Request):
    db = load_db()
    actor = 'guest'
    try:
        auth = request.headers.get('authorization', '')
        if auth:
            actor = current_user(request).get('id', 'guest')
    except Exception:
        actor = 'guest'
    row = data.model_dump()
    row.update({'id': now_id('quick'), 'actor': actor, 'created_at': time.time(), 'status': 'received'})
    if data.action == 'sell':
        prompt = v5018_sale_prompt(SalePromptRequest(**{k: row.get(k) for k in ['item','category','model','condition','estimated_low','estimated_high','memo']}))
        row['sale_prompt'] = prompt
        row['message'] = '중고형 판매글 초안이 생성되었습니다. 판매 성공 시 플랫폼 수수료 예시는 건당 1,000원입니다.'
    else:
        row['message'] = '자원 수거신청이 접수되었습니다. 담당자가 품목·주소·연락처를 확인한 뒤 즉시수거, 묶음수거, 관리자 검토 중 하나로 전환합니다.'
    db.setdefault('quick_actions', []).insert(0, row)
    db['quick_actions'] = db['quick_actions'][:300]
    save_db(db)
    audit('quick_recovery_action', actor, {'id': row['id'], 'action': data.action, 'item': data.item})
    return {'ok': True, 'request': row, 'message': row['message']}

@app.get('/api/projects')
def public_projects():
    db = load_db()
    return {'items': db.get('projects', []), 'version': APP_VERSION}

@app.post('/api/projects/apply')
def apply_project(data: ProjectApplication):
    db = load_db()
    projects = {p.get('id'): p for p in db.get('projects', [])}
    if data.project_id not in projects:
        raise HTTPException(404, '프로젝트를 찾을 수 없습니다.')
    row = data.model_dump()
    row.update({'id': now_id('projapp'), 'project_title': projects[data.project_id].get('title'), 'status': 'received', 'created_at': time.time()})
    db.setdefault('project_applications', []).insert(0, row)
    db['project_applications'] = db['project_applications'][:300]
    save_db(db)
    audit('project_application', data.company, {'id': row['id'], 'project_id': data.project_id})
    return {'ok': True, 'application': row, 'message': '프로젝트 참여 신청이 접수되었습니다. 담당자가 허가·역할·수익분배 조건을 검토합니다.'}

@app.get('/api/admin/quick-actions')
def admin_quick_actions(request: Request):
    require_admin(request)
    return {'items': load_db().get('quick_actions', [])}

@app.get('/api/admin/project-applications')
def admin_project_applications(request: Request):
    require_admin(request)
    return {'items': load_db().get('project_applications', [])}

# Serve uploaded preview files before the catch-all static mount.
app.mount('/uploads', StaticFiles(directory=UPLOADS), name='uploads')



# --- v51.09 v50base structural compatibility aliases: keep the v50.20 structure but provide simple top-level URLs used during deployment tests. ---
@app.get('/admin-dashboard.html', include_in_schema=False)
def admin_dashboard_alias():
    return FileResponse(STATIC / 'admin-dashboard.html')

@app.get('/partner-dashboard.html', include_in_schema=False)
def partner_dashboard_alias():
    return FileResponse(STATIC / 'partner-dashboard.html')

@app.get('/company-dashboard.html', include_in_schema=False)
def company_dashboard_alias():
    return FileResponse(STATIC / 'company-dashboard.html')

@app.get('/my-requests.html', include_in_schema=False)
def my_requests_alias():
    return FileResponse(STATIC / 'my-requests.html')

@app.get('/docs', include_in_schema=False)
def docs_alias():
    return FileResponse(STATIC / 'document-center.html')


# ============================================================
# v51.09 structural compatibility APIs
# - Add stable aliases and partner-center endpoints so old/new pages do not 404.
# ============================================================
@app.get('/api/admin/summary')
def admin_summary_alias(request: Request):
    return admin_overview(request)

@app.get('/api/partner/dashboard')
def partner_dashboard_api(request: Request):
    u = current_user(request)
    if u['role'] not in ['partner', 'enterprise', 'admin']:
        raise HTTPException(403, '업체센터 권한이 필요합니다.')
    db = load_db()
    pickups = db.get('pickup_requests', [])
    bids = db.get('partner_bids', [])
    return {'ok': True, 'user': u, 'summary': {'pickup_candidates': len(pickups), 'my_bids': len([b for b in bids if b.get('partner_id') == u.get('id')]), 'plan': u.get('plan'), 'trustScore': u.get('trustScore', 0)}, 'recommended': ['권역별 묶음수거 확인', '수거동선 계산', '입찰방 제안 등록']}

@app.get('/api/partner/pickups')
def partner_pickups_api(request: Request, region: str = '', material: str = ''):
    u = current_user(request)
    if u['role'] not in ['partner', 'enterprise', 'admin']:
        raise HTTPException(403, '업체센터 권한이 필요합니다.')
    rows = load_db().get('pickup_requests', [])
    if region:
        rows = [x for x in rows if region in str(x.get('address','')) or region in str(x.get('region',''))]
    if material:
        rows = [x for x in rows if material in str(x.get('material','')) or material in str(x.get('item',''))]
    return {'ok': True, 'items': rows[:200]}

@app.post('/api/partner/routes/plan')
def partner_routes_plan_api(data: RouteRequest, request: Request):
    u = current_user(request)
    if u['role'] not in ['partner', 'enterprise', 'admin']:
        raise HTTPException(403, '업체센터 권한이 필요합니다.')
    result = route_optimize(data, request)
    db = load_db()
    db.setdefault('route_plans', []).append({'id': now_id('route'), 'user': u['id'], 'request': data.model_dump(), 'result': result, 'created_at': time.time()})
    save_db(db)
    return result

@app.get('/api/partner/bids')
def partner_bids_api(request: Request):
    u = current_user(request)
    if u['role'] not in ['partner', 'enterprise', 'admin']:
        raise HTTPException(403, '업체센터 권한이 필요합니다.')
    rows = load_db().get('partner_bids', [])
    if u['role'] != 'admin':
        rows = [x for x in rows if x.get('partner_id') == u.get('id')]
    return {'ok': True, 'items': rows}

@app.post('/api/partner/bids')
def partner_bid_create_api(data: Dict[str, Any], request: Request):
    u = current_user(request)
    if u['role'] not in ['partner', 'enterprise', 'admin']:
        raise HTTPException(403, '업체센터 권한이 필요합니다.')
    db = load_db()
    row = {'id': now_id('pbid'), 'partner_id': u['id'], 'partner_name': u.get('name'), 'status': 'submitted', 'created_at': time.time(), **data}
    db.setdefault('partner_bids', []).insert(0, row)
    save_db(db)
    audit('partner_bid_create', u['id'], {'id': row['id']})
    return {'ok': True, 'bid': row}

@app.get('/api/admin/partner-bids')
def admin_partner_bids_api(request: Request):
    require_admin(request)
    return {'ok': True, 'items': load_db().get('partner_bids', [])}


@app.get('/api/v51/system-check')
def v51_system_check():
    required = ['index.html','disposal-guide.html','waste-value.html','resource-recovery.html','projects.html','pricing.html','notices.html','help.html','dashboards/admin.html','dashboards/partner.html','route.html','bidrooms.html']
    return {'ok': all((STATIC / p).exists() for p in required), 'version': APP_VERSION, 'base': 'v50.20_checked_stable + v51.09 structural audit fallback/buttons/admin/footer', 'pages': {p: (STATIC / p).exists() for p in required}}



# ============================================================
# v51.10 API-ready production bridge
# - External services are not required for MVP demo.
# - When keys/URLs are added to Render Environment, these endpoints switch from safe-mock to ready state.
# ============================================================
class ModelDiagnoseRequest(BaseModel):
    item: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    condition: Optional[str] = 'unknown'
    weight: float = 0
    memo: Optional[str] = None

class GeocodeRequest(BaseModel):
    address: str

class SmsRequest(BaseModel):
    to: Optional[str] = None
    message: str
    channel: str = 'sms'

class CheckoutRequest(BaseModel):
    order_id: Optional[str] = None
    amount: int = 0
    order_name: str = '자원잇다 서비스 이용료'
    customer_name: Optional[str] = None

class GenericWebhookPayload(BaseModel):
    provider: str = 'unknown'
    event: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

def integration_matrix() -> List[Dict[str, Any]]:
    groups = [
        ('AI 자원분류 모델', 'MODEL_API_URL', 'MODEL_API_KEY', '사진/품목을 S~D·E-risk 등급으로 판단하는 내부 모델'),
        ('OCR 문서분석', 'OCR_API_URL', 'OCR_API_KEY', '사업자등록증·허가증·차량등록증 추출'),
        ('지도/지오코딩', 'KAKAO_REST_API_KEY', 'KAKAO_MAP_JS_KEY', '주소 좌표화·지도 표시'),
        ('도로망 수거동선', 'ROUTE_API_URL', 'ROUTE_API_KEY', '실제 거리/시간 기반 차량 동선 최적화'),
        ('결제', 'TOSS_SECRET_KEY', 'PORTONE_API_KEY', '요금제·중고형 판매 수수료 결제'),
        ('문자/알림톡', 'SOLAPI_API_KEY', 'KAKAO_ALIMTALK_KEY', '접수·배정·완료 알림'),
        ('사업자 검증', 'BIZNO_API_KEY', 'BIZNO_API_URL', '업체 사업자/허가 검증'),
        ('파일저장소', 'S3_BUCKET', 'AWS_ACCESS_KEY_ID', '첨부·사진·증명서 운영 저장'),
    ]
    rows=[]
    vault=load_api_vault()
    for name, primary, secondary, purpose in groups:
        vals=[os.getenv(primary) or vault.get(primary), os.getenv(secondary) or vault.get(secondary)]
        ready=any(bool(v) for v in vals)
        rows.append({'name': name, 'primary_env': primary, 'secondary_env': secondary, 'purpose': purpose, 'mode': 'real-ready' if ready else 'safe-mock', 'configured': ready})
    return rows

@app.get('/api/integrations/status')
def integrations_status():
    rows=integration_matrix()
    return {'ok': True, 'version': APP_VERSION, 'summary': {'total': len(rows), 'configured': len([r for r in rows if r['configured']]), 'safe_mock': len([r for r in rows if not r['configured']])}, 'items': rows, 'next': 'Render Environment Variables 또는 관리자 API 연동센터에 키를 넣으면 safe-mock에서 real-ready로 전환됩니다.'}

@app.get('/api/admin/integrations/status')
def admin_integrations_status(request: Request):
    require_admin(request)
    return integrations_status()

@app.post('/api/model/diagnose')
def model_diagnose(data: ModelDiagnoseRequest):
    # Internal model team can replace this safe fallback with an HTTP call to MODEL_API_URL.
    model_url = get_config_value('MODEL_API_URL')
    if model_url:
        return {'ok': True, 'mode': 'real-ready-pending-adapter', 'model_url_configured': True, 'message': 'MODEL_API_URL이 설정되어 있습니다. 운영 어댑터 연결 시 실제 모델 결과로 교체됩니다.'}
    item=(data.item or data.model or data.category or '관리자 검토 필요')
    cond=(data.condition or 'unknown').lower()
    if any(k in cond for k in ['new','good','정상','양호','작동']): grade='S'; route='중고형 판매'
    elif any(k in cond for k in ['repair','수리','일부','배터리','액정']): grade='A'; route='수리 후 재판매'
    elif any(k in cond for k in ['broken','고장','파손','부품']): grade='B'; route='부품 회수'
    else: grade='C'; route='원자재 회수/관리자 검토'
    risk = any(k in item for k in ['휴대폰','노트북','하드','SSD','블랙박스','CCTV'])
    return {'ok': True, 'mode': 'safe-mock', 'grade': grade, 'risk_flags': ['개인정보 삭제 확인 필요'] if risk else [], 'recommended_route': route, 'item': item, 'confidence': 0.72, 'message': '내부 모델 연결 전 안전 데모 결과입니다.'}

@app.post('/api/maps/geocode')
def maps_geocode(data: GeocodeRequest):
    if get_config_value('KAKAO_REST_API_KEY') or get_config_value('NAVER_MAP_CLIENT_ID'):
        return {'ok': True, 'mode': 'real-ready-pending-adapter', 'address': data.address, 'message': '지도 API 키가 설정되어 있습니다. 운영 어댑터 연결 시 실제 좌표를 반환합니다.'}
    return {'ok': True, 'mode': 'safe-mock', 'address': data.address, 'lat': 35.1527, 'lng': 126.8910, 'message': '광주 중심 좌표 기반 데모값입니다.'}

@app.post('/api/notifications/send')
def notifications_send(data: SmsRequest, request: Request):
    # In demo mode, store notification intent instead of sending SMS.
    db=load_db()
    row={'id': now_id('noti'), 'to': data.to or '', 'message': data.message, 'channel': data.channel, 'mode': 'real-ready' if get_config_value('SOLAPI_API_KEY') else 'safe-mock', 'created_at': time.time()}
    db.setdefault('notification_queue', []).insert(0,row)
    save_db(db)
    return {'ok': True, 'queued': row, 'message': '문자 API 연결 전에는 발송 대신 큐에 저장됩니다.'}

@app.post('/api/payments/checkout')
def payments_checkout(data: CheckoutRequest, request: Request):
    oid=data.order_id or now_id('order')
    mode='real-ready' if (get_config_value('TOSS_SECRET_KEY') or get_config_value('PORTONE_API_KEY')) else 'safe-mock'
    db=load_db(); row={'id': oid, 'amount': data.amount, 'order_name': data.order_name, 'customer_name': data.customer_name, 'status': 'prepared', 'mode': mode, 'created_at': time.time()}; db.setdefault('payment_orders', []).insert(0,row); save_db(db)
    return {'ok': True, 'order': row, 'checkout_url': '' if mode=='safe-mock' else '/external/payment/checkout', 'message': '결제 API 연결 전에는 결제 준비 상태까지만 저장합니다.'}

@app.post('/api/webhooks/external')
def external_webhook(data: GenericWebhookPayload):
    db=load_db(); row={'id': now_id('webhook'), 'provider': data.provider, 'event': data.event, 'payload': data.payload, 'created_at': time.time()}; db.setdefault('webhooks', []).insert(0,row); save_db(db)
    return {'ok': True, 'received': row['id']}

@app.get('/api/business/readiness')
def business_readiness():
    required_pages=['index.html','disposal-guide.html','waste-value.html','resource-recovery.html','projects.html','partner-dashboard.html','company-dashboard.html','admin-dashboard.html','route.html','help.html','pricing.html','notices.html']
    pages={p:(STATIC/p).exists() for p in required_pages}
    integrations=integration_matrix()
    return {'ok': all(pages.values()), 'version': APP_VERSION, 'pages': pages, 'api_ready': {r['name']: r['mode'] for r in integrations}, 'launch_blockers': ['실제 AI 모델 API 연결', '지도/문자/결제 실서비스 키 등록', '폐기물·운반·보안파기 계약/법무 검토']}

# Mount static last so /api routes are not shadowed.
app.mount('/', StaticFiles(directory=STATIC, html=True), name='static')
