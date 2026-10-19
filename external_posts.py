"""KARiN.NOTES とサービス紹介の外部投稿状態。

投稿先は次の4つを別々に扱う。

- GBP東京
- GBP福岡
- Instagram
- Facebook

実投稿は STEP 1（GBP）と STEP 2（Instagram / Facebook）まで行わない。
このモジュールの送信関数は成功を返さない。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


class ExternalPostNotConnected(Exception):
    """外部APIが未接続。呼び出し元は投稿済にしてはいけない。"""


class ExternalPostConflict(Exception):
    """状態が先に変わった。上書きも再送もしない。"""


EXTERNAL_POST_TARGETS = (
    {
        "key": "gbp_tokyo",
        "channel": "gbp",
        "gbp_profile": "tokyo",
        "button_label": "GBP東京",
        "posted_label": "✓ GBP東京済",
        "guide": "東京GBP向けです。短く、記事への導線が分かる文章にしてください。",
    },
    {
        "key": "gbp_fukuoka",
        "channel": "gbp",
        "gbp_profile": "fukuoka",
        "button_label": "GBP福岡",
        "posted_label": "✓ GBP福岡済",
        "guide": "福岡GBP向けです。東京向けの文面とは別に、必要なら地域の書き方を変えてください。",
    },
    {
        "key": "instagram",
        "channel": "instagram",
        "gbp_profile": None,
        "button_label": "Instagram",
        "posted_label": "✓ Instagram済",
        "guide": "Instagram向けです。読みやすく、記事に興味が続く文章にしてください。",
    },
    {
        "key": "facebook",
        "channel": "facebook",
        "gbp_profile": None,
        "button_label": "Facebook",
        "posted_label": "✓ Facebook済",
        "guide": "Facebook向けです。Instagramより文章量を持たせ、記事の内容が伝わるようにしてください。",
    },
)

GBP_SERVICE_CATALOG = (
    {
        "key": "acupuncture",
        "label": "鍼灸",
        "note": "",
    },
    {
        "key": "seitai_conditioning",
        "label": "整体・コンディショニング",
        "note": "",
    },
    {
        "key": "training_reconditioning",
        "label": "トレーニング・リコンディショニング",
        "note": "1つのサービスとして扱います。公開ページは新設予定です。",
    },
    {
        "key": "beauty_acupuncture",
        "label": "美容鍼",
        "note": "公開ページは新設予定です。",
    },
    {
        "key": "trainer_accompany",
        "label": "トレーナー帯同",
        "note": "必要なときだけ使います。",
    },
)

GBP_SERVICE_AREAS = {
    "tokyo": "東京",
    "fukuoka": "福岡",
}

LOCKED_STATUSES = frozenset({"posted", "posting", "unknown"})

EVENT_LABELS = {
    "generated": "文面を作成",
    "edited": "文面を保存",
    "confirmed": "投稿内容を確認",
    "submit_started": "送信を開始",
    "succeeded": "投稿成功",
    "failed": "投稿失敗",
    "unknown": "成否不明",
}

_STATUS_BUTTON = {
    "draft": ("保存済", "is-saved"),
    "ready": ("確認済", "is-saved"),
    "posting": ("送信中", "is-posting"),
    "failed": ("失敗", "is-failed"),
    "unknown": ("要確認", "is-unknown"),
}


def get_target(target_key):
    key = (target_key or "").strip()
    for target in EXTERNAL_POST_TARGETS:
        if target["key"] == key:
            return target
    return None


def parse_service_area(raw):
    """不明な地域は採用しない。一覧の未指定だけ service_area が東京に戻す。"""
    area = (raw or "").strip().lower()
    if area in GBP_SERVICE_AREAS:
        return area
    return None


def service_area(raw):
    return parse_service_area(raw) or "tokyo"


def get_service(service_key):
    key = (service_key or "").strip()
    for item in GBP_SERVICE_CATALOG:
        if item["key"] == key:
            return item
    return None


def resolve_service_screen(area, service_key):
    """地域とサービスの組だけ返す。見つからなければ画面を開かない。"""
    parsed = parse_service_area(area)
    service = get_service(service_key)
    if parsed is None or service is None:
        return None, "サービスまたは地域が見つかりません"
    return {
        "area": parsed,
        "area_label": GBP_SERVICE_AREAS[parsed],
        "service": service,
        "gbp_profile": parsed,
        "channel": "gbp",
    }, None


def service_public_path(area, service_key):
    paths = {
        ("tokyo", "acupuncture"): "/tokyo/shinkyu",
        ("fukuoka", "acupuncture"): "/fukuoka/shinkyu",
        ("tokyo", "seitai_conditioning"): "/tokyo/seitai",
        ("fukuoka", "seitai_conditioning"): "/fukuoka/seitai",
        ("tokyo", "beauty_acupuncture"): "/beauty",
        ("fukuoka", "beauty_acupuncture"): "/beauty",
        ("tokyo", "training_reconditioning"): "/training",
        ("fukuoka", "training_reconditioning"): "/training",
        ("tokyo", "trainer_accompany"): "/trainer",
        ("fukuoka", "trainer_accompany"): "/trainer",
    }
    return paths.get((area, service_key), "/")


def starter_service_body(area, service, link_url):
    """地域とサービス名だけの下書き。料金や効果は書かない。"""
    place = GBP_SERVICE_AREAS.get(area) or ""
    label = (service or {}).get("label") or "施術"
    url = (link_url or "").strip()
    lines = [
        f"KARiN.の{label}について。",
        f"{place}での出張施術をご検討の方へ。内容はウェブサイトにまとめています。",
        url,
    ]
    return "\n\n".join(line for line in lines if line)


def target_key_for_row(row):
    if not row:
        return None
    channel = row.get("channel")
    profile = row.get("gbp_profile") or None
    for target in EXTERNAL_POST_TARGETS:
        if target["channel"] == channel and target["gbp_profile"] == profile:
            return target["key"]
    return None


def article_button_view(target, row):
    """カード上のラベル。色用クラスと、文字での状態を両方返す。"""
    status = (row or {}).get("status")
    if status == "posted":
        return {
            "key": target["key"],
            "label": target["posted_label"],
            "css_class": "is-posted",
            "status": status,
        }
    suffix, css_class = _STATUS_BUTTON.get(status, ("", ""))
    label = target["button_label"] if not suffix else f"{target['button_label']} {suffix}"
    return {
        "key": target["key"],
        "label": label,
        "css_class": css_class,
        "status": status,
    }


def status_caption(status):
    captions = {
        None: "未投稿",
        "": "未投稿",
        "draft": "下書き保存",
        "ready": "確認済・未投稿",
        "posting": "送信中",
        "posted": "投稿済",
        "failed": "失敗",
        "unknown": "要確認",
    }
    return captions.get(status, "未投稿")


def attach_article_buttons(blogs, client):
    """一覧用。取得に失敗しても記事一覧自体は出す。"""
    indexed = {}
    try:
        ids = [blog.get("id") for blog in blogs if blog.get("id") is not None]
        if ids and client is not None:
            res = (
                client.table("external_posts")
                .select("id,blog_id,channel,gbp_profile,status")
                .eq("source_kind", "notes_article")
                .in_("blog_id", [str(blog_id) for blog_id in ids])
                .execute()
            )
            for row in res.data or []:
                key = target_key_for_row(row)
                if not key:
                    continue
                indexed.setdefault(str(row.get("blog_id")), {})[key] = row
    except Exception as exc:
        print("❌ 外部投稿状態の取得エラー:", exc)
    for blog in blogs:
        states = indexed.get(str(blog.get("id")), {})
        blog["external_post_buttons"] = [
            article_button_view(target, states.get(target["key"]))
            for target in EXTERNAL_POST_TARGETS
        ]
    return blogs


def _clip(text, limit):
    flat = re.sub(r"\s+", " ", text or "").strip()
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def starter_body(target_key, title, excerpt, link_url):
    """媒体ごとの下書き。AIは呼ばない。記事のタイトルと導入文だけを材料にする。"""
    target = get_target(target_key)
    heading = (title or "").strip() or "KARiN.NOTES"
    lead_limit = {"gbp_tokyo": 80, "gbp_fukuoka": 80, "instagram": 140, "facebook": 280}
    lead = _clip(excerpt, lead_limit.get(target_key, 120))
    url = (link_url or "").strip()
    if target_key == "gbp_tokyo":
        lines = [heading, lead, "東京で施術をご検討の方へ。内容は記事にまとめています。", url]
    elif target_key == "gbp_fukuoka":
        lines = [heading, lead, "福岡で施術をご検討の方へ。内容は記事にまとめています。", url]
    elif target_key == "instagram":
        lines = [heading, lead, "記事に詳しく書いています。", url]
    else:
        lines = [
            heading,
            lead,
            "KARiN.NOTESに記事を公開しました。考えかたや整え方は、記事の中で紹介しています。",
            url,
        ]
    return "\n\n".join(line for line in lines if line)


def clean_body(value):
    text = (value or "").replace("\r\n", "\n").strip()
    if not text:
        raise ValueError("投稿文を入力してください")
    if len(text) > 5000:
        raise ValueError("投稿文が長すぎます")
    return text


def clean_http_url(value):
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) > 2000:
        raise ValueError("リンクが長すぎます")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("リンクは http または https のURLにしてください")
    return text


def clean_image_ref(value):
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) > 2000:
        raise ValueError("画像の指定が長すぎます")
    if text.startswith(("https://", "http://", "/static/", "static/")):
        return text
    raise ValueError("画像は https のURLか、/static/ から始まるパスにしてください")


def _kept_receipt(existing):
    """保存し直しても、一度受け取った投稿IDと投稿日時は消さない。"""
    if not existing:
        return None, None
    external_id = existing.get("external_id")
    posted_at = existing.get("posted_at")
    if not isinstance(external_id, str) or not external_id.strip():
        external_id = None
    else:
        external_id = external_id.strip()
    if not isinstance(posted_at, str) or not posted_at.strip():
        posted_at = None
    return external_id, posted_at


def prepare_notes_save(existing, target, blog_id, body, link_url, image_url, staff_id, now):
    """保存用のフィールド。status は draft 固定。投稿済にはしない。"""
    if existing and existing.get("status") in LOCKED_STATUSES:
        return None, "投稿済み、送信中、または成否未確認の記録は、この画面からは変更しません。"
    external_id, posted_at = _kept_receipt(existing)
    fields = {
        "source_kind": "notes_article",
        "blog_id": str(blog_id),
        "service_key": None,
        "channel": target["channel"],
        "gbp_profile": target["gbp_profile"],
        "status": "draft",
        "body": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "angle_label": None,
        "external_id": external_id,
        "error_message": None,
        "posted_at": posted_at,
        "updated_at": now,
    }
    if not existing:
        fields["created_by"] = staff_id or None
        fields["created_at"] = now
    event = {
        "event": "edited",
        "body_snapshot": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "detail": "保存のみ。外部サービスへは投稿していません。",
        "actor_staff_id": staff_id or None,
        "created_at": now,
    }
    return {"fields": fields, "event": event, "is_insert": existing is None}, None


def prepare_notes_revision(existing, target, body, link_url, image_url, staff_id, now):
    """投稿済みGBPの文面更新。external_id は残し、状態は確認待ちに戻す。送信はしない。"""
    if not existing or not existing.get("id"):
        return None, "先に投稿文を保存してください。"
    if existing.get("status") != "posted":
        return None, "投稿済みの記録だけ、投稿IDを保持したまま内容を更新できます。"
    if target.get("channel") != "gbp":
        return None, "この投稿先の投稿済み記録は、この画面からは変更しません。"
    external_id, posted_at = _kept_receipt(existing)
    if not external_id:
        return None, "投稿IDがないため、投稿済みの内容は変更しません。"
    fields = {
        "source_kind": "notes_article",
        "blog_id": str(existing.get("blog_id")),
        "service_key": None,
        "channel": target["channel"],
        "gbp_profile": target["gbp_profile"],
        "status": "ready",
        "body": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "angle_label": None,
        "external_id": external_id,
        "error_message": None,
        "posted_at": posted_at,
        "updated_at": now,
    }
    event = {
        "event": "edited",
        "body_snapshot": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "detail": "投稿IDは保持しています。外部サービスへは投稿していません。",
        "actor_staff_id": staff_id or None,
        "created_at": now,
    }
    return {"fields": fields, "event": event, "is_insert": False}, None


def prepare_notes_confirm(existing, target, body, link_url, image_url, staff_id, now):
    """確認済みにする。Googleへは送らない。"""
    if not existing or not existing.get("id"):
        return None, "先に投稿文を保存してください。"
    if existing.get("status") in LOCKED_STATUSES:
        return None, "投稿済み、送信中、または成否未確認の記録は、この画面からは変更しません。"
    if target.get("channel") != "gbp":
        return None, "この投稿先は確認済にできません。"
    external_id, posted_at = _kept_receipt(existing)
    fields = {
        "source_kind": "notes_article",
        "blog_id": str(existing.get("blog_id")),
        "service_key": None,
        "channel": target["channel"],
        "gbp_profile": target["gbp_profile"],
        "status": "ready",
        "body": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "angle_label": None,
        "external_id": external_id,
        "error_message": None,
        "posted_at": posted_at,
        "updated_at": now,
    }
    event = {
        "event": "confirmed",
        "body_snapshot": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "detail": "確認のみ。外部サービスへは投稿していません。",
        "actor_staff_id": staff_id or None,
        "created_at": now,
    }
    return {"fields": fields, "event": event, "is_insert": False}, None


def _same_service_row(existing, area, service_key):
    return (
        existing.get("source_kind") == "service"
        and existing.get("channel") == "gbp"
        and existing.get("gbp_profile") == area
        and existing.get("service_key") == service_key
    )


def prepare_service_save(existing, area, service_key, body, link_url, image_url, staff_id, now):
    """サービス投稿の下書き保存。Googleへは送らない。"""
    screen, reason = resolve_service_screen(area, service_key)
    if reason:
        return None, reason
    if existing and not _same_service_row(existing, screen["area"], screen["service"]["key"]):
        return None, "別の地域・サービスの記録は変更しません。"
    if existing and existing.get("status") in LOCKED_STATUSES:
        return None, "投稿済み、送信中、または成否未確認の記録は、この画面からは変更しません。"
    external_id, posted_at = _kept_receipt(existing)
    fields = {
        "source_kind": "service",
        "blog_id": None,
        "service_key": screen["service"]["key"],
        "channel": "gbp",
        "gbp_profile": screen["gbp_profile"],
        "status": "draft",
        "body": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "angle_label": existing.get("angle_label") if existing else None,
        "external_id": external_id,
        "error_message": None,
        "posted_at": posted_at,
        "updated_at": now,
    }
    if not existing:
        fields["created_by"] = staff_id or None
        fields["created_at"] = now
    event = {
        "event": "edited",
        "body_snapshot": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "detail": "保存のみ。外部サービスへは投稿していません。",
        "actor_staff_id": staff_id or None,
        "created_at": now,
    }
    return {"fields": fields, "event": event, "is_insert": existing is None}, None


def prepare_service_confirm(existing, area, service_key, body, link_url, image_url, staff_id, now):
    """サービス投稿を確認済にする。Googleへは送らない。"""
    screen, reason = resolve_service_screen(area, service_key)
    if reason:
        return None, reason
    if not existing or not existing.get("id"):
        return None, "先に投稿文を保存してください。"
    if not _same_service_row(existing, screen["area"], screen["service"]["key"]):
        return None, "別の地域・サービスの記録は変更しません。"
    if existing.get("status") in LOCKED_STATUSES:
        return None, "投稿済み、送信中、または成否未確認の記録は、この画面からは変更しません。"
    external_id, posted_at = _kept_receipt(existing)
    fields = {
        "source_kind": "service",
        "blog_id": None,
        "service_key": screen["service"]["key"],
        "channel": "gbp",
        "gbp_profile": screen["gbp_profile"],
        "status": "ready",
        "body": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "angle_label": existing.get("angle_label"),
        "external_id": external_id,
        "error_message": None,
        "posted_at": posted_at,
        "updated_at": now,
    }
    event = {
        "event": "confirmed",
        "body_snapshot": body,
        "link_url": link_url or None,
        "image_url": image_url or None,
        "detail": "確認のみ。外部サービスへは投稿していません。",
        "actor_staff_id": staff_id or None,
        "created_at": now,
    }
    return {"fields": fields, "event": event, "is_insert": False}, None


def find_latest_service_post(client, service_key, area):
    res = (
        client.table("external_posts")
        .select("*")
        .eq("source_kind", "service")
        .eq("channel", "gbp")
        .eq("service_key", service_key)
        .eq("gbp_profile", area)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def find_notes_post(client, blog_id, target):
    query = (
        client.table("external_posts")
        .select("*")
        .eq("source_kind", "notes_article")
        .eq("blog_id", str(blog_id))
        .eq("channel", target["channel"])
    )
    if target["gbp_profile"]:
        query = query.eq("gbp_profile", target["gbp_profile"])
    else:
        query = query.is_("gbp_profile", "null")
    res = query.limit(1).execute()
    rows = res.data or []
    return rows[0] if rows else None


def list_post_events(client, post_id):
    if not post_id:
        return []
    res = (
        client.table("external_post_events")
        .select("id,event,detail,body_snapshot,created_at,actor_staff_id")
        .eq("external_post_id", post_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    events = []
    for row in res.data or []:
        item = dict(row)
        item["label"] = EVENT_LABELS.get(item.get("event"), item.get("event") or "")
        events.append(item)
    return events


def save_notes_post(client, existing, prepared):
    fields = prepared["fields"]
    if prepared["is_insert"]:
        res = client.table("external_posts").insert(fields).execute()
    else:
        query = client.table("external_posts").update(fields).eq("id", existing["id"])
        expected = existing.get("status")
        if expected:
            query = query.eq("status", expected)
        res = query.execute()
        if expected and not (res.data or []):
            raise ExternalPostConflict("状態が変わったため保存しませんでした。画面を開き直してください。")
    rows = res.data or []
    saved = rows[0] if rows else dict(existing or {})
    if not saved.get("id") and existing:
        saved["id"] = existing["id"]
    event = dict(prepared["event"])
    event["external_post_id"] = saved["id"]
    client.table("external_post_events").insert(event).execute()
    return saved


def update_notes_post_if_status(client, post_id, from_statuses, fields):
    """status を条件にした1回の UPDATE。0件なら、先に状態が変わっている。"""
    statuses = [status for status in from_statuses if status]
    query = client.table("external_posts").update(fields).eq("id", post_id)
    if len(statuses) == 1:
        query = query.eq("status", statuses[0])
    elif statuses:
        query = query.in_("status", statuses)
    res = query.execute()
    rows = res.data or []
    return rows[0] if rows else None


def insert_post_event(client, post_id, event):
    payload = dict(event)
    payload["external_post_id"] = post_id
    client.table("external_post_events").insert(payload).execute()


def service_status_map(client, area):
    """サービスごとの最新状態。取得失敗時はすべて未投稿。"""
    result = {item["key"]: None for item in GBP_SERVICE_CATALOG}
    try:
        res = (
            client.table("external_posts")
            .select("service_key,status,updated_at")
            .eq("source_kind", "service")
            .eq("channel", "gbp")
            .eq("gbp_profile", area)
            .execute()
        )
        latest = {}
        for row in res.data or []:
            key = row.get("service_key")
            if key not in result:
                continue
            prev = latest.get(key)
            stamp = row.get("updated_at") or ""
            if prev is None or stamp >= (prev.get("updated_at") or ""):
                latest[key] = row
        for key, row in latest.items():
            result[key] = row.get("status")
    except Exception as exc:
        print("❌ サービス投稿状態の取得エラー:", exc)
    return result


def publish_external_post(target_key, *, body, link_url=None, image_url=None):
    """STEP 1 / STEP 2 の送信口。

    いまは未接続。成功結果は返さない。ルートから呼ばない。
    """
    del body, link_url, image_url
    target = get_target(target_key)
    label = target["button_label"] if target else "外部投稿"
    raise ExternalPostNotConnected(f"{label} の投稿APIは未接続です")
