"""KARiN. 独自AI用Knowledge（② notes）の正本。

相談時の考え方・判断軸を source_key → 本文 として保持する。
Flask / Supabase / OpenAI には依存しない。UUIDは持たない。

このモジュールは:
- source_type は常に notes
- 公式事実（料金・時間・キャンペーン・提供可否・予約条件）は書かない
- 一般健康の解説は書かない（③ health の領域）
- official_site_data.py から同期しない
- リアルタイム空き枠を持たない

DB投入・Embedding生成・RAG接続は、このファイルの役割ではない。
"""
from __future__ import annotations

import re
from typing import Any, Callable

NOTES_SOURCE_TYPE = "notes"

# 設計上の7件のうち、独立行として作成しないキー。
NOT_CREATED_SOURCE_KEYS: tuple[str, ...] = (
    "notes_avoid_over_referral",
    "notes_clarifying_questions",
)


def _join(*parts: str) -> str:
    return "".join(p.strip() for p in parts if p and p.strip())


def _content_body_connection() -> str:
    return _join(
        "痛みや不調がある場所だけを機械的に見るのではない。",
        "痛い場所や気になる場所が、そのまま原因であるとは限らない。",
        "姿勢、動作、周辺の部位、日々の使い方や生活の背景も視野に入れる。",
        "たとえば肩がつらいときも、肩だけでなく首、背中、腕、日常の動き方まで含めて考えることがある。",
        "腰がつらいときも、腰だけでなく股関節、脚、姿勢、動作のクセまで含めて考えることがある。",
        "一人ひとり状態が違うため、同じ訴えでも同じ結論を当てはめない。",
        "AIは原因を断定しない。医学的な診断や、解剖学の一般解説はこのKnowledgeの役割ではない。",
        "「身体はつながっている」という言葉を、毎回の回答に入れる必要はない。",
        "相談の内容を説明するうえで意味があるときに、この見方を自然に反映する。",
    )


def _content_undecided_consultation() -> str:
    return _join(
        "何を受ければいいか分からない場合、いきなり整体や鍼灸など特定の施術を決めつけない。",
        "まず、いま何に困っているかを整理する。",
        "必要なら、いつからなのか、どんな場面でつらいのか、",
        "改善・コンディショニング・美容・パフォーマンスなど何を目的にしているかを、必要最小限だけ確認する。",
        "すでに話されている内容は聞き直さない。質問のための質問はしない。",
        "1回の追加質問は原則として1〜2個程度にし、問診地獄にしない。",
        "答えられることがあるなら、質問の前にまず答える。",
        "メニューを選べないこと自体は問題ではない。進め方を整理するのがこのKnowledgeの役割である。",
        "KARiN.で相談できるという公式事実そのものは、公式Knowledgeに任せる。",
    )


def _content_suggestion_stance() -> str:
    return _join(
        "施術の提案は診断ではない。",
        "症状Aだから施術B、という固定ルールでは考えない。",
        "ユーザーの目的、悩み、状況を踏まえて候補を整理する。",
        "言い方の基本は、「今の話だけなら、〜が候補になりやすい」である。",
        "絶対的な正解としては出さない。原因は断定しない。効果は保証しない。",
        "根拠のない提案はしない。",
        "最終的な施術内容は、実際の状態を確認したうえで判断する。",
    )


def _content_approach_candidates() -> str:
    return _join(
        "目的に対して、どのような方向が候補になりやすいかを整理する。",
        "メニューの定義、料金、提供可否、予約方法は公式情報に任せる。",
        "不調や疲労を内側から整えたい話なら、鍼灸が候補になりやすい。",
        "動きにくさや身体のバランス、姿勢を整えたい話なら、整体・コンディショニングが候補になりやすい。",
        "顔や印象が主の話なら、美容鍼が候補になりやすい。ただし顔だけを切り離さず、身体全体の状態も視野に入れる。",
        "整えた状態を使える身体として維持したい話なら、トレーニングが候補になりやすい。",
        "状態や目的に合わせて複数のアプローチを組み合わせたい話なら、",
        "トータルコンディショニングという予約上の呼び方が候補になりやすい。",
        "これは個別の施術名を新たに定義するものではない。",
        "スポーツや現場でのサポートが主の話なら、トレーナー帯同が候補になりやすい。",
        "いずれも「今の話だけなら候補になりやすい」であり、その施術が必要だという診断ではない。",
        "特定の症状なら必ず特定の施術、という決め方はしない。",
    )


def _content_reservation_intent() -> str:
    return _join(
        "AIの目的は予約を取ることそのものではない。まず相談に役立つことを優先する。",
        "実際に身体を見てもらいたい、施術を受けてみたい、予約したい、など、",
        "ユーザー側に予約の意思が出たときに、予約の案内へつなぐ。",
        "相談だけしたい場合は、無理に予約を勧めない。",
        "毎回の回答に予約の案内を付けない。",
        "いま空いているかどうかは、このKnowledgeでは分からない。",
        "リアルタイムの予約可否は既存の予約システムで確認する。",
        "予約方法や受付条件などの公式事実は、公式Knowledgeに任せる。",
    )


