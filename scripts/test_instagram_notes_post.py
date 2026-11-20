#!/usr/bin/env python3
"""KARiN.NOTES の Instagram 投稿。Meta API へは送らない。"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app as appmod
import external_posts
import instagram_graph
from meta_graph import MetaGraphTimeout

FAILED = 0
PASSED = 0
NOW = "2026-11-20T13:00:00+09:00"
TOKEN = "EAAtestsecretvalue000000000000"
PAGE_TOKEN = "EAApageaccesssecretvalue0000000"
PAGE_ID = "61595470022494"
IG_USER = "17841400000000000"
CREATION_ID = "17890000000000001"
MEDIA_ID = "17890000000000099"
MEDIA_ID_NEW = "17890000000000100"
IMAGE = "/static/images/notes/a.jpg"
PUBLIC_IMAGE = "https://karin-sb.jp/static/images/notes/a.jpg"


def report(ok, name, detail=""):
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name} {detail}")


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, db):
        self.db = db
        self.filters = []
        self.op = None
        self.payload = None

    def update(self, fields):
        self.op = "update"
        self.payload = dict(fields)
        return self

    def insert(self, fields):
        self.op = "insert"
        self.payload = dict(fields)
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def in_(self, key, values):
        self.filters.append(("in", key, list(values)))
        return self

    def execute(self):
        if self.op == "insert":
            self.db.events.append(dict(self.payload))
            return Result([dict(self.payload)])
        if self.op != "update":
            raise AssertionError(self.op)
        for kind, key, value in self.filters:
            current = self.db.row.get(key)
            if kind == "eq" and current != value:
                return Result([])
            if kind == "in" and current not in value:
                return Result([])
        self.db.row.update(self.payload)
        self.db.updates.append(dict(self.payload))
        return Result([dict(self.db.row)])


class FakeDB:
    def __init__(self, row):
        self.row = dict(row)
        self.events = []
        self.updates = []

    def table(self, name):
        return Query(self)


def _assert_no_secret(url, body=None):
    text = url or ""
    if TOKEN in text or PAGE_TOKEN in text:
        raise AssertionError("secret in url")
    if "access_token=" in text.lower():
        raise AssertionError("token query")
    if body and "access_token" in body:
        raise AssertionError("token in body")


class AccountsHttp:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []

    def __call__(self, url, *, access_token, params=None):
        self.calls.append({"url": url, "params": dict(params or {}), "token": access_token})
        _assert_no_secret(url)
        if access_token != TOKEN:
            raise AssertionError("accounts must use system token")
        if self.mode == "timeout":
            raise MetaGraphTimeout()
        if self.mode == "denied":
            return 403, {"error": {"message": f"Bearer {TOKEN}", "code": 200}}
        if self.mode == "empty":
            return 200, {"data": []}
        if self.mode == "other_page":
            return 200, {"data": [{"id": "999999", "access_token": PAGE_TOKEN}]}
        if "/me/accounts" not in (url or ""):
            raise AssertionError("accounts url")
        return 200, {"data": [{"id": PAGE_ID, "access_token": PAGE_TOKEN}]}


class MediaHttp:
    def __init__(self, create="ok", publish="ok", create_id=CREATION_ID, media_id=MEDIA_ID):
        self.create = create
        self.publish = publish
        self.create_id = create_id
        self.media_id = media_id
        self.calls = []
        self.last_create = None
        self.last_publish = None

    def __call__(self, url, *, access_token, body):
        self.calls.append({"url": url, "body": dict(body or {})})
        _assert_no_secret(url, body)
        if access_token != PAGE_TOKEN:
            raise AssertionError("instagram must use page token")
        if url.endswith("/media_publish"):
            self.last_publish = dict(body or {})
            return self._publish()
        if url.endswith("/media"):
            self.last_create = dict(body or {})
            return self._create()
        raise AssertionError("unexpected post url")

    def _create(self):
        if self.create == "timeout":
            raise MetaGraphTimeout()
        if self.create == "server":
            return 500, {"error": {"message": f"Bearer {PAGE_TOKEN}", "code": 1}}
        if self.create == "denied":
            return 403, {"error": {"message": f"Invalid OAuth access token {PAGE_TOKEN}", "code": 190}}
        if self.create == "noid":
            return 200, {"success": True}
        return 200, {"id": self.create_id}

    def _publish(self):
        if self.publish == "timeout":
            raise MetaGraphTimeout()
        if self.publish == "server":
            return 500, {"error": {"message": f"Bearer {PAGE_TOKEN}", "code": 1}}
        if self.publish == "denied":
            return 400, {"error": {"message": f"Invalid OAuth access token {PAGE_TOKEN}", "code": 190}}
        if self.publish == "noid":
            return 200, {"success": True}
        if self.publish == "skip":
            raise AssertionError("publish should not be called")
        return 200, {"id": self.media_id}


class StatusHttp:
    def __init__(self, mode="FINISHED"):
        self.mode = mode
        self.calls = []

    def __call__(self, url, *, access_token, params=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        _assert_no_secret(url)
        if access_token != PAGE_TOKEN:
            raise AssertionError("status must use page token")
        if CREATION_ID not in (url or ""):
            raise AssertionError("status url")
        if self.mode == "timeout":
            raise MetaGraphTimeout()
        if self.mode == "IN_PROGRESS":
            return 200, {"status_code": "IN_PROGRESS"}
        if self.mode == "ERROR":
            return 200, {"status_code": "ERROR"}
        if self.mode == "denied":
            return 400, {"error": {"message": f"Bearer {PAGE_TOKEN}"}}
        return 200, {"status_code": "FINISHED"}


def sample_record(**overrides):
    row = {
        "id": "ig-1",
        "source_kind": "notes_article",
        "blog_id": "12",
        "channel": "instagram",
        "gbp_profile": None,
        "status": "draft",
        "body": "KARiN.NOTESの記事です。\nhttps://karin-sb.jp/blog/sample",
        "link_url": "https://karin-sb.jp/blog/sample",
        "image_url": IMAGE,
        "external_id": None,
        "posted_at": None,
        "error_message": None,
    }
    row.update(overrides)
    return row


def sample_config(**overrides):
    config = {
        "access_token": TOKEN,
        "page_id": PAGE_ID,
        "ig_user_id": IG_USER,
    }
    config.update(overrides)
    return config


def secrets_absent(*texts):
    blob = "\n".join(text or "" for text in texts)
    return TOKEN not in blob and PAGE_TOKEN not in blob and "EAAtest" not in blob and "EAApage" not in blob


def run_create(record, post_http, *, config=None, accounts=None, status=None, **kwargs):
    db = FakeDB(record)
    accounts_http = accounts if accounts is not None else AccountsHttp("ok")
    status_http = status if status is not None else StatusHttp("FINISHED")
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        result = instagram_graph.perform_notes_instagram_create(
            db,
            record,
            config=config or sample_config(),
            post_exchange=post_http,
            accounts_exchange=accounts_http,
            get_exchange=status_http,
            now=NOW,
            staff_id="staff-1",
            sleep_fn=lambda _: None,
            max_wait_seconds=kwargs.get("max_wait_seconds", 0),
            poll_interval_seconds=kwargs.get("poll_interval_seconds", 2),
        )
    log = stdout.getvalue()
    if not secrets_absent(log):
        raise AssertionError("secret in log")
    stored = " ".join(
        [
            str(db.row.get("error_message") or ""),
            " ".join(str(item.get("detail") or "") for item in db.events),
        ]
    )
    if not secrets_absent(stored):
        raise AssertionError("secret in db")
    return result, db, log, accounts_http, status_http


def test_caption_and_images():
    article_url = "https://karin-sb.jp/blog/kata"
    ig_text = external_posts.starter_body(
        "instagram",
        "肩の話",
        "つながって見る",
        article_url,
        body="<p>つながって見る</p><p>肩だけでなく、背中や腕の使い方も関係します。</p>",
        tags=["肩こり", "整体", "肩こり"],
    )
    report(article_url not in ig_text, "Instagram初期文面に記事URLを入れない")
    report("肩の話" in ig_text and "つながって見る" in ig_text, "Instagram初期文面はタイトルと概要を使う")
    report("背中や腕の使い方も関係します" in ig_text, "Instagram初期文面は本文の要点を足す")
    report(
        "詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" in ig_text,
        "Instagram初期文面の末尾はプロフィール誘導",
    )
    report("#肩こり" in ig_text and "#整体" in ig_text, "Instagram初期文面は記事タグからハッシュタグを付ける")
    report(ig_text.count("#肩こり") == 1, "同じハッシュタグは重複しない")
    fb_text = external_posts.starter_body("facebook", "肩の話", "つながって見る", article_url)
    gbp_text = external_posts.starter_body("gbp_tokyo", "肩の話", "つながって見る", article_url)
    report(article_url not in fb_text and article_url in gbp_text, "FacebookとGBPの初期文面ルールは変えない")
    report("詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" not in fb_text, "Facebook初期文面にInstagram誘導を入れない")

    saved = external_posts.starter_body("instagram", "別タイトル", "別概要", article_url)
    report("別タイトル" in saved, "未保存の初期生成は呼び出した材料だけを使う")

    candidates = external_posts.instagram_article_image_candidates(
        "/static/images/notes/thumb.jpg",
        '<p>本文</p><img src="/static/images/notes/body.jpg" alt="a">'
        '<img src="/static/images/notes/skip.png">'
        '<img src="/static/images/notes/thumb.jpg">',
    )
    urls = [item["url"] for item in candidates]
    report(
        urls == [
            "https://karin-sb.jp/static/images/notes/thumb.jpg",
            "https://karin-sb.jp/static/images/notes/body.jpg",
        ],
        "記事候補はサムネイルと本文JPEGだけで、重複とPNGは除く",
        str(urls),
    )
    report(candidates[0]["location"] == "thumbnail" and candidates[1]["location"] == "body", "記事候補の出所が分かる")

    tmp = tempfile.mkdtemp()
    try:
        notes = os.path.join(tmp, "notes")
        dedicated = os.path.join(notes, "instagram")
        os.makedirs(dedicated)
        open(os.path.join(notes, "keep.jpg"), "w").close()
        open(os.path.join(notes, "skip.png"), "w").close()
        open(os.path.join(dedicated, "special.jpeg"), "w").close()
        open(os.path.join(tmp, "leftover.jpg"), "w").close()
        open(os.path.join(tmp, "treatment.jpg"), "w").close()
        listed = appmod.list_instagram_server_images(images_root=tmp)
        names = [item["name"] for item in listed]
        locations = {item["name"]: item["location"] for item in listed}
        report("keep.jpg" in names and "special.jpeg" in names and "leftover.jpg" in names, "サーバー候補はnotesと専用フォルダと未移動JPEG")
        report("skip.png" not in names and "treatment.jpg" not in names, "サーバー候補からPNGとサイト用画像を除く")
        report(locations.get("special.jpeg") == "instagram" and locations.get("keep.jpg") == "notes", "サーバー候補の場所が分かる")
    finally:
        shutil.rmtree(tmp)

    one = "/static/images/notes/a.jpg"
    parsed_one = external_posts.parse_instagram_image_urls(one)
    report(
        parsed_one == [PUBLIC_IMAGE],
        "既存の1枚image_urlを公開httpsとして読む",
        str(parsed_one),
    )
    two_saved = PUBLIC_IMAGE + "\nhttps://karin-sb.jp/static/images/notes/b.jpg"
    parsed_two = external_posts.parse_instagram_image_urls(two_saved)
    report(
        parsed_two == [PUBLIC_IMAGE, "https://karin-sb.jp/static/images/notes/b.jpg"],
        "改行区切りの複数URLを順に読む",
        str(parsed_two),
    )
    report(
        external_posts.parse_instagram_image_urls(two_saved + "\n" + PUBLIC_IMAGE)
        == [PUBLIC_IMAGE, "https://karin-sb.jp/static/images/notes/b.jpg"],
        "同じ画像は保存時も重複しない",
    )
    cleaned = external_posts.clean_instagram_image_refs([one, "/static/images/notes/b.jpg"])
    report(
        cleaned == PUBLIC_IMAGE + "\nhttps://karin-sb.jp/static/images/notes/b.jpg",
        "Instagram保存は公開httpsを改行でつなぐ",
        cleaned,
    )
    report(external_posts.clean_image_ref(one) == one, "GBP/Facebook用のclean_image_refは1枚のまま")
    empty_error = ""
    try:
        external_posts.clean_instagram_image_refs("")
    except ValueError as exc:
        empty_error = str(exc)
    report("1枚以上" in empty_error, "0枚はInstagram保存できない", empty_error)
    png_error = ""
    try:
        external_posts.clean_instagram_image_refs("/static/images/notes/a.png")
    except ValueError as exc:
        png_error = str(exc)
    report("JPEG" in png_error, "PNGはInstagram保存できない", png_error)
    many = [f"/static/images/notes/{index}.jpg" for index in range(11)]
    many_error = ""
    try:
        external_posts.clean_instagram_image_refs(many)
    except ValueError as exc:
        many_error = str(exc)
    report("10枚以内" in many_error, "11枚はInstagram保存できない", many_error)
    long_urls = [
        f"https://karin-sb.jp/static/images/notes/{'a' * 180}{index}.jpg"
        for index in range(10)
    ]
    joined_long = external_posts.clean_instagram_image_refs(long_urls)
    report(
        len(joined_long) > 2000 and joined_long.count("\n") == 9,
        "Instagramだけ2000文字を超える複数URLを保存できる",
        str(len(joined_long)),
    )

    instagram = external_posts.get_target("instagram")
    facebook = external_posts.get_target("facebook")
    tokyo = external_posts.get_target("gbp_tokyo")
    preview_one = appmod._instagram_post_preview(instagram, "本文", one)
    report(preview_one and preview_one["ok"], "1枚のInstagram確認は従来どおり送れる")
    preview_two = appmod._instagram_post_preview(instagram, "本文", cleaned)
    report(
        preview_two
        and not preview_two["ok"]
        and any("次の段階" in item for item in preview_two["errors"]),
        "2枚以上は保存できても今回は送信確認しない",
        str((preview_two or {}).get("errors")),
    )
    report(appmod._instagram_post_preview(facebook, "本文", one) is None, "FacebookにInstagram確認は出ない")
    report(
        appmod._instagram_saved_matches(
            {"body": "本文", "link_url": article_url, "image_url": one},
            "本文",
            article_url,
            PUBLIC_IMAGE,
        ),
        "1枚の相対パスと公開httpsは同じ保存内容として扱う",
    )
    report(
        appmod._instagram_saved_matches(
            {"body": "本文", "link_url": article_url, "image_url": cleaned},
            "本文",
            article_url,
            [one, "/static/images/notes/b.jpg"],
        ),
        "複数画像も正規化して保存内容と照合する",
    )
    ig_blog = {
        "id": "12",
        "title": "肩の話",
        "slug": "kata",
        "excerpt": "つながって見る",
        "body": "<p>肩だけでなく、背中も見ます。</p><img src='/static/images/notes/body.jpg'>",
        "image": "/static/images/notes/a.jpg",
        "tags_list": ["肩こり"],
    }
    fresh = appmod._external_post_form_values(ig_blog, instagram, None)
    report("肩の話" in fresh["body"] and "つながって見る" in fresh["body"], "未保存フォームはタイトルと概要を使う")
    report(article_url not in fresh["body"], "未保存のInstagram投稿文に記事URLを入れない", fresh["body"])
    report("#肩こり" in fresh["body"], "未保存のInstagram投稿文にハッシュタグを付ける")
    report(fresh["image_url"] == PUBLIC_IMAGE, "未保存のInstagram画像は記事サムネイルのJPEG", fresh["image_url"])
    kept = appmod._external_post_form_values(
        ig_blog,
        instagram,
        {"status": "draft", "body": "保存済みの文", "link_url": article_url, "image_url": one},
    )
    report(kept["body"] == "保存済みの文", "保存済みのInstagram投稿文は初期生成で上書きしない")
    report(kept["image_url"] == PUBLIC_IMAGE, "保存済みの1枚画像は公開httpsで再表示する")
    gbp_fresh = appmod._external_post_form_values(ig_blog, tokyo, None)
    report(article_url in gbp_fresh["body"] or "/blog/kata" in gbp_fresh["link_url"], "GBPの未保存文面は従来どおり記事へ案内する")
    report("詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" not in gbp_fresh["body"], "GBP文面にInstagram誘導を入れない")
    fb_fresh = appmod._external_post_form_values(ig_blog, facebook, None)
    report("詳しくはプロフィールのリンクから、KARiN.NOTESをご覧ください。" not in fb_fresh["body"], "Facebook文面にInstagram誘導を入れない")
    report(
        appmod._facebook_post_preview(instagram, "本文", article_url) is None
        and appmod._gbp_post_preview(instagram, "本文", article_url, cleaned, notes_create=True) is None,
        "Instagram画面にFacebookとGBPの送信確認は出ない",
    )


def main():
    test_caption_and_images()
    converted = instagram_graph.public_instagram_image_url(IMAGE)
    report(converted == PUBLIC_IMAGE, "相対パスは公開httpsに変換する", converted)
    report(
        instagram_graph.public_instagram_image_url("static/images/notes/a.jpg") == PUBLIC_IMAGE,
        "static/ からも公開httpsにする",
    )
    report(
        instagram_graph.public_instagram_image_url(PUBLIC_IMAGE) == PUBLIC_IMAGE,
        "既にあるhttpsは維持する",
    )
    report(
        instagram_graph.public_instagram_image_url("http://karin-sb.jp/static/images/notes/a.jpg") == PUBLIC_IMAGE,
        "公式サイトのhttpはhttpsにする",
    )
    report(not instagram_graph.public_instagram_image_url("http://example.com/a.jpg"), "他サイトのhttpは使わない")
    report(not instagram_graph.public_instagram_image_url("/images/notes/a.jpg"), "static以外の相対パスは使わない")
    encoded = instagram_graph.public_instagram_image_url("/static/images/notes/pole.サムネイル.jpg")
    report(
        encoded == "https://karin-sb.jp/static/images/notes/pole.%E3%82%B5%E3%83%A0%E3%83%8D%E3%82%A4%E3%83%AB.jpg",
        "日本語ファイル名はパーセントエンコードする",
        encoded,
    )

    preview = instagram_graph.instagram_preview("本文", IMAGE)
    report(preview["ok"] and "本文" in preview["payload_text"] and PUBLIC_IMAGE in preview["payload_text"], "確認画面はキャプションと画像URL")
    report("access_token" not in preview["payload_text"] and TOKEN not in preview["payload_text"], "確認画面にトークンを出さない")
    report(not instagram_graph.instagram_preview("本文", "http://example.com/a.jpg")["ok"], "https以外の画像は確認できない")
    report(not instagram_graph.instagram_preview("本文", "/static/images/notes/a.webp")["ok"], "WebPは確認できない")
    report(not instagram_graph.instagram_preview("本文", "/static/images/notes/a.png")["ok"], "PNGは確認できない")
    report(not instagram_graph.instagram_preview("本文", "")["ok"], "画像なしは確認できない")
    long_caption = "あ" * 2201
    report(not instagram_graph.instagram_preview(long_caption, IMAGE)["ok"], "2201文字は送れない")
    report(instagram_graph.instagram_preview("あ" * 2200, IMAGE)["ok"], "2200文字は確認できる")

    payload = instagram_graph.build_instagram_media_payload("本文", IMAGE)
    report(
        payload == {"image_url": PUBLIC_IMAGE, "caption": "本文"},
        "送信ペイロードはimage_urlとcaptionだけ",
    )

    url = instagram_graph.instagram_media_url(IG_USER)
    report(
        url == f"https://graph.facebook.com/v27.0/{IG_USER}/media" and "access_token" not in url,
        "コンテナURLはv27.0でトークンを含まない",
        url,
    )
    publish = instagram_graph.instagram_publish_url(IG_USER)
    report(
        publish == f"https://graph.facebook.com/v27.0/{IG_USER}/media_publish" and "access_token" not in publish,
        "公開URLはv27.0でトークンを含まない",
    )

    missing = instagram_graph.missing_instagram_env({"access_token": "", "page_id": "", "ig_user_id": ""})
    report(
        missing == [
            "FACEBOOK_SYSTEM_USER_ACCESS_TOKEN",
            "FACEBOOK_PAGE_ID",
            "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        ],
        "不足している環境変数名だけ返す",
        str(missing),
    )
    loaded = instagram_graph.load_instagram_config(
        {
            "FACEBOOK_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "FACEBOOK_PAGE_ID": PAGE_ID,
            "INSTAGRAM_BUSINESS_ACCOUNT_ID": IG_USER,
        }
    )
    report(
        loaded["ig_user_id"] == IG_USER and loaded["page_id"] == PAGE_ID,
        "Instagram設定は3つの環境変数を読む",
    )

    post_http = MediaHttp()
    result, db, log, accounts, status = run_create(sample_record(), post_http)
    report(result["ok"] and db.row["status"] == "posted", "公開成功で posted")
    report(db.row["external_id"] == MEDIA_ID and db.row["posted_at"] == NOW, "InstagramメディアIDと投稿日時を保存")
    report(
        post_http.last_create == {"image_url": PUBLIC_IMAGE, "caption": sample_record()["body"]}
        and post_http.last_publish == {"creation_id": CREATION_ID},
        "コンテナ作成のあと media_publish する",
    )
    report(len(post_http.calls) == 2 and len(status.calls) == 1, "作成・確認・公開の順で1回ずつ")
    report(accounts.calls and accounts.calls[0]["token"] == TOKEN, "Pageトークン取得はシステムユーザートークン")
    report(all(call["body"].get("access_token") is None for call in post_http.calls), "POST本文にトークンを入れない")
    report(secrets_absent(log) and "Instagram投稿" in log, "成功時のログにトークンがない")
    events = [item.get("event") for item in db.events]
    report(events == ["submit_started", "succeeded"], "成功時は開始と成功の履歴")

    denied = MediaHttp(create="denied")
    denied_result, denied_db, denied_log, _acc, denied_status = run_create(sample_record(), denied)
    report(not denied_result["ok"] and denied_db.row["status"] == "failed", "コンテナ作成の4xxは failed")
    report(denied.last_publish is None and denied_status.calls == [], "作成失敗では公開しない")
    report(denied_db.row["external_id"] is None, "失敗では投稿済にしない")
    report(secrets_absent(denied_log, denied_db.row.get("error_message")), "4xxの保存とログにトークンがない")

    error_status = StatusHttp("ERROR")
    error_http = MediaHttp(publish="skip")
    error_result, error_db, _error_log, _acc, error_st = run_create(
        sample_record(), error_http, status=error_status
    )
    report(not error_result["ok"] and error_db.row["status"] == "failed", "コンテナ処理ERRORは failed")
    report(error_http.last_publish is None, "ERRORでは media_publish しない")
    report("画像の処理に失敗" in (error_result["message"] or ""), "ERRORは明確な失敗として案内する")

    wait_http = MediaHttp(publish="skip")
    wait_status = StatusHttp("IN_PROGRESS")
    wait_result, wait_db, _wait_log, _acc, wait_st = run_create(
        sample_record(),
        wait_http,
        status=wait_status,
        max_wait_seconds=0,
    )
    report(not wait_result["ok"] and wait_db.row["status"] == "unknown", "コンテナ処理タイムアウトは unknown")
    report(wait_http.last_publish is None, "待機タイムアウトでは公開しない")
    report("自動再送しません" in (wait_result["message"] or ""), "待機タイムアウトは自動再送しない")

    create_timeout = MediaHttp(create="timeout", publish="skip")
    cto_result, cto_db, _cto_log, _acc, cto_st = run_create(sample_record(), create_timeout)
    report(not cto_result["ok"] and cto_db.row["status"] == "unknown", "コンテナ作成タイムアウトは unknown")
    report(cto_st.calls == [] and create_timeout.last_publish is None, "作成タイムアウトでは確認も公開もしない")

    pub_denied = MediaHttp(publish="denied")
    pd_result, pd_db, pd_log, _acc, _st = run_create(sample_record(), pub_denied)
    report(not pd_result["ok"] and pd_db.row["status"] == "failed", "media_publish失敗は failed")
    report(secrets_absent(pd_log, pd_db.row.get("error_message")), "公開失敗の記録にトークンがない")

    pub_timeout = MediaHttp(publish="timeout")
    pto_result, pto_db, _pto_log, _acc, _st = run_create(sample_record(), pub_timeout)
    report(not pto_result["ok"] and pto_db.row["status"] == "unknown", "media_publishタイムアウトは unknown")
    report("自動再送しません" in (pto_result["message"] or ""), "公開タイムアウトは自動再送しない")

    noid = MediaHttp(publish="noid")
    noid_result, noid_db, _noid_log, _acc, _st = run_create(sample_record(), noid)
    report(not noid_result["ok"] and noid_db.row["status"] == "unknown", "公開応答にIDが無いと unknown")

    mismatch = AccountsHttp("other_page")
    mm_http = MediaHttp(publish="skip")
    mm_result, mm_db, mm_log, mm_acc, mm_st = run_create(
        sample_record(), mm_http, accounts=mismatch
    )
    report(not mm_result["ok"] and mm_http.calls == [] and mm_st.calls == [], "FacebookページIDが違うときは投稿しない")
    report(mm_db.row["status"] == "failed", "ページ不一致は failed に記録する")
    report("FACEBOOK_PAGE_ID" in (mm_result["message"] or "") and secrets_absent(mm_log), "不一致の失敗文にトークンがない")

    missing_http = MediaHttp(publish="skip")
    missing_acc = AccountsHttp("ok")
    missing_result, missing_db, missing_log, missing_acc, missing_st = run_create(
        sample_record(),
        missing_http,
        config={"access_token": "", "page_id": "", "ig_user_id": ""},
        accounts=missing_acc,
    )
    report(not missing_result["ok"] and missing_http.calls == [] and missing_acc.calls == [], "環境変数不足では送信しない")
    report(missing_db.row["status"] == "draft" and not missing_db.updates, "設定不足では状態を変えない")
    report("設定が不足" in (missing_result["message"] or "") and secrets_absent(missing_log), "設定不足の文言にトークンがない")

    no_image = MediaHttp(publish="skip")
    ni_result, ni_db, _ni_log, ni_acc, ni_st = run_create(
        sample_record(image_url=""),
        no_image,
    )
    report(not ni_result["ok"] and no_image.calls == [] and ni_acc.calls == [], "画像なしでは送信しない")
    report(ni_db.row["status"] == "failed", "画像なしは failed")

    posted_http = MediaHttp(media_id=MEDIA_ID_NEW)
    posted_result, posted_db, _posted_log, posted_acc, posted_st = run_create(
        sample_record(status="posted", external_id=MEDIA_ID, posted_at=NOW),
        posted_http,
    )
    posted_started = " ".join(
        item.get("detail") or "" for item in posted_db.events if item.get("event") == "submit_started"
    )
    report(posted_result["ok"] and len(posted_http.calls) == 2, "posted は明示操作で新規投稿できる")
    report(
        posted_db.row["external_id"] == MEDIA_ID_NEW
        and MEDIA_ID in posted_started
        and MEDIA_ID_NEW not in posted_started,
        "再投稿開始時は前回IDを履歴に残し、成功時だけ最新IDへ更新する",
        posted_started,
    )

    unknown_http = MediaHttp(media_id=MEDIA_ID_NEW)
    unknown_result, unknown_db, _unknown_log, _acc, _st = run_create(
        sample_record(status="unknown", external_id=MEDIA_ID, posted_at=NOW),
        unknown_http,
    )
    unknown_started = " ".join(
        item.get("detail") or "" for item in unknown_db.events if item.get("event") == "submit_started"
    )
    report(unknown_result["ok"] and len(unknown_http.calls) == 2, "unknown は明示操作で新規投稿できる")
    report(
        unknown_db.row["external_id"] == MEDIA_ID_NEW and MEDIA_ID in unknown_started,
        "unknown の再投稿成功でも前回IDは履歴に残り、最新IDへ更新する",
        unknown_started,
    )

    posting_http = MediaHttp()
    posting_acc = AccountsHttp("ok")
    posting_result, posting_db, _posting_log, posting_acc, posting_st = run_create(
        sample_record(status="posting", external_id=MEDIA_ID, posted_at=NOW),
        posting_http,
        accounts=posting_acc,
    )
    report(
        not posting_result["ok"] and posting_http.calls == [] and posting_acc.calls == [],
        "posting は再送できない",
    )
    report(
        posting_db.row["status"] == "posting" and posting_db.row["external_id"] == MEDIA_ID,
        "posting の状態と投稿IDは変えない",
    )

    denied_posted = MediaHttp(create="denied")
    dp_result, dp_db, _dp_log, _acc, _st = run_create(
        sample_record(status="posted", external_id=MEDIA_ID, posted_at=NOW),
        denied_posted,
    )
    report(
        not dp_result["ok"]
        and dp_db.row["status"] == "failed"
        and dp_db.row["external_id"] == MEDIA_ID
        and dp_db.row["posted_at"] == NOW,
        "再投稿が4xxでも前回の投稿IDは残す",
    )

    timeout_posted = MediaHttp(publish="timeout")
    tp_result, tp_db, _tp_log, _acc, _st = run_create(
        sample_record(status="posted", external_id=MEDIA_ID, posted_at=NOW),
        timeout_posted,
    )
    report(
        not tp_result["ok"]
        and tp_db.row["status"] == "unknown"
        and tp_db.row["external_id"] == MEDIA_ID,
        "再投稿が結果不明でも前回の投稿IDは残す",
    )

    failed_http = MediaHttp()
    failed_result, failed_db, _failed_log, _acc, _st = run_create(sample_record(status="failed"), failed_http)
    report(failed_result["ok"] and failed_db.row["status"] == "posted", "failed は再送できる")

    facebook_http = MediaHttp(publish="skip")
    facebook_acc = AccountsHttp("ok")
    facebook_result, facebook_db, _fb_log, facebook_acc, facebook_st = run_create(
        sample_record(channel="facebook"),
        facebook_http,
        accounts=facebook_acc,
    )
    report(
        not facebook_result["ok"] and facebook_http.calls == [] and facebook_acc.calls == [],
        "Facebookの行はInstagram送信しない",
    )
    report(facebook_db.row["channel"] == "facebook" and facebook_db.row["status"] == "draft", "Facebookの状態は変えない")

    gbp_http = MediaHttp(publish="skip")
    gbp_result, gbp_db, _gbp_log, gbp_acc, gbp_st = run_create(
        sample_record(channel="gbp", gbp_profile="tokyo"),
        gbp_http,
    )
    report(not gbp_result["ok"] and gbp_http.calls == [] and gbp_acc.calls == [], "GBPの行はInstagram送信しない")

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": CREATION_ID}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    original_post = instagram_graph.requests.post
    instagram_graph.requests.post = fake_post
    try:
        status, body = instagram_graph.instagram_post_exchange(
            instagram_graph.instagram_media_url(IG_USER),
            access_token=PAGE_TOKEN,
            body=payload,
        )
    finally:
        instagram_graph.requests.post = original_post
    header_auth = (captured.get("headers") or {}).get("Authorization") or ""
    report(
        status == 200
        and body == {"id": CREATION_ID}
        and TOKEN not in (captured.get("url") or "")
        and PAGE_TOKEN not in (captured.get("url") or "")
        and "access_token" not in (captured.get("data") or {})
        and header_auth.startswith("Bearer ")
        and captured.get("timeout") == 30,
        "実送信口はヘッダー認証で、クエリと本文にトークンを置かない",
    )

    captured_get = {}

    class FakeGetResponse:
        status_code = 200

        def json(self):
            return {"status_code": "FINISHED"}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured_get["url"] = url
        captured_get["params"] = params
        captured_get["headers"] = headers
        captured_get["timeout"] = timeout
        return FakeGetResponse()

    original_get = instagram_graph.requests.get
    instagram_graph.requests.get = fake_get
    try:
        status, body = instagram_graph.instagram_get_exchange(
            instagram_graph.instagram_container_url(CREATION_ID),
            access_token=PAGE_TOKEN,
            params={"fields": "status_code"},
        )
    finally:
        instagram_graph.requests.get = original_get
    get_auth = (captured_get.get("headers") or {}).get("Authorization") or ""
    report(
        status == 200
        and "access_token" not in (captured_get.get("params") or {})
        and get_auth.startswith("Bearer ")
        and captured_get.get("params") == {"fields": "status_code"},
        "コンテナ確認もヘッダー認証で、クエリにトークンを置かない",
    )

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
