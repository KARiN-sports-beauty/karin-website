#!/usr/bin/env python3
"""GBP読み取りの失敗区分。Google API も DB も使わない。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gbp_read
from gbp_read import (
    GbpReadAuthError,
    GbpReadNotConfigured,
    GbpReadNotFound,
    GbpReadPermissionError,
)

FAILED = 0
PASSED = 0
SECRET = "refresh-secret-value"
ACCESS = "access-secret-value"


def report(ok, name, detail=""):
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name} {detail}")


class FakeHttp:
    def __init__(self, routes):
        self.routes = list(routes)
        self.calls = []

    def __call__(self, method, url, *, headers=None, body=None):
        self.calls.append({"method": method, "url": url, "body": body or ""})
        if not self.routes:
            return 500, {}
        status, payload = self.routes.pop(0)
        return status, payload


def config(**overrides):
    base = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": SECRET,
        "locations": {
            "tokyo": "locations/tokyo-id",
            "fukuoka": "locations/fukuoka-id",
        },
    }
    for key, value in overrides.items():
        if key == "locations":
            base["locations"].update(value)
        else:
            base[key] = value
    return base


def token_ok():
    return 200, {"access_token": ACCESS, "token_type": "Bearer"}


def location_ok(name, title, locality):
    return 200, {
        "name": name,
        "title": title,
        "storefrontAddress": {"locality": locality, "administrativeArea": locality},
    }


def main():
    loaded = gbp_read.load_gbp_read_config(
        {
            "GOOGLE_CREDENTIALS": "credentials.json",
            "GBP_OAUTH_CLIENT_ID": " cid ",
            "GBP_TOKYO_LOCATION_NAME": " locations/abc ",
        }
    )
    report(loaded["client_id"] == "cid" and loaded["refresh_token"] == "", "OAuth未設定は空。他のGoogle変数は読まない")
    report(loaded["locations"]["tokyo"] == "locations/abc" and loaded["locations"]["fukuoka"] == "", "地域のロケーション名は別")
    report("credentials.json" not in str(loaded), "サービスアカウントのパスを設定に入れない")

    no_auth = FakeHttp([])
    blocked = gbp_read.read_profiles(
        config(client_id="", client_secret="", refresh_token=""),
        no_auth,
    )
    report(no_auth.calls == [], "OAuth未設定ではHTTPしない")
    report(
        blocked["tokyo"]["status"] == "not_configured" and blocked["fukuoka"]["status"] == "not_configured",
        "OAuth未設定は両方とも未設定",
    )
    report("GBP_OAUTH_REFRESH_TOKEN" in blocked["tokyo"]["detail"], "未設定の変数名は出す")
    report(SECRET not in blocked["tokyo"]["detail"], "未設定エラーに秘密を出さない")

    only_fukuoka = FakeHttp([token_ok(), location_ok("locations/fukuoka-id", "福岡店", "福岡市")])
    partial = gbp_read.read_profiles(config(locations={"tokyo": ""}), only_fukuoka)
    report(partial["tokyo"]["status"] == "not_configured", "東京名が空なら東京は未設定")
    report(partial["fukuoka"]["status"] == "ok" and partial["fukuoka"]["title"] == "福岡店", "福岡だけ取得できる")
    report(
        [call["method"] for call in only_fukuoka.calls] == ["POST", "GET"]
        and all(call["method"] != "POST" or call["url"] == gbp_read.OAUTH_TOKEN_URL for call in only_fukuoka.calls),
        "送るのはトークン更新のPOSTとロケーションのGETだけ",
    )
    bad_request = gbp_read.read_profiles(
        config(),
        FakeHttp([token_ok(), (400, {"error": {"status": "INVALID_ARGUMENT"}}), location_ok("locations/fukuoka-id", "福岡店", "福岡市")]),
    )
    report(bad_request["tokyo"]["status"] == "error" and bad_request["fukuoka"]["status"] == "ok", "ロケーションの400は認証失敗にしない")
    report(ACCESS not in str(partial), "結果にアクセストークンを残さない")

    same = FakeHttp([])
    duplicated = gbp_read.read_profiles(
        config(locations={"tokyo": "locations/same", "fukuoka": "locations/same"}),
        same,
    )
    report(same.calls == [], "同じロケーション名では取得しない")
    report(duplicated["tokyo"]["status"] == "not_configured" and duplicated["fukuoka"]["status"] == "not_configured", "同じ指定は両方とも未設定")

    auth_http = FakeHttp([(400, {"error": "invalid_grant"})])
    try:
        gbp_read.fetch_access_token(config(), auth_http)
        raised = None
    except GbpReadAuthError as exc:
        raised = exc
    report(isinstance(raised, GbpReadAuthError) and not isinstance(raised, GbpReadPermissionError), "invalid_grant は認証失敗")
    report(SECRET not in str(raised), "認証失敗にリフレッシュトークンを出さない")
    report("client-secret" not in str(raised), "認証失敗にクライアントシークレットを出さない")

    auth_profiles = gbp_read.read_profiles(config(), FakeHttp([(401, {"error": {"status": "UNAUTHENTICATED"}})]))
    report(auth_profiles["tokyo"]["status"] == "auth" and auth_profiles["fukuoka"]["status"] == "auth", "トークン失敗は両方とも認証失敗")

    denied = gbp_read.read_profiles(
        config(),
        FakeHttp([token_ok(), (403, {"error": {"status": "PERMISSION_DENIED"}}), location_ok("locations/fukuoka-id", "福岡店", "福岡市")]),
    )
    report(denied["tokyo"]["status"] == "permission", "403は権限不足")
    report(denied["fukuoka"]["status"] == "ok", "東京の権限不足でも福岡は取得する")

    missing = gbp_read.read_profiles(
        config(),
        FakeHttp([token_ok(), (404, {"error": {"status": "NOT_FOUND"}}), (404, {})]),
    )
    report(missing["tokyo"]["status"] == "not_found" and missing["fukuoka"]["status"] == "not_found", "404はプロフィール未取得")
    report(missing["tokyo"]["status"] != "auth" and missing["tokyo"]["status"] != "permission", "未取得は認証失敗や権限不足と違う")

    mismatch = gbp_read.read_profiles(
        config(),
        FakeHttp([token_ok(), (200, {"name": "locations/other", "title": "別店舗"}), location_ok("locations/fukuoka-id", "福岡店", "福岡市")]),
    )
    report(mismatch["tokyo"]["status"] == "error", "応答のロケーション名が違えば成功にしない")
    report(mismatch["fukuoka"]["status"] == "ok", "東京の不一致は福岡に影響しない")

    try:
        gbp_read.read_location("tokyo", config(locations={"tokyo": "accounts/1/locations/2"}), FakeHttp([]), "token")
        bad_name = None
    except GbpReadNotConfigured as exc:
        bad_name = exc
    report(isinstance(bad_name, GbpReadNotConfigured), "accounts付きの名前は未設定扱いで取得しない")

    listed = gbp_read.list_unassigned_locations(
        FakeHttp([(200, {"locations": [{"name": "locations/1", "title": "KARiN東京", "accountName": "hidden"}], "nextPageToken": "page-secret"})]),
        "token",
    )
    report(listed["locations"] == [{"name": "locations/1", "title": "KARiN東京"}], "候補はnameとtitleだけ")
    report(listed["has_more"] is True and "page-secret" not in str(listed), "続きトークンは返さない")

    accounts = gbp_read.list_accounts(
        FakeHttp([(200, {"accounts": [{"name": "accounts/9", "type": "PERSONAL", "accountName": "owner@example.com"}]})]),
        "token",
    )
    report(accounts["accounts"] == [{"name": "accounts/9", "type": "PERSONAL"}], "アカウント表示名は返さない")

    try:
        gbp_read.list_accounts(FakeHttp([(403, {"error": {"status": "PERMISSION_DENIED"}})]), "token")
        account_error = None
    except GbpReadPermissionError as exc:
        account_error = exc
    report(isinstance(account_error, GbpReadPermissionError), "アカウント一覧の403は権限不足")

    try:
        gbp_read.list_unassigned_locations(FakeHttp([(404, {})]), "token")
        list_missing = None
    except GbpReadNotFound as exc:
        list_missing = exc
    report(isinstance(list_missing, GbpReadNotFound), "一覧の404は未取得")

    import external_posts

    still = False
    try:
        external_posts.publish_external_post("gbp_tokyo", body="本文")
    except external_posts.ExternalPostNotConnected:
        still = True
    report(still, "投稿口は未接続のまま")

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
