"""KARiN. 一般健康Knowledge（③ health）の正本。

一般的な健康相談の補助知識を source_key → 本文 として保持する。
Flask / Supabase / OpenAI には依存しない。UUIDは持たない。

このモジュールは:
- source_type は常に health
- 診断データベースではない（病名・原因・治療の断定をしない）
- KARiN.の料金・営業時間・予約・施術メニュー・キャンペーンは書かない
- 施術効果を保証しない
- official_site_data.py / notes_ai_data.py から同期しない
- C1の安全ゲートを置き換えない

DB投入・Embedding生成・RAG接続は、このファイルの役割ではない。
"""
from __future__ import annotations

import re
from typing import Any, Callable

HEALTH_SOURCE_TYPE = "health"
HEALTH_CATEGORY = "health"


def _join(*parts: str) -> str:
    return "".join(p.strip() for p in parts if p and p.strip())


def _content_general() -> str:
    return _join(
        "これは一般的な健康相談の基本方針である。個人の診断や病名の判定には使わない。",
        "いまの症状だけから、原因を決めることはできない。",
        "同じようなつらさでも、生活のリズム、動き方、疲労、睡眠、体質など、背景は人によって違う。",
        "いつからなのか、良くなっているのか、悪化しているのかによって、考え方が変わることもある。",
        "「この症状ならこの病気」「これが原因」「これをすれば治る」とは言わない。",
        "数日たっても改善しない、悪化する、普段と明らかに違う変化がある場合は、医療機関への相談を検討する。",
        "一時的な疲れや、よくある肩こり・腰痛まで、一律に病院へ送る必要はない。",
        "特定の店舗の料金、予約の可否、施術メニューの効果は、このKnowledgeでは扱わない。",
    )


def _content_back_pain() -> str:
    return _join(
        "腰の痛みや違和感についての、一般的な健康知識である。腰痛という病名の診断には使わない。",
        "腰のつらさは、長時間同じ姿勢でいること、運動量の変化、筋肉や関節の状態、",
        "睡眠や疲労、日常生活の動き方など、いくつかの要因が重なっていることがある。",
        "痛い場所が、そのまま原因であるとは限らない。",
        "「腰痛＝この病気」「腰が悪いからこうなる」と決めつけない。",
        "無理のない範囲で姿勢を変えたり、痛みが強くならない程度に身体を動かしたりすることは、一般的な工夫の一つである。",
        "痛みが強い、足のしびれや力が入りにくさが進む、発熱や急な悪化がある場合は、医療機関への相談を検討する。",
        "通常の腰のだるさまで、自動的に受診を勧める必要はない。施術の効果はこのKnowledgeでは分からない。",
    )


def _content_shoulder_neck() -> str:
    return _join(
        "肩こりや首の違和感についての、一般的な健康知識である。病名の診断には使わない。",
        "肩や首のつらさは、日常の姿勢、長時間同じ姿勢でいること、活動量、疲労、睡眠など、",
        "複数の要因が関係していることがある。",
        "「肩こりの原因はこれです」と断定しない。肩だけを切り離して考えないこともある。",
        "同じ向きで固まり続けない、こまめに動かす、負担が強い動きを急に増やさない、などは一般的な工夫である。",
        "急に首が回らない、腕や手のしびれが強い、力が入りにくい、痛みが急速に悪化する場合は、医療機関への相談を検討する。",
        "よくある肩こりだけを、一律に病院へ送る必要はない。特定の施術で治る、とは言わない。",
    )


def _content_sleep() -> str:
    return _join(
        "睡眠についての一般的な健康知識である。睡眠障害の診断や治療方針の決定には使わない。",
        "睡眠は時間の長さだけでなく、質も大切だと考えられている。",
        "就寝と起床の時刻をなるべく一定にすること、就寝前の強い光や刺激を減らすこと、",
        "日中にある程度身体を動かすこと、カフェインなどの摂取タイミングに気をつけること、などが一般的な工夫である。",
        "「これだけ眠れば治る」「この方法で必ず眠れる」とは言わない。",
        "個人の生活に合うやり方は一つではない。",
        "日中の強い眠気、呼吸が苦しくなるような睡眠、急に悪化した不眠が続く場合は、医療機関への相談を検討する。",
        "数日程度の寝つきの悪さだけを、直ちに病気と決めつけない。",
    )


