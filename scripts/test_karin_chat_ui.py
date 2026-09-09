"""KARiN.chatbot UI改善テスト。会話ロジック・RAG・予約は触らない。

  python scripts/test_karin_chat_ui.py
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
GREETING = "気になることがあれば、お気軽にご相談ください。"
ENTRY_SAMPLES = [
    "予約がしたいです",
    "身体の相談をしたいです",
    "トレーナー帯同を依頼したいです",
    "企業訪問をお願いしたいです",
]
BODY_CONSULT_SAMPLES = [
    "腰が痛いんですが、何をしたらいいですか？",
    "鍼と整体、どちらが合いそうですか？",
    "初めてなんですが、どんな施術がありますか？",
    "東京で施術を受けたいです",
]


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


def js_string_array(js: str, name: str) -> list[str] | None:
    match = re.search(
        rf"var {name} = \[\s*((?:.|\n)*?)\s*\];",
        js,
    )
    if not match:
        return None
    return re.findall(r'"([^"]*)"', match.group(1))


def panel_head_html(widget: str) -> str:
    match = re.search(
        r'<div class="karin-chat-panel-head">(.*?)</div>\s*<div\s+class="karin-chat-messages"',
        widget,
        re.S,
    )
    return match.group(1) if match else ""


def main() -> int:
    print("mode: UI改善 / Knowledge読み取り専用 / 予約確定なし")
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h, before_c = snapshot_knowledge(admin)
    print(f"snapshot before: n={before_n} hash={before_h}")
    print("counts:", before_c)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")
    for key, value in EXPECTED_COUNTS.items():
        if before_c.get(key) != value:
            failures.append(f"開始時件数 {key}={before_c.get(key)}")

    js_path = os.path.join(ROOT, "static", "js", "karin_chat.js")
    css_path = os.path.join(ROOT, "static", "css", "karin_chat.css")
    widget_path = os.path.join(ROOT, "templates", "_karin_chat.html")
    js = open(js_path, encoding="utf-8").read()
    css = open(css_path, encoding="utf-8").read()
    widget = open(widget_path, encoding="utf-8").read()
    head = panel_head_html(widget)

    print("\n===== 初期表示 =====")
    greeting_match = re.search(r'var GREETING =\s*"([^"]*)"', js)
    greeting = greeting_match.group(1) if greeting_match else ""
    print("  greeting:", greeting)
    if greeting != GREETING:
        failures.append(f"初回メッセージ不一致: {greeting}")
    entry = js_string_array(js, "ENTRY_SAMPLES")
    print("  entry:", entry)
    if entry != ENTRY_SAMPLES:
        failures.append(f"初回4択不一致: {entry}")
    if "showSamples(ENTRY_SAMPLES)" not in js:
        failures.append("初回4択がUIに出る経路がない")

    print("\n===== 選択肢送信 =====")
    if "input.value = sample" in js:
        failures.append("選択肢が入力欄埋め込みのまま")
    if "sendMessage(sample)" not in js:
        failures.append("選択肢が sendMessage を呼んでいない")
    if js.count('fetch("/api/chat"') != 1:
        failures.append("チャット送信経路が二重実装されている")
    if "if (!message || sending) return" not in js:
        failures.append("二重送信防止がない")
    if "setChipsDisabled" not in js:
        failures.append("応答待ちの選択肢 disabled がない")
    if "appendMessage(\"user\", message)" not in js:
        failures.append("ユーザー発言として会話欄へ追加していない")

    print("\n===== 身体の相談 =====")
    if 'var BODY_CONSULT_MESSAGE = "身体の相談をしたいです"' not in js:
        failures.append("身体の相談の即時送信文言がない")
    body = js_string_array(js, "BODY_CONSULT_SAMPLES")
    print("  body samples:", body)
    if body != BODY_CONSULT_SAMPLES:
        failures.append(f"既存の身体の相談選択肢を変更している: {body}")
    if "message === BODY_CONSULT_MESSAGE ? BODY_CONSULT_SAMPLES" not in js:
        failures.append("身体の相談後に既存選択肢を再利用していない")
    if "showSamples(BODY_CONSULT_SAMPLES)" not in js and "showSamples(nextSamples)" not in js:
        failures.append("身体の相談後の再表示経路がない")
    if "followup_choices" not in js:
        failures.append("APIの followup_choices を見ていない")
    if "normalizeChoices" not in js:
        failures.append("followup_choices の正規化がない")

    print("\n===== ヘッダー =====")
    if "身体の相談" in head:
        failures.append("ヘッダーに『身体の相談』が残っている")
    if "<img" in head:
        failures.append("ヘッダーにアイコンがある")
    if "karin-chat-brand" not in head or "chatbot" not in head:
        failures.append("ヘッダーが KARiN.chatbot になっていない")
    if "新しく相談する" not in head:
        failures.append("新しく相談するがヘッダーにない")
    if "space-between" not in css or "karin-chat-panel-titlewrap" not in css:
        failures.append("タイトルと操作の分離レイアウトがない")
    if "flex-wrap: nowrap" not in css:
        failures.append("ヘッダーの折り返し抑制がない")

    print("\n===== アイコン =====")
    if "chatbotfaceicon.png" not in widget:
        failures.append("PNG参照がない")
    if "chatbotfaceicon.jpg" in widget or "chatbotfaceicon.jpg" in js:
        failures.append("JPG参照が残っている")
    if 'img.alt = "KARiN.chatbot"' not in js:
        failures.append("AIメッセージのアイコン alt がない")
    if re.search(r"row--user[\s\S]{0,400}chatbotfaceicon", js):
        failures.append("ユーザー側にアイコンを付ける実装がある")
    if "data-icon-url" not in widget:
        failures.append("AIアイコンURLがない")

    print("\n===== トップ起動UI =====")
    if "karin-launcher-in 10s" not in css:
        failures.append("約10秒のフェードインがない")
    if "animation-fill-mode: forwards" not in css and "forwards" not in css:
        failures.append("フェードイン後に表示が定着しない")
    if "data-karin-dismiss-launcher" not in widget:
        failures.append("起動UIの×がない")
    if "stopPropagation" not in js or "launcher.hidden = true" not in js:
        failures.append("×で起動UIを閉じる処理がない")
    if ".karin-chat-launcher:hover .karin-chat-fab-dismiss" not in css:
        failures.append("PCでhover時に×を出す指定がない")
    if re.search(r"\.karin-chat-fab-dismiss\s*\{[^}]*opacity:\s*0", css) is None:
        failures.append("PCで非hover時に×が隠れない")
    if "(hover: none)" not in css:
        failures.append("スマホでタップ可能な×指定がない")
    if ".karin-chat-fab-dismiss::before" not in css or "inset: -13px" not in css:
        failures.append("起動UIの×のタップ範囲拡張がない")
    if re.search(r"\.karin-chat-fab-dismiss\s*\{[^}]*width:\s*18px", css) is None:
        failures.append("起動UIの×の見た目が小さくなっていない")

    print("\n===== 書体・安全 =====")
    if '"Playfair Display"' not in css or ".karin-chat-brand" not in css:
        failures.append("KARiN.の既存書体指定がない")
    if ".karin-chat-title-rest" not in css or '"Noto Sans JP"' not in css:
        failures.append("chatbot部分の本文書体指定がない")
    if "innerHTML" in js:
        failures.append("innerHTML を使用している")
    if "/api/book" in js:
        failures.append("/api/book を呼ぶ実装がある")
    if "list_web_booking_slots" in js or "is_emergency_message" in js:
        failures.append("UIに予約ロジックまたはSafety Gateを複製している")

    after_n, after_h, after_c = snapshot_knowledge(admin)
    print(f"\nsnapshot after: n={after_n} hash={after_h}")
    if (after_n, after_h, after_c) != (before_n, before_h, before_c):
        failures.append("Knowledge DB がUIテスト中に変化した")
    if after_h != EXPECTED_HASH:
        failures.append(f"終了時 hash 不一致 {after_h}")

    if failures:
        print("\nUI FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nUI改善テスト: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
