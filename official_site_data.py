"""KARiN. 公式情報の第一正本（Python source-of-truth）。

サイト表示・予約定数・①公式Knowledge が将来同じ事実を参照するためのモジュール。
Flask / Supabase / OpenAI には依存しない。

このモジュールは:
- source_key → 公式事実 を管理する
- source_key → UUID は管理しない（UUIDはDBの物理ID）

① official Knowledge のみ、将来このデータから同期する。
② notes / ③ health はここから上書きしない。

リアルタイム空き枠・スタッフシフト・予約可否の判定ロジックは持たない。
トータルコンディショニングは個別アプローチではなく、予約・料金上のコース名称。
"""
from __future__ import annotations

import math
from typing import Any, Callable

# ①公式Knowledge の source_type。同期対象はこれだけ。
OFFICIAL_SOURCE_TYPE = "official"

TAX_RATE = 0.10

SITE_BASE_URL = "https://karin-sb.jp"
LINE_URL = "https://lin.ee/rVEbNhl5"
PHONE = "090-8154-9313"
EMAIL = "info@karin-sb.jp"

# ---------------------------------------------------------------------------
# 税込算出（公開表示用）。管理画面 JS の Math.floor(税抜 * 1.1) に合わせる。
# コース料金の canonical は税抜整数円。
# ---------------------------------------------------------------------------


def tax_included_yen(tax_excluded_yen: int) -> int:
    return math.floor(int(tax_excluded_yen) * (1 + TAX_RATE))


def price_pair(tax_excluded_yen: int) -> dict[str, int]:
    return {
        "tax_excluded_yen": int(tax_excluded_yen),
        "tax_included_yen": tax_included_yen(tax_excluded_yen),
    }


# ---------------------------------------------------------------------------
# 状態
# available: 現在利用可 / preparing: 準備中 / hidden: 非公開
# ---------------------------------------------------------------------------

STATUS_AVAILABLE = "available"
STATUS_PREPARING = "preparing"
STATUS_HIDDEN = "hidden"

# ---------------------------------------------------------------------------
# 連絡先
# ---------------------------------------------------------------------------

CONTACT = {
    "line_url": LINE_URL,
    "phone": PHONE,
    "email": EMAIL,
    "contact_page_path": "/contact",
    "booking_page_path": "/book",
}

# ---------------------------------------------------------------------------
# 対応エリア・基本営業時間
# 公開サイト本文（index.html）を現時点の正しい基本時間とする。
# OG の「受付10:00〜19:00」は採用しない。
# 空き枠・シフトは持たない。
# ---------------------------------------------------------------------------

AREAS = {
    "tokyo": {
        "id": "tokyo",
        "label": "東京",
        "hub": "代々木上原",
        "hub_note": "代々木上原中心",
        "travel_from": "代々木上原駅",
        "hours_start": "12:00",
        "hours_end": "26:00",
        "holiday": "不定休",
        "selectable": True,
        "booking_selectable": True,
    },
    "fukuoka": {
        "id": "fukuoka",
        "label": "福岡",
        "hub": "薬院",
        "hub_note": "薬院中心",
        "travel_from": "薬院駅",
        "hours_start": "10:00",
        "hours_end": "19:00",
        "holiday": "不定休",
        "selectable": True,
        "booking_selectable": True,
    },
}

# ---------------------------------------------------------------------------
# 施術場所
# ---------------------------------------------------------------------------

PLACE_TYPES = {
    "visit": {
        "id": "visit",
        "label": "出張",
        "status": STATUS_AVAILABLE,
        "web_bookable": True,
        "is_current_primary": True,
        "note": "ご自宅・会社・ホテル・レンタルスペースなど、ご指定の場所へ伺う。",
    },
    "in_house": {
        "id": "in_house",
        "label": "院内",
        "status": STATUS_PREPARING,
        "web_bookable": False,
        "is_current_primary": False,
        "public_label": "院内（準備中）",
        "note": "現在は出張施術を中心に承っており、院内施術については準備中。",
    },
    "field": {
        "id": "field",
        "label": "帯同",
        "status": STATUS_AVAILABLE,
        "web_bookable": False,
        "is_current_primary": False,
        "note": "トレーナー帯同。公開Web予約の対象外。LINEまたはお問い合わせ。",
    },
}

