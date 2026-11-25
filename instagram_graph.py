"""KARiN.NOTES の Instagram フィード投稿（単一画像とカルーセル）。

Facebook と GBP は扱わない。このモジュールを読み込んだだけでは Meta へ送信しない。
Page Access Token は /me/accounts から取得し、システムユーザートークンは Instagram API に直接渡さない。
トークンは Authorization ヘッダーだけに置き、URL・ログ・例外文言には出さない。
"""

from __future__ import annotations

import os
import re
import struct
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import quote, unquote, urlparse, urlunparse

import requests

import meta_graph
from meta_graph import MetaGraphRefused, MetaGraphTimeout

GRAPH_VERSION = meta_graph.GRAPH_VERSION
GRAPH_HOST = meta_graph.GRAPH_HOST
REQUEST_TIMEOUT_SECONDS = 30
CONTAINER_WAIT_SECONDS = 60
CONTAINER_POLL_SECONDS = 2
CAPTION_MAX = 2200
CAROUSEL_MIN = 2
CAROUSEL_MAX = 10
PUBLIC_ORIGIN = "https://karin-sb.jp"
IG_MEDIA_PREFIX = "/ig-media/"
INSTAGRAM_SEND_STATUSES = frozenset({"draft", "ready", "failed", "posted", "unknown"})
_IG_ID = re.compile(r"^[0-9]{5,32}$")
_IG_MEDIA_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
_IMAGE_EXT = re.compile(r"\.(?:jpe?g)$", re.I)
_ASPECT_MIN = 0.8
_ASPECT_MAX = 1.91
_MIN_WIDTH = 320
_MAX_BYTES = 8 * 1024 * 1024
_ROOT = os.path.dirname(os.path.abspath(__file__))


def load_instagram_config(env=None):
    """Instagram投稿に使う値だけ読む。値は返すが、呼び出し側はログに出さない。"""
    source = env if env is not None else os.environ
    facebook = meta_graph.load_facebook_config(source)
    return {
        "access_token": facebook["access_token"],
        "page_id": facebook["page_id"],
        "ig_user_id": (source.get("INSTAGRAM_BUSINESS_ACCOUNT_ID") or "").strip(),
    }


