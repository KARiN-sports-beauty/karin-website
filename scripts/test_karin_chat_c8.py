"""C8 UI/バックエンド境界。空き枠と予約導線は構造化。PNGアイコン。

  python scripts/test_karin_chat_c8.py
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
from karin_chat import (  # noqa: E402
    BOOKING_LOOKUP_ERROR_REPLY,
    EMERGENCY_REPLY,
    chat_public_payload,
    is_emergency_message,
    run_chat,
)
from karin_chat_memory import reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
EXPECTED_COUNTS = {
    "total": 34,
    "inactive": 2,
    "official_active_canonical": 19,
    "notes": 6,
    "health": 7,
}


def snapshot_knowledge(admin) -> tuple[int, str, dict[str, int]]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    counts = {
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
    }
    return len(rows), digest, counts


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


def empty_match(*_a, **_k):
    return []


def main() -> int:
    print("mode: C8 UI境界 / Knowledge読み取り専用 / 予約確定なし")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h, before_c = snapshot_knowledge(admin)
    print(f"snapshot before: n={before_n} hash={before_h}")
    print("counts:", before_c)
    if before_h != EXPECTED_HASH:
        failures.append(f"C8前 hash 不一致 {before_h}")
    for key, value in EXPECTED_COUNTS.items():
        if before_c.get(key) != value:
            failures.append(f"C8前件数 {key}={before_c.get(key)}")

    js_path = os.path.join(ROOT, "static", "js", "karin_chat.js")
    css_path = os.path.join(ROOT, "static", "css", "karin_chat.css")
    widget_path = os.path.join(ROOT, "templates", "_karin_chat.html")
    chat_page_path = os.path.join(ROOT, "templates", "chat.html")
    js = open(js_path, encoding="utf-8").read()
    css = open(css_path, encoding="utf-8").read()
    widget = open(widget_path, encoding="utf-8").read()
    chat_page = open(chat_page_path, encoding="utf-8").read() if os.path.exists(chat_page_path) else ""

    print("\n===== Test 1 構造化空き枠 =====")
    lookup = mock_slots("18:00", "19:30")
    t1 = run_chat(
        "東京で90分、明日空いてますか？",
        lookup_fn=lookup,
        match_fn=empty_match,
        complete_fn=lambda _m: "ご希望の条件で空きを確認しました。",
    )
    p1 = chat_public_payload(t1)
    print("  available_slots:", p1["available_slots"])
    if p1["available_slots"] != ["18:00", "19:30"]:
        failures.append(f"Test1: slots={p1['available_slots']}")
    if p1["reply"] != t1.reply or not p1.get("conversation_id"):
        failures.append("Test1: reply/conversation_id 互換が崩れた")
    if not lookup.calls:
        failures.append("Test1: 既存予約lookupを使っていない")

    print("\n===== Test 2 未返却時刻を追加しない =====")
    if "20:00" in p1["available_slots"] or "20:30" in p1["available_slots"] or "21:00" in p1["available_slots"]:
        failures.append("Test2: APIにない時刻が構造化データにある")
    if re.search(r'["\']20:00["\']', js) or re.search(r'["\']18:00["\']', js):
        failures.append("Test2: UIが時刻をハードコードしている")

    print("\n===== Test 3 本文と構造化枠 =====")
    if p1["available_slots"] != ["18:00", "19:30"]:
        failures.append("Test3: 構造化枠がない")
    if "available_slots" not in js or "normalizeSlots" not in js or "appendSlots" not in js:
        failures.append("Test3: UIが available_slots から枠を描画する経路がない")
    if "formatSlotLabel" not in js:
        failures.append("Test3: 日時を1つにまとめる表示がない")
    if "ご希望の条件で確認しました。" in js:
        failures.append("Test3: 重複テロップが残っている")

    print("\n===== Test 4 LLMが20:00と書いても構造化枠に足さない =====")
    lookup4 = mock_slots("18:00", "19:30")
    t4 = run_chat(
        "東京で90分、明日空いてますか？",
        lookup_fn=lookup4,
        match_fn=empty_match,
        complete_fn=lambda _m: "20:00も空いています。",
    )
    p4 = chat_public_payload(t4)
    print("  reply has 20:00:", "20:00" in (p4["reply"] or ""), "slots:", p4["available_slots"])
    if p4["available_slots"] != ["18:00", "19:30"]:
        failures.append(f"Test4: slots={p4['available_slots']}")
    if "20:00" in p4["available_slots"]:
        failures.append("Test4: 本文の20:00を構造化枠へ混ぜた")

    print("\n===== Test 5 予約CTA =====")
    t5 = run_chat(
        "予約したいです。",
        match_fn=empty_match,
        complete_fn=lambda _m: "ご希望のエリアを教えてください。",
    )
    p5 = chat_public_payload(t5)
    print("  show_booking_cta:", p5["show_booking_cta"], "intent:", t5.primary_intent)
    if not p5["show_booking_cta"]:
        failures.append("Test5: 予約意図なのに CTA がない")
    if "Web予約へ進む" not in js:
        failures.append("Test5: 固定ボタン文言がない")
    if "appendBookCta" not in js or "showBookingCta" not in js:
        failures.append("Test5: CTA をAPIフラグから出していない")
    if 'link.href = bookUrl' not in js:
        failures.append("Test5: /book への遷移がない")
    if "data-book-url" not in widget:
        failures.append("Test5: テンプレートに book URL がない")

    print("\n===== Test 6 相談中は大きな予約ボタンを出さない =====")
    t6 = run_chat(
        "腰が痛いです。",
        match_fn=empty_match,
        complete_fn=lambda _m: "腰の痛みについてお聞きします。",
    )
    p6 = chat_public_payload(t6)
    print("  show_booking_cta:", p6["show_booking_cta"], "intent:", t6.primary_intent)
    if p6["show_booking_cta"]:
        failures.append("Test6: 相談中に CTA が出ている")
    if p6["available_slots"]:
        failures.append(f"Test6: 相談中に空き枠がある {p6['available_slots']}")
    if "show_booking_cta === true" not in js and "showBookingCta" not in js:
        failures.append("Test6: CTA が常時表示になる実装")

    print("\n===== Test 7 Safety Gate =====")
    emergency_msg = "さっきから急に右半身に力が入らなくなりました。"
    if not is_emergency_message(emergency_msg):
        failures.append("Test7: 緊急判定できていない")
    t7 = run_chat(
        emergency_msg,
        match_fn=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rag")),
        complete_fn=lambda _m: "should-not-run",
        lookup_fn=boom_lookup,
    )
    p7 = chat_public_payload(t7)
    print("  emergency:", t7.emergency, "slots:", p7["available_slots"], "cta:", p7["show_booking_cta"])
    if not t7.emergency or t7.reply != EMERGENCY_REPLY:
        failures.append("Test7: 固定の受診文でない")
    if t7.rag_called or t7.openai_called or t7.reservation_api_called:
        failures.append("Test7: 緊急時にRAG/OpenAI/予約APIを呼んだ")
    if p7["available_slots"] or p7["show_booking_cta"] or p7.get("show_inquiry_cta"):
        failures.append("Test7: 緊急時に枠またはCTAがある")

    print("\n===== 予約APIエラー =====")
    t_err = run_chat(
        "東京で90分、明日の19時は空いてますか？",
        lookup_fn=boom_lookup,
        match_fn=empty_match,
        complete_fn=lambda _m: "should-not-run",
    )
    p_err = chat_public_payload(t_err)
    if t_err.reply != BOOKING_LOOKUP_ERROR_REPLY:
        failures.append("ERR: 固定安全文でない")
    if p_err["available_slots"] or p_err["show_booking_cta"]:
        failures.append("ERR: エラー時に枠またはCTAがある")
    if any(x in (t_err.reply or "") for x in ("SELECT", "traceback", "https://internal", "sk-")):
        failures.append("ERR: 内部情報漏洩")

    print("\n===== Test 8 PNGアイコン =====")
    from app import app

    with app.test_client() as client:
        icon = client.get("/static/images/chatbotfaceicon.png")
        chat_html = client.get("/chat")
        book_html = client.get("/book")
        empty = client.post("/api/chat", json={})
        print("  /chat", chat_html.status_code, "/book", book_html.status_code, "icon", icon.status_code)
        if icon.status_code != 200 or "png" not in (icon.content_type or "").lower():
            failures.append("Test8: PNGが読めない")
        chat_text = chat_html.get_data(as_text=True)
        if "chatbotfaceicon.png" not in widget or "chatbotfaceicon.png" not in chat_text:
            failures.append("Test8: PNG参照がない")
        if "chatbotfaceicon.jpg" in widget or "chatbotfaceicon.jpg" in js or "chatbotfaceicon.jpg" in css:
            failures.append("Test8: C5 UIにJPG参照が残っている")
        if "chatbotfaceicon.jpg" in chat_page or "chatbotfaceicon.jpg" in chat_text:
            failures.append("Test8: /chat にJPG参照がある")
        if 'img.alt = "KARiN.chatbot"' not in js:
            failures.append("Test8: AIアイコン alt がない")
        if re.search(r"row--user[\s\S]{0,400}chatbotfaceicon", js):
            failures.append("Test8: ユーザー側にアイコンを付ける実装")
        if book_html.status_code != 200:
            failures.append("Test8: /book が開けない")
        empty_body = empty.get_json(silent=True) or {}
        if empty.status_code == 200:
            failures.append("SEC: 空メッセージが200")
        if any(x in json.dumps(empty_body) for x in ("sk-", "traceback", "SUPABASE_SERVICE")):
            failures.append("SEC: エラーに秘密情報")

    print("\n===== Test 9 XSS =====")
    if "innerHTML" in js:
        failures.append("Test9: innerHTML を使用")
    if "textContent" not in js or "createElement" not in js:
        failures.append("Test9: 安全なDOM生成がない")
    if "renderSafeText" not in js:
        failures.append("Test9: 本文の安全描画がない")

    ui_files = js + css + widget + chat_page
    if "list_web_booking_slots" in js or "build_booking_slot_list" in js:
        failures.append("UI: 予約ロジックを複製している")
    if "/api/book" in js:
        failures.append("UI: 予約作成APIを呼ぶ実装がある")

    after_n, after_h, after_c = snapshot_knowledge(admin)
    print(f"\nsnapshot after: n={after_n} hash={after_h}")
    if (after_n, after_h, after_c) != (before_n, before_h, before_c):
        failures.append("Knowledge DB がC8中に変化した")
    if after_h != EXPECTED_HASH:
        failures.append(f"C8後 hash 不一致 {after_h}")

    if failures:
        print("\nC8 FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nC8 UI境界テスト: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
