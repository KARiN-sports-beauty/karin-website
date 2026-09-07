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
INTENT_TRAINER_ACCOMPANY = "trainer_accompaniment"
INTENT_CORPORATE_VISIT = "corporate_visit"
INTENT_INQUIRY_REQUIRED = "inquiry_required"
INTENT_CONSULTATION = "consultation"
INTENT_HEALTH = "health_general"
INTENT_UNCLEAR = "unclear"

# チャットでは受け付けず、お問い合わせフォームへ誘導する依頼。
INQUIRY_REQUIRED_INTENTS = frozenset(
    {
        INTENT_TRAINER_ACCOMPANY,
        INTENT_CORPORATE_VISIT,
    }
)

# primary を決めるときの具体性。Knowledge種別の優先順位ではない。
_PRIMARY_ORDER = (
    INTENT_SAFETY,
    INTENT_TRAINER_ACCOMPANY,
    INTENT_CORPORATE_VISIT,
    INTENT_TREATMENT,
    INTENT_CAMPAIGN,
    INTENT_PRICE,
    INTENT_HOURS,
    INTENT_SERVICE,
    INTENT_RESERVATION_INFO,
    INTENT_RESERVATION,
    INTENT_CONSULTATION,
    INTENT_HEALTH,
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


def _explicit_consult_switch(text: str) -> bool:
    """予約の途中でも、ユーザーが相談へ戻したいと明示したとき。"""
    raw = (text or "").strip()
    if not raw:
        return False
    if _consult_only(raw):
        return True
    return _has(
        r"詳しく相談|予約する前に.{0,24}相談|"
        r"身体の(こと|悩み).{0,16}相談|"
        r"(鍼|整体).{0,20}(どちら|どっち).{0,16}(詳しく|相談)",
        raw,
    )


def _is_reservation_want(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    capability_ask = _has(r"(でき|できます)か|お願いすることは", raw)
    return _has(
        r"予約(が|を)?したい|予約をお願い|予約を(取り|と)たい|"
        r"施術をお願いしたい|予約できるか|空いてますか|空き.{0,6}(確認|知り)|"
        r"どこか空いて",
        raw,
    ) or (
        _has(r"(明日|今日|今夜).{0,20}お願いしたい", raw) and not capability_ask
    ) or (
        _has(r"(明日|今日|今夜).{0,12}(夜|夕方).{0,16}(どう|いかが)", raw)
        and not capability_ask
    ) or (
        _has(r"(東京|福岡).{0,24}\d+分.{0,16}お願いしたい", raw)
        and not capability_ask
    )


def _prior_had_reservation(prior_user_texts: list[str]) -> bool:
    for item in prior_user_texts:
        if _is_reservation_want(item) and not _consult_only(item):
            return True
    return False


def _is_inquiry_info_ask(text: str) -> bool:
    return _has(r"(でき|できます)か|とは|って何|について(知り|教えて)", text)


def _is_trainer_accompany_request(text: str) -> bool:
    """チャットで帯同を依頼する明確な意思。案内や「できますか」は含めない。"""
    raw = (text or "").strip()
    if not raw or _is_inquiry_info_ask(raw):
        return False
    return _has(
        r"トレーナー帯同を依頼|"
        r"トレーナー帯同.{0,16}(お願いしたい|を依頼)|"
        r"(トレーナー)?帯同を(依頼したい|お願いしたい)",
        raw,
    )


def _is_corporate_visit_request(text: str) -> bool:
    """チャットで企業訪問を依頼する明確な意思。案内や「できますか」は含めない。"""
    raw = (text or "").strip()
    if not raw or _is_inquiry_info_ask(raw):
        return False
    return _has(
        r"企業訪問をお願いしたい|"
        r"企業訪問を依頼|"
        r"企業訪問.{0,16}(お願いしたい|を依頼)|"
        r"法人(向け)?(の)?(訪問|コンディショニング).{0,16}(お願いしたい|を依頼)",
        raw,
    )


def inquiry_request_kind(text: str) -> str | None:
    """trainer_accompaniment / corporate_visit。どちらでも inquiry_required フロー。"""
    if _is_trainer_accompany_request(text):
        return INTENT_TRAINER_ACCOMPANY
    if _is_corporate_visit_request(text):
        return INTENT_CORPORATE_VISIT
    return None


def _prior_inquiry_kind(prior_user_texts: list[str] | None) -> str | None:
    for item in reversed(prior_user_texts or []):
        kind = inquiry_request_kind(item)
        if kind:
            return kind
    return None


def is_inquiry_required_intent(intent: IntentResult | None) -> bool:
    if intent is None:
        return False
    return any(item in INQUIRY_REQUIRED_INTENTS for item in intent.all_intents)


def _needs_official_for_treatment(text: str) -> bool:
    return bool(_OFFICIAL_SERVICE_HINT.search(text))


def _is_general_health_topic(text: str) -> bool:
    """睡眠・水分・暑さ・運動などの一般健康の話。KARiN事実の判定ではない。"""
    return _has(
        r"睡眠|寝つき|眠れ|眠気|寝不足|就寝|起床|"
        r"水分|脱水|のどが渇|"
        r"熱中症|暑い日|暑さ|"
        r"運動(を始め|後|中|するとき|時|して)|いきなり頑張",
        text,
    )


def is_deictic_followup(text: str) -> bool:
    """現在の発話だけだと指示対象が足りない続き。"""
    raw = (text or "").strip()
    if not raw:
        return False
    if _has(r"鍼|整体|美容鍼|料金|いくら|予約|割引|出張|病院", raw):
        return False
    return bool(
        re.search(r"^(それ|その|あれ|じゃあ)|それって|それなら|どっち|どちら", raw)
    )


def detect_intents(
    text: str, prior_user_texts: list[str] | None = None
) -> IntentResult:
    """現在の発話を最優先し、不足するときだけ過去ターンを補助に使う。Intentは固定しない。"""
    current = _detect_from_text(text)
    priors = [p.strip() for p in (prior_user_texts or []) if (p or "").strip()]
    if _explicit_consult_switch(text):
        if current.primary_intent != INTENT_UNCLEAR:
            return current
        if priors:
            return _detect_from_text(" ".join(priors[-2:] + [(text or "").strip()]))
        return current
    current_inquiry = inquiry_request_kind(text)
    if current_inquiry:
        return IntentResult(
            primary_intent=current_inquiry,
            secondary_intents=[INTENT_INQUIRY_REQUIRED],
            source_types=source_types_for_intents(current_inquiry, [INTENT_INQUIRY_REQUIRED], text),
        )
    prior_inquiry = _prior_inquiry_kind(priors)
    if (
        prior_inquiry
        and not _is_reservation_want(text)
        and current.primary_intent in (INTENT_UNCLEAR, INTENT_SERVICE)
    ):
        return IntentResult(
            primary_intent=prior_inquiry,
            secondary_intents=[INTENT_INQUIRY_REQUIRED],
            source_types=source_types_for_intents(prior_inquiry, [INTENT_INQUIRY_REQUIRED], text),
        )
    if _prior_had_reservation(priors) and current.primary_intent in (
        INTENT_UNCLEAR,
        INTENT_CONSULTATION,
        INTENT_HEALTH,
        INTENT_TREATMENT,
    ):
        secondary = [
            x
            for x in current.all_intents
            if x not in (INTENT_UNCLEAR, INTENT_RESERVATION)
        ]
        types = source_types_for_intents(INTENT_RESERVATION, [], text)
        return IntentResult(
            primary_intent=INTENT_RESERVATION,
            secondary_intents=secondary,
            source_types=types,
        )
    if not priors:
        return current
    if current.primary_intent != INTENT_UNCLEAR:
        return current
    combined = " ".join(priors[-2:] + [(text or "").strip()])
    return _detect_from_text(combined)


def _detect_from_text(text: str) -> IntentResult:
    raw = (text or "").strip()
    matched: list[str] = []

    if _consult_only(raw) or _has(
        r"聞いても(いい|良い)|ちょっと聞|質問しても", raw
    ):
        matched.append(INTENT_CONSULTATION)
    elif _has(r"初めて(利用|来|お願い|受け)", raw) and not _has(
        r"割引|特典|安く", raw
    ):
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
        r"予約(って)?どう|どうやって(取|予約)|LINEから.{0,10}予約|何を入力|"
        r"予約するとき|予約するならどう|どうしたらいい|どうすればいい",
        raw,
    )
    if how_to_book:
        matched.append(INTENT_RESERVATION_INFO)

    capability_ask = _has(r"(でき|できます)か|お願いすることは", raw)
    want_booking = _is_reservation_want(raw)
    if want_booking and not _consult_only(raw):
        if INTENT_RESERVATION_INFO not in matched or _has(r"空いて", raw):
            matched.append(INTENT_RESERVATION)

    if _has(
        r"(鍼|整体|美容鍼).{0,24}(どっち|どちら|向いて|違う|合い)|"
        r"鍼と整体|整体と鍼|鍼とか整体|鍼や整体|"
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

    body_talk = _has(r"痛|こり|こります|凝って|つら|温め|重い|しび", raw)
    if body_talk and INTENT_SAFETY not in matched and INTENT_TREATMENT not in matched:
        matched.append(INTENT_CONSULTATION)

    if _is_general_health_topic(raw):
        matched.append(INTENT_HEALTH)

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
        if intent == INTENT_HEALTH:
            add("health")
        elif intent in (INTENT_CONSULTATION, INTENT_SAFETY, INTENT_UNCLEAR):
            add("notes")
            if intent == INTENT_CONSULTATION:
                add("health")
        elif intent == INTENT_TREATMENT:
            add("notes")
            add("health")
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
        elif intent in INQUIRY_REQUIRED_INTENTS or intent == INTENT_INQUIRY_REQUIRED:
            add("official")
    if not selected:
        add("notes")
    return selected
