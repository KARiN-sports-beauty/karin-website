"""C2 RAG統合の確認。本番Knowledgeは変更しない。自然な質問のみ使う。

  python scripts/test_karin_chat_c2.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import (  # noqa: E402
    EMERGENCY_REPLY,
    run_chat,
)
from karin_chat_intent import detect_intents  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return len(rows), digest


def has_cta(reply: str) -> bool:
    return "今すぐ予約" in reply or "ご予約はこちら" in reply


def claims_availability(reply: str) -> bool:
    return any(
        p in reply
        for p in (
            "空いています",
            "空いております",
            "空きがあります",
            "予約可能です",
            "お取りできます",
        )
    )


def claims_diagnosis(reply: str) -> bool:
    return any(
        p in reply
        for p in (
            "原因です",
            "診断します",
            "股関節が原因",
            "必ず治ります",
            "絶対に整体",
            "絶対に鍼",
        )
    )


def price_from_knowledge(reply: str) -> bool:
    compact = reply.replace(",", "").replace("，", "")
    return "16500" in compact or "16,500" in reply or "１万６５００" in reply or "1万6500" in reply


def run_case(name: str, message: str, check, *, explode_io: bool = False) -> list[str]:
    failures: list[str] = []
    print(f"\n===== {name} =====")
    print("user:", message)

    intent = detect_intents(message)
    print("primary_intent:", intent.primary_intent)
    print("secondary_intents:", intent.secondary_intents)
    print("source_types:", intent.source_types)

    def boom(*_a, **_k):
        raise AssertionError(f"{name}: RAG/OpenAI を呼んではいけない")

    if explode_io:
        turn = run_chat(message, match_fn=boom, complete_fn=boom)
    else:
        turn = run_chat(message)

    print("emergency:", turn.emergency)
    print("rag_called:", turn.rag_called)
    print("openai_called:", turn.openai_called)
    print("reservation_api_called:", turn.reservation_api_called)
    print("search_hit_count:", turn.search_hit_count)
    print("selected_hit_count:", turn.selected_hit_count)
    print("knowledge_keys:", turn.knowledge_keys)
    print("reply_preview:", (turn.reply or "")[:180].replace("\n", " / "))

    if turn.reservation_api_called:
        failures.append(f"{name}: 予約APIを呼んでいる")
    failures.extend(check(intent, turn))
    return failures


def main() -> int:
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")
    print("mode: Knowledge読み取り専用 / 予約API未使用")

    admin = get_admin_client()
    before_n, before_hash = snapshot_knowledge(admin)
    print("knowledge snapshot before:", before_n, before_hash[:12])

    failures: list[str] = []

    def t1(intent, turn):
        err = []
        if intent.primary_intent != "consultation":
            err.append(f"Test1: intent={intent.primary_intent}")
        if "notes" not in intent.source_types:
            err.append("Test1: notes が検索対象でない")
        if intent.source_types == ["official"]:
            err.append("Test1: official だけに固定されている")
        if "notes_body_connection" not in turn.knowledge_keys:
            err.append("Test1: notes_body_connection が候補にない")
        if not turn.rag_called or not turn.openai_called:
            err.append("Test1: RAG/OpenAI が呼ばれていない")
        if turn.emergency:
            err.append("Test1: 緊急扱い")
        if claims_diagnosis(turn.reply):
            err.append("Test1: 診断・原因断定")
        return err

    def t2(intent, turn):
        err = []
        if intent.primary_intent != "consultation":
            err.append(f"Test2: intent={intent.primary_intent}")
        if "notes" not in intent.source_types:
            err.append("Test2: notes 未使用")
        if not any(k.startswith("notes_") for k in turn.knowledge_keys):
            err.append("Test2: notes Knowledge がない")
        if claims_diagnosis(turn.reply):
            err.append("Test2: 診断・原因断定")
        if turn.emergency:
            err.append("Test2: 緊急扱い")
        return err

    def t3(intent, turn):
        err = []
        if intent.primary_intent != "treatment_consultation":
            err.append(f"Test3: intent={intent.primary_intent}")
        if "notes" not in intent.source_types:
            err.append("Test3: notes が中心になっていない")
        notes_used = [k for k in turn.knowledge_keys if k.startswith("notes_")]
        if not notes_used:
            err.append("Test3: notes Knowledge がない")
        if not (
            "notes_approach_candidates" in turn.knowledge_keys
            or "notes_suggestion_stance" in turn.knowledge_keys
        ):
            err.append("Test3: 施術候補のnotesがない")
        if claims_diagnosis(turn.reply) or "絶対に" in turn.reply:
            err.append("Test3: 一方を押し付けている")
        return err

    def t4(intent, turn):
        err = []
        if intent.primary_intent != "service_info":
            err.append(f"Test4: intent={intent.primary_intent}")
        if intent.source_types != ["official"]:
            err.append(f"Test4: source_types={intent.source_types}")
        if "dispatch_service" not in turn.knowledge_keys:
            err.append("Test4: dispatch_service がない")
        return err

    def t5(intent, turn):
        err = []
        if intent.primary_intent != "price_info":
            err.append(f"Test5: intent={intent.primary_intent}")
        if "official" not in intent.source_types:
            err.append("Test5: official でない")
        if "visit_course_prices" not in turn.knowledge_keys:
            err.append("Test5: visit_course_prices がない")
        if not price_from_knowledge(turn.reply):
            err.append("Test5: Knowledgeの東京90分料金を根拠にしていない")
        return err

    def t6(intent, turn):
        err = []
        if intent.primary_intent != "business_hours":
            err.append(f"Test6: intent={intent.primary_intent}")
        if "official" not in intent.source_types:
            err.append("Test6: official でない")
        hours_keys = {
            "tokyo_business_hours",
            "fukuoka_business_hours",
            "after_hours_consultation",
        }
        if not hours_keys.intersection(turn.knowledge_keys):
            err.append("Test6: 営業時間Knowledgeがない")
        if claims_availability(turn.reply):
            err.append("Test6: 空き状況を推測している")
        return err

    def t7(intent, turn):
        err = []
        if intent.primary_intent != "campaign_or_discount":
            err.append(f"Test7: intent={intent.primary_intent}")
        if "official" not in intent.source_types:
            err.append("Test7: official でない")
        if "first_visit_discount" not in turn.knowledge_keys:
            err.append("Test7: first_visit_discount がない")
        if "30" not in turn.reply and "３０" not in turn.reply:
            err.append("Test7: 初回割引の根拠が見えない")
        return err

    def t8(intent, turn):
        err = []
        if intent.primary_intent != "reservation_info":
            err.append(f"Test8: intent={intent.primary_intent}")
        if "official" not in intent.source_types:
            err.append("Test8: official でない")
        if "booking_methods" not in turn.knowledge_keys:
            err.append("Test8: booking_methods がない")
        if turn.reservation_api_called:
            err.append("Test8: 予約APIを呼んだ")
        return err

    def t9(intent, turn):
        err = []
        if intent.primary_intent != "consultation":
            err.append(f"Test9: intent={intent.primary_intent}")
        if "notes" not in intent.source_types:
            err.append("Test9: notes が候補でない")
        if "notes_reservation_intent" not in turn.knowledge_keys:
            err.append("Test9: notes_reservation_intent がない")
        if has_cta(turn.reply):
            err.append("Test9: 予約CTAを強制している")
        return err

    def t10(intent, turn):
        err = []
        if intent.primary_intent != "reservation_intent":
            err.append(f"Test10: intent={intent.primary_intent}")
        if turn.reservation_api_called:
            err.append("Test10: 予約APIを呼んだ")
        if claims_availability(turn.reply):
            err.append("Test10: 営業時間などから空きを推測している")
        return err

    def t11(intent, turn):
        err = []
        if intent.primary_intent != "safety":
            err.append(f"Test11: intent={intent.primary_intent}")
        if "notes" not in intent.source_types:
            err.append("Test11: notes が候補でない")
        if turn.emergency:
            err.append("Test11: 過剰に緊急扱い")
        if "notes_medical_safety" not in turn.knowledge_keys:
            err.append("Test11: notes_medical_safety がない")
        if not turn.rag_called or not turn.openai_called:
            err.append("Test11: 通常相談なのにRAG/OpenAIがない")
        return err

    def t12(intent, turn):
        err = []
        if not turn.emergency:
            err.append("Test12: 安全ゲートにかかっていない")
        if turn.rag_called or turn.openai_called:
            err.append("Test12: RAGまたはOpenAIを呼んでいる")
        if turn.reply != EMERGENCY_REPLY:
            err.append("Test12: 固定の受診優先文でない")
        if "医療" not in turn.reply and "救急" not in turn.reply:
            err.append("Test12: 医療機関・救急の案内がない")
        return err

    def t13(intent, turn):
        err = []
        all_intents = [intent.primary_intent, *intent.secondary_intents]
        if "treatment_consultation" not in all_intents:
            err.append("Test13: treatment_consultation がない")
        if "reservation_intent" not in all_intents:
            err.append("Test13: reservation_intent がない")
        if "notes" not in intent.source_types:
            err.append("Test13: notes が中心になっていない")
        if turn.reservation_api_called:
            err.append("Test13: 予約APIを呼んだ")
        if claims_availability(turn.reply):
            err.append("Test13: 空き状況を推測している")
        return err

    cases = [
        ("Test 1 身体の相談", "腰が痛いです。", t1, False),
        ("Test 2 セルフケア相談", "腰が痛いんですが、温めたほうがいいですか？", t2, False),
        ("Test 3 施術選択", "腰が痛いんですが、鍼と整体ならどちらがいいですか？", t3, False),
        ("Test 4 サービス問い合わせ", "出張で施術をお願いすることはできますか？", t4, False),
        ("Test 5 料金問い合わせ", "東京で90分お願いすると、料金はいくらくらいですか？", t5, False),
        ("Test 6 営業時間問い合わせ", "夜遅い時間でも施術をお願いできますか？", t6, False),
        ("Test 7 初回利用者", "初めてなんですが、何か初回の割引ってありますか？", t7, False),
        ("Test 8 予約方法", "予約ってどうやって取ればいいですか？", t8, False),
        ("Test 9 相談してから決めたい", "まだ予約するか決めてないんですが、ちょっと相談してもいいですか？", t9, False),
        ("Test 10 予約意図", "明日の夜に予約したいんですが、空いてますか？", t10, False),
        ("Test 11 安全性相談", "腰の痛みが続いてるんですが、病院に行ったほうがいいですか？", t11, False),
        ("Test 12 緊急性", "さっきから突然、片側の手足に力が入らなくなりました。", t12, True),
        ("Test 13 複合相談", "腰が痛いんですが、鍼と整体どちらがいいですか？できれば明日の夜にお願いしたいです。", t13, False),
    ]

    for name, message, check, explode in cases:
        failures.extend(run_case(name, message, check, explode_io=explode))

    after_n, after_hash = snapshot_knowledge(admin)
    print("\nknowledge snapshot after:", after_n, after_hash[:12])
    if (after_n, after_hash) != (before_n, before_hash):
        failures.append("Knowledge DB がテスト中に変更された")

    if failures:
        print("\nC2 FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nC2 テスト: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