def _content_hydration() -> str:
    return _join(
        "水分補給についての一般的な健康知識である。必要な飲水量を一人ひとりに断定しない。",
        "汗をかくとき、暑い環境、運動時は、脱水に注意して水分補給を意識するとよい、というのが一般的な考え方である。",
        "のどの渇きだけに頼らず、状況に応じて少しずつ補給することがある。",
        "どれだけ飲めばよいかは、気温、活動量、体質、持病などによって違う。",
        "「毎日この量を飲めば健康になる」とは言わない。",
        "めまいや強いだるさ、尿が極端に減る、意識がはっきりしないなど、重い変化がある場合は医療機関への相談を優先する。",
        "特定の施術や予約の判断には使わない。",
    )


def _content_heat_illness() -> str:
    return _join(
        "暑さや熱中症についての一般的な安全知識である。熱中症かどうかの診断には使わない。",
        "暑い環境では、体調の変化に注意する。涼しい場所へ移動する、衣服をゆるめる、",
        "水分や電解質の補給を意識する、無理に動き続けない、などが一般的な対応の例である。",
        "このKnowledgeは緊急判定そのものではない。緊急の症状判定は、別の安全処理が担当する。",
        "「この条件なら熱中症である」「こうすれば必ず防げる」とは言わない。",
        "意識がおかしい、けいれん、自分で水分が取れない、など重い様子がある場合は、医療や救急への相談を優先する。",
        "暑い日の一般的な注意と、店舗の予約可否は別である。",
    )


def _content_exercise() -> str:
    return _join(
        "運動についての一般的な安全知識である。運動処方やトレーニングメニューの作成には使わない。",
        "体調に合わせて強度を調整する。急に負荷を大きく上げない。痛みが強いときは無理をしない。",
        "始めたばかりの時期は、短い時間や弱い負荷から慣らしていく、というのが一般的な考え方である。",
        "「毎日これをすれば必ず良くなる」「この種目が正しい」とは言わない。",
        "運動中に強い胸の痛み、息の苦しさ、意識がおかしいなどの変化があれば、中止して医療対応を優先する。",
        "このKnowledgeは緊急判定そのものではない。緊急の症状判定は、別の安全処理が担当する。",
        "特定の施術の効果や、今すぐ運動を始めるべきかどうかの断定には使わない。",
    )


KNOWLEDGE_DOCUMENTS: dict[str, dict[str, Any]] = {
    "health_general": {
        "source_key": "health_general",
        "title": "一般的な健康相談の基本方針",
        "category": HEALTH_CATEGORY,
        "build_content": _content_general,
    },
    "health_back_pain": {
        "source_key": "health_back_pain",
        "title": "腰の痛みに関する一般的な健康知識",
        "category": HEALTH_CATEGORY,
        "build_content": _content_back_pain,
    },
    "health_shoulder_neck": {
        "source_key": "health_shoulder_neck",
        "title": "肩こり・首の違和感に関する一般的な健康知識",
        "category": HEALTH_CATEGORY,
        "build_content": _content_shoulder_neck,
    },
    "health_sleep": {
        "source_key": "health_sleep",
        "title": "睡眠に関する一般的な健康知識",
        "category": HEALTH_CATEGORY,
        "build_content": _content_sleep,
    },
    "health_hydration": {
        "source_key": "health_hydration",
        "title": "水分補給に関する一般的な健康知識",
        "category": HEALTH_CATEGORY,
        "build_content": _content_hydration,
    },
    "health_heat_illness": {
        "source_key": "health_heat_illness",
        "title": "暑さ・熱中症に関する一般的な安全知識",
        "category": HEALTH_CATEGORY,
        "build_content": _content_heat_illness,
    },
    "health_exercise": {
        "source_key": "health_exercise",
        "title": "運動に関する一般的な安全知識",
        "category": HEALTH_CATEGORY,
        "build_content": _content_exercise,
    },
}

SOURCE_KEYS: tuple[str, ...] = tuple(KNOWLEDGE_DOCUMENTS.keys())