# ---------------------------------------------------------------------------
# 個別アプローチ（サービス一覧）
# トータルコンディショニングはここに入れない。
# ---------------------------------------------------------------------------

APPROACHES = [
    {
        "id": "acupuncture",
        "label": "鍼灸",
        "summary": "その日の身体の状態を見ながら、痛みや不調、疲労、コンディションを内側から整える。",
    },
    {
        "id": "seitai_conditioning",
        "label": "整体・コンディショニング",
        "summary": "姿勢・可動域・筋肉の状態など身体全体のバランスを見ながら、動きやすい状態を目指す。",
    },
    {
        "id": "beauty_acupuncture",
        "label": "美容鍼",
        "summary": "お顔だけでなく身体全体の状態にも目を向けながら行う、整える考え方のひとつ。",
    },
    {
        "id": "training",
        "label": "トレーニング",
        "summary": "整えた身体を使える身体へ。姿勢や動き、筋力を整え、良い状態を維持する。",
    },
]

ADJUNCT_APPROACHES = [
    "ストレッチ",
    "リコンディショニング",
    "筋膜へのアプローチ",
    "カッピング",
    "コンプレフロス",
    "アクティベーター",
    "オイルトリートメント",
]

# ---------------------------------------------------------------------------
# 提供形態（サイトのサービス枠）
# ---------------------------------------------------------------------------

OFFERINGS = {
    "visit_treatment": {
        "id": "visit_treatment",
        "label": "出張施術・コンディショニング",
        "status": STATUS_AVAILABLE,
        "summary": "鍼灸・整体・トレーニングなどを、身体の状態や目的に合わせて組み合わせて提供する。",
    },
    "trainer_accompany": {
        "id": "trainer_accompany",
        "label": "トレーナー帯同",
        "status": STATUS_AVAILABLE,
        "web_bookable": False,
        "summary": "スポーツ・エンターテインメントの現場に帯同し、コンディショニングから身体のケアまでサポートする。",
    },
    "corporate": {
        "id": "corporate",
        "label": "法人向けコンディショニング",
        "status": STATUS_AVAILABLE,
        "web_bookable": False,
        "summary": "福利厚生や従業員の健康サポートなど、企業・団体のニーズに合わせたコンディショニングを相談できる。",
    },
}

# ---------------------------------------------------------------------------
# 予約・料金上のコース
# total_conditioning は個別サービスではなく、組み合わせ提供のメニュー名・料金単位。
# ---------------------------------------------------------------------------

BOOKING_COURSES = {
    "total_conditioning": {
        "id": "total_conditioning",
        "kind": "booking_course",
        "label": "トータルコンディショニング",
        "public": True,
        "status": STATUS_AVAILABLE,
        "place_types": ["visit"],
        "durations_minutes": (120, 90, 60),
        "combines_approaches": True,
        "description": (
            "ユーザーの状態・目的に応じて、鍼灸・整体・美容鍼・トレーニング等を"
            "組み合わせて提供するときの予約・料金上のコース名称。"
            "個別サービス一覧とは別概念。"
        ),
        "prices_tax_excluded": {
            "tokyo": {120: 20000, 90: 15000, 60: 10000},
            "fukuoka": {120: 16000, 90: 12000, 60: 8000},
        },
    },
    "shinkyu_only": {
        "id": "shinkyu_only",
        "kind": "booking_course",
        "label": "鍼灸のみ",
        "public": False,
        "status": STATUS_PREPARING,
        "place_types": ["in_house"],
        "durations_minutes": (90, 60, 30),
        "combines_approaches": False,
        "description": "鍼灸メインの院内施術コース。現在は公開準備中。",
        "prices_tax_excluded": {
            "tokyo": {90: 12000, 60: 8000, 30: 4000},
            "fukuoka": {90: 9000, 60: 6000, 30: 3000},
        },
    },
}

# 公開サイトと同じ税込額（出張費・オイル・帯同は税区分がコード上不明なため、掲載額をそのまま保持）
TRAVEL_FEES_PUBLISHED = {
    "unit": "yen_as_published",
    "brackets": (
        {"max_km": 5, "amount_yen": 1000, "label": "5km圏内"},
        {"max_km": 10, "amount_yen": 2000, "label": "10km圏内"},
        {"max_km": 15, "amount_yen": 3000, "label": "15km圏内"},
        {"max_km": None, "amount_yen": None, "label": "それ以上", "note": "要相談"},
    ),
    "note": "レンタルスペースやスタジオをご希望の場合、別途レンタル費用をご負担いただく場合がある。",
}

