"""予約候補の絞り込み。候補選択後に一覧へ戻らないこと。

  python scripts/test_karin_chat_booking_narrow.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import run_chat  # noqa: E402
from karin_chat_booking import (  # noqa: E402
    _consecutive_bands,
    _format_bands,
    _parse_clock_time,
    _parse_day_only,
    _parse_time_from,
)
from karin_chat_memory import reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
JST = timezone(timedelta(hours=9))
DONE = ("予約をお取りしました", "ご予約が完了しました", "予約を完了")


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def day_iso(day: int) -> str:
    today = datetime.now(JST).date()
    for i in range(0, 45):
        d = today + timedelta(days=i)
        if d.day == day:
            return d.isoformat()
    raise RuntimeError(f"{day}日が予約期間にない")


def jp_date(iso: str) -> str:
    _y, month, day = iso.split("-")
    return f"{int(month)}月{int(day)}日"


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def empty_match(*_a, **_k):
    return []


def complete(_messages):
    return "承知しました。"


def mock_plan(plan):
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        date = kwargs.get("date")
        duration = int(kwargs.get("duration_minutes") or 0)
        times = plan(date, duration)
        return {
            "date": date,
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": duration,
            "staff": [],
            "free_row": {
                "staff_name": "フリー",
                "slots": [{"time": t, "available": True} for t in times],
            },
        }

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


def evening_plan(date, duration):
    """9日・11日は18:00あり。10日は夕方のみ。8日は空きなし。"""
    if duration != 90:
        return []
    day = int(str(date).split("-")[2])
    if day == 8:
        return []
    if day == 10:
        return ["17:00", "17:15", "17:30"]
    if day in (9, 11):
        return ["17:00", "17:15", "17:30", "17:45", "18:00", "18:15", "18:30"]
    if datetime.fromisoformat(str(date)).weekday() >= 5:
        return []
    return []


def start_weekday(lookup, book_fn=None):
    kwargs = dict(match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    if book_fn is not None:
        kwargs["book_fn"] = book_fn
    t0 = continue_chat("予約したいです", None, **kwargs)
    t1 = continue_chat("東京で90分", t0, **kwargs)
    t2 = continue_chat("平日", t1, **kwargs)
    return t2, kwargs


def dates_in_reply(reply: str, isos: list[str]) -> list[str]:
    return [iso for iso in isos if jp_date(iso) in (reply or "")]


def main() -> int:
    print("mode: 予約候補の絞り込み / Knowledge読み取り専用")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    d9, d10, d11 = day_iso(9), day_iso(10), day_iso(11)
    print("  targets", d9, d10, d11)

    def book_fn(*args, **kwargs):
        return {"booking_id": "test-booking", "staff_name": "テスト"}

    print("\n===== parse 「11日」「18:00〜」 =====")
    today = datetime.now(JST).date()
    parsed_11 = _parse_day_only("11日18:00", today, [d9, d11])
    if parsed_11 != d11:
        failures.append(f"parse 11日18:00 → {parsed_11}")
    if _parse_day_only("11日", today, [d9, d11]) != d11:
        failures.append("parse 11日 が候補日に解決されない")
    if _parse_time_from("18:00〜") != "18:00":
        failures.append(f"18:00〜 → {_parse_time_from('18:00〜')}")
    if _parse_time_from("18時以降") != "18:00":
        failures.append(f"18時以降 → {_parse_time_from('18時以降')}")
    if _parse_time_from("18:00で") is not None:
        failures.append("18:00で を以降扱いにしている")
    if _parse_time_from("18時頃") is not None:
        failures.append("18時頃 を以降扱いにしている")
    if _parse_clock_time("18:00で") != "18:00":
        failures.append("18:00で が正確な18:00になっていない")
    if _parse_clock_time("18時頃") != "18:00":
        failures.append("18時頃 が18:00になっていない")
    if _consecutive_bands(
        ["17:00", "17:15", "17:30", "17:45", "18:00", "18:15", "18:30"]
    ) != [("17:00", "18:30")]:
        failures.append(
            f"連続帯 {_consecutive_bands(['17:00', '17:15', '17:30', '17:45', '18:00', '18:15', '18:30'])}"
        )
    jumped = _format_bands(["17:00", "18:00", "20:00"])
    if jumped == "17:00〜20:00" or "17:00〜20:00" in jumped:
        failures.append(f"飛び枠を一括範囲にしている {jumped}")

    print("\n===== Test 1 平日→夕方→18:00→11日18:00 =====")
    reset_store_for_tests()
    lookup1 = mock_plan(evening_plan)
    t, kw = start_weekday(lookup1)
    t_eve = continue_chat("夕方ぐらいで", t, **kw)
    t_1800 = continue_chat("18:00", t_eve, **kw)
    n_before = len(lookup1.calls)
    t_pick = continue_chat("11日18:00", t_1800, **kw)
    print("  eve dates", t_eve.available_dates)
    print("  18:00 dates", t_1800.available_dates, "reply", (t_1800.reply or "")[:80])
    print("  pick date", t_pick.requested_date, t_pick.selected_date, t_pick.requested_time)
    print("  pick reply", (t_pick.reply or "")[:120])
    if t_pick.requested_date != d11 or t_pick.selected_date != d11:
        failures.append(f"T1: date={t_pick.requested_date}/{t_pick.selected_date}")
    if t_pick.requested_time != "18:00" and t_pick.selected_time != "18:00":
        failures.append(f"T1: time={t_pick.requested_time}/{t_pick.selected_time}")
    if jp_date(d9) in (t_pick.reply or ""):
        failures.append("T1: 11日18:00指定後も9日が残っている")
    if jp_date(d11) not in (t_pick.reply or "") or "18:00" not in (t_pick.reply or ""):
        failures.append("T1: 11日18:00の確認がない")
    if "進めますか" not in (t_pick.reply or ""):
        failures.append("T1: 次の確認へ進んでいない")
    later = lookup1.calls[n_before:]
    if not later:
        failures.append("T1: 11日18:00の再検索がない")
    elif any(c.get("date") != d11 for c in later):
        failures.append(f"T1: 最終検索に他日が残る {[c.get('date') for c in later]}")

    print("\n===== Test 2 18:00〜 → 11日 =====")
    reset_store_for_tests()
    lookup2 = mock_plan(evening_plan)
    t, kw = start_weekday(lookup2)
    t_eve = continue_chat("夕方ぐらいで", t, **kw)
    t_from = continue_chat("18:00〜", t_eve, **kw)
    n_before = len(lookup2.calls)
    t_day = continue_chat("11日", t_from, **kw)
    print("  from", t_from.time_from, t_from.available_dates)
    print("  11日", t_day.requested_date, t_day.time_from, t_day.requested_time)
    print("  11日 reply", (t_day.reply or "")[:140])
    if t_from.time_from != "18:00":
        failures.append(f"T2: 18:00〜 が time_from でない {t_from.time_from}")
    if t_from.requested_time == "18:00" and t_from.time_from is None:
        failures.append("T2: 18:00〜 を固定18:00にしている")
    if t_day.requested_date != d11 and t_day.selected_date != d11:
        failures.append(f"T2: 11日が日付になっていない {t_day.requested_date}")
    if t_day.time_from != "18:00" and t_day.requested_time not in (None, "18:00"):
        failures.append("T2: 直前の時間条件が消えている")
    if jp_date(d9) in (t_day.reply or "") or jp_date(d10) in (t_day.reply or ""):
        failures.append("T2: 11日指定後に他日が混ざっている")
    later = lookup2.calls[n_before:]
    if not later:
        failures.append("T2: 11日の再検索がない")
    elif any(c.get("date") != d11 for c in later):
        failures.append(f"T2: 11日以外を検索している {[c.get('date') for c in later]}")
    if any(c.get("duration_minutes") != 90 for c in later):
        failures.append("T2: 11日検索が90分でない")

    print("\n===== Test 3 候補選択後に9/9を再表示しない =====")
    reset_store_for_tests()
    lookup3 = mock_plan(evening_plan)
    t, kw = start_weekday(lookup3)
    t_eve = continue_chat("夕方ぐらいで", t, **kw)
    t_1800 = continue_chat("18:00", t_eve, **kw)
    t_pick = continue_chat("11日18:00", t_1800, **kw)
    if jp_date(d9) in (t_pick.reply or "") and jp_date(d11) in (t_pick.reply or ""):
        failures.append("T3: 11日18:00のあと9日と11日を再表示している")
    if t_pick.available_dates and d9 in t_pick.available_dates:
        failures.append(f"T3: available_dates に9日 {t_pick.available_dates}")

    print("\n===== Test 4 「11日」で直前の時間を保持 =====")
    reset_store_for_tests()
    lookup4 = mock_plan(evening_plan)
    t, kw = start_weekday(lookup4)
    t_eve = continue_chat("夕方ぐらいで", t, **kw)
    t_1800 = continue_chat("18:00", t_eve, **kw)
    t_day = continue_chat("11日", t_1800, **kw)
    print("  keep time", t_day.requested_time, t_day.time_from, t_day.requested_date)
    if t_day.requested_date != d11:
        failures.append(f"T4: date={t_day.requested_date}")
    if t_day.requested_time != "18:00" and t_day.time_from != "18:00":
        failures.append("T4: 18:00の条件が消えている")
    if jp_date(d9) in (t_day.reply or ""):
        failures.append("T4: 11日のあとに9日が出ている")

    print("\n===== Test 5 夕方は実在枠の幅 =====")
    reset_store_for_tests()
    lookup5 = mock_plan(evening_plan)
    t, kw = start_weekday(lookup5)
    t_eve = continue_chat("夕方ぐらいで", t, **kw)
    print("  eve reply", (t_eve.reply or "")[:200])
    if "17:00〜18:30" not in (t_eve.reply or "") and "18:00" not in (t_eve.reply or ""):
        failures.append("T5: 夕方の実在時間帯が出ていない")
    if t_eve.requested_time == "19:00":
        failures.append("T5: 夕方を19:00にしている")
    if "17:00〜20:00" in (t_eve.reply or ""):
        failures.append("T5: 存在しない20:00までを一括表示している")

    print("\n===== Test 6 昼間は実在枠の幅 =====")
    reset_store_for_tests()

    def day_plan(date, duration):
        if duration != 90:
            return []
        day = int(str(date).split("-")[2])
        if day == 10:
            return ["10:00", "10:15", "10:30", "14:00"]
        if day in (9, 11):
            return ["10:00", "10:15", "10:30", "10:45", "11:00"]
        return ["10:00"]

    lookup6 = mock_plan(day_plan)
    t, kw = start_weekday(lookup6)
    t_daytime = continue_chat("昼間がいいです", t, **kw)
    print("  daytime", (t_daytime.reply or "")[:200])
    if t_daytime.time_period != "daytime":
        failures.append(f"T6: period={t_daytime.time_period}")
    if "10:00" not in (t_daytime.reply or ""):
        failures.append("T6: 昼間の実在枠が出ていない")
    if "10:00〜14:00" in (t_daytime.reply or ""):
        failures.append("T6: 飛びのある昼間枠を一括範囲にしている")
    if "19:00" in (t_daytime.reply or "") or "20:00" in (t_daytime.reply or ""):
        failures.append("T6: 昼間に夜の時刻を作っている")

    print("\n===== Test 7 夕方あり・18:00以降なし =====")
    reset_store_for_tests()

    def no_1800(date, duration):
        if duration != 90:
            return []
        return ["17:00", "17:15", "17:30"]

    lookup7 = mock_plan(no_1800)
    t, kw = start_weekday(lookup7)
    t_eve = continue_chat("夕方ぐらいで", t, **kw)
    t_from = continue_chat("18:00〜", t_eve, **kw)
    print("  none", (t_from.reply or "")[:160])
    if "18:00" not in (t_from.reply or "") or "空き" not in (t_from.reply or ""):
        failures.append("T7: 18:00以降に空きがない説明がない")
    if "先ほど" not in (t_from.reply or "") and "夕方" not in (t_from.reply or ""):
        failures.append("T7: 夕方候補から減ったことが分からない")
    if t_from.booking_completed:
        failures.append("T7: 空きなしなのに予約完了")

    print("\n===== Test 8 90分枠だけ =====")
    reset_store_for_tests()

    def dur_plan(date, duration):
        if duration == 90:
            return ["18:00", "18:15"]
        return ["10:00", "11:00"]

    lookup8 = mock_plan(dur_plan)
    t, kw = start_weekday(lookup8)
    t_eve = continue_chat("夕方ぐらいで", t, **kw)
    if any(c.get("duration_minutes") not in (90, 60) for c in lookup8.calls):
        failures.append("T8: 想定外の施術時間で検索している")
    if any(c.get("duration_minutes") != 90 for c in lookup8.calls):
        failures.append("T8: 90分以外で候補検索している")
    if "10:00" in (t_eve.reply or ""):
        failures.append("T8: 60分の枠を90分候補に混ぜている")
    if "18:00" not in (t_eve.reply or ""):
        failures.append("T8: 90分の夕方枠が出ていない")

    print("\n===== Test 9 90分なし・60分代替（了承前は未確定） =====")
    reset_store_for_tests()

    def alt_plan(date, duration):
        if duration == 90:
            return []
        if duration == 60:
            return ["18:00"]
        return []

    lookup9 = mock_plan(alt_plan)
    creates: list = []

    def book_fn(*args, **kwargs):
        creates.append({"args": args, "kwargs": kwargs})
        return {"booking_id": "test-booking", "staff_name": "テスト"}

    t0 = continue_chat(
        "予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup9, book_fn=book_fn
    )
    t9 = continue_chat(
        f"腰が痛いので鍼を受けたいです。東京で{jp_date(d11)} 18:00、90分で予約したい",
        t0,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup9,
        book_fn=book_fn,
    )
    print("  alt phase", t9.booking_phase, "pref", t9.preferred_duration, "conf", t9.confirmed_duration)
    if t9.preferred_duration != 90:
        failures.append(f"T9: preferred={t9.preferred_duration}")
    if t9.confirmed_duration == 60:
        failures.append("T9: 了承前に60分確定している")
    if "60分" not in (t9.reply or ""):
        failures.append("T9: 60分の代替がない")
    if t9.booking_completed or t9.booking_create_called or creates:
        failures.append("T9: 代替提示だけで予約確定している")
    if t9.booking_phase != "proposing_alt":
        failures.append(f"T9: phase={t9.booking_phase}")

    print("\n===== Test 10 日時決定後は最終確認へ =====")
    reset_store_for_tests()
    lookup10 = mock_plan(evening_plan)
    t, kw = start_weekday(lookup10, book_fn=book_fn)
    t_eve = continue_chat("夕方ぐらいで", t, **kw)
    t_1800 = continue_chat("18:00", t_eve, **kw)
    t_pick = continue_chat("11日18:00", t_1800, **kw)
    t_yes = continue_chat("お願いします", t_pick, **kw)
    print("  yes phase", t_yes.booking_phase, (t_yes.reply or "")[:80])
    if t_yes.booking_phase != "confirming":
        failures.append(f"T10: phase={t_yes.booking_phase}")
    if "予約内容をご確認ください" not in (t_yes.reply or ""):
        failures.append("T10: 最終確認に進んでいない")
    if jp_date(d9) in (t_yes.reply or "") and "候補" in (t_yes.reply or ""):
        failures.append("T10: 最終確認なのに候補一覧へ戻っている")
    if any(p in (t_yes.reply or "") for p in DONE):
        failures.append("T10: お願いしますだけで予約完了している")
    if t_yes.booking_completed or t_yes.booking_create_called:
        failures.append("T10: お願いしますで DB 予約している")

    src = open(os.path.join(ROOT, "karin_chat_booking.py"), encoding="utf-8").read()
    if "list_web_booking_slots" not in src or "atomic_create_web_reservation" not in src:
        failures.append("既存予約関数を再利用していない")
    if "/api/book" in src:
        failures.append("チャット予約が /api/book を別実装している")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if (after_n, after_h) != (before_n, before_h):
        failures.append("Knowledge DB がテスト中に変化した")
    if after_h != EXPECTED_HASH:
        failures.append(f"終了時 hash 不一致 {after_h}")

    if failures:
        print("\n予約候補絞り込み FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\n予約候補絞り込み: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