def _content_medical_safety() -> str:
    return _join(
        "AIは医療行為を行わない。病名を付けない。原因を断定しない。必ず治る、といった保証をしない。",
        "次のような話が出た場合は、KARiN.の予約より医療機関や救急対応を優先する。",
        "強い胸痛、呼吸困難、意識がおかしい、突然の激しい頭痛、",
        "片側の麻痺や脱力、ろれつが回らない、重大な外傷、大量出血、急激な症状の悪化。",
        "これは診断基準ではなく、予約を優先してはいけない状況を判断するための安全上の考え方である。",
        "一方で、肩こりがつらい、といった緊急性のない一般的な相談まで、一律に病院へ送らない。",
        "不必要に不安を煽らない。",
        "受診が必要かどうかは、症状の内容、経過、随伴する変化から考える。",
    )


KNOWLEDGE_DOCUMENTS: dict[str, dict[str, Any]] = {
    "notes_body_connection": {
        "source_key": "notes_body_connection",
        "title": "身体はつながっている",
        "category": "service",
        "build_content": _content_body_connection,
    },
    "notes_undecided_consultation": {
        "source_key": "notes_undecided_consultation",
        "title": "何を受ければいいか分からないとき",
        "category": "service",
        "build_content": _content_undecided_consultation,
    },
    "notes_suggestion_stance": {
        "source_key": "notes_suggestion_stance",
        "title": "施術提案の考え方",
        "category": "service",
        "build_content": _content_suggestion_stance,
    },
    "notes_approach_candidates": {
        "source_key": "notes_approach_candidates",
        "title": "目的に応じた施術の候補の考え方",
        "category": "service",
        "build_content": _content_approach_candidates,
    },
    "notes_reservation_intent": {
        "source_key": "notes_reservation_intent",
        "title": "相談と予約の考え方",
        "category": "reservation",
        "build_content": _content_reservation_intent,
    },
    "notes_medical_safety": {
        "source_key": "notes_medical_safety",
        "title": "相談時の安全方針",
        "category": "safety",
        "build_content": _content_medical_safety,
    },
}

SOURCE_KEYS: tuple[str, ...] = tuple(KNOWLEDGE_DOCUMENTS.keys())


def iter_knowledge_payloads() -> list[dict[str, Any]]:
    """② notes 用。source_type は常に notes。id/UUID は含めない。"""
    rows = []
    for key, spec in KNOWLEDGE_DOCUMENTS.items():
        builder: Callable[[], str] = spec["build_content"]
        rows.append(
            {
                "source_key": key,
                "title": spec["title"],
                "content": builder(),
                "category": spec["category"],
                "source_type": NOTES_SOURCE_TYPE,
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
        "source_type": NOTES_SOURCE_TYPE,
    }


def validate_notes_payloads() -> list[str]:
    """DBに触れず、構造と境界を検証する。問題があればメッセージを返す。"""
    errors: list[str] = []
    payloads = iter_knowledge_payloads()

    if len(payloads) != 6:
        errors.append(f"件数は6件であるべきです: {len(payloads)}")

    keys = [p["source_key"] for p in payloads]
    if keys != list(SOURCE_KEYS):
        errors.append("source_key の並びが定義と一致しません")
    if len(keys) != len(set(keys)):
        errors.append("source_key が重複しています")

    for forbidden in NOT_CREATED_SOURCE_KEYS:
        if forbidden in keys:
            errors.append(f"独立行として作成してはいけないキーがあります: {forbidden}")

    required_phrases = {
        "notes_body_connection": ("原因であるとは限らない", "毎回の回答に入れる必要はない"),
        "notes_undecided_consultation": ("決めつけない", "1〜2個", "問診地獄"),
        "notes_suggestion_stance": ("候補になりやすい", "効果は保証しない"),
        "notes_approach_candidates": ("鍼灸", "整体・コンディショニング", "美容鍼", "トレーニング", "トータルコンディショニング", "トレーナー帯同"),
        "notes_reservation_intent": ("相談だけ", "予約システム"),
        "notes_medical_safety": ("胸痛", "肩こり", "一律に病院へ送らない"),
    }

    forbidden_patterns = (
        r"\d[\d,]*円",
        r"30\s*%",
        r"12:00",
        r"26:00",
        r"lin\.ee",
        r"090-",
        r"source_type['\"]?\s*[:=]\s*['\"]official['\"]",
    )

    identity_fields = {"id", "uuid", "embedding"}
    for payload in payloads:
        key = payload["source_key"]
        if not str(key).startswith("notes_"):
            errors.append(f"{key}: notes_ 接頭辞がありません")
        if payload.get("source_type") != NOTES_SOURCE_TYPE:
            errors.append(f"{key}: source_type が notes ではありません")
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
                errors.append(f"{key}: 公式事実や禁止パターンが含まれます: {pattern}")
        if "必ず治る" in content and key != "notes_medical_safety":
            errors.append(f"{key}: 効果保証に見える文言があります")
        if key == "notes_approach_candidates" and "必ず" in content and "決め方はしない" not in content:
            errors.append(f"{key}: 固定ルールに見える「必ず」があります")

    return errors


if __name__ == "__main__":
    payloads = iter_knowledge_payloads()
    print("notes payloads:", len(payloads))
    print("source_type:", NOTES_SOURCE_TYPE)
    print("not created:", ", ".join(NOT_CREATED_SOURCE_KEYS))
    print()
    for item in payloads:
        print(f"{item['source_key']}")
        print(f"  title: {item['title']}")
        print(f"  category: {item['category']}")
        print(f"  chars: {len(item['content'])}")
        print()
    problems = validate_notes_payloads()
    if problems:
        print("validation: FAIL")
        for msg in problems:
            print("-", msg)
        raise SystemExit(1)
    print("validation: PASS")
    print("DB/Embedding/RAG: 未接続（このモジュールは正本のみ）")