ADD_ON_OIL = {
    "id": "oil_treatment",
    "label": "オイルトリートメント",
    "amount_yen_per_hour": 3000,
    "pricing_basis": "published_on_price_page",
    "note": "トータルコンディショニングに追加する場合、+3,000円 / 1時間（料金表掲載額）。",
}

TRAINER_ACCOMPANY_RATE = {
    "amount_yen_from": 55000,
    "unit": "per_day",
    "pricing_basis": "published_on_price_page",
    "note": "現場の内容・拘束時間・移動距離により変動。東京・福岡どちらも対応。法人契約・年間・スポットも相談可。",
}

# ---------------------------------------------------------------------------
# 初回30%OFF（正式ルール）
# 60分限定ではない。管理画面の「60分：30%OFF」表記は後の修正対象。
# ---------------------------------------------------------------------------

FIRST_VISIT_DISCOUNT = {
    "id": "first_visit_discount",
    "active": True,
    "percent_off": 30,
    "first_visit_only": True,
    "requires_line_registration": True,
    "applies_to_first_treatment": True,
    "duration_restricted": False,
    "menu_restricted": False,
    "restricted_minutes": None,
    "web_booking_ok_if_line_registered": True,
    "how_to_apply": "ご予約後、当日担当者にLINE登録済みである旨を伝える。",
    "end_date": None,
}

# ---------------------------------------------------------------------------
# 予約方法・公開されている予約条件
# 判定ロジック（枠の○×、シフト照合）は予約システム側。ここは公開事実のみ。
# ---------------------------------------------------------------------------

BOOKING_METHODS = {
    "web": {
        "id": "web",
        "label": "Web予約",
        "path": "/book",
        "for": "日時・メニューが決まっている方",
        "note": "空き状況の確認と予約確定は既存予約システムが行う。",
    },
    "line": {
        "id": "line",
        "label": "公式LINE",
        "url": LINE_URL,
        "for": "相談してから決めたい方、帯同・直前の相談",
    },
    "contact_form": {
        "id": "contact_form",
        "label": "お問い合わせフォーム",
        "path": "/contact",
        "for": "トレーナー帯同・法人・その他の相談",
    },
}

WEB_BOOKING_POLICY = {
    "min_lead_minutes": 12 * 60,
    "min_lead_hours": 12,
    "days_ahead": 14,
    "slot_step_minutes": 15,
    "within_lead_time_channel": "LINEまたはお問い合わせフォーム",
    "field_not_web_bookable": True,
    "in_house_web_bookable": False,
    "appointment_only": True,
}

AFTER_HOURS_CONSULTATION = {
    "available": True,
    "guaranteed": False,
    "channels": ("line", "contact_form"),
    "note": (
        "基本営業時間以外をご希望の場合も、可能な限り対応する。"
        "必ず対応できる保証ではない。"
        "LINEまたはお問い合わせフォームから相談する。"
    ),
}

BASIC_INFO = {
    "brand": "KARiN.",
    "legal_name": "KARiN. ~Sports & Beauty~",
    "summary": (
        "鍼灸・整体・トレーニング・コンディショニングなどを、"
        "身体の状態や目的に合わせて組み合わせて提供している。"
    ),
    "appointment_only": True,
    "current_primary_place": "visit",
}

TREATMENT_POLICY = {
    "need_not_choose_menu_in_advance": True,
    "combines_by_condition_and_goal": True,
    "summary": (
        "何を受ければいいか分からない場合でも相談できる。"
        "状態や目的を確認したうえで、必要な施術内容を組み合わせる。"
    ),
}


# ---------------------------------------------------------------------------
# 参照ヘルパー（サイト・予約が後から使う）
# ---------------------------------------------------------------------------


def course_public_prices(course_id: str, area_id: str) -> dict[int, dict[str, int]]:
    """分数 → 税抜/税込。canonical は税抜。"""
    course = BOOKING_COURSES[course_id]
    raw = (course.get("prices_tax_excluded") or {}).get(area_id) or {}
    return {int(minutes): price_pair(amount) for minutes, amount in raw.items()}