def iter_knowledge_payloads() -> list[dict[str, Any]]:
    """③ health 用。source_type は常に health。id/UUID は含めない。"""
    rows = []
    for key, spec in KNOWLEDGE_DOCUMENTS.items():
        builder: Callable[[], str] = spec["build_content"]
        rows.append(
            {
                "source_key": key,
                "title": spec["title"],
                "content": builder(),
                "category": spec["category"],
                "source_type": HEALTH_SOURCE_TYPE,
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
        "source_type": HEALTH_SOURCE_TYPE,
    }


def validate_health_payloads() -> list[str]:
    """DBに触れず、構造と境界を検証する。問題があればメッセージを返す。"""
    errors: list[str] = []
    payloads = iter_knowledge_payloads()

    if len(payloads) != 7:
        errors.append(f"件数は7件であるべきです: {len(payloads)}")

    keys = [p["source_key"] for p in payloads]
    if keys != list(SOURCE_KEYS):
        errors.append("source_key の並びが定義と一致しません")
    if len(keys) != len(set(keys)):
        errors.append("source_key が重複しています")

    required_phrases = {
        "health_general": ("原因を決めることはできない", "一律に病院へ送る必要はない", "診断"),
        "health_back_pain": ("長時間同じ姿勢", "決めつけない", "医療機関への相談"),
        "health_shoulder_neck": ("日常の姿勢", "断定しない", "一律に病院へ送る必要はない"),
        "health_sleep": ("質も大切", "睡眠障害の診断", "就寝"),
        "health_hydration": ("のどの渇きだけに頼らず", "断定しない"),
        "health_heat_illness": ("涼しい場所", "緊急判定そのものではない", "救急"),
        "health_exercise": ("急に負荷", "緊急判定そのものではない", "無理をしない"),
    }

    forbidden_patterns = (
        r"\d[\d,]*円",
        r"30\s*%",
        r"12:00",
        r"26:00",
        r"lin\.ee",
        r"090-",
        r"KARiN",
        r"初回",
        r"キャンペーン",
        r"営業時間",
        r"出張",
        r"院内",
        r"美容鍼",
        r"整体で",
        r"鍼は",
        r"効きます",
        r"治ります",
        r"原因です",
        r"○○病",
    )

    identity_fields = {"id", "uuid", "embedding"}
    for payload in payloads:
        key = payload["source_key"]
        if not str(key).startswith("health_"):
            errors.append(f"{key}: health_ 接頭辞がありません")
        if payload.get("source_type") != HEALTH_SOURCE_TYPE:
            errors.append(f"{key}: source_type が health ではありません")
        if payload.get("category") != HEALTH_CATEGORY:
            errors.append(f"{key}: category が health ではありません")
        if any(field in payload for field in identity_fields):
            errors.append(f"{key}: UUID/embedding をpayloadに含めてはいけません")
        content = payload.get("content") or ""
        if not content.strip():
            errors.append(f"{key}: content が空です")
        title = (payload.get("title") or "").strip()
        expected_title = KNOWLEDGE_DOCUMENTS[key]["title"]
        if title != expected_title:
            errors.append(f"{key}: title が仕様と一致しません")
        for phrase in required_phrases.get(key, ()):
            if phrase not in content:
                errors.append(f"{key}: 必要な文言がありません: {phrase}")
        for pattern in forbidden_patterns:
            if re.search(pattern, content):
                errors.append(f"{key}: 禁止パターンが含まれます: {pattern}")
        if "必ず治る" in content:
            errors.append(f"{key}: 効果保証に見える文言があります")

    return errors


if __name__ == "__main__":
    payloads = iter_knowledge_payloads()
    print("health payloads:", len(payloads))
    print("source_type:", HEALTH_SOURCE_TYPE)
    print()
    for item in payloads:
        print(f"{item['source_key']}")
        print(f"  title: {item['title']}")
        print(f"  category: {item['category']}")
        print(f"  chars: {len(item['content'])}")
        print()
    problems = validate_health_payloads()
    if problems:
        print("validation: FAIL")
        for msg in problems:
            print("-", msg)
        raise SystemExit(1)
    print("validation: PASS")
    print("DB/Embedding/RAG: 未接続（このモジュールは正本のみ）")
