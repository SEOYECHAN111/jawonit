from __future__ import annotations

from sqlalchemy.orm import Session
from app import models


def get_or_create(db: Session, model, defaults=None, **kwargs):
    row = db.query(model).filter_by(**kwargs).first()
    if row:
        return row
    data = dict(kwargs)
    if defaults:
        data.update(defaults)
    row = model(**data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def seed(db: Session) -> dict:
    categories = [
        ("smartphone", "폐휴대폰/스마트폰", ["휴대폰", "스마트폰", "아이폰", "갤럭시", "iphone", "galaxy"], "중고폰/부품폰/도시광산", "매우 높음", 2500, ["본인 소유 확인", "잠금해제", "유심 제거", "IMEI 확인", "데이터삭제"]),
        ("tablet", "태블릿", ["태블릿", "아이패드", "갤럭시탭", "ipad"], "중고/부품/디스플레이", "높음", 3000, ["계정 로그아웃", "잠금해제", "데이터삭제"]),
        ("laptop", "폐노트북", ["노트북", "랩탑", "맥북", "그램", "갤럭시북", "laptop", "macbook"], "중고/부품/보드/저장매체", "매우 높음", 6000, ["SSD/HDD 삭제", "전원 상태", "액정 파손", "배터리 부풀음"]),
        ("desktop", "폐데스크탑/PC 본체", ["데스크탑", "PC", "컴퓨터", "본체", "workstation"], "중고부품/보드/CPU/RAM/저장매체", "높음", 9000, ["저장장치 삭제", "CPU/RAM/GPU 확인", "기업 자산번호"]),
        ("monitor", "모니터/디스플레이", ["모니터", "display", "lcd", "oled"], "중고/패널/부품", "낮음", 1500, ["화면 파손", "전원", "인치", "스탠드 포함"]),
        ("server", "서버/NAS/네트워크 장비", ["서버", "NAS", "랙서버", "라우터", "스위치"], "중고장비/부품/저장매체", "매우 높음", 12000, ["디스크 삭제", "관리자 비밀번호 초기화", "기업 자산 반출"]),
        ("storage", "HDD/SSD/저장장치", ["HDD", "SSD", "하드", "외장하드", "USB"], "데이터삭제/부품/금속", "매우 높음", 800, ["데이터 삭제", "물리 파기 여부", "용량", "SMART 상태"]),
        ("pc_parts", "PC 부품", ["그래픽카드", "GPU", "RAM", "CPU", "메인보드", "파워"], "중고부품/보드/희소금속", "낮음~중간", 3500, ["모델명", "핀 휨", "작동 확인"]),
        ("camera_audio", "카메라/오디오/게임기", ["카메라", "렌즈", "오디오", "게임기", "플레이스테이션", "닌텐도"], "수집가치/중고/부품", "낮음~중간", 1500, ["모델명", "작동", "구성품", "희소성"]),
    ]
    cat_map = {}
    for code, name, aliases, route, sec, floor, checks in categories:
        cat_map[code] = get_or_create(
            db, models.DeviceCategory,
            code=code,
            defaults={"name": name, "aliases": aliases, "default_route": route, "security_level": sec, "urban_mining_floor": floor, "checklist": checks},
        )

    manufacturers = [
        ("Apple", "Apple", ["애플", "아이폰", "맥북", "아이패드"]),
        ("Samsung", "Samsung", ["삼성", "갤럭시", "갤럭시북"]),
        ("LG", "LG", ["엘지", "그램"]),
        ("Lenovo", "Lenovo", ["레노버", "ThinkPad", "씽크패드"]),
        ("Dell", "Dell", ["델", "PowerEdge", "XPS"]),
        ("HP", "HP", ["HPE", "ProLiant"]),
        ("Sony", "Sony", ["소니", "PlayStation"]),
        ("Nintendo", "Nintendo", ["닌텐도", "Switch"]),
        ("NVIDIA", "NVIDIA", ["RTX", "GTX"]),
    ]
    man_map = {}
    for ko, en, aliases in manufacturers:
        man_map[ko.lower()] = get_or_create(db, models.Manufacturer, name_ko=ko, defaults={"name_en": en, "aliases": aliases})

    model_seed = [
        ("smartphone", "Apple", "iPhone 12", "iPhone", ["아이폰12", "iphone12"], 2020, 120000, 5000, 450000, 1.0, [("128GB", 128, None, None, None, None, 1.05), ("256GB", 256, None, None, None, None, 1.18)]),
        ("smartphone", "Apple", "iPhone 13", "iPhone", ["아이폰13", "iphone13"], 2021, 180000, 8000, 550000, 1.0, [("128GB", 128, None, None, None, None, 1.0), ("256GB", 256, None, None, None, None, 1.16)]),
        ("smartphone", "Samsung", "Galaxy S21", "Galaxy S", ["갤럭시 S21", "갤s21", "s21"], 2021, 90000, 3000, 350000, 0.95, [("128GB", 128, None, None, None, None, 1.0), ("256GB", 256, None, None, None, None, 1.15)]),
        ("smartphone", "Samsung", "Galaxy S23", "Galaxy S", ["갤럭시 S23", "s23"], 2023, 180000, 5000, 600000, 1.1, [("256GB", 256, None, None, None, None, 1.0), ("512GB", 512, None, None, None, None, 1.2)]),
        ("smartphone", "Samsung", "Galaxy Z Fold", "Galaxy Z", ["폴드", "z fold", "갤럭시 폴드"], 2022, 220000, 8000, 900000, 1.0, [("256GB", 256, None, None, None, None, 1.0)]),
        ("laptop", "Apple", "MacBook Air M1", "MacBook", ["맥북에어 m1", "m1 맥북", "macbook air"], 2020, 420000, 20000, 900000, 1.15, [("8GB/256GB", 256, 8, "M1", None, "13", 1.0), ("16GB/512GB", 512, 16, "M1", None, "13", 1.25)]),
        ("laptop", "LG", "LG gram", "gram", ["엘지그램", "그램", "lg그램"], 2021, 220000, 10000, 800000, 0.95, [("i5/16GB/512GB", 512, 16, "i5", None, "14~16", 1.0)]),
        ("laptop", "Samsung", "Galaxy Book", "Galaxy Book", ["갤럭시북", "galaxybook"], 2021, 180000, 8000, 700000, 0.9, [("i5/16GB/512GB", 512, 16, "i5", None, "15", 1.0)]),
        ("laptop", "Lenovo", "ThinkPad X1", "ThinkPad", ["씽크패드 x1", "thinkpad x1"], 2020, 220000, 10000, 800000, 1.0, [("i7/16GB/512GB", 512, 16, "i7", None, "14", 1.1)]),
        ("desktop", "Dell", "OptiPlex", "OptiPlex", ["옵티플렉스", "사무용 pc"], 2019, 80000, 5000, 350000, 0.8, [("i5/8GB/256GB", 256, 8, "i5", None, None, 1.0)]),
        ("desktop", "Dell", "Precision Workstation", "Precision", ["워크스테이션", "precision"], 2020, 250000, 15000, 1200000, 1.0, [("Xeon/32GB", None, 32, "Xeon", None, None, 1.2)]),
        ("pc_parts", "NVIDIA", "GeForce RTX 3060", "RTX", ["rtx3060", "3060"], 2021, 180000, 10000, 500000, 1.1, [("12GB", None, None, None, "RTX 3060", None, 1.0)]),
        ("pc_parts", "NVIDIA", "GeForce RTX 4070", "RTX", ["rtx4070", "4070"], 2023, 420000, 20000, 900000, 1.2, [("12GB", None, None, None, "RTX 4070", None, 1.0)]),
    ]
    for cat_code, man_name, model_name, family, aliases, year, base, minv, maxv, demand, variants in model_seed:
        model = get_or_create(
            db,
            models.DeviceModel,
            manufacturer_id=man_map[man_name.lower()].id,
            model_name=model_name,
            defaults={
                "category_id": cat_map[cat_code].id,
                "model_family": family,
                "aliases": aliases,
                "release_year": year,
                "base_value": base,
                "min_value": minv,
                "max_value": maxv,
                "demand_factor": demand,
            },
        )
        for variant_name, storage, ram, cpu, gpu, screen, mult in variants:
            get_or_create(
                db, models.ModelVariant,
                model_id=model.id,
                variant_name=variant_name,
                defaults={"storage_gb": storage, "ram_gb": ram, "cpu": cpu, "gpu": gpu, "screen_size": screen, "value_multiplier": mult},
            )

    rules = [
        ("condition", "new", "미개봉/새제품", 1.15, None),
        ("condition", "excellent", "정상 작동/상태 좋음", 1.0, None),
        ("condition", "good", "사용 가능/생활기스", 0.82, None),
        ("condition", "minor_damage", "일부 파손/부품 교체 필요", 0.55, "상태 확인 후 감가가 적용됩니다."),
        ("condition", "screen_broken", "화면 파손", 0.38, "화면 파손은 부품폰/수리용 가치로 계산됩니다."),
        ("condition", "power_issue", "전원 불량", 0.22, "전원 불량은 관리자 검수가 필요할 수 있습니다."),
        ("condition", "dead", "완전 고장/부품용", 0.12, "완전 고장은 도시광산 또는 부품 회수 기준으로 계산됩니다."),
        ("condition", "unknown", "상태 모름", 0.32, "상태 미확인은 관리자 검토 대상입니다."),
        ("age", "0_1", "1년 이내", 1.15, None),
        ("age", "1_3", "1~3년", 1.0, None),
        ("age", "3_5", "3~5년", 0.63, None),
        ("age", "5_8", "5~8년", 0.32, None),
        ("age", "8_plus", "8년 이상", 0.14, None),
        ("age", "unknown", "연식 모름", 0.45, "연식 미확인은 낮은 신뢰도로 계산됩니다."),
        ("security", "unlocked", "잠금해제/초기화 가능", 1.0, "데이터삭제 확인 필요"),
        ("security", "locked", "잠금해제 불가", 0.18, "잠금해제 불가 기기는 거래 제한 또는 소유 확인 대상입니다."),
        ("security", "business", "기관/기업 저장매체 포함", 0.82, "전문 데이터삭제 확인서가 필요합니다."),
        ("security", "removed", "저장매체 제거 완료", 0.92, "저장매체 제거 확인이 필요합니다."),
        ("security", "none", "저장매체 없음", 1.0, None),
        ("security", "unknown", "확인 필요", 0.75, "저장매체 및 계정 상태 확인이 필요합니다."),
    ]
    for rule_type, code, label, factor, warning in rules:
        get_or_create(db, models.ValuationRule, rule_type=rule_type, code=code, defaults={"label": label, "factor": factor, "warning": warning})

    return {
        "categories": len(categories),
        "manufacturers": len(manufacturers),
        "models": len(model_seed),
        "rules": len(rules),
    }
