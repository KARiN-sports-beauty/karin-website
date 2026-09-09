"""会話に応じた定義済み選択肢。Knowledgeは読み取り専用。INSERTなし。

  python scripts/test_karin_chat_choices.py
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
from karin_chat import INITIAL_RESERVATION_REPLY, chat_public_payload, run_chat  # noqa: E402
from karin_chat_booking import BookingDraft, PHASE_GUEST  # noqa: E402
from karin_chat_choices import (  # noqa: E402
    CHOICE_SETS,
    FREE_OTHER,
    choice_set,
    select_followup_choices,
)
from karin_chat_intent import detect_intents  # noqa: E402
from karin_chat_memory import get_or_create_conversation, reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"


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


def complete_pain_where(_messages):
    return "どのあたりの痛みが気になりますか？"


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


def main() -> int:
    print("mode: followup choices / Knowledge読み取り専用 / INSERTなし")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    print("\n===== 1 鍼と整体 → 目的選択肢 =====")
    reset_store_for_tests()
    t1 = run_chat(
        "鍼と整体、どちらが合いそうですか？",
        match_fn=empty_match,
        complete_fn=complete_goal,
    )
    want_goal = choice_set("treatment_goal")
    print("  choices", t1.followup_choices)
    if t1.followup_choices != want_goal:
        failures.append(f"1: {t1.followup_choices}")
    if FREE_OTHER not in (t1.followup_choices or []):
        failures.append("1: その他がない")
    if len(t1.followup_choices) > 5:
        failures.append("1: 選択肢が多すぎる")
    payload = chat_public_payload(t1)
    if payload.get("followup_choices") != want_goal:
        failures.append("1: 公開JSONに出ていない")
    if t1.preferred_treatment:
        failures.append("1: 比較質問だけで施術が決まっている")

    print("\n===== 2 痛みを軽減したい → 通常発話 =====")
    t2 = continue_chat(
        "痛みを軽減したい",
        t1,
        match_fn=empty_match,
        complete_fn=complete_pain_where,
    )
    print("  phase", t2.booking_phase, "treatment", t2.preferred_treatment, t2.followup_choices)
    if t2.preferred_treatment in ("鍼", "整体", "美容鍼"):
        failures.append("5: 痛みチップで施術を自動決定している")
    if "腰" not in (t2.followup_choices or []) and t2.followup_choices != choice_set("pain_area"):
        failures.append(f"3: 次セットが出ない {t2.followup_choices}")

    print("\n===== 4 その他・自由に相談 =====")
    t_free = continue_chat(
        FREE_OTHER,
        t2,
        match_fn=empty_match,
        complete_fn=complete_ok,
    )
    if t_free.followup_choices:
        failures.append(f"4: その他のあとにもチップがある {t_free.followup_choices}")

    print("\n===== 6 予約会話中は相談チップを出さない =====")
    reset_store_for_tests()
    t_book = run_chat("予約がしたいです", match_fn=empty_match, complete_fn=complete_ok)
    print("  book choices", t_book.followup_choices, "cta", t_book.show_booking_cta)
    if not t_book.show_booking_cta:
        failures.append("9: 予約CTAがない")
    if t_book.reply != INITIAL_RESERVATION_REPLY:
        failures.append("9: 初回予約案内が変わっている")
    if "ヘッダー" in (t_book.reply or ""):
        failures.append("10: 予約案内にヘッダーがある")
    if "痛みを軽減したい" in (t_book.followup_choices or []):
        failures.append("6: 予約中に相談用選択肢がある")
    if "東京" not in (t_book.followup_choices or []):
        failures.append(f"6: エリア選択肢がない {t_book.followup_choices}")

    print("\n===== 7 guest_info では出さない =====")
    reset_store_for_tests()
    lookup = mock_slots("18:00")

    def book_fn(*_a, **_k):
        raise AssertionError("INSERTしてはいけない")

    g0 = run_chat("予約したいです", match_fn=empty_match, complete_fn=complete_ok, lookup_fn=lookup, book_fn=book_fn)
    g1 = continue_chat("東京で9/10 18:00、90分", g0, match_fn=empty_match, complete_fn=complete_ok, lookup_fn=lookup, book_fn=book_fn)
    g2 = continue_chat("お願いします", g1, match_fn=empty_match, complete_fn=complete_ok, lookup_fn=lookup, book_fn=book_fn)
    g3 = continue_chat("はい", g2, match_fn=empty_match, complete_fn=complete_ok, lookup_fn=lookup, book_fn=book_fn)
    print("  guest", g3.booking_phase, t_book.followup_choices if False else g3.followup_choices)
    if g3.booking_phase != "guest_info":
        failures.append(f"7: phase={g3.booking_phase}")
    if g3.followup_choices:
        failures.append(f"7: guest_info で選択肢 {g3.followup_choices}")
    if g3.booking_create_called:
        failures.append("7: guest_info で予約作成している")

    print("\n===== 8 緊急 =====")
    reset_store_for_tests()
    t_em = run_chat(
        "急に右半身に力が入らなくなりました。",
        match_fn=empty_match,
        complete_fn=lambda _m: "should-not-run",
    )
    if not t_em.emergency:
        failures.append("8: 緊急判定できていない")
    if t_em.followup_choices:
        failures.append(f"8: 緊急で選択肢 {t_em.followup_choices}")
    if t_em.show_booking_cta:
        failures.append("8: 緊急で予約CTA")

    print("\n===== unit select =====")
    sleep_intent = detect_intents("なかなか眠れません")
    sleep_choices = select_followup_choices(
        user_text="なかなか眠れません",
        reply="どんな睡眠の悩みが一番気になりますか？",
        intent=sleep_intent,
        draft=BookingDraft(phase="consult"),
    )
    if sleep_choices != choice_set("sleep"):
        failures.append(f"sleep: {sleep_choices}")
    guest_choices = select_followup_choices(
        user_text="藤田",
        reply="ご予約に必要な情報をお伺いします。",
        intent=detect_intents("予約したいです"),
        draft=BookingDraft(phase=PHASE_GUEST, reservation_intent=True),
    )
    if guest_choices:
        failures.append(f"guest unit: {guest_choices}")
    if FREE_OTHER not in CHOICE_SETS["treatment_goal"] and FREE_OTHER not in choice_set("treatment_goal"):
        failures.append("その他がセットに載っていない")

    js = open(os.path.join(ROOT, "static", "js", "karin_chat.js"), encoding="utf-8").read()
    booking_src = open(os.path.join(ROOT, "karin_chat_booking.py"), encoding="utf-8").read()
    if "followup_choices" not in js or "normalizeChoices" not in js:
        failures.append("JS: APIの選択肢を出していない")
    if "ヘッダー" in INITIAL_RESERVATION_REPLY:
        failures.append("10: INITIAL にヘッダーがある")
    if "ヘッダーの『ご予約』" in booking_src:
        failures.append("10: 予約案内にヘッダーが残っている")
    if "sendMessage(sample)" not in js:
        failures.append("2: チップが通常送信でない")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if after_h != before_h:
        failures.append("Knowledge hash が変わった")

    if failures:
        print("\nFAIL")
        for item in failures:
            print(" -", item)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
