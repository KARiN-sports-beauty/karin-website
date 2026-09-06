"""C3 会話継続の確認。本番Knowledgeは変更しない。自然な複数ターンのみ使う。

  python scripts/test_karin_chat_c3.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import EMERGENCY_REPLY, count_followup_questions, run_chat  # noqa: E402
from karin_chat_memory import reset_store_for_tests  # noqa: E402

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
        for p in ("原因です", "診断します", "股関節が原因", "必ず治ります", "絶対に整体", "絶対に鍼")
    )


def price_from_knowledge(reply: str) -> bool:
    compact = reply.replace(",", "").replace("，", "")
    return any(p in compact or p in reply for p in ("16500", "16,500", "13200", "13,200", "1万6500"))


def print_turn(label: str, message: str, turn) -> None:
    print(f"  -- {label} --")
    print("  user:", message)
    print("  conversation_id:", turn.conversation_id)
    print("  turn_index:", turn.turn_index)
    print("  primary_intent:", turn.primary_intent)
    print("  secondary_intents:", turn.secondary_intents)
    print("  source_types:", turn.source_types)
    print("  search_query:", (turn.search_query or "")[:120])
    print("  knowledge_keys:", turn.knowledge_keys)
    print("  emergency:", turn.emergency)
    print("  rag_called:", turn.rag_called)
    print("  openai_called:", turn.openai_called)
    print("  reservation_api_called:", turn.reservation_api_called)
    print("  question_count:", turn.question_count)
    print("  reply_preview:", (turn.reply or "")[:160].replace("\n", " / "))


def continue_chat(message: str, previous, *, explode_io: bool = False):
    cid = None if previous is None else previous.conversation_id

    def boom(*_a, **_k):
        raise AssertionError("RAG/OpenAI を呼んではいけない")

    if explode_io:
        return run_chat(message, conversation_id=cid, match_fn=boom, complete_fn=boom)
    return run_chat(message, conversation_id=cid)


def main() -> int:
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")
    print("mode: Knowledge読み取り専用 / 予約API未使用 / 会話は短期メモリのみ")
    reset_store_for_tests()

    admin = get_admin_client()
    before_n, before_hash = snapshot_knowledge(admin)
    print("knowledge snapshot before:", before_n, before_hash[:12])
    failures: list[str] = []

    print("\n===== Test 1 基本的な継続 =====")
    t1a = continue_chat("腰が痛いです。", None)
    t1b = continue_chat("特に座ってるときがつらいです。", t1a)
    print_turn("T1-1", "腰が痛いです。", t1a)
    print_turn("T1-2", "特に座ってるときがつらいです。", t1b)
    if t1a.turn_index != 1 or t1b.turn_index != 2:
        failures.append("Test1: turn数がおかしい")
    if t1a.conversation_id != t1b.conversation_id or not t1a.conversation_id:
        failures.append("Test1: conversation_id が継続していない")
    if t1b.primary_intent != "consultation":
        failures.append(f"Test1: turn2 intent={t1b.primary_intent}")
    if "notes" not in t1b.source_types:
        failures.append("Test1: notes が使われていない")
    if re.search(r"どこが(痛い|つらい)|どのあたり", t1b.reply or ""):
        failures.append("Test1: 腰痛を再質問している")
    if "座" not in (t1b.reply or "") and "デスク" not in (t1b.reply or ""):
        failures.append("Test1: 座っているときにつらい情報が反映されていない")
    if t1b.reservation_api_called:
        failures.append("Test1: 予約API")

    print("\n===== Test 2 施術相談へのIntent変更 =====")
    t2a = continue_chat("腰が痛いです。", None)
    t2b = continue_chat("鍼と整体だったらどっちがいいですか？", t2a)
    print_turn("T2-1", "腰が痛いです。", t2a)
    print_turn("T2-2", "鍼と整体だったらどっちがいいですか？", t2b)
    if t2a.primary_intent != "consultation":
        failures.append(f"Test2: turn1 intent={t2a.primary_intent}")
    if t2b.primary_intent != "treatment_consultation":
        failures.append(f"Test2: turn2 intent={t2b.primary_intent}")
    if "notes" not in t2b.source_types:
        failures.append("Test2: notes 未使用")
    if claims_diagnosis(t2b.reply or "") or "絶対に" in (t2b.reply or ""):
        failures.append("Test2: 一方を断定している")

    print("\n===== Test 3 予約意図への変更 =====")
    t3a = continue_chat("腰が痛いです。", None)
    t3b = continue_chat("じゃあ明日の夜に予約したいです。", t3a)
    print_turn("T3-1", "腰が痛いです。", t3a)
    print_turn("T3-2", "じゃあ明日の夜に予約したいです。", t3b)
    if t3a.primary_intent != "consultation":
        failures.append(f"Test3: turn1 intent={t3a.primary_intent}")
    if t3b.primary_intent != "reservation_intent":
        failures.append(f"Test3: turn2 intent={t3b.primary_intent}")
    if t3b.reservation_api_called:
        failures.append("Test3: 予約APIを呼んだ")
    if claims_availability(t3b.reply or ""):
        failures.append("Test3: 空き状況を推測している")

    print("\n===== Test 4 相談から料金確認 =====")
    t4a = continue_chat("腰が痛いんですが、鍼と整体ならどちらがいいですか？", None)
    t4b = continue_chat("じゃあ90分でお願いするといくらですか？", t4a)
    print_turn("T4-1", "腰が痛いんですが、鍼と整体ならどちらがいいですか？", t4a)
    print_turn("T4-2", "じゃあ90分でお願いするといくらですか？", t4b)
    if t4a.primary_intent != "treatment_consultation":
        failures.append(f"Test4: turn1 intent={t4a.primary_intent}")
    if t4b.primary_intent != "price_info":
        failures.append(f"Test4: turn2 intent={t4b.primary_intent}")
    if t4b.source_types != ["official"]:
        failures.append(f"Test4: source_types={t4b.source_types}")
    if "visit_course_prices" not in t4b.knowledge_keys:
        failures.append("Test4: visit_course_prices がない")
    if not price_from_knowledge(t4b.reply or ""):
        failures.append("Test4: Knowledgeの料金を根拠にしていない")

    print("\n===== Test 5 初回割引の自然な質問 =====")
    t5a = continue_chat("初めて利用しようと思ってるんですが、ちょっと聞いてもいいですか？", None)
    t5b = continue_chat("初めてだと、何か安くなったりしますか？", t5a)
    print_turn("T5-1", "初めて利用しようと思ってるんですが、ちょっと聞いてもいいですか？", t5a)
    print_turn("T5-2", "初めてだと、何か安くなったりしますか？", t5b)
    if t5a.primary_intent != "consultation":
        failures.append(f"Test5: turn1 intent={t5a.primary_intent}")
    if t5b.primary_intent != "campaign_or_discount":
        failures.append(f"Test5: turn2 intent={t5b.primary_intent}")
    if "official" not in t5b.source_types:
        failures.append("Test5: official へ切り替わっていない")
    if "first_visit_discount" not in t5b.knowledge_keys:
        failures.append("Test5: first_visit_discount がない")
    if "30" not in (t5b.reply or "") and "３０" not in (t5b.reply or ""):
        failures.append("Test5: 初回割引の根拠が見えない")

    print("\n===== Test 6 既知情報を再質問しない =====")
    t6a = continue_chat("最近デスクワークが増えて、腰が痛くなりました。", None)
    t6b = continue_chat("夕方になると特につらいです。", t6a)
    print_turn("T6-1", "最近デスクワークが増えて、腰が痛くなりました。", t6a)
    print_turn("T6-2", "夕方になると特につらいです。", t6b)
    if re.search(r"デスクワークですか", t6b.reply or ""):
        failures.append("Test6: デスクワークを再質問している")
    if "夕方" not in (t6b.reply or ""):
        failures.append("Test6: 夕方につらい情報が反映されていない")
    if t6b.primary_intent != "consultation":
        failures.append(f"Test6: turn2 intent={t6b.primary_intent}")

    print("\n===== Test 7 曖昧な代名詞 =====")
    t7a = continue_chat("腰が痛くて、鍼と整体どっちがいいか迷っています。", None)
    t7b = continue_chat("それってどっちのほうがいいんですか？", t7a)
    print_turn("T7-1", "腰が痛くて、鍼と整体どっちがいいか迷っています。", t7a)
    print_turn("T7-2", "それってどっちのほうがいいんですか？", t7b)
    if t7b.primary_intent != "treatment_consultation":
        failures.append(f"Test7: turn2 intent={t7b.primary_intent}")
    if "鍼" not in (t7b.reply or "") or "整体" not in (t7b.reply or ""):
        failures.append("Test7: 鍼と整体の質問として処理されていない")
    if "notes" not in t7b.source_types:
        failures.append("Test7: notes が使われていない")
    if "腰が痛い" in (t7b.search_query or "") or "鍼" in (t7b.search_query or ""):
        pass
    else:
        failures.append("Test7: RAG query に会話履歴が足りない")

    print("\n===== Test 8 相談から予約方法 =====")
    t8a = continue_chat("腰が痛いんですが、まず相談してから決めたいです。", None)
    t8b = continue_chat("相談したあと、予約ってどうやって取るんですか？", t8a)
    print_turn("T8-1", "腰が痛いんですが、まず相談してから決めたいです。", t8a)
    print_turn("T8-2", "相談したあと、予約ってどうやって取るんですか？", t8b)
    if t8b.primary_intent != "reservation_info":
        failures.append(f"Test8: turn2 intent={t8b.primary_intent}")
    if "official" not in t8b.source_types:
        failures.append("Test8: official 未使用")
    if "booking_methods" not in t8b.knowledge_keys:
        failures.append("Test8: booking_methods がない")
    if t8b.reservation_api_called:
        failures.append("Test8: 予約APIを呼んだ")

    print("\n===== Test 9 緊急性の途中発生 =====")
    t9a = continue_chat("肩がこります。", None)
    t9b = continue_chat(
        "さっきから急に片側の手足に力が入らなくなりました。",
        t9a,
        explode_io=True,
    )
    print_turn("T9-1", "肩がこります。", t9a)
    print_turn("T9-2", "さっきから急に片側の手足に力が入らなくなりました。", t9b)
    if t9a.conversation_id != t9b.conversation_id:
        failures.append("Test9: conversation_id が切れている")
    if not t9b.emergency:
        failures.append("Test9: 安全ゲートにかかっていない")
    if t9b.rag_called or t9b.openai_called:
        failures.append("Test9: RAGまたはOpenAIを呼んでいる")
    if t9b.reply != EMERGENCY_REPLY:
        failures.append("Test9: 固定の受診優先文でない")
    if t9a.emergency:
        failures.append("Test9: 肩こりを緊急扱いしている")

    print("\n===== Test 10 質問を増やしすぎない =====")
    t10a = continue_chat("腰が痛いです。", None)
    t10b = continue_chat("座っていると特に痛みます。", t10a)
    print_turn("T10-1", "腰が痛いです。", t10a)
    print_turn("T10-2", "座っていると特に痛みます。", t10b)
    q1 = count_followup_questions(t10a.reply or "")
    q2 = count_followup_questions(t10b.reply or "")
    if q1 > 2:
        failures.append(f"Test10: turn1 の質問が多すぎる ({q1})")
    if q2 > 2:
        failures.append(f"Test10: turn2 の質問が多すぎる ({q2})")
    if re.search(r"どこが(痛い|つらい)", t10a.reply or "") or re.search(
        r"どこが(痛い|つらい)", t10b.reply or ""
    ):
        failures.append("Test10: 既知の部位を聞き直している")

    print("\n===== API互換: conversation_id なしでも開始 =====")
    from app import app

    with app.test_client() as client:
        first = client.post("/api/chat", json={"message": "肩がこります。"})
        body1 = first.get_json(silent=True) or {}
        cid = body1.get("conversation_id")
        print("  status1:", first.status_code, "cid:", cid)
        if first.status_code != 200 or not body1.get("reply") or not cid:
            failures.append("API: 初回に reply または conversation_id がない")
        second = client.post(
            "/api/chat",
            json={"message": "夕方になるとつらいです。", "conversation_id": cid},
        )
        body2 = second.get_json(silent=True) or {}
        print("  status2:", second.status_code, "cid2:", body2.get("conversation_id"))
        if second.status_code != 200 or body2.get("conversation_id") != cid:
            failures.append("API: conversation_id が継続していない")
        if "夕方" not in (body2.get("reply") or ""):
            failures.append("API: 2ターン目に夕方の情報が反映されていない")

    after_n, after_hash = snapshot_knowledge(admin)
    print("\nknowledge snapshot after:", after_n, after_hash[:12])
    if (after_n, after_hash) != (before_n, before_hash):
        failures.append("Knowledge DB がテスト中に変更された")

    if failures:
        print("\nC3 FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nC3 テスト: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