def area_hours_label(area_id: str) -> str:
    area = AREAS[area_id]
    return f"{area['hours_start']}〜{area['hours_end']}"


# ---------------------------------------------------------------------------
# ① Knowledge 用: source_key → 検索用文章
# 同期処理は未実装。将来ここから title / content / category を生成する。
# ---------------------------------------------------------------------------


def _join(*parts: str) -> str:
    return "".join(p.strip() for p in parts if p and p.strip())


def _content_basic_info() -> str:
    return _join(
        BASIC_INFO["summary"],
        "完全予約制。",
        "東京（代々木上原中心）と福岡（薬院中心）を拠点に、現在は出張施術を中心に提供している。",
        "トータルコンディショニングは独立した個別サービスではなく、",
        "状態・目的に応じて複数のアプローチを組み合わせる提供形態・予約コースの名称である。",
    )


def _content_treatment_policy() -> str:
    return TREATMENT_POLICY["summary"]


def _content_approaches() -> str:
    lines = [
        "KARiN.の個別アプローチは次のとおり。トータルコンディショニングはここに含めない。",
    ]
    for item in APPROACHES:
        lines.append(f"{item['label']}：{item['summary']}")
    lines.append("必要に応じて次も組み合わせる。" + "、".join(ADJUNCT_APPROACHES) + "。")
    return "".join(lines)


def _content_dispatch_service() -> str:
    visit = PLACE_TYPES["visit"]
    return _join(
        "現在の主な提供形態は出張施術である。",
        visit["note"],
        "東京・福岡に対応。完全予約制。",
    )


def _content_in_house_status() -> str:
    return PLACE_TYPES["in_house"]["note"]


def _content_trainer_accompany() -> str:
    rate = TRAINER_ACCOMPANY_RATE
    return _join(
        OFFERINGS["trainer_accompany"]["summary"],
        f"目安料金は1日 {rate['amount_yen_from']:,}円から。{rate['note']}",
        "公開Web予約の対象外。LINEまたはお問い合わせフォームから相談する。",
    )


def _content_booking_courses() -> str:
    tc = BOOKING_COURSES["total_conditioning"]
    so = BOOKING_COURSES["shinkyu_only"]
    tc_dur = "、".join(f"{m}分" for m in tc["durations_minutes"])
    so_dur = "、".join(f"{m}分" for m in so["durations_minutes"])
    return _join(
        f"予約・料金上のコース「{tc['label']}」は、{tc['description']}",
        f"公開中の時間は{tc_dur}。",
        f"「{so['label']}」は院内向けで、現在は準備中。時間は{so_dur}。",
    )


def _content_visit_course_prices() -> str:
    tc = BOOKING_COURSES["total_conditioning"]
    chunks = [
        "出張のトータルコンディショニング公開料金（税込）。"
        "料金の正本は税抜で管理し、公開税込は税率10%で算出している。"
    ]
    for area_id, area in AREAS.items():
        pairs = course_public_prices("total_conditioning", area_id)
        parts = [
            f"{m}分 {pairs[m]['tax_included_yen']:,}円"
            for m in tc["durations_minutes"]
            if m in pairs
        ]
        chunks.append(f"{area['label']}：{'、'.join(parts)}。")
    return "".join(chunks)


def _content_travel_fees() -> str:
    chunks = ["出張費は拠点からの距離の目安。"]
    for area in AREAS.values():
        chunks.append(f"{area['label']}は{area['travel_from']}から。")
    for b in TRAVEL_FEES_PUBLISHED["brackets"]:
        if b["amount_yen"] is None:
            chunks.append(f"{b['label']}は{b.get('note') or '要相談'}。")
        else:
            chunks.append(f"{b['label']} {b['amount_yen']:,}円。")
    chunks.append(TRAVEL_FEES_PUBLISHED["note"])
    return "".join(chunks)


def _content_add_on_oil() -> str:
    return ADD_ON_OIL["note"]


def _content_tokyo_business_hours() -> str:
    a = AREAS["tokyo"]
    return _join(
        f"東京（{a['hub_note']}）の基本営業時間は{area_hours_label('tokyo')}。",
        f"定休日は{a['holiday']}。",
        "これは基本時間であり、時間外を絶対に受け付けないという意味ではない。",
    )


