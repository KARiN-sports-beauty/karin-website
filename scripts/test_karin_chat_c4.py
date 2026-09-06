"""C4 既存予約システムへの空き確認。本番Knowledgeは変更しない。予約は確定しない。

  python scripts/test_karin_chat_c4.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import EMERGENCY_REPLY, count_followup_questions, run_chat  # noqa: E402
from karin_chat_booking import BOOKING_LOOKUP_ERROR_REPLY  # noqa: E402
from karin_chat_memory import reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
JST = timezone(timedelta(hours=9))


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return len(rows), digest


def tomorrow_iso() -> str:
    return (datetime.now(JST).date() + timedelta(days=1)).isoformat()


def claims_availability(reply: str) -> bool:
    return any(
        p in (reply or "")
        for p in ("空いています", "空いております", "空きがあります", "予約可能です", "お取りできます")
    )


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


def print_turn(label: str, message: str, turn) -> None:
    print(f"  -- {label} --")
    print("  user:", message)
    print("  intent:", turn.primary_intent, turn.secondary_intents)
    print("  api_called:", turn.reservation_api_called, "status:", turn.api_status)
    print("  area/date/duration/time/range:", turn.requested_area, turn.requested_date, turn.requested_duration, turn.requested_time, turn.requested_time_range)
    print("  slots:", turn.available_slots)
    print("  emergency/openai/rag:", turn.emergency, turn.openai_called, turn.rag_called)
    print("  reply_preview:", (turn.reply or "")[:160].replace("\n", " / "))


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def main() -> int:
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")
    print("mode: Knowledge読み取り専用 / 予約確定なし / 空きは既存予約処理へ")
    reset_store_for_tests()
    admin = get_admin_client()
    before_n, before_hash = snapshot_knowledge(admin)
    print("knowledge snapshot before:", before_n, before_hash[:12])
    failures: list[str] = []
    tomorrow = tomorrow_iso()

    print("\n===== Test 1 明日の夜に予約したい =====")
    t1 = run_chat("明日の夜に予約したいです")
    print_turn("T1", "明日の夜に予約したいです", t1)
    if t1.primary_intent != "reservation_intent":
        failures.append(f"Test1: intent={t1.primary_intent}")
    if t1.requested_date != tomorrow:
        failures.append(f"Test1: date={t1.requested_date}")
    if t1.requested_time_range != "evening":
        failures.append("Test1: 夜が time_range になっていない")
    if t1.requested_time == "19:00":
        failures.append("Test1: 夜を19:00に変換している")
    if t1.reservation_api_called:
        failures.append("Test1: エリア不足なのにAPIを呼んだ")
    if t1.api_status != "skipped_insufficient":
        failures.append(f"Test1: api_status={t1.api_status}")

    print("\n===== Test 2 明日の19時 =====")
    t2 = run_chat("明日の19時って空いてますか？")
    print_turn("T2", "明日の19時って空いてますか？", t2)
    if t2.primary_intent != "reservation_intent":
        failures.append(f"Test2: intent={t2.primary_intent}")
    if t2.requested_time != "19:00":
        failures.append(f"Test2: time={t2.requested_time}")
    if t2.requested_date != tomorrow:
        failures.append("Test2: 明日が日付になっていない")
    if t2.reservation_api_called:
        failures.append("Test2: エリア不足なのにAPIを呼んだ")

    print("\n===== Test 3 東京90分・明日の夜 =====")
    lookup3 = mock_slots("10:00", "18:00", "19:30")
    t3 = run_chat("東京で90分、明日の夜にお願いしたいです", lookup_fn=lookup3)
    print_turn("T3", "東京で90分、明日の夜にお願いしたいです", t3)
    if t3.primary_intent != "reservation_intent":
        failures.append(f"Test3: intent={t3.primary_intent}")
    if not t3.reservation_api_called or not lookup3.calls:
        failures.append("Test3: 予約APIを呼んでいない")
    else:
        args = lookup3.calls[0]
        if args.get("area") != "tokyo":
            failures.append(f"Test3: area={args.get('area')}")
        if args.get("duration_minutes") != 90:
            failures.append(f"Test3: duration={args.get('duration_minutes')}")
        if args.get("date") != tomorrow:
            failures.append(f"Test3: date={args.get('date')}")
        if args.get("place_type") != "visit":
            failures.append(f"Test3: place_type={args.get('place_type')}")
        if "time" in args:
            failures.append("Test3: 夜を具体時刻としてAPIに渡している")
    if t3.requested_time_range != "evening":
        failures.append("Test3: 夜を保持していない")
    if "10:00" in t3.available_slots:
        failures.append("Test3: 夜以外の枠を夜の結果に混ぜている")
    if "18:00" not in t3.available_slots or "19:30" not in t3.available_slots:
        failures.append(f"Test3: 夜の空き枠が反映されていない {t3.available_slots}")

    print("\n===== Test 4 会話継続 =====")
    t4a = continue_chat("腰が痛いです", None)
    t4b = continue_chat("鍼と整体ならどっちがいいですか？", t4a)
    t4c = continue_chat("じゃあ明日お願いしたいです", t4b)
    print_turn("T4-3", "じゃあ明日お願いしたいです", t4c)
    if t4a.conversation_id != t4c.conversation_id:
        failures.append("Test4: conversation_id が切れている")
    if t4c.primary_intent != "reservation_intent":
        failures.append(f"Test4: turn3 intent={t4c.primary_intent}")
    if t4c.turn_index != 3:
        failures.append(f"Test4: turn={t4c.turn_index}")
    if t4c.requested_date != tomorrow:
        failures.append("Test4: 明日が維持されていない")
    if t4a.primary_intent != "consultation" or t4b.primary_intent != "treatment_consultation":
        failures.append("Test4: 過去ターンのintent再評価がおかしい")

    print("\n===== Test 5 予約したいです だけ =====")
    t5 = run_chat("予約したいです")
    print_turn("T5", "予約したいです", t5)
    if t5.primary_intent != "reservation_intent":
        failures.append(f"Test5: intent={t5.primary_intent}")
    if t5.reservation_api_called:
        failures.append("Test5: 情報不足なのにAPIを呼んだ")
    if count_followup_questions(t5.reply) > 2:
        failures.append(f"Test5: 質問が多すぎる {count_followup_questions(t5.reply)}")

    print("\n===== Test 6 Knowledgeから空きと判定しない =====")
    t6 = run_chat("明日の20時って空いてますか？")
    print_turn("T6", "明日の20時って空いてますか？", t6)
    if t6.reservation_api_called:
        failures.append("Test6: エリア不足なのにAPIを呼んだ")
    if claims_availability(t6.reply or ""):
        failures.append("Test6: Knowledgeの営業時間から空きと判定している")
    if t6.requested_time != "20:00":
        failures.append(f"Test6: time={t6.requested_time}")

    print("\n===== Test 7 予約APIエラー =====")
    t7 = run_chat("東京で90分、明日の19時は空いてますか？", lookup_fn=boom_lookup)
    print_turn("T7", "東京で90分、明日の19時は空いてますか？", t7)
    if not t7.reservation_api_called:
        failures.append("Test7: API呼び出し前に止まっている")
    if t7.api_status != "error":
        failures.append(f"Test7: api_status={t7.api_status}")
    if t7.openai_called or t7.rag_called:
        failures.append("Test7: エラー時にOpenAI/RAGを呼んでいる")
    if t7.reply != BOOKING_LOOKUP_ERROR_REPLY:
        failures.append("Test7: 安全なエラー文でない")
    leaked = ("secret_table", "SELECT", "https://internal", "Traceback", "OPENAI", "sk-")
    if any(x in (t7.reply or "") for x in leaked):
        failures.append("Test7: 内部エラー詳細が漏れている")
    if claims_availability(t7.reply or ""):
        failures.append("Test7: エラーなのに空きを推測している")

    print("\n===== Test 8 緊急症状 =====")
    t8a = continue_chat("肩が凝っています", None)
    t8b = continue_chat(
        "急に右半身に力が入らなくなりました",
        t8a,
        lookup_fn=lambda **_k: (_ for _ in ()).throw(AssertionError("booking")),
        match_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("rag")),
        complete_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("openai")),
    )
    print_turn("T8-2", "急に右半身に力が入らなくなりました", t8b)
    if not t8b.emergency:
        failures.append("Test8: 安全ゲートにかかっていない")
    if t8b.reservation_api_called or t8b.openai_called or t8b.rag_called:
        failures.append("Test8: 緊急時に予約API/OpenAI/RAGを呼んでいる")
    if t8b.reply != EMERGENCY_REPLY:
        failures.append("Test8: 固定の受診優先文でない")

    print("\n===== Test 9 既知情報の再利用 =====")
    lookup9 = mock_slots("19:00")
    t9a = continue_chat("東京で90分をお願いしたいです", None, lookup_fn=lookup9)
    t9b = continue_chat("明日の19時は空いてますか？", t9a, lookup_fn=lookup9)
    print_turn("T9-1", "東京で90分をお願いしたいです", t9a)
    print_turn("T9-2", "明日の19時は空いてますか？", t9b)
    if t9b.primary_intent != "reservation_intent":
        failures.append(f"Test9: turn2 intent={t9b.primary_intent}")
    if not lookup9.calls:
        failures.append("Test9: 予約APIを呼んでいない")
    else:
        args = lookup9.calls[-1]
        if args.get("area") != "tokyo" or args.get("duration_minutes") != 90:
            failures.append(f"Test9: 既知の東京/90分をAPIへ渡していない {args}")
        if args.get("date") != tomorrow:
            failures.append(f"Test9: date={args.get('date')}")
    if re.search(r"東京ですか|90分ですか", t9b.reply or ""):
        failures.append("Test9: 既知情報を聞き直している")
    if t9b.requested_time != "19:00":
        failures.append(f"Test9: time={t9b.requested_time}")

    print("\n===== Test 10 APIにない時刻を追加しない =====")
    lookup10 = mock_slots("18:00", "19:30")
    t10 = run_chat("東京で90分、明日空いてますか？", lookup_fn=lookup10)
    print_turn("T10", "東京で90分、明日空いてますか？", t10)
    if t10.available_slots != ["18:00", "19:30"]:
        failures.append(f"Test10: available_slots={t10.available_slots}")
    if re.search(r"20(:00|時).{0,12}(空き|空いて)", t10.reply or ""):
        failures.append("Test10: APIにない20:00を空きとして提示している")
    if "18:00" not in (t10.reply or "") and "19:30" not in (t10.reply or "") and "18時" not in (t10.reply or ""):
        failures.append("Test10: APIの空き枠を伝えていない")

    after_n, after_hash = snapshot_knowledge(admin)
    print("\nknowledge snapshot after:", after_n, after_hash[:12])
    if (after_n, after_hash) != (before_n, before_hash):
        failures.append("Knowledge DB がテスト中に変更された")

    if failures:
        print("\nC4 FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nC4 テスト: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
