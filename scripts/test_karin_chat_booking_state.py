"""予約条件の短期保持（C9準備）。予約確定はしない。

  python scripts/test_karin_chat_booking_state.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import run_chat  # noqa: E402
from karin_chat_memory import reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
BOOK_MARKERS = ("/api/book", "reservations", "INSERT")


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


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


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def empty_match(*_a, **_k):
    return []


def read(path: str) -> str:
    return open(os.path.join(ROOT, path), encoding="utf-8").read()


def main() -> int:
    print("mode: 予約条件の短期保持 / 予約確定なし / Knowledge読み取り専用")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    lookup = mock_slots("18:00", "19:00")
    captured: list[str] = []

    def complete(messages):
        captured.append("\n".join(m.get("content") or "" for m in messages))
        return "承知しました。"

    print("\n===== A 予約意図 =====")
    t0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    print("  intent", t0.reservation_intent, "ready", t0.booking_ready, "cta", t0.show_booking_cta)
    if not t0.reservation_intent:
        failures.append("A: reservation_intent が true でない")
    if t0.booking_ready:
        failures.append("A: 初回なのに booking_ready")
    if not t0.show_booking_cta:
        failures.append("A: 初回 CTA がない")
    if t0.show_booking_cta and t0.booking_ready:
        failures.append("A: CTA と booking_ready が同じ意味になっている")

    print("\n===== B 条件の段階的追加 =====")
    t1 = continue_chat("東京で", t0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    t2 = continue_chat("今週の平日で空いてるところありますか？", t1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    t3 = continue_chat("夕方がいいです", t2, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    t4 = continue_chat("水曜がいいです", t3, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    t5 = continue_chat("19時がいいです", t4, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    t6 = continue_chat("60分でお願いします", t5, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    print("  B1 area", t1.requested_area, "ready", t1.booking_ready)
    print("  B2 range", t2.date_range, "date", t2.requested_date)
    print("  B3 period", t3.time_period, "time", t3.requested_time)
    print("  B4 date", t4.requested_date, "cta", t4.show_booking_cta)
    print("  B5 time", t5.requested_time)
    print("  B6 duration", t6.requested_duration, "ready", t6.booking_ready, "cta", t6.show_booking_cta)
    if t1.requested_area != "tokyo" or not t1.reservation_intent:
        failures.append("B: 東京が保持されていない")
    if t1.booking_ready:
        failures.append("B: 東京だけの段階で booking_ready")
    if t2.requested_date:
        failures.append(f"B: 今週の平日を具体日にしている {t2.requested_date}")
    if not t2.date_range:
        failures.append("B: date_range がない")
    if t3.requested_time == "19:00":
        failures.append("B: 夕方を19:00に変換している")
    if t3.time_period != "evening":
        failures.append(f"B: time_period={t3.time_period}")
    if not t4.requested_date:
        failures.append("B: 水曜が日付になっていない")
    else:
        y, m, d = t4.requested_date.split("-")
        if datetime(int(y), int(m), int(d)).weekday() != 2:
            failures.append("B: 水曜の日付が水曜日でない")
    if t4.show_booking_cta:
        failures.append("B: 水曜確認中に CTA がある")
    if t5.requested_time != "19:00":
        failures.append(f"B: 19時が保持されていない {t5.requested_time}")
    if t6.requested_duration != 60:
        failures.append(f"B: 60分が保持されていない {t6.requested_duration}")
    if t1.requested_area != "tokyo" or t6.requested_area != "tokyo":
        failures.append("B: 東京が後のターンで落ちている")

    print("\n===== C 再質問防止 =====")
    joined = "\n".join(captured)
    if re.search(r"東京・福岡|東京か福岡|東京ですか", joined) and "エリア: 東京" not in joined:
        failures.append("C: 既知の東京を聞き直すプロンプトになっている")
    if "エリア: 東京" not in joined:
        failures.append("C: 既知エリアがプロンプトにない")
    if t6.requested_duration == 60 and re.search(r"施術時間は何分", t6.reply or ""):
        failures.append("C: 60分のあと施術時間を聞き直している")
    if "これらを聞き直さないでください" not in joined:
        failures.append("C: 既知条件の再利用指示がない")

    print("\n===== D 大まかな条件を日時へ変換しない =====")
    reset_store_for_tests()
    d0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    d1 = continue_chat("来週の夜で空いてますか？", d0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    print("  D date", d1.requested_date, "time", d1.requested_time, "period", d1.time_period, "range", d1.date_range)
    if d1.requested_time == "19:00":
        failures.append("D: 夜を19:00に変換している")
    if d1.time_period != "evening":
        failures.append(f"D: time_period={d1.time_period}")
    if d1.requested_date and not d1.date_range:
        failures.append(f"D: 来週を具体1日にしている {d1.requested_date}")

    print("\n===== E 予約意図＋症状 =====")
    reset_store_for_tests()
    e0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    e1 = continue_chat("腰が痛くて鍼を受けたいです", e0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    print("  E intent", e1.reservation_intent, "treatment", e1.preferred_treatment, "primary", e1.primary_intent)
    if not e1.reservation_intent:
        failures.append("E: 予約意図が解除されている")
    if e1.primary_intent != "reservation_intent":
        failures.append(f"E: primary={e1.primary_intent}")
    if e1.preferred_treatment != "鍼":
        failures.append(f"E: 明示の鍼が保持されていない {e1.preferred_treatment}")

    print("\n===== F 明示的な相談切り替え =====")
    f1 = continue_chat(
        "予約する前に、鍼と整体どちらが自分に合うか詳しく相談したいです",
        e1,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup,
    )
    print("  F primary", f1.primary_intent, "reservation_intent", f1.reservation_intent, "ready", f1.booking_ready)
    if f1.primary_intent != "treatment_consultation":
        failures.append(f"F: primary={f1.primary_intent}")
    if f1.reservation_intent:
        failures.append("F: 明示的な相談切り替え後も reservation_intent が残っている")
    if f1.booking_ready:
        failures.append("F: 相談中なのに booking_ready")

    print("\n===== G booking_ready =====")
    reset_store_for_tests()
    g0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    g1 = continue_chat("東京で", g0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    g2 = continue_chat(
        "水曜19時、60分でお願いします",
        g1,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup,
    )
    print("  G0 ready", g0.booking_ready, "G1", g1.booking_ready, "G2", g2.booking_ready, "cta", g2.show_booking_cta)
    if g0.booking_ready or g1.booking_ready:
        failures.append("G: 条件不足なのに booking_ready")
    if not g2.booking_ready:
        failures.append("G: 東京・水曜19時・60分で booking_ready になっていない")
    if g2.requested_area != "tokyo" or g2.requested_time != "19:00" or g2.requested_duration != 60:
        failures.append("G: 主要条件が欠けている")
    if "予約をお取りしました" in (g2.reply or "") or "確定しました" in (g2.reply or ""):
        failures.append("G: 予約確定したように表示している")

    print("\n===== H CTA =====")
    if not t0.show_booking_cta:
        failures.append("H: 初回 CTA がない")
    if t2.show_booking_cta or t3.show_booking_cta or t4.show_booking_cta:
        failures.append("H: 候補確認中に CTA がある")
    if not g2.show_booking_cta:
        failures.append("H: 具体的な予約意思なのに CTA がない")
    if g2.show_booking_cta == g2.booking_ready and g0.show_booking_cta == g0.booking_ready:
        failures.append("H: CTA と booking_ready が常に一致している")

    print("\n===== I 予約処理の非実行 =====")
    chat_src = read("karin_chat.py") + read("karin_chat_booking.py") + read("karin_chat_memory.py")
    if "/api/book" in chat_src:
        failures.append("I: チャット経路に /api/book がある")
    if re.search(r"reservations.+(insert|INSERT)|table\(\"reservations\"\)", chat_src):
        failures.append("I: チャット経路から reservations INSERT がある")
    if "予約をお取りしました" in chat_src:
        failures.append("I: 予約確定文言がある")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if (after_n, after_h) != (before_n, before_h):
        failures.append("Knowledge DB がテスト中に変化した")

    if failures:
        print("\n予約条件保持 FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\n予約条件保持: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