def _content_fukuoka_business_hours() -> str:
    a = AREAS["fukuoka"]
    return _join(
        f"福岡（{a['hub_note']}）の基本営業時間は{area_hours_label('fukuoka')}。",
        f"定休日は{a['holiday']}。",
        "これは基本時間であり、時間外を絶対に受け付けないという意味ではない。",
    )


def _content_after_hours_consultation() -> str:
    p = AFTER_HOURS_CONSULTATION
    return _join(
        "基本営業時間はサイト記載の時間。",
        p["note"],
        "リアルタイムの空きやスタッフ稼働状況は、この情報からは分からない。",
    )


def _content_areas() -> str:
    parts = ["対応エリアは東京と福岡。"]
    for a in AREAS.values():
        parts.append(f"{a['label']}は{a['hub_note']}。")
    parts.append("現在は出張施術が中心。")
    return "".join(parts)


def _content_first_visit_discount() -> str:
    d = FIRST_VISIT_DISCOUNT
    return _join(
        "初回の方で、公式LINEに登録している場合、初回施術を30%OFFで利用できる。",
        "対象時間・メニューに制限はない。60分限定ではない。",
        "Webから予約した場合でも、LINEに登録していれば初回30%OFFを利用できる。",
        d["how_to_apply"],
        f"割引率は{d['percent_off']}%。終了日の設定はない（end_date未設定）。",
    )


def _content_booking_methods() -> str:
    return _join(
        "予約・相談の方法は、Web予約、公式LINE、お問い合わせフォーム。",
        "日時・メニューが決まっている方はWeb予約。",
        "相談してから決めたい方、帯同・直前の相談はLINEまたはお問い合わせ。",
        "トレーナー帯同・法人はお問い合わせまたはLINE。",
        "完全予約制。空き枠の有無はこの情報だけでは分からない。",
    )


def _content_web_booking_lead_time() -> str:
    p = WEB_BOOKING_POLICY
    return _join(
        f"Web予約は、開始時刻の{p['min_lead_hours']}時間前まで。",
        f"{p['min_lead_hours']}時間以内の枠はWeb予約できない。",
        f"その場合は{p['within_lead_time_channel']}を利用する。",
        f"Web予約で見られる日数は当日を含め概ね{p['days_ahead']}日先まで。",
        "実際にその時間が空いているかは予約システムで確認する。",
        "この条件は公開されている予約条件であり、空き枠そのものではない。",
    )


def _content_contact_channels() -> str:
    return _join(
        f"公式LINE：{CONTACT['line_url']}。",
        f"電話：{CONTACT['phone']}。",
        f"メール：{CONTACT['email']}。",
        "お問い合わせフォーム：/contact。",
        "Web予約：/book。",
    )


def _content_corporate_offering() -> str:
    return _join(
        OFFERINGS["corporate"]["summary"],
        "公開Web予約の対象外。お問い合わせフォームまたはLINEから相談する。",
    )


