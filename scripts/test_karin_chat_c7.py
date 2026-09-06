"""C7 KARiN.chatbot 総合テスト。本番Knowledgeは読み取り専用。予約は確定しない。

  python scripts/test_karin_chat_c7.py
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from health_knowledge_data import SOURCE_KEYS as HEALTH_KEYS  # noqa: E402
from health_knowledge_data import iter_knowledge_payloads as health_payloads  # noqa: E402
from karin_chat import (  # noqa: E402
    EMERGENCY_REPLY,
    build_known_facts_prompt,
    count_followup_questions,
    is_emergency_message,
    run_chat,
)
from karin_chat_booking import BOOKING_LOOKUP_ERROR_REPLY  # noqa: E402
from karin_chat_memory import (  # noqa: E402
    MAX_CONVERSATIONS,
    MAX_USER_TURNS,
    TTL_SECONDS,
    _STORE,
    append_turn,
    get_or_create_conversation,
    history_messages,
    reset_store_for_tests,
)
from notes_ai_data import SOURCE_KEYS as NOTES_KEYS  # noqa: E402
from notes_ai_data import iter_knowledge_payloads as notes_payloads  # noqa: E402
from official_site_data import SOURCE_KEYS as OFFICIAL_KEYS  # noqa: E402
from official_site_data import iter_knowledge_payloads as official_payloads  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
SECRET_MARKERS = (
    "sk-",
    "SUPABASE_SERVICE",
    "traceback",
    "Traceback",
    "SELECT * FROM",
    "https://internal",
    "secret_table",
)
EXTRA_SLOT_LABELS = ("20:00", "20:30", "21:00")
HEALTH_KEY_SET = set(HEALTH_KEYS)
NOTES_KEY_SET = set(NOTES_KEYS)
SLOT_RETRIES = 3


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def type_counts(rows: list[dict]) -> dict[str, int]:
    return {
        "total": len(rows),
        "inactive": sum(1 for r in rows if r.get("status") != "active"),
        "official_active_canonical": sum(
            1
            for r in rows
            if r.get("source_type") == "official"
            and r.get("status") == "active"
            and r.get("source_key")
        ),
        "notes": sum(1 for r in rows if r.get("source_type") == "notes"),
        "health": sum(1 for r in rows if r.get("source_type") == "health"),
        "official_keys": len(
            {
                r.get("source_key")
                for r in rows
                if r.get("source_type") == "official"
                and r.get("status") == "active"
                and r.get("source_key")
            }
        ),
        "notes_keys": len(
            {
                r.get("source_key")
                for r in rows
                if r.get("source_type") == "notes" and r.get("source_key")
            }
        ),
        "health_keys": len(
            {
                r.get("source_key")
                for r in rows
                if r.get("source_type") == "health" and r.get("source_key")
            }
        ),
    }


def fetch_all(admin) -> list[dict]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    return list(res.data or [])


def claims_diagnosis(reply: str) -> bool:
    return any(
        p in (reply or "")
        for p in ("原因です", "診断します", "必ず治ります", "絶対に整体", "絶対に鍼", "睡眠障害です")
    )


def claims_availability(reply: str) -> bool:
    return any(
        p in (reply or "")
        for p in ("空いています", "空いております", "空きがあります", "予約可能です", "お取りできます")
    )


def price_from_official(reply: str) -> bool:
    compact = (reply or "").replace(",", "").replace("，", "")
    return any(p in compact or p in (reply or "") for p in ("16500", "16,500", "1万6500"))


def invents_unreturned_slot(reply: str) -> bool:
    text = reply or ""
    return bool(
        re.search(r"20(:00|時).{0,16}(空き|空いて|予約可能)", text)
        or re.search(r"20:30.{0,16}(空き|空いて|予約可能)", text)
        or re.search(r"21(:00|時).{0,16}(空き|空いて|予約可能)", text)
    )


def mentions_returned_slots(reply: str) -> bool:
    text = reply or ""
    return "18:00" in text or "19:30" in text or "18時" in text or "19時半" in text


def mock_slots(*times: str):
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        slots = [{"time": t, "available": True} for t in times]
        return {
            "date": kwargs.get("date"),
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": kwargs.get("duration_minutes"),
            "staff": [],
            "free_row": {"staff_name": "フリー", "slots": slots},
        }

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


def boom_lookup(**_kwargs):
    raise RuntimeError("internal boom SELECT * FROM secret_table url=https://internal")


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def print_turn(label: str, message: str, turn) -> None:
    print(f"  -- {label} --")
    print("  user:", message)
    print("  intent:", turn.primary_intent, turn.secondary_intents)
    print("  source_types:", turn.source_types)
    print("  keys:", turn.knowledge_keys)
    print("  emergency/openai/rag/api:", turn.emergency, turn.openai_called, turn.rag_called, turn.reservation_api_called)
    print("  slots:", turn.available_slots, "status:", turn.api_status)
    print("  reply_preview:", (turn.reply or "")[:150].replace("\n", " / "))


def leaks_secret(text: str) -> bool:
    blob = text or ""
    return any(m in blob for m in SECRET_MARKERS)


def ask_retry(build_fn, ok_fn, attempts: int = SLOT_RETRIES):
    last = None
    for _ in range(attempts):
        last = build_fn()
        if ok_fn(last):
            return last, True, _
    return last, False, attempts - 1


def main() -> int:
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")
    print("mode: C7 総合 / Knowledge読み取り専用 / 予約確定なし")
    reset_store_for_tests()
    failures: list[str] = []
    llm_notes: list[str] = []

    admin = get_admin_client()
    before_rows = fetch_all(admin)
    before_n, before_h = snapshot_knowledge(admin)
    counts = type_counts(before_rows)
    print(f"snapshot before: n={before_n} hash={before_h[:16]}...")
    print("counts:", counts)

    print("\n===== 17 Knowledge構成 =====")
    expected = {
        "total": 34,
        "official_active_canonical": 19,
        "notes": 6,
        "health": 7,
        "inactive": 2,
        "official_keys": 19,
        "notes_keys": 6,
        "health_keys": 7,
    }
    for key, value in expected.items():
        if counts.get(key) != value:
            failures.append(f"Knowledge構成: {key}={counts.get(key)} expected={value}")

    print("\n===== 18 Canonical整合 =====")
    by_key = {}
    for row in before_rows:
        key = (row.get("source_key") or "").strip()
        if key and row.get("status") == "active":
            by_key[(row.get("source_type"), key)] = row
    for payload in official_payloads():
        row = by_key.get(("official", payload["source_key"]))
        if row is None:
            failures.append(f"canonical official 欠落: {payload['source_key']}")
        elif (row.get("content") or "") != payload["content"]:
            failures.append(f"canonical official 不一致: {payload['source_key']}")
    for payload in notes_payloads():
        row = by_key.get(("notes", payload["source_key"]))
        if row is None or (row.get("content") or "") != payload["content"]:
            failures.append(f"canonical notes 不一致: {payload['source_key']}")
    for payload in health_payloads():
        row = by_key.get(("health", payload["source_key"]))
        if row is None or (row.get("content") or "") != payload["content"]:
            failures.append(f"canonical health 不一致: {payload['source_key']}")
    if not any(f.startswith("canonical") for f in failures):
        print("  official/notes/health 正本とDB本文: 一致")

    lookup_a = mock_slots("18:00", "19:30")
    print("\n===== A 相談→施術→料金→空き→予約 =====")
    a1 = continue_chat("腰が痛いです。", None, lookup_fn=lookup_a)
    print_turn("A1", "腰が痛いです。", a1)
    if a1.emergency:
        failures.append("A1: emergency")
    if a1.primary_intent != "consultation":
        failures.append(f"A1: intent={a1.primary_intent}")
    if "notes" not in a1.source_types or "health" not in a1.source_types:
        failures.append(f"A1: source_types={a1.source_types}")
    if claims_diagnosis(a1.reply or ""):
        failures.append("A1: 診断")

    a2 = continue_chat("鍼と整体だったらどっちがいいですか？", a1, lookup_fn=lookup_a)
    print_turn("A2", "鍼と整体だったらどっちがいいですか？", a2)
    if a2.conversation_id != a1.conversation_id:
        failures.append("A2: conversation_id が切れた")
    if a2.primary_intent != "treatment_consultation":
        failures.append(f"A2: intent={a2.primary_intent}")
    if "notes" not in a2.source_types:
        failures.append("A2: notes 未使用")
    if a2.source_types == ["health"]:
        failures.append("A2: healthだけで施術決定")
    if not any(k in NOTES_KEY_SET for k in a2.knowledge_keys):
        failures.append("A2: notes Knowledge がない")
    if claims_diagnosis(a2.reply or "") or "必ず鍼" in (a2.reply or "") or "必ず整体" in (a2.reply or ""):
        failures.append("A2: 施術断定")

    a3 = continue_chat("東京で90分だといくらですか？", a2, lookup_fn=lookup_a)
    print_turn("A3", "東京で90分だといくらですか？", a3)
    if a3.primary_intent != "price_info":
        failures.append(f"A3: intent={a3.primary_intent}")
    if a3.source_types != ["official"]:
        failures.append(f"A3: source_types={a3.source_types}")
    if "visit_course_prices" not in a3.knowledge_keys:
        failures.append("A3: visit_course_prices がない")
    if any(k in HEALTH_KEY_SET or k in NOTES_KEY_SET for k in a3.knowledge_keys):
        failures.append("A3: health/notes を料金根拠にしている")
    if not price_from_official(a3.reply or ""):
        failures.append("A3: 公式の東京90分料金が見えない")
        llm_notes.append("A3 料金言及はLLM依存の可能性")

    a4 = continue_chat("明日の夜って空いてますか？", a3, lookup_fn=lookup_a)
    print_turn("A4", "明日の夜って空いてますか？", a4)
    if a4.primary_intent != "reservation_intent":
        failures.append(f"A4: intent={a4.primary_intent}")
    if not lookup_a.calls:
        failures.append("A4: 既存予約処理を呼んでいない")
    else:
        args = lookup_a.calls[-1]
        if args.get("area") != "tokyo" or args.get("duration_minutes") != 90:
            failures.append(f"A4: 東京/90分を再利用していない {args}")
    if a4.requested_time == "19:00":
        failures.append("A4: 夜を19:00に変換している")
    if a4.requested_time_range != "evening":
        failures.append(f"A4: time_range={a4.requested_time_range}")
    if set(a4.available_slots) != {"18:00", "19:30"}:
        failures.append(f"A4: available_slots={a4.available_slots}")
    if invents_unreturned_slot(a4.reply or ""):
        failures.append("A4: APIにない時刻を空きとして追加")
    if claims_availability(a4.reply or "") and not a4.reservation_api_called:
        failures.append("A4: Knowledgeから空きを推測")

    a5 = continue_chat("じゃあ予約したいです。", a4, lookup_fn=lookup_a)
    print_turn("A5", "じゃあ予約したいです。", a5)
    if a5.primary_intent != "reservation_intent":
        failures.append(f"A5: intent={a5.primary_intent}")
    if "確定しました" in (a5.reply or "") or "予約を完了" in (a5.reply or ""):
        failures.append("A5: 予約確定を実行している")
    if not a5.show_booking_cta:
        failures.append("A5: show_booking_cta がない")

    print("\n===== B Health→KARiN相談→予約方法 =====")
    b1 = continue_chat("最近寝つきが悪いんですが、何か気をつけることありますか？", None)
    print_turn("B1", "最近寝つきが悪いんですが、何か気をつけることありますか？", b1)
    if b1.primary_intent != "health_general":
        failures.append(f"B1: intent={b1.primary_intent}")
    if b1.source_types != ["health"]:
        failures.append(f"B1: source_types={b1.source_types}")
    if claims_diagnosis(b1.reply or "") or "睡眠障害" in (b1.reply or ""):
        failures.append("B1: 病名/診断")

    b2 = continue_chat("それって鍼とか整体で相談できますか？", b1)
    print_turn("B2", "それって鍼とか整体で相談できますか？", b2)
    if b2.conversation_id != b1.conversation_id:
        failures.append("B2: conversation_id")
    if b2.primary_intent == "health_general" and b2.source_types == ["health"]:
        failures.append("B2: healthだけに固定された")
    if b2.primary_intent != "treatment_consultation":
        failures.append(f"B2: intent={b2.primary_intent}")
    if "notes" not in b2.source_types:
        failures.append("B2: notes へ切り替わっていない")
    if "必ず効" in (b2.reply or "") or "必ず改善" in (b2.reply or ""):
        failures.append("B2: 施術効果を保証")

    b3 = continue_chat("予約するならどうすればいいですか？", b2)
    print_turn("B3", "予約するならどうすればいいですか？", b3)
    if b3.primary_intent not in ("reservation_info", "reservation_intent"):
        failures.append(f"B3: intent={b3.primary_intent}")
    if "official" not in b3.source_types:
        failures.append("B3: official が使われていない")
    if "booking_methods" not in b3.knowledge_keys and b3.primary_intent == "reservation_info":
        failures.append("B3: booking_methods がない")
    if b3.reservation_api_called and b3.primary_intent == "reservation_info":
        failures.append("B3: 予約方法なのに空きAPIを呼んだ")
    if claims_availability(b3.reply or "") and not b3.reservation_api_called:
        failures.append("B3: 予約方法と空きを混同")

    print("\n===== C 会話途中の緊急 =====")
    def boom(*_a, **_k):
        raise AssertionError("C: 緊急時にRAG/OpenAIを呼んではいけない")

    c1 = continue_chat("肩が凝っています。", None)
    print_turn("C1", "肩が凝っています。", c1)
    if c1.emergency or is_emergency_message("肩が凝っています。"):
        failures.append("C1: 通常の肩こりを緊急扱い")
    if "救急" in (c1.reply or ""):
        failures.append("C1: 過剰に救急へ誘導")
    c2 = continue_chat(
        "さっきから急に右半身に力が入らなくなりました。",
        c1,
        match_fn=boom,
        complete_fn=boom,
        lookup_fn=boom_lookup,
    )
    print_turn("C2", "さっきから急に右半身に力が入らなくなりました。", c2)
    if not c2.emergency or c2.reply != EMERGENCY_REPLY:
        failures.append("C2: C1安全ゲートが最優先でない")
    if c2.rag_called or c2.openai_called or c2.reservation_api_called:
        failures.append("C2: 緊急時にRAG/OpenAI/予約APIを呼んだ")
    if c2.conversation_id != c1.conversation_id:
        failures.append("C2: conversation_id")

    print("\n===== D HealthとNotesの競合 =====")
    d1 = continue_chat("腰が痛いんですが、普段何に気をつけたらいいですか？", None)
    print_turn("D1", "腰が痛いんですが、普段何に気をつけたらいいですか？", d1)
    if "health" not in d1.source_types or "notes" not in d1.source_types:
        failures.append(f"D1: 一方に固定 {d1.source_types}")
    if "health_back_pain" not in d1.knowledge_keys:
        failures.append("D1: health_back_pain がない")
    if not any(k in ("notes_body_connection", "notes_medical_safety", "notes_undecided_consultation") for k in d1.knowledge_keys):
        failures.append("D1: notes の身体観がない")
    if claims_diagnosis(d1.reply or ""):
        failures.append("D1: 原因断定")
    d2 = continue_chat("じゃあ鍼と整体ならどっちがいいですか？", d1)
    print_turn("D2", "じゃあ鍼と整体ならどっちがいいですか？", d2)
    if d2.primary_intent != "treatment_consultation":
        failures.append(f"D2: intent={d2.primary_intent}")
    if "notes" not in d2.source_types or d2.source_types == ["health"]:
        failures.append("D2: notesが中心になっていない")
    if not any(k in ("notes_suggestion_stance", "notes_approach_candidates") for k in d2.knowledge_keys):
        failures.append("D2: 施術notesがない")

    print("\n===== E OfficialとHealthの分離 =====")
    e_cases = [
        ("東京で90分だといくらですか？", "price_info", ["official"], "visit_course_prices"),
        ("最近寝つきが悪いんですが、何か気をつけることありますか？", "health_general", ["health"], "health_sleep"),
        ("初めてなんですが、割引ありますか？", "campaign_or_discount", ["official"], "first_visit_discount"),
        ("暑い日に運動するとき、水分ってどう取ったらいいですか？", "health_general", ["health"], None),
    ]
    for msg, intent, types, key in e_cases:
        turn = run_chat(msg)
        print_turn("E", msg, turn)
        if turn.primary_intent != intent:
            failures.append(f"E: {msg[:12]} intent={turn.primary_intent}")
        if turn.source_types != types:
            failures.append(f"E: {msg[:12]} source_types={turn.source_types}")
        if key and key not in turn.knowledge_keys:
            failures.append(f"E: {msg[:12]} key={key} がない")
        if types == ["official"] and any(k in HEALTH_KEY_SET for k in turn.knowledge_keys):
            failures.append(f"E: official質問にhealthを根拠にしている {msg[:12]}")
        if types == ["health"] and "visit_course_prices" in turn.knowledge_keys:
            failures.append("E: health質問に料金Knowledgeを載せている")

    print("\n===== F 予約条件の会話継続 =====")
    lookup_f = mock_slots("19:00")
    f1 = continue_chat("東京で90分をお願いしたいです。", None, lookup_fn=lookup_f)
    f2 = continue_chat("明日の19時は空いてますか？", f1, lookup_fn=lookup_f)
    print_turn("F1", "東京で90分をお願いしたいです。", f1)
    print_turn("F2", "明日の19時は空いてますか？", f2)
    if f1.primary_intent != "reservation_intent":
        failures.append(f"F1: intent={f1.primary_intent}")
    if f2.primary_intent != "reservation_intent":
        failures.append(f"F2: intent={f2.primary_intent}")
    if not lookup_f.calls:
        failures.append("F2: 予約システム未使用")
    else:
        args = lookup_f.calls[-1]
        if args.get("area") != "tokyo" or args.get("duration_minutes") != 90:
            failures.append(f"F2: 東京/90分未保持 {args}")
    if re.search(r"東京ですか|90分ですか", f2.reply or ""):
        failures.append("F2: 既知情報を聞き直している")
    if f2.available_slots != ["19:00"]:
        failures.append(f"F2: slots={f2.available_slots}")

    lookup_fe = mock_slots("10:00", "18:00", "19:30")
    fe1 = continue_chat("東京で90分をお願いしたいです。", None, lookup_fn=lookup_fe)
    fe2 = continue_chat("明日の夜ならどうですか？", fe1, lookup_fn=lookup_fe)
    print_turn("F-eve2", "明日の夜ならどうですか？", fe2)
    if fe2.primary_intent != "reservation_intent":
        failures.append(f"F-eve: intent={fe2.primary_intent}")
    if not lookup_fe.calls:
        failures.append("F-eve: 予約システム未使用")
    if fe2.requested_time == "19:00":
        failures.append("F-eve: 夜を19:00に変換している")
    if fe2.requested_time_range != "evening":
        failures.append(f"F-eve: time_range={fe2.requested_time_range}")
    if set(fe2.available_slots) != {"18:00", "19:30"}:
        failures.append(f"F-eve: 夜フィルタ後 slots={fe2.available_slots}")
    if "10:00" in fe2.available_slots:
        failures.append("F-eve: 朝の枠を夜候補に残している")

    print("\n===== 10 空き枠捏造防止（構造化） =====")
    lookup_s = mock_slots("18:00", "19:30")
    last_slot = run_chat("東京で90分、明日空いてますか？", lookup_fn=lookup_s)
    print_turn("SLOT-1", "東京で90分、明日空いてますか？", last_slot)
    if last_slot.available_slots != ["18:00", "19:30"]:
        failures.append(f"SLOT: available_slots={last_slot.available_slots}")
    if invents_unreturned_slot(last_slot.reply or ""):
        failures.append("SLOT: 20:00等を予約可能として追加")
    print("  structured slots=18:00,19:30 固定。本文の時刻記載は必須としない")

    print("\n===== 11 予約APIエラー =====")
    t_err = run_chat("東京で90分、明日の19時は空いてますか？", lookup_fn=boom_lookup)
    print_turn("ERR", "東京で90分、明日の19時は空いてますか？", t_err)
    if t_err.reply != BOOKING_LOOKUP_ERROR_REPLY:
        failures.append("ERR: 安全なエラー文でない")
    if claims_availability(t_err.reply or "") or "空いていません" in (t_err.reply or ""):
        failures.append("ERR: 空きを推測している")
    if "営業時間" in (t_err.reply or ""):
        failures.append("ERR: 営業時間を理由にしている")
    if leaks_secret(t_err.reply or ""):
        failures.append("ERR: 内部情報漏洩")

    print("\n===== 12 情報不足 =====")
    t_need = run_chat("予約したいです。")
    print_turn("NEED", "予約したいです。", t_need)
    if t_need.reservation_api_called:
        failures.append("NEED: 情報不足なのに予約API")
    if t_need.primary_intent != "reservation_intent":
        failures.append(f"NEED: intent={t_need.primary_intent}")
    if count_followup_questions(t_need.reply or "") > 2:
        failures.append(f"NEED: 質問が多すぎる {count_followup_questions(t_need.reply or '')}")

    print("\n===== 14 代名詞 =====")
    p1 = continue_chat("腰が痛いです。", None)
    p2 = continue_chat("それなら鍼と整体どっちがいい？", p1)
    print_turn("P2", "それなら鍼と整体どっちがいい？", p2)
    if p2.conversation_id != p1.conversation_id:
        failures.append("P2: conversation_id が切れている")
    if p2.primary_intent != "treatment_consultation":
        failures.append(f"P2: intent={p2.primary_intent}")
    p2_state = _STORE.get(p2.conversation_id)
    prior_blob = " ".join(p2_state.prior_user_texts() if p2_state else [])
    if "腰" not in prior_blob:
        failures.append("P2: メモリに直前の腰の相談が残っていない")
    known = build_known_facts_prompt(
        [t for t in (p2_state.prior_user_texts() if p2_state else []) if t != "それなら鍼と整体どっちがいい？"]
    )
    if "腰" not in known:
        failures.append("P2: known facts に腰がなく、代名詞の参照材料がない")
    if "notes" not in (p2.source_types or []):
        failures.append("P2: notes が使われていない")
    if "腰" not in (p2.reply or "") and "腰痛" not in (p2.reply or ""):
        llm_notes.append(
            "P2: メモリとknown factsには腰があるが、回答文への言及はLLM依存"
        )

    print("\n===== 15 追加質問制御 =====")
    q1 = run_chat("腰が痛いです。特に座っているときがつらいです。")
    print_turn("Q1", "腰が痛いです。特に座っているときがつらいです。", q1)
    if re.search(r"どこが(痛い|つらい)|どのあたり", q1.reply or ""):
        failures.append("Q1: 部位を再質問")
    if re.search(r"どんな(とき|時|場面).{0,8}(痛い|つらい)", q1.reply or "") and "座" in (q1.reply or ""):
        pass
    if count_followup_questions(q1.reply or "") > 2:
        failures.append(f"Q1: 質問数 {count_followup_questions(q1.reply or '')}")

    print("\n===== 16 Safety境界 =====")
    for msg in (
        "肩が凝っています",
        "腰が重いです",
        "最近少し疲れています",
        "運動したら筋肉痛になりました",
    ):
        if is_emergency_message(msg):
            failures.append(f"Safety: 通常症状を緊急判定 {msg}")
        turn = run_chat(msg, match_fn=None)
        if turn.emergency:
            failures.append(f"Safety: 通常をemergency {msg}")
        if "救急" in (turn.reply or "") and "筋肉痛" in msg:
            failures.append("Safety: 筋肉痛を救急へ")
    emergencies = (
        "突然、片側の手足に力が入らなくなりました",
        "意識がおかしいです",
        "強い胸痛があります",
        "呼吸が苦しいです",
        "突然の激しい頭痛です",
        "大きな外傷を負いました",
        "大量出血しています",
        "症状が急激に悪化しています",
    )
    for msg in emergencies:
        if not is_emergency_message(msg):
            failures.append(f"Safety: 緊急を見逃し {msg}")
        turn = run_chat(msg, match_fn=boom, complete_fn=boom, lookup_fn=boom_lookup)
        if not turn.emergency or turn.rag_called or turn.openai_called or turn.reservation_api_called:
            failures.append(f"Safety: 緊急時に通常処理 {msg}")
        if turn.reply != EMERGENCY_REPLY:
            failures.append(f"Safety: 固定文でない {msg}")

    print("\n===== 22 XSS/秘密情報 =====")
    xss = run_chat(
        "こんにちは",
        complete_fn=lambda _m: "<script>alert(1)</script><img src=x onerror=alert(1)>",
        match_fn=lambda *_a, **_k: [],
    )
    if "<script>" not in (xss.reply or ""):
        # complete_fn の文字列がそのまま reply になること（実行ではなくテキスト）
        failures.append("XSS: テキストとしての返却が確認できない")
    from app import app

    js = open(os.path.join(ROOT, "static", "js", "karin_chat.js"), encoding="utf-8").read()
    css = open(os.path.join(ROOT, "static", "css", "karin_chat.css"), encoding="utf-8").read()
    widget = open(os.path.join(ROOT, "templates", "_karin_chat.html"), encoding="utf-8").read()
    if "innerHTML" in js:
        failures.append("XSS: UIが innerHTML を使用")
    if "textContent" not in js:
        failures.append("XSS: textContent がない")
    with app.test_client() as client:
        chat_page = client.get("/chat")
        index_page = client.get("/")
        book_page = client.get("/book")
        icon = client.get("/static/images/chatbotfaceicon.png")
        empty = client.post("/api/chat", json={})
        empty_body = empty.get_json(silent=True) or {}
        print("  /chat", chat_page.status_code, "/book", book_page.status_code, "icon", icon.status_code)
        if chat_page.status_code != 200:
            failures.append("UI: /chat が開けない")
        if index_page.status_code != 200:
            failures.append("UI: トップが開けない")
        if "相談する" not in index_page.get_data(as_text=True) or "/chat" not in index_page.get_data(as_text=True):
            failures.append("UI: トップの相談する導線がない")
        if "karin-chat-fab" not in index_page.get_data(as_text=True):
            failures.append("UI: 右下アイコン起動がない")
        if icon.status_code != 200 or "png" not in (icon.content_type or "").lower():
            failures.append("UI: 顔アイコンPNGが読めない")
        if "chatbotfaceicon.png" not in widget:
            failures.append("UI: AIアイコン参照がない")
        if "img.alt = \"KARiN.chatbot\"" not in js:
            failures.append("UI: AIアイコン alt がない")
        if re.search(r"row--user[\s\S]{0,400}chatbotfaceicon", js):
            failures.append("UI: ユーザー側にアイコンを付ける実装")
        if "payload.conversation_id" not in js:
            failures.append("UI: 2ターン目の conversation_id がない")
        if "新しく相談する" not in widget or "conversationId = null" not in js:
            failures.append("UI: 新しく相談するがない")
        if "/book" not in chat_page.get_data(as_text=True) and "ご予約" not in widget:
            failures.append("UI: /book 導線がない")
        if book_page.status_code != 200:
            failures.append("UI: /book が開けない")
        if "@media (max-width: 767px)" not in css or "min-height: 44px" not in css:
            failures.append("UI: スマホ幅/タップ領域の指定がない")
        if leaks_secret(json.dumps(empty_body, ensure_ascii=False)):
            failures.append("SEC: APIエラーに秘密情報")
        if empty.status_code == 200:
            failures.append("SEC: 空メッセージが200")

    print("\n===== 23 Conversation memory =====")
    reset_store_for_tests()
    mem_a = get_or_create_conversation(None)
    append_turn(mem_a, "腰が痛いです。", "承知しました。")
    mem_b = get_or_create_conversation(None)
    append_turn(mem_b, "肩こりです。", "承知しました。")
    if mem_a.conversation_id == mem_b.conversation_id:
        failures.append("MEM: 別会話が同一ID")
    if any("肩" in (m.get("content") or "") for m in mem_a.messages):
        failures.append("MEM: 会話が混線")
    fresh = get_or_create_conversation(None)
    if any("腰" in (m.get("content") or "") for m in fresh.messages):
        failures.append("MEM: 新IDが過去を参照")
    long_state = get_or_create_conversation(None)
    for i in range(9):
        append_turn(long_state, f"user-{i}", f"ai-{i}")
    if long_state.user_turn_count > MAX_USER_TURNS:
        failures.append(f"MEM: user turns={long_state.user_turn_count}")
    if len(history_messages(long_state)) > MAX_USER_TURNS * 2:
        failures.append("MEM: 履歴が16超")
    expired = get_or_create_conversation(None)
    expired_id = expired.conversation_id
    expired.updated_at = time.time() - TTL_SECONDS - 10
    get_or_create_conversation(None)
    if expired_id in _STORE:
        failures.append("MEM: TTL後も残っている")
    reset_store_for_tests()
    first_ids = []
    for _ in range(MAX_CONVERSATIONS):
        first_ids.append(get_or_create_conversation(None).conversation_id)
    if len(_STORE) != MAX_CONVERSATIONS:
        failures.append(f"MEM: 200件まで保持できない {len(_STORE)}")
    extra = get_or_create_conversation(None)
    if len(_STORE) > MAX_CONVERSATIONS:
        failures.append(f"MEM: 201件目追加後も上限超過 {len(_STORE)}")
    if extra.conversation_id not in _STORE:
        failures.append("MEM: 201件目の会話が保持されていない")
    if first_ids[0] in _STORE:
        failures.append("MEM: 201件目追加後も最古の会話が残っている")
    for _ in range(4):
        get_or_create_conversation(None)
    if len(_STORE) > MAX_CONVERSATIONS:
        failures.append(f"MEM: 追加後に200以下へ収束しない {len(_STORE)}")
    mem_src = inspect.getsource(sys.modules["karin_chat_memory"])
    if re.search(r"^(from flask import|import flask)\b", mem_src, re.M):
        failures.append("MEM: staff session と結合している")
    if re.search(r"\bsession\.(get|pop)\b|session\[", mem_src):
        failures.append("MEM: memory が session を参照している")
    from app import api_chat as api_chat_fn

    api_src = inspect.getsource(api_chat_fn)
    api_body = api_src.split('"""', 2)[-1] if '"""' in api_src else api_src
    if re.search(r"\bsession\.(get|pop)\b|session\[", api_body):
        failures.append("MEM: /api/chat が session を使っている")

    after_n, after_h = snapshot_knowledge(admin)
    after_counts = type_counts(fetch_all(admin))
    print(f"\nsnapshot after: n={after_n} hash={after_h[:16]}...")
    if (after_n, after_h) != (before_n, before_h):
        failures.append("Knowledge DB がC7中に変化した")
    if after_counts != counts:
        failures.append(f"件数変化 {after_counts}")

    print("\n===== LLM依存メモ =====")
    for note in llm_notes:
        print("-", note)

    if failures:
        print("\nC7 FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nC7 総合テスト: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
