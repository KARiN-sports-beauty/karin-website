"""C8最終調整 + C9チャット予約。Knowledgeは読み取り専用。本番INSERTはしない。

  python scripts/test_karin_chat_c9.py
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
from karin_chat import chat_public_payload, run_chat  # noqa: E402
from karin_chat_booking import build_staff_note, format_booking_datetime  # noqa: E402
from karin_chat_memory import get_or_create_conversation, reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
JST = timezone(timedelta(hours=9))
DONE_PHRASES = ("予約をお取りしました", "予約が完了しました", "予約を完了", "承りました")


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


def mock_slots_by_duration(mapping: dict[int, list[str]]):
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        duration = int(kwargs.get("duration_minutes") or 0)
        times = mapping.get(duration, [])
        slots = [{"time": t, "available": True} for t in times]
        return {
            "date": kwargs.get("date"),
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": duration,
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


def complete(_messages):
    return "承知しました。"


def next_iso(month: int, day: int) -> str:
    today = datetime.now(JST).date()
    try:
        candidate = today.replace(month=month, day=day)
    except ValueError:
        candidate = today
    if candidate < today:
        candidate = candidate.replace(year=today.year + 1)
    return candidate.isoformat()


def main() -> int:
    print("mode: C9 チャット予約 / Knowledge読み取り専用 / 本番INSERTなし")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    creates: list[dict] = []

    def book_fn(*args, **kwargs):
        creates.append({"args": args, "kwargs": kwargs})
        return {"booking_id": "test-booking", "staff_name": "テスト"}

    print("\n===== A 予約条件の分離 =====")
    lookup_a = mock_slots("18:00")
    a0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_a, book_fn=book_fn)
    a1 = continue_chat(
        "腰が痛いので鍼を受けたい。90分",
        a0,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_a,
        book_fn=book_fn,
    )
    print("  A intent", a1.reservation_intent, a1.primary_intent, "treatment", a1.preferred_treatment, "dur", a1.requested_duration)
    if not a1.reservation_intent or a1.primary_intent != "reservation_intent":
        failures.append(f"A: 予約意図が維持されていない {a1.primary_intent}")
    if a1.preferred_treatment != "鍼":
        failures.append(f"A: treatment={a1.preferred_treatment}")
    if a1.requested_duration != 90:
        failures.append(f"A: duration={a1.requested_duration}")
    if a1.concern_summary != "腰痛":
        failures.append(f"A: concern={a1.concern_summary}")
    if "いつから" in (a1.reply or "") or "どんな痛" in (a1.reply or ""):
        failures.append("A: 施術相談へ移行している")
    if a1.booking_create_called or a1.booking_completed:
        failures.append("A: 予約確定している")

    print("\n===== B 施術時間未指定 =====")
    reset_store_for_tests()
    lookup_b = mock_slots("18:00")
    b0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_b, book_fn=book_fn)
    b1 = continue_chat("東京で水曜18時に予約したい", b0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_b, book_fn=book_fn)
    print("  B api", b1.reservation_api_called, "dur", b1.requested_duration, "reply", (b1.reply or "")[:80])
    if b1.reservation_api_called:
        failures.append("B: 施術時間未指定なのに空き検索した")
    if b1.requested_duration in (60, 90, 120):
        failures.append("B: 施術時間を勝手に入れている")
    if "60分" not in (b1.reply or "") or "90分" not in (b1.reply or "") or "120分" not in (b1.reply or ""):
        failures.append("B: 施術時間の確認がない")

    print("\n===== C 90分で空きあり =====")
    reset_store_for_tests()
    lookup_c = mock_slots_by_duration({90: ["18:00"], 60: ["18:00"]})
    target = next_iso(9, 10)
    c0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_c, book_fn=book_fn)
    c1 = continue_chat("東京で9/10 18:00、90分で予約したい", c0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_c, book_fn=book_fn)
    print("  C date", c1.requested_date, "slots", c1.available_slots, "dur calls", [c.get("duration_minutes") for c in lookup_c.calls])
    if target != c1.requested_date and c1.requested_date is None:
        failures.append(f"C: date={c1.requested_date}")
    if "18:00" not in (c1.available_slots or []) and "18:00" not in (c1.reply or ""):
        failures.append("C: 90分の候補が出ていない")
    if lookup_c.calls and lookup_c.calls[0].get("duration_minutes") != 90:
        failures.append("C: 最初に90分以外で検索している")

    print("\n===== D 90分なし・60分あり =====")
    reset_store_for_tests()
    lookup_d = mock_slots_by_duration({90: [], 60: ["18:00"]})
    d0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_d, book_fn=book_fn)
    d1 = continue_chat(
        "腰が痛いので鍼を受けたいです。東京で9/10 18時、90分で予約したい",
        d0,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_d,
        book_fn=book_fn,
    )
    print("  D phase", d1.booking_phase, "pref", d1.preferred_duration, "conf", d1.confirmed_duration)
    if d1.preferred_duration != 90:
        failures.append(f"D: preferred={d1.preferred_duration}")
    if d1.confirmed_duration == 60:
        failures.append("D: 了承前に confirmed が60になっている")
    if "60分" not in (d1.reply or "") or "90分" not in (d1.reply or ""):
        failures.append("D: 60分の代替提案がない")
    d2 = continue_chat("それでお願いします", d1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_d, book_fn=book_fn)
    print("  D2 pref", d2.preferred_duration, "conf", d2.confirmed_duration, "phase", d2.booking_phase)
    if d2.preferred_duration != 90:
        failures.append("D: 了承後に preferred 90 が消えた")
    if d2.requested_duration != 60:
        failures.append(f"D: working duration={d2.requested_duration}")
    if d2.confirmed_duration == 60:
        failures.append("D: 最終確認前に confirmed が60になっている")
    if d2.booking_phase != "confirming":
        failures.append(f"D: phase={d2.booking_phase}")
    if d2.booking_completed or d2.booking_create_called:
        failures.append("D: 代替了承だけで予約確定している")

    print("\n===== E 希望伝達事項 =====")
    note = d2.staff_note or build_staff_note(get_or_create_conversation(d2.conversation_id).booking_draft)
    print("  note:", note.replace("\n", " / "))
    if "腰痛" not in note or "鍼" not in note:
        failures.append("E: 腰痛・鍼希望がない")
    if "90分" not in note or "60分" not in note:
        failures.append("E: 90分→60分の経緯がない")
    if "股関節" in note or "原因" in note:
        failures.append("E: AIの推測が入っている")

    print("\n===== F 日時変更 =====")
    reset_store_for_tests()
    lookup_f = mock_slots("18:00")
    f0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_f, book_fn=book_fn)
    f1 = continue_chat("東京で9/10 18:00、60分", f0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_f, book_fn=book_fn)
    f2 = continue_chat("やっぱり9/11 18:00がいいです", f1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_f, book_fn=book_fn)
    print("  F pref", f2.preferred_date, "current", f2.requested_date)
    if f2.preferred_date == f2.requested_date:
        failures.append("F: 元の希望日と現在日が同じまま上書きされている")
    if f2.preferred_time != "18:00":
        failures.append(f"F: preferred_time={f2.preferred_time}")

    print("\n===== G 相談への明示的切り替え =====")
    g1 = continue_chat(
        "予約前に鍼と整体どちらがいいか詳しく相談したい",
        f2,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_f,
        book_fn=book_fn,
    )
    print("  G", g1.primary_intent, g1.reservation_intent)
    if g1.primary_intent != "treatment_consultation":
        failures.append(f"G: intent={g1.primary_intent}")
    if g1.reservation_intent:
        failures.append("G: 予約意図が残っている")

    print("\n===== H 平日の夕方 =====")
    reset_store_for_tests()
    lookup_h = mock_slots("10:00", "18:00", "19:30")
    h0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_h, book_fn=book_fn)
    h1 = continue_chat("東京で90分、平日の夕方", h0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_h, book_fn=book_fn)
    print("  H dates", h1.available_dates, "slots", h1.available_slots, "time", h1.requested_time)
    if h1.requested_time == "19:00":
        failures.append("H: 夕方を19:00にしている")
    if h1.available_slots:
        failures.append("H: 複数日なのに時刻を混ぜている")
    if not h1.available_dates:
        failures.append("H: 既存予約の候補日がない")
    if "20:00" in (h1.reply or "") and "20:00" not in {"18:00", "19:30"}:
        failures.append("H: 存在しない枠を出している")

    print("\n===== I 夜 =====")
    reset_store_for_tests()
    lookup_i = mock_slots("18:00")
    i0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_i, book_fn=book_fn)
    i1 = continue_chat("来週の夜で空いてますか？", i0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_i, book_fn=book_fn)
    print("  I time", i1.requested_time, "period", i1.time_period)
    if i1.requested_time == "19:00":
        failures.append("I: 夜を19:00に変換している")
    if i1.time_period != "night":
        failures.append(f"I: time_period={i1.time_period}")
    if "夕方" in (i1.reply or ""):
        failures.append("I: 夜を夕方に言い換えている")

    print("\n===== J お願いします → 最終確認（未確定） =====")
    reset_store_for_tests()
    creates.clear()
    lookup_j = mock_slots("18:00")
    j0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_j, book_fn=book_fn)
    j1 = continue_chat("東京で9/10 18:00、60分でお願いします", j0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_j, book_fn=book_fn)
    print("  J phase", j1.booking_phase, "create", j1.booking_create_called, "done", j1.booking_completed)
    if j1.booking_completed or j1.booking_create_called or creates:
        failures.append("J: お願いしますだけで予約確定している")
    if "予約内容をご確認ください" not in (j1.reply or ""):
        failures.append("J: 最終確認に進んでいない")
    if any(p in (j1.reply or "") for p in DONE_PHRASES if p != "承りました"):
        if "ご予約が完了しました" in (j1.reply or ""):
            failures.append("J: 確定前に完了と表示している")
    if "ご予約が完了しました" in (j1.reply or "") or "予約をお取りしました" in (j1.reply or ""):
        failures.append("J: 確定前の完了表示")

    print("\n===== K 明示確定 → 個人情報 → 既存予約処理 =====")
    j2 = continue_chat("この内容で予約する", j1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_j, book_fn=book_fn)
    print("  K2 phase", j2.booking_phase, "create", j2.booking_create_called)
    if j2.booking_create_called or creates:
        failures.append("K: 個人情報前に予約作成している")
    if "姓" not in (j2.reply or "") or "名" not in (j2.reply or ""):
        failures.append("K: 個人情報の取得がない")
    j3 = continue_chat(
        "山田 太郎、09012345678、taro@example.com、出張先は渋谷",
        j2,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_j,
        book_fn=book_fn,
    )
    print("  K3 phase", j3.booking_phase, "create", j3.booking_create_called, (j3.reply or "")[:80])
    if j3.booking_create_called or creates:
        failures.append("K: guest_info 入力時点で予約作成している")
    if j3.booking_phase != "confirming":
        failures.append(f"K: guest完了後 phase={j3.booking_phase}")
    if "お名前" not in (j3.reply or "") or "山田" not in (j3.reply or ""):
        failures.append("K: 最終確認にお名前がない")
    j4 = continue_chat("はい", j3, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_j, book_fn=book_fn)
    print("  K4 create", j4.booking_create_called, "done", j4.booking_completed, "n", len(creates))
    if not j4.booking_create_called or not creates:
        failures.append("K: 既存予約処理を呼んでいない")
    if not j4.booking_completed:
        failures.append("K: DB相当の成功後に完了になっていない")
    if "ご予約が完了しました" not in (j4.reply or ""):
        failures.append("K: 成功後の完了表示がない")
    if creates:
        args = creates[-1]["args"]
        note = args[11] if len(args) > 11 else None
        print("  K note", note)
        if "山田" not in str(args) and "太郎" not in str(args):
            failures.append("K: 氏名が予約処理に渡っていない")

    print("\n===== UX A-T 確認・はい・表示 =====")
    if format_booking_datetime("2026-09-17", "18:00", 90) != "9月17日18:00〜19:30":
        failures.append("J: 90分の表示が 18:00〜19:30 でない")
    if format_booking_datetime("2026-09-17", "18:00", 60) != "9月17日18:00〜19:00":
        failures.append("Kfmt: 60分の表示が 18:00〜19:00 でない")
    if format_booking_datetime("2026-09-17", "18:00", 120) != "9月17日18:00〜20:00":
        failures.append("Lfmt: 120分の表示が 18:00〜20:00 でない")

    reset_store_for_tests()
    creates.clear()
    lookup_yes = mock_slots("18:00")
    y0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes, book_fn=book_fn)
    y1 = continue_chat("東京で9/10 18:00、90分", y0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes, book_fn=book_fn)
    if y1.show_booking_cta:
        failures.append("F: 空き確認中に show_booking_cta")
    y2 = continue_chat("お願いします", y1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes, book_fn=book_fn)
    py2 = chat_public_payload(y2)
    print("  confirming", y2.booking_phase, "cta", py2.get("show_booking_cta"), "slots", py2.get("available_slots"))
    if y2.booking_phase != "confirming":
        failures.append(f"confirm: phase={y2.booking_phase}")
    if py2.get("show_booking_cta"):
        failures.append("E: confirming で show_booking_cta")
    if py2.get("available_slots"):
        failures.append(f"F: confirming で available_slots={py2.get('available_slots')}")
    if "施術：未指定" in (y2.reply or ""):
        failures.append("G: 施術：未指定 が残っている")
    if "ご要望：特になし" not in (y2.reply or ""):
        failures.append("H: ご要望：特になし がない")
    if "18:00〜19:30" not in (y2.reply or ""):
        failures.append("J: 確認文に 18:00〜19:30 がない")

    y_yes = continue_chat("はい", y2, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes, book_fn=book_fn)
    print("  はい", y_yes.booking_phase, (y_yes.reply or "")[:60], "create", y_yes.booking_create_called)
    if y_yes.booking_phase != "guest_info":
        failures.append(f"A: はい で guest_info にならない phase={y_yes.booking_phase}")
    if y_yes.show_booking_cta:
        failures.append("H: guest_info で show_booking_cta")
    if "姓" not in (y_yes.reply or "") or "名" not in (y_yes.reply or ""):
        failures.append("A: はい のあと姓名確認がない")
    if "予約内容をご確認ください" in (y_yes.reply or ""):
        failures.append("A: はいで確認文がループしている")
    if y_yes.booking_create_called or y_yes.booking_completed or creates:
        failures.append("P: はい の時点で予約作成している")
    if "予約が完了" in (y_yes.reply or "") or "ご予約が完了しました" in (y_yes.reply or ""):
        failures.append("R: 個人情報前に予約完了と表示している")

    reset_store_for_tests()
    creates.clear()
    lookup_yes2 = mock_slots("18:00")
    z0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes2, book_fn=book_fn)
    z1 = continue_chat("東京で9/10 18:00、90分", z0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes2, book_fn=book_fn)
    z2 = continue_chat("お願いします", z1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes2, book_fn=book_fn)
    z_b = continue_chat("お願いします", z2, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes2, book_fn=book_fn)
    if z_b.booking_phase != "guest_info":
        failures.append(f"B: お願いします で guest_info にならない {z_b.booking_phase}")
    reset_store_for_tests()
    creates.clear()
    lookup_yes3 = mock_slots("18:00")
    w0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes3, book_fn=book_fn)
    w1 = continue_chat("東京で9/10 18:00、90分", w0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes3, book_fn=book_fn)
    w2 = continue_chat("お願いします", w1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes3, book_fn=book_fn)
    w_c = continue_chat("この内容でお願いします", w2, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_yes3, book_fn=book_fn)
    if w_c.booking_phase != "guest_info":
        failures.append(f"C: この内容でお願いします で guest_info にならない {w_c.booking_phase}")

    reset_store_for_tests()
    creates.clear()
    lookup_chg = mock_slots_by_duration({90: ["18:00"], 60: ["18:00"]})
    ch0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_chg, book_fn=book_fn)
    ch1 = continue_chat("東京で9/10 18:00、90分", ch0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_chg, book_fn=book_fn)
    ch2 = continue_chat("お願いします", ch1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_chg, book_fn=book_fn)
    ch3 = continue_chat("60分に変更したい", ch2, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_chg, book_fn=book_fn)
    print("  change", ch3.booking_phase, ch3.requested_duration, (ch3.reply or "")[:80])
    if ch3.booking_phase == "guest_info":
        failures.append("Dchg: 60分変更で guest_info に進んでいる")
    if ch3.requested_duration != 60:
        failures.append(f"Dchg: duration={ch3.requested_duration}")
    if "お名前" in (ch3.reply or ""):
        failures.append("Dchg: 変更なのに名前確認へ進んでいる")

    reset_store_for_tests()
    lookup_tr = mock_slots("18:00")
    tr0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_tr, book_fn=book_fn)
    tr1 = continue_chat("腰が痛いので鍼を受けたい。東京で9/10 18:00、90分", tr0, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_tr, book_fn=book_fn)
    tr2 = continue_chat("お願いします", tr1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_tr, book_fn=book_fn)
    if "ご要望：鍼を希望" not in (tr2.reply or ""):
        failures.append("Ireq: ご要望：鍼を希望 がない")

    reset_store_for_tests()
    night_times = []
    h, m = 16, 0
    while h * 60 + m <= 24 * 60 + 30:
        night_times.append(f"{h:02d}:{m:02d}")
        m += 15
        if m >= 60:
            h += 1
            m = 0
    lookup_n = mock_slots(*night_times)

    def night_by_date(**kwargs):
        lookup_n.calls.append(dict(kwargs))
        date = str(kwargs.get("date") or "")
        day = int(date.split("-")[2]) if date else 0
        if day % 2 == 0:
            times = [t for t in night_times if t <= "21:00"]
        else:
            times = list(night_times)
        return {
            "date": kwargs.get("date"),
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": kwargs.get("duration_minutes"),
            "staff": [],
            "free_row": {"staff_name": "フリー", "slots": [{"time": t, "available": True} for t in times]},
        }

    night_by_date.calls = []  # type: ignore[attr-defined]
    n0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=night_by_date, book_fn=book_fn)
    n1 = continue_chat("東京で90分、平日", n0, match_fn=empty_match, complete_fn=complete, lookup_fn=night_by_date, book_fn=book_fn)
    n2 = continue_chat("夜空いてるのは？", n1, match_fn=empty_match, complete_fn=complete, lookup_fn=night_by_date, book_fn=book_fn)
    print("  night", n2.time_period, (n2.reply or "")[:180])
    if n2.time_period != "night":
        failures.append(f"M: time_period={n2.time_period}")
    if "夕方" in (n2.reply or ""):
        failures.append("M: 夜を夕方に変換している")
    if "16:00〜26:00" not in (n2.reply or "") and "18:00〜26:00" not in (n2.reply or ""):
        failures.append(f"N: 16:00〜26:00 相当の表示がない {(n2.reply or '')[:200]}")

    n3 = continue_chat("17日の18:00〜", n2, match_fn=empty_match, complete_fn=complete, lookup_fn=night_by_date, book_fn=book_fn)
    print("  pick", n3.selected_date, n3.selected_time, (n3.reply or "")[:120])
    if n3.time_from != "18:00":
        failures.append(f"P: 17日の18:00〜 で time_from が消えた {n3.time_from}")
    if "18:00" not in (n3.reply or ""):
        failures.append("O18: 18:00以降の空き表示がない")
    other_days = [d for d in (n2.available_dates or []) if d != n3.requested_date]
    if any(f"{int(d.split('-')[1])}月{int(d.split('-')[2])}日" in (n3.reply or "") for d in other_days[:5]):
        failures.append("O: 候補選択後に以前の候補日が再表示されている")

    n3b = continue_chat("18:00", n3, match_fn=empty_match, complete_fn=complete, lookup_fn=night_by_date, book_fn=book_fn)
    print("  pick time", n3b.selected_time, (n3b.reply or "")[:120])
    pn3 = chat_public_payload(n3b)
    if "18:00〜19:30" not in (n3b.reply or ""):
        failures.append("O18: 18:00〜19:30 がない")
    if "頃で空き" in (n3b.reply or ""):
        failures.append("O18: 曖昧な頃表現がある")
    if pn3.get("available_slots"):
        failures.append("O: 選択後に構造化枠が重複している")

    n4 = continue_chat("お願いします", n3b, match_fn=empty_match, complete_fn=complete, lookup_fn=night_by_date, book_fn=book_fn)
    n5 = continue_chat("はい", n4, match_fn=empty_match, complete_fn=complete, lookup_fn=night_by_date, book_fn=book_fn)
    n6 = continue_chat(
        "山田 太郎、09012345678、taro@example.com、出張先は渋谷",
        n5,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=night_by_date,
        book_fn=book_fn,
    )
    print("  guest done", n6.booking_phase, n6.booking_create_called)
    if n5.booking_create_called:
        failures.append("Q: guest_info 完了前に予約作成している")
    if n6.booking_create_called or creates:
        failures.append("L: guest_info 入力時点で予約作成している")
    if n6.booking_phase != "confirming":
        failures.append(f"J: guest完了後 phase={n6.booking_phase}")
    n7 = continue_chat("はい", n6, match_fn=empty_match, complete_fn=complete, lookup_fn=night_by_date, book_fn=book_fn)
    print("  booked", n7.booking_create_called, n7.booking_completed, "n", len(creates))
    if not n7.booking_create_called or not creates:
        failures.append("Q: guest_info 完了後に atomic_create 相当を呼んでいない")
    if not n7.booking_completed or "ご予約が完了しました" not in (n7.reply or ""):
        failures.append("Q: 成功後の完了表示がない")

    src = open(os.path.join(ROOT, "karin_chat_booking.py"), encoding="utf-8").read()
    src_chat = open(os.path.join(ROOT, "karin_chat.py"), encoding="utf-8").read()
    if "/api/book" in src or "/api/book" in src_chat:
        failures.append("S: /api/book の HTTP POST がある")

    print("\n===== L Knowledge DB =====")
    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if (after_n, after_h) != (before_n, before_h):
        failures.append("L: Knowledge DB が変化した")
    if after_h != EXPECTED_HASH:
        failures.append(f"L: hash 不一致 {after_h}")

    src = open(os.path.join(ROOT, "karin_chat_booking.py"), encoding="utf-8").read()
    if "list_web_booking_slots" not in src or "atomic_create_web_reservation" not in src:
        failures.append("既存予約関数を再利用していない")
    if "/api/book" in src:
        failures.append("チャット予約が /api/book を別実装している")

    if failures:
        print("\nC9 FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nC9 テスト: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