KNOWLEDGE_DOCUMENTS: dict[str, dict[str, Any]] = {
    "basic_info": {
        "source_key": "basic_info",
        "title": "KARiN.基本情報",
        "category": "service",
        "source_url": f"{SITE_BASE_URL}/",
        "build_content": _content_basic_info,
    },
    "treatment_policy": {
        "source_key": "treatment_policy",
        "title": "施術について",
        "category": "service",
        "source_url": f"{SITE_BASE_URL}/treatment",
        "build_content": _content_treatment_policy,
    },
    "approaches": {
        "source_key": "approaches",
        "title": "KARiN.の個別アプローチ",
        "category": "service",
        "source_url": f"{SITE_BASE_URL}/treatment",
        "build_content": _content_approaches,
    },
    "dispatch_service": {
        "source_key": "dispatch_service",
        "title": "出張施術",
        "category": "service",
        "source_url": f"{SITE_BASE_URL}/",
        "build_content": _content_dispatch_service,
    },
    "in_house_status": {
        "source_key": "in_house_status",
        "title": "現在の院内施術",
        "category": "service",
        "source_url": f"{SITE_BASE_URL}/book",
        "build_content": _content_in_house_status,
    },
    "trainer_accompany": {
        "source_key": "trainer_accompany",
        "title": "トレーナー帯同",
        "category": "service",
        "source_url": f"{SITE_BASE_URL}/price",
        "build_content": _content_trainer_accompany,
    },
    "booking_courses": {
        "source_key": "booking_courses",
        "title": "予約コース",
        "category": "reservation",
        "source_url": f"{SITE_BASE_URL}/book",
        "build_content": _content_booking_courses,
    },
    "visit_course_prices": {
        "source_key": "visit_course_prices",
        "title": "出張コース料金",
        "category": "pricing",
        "source_url": f"{SITE_BASE_URL}/price",
        "build_content": _content_visit_course_prices,
    },
    "travel_fees": {
        "source_key": "travel_fees",
        "title": "出張費",
        "category": "pricing",
        "source_url": f"{SITE_BASE_URL}/price",
        "build_content": _content_travel_fees,
    },
    "add_on_oil": {
        "source_key": "add_on_oil",
        "title": "オイルトリートメント追加料金",
        "category": "pricing",
        "source_url": f"{SITE_BASE_URL}/price",
        "build_content": _content_add_on_oil,
    },
    "tokyo_business_hours": {
        "source_key": "tokyo_business_hours",
        "title": "東京の基本営業時間",
        "category": "faq",
        "source_url": f"{SITE_BASE_URL}/",
        "build_content": _content_tokyo_business_hours,
    },
    "fukuoka_business_hours": {
        "source_key": "fukuoka_business_hours",
        "title": "福岡の基本営業時間",
        "category": "faq",
        "source_url": f"{SITE_BASE_URL}/",
        "build_content": _content_fukuoka_business_hours,
    },
    "after_hours_consultation": {
        "source_key": "after_hours_consultation",
        "title": "営業時間外の相談",
        "category": "faq",
        "source_url": f"{SITE_BASE_URL}/",
        "build_content": _content_after_hours_consultation,
    },
    "areas": {
        "source_key": "areas",
        "title": "対応エリア",
        "category": "service",
        "source_url": f"{SITE_BASE_URL}/",
        "build_content": _content_areas,
    },
    "first_visit_discount": {
        "source_key": "first_visit_discount",
        "title": "初回30%OFFについて",
        "category": "pricing",
        "source_url": f"{SITE_BASE_URL}/lp",
        "build_content": _content_first_visit_discount,
    },
    "booking_methods": {
        "source_key": "booking_methods",
        "title": "予約方法",
        "category": "reservation",
        "source_url": f"{SITE_BASE_URL}/book",
        "build_content": _content_booking_methods,
    },
    "web_booking_lead_time": {
        "source_key": "web_booking_lead_time",
        "title": "Web予約の受付条件",
        "category": "reservation",
        "source_url": f"{SITE_BASE_URL}/book",
        "build_content": _content_web_booking_lead_time,
    },
    "contact_channels": {
        "source_key": "contact_channels",
        "title": "問い合わせ先",
        "category": "faq",
        "source_url": f"{SITE_BASE_URL}/contact",
        "build_content": _content_contact_channels,
    },
    "corporate_offering": {
        "source_key": "corporate_offering",
        "title": "法人向けコンディショニング",
        "category": "service",
        "source_url": f"{SITE_BASE_URL}/contact",
        "build_content": _content_corporate_offering,
    },
}

SOURCE_KEYS: tuple[str, ...] = tuple(KNOWLEDGE_DOCUMENTS.keys())


def iter_knowledge_payloads() -> list[dict[str, Any]]:
    """①同期用。source_type は常に official。id/UUID は含めない。"""
    rows = []
    for key, spec in KNOWLEDGE_DOCUMENTS.items():
        builder: Callable[[], str] = spec["build_content"]
        rows.append(
            {
                "source_key": key,
                "title": spec["title"],
                "content": builder(),
                "category": spec["category"],
                "source_type": OFFICIAL_SOURCE_TYPE,
                "source_url": spec["source_url"],
            }
        )
    return rows


def get_knowledge_payload(source_key: str) -> dict[str, Any]:
    spec = KNOWLEDGE_DOCUMENTS[source_key]
    builder: Callable[[], str] = spec["build_content"]
    return {
        "source_key": source_key,
        "title": spec["title"],
        "content": builder(),
        "category": spec["category"],
        "source_type": OFFICIAL_SOURCE_TYPE,
        "source_url": spec["source_url"],
    }
