"""KARiN.chatbot C2: Intent と source_type 選択（アプリ層）。

固定順位 official > notes > health は作らない。
LLMには丸投げしない。単語「腰」だけで consultation にもしない。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

INTENT_SAFETY = "safety"
INTENT_TREATMENT = "treatment_consultation"
INTENT_CAMPAIGN = "campaign_or_discount"
INTENT_PRICE = "price_info"
INTENT_HOURS = "business_hours"
INTENT_SERVICE = "service_info"
INTENT_RESERVATION_INFO = "reservation_info"
INTENT_RESERVATION = "reservation_intent"
INTENT_CONSULTATION = "consultation"
INTENT_UNCLEAR = "unclear"

# primary を決めるときの具体性。Knowledge種別の優先順位ではない。
_PRIMARY_ORDER = (
    INTENT_SAFETY,
    INTENT_TREATMENT,
    INTENT_CAMPAIGN,
    INTENT_PRICE,
    INTENT_HOURS,
    INTENT_SERVICE,
    INTENT_RESERVATION_INFO,
    INTENT_RESERVATION,
    INTENT_CONSULTATION,
    INTENT_UNCLEAR,
)

_OFFICIAL_SERVICE_HINT = re.compile(
    r"美容鍼|帯同|出張|トータルコンディショニング|院内"
)


@dataclass
class IntentResult:
    primary_intent: str
    secondary_intents: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)

    @property
    def all_intents(self) -> list[str]:
        out = [self.primary_intent]
        for item in self.secondary_intents:
            if item not in out:
                out.append(item)
        return out


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text))


def _consult_only(text: str) -> bool:
    if _has(r"空いて", text):
        return False
    return _has(
        r"(まだ)?予約.{0,20}(決め|決めてない|してない)|相談(だけ|しても(いい|良い))",
        text,
    )


def _needs_official_for_treatment(text: str) -> bool:
    return bool(_OFFICIAL_SERVICE_HINT.search(text))


def detect_intents(text: str) -> IntentResult:
    raw = (text or "").strip()
    matched: list[str] = []

    if _consult_only(raw):
        matched.append(INTENT_CONSULTATION)

    if _has(
        r"病院に(行った|行く)|受診|放っておいて|病院に行くか迷|病院.{0,12}迷って",
        raw,
    ):
        matched.append(INTENT_SAFETY)

    if _has(
        r"初回.{0,12}(割引|特典|安)|初めて.{0,16}(割引|特典|安く)|"
        r"特典.{0,8}(あり|ある)|割引.{0,10}(あり|ある|します)",
        raw,
    ):
        matched.append(INTENT_CAMPAIGN)

    if _has(r"いくら|料金|税込|円くら|交通費", raw):
        matched.append(INTENT_PRICE)

    if _has(r"何時まで|何時から|営業時間|夜遅|夜も(やっ|対応|やって)|遅い時間", raw):
        matched.append(INTENT_HOURS)
    elif _has(r"(夜|遅い).{0,12}(お願い|施術|対応)(でき|できます)", raw) and not _has(
        r"空いて|予約したい", raw
    ):
        matched.append(INTENT_HOURS)

    how_to_book = _has(r"予約", raw) and _has(
        r"予約(って)?どう|どうやって取|LINEから.{0,10}予約|何を入力|予約するとき|どうしたらいい",
        raw,
    )
    if how_to_book:
        matched.append(INTENT_RESERVATION_INFO)

    capability_ask = _has(r"(でき|できます)か|お願いすることは", raw)
    want_booking = _has(
        r"予約したい|施術をお願いしたい|予約できるか|空いてますか|空き.{0,6}(確認|知り)",
        raw,
    ) or (
        _has(r"(明日|今日|今夜).{0,20}お願いしたい", raw) and not capability_ask
    )
    if want_booking and not _consult_only(raw):
        if INTENT_RESERVATION_INFO not in matched or _has(r"空いて", raw):
            matched.append(INTENT_RESERVATION)

    if _has(
        r"(鍼|整体|美容鍼).{0,24}(どっち|どちら|向いて|違う|合い)|"
        r"鍼と整体|整体と鍼|"
        r"どんなときに受ける|どんな施術が合い|どの施術",
        raw,
    ):
        matched.append(INTENT_TREATMENT)

    if _has(
        r"出張.{0,16}(でき|お願い|対応)|東京でも施術|福岡でも|"
        r"美容鍼もやっ|帯同.{0,12}(でき|お願い)|院内で(施術|受け)",
        raw,
    ):
        matched.append(INTENT_SERVICE)

    body_talk = _has(r"痛|こり|こります|つら|温め|重い|しび", raw)
    if body_talk and INTENT_SAFETY not in matched and INTENT_TREATMENT not in matched:
        matched.append(INTENT_CONSULTATION)

    uniq: list[str] = []
    for item in matched:
        if item not in uniq:
            uniq.append(item)
    if not uniq:
        uniq = [INTENT_UNCLEAR]

    primary = next((p for p in _PRIMARY_ORDER if p in uniq), uniq[0])
    secondary = [x for x in uniq if x != primary]
    types = source_types_for_intents(primary, secondary, raw)
    return IntentResult(primary_intent=primary, secondary_intents=secondary, source_types=types)


def source_types_for_intents(
    primary: str, secondary: list[str], text: str
) -> list[str]:
    """質問の目的に応じた検索対象。①＞②＞③の固定順位ではない。"""
    selected: list[str] = []

    def add(kind: str) -> None:
        if kind not in selected:
            selected.append(kind)

    for intent in [primary, *secondary]:
        if intent in (INTENT_CONSULTATION, INTENT_SAFETY, INTENT_UNCLEAR):
            add("notes")
        elif intent == INTENT_TREATMENT:
            add("notes")
            # 美容鍼・帯同などKARiNの具体サービスに触れるときは official も候補。
            if _needs_official_for_treatment(text) or _has(r"鍼|整体|トレーニング", text):
                add("official")
        elif intent in (
            INTENT_SERVICE,
            INTENT_PRICE,
            INTENT_HOURS,
            INTENT_CAMPAIGN,
            INTENT_RESERVATION_INFO,
        ):
            add("official")
        elif intent == INTENT_RESERVATION:
            # 空きはKnowledgeで判断しない。方法・条件の事実だけ必要なら official。
            add("official")
    if not selected:
        add("notes")
    return selected
