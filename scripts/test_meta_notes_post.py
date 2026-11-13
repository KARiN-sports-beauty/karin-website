#!/usr/bin/env python3
"""KARiN.NOTES の Facebook 投稿。Meta API へは送らない。"""
from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import meta_graph
from meta_graph import MetaGraphTimeout

FAILED = 0
PASSED = 0
NOW = "2026-11-13T15:00:00+09:00"
TOKEN = "EAAtestsecretvalue000000000000"
PAGE_ID = "61595470022494"
POST_ID = "61595470022494_111222333"


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


class FeedHttp:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []
        self.last_body = None
        self.last_url = None

    def __call__(self, url, *, access_token, body):
        self.calls.append({"url": url, "body": dict(body or {})})
        self.last_url = url
        self.last_body = body
        if access_token != TOKEN:
            raise AssertionError("unexpected token")
        if TOKEN in (url or ""):
            raise AssertionError("secret in url")
        if "access_token=" in (url or "").lower():
            raise AssertionError("token query")
        if body and "access_token" in body:
            raise AssertionError("token in body")
        if self.mode == "timeout":
            raise MetaGraphTimeout()
        if self.mode == "server":
            return 500, {"error": {"message": f"Bearer {TOKEN}", "code": 1}}
        if self.mode == "denied":
            return 403, {"error": {"message": f"Invalid OAuth access token {TOKEN}", "code": 190}}
        if self.mode == "noid":
            return 200, {"success": True}
        return 200, {"id": POST_ID}


def sample_record(**overrides):
    row = {
        "id": "fb-1",
        "source_kind": "notes_article",
        "blog_id": "12",
        "channel": "facebook",
        "gbp_profile": None,
        "status": "draft",
        "body": "KARiN.NOTESの記事です。",
        "link_url": "https://karin-sb.jp/blog/sample",
        "image_url": "/static/images/notes/a.jpg",
        "external_id": None,
        "posted_at": None,
        "error_message": None,
    }
    row.update(overrides)
    return row


def sample_config(**overrides):
    config = {"access_token": TOKEN, "page_id": PAGE_ID}
    config.update(overrides)
    return config


def run_create(record, http, config=None):
    db = FakeDB(record)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        result = meta_graph.perform_notes_facebook_create(
            db,
            record,
            config=config or sample_config(),
            post_exchange=http,
            now=NOW,
            staff_id="staff-1",
        )
    log = stdout.getvalue()
    if TOKEN in log:
        raise AssertionError("secret in log")
    return result, db, log