def missing_instagram_env(config):
    missing = list(meta_graph.missing_facebook_env(config))
    if not (config.get("ig_user_id") or "").strip():
        missing.append("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    return missing


def public_instagram_image_url(value):
    """保存値を Instagram が取得できる https URL にする。表示用パスは変えない。"""
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("https://"):
        url = text
    elif text.startswith("http://"):
        rest = text[len("http://") :]
        if rest == "karin-sb.jp" or rest.startswith("karin-sb.jp/"):
            url = "https://" + rest
        else:
            return ""
    elif text.startswith("/static/"):
        url = PUBLIC_ORIGIN + text
    elif text.startswith("static/"):
        url = PUBLIC_ORIGIN + "/" + text
    else:
        return ""
    return _encode_image_url(url)


def instagram_graph_image_url(value):
    """Instagram API に渡す取得URL。日本語ファイル名は ASCII の /ig-media/ にする。"""
    public = public_instagram_image_url(value)
    if not public:
        return ""
    path = unquote(urlparse(public).path or "")
    if path.isascii():
        return public
    token = ig_media_token_from_static_path(path)
    if not token:
        return ""
    return f"{PUBLIC_ORIGIN}{IG_MEDIA_PREFIX}{token}.jpg"


def ig_media_token_from_static_path(path):
    text = (path or "").strip()
    if not _safe_static_jpeg_path(text):
        return ""
    return urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def static_path_from_ig_media_token(token):
    raw = (token or "").strip()
    if not raw or not _IG_MEDIA_TOKEN.fullmatch(raw):
        return ""
    pad = "=" * ((4 - len(raw) % 4) % 4)
    try:
        decoded = urlsafe_b64decode(raw + pad).decode("utf-8")
    except Exception:
        return ""
    if not _safe_static_jpeg_path(decoded):
        return ""
    return decoded


def local_path_from_ig_media_token(token):
    path = static_path_from_ig_media_token(token)
    if not path:
        return None
    return _local_static_path(PUBLIC_ORIGIN + path)


def _safe_static_jpeg_path(path):
    text = (path or "").strip()
    if not text.startswith("/static/") or ".." in text:
        return False
    if text != os.path.normpath(text).replace("\\", "/"):
        return False
    return bool(_IMAGE_EXT.search(text))


def instagram_image_urls(value):
    """保存値を公開httpsのJPEG URLリストにする。1枚の既存保存も読む。"""
    import external_posts

    return external_posts.parse_instagram_image_urls(value)


def instagram_preview(body, image_url):
    """送信JSONは作らない。画面確認用。Metaへは送らない。"""
    errors = []
    caption = (body or "").replace("\r\n", "\n").strip()
    if not caption:
        errors.append("投稿文を入力してください")
    elif len(caption) > CAPTION_MAX:
        errors.append("投稿文は2200文字以内にしてください")
    urls = instagram_image_urls(image_url)
    if not urls:
        errors.append("画像は公開された https のJPEGにしてください")
    elif len(urls) > CAROUSEL_MAX:
        errors.append("Instagramの画像は10枚以内にしてください")
    for image in urls:
        errors.extend(_image_constraint_errors(image))
    image = urls[0] if urls else ""
    if errors:
        return {
            "ok": False,
            "errors": errors,
            "payload_text": "",
            "caption": caption,
            "image_url": image,
            "image_urls": urls,
        }
    if len(urls) == 1:
        payload_text = f"caption:\n{caption}\n\nimage_url:\n{image}"
    else:
        listed = "\n".join(f"{index}. {url}" for index, url in enumerate(urls, start=1))
        payload_text = (
            f"caption:\n{caption}\n\nmedia_type: CAROUSEL\nimage_url:\n{listed}"
        )
    return {
        "ok": True,
        "errors": [],
        "payload_text": payload_text,
        "caption": caption,
        "image_url": image,
        "image_urls": urls,
    }


def build_instagram_media_payload(body, image_url):
    preview = instagram_preview(body, image_url)
    if not preview["ok"]:
        raise MetaGraphRefused(preview["errors"][0])
    urls = preview.get("image_urls") or []
    if len(urls) != 1:
        raise MetaGraphRefused("単一画像の送信処理は1枚のときだけ使います。")
    image = instagram_graph_image_url(preview["image_url"])
    if not image:
        raise MetaGraphRefused("画像は公開された https のJPEGにしてください")
    return {
        "image_url": image,
        "caption": preview["caption"],
        "media_type": "IMAGE",
    }


def build_instagram_child_payload(image_url):
    image = public_instagram_image_url(image_url)
    if not image:
        raise MetaGraphRefused("画像は公開された https のJPEGにしてください")
    errors = _image_constraint_errors(image)
    if errors:
        raise MetaGraphRefused(errors[0])
    fetch_url = instagram_graph_image_url(image)
    if not fetch_url:
        raise MetaGraphRefused("画像は公開された https のJPEGにしてください")
    return {
        "image_url": fetch_url,
        "is_carousel_item": "true",
        "media_type": "IMAGE",
    }


def build_instagram_carousel_payload(body, child_ids):
    caption = (body or "").replace("\r\n", "\n").strip()
    if not caption:
        raise MetaGraphRefused("投稿文を入力してください")
    if len(caption) > CAPTION_MAX:
        raise MetaGraphRefused("投稿文は2200文字以内にしてください")
    children = [item.strip() for item in child_ids if (item or "").strip()]
    if len(children) < CAROUSEL_MIN or len(children) > CAROUSEL_MAX:
        raise MetaGraphRefused("カルーセルは2〜10枚の画像が必要です。")
    for item in children:
        if not _IG_ID.fullmatch(item):
            raise MetaGraphRefused("作成中の画像IDが不正なため、送信しません。")
    return {
        "media_type": "CAROUSEL",
        "children": ",".join(children),
        "caption": caption,
    }


def instagram_media_url(ig_user_id):
    user = (ig_user_id or "").strip()
    if not _IG_ID.fullmatch(user):
        raise MetaGraphRefused("InstagramアカウントIDが不正なため、送信しません。")
    return f"{GRAPH_HOST}/{GRAPH_VERSION}/{user}/media"


def instagram_publish_url(ig_user_id):
    user = (ig_user_id or "").strip()
    if not _IG_ID.fullmatch(user):
        raise MetaGraphRefused("InstagramアカウントIDが不正なため、送信しません。")
    return f"{GRAPH_HOST}/{GRAPH_VERSION}/{user}/media_publish"


def instagram_container_url(creation_id):
    value = (creation_id or "").strip()
    if not _IG_ID.fullmatch(value):
        raise MetaGraphRefused("作成中の画像IDが不正なため、送信しません。")
    return f"{GRAPH_HOST}/{GRAPH_VERSION}/{value}"


def can_send_instagram_record(record):
    if not record or not record.get("id"):
        return False, "保存したInstagramだけ送信できます。"
    if record.get("channel") != "instagram":
        return False, "Instagramの保存内容だけ送信できます。"
    status = record.get("status")
    if status == "posting":
        return False, "送信中です。重なって送信しません。"
    if status not in INSTAGRAM_SEND_STATUSES:
        return False, "この状態からは投稿できません。"
    return True, None


def begin_notes_instagram_create(record, now):
    allowed, reason = can_send_instagram_record(record)
    if not allowed:
        return None, reason
    previous_id = (record.get("external_id") or "").strip() or None
    detail = "送信を開始しました。成功を確認するまで投稿済にはしません。"
    if previous_id:
        detail = f"{detail} 前回のInstagram投稿ID: {previous_id}"
    return {
        "fields": {
            "status": "posting",
            "error_message": None,
            "updated_at": now,
        },
        "event": {
            "event": "submit_started",
            "body_snapshot": record.get("body") or "",
            "link_url": record.get("link_url") or None,
            "image_url": record.get("image_url") or None,
            "detail": detail,
            "created_at": now,
        },
        "previous_id": previous_id,
    }, None


def finish_notes_instagram_create(record, *, http_status, body, timed_out, now):
    """公開IDがある200だけ posted。4xxは failed。5xx・タイムアウト・IDなしは unknown。"""
    previous_id, previous_at = _kept_instagram_receipt(record)
    if timed_out or http_status is None or http_status >= 500:
        return _outcome(
            record,
            status="unknown",
            external_id=previous_id,
            posted_at=previous_at,
            error_message="結果不明。自動再送しません。",
            event="unknown",
            detail="結果不明。自動再送しません。Instagram側で投稿の有無を確認してください。",
            now=now,
        )
    if http_status == 200:
        media_id = _instagram_media_id(body)
        if media_id:
            return _outcome(
                record,
                status="posted",
                external_id=media_id,
                posted_at=now,
                error_message=None,
                event="succeeded",
                detail=f"投稿成功を確認しました。Instagram投稿ID: {media_id}",
                now=now,
            )
        return _outcome(
            record,
            status="unknown",
            external_id=previous_id,
            posted_at=previous_at,
            error_message="応答に投稿IDがありません。",
            event="unknown",
            detail="投稿IDを確認できないため、投稿済にしていません。自動では再送しません。",
            now=now,
        )
    if 400 <= http_status < 500:
        message = _instagram_error_text(body, http_status)
        return _outcome(
            record,
            status="failed",
            external_id=previous_id,
            posted_at=previous_at,
            error_message=message,
            event="failed",
            detail=message,
            now=now,
        )
    return _outcome(
        record,
        status="unknown",
        external_id=previous_id,
        posted_at=previous_at,
        error_message="結果不明。自動再送しません。",
        event="unknown",
        detail="結果不明。自動再送しません。",
        now=now,
    )


def wait_instagram_container(
    creation_id,
    *,
    get_exchange,
    access_token,
    sleep_fn=None,
    max_wait_seconds=CONTAINER_WAIT_SECONDS,
    poll_interval_seconds=CONTAINER_POLL_SECONDS,
):
    """FINISHED まで確認する。ERROR は失敗。時間切れはタイムアウト。自動再送しない。"""
    waiter = sleep_fn or time.sleep
    url = instagram_container_url(creation_id)
    started = time.monotonic()
    while True:
        try:
            http_status, body = get_exchange(
                url,
                access_token=access_token,
                params={"fields": "status_code"},
            )
        except MetaGraphTimeout:
            raise
        except MetaGraphRefused:
            raise
        except Exception:
            raise MetaGraphTimeout() from None
        if http_status is None or http_status >= 500:
            raise MetaGraphTimeout()
        if 400 <= http_status < 500:
            raise MetaGraphRefused(_instagram_error_text(body, http_status))
        code = ""
        if isinstance(body, dict):
            code = str(body.get("status_code") or "").strip().upper()
        if code in {"FINISHED", "PUBLISHED"}:
            return body
        if code == "ERROR":
            raise MetaGraphRefused("Instagramが画像の処理に失敗しました。")
        if code == "EXPIRED":
            raise MetaGraphRefused("画像の処理期限が切れたため、送信しません。")
        elapsed = time.monotonic() - started
        if elapsed >= max_wait_seconds:
            raise MetaGraphTimeout()
        wait_for = min(poll_interval_seconds, max(0, max_wait_seconds - elapsed))
        if wait_for > 0:
            waiter(wait_for)
        if time.monotonic() - started >= max_wait_seconds:
            raise MetaGraphTimeout()


def fetch_instagram_page_token(config, *, get_exchange):
    """システムユーザートークンで /me/accounts し、Page トークンだけ返す。Instagram API にはまだ送らない。"""
    if missing_instagram_env(config):
        raise MetaGraphRefused("Instagram投稿の設定が不足しているため、送信しません。")
    page_id = (config.get("page_id") or "").strip()
    system_token = (config.get("access_token") or "").strip()
    try:
        http_status, body = get_exchange(
            meta_graph.facebook_accounts_url(),
            access_token=system_token,
            params={"fields": "id,access_token"},
        )
    except MetaGraphTimeout:
        raise MetaGraphRefused(
            "対象のFacebookページの投稿トークンを取得できませんでした。Instagramへは送っていません。"
        ) from None
    except MetaGraphRefused:
        raise
    except Exception:
        raise MetaGraphRefused(
            "対象のFacebookページの投稿トークンを取得できませんでした。Instagramへは送っていません。"
        ) from None
    if http_status != 200:
        raise MetaGraphRefused(
            f"対象のFacebookページの投稿トークンを取得できませんでした HTTP {http_status}。"
            " pages_read_engagement を確認してください。"
        )
    return meta_graph.select_page_access_token(body, page_id)


def _post_media_container(post_exchange, url, page_token, payload, outgoing, now):
    """1つのメディアコンテナを作る。成功時はID、失敗時は保存用outcome。"""
    try:
        http_status, response = post_exchange(url, access_token=page_token, body=payload)
        timed_out = False
    except MetaGraphTimeout:
        http_status, response, timed_out = None, {}, True
    except Exception:
        print("Instagram投稿 error=Exception")
        http_status, response, timed_out = None, {}, True
    if timed_out or http_status is None or http_status >= 500:
        finished = finish_notes_instagram_create(
            outgoing, http_status=http_status, body=response, timed_out=True, now=now
        )
        return None, finished, http_status
    if http_status != 200:
        finished = finish_notes_instagram_create(
            outgoing, http_status=http_status, body=response, timed_out=False, now=now
        )
        return None, finished, http_status
    creation_id = _instagram_media_id(response)
    if not creation_id:
        finished = finish_notes_instagram_create(
            outgoing, http_status=200, body={}, timed_out=False, now=now
        )
        return None, finished, http_status
    return creation_id, None, http_status


def _wait_media_container(
    creation_id,
    *,
    get_exchange,
    page_token,
    sleep_fn,
    max_wait_seconds,
    poll_interval_seconds,
    outgoing,
    now,
):
    try:
        wait_instagram_container(
            creation_id,
            get_exchange=get_exchange,
            access_token=page_token,
            sleep_fn=sleep_fn,
            max_wait_seconds=max_wait_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except MetaGraphRefused as exc:
        previous_id, previous_at = _kept_instagram_receipt(outgoing)
        return _outcome(
            outgoing,
            status="failed",
            external_id=previous_id,
            posted_at=previous_at,
            error_message=exc.detail,
            event="failed",
            detail=exc.detail,
            now=now,
        )
    except (MetaGraphTimeout, Exception):
        return finish_notes_instagram_create(
            outgoing, http_status=None, body={}, timed_out=True, now=now
        )
    return None


def _publish_media_container(post_exchange, publish_url, page_token, creation_id, outgoing, now):
    try:
        http_status, response = post_exchange(
            publish_url,
            access_token=page_token,
            body={"creation_id": creation_id},
        )
        timed_out = False
    except MetaGraphTimeout:
        http_status, response, timed_out = None, {}, True
    except Exception:
        print("Instagram投稿 error=Exception")
        http_status, response, timed_out = None, {}, True
    finished = finish_notes_instagram_create(
        outgoing,
        http_status=http_status,
        body=response,
        timed_out=timed_out,
        now=now,
    )
    return finished, http_status


def _store_logged_outcome(client, outgoing, finished, now, *, http_status, staff_id, post_store):
    _log_instagram_outcome(http_status, finished)
    return _store_outcome(client, outgoing, finished, now, staff_id=staff_id, post_store=post_store)


def perform_notes_instagram_create(
    client,
    record,
    *,
    config,
    post_exchange,
    now,
    staff_id=None,
    post_store=None,
    accounts_exchange=None,
    get_exchange=None,
    sleep_fn=None,
    max_wait_seconds=CONTAINER_WAIT_SECONDS,
    poll_interval_seconds=CONTAINER_POLL_SECONDS,
):
    """保存済みInstagramだけ投稿する。コンテナ作成だけでは成功にしない。"""
    store = _post_store(post_store)
    accounts = accounts_exchange or meta_graph.facebook_accounts_exchange
    getter = get_exchange or instagram_get_exchange
    allowed, reason = can_send_instagram_record(record)
    if not allowed:
        return _flow(False, record, reason)
    missing = missing_instagram_env(config)
    if missing:
        return _flow(False, record, "Instagram投稿の設定が不足しているため、送信しません。")
    try:
        media_url = instagram_media_url(config.get("ig_user_id"))
        publish_url = instagram_publish_url(config.get("ig_user_id"))
        preview = instagram_preview(record.get("body"), record.get("image_url"))
        if not preview["ok"]:
            raise MetaGraphRefused(preview["errors"][0])
        urls = preview.get("image_urls") or []
        if len(urls) == 1:
            payloads = [build_instagram_media_payload(record.get("body"), urls[0])]
        elif CAROUSEL_MIN <= len(urls) <= CAROUSEL_MAX:
            payloads = [build_instagram_child_payload(url) for url in urls]
        else:
            raise MetaGraphRefused("Instagramの画像は1〜10枚にしてください")
        page_token = fetch_instagram_page_token(config, get_exchange=accounts)
    except MetaGraphRefused as exc:
        return _record_unsent_failure(
            client, record, exc.detail, now, staff_id=staff_id, post_store=store
        )

    begun, reason = begin_notes_instagram_create(record, now)
    if reason:
        return _flow(False, record, reason)
    try:
        claimed = store["update_if_status"](
            client,
            record["id"],
            tuple(INSTAGRAM_SEND_STATUSES),
            begun["fields"],
        )
    except Exception:
        return _flow(False, record, "送信開始を保存できなかったため、Instagramへは送っていません。")
    if not claimed:
        return _flow(False, record, "他の操作が先に状態を変えたため、送信しません。")
    outgoing = dict(claimed)
    outgoing["body"] = record.get("body")
    outgoing["link_url"] = record.get("link_url")
    outgoing["image_url"] = record.get("image_url")
    outgoing["external_id"] = record.get("external_id")
    outgoing["posted_at"] = record.get("posted_at")
    try:
        event = dict(begun["event"])
        event["actor_staff_id"] = staff_id or None
        store["insert_event"](client, claimed["id"], event)
    except Exception:
        return _flow(
            False,
            claimed,
            "送信開始の記録に失敗したため、Instagramへは送っていません。再送せず、結果を確認してください。",
        )

    wait_kwargs = {
        "get_exchange": getter,
        "page_token": page_token,
        "sleep_fn": sleep_fn,
        "max_wait_seconds": max_wait_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "outgoing": outgoing,
        "now": now,
    }
    if len(urls) == 1:
        creation_id, finished, http_status = _post_media_container(
            post_exchange, media_url, page_token, payloads[0], outgoing, now
        )
        if finished:
            return _store_logged_outcome(
                client, outgoing, finished, now, http_status=http_status, staff_id=staff_id, post_store=store
            )
        finished = _wait_media_container(creation_id, **wait_kwargs)
        if finished:
            return _store_logged_outcome(
                client, outgoing, finished, now, http_status=None, staff_id=staff_id, post_store=store
            )
        finished, http_status = _publish_media_container(
            post_exchange, publish_url, page_token, creation_id, outgoing, now
        )
        return _store_logged_outcome(
            client, outgoing, finished, now, http_status=http_status, staff_id=staff_id, post_store=store
        )

    child_ids = []
    for payload in payloads:
        creation_id, finished, http_status = _post_media_container(
            post_exchange, media_url, page_token, payload, outgoing, now
        )
        if finished:
            return _store_logged_outcome(
                client, outgoing, finished, now, http_status=http_status, staff_id=staff_id, post_store=store
            )
        finished = _wait_media_container(creation_id, **wait_kwargs)
        if finished:
            return _store_logged_outcome(
                client, outgoing, finished, now, http_status=None, staff_id=staff_id, post_store=store
            )
        child_ids.append(creation_id)

    try:
        parent_payload = build_instagram_carousel_payload(record.get("body"), child_ids)
    except MetaGraphRefused as exc:
        previous_id, previous_at = _kept_instagram_receipt(outgoing)
        finished = _outcome(
            outgoing,
            status="failed",
            external_id=previous_id,
            posted_at=previous_at,
            error_message=exc.detail,
            event="failed",
            detail=exc.detail,
            now=now,
        )
        return _store_logged_outcome(
            client, outgoing, finished, now, http_status=None, staff_id=staff_id, post_store=store
        )
    parent_id, finished, http_status = _post_media_container(
        post_exchange, media_url, page_token, parent_payload, outgoing, now
    )
    if finished:
        return _store_logged_outcome(
            client, outgoing, finished, now, http_status=http_status, staff_id=staff_id, post_store=store
        )
    finished = _wait_media_container(parent_id, **wait_kwargs)
    if finished:
        return _store_logged_outcome(
            client, outgoing, finished, now, http_status=None, staff_id=staff_id, post_store=store
        )
    finished, http_status = _publish_media_container(
        post_exchange, publish_url, page_token, parent_id, outgoing, now
    )
    return _store_logged_outcome(
        client, outgoing, finished, now, http_status=http_status, staff_id=staff_id, post_store=store
    )


def instagram_post_exchange(url, *, access_token, body, timeout=REQUEST_TIMEOUT_SECONDS):
    """トークンはヘッダーだけ。クエリにも本文にも入れない。"""
    token = (access_token or "").strip()
    if not token:
        raise MetaGraphRefused("Instagram投稿の設定が不足しているため、送信しません。")
    if "access_token=" in (url or "").lower():
        raise MetaGraphRefused("送信先が不正なため、Instagramへは送りません。")
    try:
        response = requests.post(
            url,
            data=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.Timeout:
        raise MetaGraphTimeout() from None
    except requests.RequestException:
        raise MetaGraphTimeout() from None
    return response.status_code, _parse_graph_json(response)


def instagram_get_exchange(url, *, access_token, params=None, timeout=REQUEST_TIMEOUT_SECONDS):
    """Page トークンでコンテナ状態を取る。トークンはヘッダーだけ。"""
    token = (access_token or "").strip()
    if not token:
        raise MetaGraphRefused("Instagram投稿の設定が不足しているため、送信しません。")
    if "access_token=" in (url or "").lower():
        raise MetaGraphRefused("送信先が不正なため、Instagramへは送りません。")
    query = dict(params or {})
    if "access_token" in query:
        raise MetaGraphRefused("送信先が不正なため、Instagramへは送りません。")
    try:
        response = requests.get(
            url,
            params=query,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.Timeout:
        raise MetaGraphTimeout() from None
    except requests.RequestException:
        raise MetaGraphTimeout() from None
    return response.status_code, _parse_graph_json(response)


def _encode_image_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    path = quote(unquote(parsed.path or ""), safe="/")
    return urlunparse(("https", parsed.netloc, path, "", parsed.query, ""))


def _image_constraint_errors(url):
    errors = []
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    if not _IMAGE_EXT.search(path):
        errors.append("画像はJPEGにしてください")
        return errors
    local = _local_static_path(url)
    if not local:
        return errors
    try:
        if os.path.getsize(local) > _MAX_BYTES:
            errors.append("画像が大きすぎるため、Instagramへは送れません")
            return errors
        size = _jpeg_size(local)
    except Exception:
        errors.append("画像はJPEGにしてください")
        return errors
    if not size:
        errors.append("画像はJPEGにしてください")
        return errors
    width, height = size
    if width < _MIN_WIDTH:
        errors.append("画像が小さすぎるため、Instagramへは送れません")
        return errors
    ratio = width / height if height else 0
    if ratio < _ASPECT_MIN or ratio > _ASPECT_MAX:
        errors.append("画像の縦横比がInstagramの通常投稿に合いません")
    return errors


def inspect_instagram_image(url):
    """サイト内のJPEGだけ寸法を見る。JPEGでなければ None。"""
    path = _local_static_path(url)
    if not path:
        return None
    try:
        return _jpeg_size(path)
    except Exception:
        return None


def _local_static_path(url):
    parsed = urlparse(url)
    if parsed.netloc != "karin-sb.jp":
        return None
    rel = unquote(parsed.path or "")
    if not rel.startswith("/static/") or ".." in rel:
        return None
    candidate = os.path.normpath(os.path.join(_ROOT, rel.lstrip("/")))
    static_root = os.path.normpath(os.path.join(_ROOT, "static"))
    if candidate != static_root and not candidate.startswith(static_root + os.sep):
        return None
    if not os.path.isfile(candidate):
        return None
    return candidate


def _jpeg_size(path):
    with open(path, "rb") as handle:
        header = handle.read(2)
        if header != b"\xff\xd8":
            return None
        data = header + handle.read()
    index = 0
    while index < len(data) - 8:
        if data[index] == 0xFF and data[index + 1] in (0xC0, 0xC1, 0xC2):
            height = struct.unpack(">H", data[index + 5 : index + 7])[0]
            width = struct.unpack(">H", data[index + 7 : index + 9])[0]
            return width, height
        index += 1
    return None


def _parse_graph_json(response):
    parsed = {}
    try:
        parsed = response.json()
    except ValueError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed


def _record_unsent_failure(client, record, detail, now, staff_id=None, post_store=None):
    """トークンや画像が送れないなど、Instagramへ送る前の失敗。unknown にはしない。"""
    message = (detail or "").strip() or "Instagramへは送っていません。"
    if "Instagramへは送っていません" not in message:
        message = f"{message} Instagramへは送っていません。"
    previous_id, previous_at = _kept_instagram_receipt(record)
    outcome = _outcome(
        record,
        status="failed",
        external_id=previous_id,
        posted_at=previous_at,
        error_message=message,
        event="failed",
        detail=message,
        now=now,
    )
    return _store_outcome(
        client,
        record,
        outcome,
        now,
        from_statuses=tuple(INSTAGRAM_SEND_STATUSES),
        staff_id=staff_id,
        post_store=post_store,
    )


def _instagram_media_id(body):
    if not isinstance(body, dict):
        return None
    value = body.get("id")
    if isinstance(value, int) and value > 0:
        value = str(value)
    if isinstance(value, str) and _IG_ID.fullmatch(value.strip()):
        return value.strip()
    return None


def _instagram_error_text(body, http_status):
    raw = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        raw = body["error"].get("message") or ""
    cleaned = meta_graph.sanitize_meta_error_message(raw) if raw else None
    if cleaned:
        return f"投稿失敗 HTTP {http_status} {cleaned}".strip()
    return f"投稿失敗 HTTP {http_status}"


def _log_instagram_outcome(http_status, finished):
    fields = (finished or {}).get("fields") or {}
    status = fields.get("status") or ""
    error_message = meta_graph.sanitize_meta_error_message(fields.get("error_message") or "")
    parts = [f"Instagram投稿 HTTP {http_status}", f"status={status}"]
    if error_message:
        parts.append(f"error_message={error_message}")
    print(" ".join(parts))


def _kept_instagram_receipt(record):
    """再投稿が成功するまで、前回の投稿IDと投稿日時は消さない。"""
    if not record:
        return None, None
    external_id = record.get("external_id")
    posted_at = record.get("posted_at")
    if not isinstance(external_id, str) or not external_id.strip():
        external_id = None
    else:
        external_id = external_id.strip()
    if not isinstance(posted_at, str) or not posted_at.strip():
        posted_at = None
    return external_id, posted_at


def _outcome(record, *, status, error_message, event, detail, now, external_id=None, posted_at=None):
    return {
        "fields": {
            "status": status,
            "external_id": external_id,
            "posted_at": posted_at,
            "error_message": error_message,
            "updated_at": now,
        },
        "event": {
            "event": event,
            "body_snapshot": record.get("body") or "",
            "link_url": record.get("link_url") or None,
            "image_url": record.get("image_url") or None,
            "detail": detail,
            "created_at": now,
        },
    }


def _flow(ok, record, message):
    return {"ok": ok, "record": record, "message": message}


def _post_store(store):
    if store:
        return store
    import external_posts

    return {
        "update_if_status": external_posts.update_notes_post_if_status,
        "insert_event": external_posts.insert_post_event,
    }


def _store_outcome(client, record, outcome, now, from_statuses=("posting",), staff_id=None, post_store=None):
    store = _post_store(post_store)
    event = dict(outcome["event"])
    event["actor_staff_id"] = staff_id or None
    try:
        saved = store["update_if_status"](
            client, record["id"], from_statuses, outcome["fields"]
        )
    except Exception:
        return _flow(False, record, "通信後に状態を保存できませんでした。自動では再送しません。結果を確認してください。")
    if not saved:
        return _flow(False, record, "通信後に状態を保存できませんでした。自動では再送しません。結果を確認してください。")
    try:
        store["insert_event"](client, saved["id"], event)
    except Exception:
        return _flow(True, saved, "状態は保存しました。履歴の記録に失敗しました。自動では再送しません。")
    status = saved.get("status")
    if status == "posted":
        message = "投稿成功を確認しました。"
    elif status == "unknown":
        message = "結果不明。自動再送しません。"
    elif status == "failed":
        message = saved.get("error_message") or "投稿に失敗しました。自動では再送しません。"
    else:
        message = "状態を保存しました。自動では再送しません。"
    return _flow(status == "posted", saved, message)
