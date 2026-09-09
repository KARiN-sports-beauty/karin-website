"""利用分析ログ。Knowledgeは読み取り専用。予約INSERTなし。

  python scripts/test_karin_chat_usage.py
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
from karin_chat import run_chat  # noqa: E402
from karin_chat_choices import FREE_OTHER, choice_set  # noqa: E402
from karin_chat_intent import INTENT_RESERVATION, INTENT_TREATMENT  # noqa: E402
from karin_chat_memory import reset_store_for_tests  # noqa: E402
from karin_chat_usage import set_usage_log_sink  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
SECRET_FREE = "夜中に腰が痛くて眠れません。氏名は記録しないでください。"


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def empty_match(*_a, **_k):
    return []


def complete_goal(_messages):
    return (
        "どちらが合うかは、今の状態や目的によって変わります。"
        "まず、どんな状態を改善したいか教えていただければ、より具体的に一緒に考えられます。"
    )


def complete_ok(_messages):
    return "承知しました。"


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def mock_slots(*times: str):
    def lookup(**kwargs):
        return {
            "date": kwargs.get("date"),
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": kwargs.get("duration_minutes"),
            "staff": [],
            "free_row": {
                "staff_name": "フリー",
                "slots": [{"time": t, "available": True} for t in times],
            },
        }

    return lookup


def boom_insert(_row):
    raise RuntimeError("usage insert failed on purpose")


def row_blob(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False)


def main() -> int:
    print("mode: usage logs / Knowledge読み取り専用 / 予約INSERTなし")
    reset_store_for_tests()
    captured: list[dict] = []
    set_usage_log_sink(captured.append)
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    print("\n===== Test 1 通常応答 =====")
    t1 = run_chat(
        "鍼と整体、どちらが合いそうですか？",
        match_fn=empty_match,
        complete_fn=complete_goal,
    )
    if not (t1.reply or "").strip():
        failures.append("1: reply がない")
    if t1.emergency:
        failures.append("1: 緊急になっている")

    print("\n===== Test 2 動的選択肢 =====")
    want_goal = choice_set("treatment_goal")
    print("  choices", t1.followup_choices)
    if t1.followup_choices != want_goal:
        failures.append(f"2: {t1.followup_choices}")
    if not captured:
        failures.append("1: ログが無い")
    else:
        first = captured[0]
        if first.get("choice_set") != "treatment_goal":
            failures.append(f"2: choice_set={first.get('choice_set')}")
        if first.get("shown_choices") != want_goal:
            failures.append(f"2: shown={first.get('shown_choices')}")
        if first.get("input_type") != "free_text":
            failures.append(f"1: input_type={first.get('input_type')}")
        if first.get("selected_choice") is not None:
            failures.append("1: 初回なのに selected_choice がある")
        if first.get("next_intent") != INTENT_TREATMENT:
            failures.append(f"5: next_intent={first.get('next_intent')}")

    print("\n===== Test 3 選択肢クリック =====")
    before = len(captured)
    t2 = continue_chat(
        "痛みを軽減したい",
        t1,
        match_fn=empty_match,
        complete_fn=lambda _m: "どのあたりの痛みが気になりますか？",
    )
    if len(captured) != before + 1:
        failures.append(f"3: ログ件数 {len(captured) - before}")
    else:
        click = captured[-1]
        print("  selected", click.get("selected_choice"), click.get("input_type"))
        if click.get("input_type") != "choice":
            failures.append(f"3: input_type={click.get('input_type')}")
        if click.get("selected_choice") != "痛みを軽減したい":
            failures.append(f"3: selected={click.get('selected_choice')}")
        if click.get("intent") != INTENT_TREATMENT:
            failures.append(f"5: intent={click.get('intent')}")

    print("\n===== Test 4 自由入力本文を保存しない =====")
    reset_store_for_tests()
    captured.clear()
    set_usage_log_sink(captured.append)
    t_free = run_chat(
        SECRET_FREE,
        match_fn=empty_match,
        complete_fn=complete_ok,
    )
    blob = row_blob(captured)
    if SECRET_FREE in blob:
        failures.append("4: 自由入力本文がログにある")
    if "記録しないでください" in blob:
        failures.append("4: 自由入力の一部がログにある")
    if not captured or captured[-1].get("input_type") != "free_text":
        failures.append("4: free_text になっていない")
    if captured and captured[-1].get("selected_choice") is not None:
        failures.append("4: selected_choice がある")
    if not (t_free.reply or "").strip():
        failures.append("1: 自由入力の応答がない")

    print("\n===== Test 6 予約開始 =====")
    reset_store_for_tests()
    captured.clear()
    set_usage_log_sink(captured.append)
    t_book = run_chat("予約がしたいです", match_fn=empty_match, complete_fn=complete_ok)
    if not t_book.show_booking_cta:
        failures.append("6: CTA がない")
    started = [r for r in captured if r.get("booking_started")]
    if not started:
        failures.append("6: booking_started がない")
    elif started[-1].get("next_intent") != INTENT_RESERVATION:
        failures.append(f"6: next_intent={started[-1].get('next_intent')}")
    if any(r.get("booking_completed") for r in captured):
        failures.append("6: 開始だけで completed")

    print("\n===== Test 7 予約完了フラグ =====")
    reset_store_for_tests()
    captured.clear()
    set_usage_log_sink(captured.append)
    creates: list[dict] = []

    def book_fn(*args, **kwargs):
        creates.append({"args": args, "kwargs": kwargs})
        return {"staff_name": "フリー"}

    lookup = mock_slots("18:00")
    g0 = run_chat(
        "予約したいです",
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup,
        book_fn=book_fn,
    )
    g1 = continue_chat(
        "東京で9/10 18:00、90分",
        g0,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup,
        book_fn=book_fn,
    )
    g2 = continue_chat(
        "お願いします",
        g1,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup,
        book_fn=book_fn,
    )
    g3 = continue_chat(
        "はい",
        g2,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup,
        book_fn=book_fn,
    )
    g4 = continue_chat(
        "姓：藤田、名：幸士、090-1234-5678、test@example.com、東京都渋谷区神南",
        g3,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup,
        book_fn=book_fn,
    )
    g5 = continue_chat(
        "はい",
        g4,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup,
        book_fn=book_fn,
    )
    print("  done", g5.booking_completed, "creates", len(creates), "phase", g5.booking_phase)
    if not g5.booking_completed or not creates:
        failures.append("7: 予約完了していない")
    done_rows = [r for r in captured if r.get("booking_completed")]
    if not done_rows:
        failures.append("7: booking_completed ログがない")
    guest_blob = row_blob(captured)
    if "藤田" in guest_blob or "幸士" in guest_blob:
        failures.append("4: 氏名が分析ログにある")
    if "090-1234-5678" in guest_blob or "09012345678" in guest_blob:
        failures.append("4: 電話が分析ログにある")
    if "test@example.com" in guest_blob:
        failures.append("4: メールが分析ログにある")
    if "渋谷区神南" in guest_blob:
        failures.append("4: 住所が分析ログにある")

    print("\n===== Test 8 INSERT失敗でも応答 =====")
    reset_store_for_tests()
    set_usage_log_sink(boom_insert)
    t_ok = run_chat(
        "鍼と整体、どちらが合いそうですか？",
        match_fn=empty_match,
        complete_fn=complete_goal,
    )
    if not (t_ok.reply or "").strip():
        failures.append("8: INSERT失敗で応答が止まった")
    if t_ok.followup_choices != want_goal:
        failures.append(f"8: 選択肢が壊れた {t_ok.followup_choices}")

    print("\n===== Test 9 INSERT失敗でも予約完了 =====")
    reset_store_for_tests()
    set_usage_log_sink(boom_insert)
    creates.clear()
    lookup2 = mock_slots("18:00")
    h0 = run_chat(
        "予約したいです",
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup2,
        book_fn=book_fn,
    )
    h1 = continue_chat(
        "東京で9/10 18:00、90分",
        h0,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup2,
        book_fn=book_fn,
    )
    h2 = continue_chat(
        "お願いします",
        h1,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup2,
        book_fn=book_fn,
    )
    h3 = continue_chat(
        "はい",
        h2,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup2,
        book_fn=book_fn,
    )
    h4 = continue_chat(
        "姓：藤田、名：幸士、090-1234-5678、test@example.com、東京都渋谷区神南",
        h3,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup2,
        book_fn=book_fn,
    )
    h5 = continue_chat(
        "はい",
        h4,
        match_fn=empty_match,
        complete_fn=complete_ok,
        lookup_fn=lookup2,
        book_fn=book_fn,
    )
    if not h5.booking_completed or not creates:
        failures.append("9: INSERT失敗で予約が止まった")
    if "ご予約が完了しました" not in (h5.reply or ""):
        failures.append("9: 完了文言がない")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if after_n != before_n or after_h != before_h:
        failures.append("Knowledge が変化している")

    if failures:
        print("\nFAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