def main():
    preview = meta_graph.facebook_preview("本文", "https://karin-sb.jp/blog/a")
    report(preview["ok"] and "本文" in preview["payload_text"] and "https://karin-sb.jp/blog/a" in preview["payload_text"], "確認画面は本文とリンク")
    report("access_token" not in preview["payload_text"] and TOKEN not in preview["payload_text"], "確認画面にトークンを出さない")
    bad_link = meta_graph.facebook_preview("本文", "http://karin-sb.jp/blog/a")
    report(not bad_link["ok"], "httpリンクは送信確認できない")

    url = meta_graph.facebook_feed_url(PAGE_ID)
    report(
        url == f"https://graph.facebook.com/v27.0/{PAGE_ID}/feed" and "access_token" not in url,
        "投稿URLはv27.0でトークンを含まない",
        url,
    )

    missing = meta_graph.missing_facebook_env({"access_token": "", "page_id": ""})
    report(
        missing == ["FACEBOOK_SYSTEM_USER_ACCESS_TOKEN", "FACEBOOK_PAGE_ID"],
        "不足している環境変数名だけ返す",
        str(missing),
    )
    loaded = meta_graph.load_facebook_config(
        {
            "FACEBOOK_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "FACEBOOK_PAGE_ID": PAGE_ID,
            "INSTAGRAM_BUSINESS_ACCOUNT_ID": "1784140000",
        }
    )
    report(
        loaded["page_id"] == PAGE_ID and "instagram" not in loaded and loaded["access_token"] == TOKEN,
        "Facebook設定はInstagramの値を使わない",
    )

    dirty = meta_graph.sanitize_meta_error_message(
        f"Invalid OAuth access token {TOKEN} https://graph.facebook.com/debug Bearer {TOKEN}"
    )
    report(
        dirty
        and TOKEN not in dirty
        and "https://" not in dirty
        and "Bearer" not in dirty
        and "[redacted]" in dirty,
        "エラー文からトークンとURLを除く",
        dirty or "",
    )

    ok_http = FeedHttp("ok")
    ok_result, ok_db, ok_log = run_create(sample_record(), ok_http)
    report(ok_result["ok"] and ok_db.row["status"] == "posted", "正常レスポンスで posted")
    report(ok_db.row["external_id"] == POST_ID and ok_db.row["posted_at"] == NOW, "投稿IDと投稿日時を保存")
    report(
        ok_http.last_body == {"message": "KARiN.NOTESの記事です。", "link": "https://karin-sb.jp/blog/sample"},
        "message と link だけ送る",
        str(ok_http.last_body),
    )
    report(len(ok_http.calls) == 1 and TOKEN not in ok_log and "EAAtest" not in ok_log, "成功時のログにトークンがない")
    events = [item.get("event") for item in ok_db.events]
    report(events == ["submit_started", "succeeded"], "成功時は開始と成功の履歴", str(events))

    denied_http = FeedHttp("denied")
    denied_result, denied_db, denied_log = run_create(sample_record(), denied_http)
    report(not denied_result["ok"] and denied_db.row["status"] == "failed", "4xxで failed")
    report(denied_db.row.get("external_id") is None and denied_db.row.get("posted_at") is None, "失敗では投稿済にしない")
    report(TOKEN not in (denied_db.row.get("error_message") or "") and TOKEN not in denied_log, "4xxの保存とログにトークンがない")

    server_http = FeedHttp("server")
    server_result, server_db, server_log = run_create(sample_record(), server_http)
    report(not server_result["ok"] and server_db.row["status"] == "unknown", "5xxで unknown")
    report("自動再送しません" in (server_result["message"] or ""), "5xxは自動再送しない")
    report(TOKEN not in server_log, "5xxのログにトークンがない")

    timeout_http = FeedHttp("timeout")
    timeout_result, timeout_db, _timeout_log = run_create(sample_record(), timeout_http)
    report(not timeout_result["ok"] and timeout_db.row["status"] == "unknown", "タイムアウトで unknown")
    report(timeout_db.row.get("external_id") is None, "タイムアウトでは投稿IDを書かない")

    noid_http = FeedHttp("noid")
    noid_result, noid_db, _noid_log = run_create(sample_record(), noid_http)
    report(not noid_result["ok"] and noid_db.row["status"] == "unknown", "投稿IDがない200は unknown")

    missing_http = FeedHttp("ok")
    missing_result, missing_db, missing_log = run_create(
        sample_record(),
        missing_http,
        config={"access_token": "", "page_id": ""},
    )
    report(not missing_result["ok"] and missing_http.calls == [], "環境変数不足では送信しない")
    report(missing_db.row["status"] == "draft" and not missing_db.updates, "設定不足では状態を変えない")
    report("設定が不足" in (missing_result["message"] or "") and TOKEN not in missing_log, "設定不足の文言にトークンがない")

    posted_http = FeedHttp("ok")
    posted_result, posted_db, _posted_log = run_create(
        sample_record(status="posted", external_id=POST_ID, posted_at=NOW),
        posted_http,
    )
    report(not posted_result["ok"] and posted_http.calls == [], "posted は再送できない")
    report(posted_db.row["status"] == "posted", "posted の状態は変えない")

    unknown_http = FeedHttp("ok")
    unknown_result, unknown_db, _unknown_log = run_create(
        sample_record(status="unknown"),
        unknown_http,
    )
    report(not unknown_result["ok"] and unknown_http.calls == [], "unknown は再送できない")
    report(unknown_db.row["status"] == "unknown", "unknown の状態は変えない")

    failed_http = FeedHttp("ok")
    failed_result, failed_db, _failed_log = run_create(sample_record(status="failed"), failed_http)
    report(failed_result["ok"] and failed_db.row["status"] == "posted", "failed は再送できる")

    instagram_http = FeedHttp("ok")
    instagram_result, instagram_db, _ig_log = run_create(
        sample_record(channel="instagram"),
        instagram_http,
    )
    report(not instagram_result["ok"] and instagram_http.calls == [], "Instagramの行はFacebook送信しない")
    report(instagram_db.row["channel"] == "instagram" and instagram_db.row["status"] == "draft", "Instagramの状態は変えない")

    gbp_http = FeedHttp("ok")
    gbp_result, gbp_db, _gbp_log = run_create(
        sample_record(channel="gbp", gbp_profile="tokyo"),
        gbp_http,
    )
    report(not gbp_result["ok"] and gbp_http.calls == [], "GBPの行はFacebook送信しない")

    payload = meta_graph.build_facebook_feed_payload("本文", "https://karin-sb.jp/blog/a")
    report(payload == {"message": "本文", "link": "https://karin-sb.jp/blog/a"}, "送信ペイロードにトークンを入れない")

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": POST_ID}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    original_post = meta_graph.requests.post
    meta_graph.requests.post = fake_post
    try:
        status, body = meta_graph.facebook_feed_exchange(
            meta_graph.facebook_feed_url(PAGE_ID),
            access_token=TOKEN,
            body=payload,
        )
    finally:
        meta_graph.requests.post = original_post
    header_auth = (captured.get("headers") or {}).get("Authorization") or ""
    report(
        status == 200
        and body == {"id": POST_ID}
        and TOKEN not in (captured.get("url") or "")
        and "access_token" not in (captured.get("data") or {})
        and header_auth.startswith("Bearer ")
        and captured.get("timeout") == 30,
        "実送信口はヘッダー認証で、クエリと本文にトークンを置かない",
    )

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
