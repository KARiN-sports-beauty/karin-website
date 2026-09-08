"""guest_info の一括取得・不足項目のみ確認。Knowledgeは読み取り専用。

  python scripts/test_karin_chat_guest_info.py
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
    BookingDraft,
    build_guest_info_ask,
    chat_in_house_booking_enabled,
    guest_display_name,
    guest_fields_for_place,
    guest_info_complete,
    missing_guest_fields,
    parse_guest_info,
    required_guest_fields,
)
from karin_chat_memory import get_or_create_conversation, reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
JST = timezone(timedelta(hours=9))
NAME_REASK = "お名前を教えてください"
OLD_NAME_ASK = "ご予約者様のお名前を教えてください"


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


def draft_of(turn) -> BookingDraft:
    return get_or_create_conversation(turn.conversation_id).booking_draft


def reach_confirming(book_fn, lookup_fn, **kwargs):
    t0 = continue_chat(
        "予約したいです",
        None,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_fn,
        book_fn=book_fn,
        **kwargs,
    )
    t1 = continue_chat(
        "東京で9/10 18:00、90分",
        t0,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_fn,
        book_fn=book_fn,
        **kwargs,
    )
    t2 = continue_chat(
        "お願いします",
        t1,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_fn,
        book_fn=book_fn,
        **kwargs,
    )
    return t2


def reach_guest(book_fn, lookup_fn, place_type: str = "visit"):
    confirming = reach_confirming(book_fn, lookup_fn)
    draft = draft_of(confirming)
    draft.place_type = place_type
    draft.confirmed_place_type = place_type
    return continue_chat(
        "はい",
        confirming,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_fn,
        book_fn=book_fn,
    )


def main() -> int:
    print("mode: guest_info 一括取得 / Knowledge読み取り専用 / 本番INSERTなし")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    print("\n===== unit required / missing =====")
    visit = BookingDraft(area="tokyo", place_type="visit")
    fukuoka_visit = BookingDraft(area="fukuoka", place_type="visit")
    house = BookingDraft(area="tokyo", place_type="in_house")
    fukuoka_house = BookingDraft(area="fukuoka", place_type="in_house")
    visit_fields = ["name", "phone", "email", "dispatch_destination"]
    future_house_fields = ["name", "phone", "email"]
    if guest_fields_for_place("visit") != visit_fields:
        failures.append(f"guest_fields visit={guest_fields_for_place('visit')}")
    if guest_fields_for_place("in_house") != future_house_fields:
        failures.append(f"guest_fields in_house={guest_fields_for_place('in_house')}")
    if required_guest_fields(visit) != visit_fields:
        failures.append(f"required visit={required_guest_fields(visit)}")
    if required_guest_fields(fukuoka_visit) != visit_fields:
        failures.append(f"required fukuoka visit={required_guest_fields(fukuoka_visit)}")
    if chat_in_house_booking_enabled():
        failures.append("G: 院内チャット予約が有効化されている")
    if required_guest_fields(house) != visit_fields:
        failures.append(f"G: 院内未提供なのに required={required_guest_fields(house)}")
    if required_guest_fields(fukuoka_house) != visit_fields:
        failures.append(f"G: 福岡院内未提供なのに required={required_guest_fields(fukuoka_house)}")
    if missing_guest_fields(visit) != visit_fields:
        failures.append(f"missing empty visit={missing_guest_fields(visit)}")

    print("\n===== A 姓：藤田、名：幸士 =====")
    d_a = BookingDraft(place_type="visit")
    parse_guest_info(d_a, "姓：藤田、名：幸士")
    print("  A", d_a.guest_last_name, d_a.guest_first_name, missing_guest_fields(d_a))
    if d_a.guest_last_name != "藤田" or d_a.guest_first_name != "幸士":
        failures.append(f"A: name={d_a.guest_last_name}/{d_a.guest_first_name}")
    if "name" in missing_guest_fields(d_a):
        failures.append("A: name が missing のまま")

    print("\n===== B 空白区切り =====")
    d_b = BookingDraft(place_type="visit")
    parse_guest_info(d_b, "藤田 幸士")
    if d_b.guest_last_name != "藤田" or d_b.guest_first_name != "幸士":
        failures.append(f"B: name={d_b.guest_last_name}/{d_b.guest_first_name}")

    print("\n===== C 全角スペース =====")
    d_c = BookingDraft(place_type="visit")
    parse_guest_info(d_c, "藤田　幸士")
    if d_c.guest_last_name != "藤田" or d_c.guest_first_name != "幸士":
        failures.append(f"C: name={d_c.guest_last_name}/{d_c.guest_first_name}")

    print("\n===== D 藤田幸士は自動分割しない =====")
    d_d = BookingDraft(place_type="visit")
    parse_guest_info(d_d, "藤田幸士")
    print("  D", d_d.guest_last_name, d_d.guest_first_name, missing_guest_fields(d_d))
    if d_d.guest_last_name or d_d.guest_first_name:
        failures.append("D: 空白なし氏名を自動分割している")
    if "name" not in missing_guest_fields(d_d):
        failures.append("D: name が missing になっていない")
    ask_d = build_guest_info_ask(d_d)
    if "姓" not in ask_d or "名" not in ask_d:
        failures.append(f"D: 姓・名の確認がない {ask_d}")
    booking_src = open(os.path.join(ROOT, "karin_chat_booking.py"), encoding="utf-8").read()
    if "return raw[:2], raw[2:]" in booking_src or "raw[:2], raw[2:]" in booking_src:
        failures.append("D: 文字数による姓・名の推測分割が残っている")

    print("\n===== E 曖昧氏名＋phone/email =====")
    d_e = BookingDraft(place_type="visit")
    parse_guest_info(d_e, "藤田幸士、090-1234-5678、test@example.com")
    if d_e.guest_last_name or d_e.guest_first_name:
        failures.append("E: 曖昧氏名を自動分割している")
    if d_e.guest_phone != "09012345678" or d_e.guest_email != "test@example.com":
        failures.append(f"E: phone/email 未保存 {d_e.guest_phone} {d_e.guest_email}")
    if missing_guest_fields(d_e) != ["name", "dispatch_destination"]:
        failures.append(f"E: missing={missing_guest_fields(d_e)}")
    ask_e = build_guest_info_ask(d_e)
    if "姓" not in ask_e or "名" not in ask_e:
        failures.append(f"E: 姓名確認がない {ask_e}")
    if "電話番号を教えて" in ask_e or "メールアドレスを教えて" in ask_e:
        failures.append(f"E: 保存済みの電話/メールを再質問 {ask_e}")

    print("\n===== F 姓だけ =====")
    d_f = BookingDraft(place_type="visit")
    parse_guest_info(d_f, "姓：藤田")
    if d_f.guest_last_name != "藤田" or d_f.guest_first_name:
        failures.append(f"F: {d_f.guest_last_name}/{d_f.guest_first_name}")
    if "name" not in missing_guest_fields(d_f):
        failures.append("F: 姓だけでは name 完了になっている")
    ask_f = build_guest_info_ask(d_f)
    if "名" not in ask_f:
        failures.append(f"F: 名の確認がない {ask_f}")

    print("\n===== G 名だけ =====")
    d_g_name = BookingDraft(place_type="visit")
    parse_guest_info(d_g_name, "名：幸士")
    if d_g_name.guest_first_name != "幸士" or d_g_name.guest_last_name:
        failures.append(f"G: {d_g_name.guest_last_name}/{d_g_name.guest_first_name}")
    if "name" not in missing_guest_fields(d_g_name):
        failures.append("G: 名だけでは name 完了になっている")
    ask_gn = build_guest_info_ask(d_g_name)
    if "姓" not in ask_gn:
        failures.append(f"G: 姓の確認がない {ask_gn}")

    print("\n===== H 姓名＋電話＋メール（出張先は別途） =====")
    d_h = BookingDraft(place_type="visit")
    parse_guest_info(d_h, "姓：藤田、名：幸士、090-1234-5678、test@example.com")
    if d_h.guest_last_name != "藤田" or d_h.guest_first_name != "幸士":
        failures.append("H: 姓名未保存")
    if d_h.guest_phone != "09012345678" or d_h.guest_email != "test@example.com":
        failures.append("H: phone/email 未保存")
    if missing_guest_fields(d_h) != ["dispatch_destination"]:
        failures.append(f"H: missing={missing_guest_fields(d_h)}")
    ask_h = build_guest_info_ask(d_h)
    if "姓" in ask_h or "名：" in ask_h:
        failures.append(f"H: 姓名を再質問 {ask_h}")
    if "出張先" not in ask_h:
        failures.append(f"H: 出張先を聞いていない {ask_h}")

    print("\n===== I 複数ターン保持 =====")
    d_i = BookingDraft(place_type="visit")
    parse_guest_info(d_i, "姓：藤田、名：幸士、電話：090-1234-5678")
    parse_guest_info(d_i, "test@example.com")
    if d_i.guest_last_name != "藤田" or d_i.guest_phone != "09012345678":
        failures.append("I: 既存項目が消えた")
    if d_i.guest_email != "test@example.com":
        failures.append("I: email 未保存")
    if missing_guest_fields(d_i) != ["dispatch_destination"]:
        failures.append(f"I: missing={missing_guest_fields(d_i)}")
    parse_guest_info(d_i, "東京都渋谷区神南")
    if not guest_info_complete(d_i):
        failures.append("I: 完了しない")

    print("\n===== newline 例2 =====")
    d_nl = BookingDraft(place_type="visit")
    parse_guest_info(d_nl, "藤田\n幸士\n090-1234-5678\ntest@example.com")
    if d_nl.guest_last_name != "藤田" or d_nl.guest_first_name != "幸士":
        failures.append(f"newline: {d_nl.guest_last_name}/{d_nl.guest_first_name}")
    if d_nl.guest_phone != "09012345678" or d_nl.guest_email != "test@example.com":
        failures.append("newline: phone/email 未保存")

    print("\n===== 院内は予約選択肢にしない =====")
    d_place = BookingDraft(place_type="in_house")
    ask_place = build_guest_info_ask(d_place)
    if "出張先" not in ask_place:
        failures.append(f"place: 現在出張なのに出張先を聞いていない {ask_place}")
    if "院内" in ask_place:
        failures.append(f"place: guest_info で院内を案内している {ask_place}")
    if "dispatch_destination" not in required_guest_fields(d_place):
        failures.append("place: 院内未提供なのに出張先が required から外れている")
    if "姓：" not in ask_place or "名：" not in ask_place:
        failures.append(f"place: 姓・名の案内がない {ask_place}")

    creates: list[dict] = []

    def book_fn(*args, **kwargs):
        creates.append({"args": args, "kwargs": kwargs})
        return {"booking_id": "test-booking", "staff_name": "テスト"}

    print("\n===== J 会話: 一度入力した姓名を再質問しない =====")
    reset_store_for_tests()
    creates.clear()
    lookup_i = mock_slots("18:00")
    g_i = reach_guest(book_fn, lookup_i, place_type="visit")
    print("  guest ask", (g_i.reply or "")[:80], "phase", g_i.booking_phase)
    if g_i.booking_phase != "guest_info":
        failures.append(f"J: phase={g_i.booking_phase}")
    if "姓：" not in (g_i.reply or "") or "名：" not in (g_i.reply or "") or "出張先：" not in (g_i.reply or ""):
        failures.append(f"J: 一括案内がない {g_i.reply}")
    if "院内" in (g_i.reply or "") or "出張か院内" in (g_i.reply or ""):
        failures.append("place-chat: 院内を予約選択肢として案内している")
    d_amb = continue_chat(
        "藤田幸士",
        g_i,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_i,
        book_fn=book_fn,
    )
    amb_draft = draft_of(d_amb)
    if amb_draft.guest_last_name or amb_draft.guest_first_name:
        failures.append("D-chat: 藤田幸士を自動分割している")
    if "姓と名" not in (d_amb.reply or "") and "姓：" not in (d_amb.reply or ""):
        failures.append(f"D-chat: 姓名確認がない {d_amb.reply}")
    if d_amb.booking_create_called or creates:
        failures.append("M: guest_info 中に予約作成している")
    i1 = continue_chat(
        "姓：藤田、名：幸士",
        d_amb,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_i,
        book_fn=book_fn,
    )
    d_i = draft_of(i1)
    print("  after name", guest_display_name(d_i), "missing", missing_guest_fields(d_i), (i1.reply or "")[:80])
    if d_i.guest_last_name != "藤田" or d_i.guest_first_name != "幸士":
        failures.append("J: 会話で name が保存されていない")
    if NAME_REASK in (i1.reply or "") or OLD_NAME_ASK in (i1.reply or ""):
        failures.append(f"J: 名前再質問 {i1.reply}")
    if "姓と名を分けて" in (i1.reply or ""):
        failures.append("J: 保存済み姓名を再確認している")
    if i1.booking_create_called or creates:
        failures.append("M: guest_info 中に予約作成している")
    if i1.booking_phase != "guest_info":
        failures.append(f"J: nameだけなのに phase={i1.booking_phase}")
    if d_i.place_type != "visit":
        failures.append(f"place: 現在の予約 place_type={d_i.place_type}")

    print("\n===== E 会話: 曖昧氏名でも phone/email は保持 =====")
    reset_store_for_tests()
    creates.clear()
    lookup_e = mock_slots("18:00")
    g_e = reach_guest(book_fn, lookup_e, place_type="visit")
    e1 = continue_chat(
        "藤田幸士、090-1234-5678、test@example.com",
        g_e,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_e,
        book_fn=book_fn,
    )
    de = draft_of(e1)
    if de.guest_last_name or de.guest_first_name:
        failures.append("E-chat: 曖昧氏名を自動分割している")
    if de.guest_phone != "09012345678" or de.guest_email != "test@example.com":
        failures.append("E-chat: phone/email が保存されていない")
    if "電話番号を教えて" in (e1.reply or "") or "メールアドレスを教えて" in (e1.reply or ""):
        failures.append(f"E-chat: 保存済み連絡先を再質問 {e1.reply}")
    if "姓" not in (e1.reply or ""):
        failures.append(f"E-chat: 姓名確認がない {e1.reply}")
    if e1.booking_create_called or creates:
        failures.append("M: 曖昧氏名ターンで予約作成している")

    print("\n===== K 会話: 明確な姓名＋連絡先＋出張先 → 最終確認 =====")
    reset_store_for_tests()
    creates.clear()
    lookup_j = mock_slots("18:00")
    g_j = reach_guest(book_fn, lookup_j, place_type="visit")
    j1 = continue_chat(
        "姓：藤田、名：幸士、090-1234-5678、test@example.com、東京都渋谷区神南",
        g_j,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_j,
        book_fn=book_fn,
    )
    print("  K phase", j1.booking_phase, "create", j1.booking_create_called, (j1.reply or "")[:100])
    if j1.booking_create_called or creates:
        failures.append("H-chat: 一括入力時点で予約作成している")
    if j1.booking_phase != "confirming":
        failures.append(f"K: guest完了後 phase={j1.booking_phase}")
    if NAME_REASK in (j1.reply or "") or "姓と名を分けて" in (j1.reply or ""):
        failures.append("H-chat: 一括入力後に名前を聞いている")
    if "この内容で予約を確定しますか？" not in (j1.reply or ""):
        failures.append("K: 最終確認がない")
    if "藤田" not in (j1.reply or "") or "09012345678" not in (j1.reply or "") or "test@example.com" not in (j1.reply or ""):
        failures.append("K: 最終確認に個人情報がない")
    if "出張先" not in (j1.reply or "") or "渋谷" not in (j1.reply or ""):
        failures.append("K: 最終確認に出張先がない")
    if "院内" in (j1.reply or ""):
        failures.append("place-chat: 最終確認で院内を案内している")

    print("\n===== L 最終確認のはい → create =====")
    j2 = continue_chat("はい", j1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_j, book_fn=book_fn)
    print("  L create", j2.booking_create_called, j2.booking_completed, "n", len(creates))
    if not j2.booking_create_called or not creates:
        failures.append("L: atomic_create 相当を呼んでいない")
    if not j2.booking_completed:
        failures.append("L: 完了になっていない")
    if creates:
        args = creates[-1]["args"]
        if "藤田" not in str(args) or "幸士" not in str(args):
            failures.append("L: 氏名が予約処理に渡っていない")
        if len(args) > 1 and args[1] != "visit":
            failures.append(f"L: place_type={args[1]}")

    print("\n===== 空白姓名＋連絡先＋出張先 =====")
    reset_store_for_tests()
    creates.clear()
    lookup_v = mock_slots("18:00")
    g_v = reach_guest(book_fn, lookup_v, place_type="visit")
    if "出張先" not in (g_v.reply or ""):
        failures.append(f"visit-ask: 出張なのに出張先案内がない {g_v.reply}")
    v1 = continue_chat(
        "藤田 幸士、090-1234-5678、test@example.com",
        g_v,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_v,
        book_fn=book_fn,
    )
    if v1.booking_phase != "guest_info":
        failures.append(f"H-space: phase={v1.booking_phase}")
    if "出張先だけ" not in (v1.reply or ""):
        failures.append(f"H-space: 出張先だけ聞いていない {v1.reply}")
    if v1.booking_create_called or creates:
        failures.append("M: 出張の不足確認中に予約作成している")
    v2 = continue_chat(
        "東京都渋谷区神南1-1",
        v1,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_v,
        book_fn=book_fn,
    )
    print("  visit confirm", v2.booking_phase, (v2.reply or "")[:80])
    if v2.booking_phase != "confirming":
        failures.append(f"K-follow: phase={v2.booking_phase}")
    if "出張先" not in (v2.reply or "") or "渋谷" not in (v2.reply or ""):
        failures.append("K: 出張の最終確認に出張先がない")
    if v2.booking_create_called or len(creates) != 0:
        failures.append("K: 最終確認前に予約作成している")

    reset_store_for_tests()
    creates.clear()
    g_f = reach_guest(book_fn, lookup_v, place_type="visit")
    f1 = continue_chat(
        "藤田 幸士、090-1234-5678、test@example.com、東京都渋谷区神南",
        g_f,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_v,
        book_fn=book_fn,
    )
    if f1.booking_phase != "confirming":
        failures.append(f"H-chat: 空白姓名一括後 phase={f1.booking_phase}")
    if NAME_REASK in (f1.reply or "") or "教えてください" in (f1.reply or ""):
        failures.append("H-chat: 一括入力後に追加質問している")
    if f1.booking_create_called or creates:
        failures.append("H-chat: 一括入力時点で予約作成している")

    print("\n===== I 会話: 複数ターン =====")
    reset_store_for_tests()
    creates.clear()
    lookup_h = mock_slots("18:00")
    g_h = reach_guest(book_fn, lookup_h, place_type="visit")
    h1 = continue_chat("姓：藤田、名：幸士", g_h, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_h, book_fn=book_fn)
    h2 = continue_chat("090-1234-5678です", h1, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_h, book_fn=book_fn)
    d_h2 = draft_of(h2)
    if d_h2.guest_last_name != "藤田" or d_h2.guest_phone != "09012345678":
        failures.append("I-chat: 既存項目が消えた")
    if NAME_REASK in (h2.reply or "") or OLD_NAME_ASK in (h2.reply or "") or "姓と名を分けて" in (h2.reply or ""):
        failures.append("I-chat: 姓名を再質問")
    if "メールアドレス" not in (h2.reply or "") or "出張先" not in (h2.reply or ""):
        failures.append(f"I-chat: 不足項目を聞いていない {h2.reply}")
    h3 = continue_chat("test@example.com", h2, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_h, book_fn=book_fn)
    if h3.booking_phase != "guest_info":
        failures.append(f"I-chat: email後 phase={h3.booking_phase}")
    if "出張先だけ" not in (h3.reply or ""):
        failures.append(f"I-chat: 出張先だけ聞いていない {h3.reply}")
    h4 = continue_chat("東京都渋谷区神南", h3, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_h, book_fn=book_fn)
    if h4.booking_phase != "confirming":
        failures.append(f"I-chat: 完了後 phase={h4.booking_phase}")
    if creates:
        failures.append("M: 複数ターン入力中に予約作成している")

    print("\n===== G 会話: 院内と言っても出張で検索 =====")
    reset_store_for_tests()
    creates.clear()
    lookup_g = mock_slots("18:00")
    g0 = continue_chat("予約したいです", None, match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_g, book_fn=book_fn)
    g1 = continue_chat(
        "東京の院内で9/10 18:00、90分",
        g0,
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=lookup_g,
        book_fn=book_fn,
    )
    print("  in_house utterance lookups", [c.get("place_type") for c in lookup_g.calls], (g1.reply or "")[:60])
    if lookup_g.calls and any(c.get("place_type") == "in_house" for c in lookup_g.calls):
        failures.append("G: 院内を予約枠検索に使っている")
    if lookup_g.calls and any(c.get("place_type") != "visit" for c in lookup_g.calls):
        failures.append(f"G: lookup place_type={[c.get('place_type') for c in lookup_g.calls]}")
    if "出張か院内" in (g1.reply or "") or "院内と出張" in (g1.reply or ""):
        failures.append("G: 院内を予約選択肢として聞いている")
    if g1.requested_place_type == "in_house":
        failures.append("G: requested_place_type=in_house")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if (after_n, after_h) != (before_n, before_h):
        failures.append("Knowledge DB がテスト中に変化した")
    if after_h != EXPECTED_HASH:
        failures.append(f"終了時 hash 不一致 {after_h}")

    if failures:
        print("\nguest_info FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nguest_info: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    print(f"next_iso sample {next_iso(9, 10)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
