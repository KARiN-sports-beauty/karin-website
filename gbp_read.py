"""Google Business Profile の読み取り。

東京と福岡は、環境変数で指定したロケーションを別々に GET する。
片方の結果でもう一方を補わない。投稿・更新・削除は送らない。
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote
from urllib.parse import urlencode

import requests

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
ACCOUNT_LIST_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
LOCATION_LIST_URL = "https://mybusinessbusinessinformation.googleapis.com/v1/accounts/-/locations"
LOCATION_GET_URL = "https://mybusinessbusinessinformation.googleapis.com/v1/{name}"
READ_SCOPE = "https://www.googleapis.com/auth/business.manage"
LOCATION_READ_MASK = "name,title,storefrontAddress,metadata"
ACCOUNT_PAGE_SIZE = 20

_OAUTH_ENV = (
    ("client_id", "GBP_OAUTH_CLIENT_ID"),
    ("client_secret", "GBP_OAUTH_CLIENT_SECRET"),
    ("refresh_token", "GBP_OAUTH_REFRESH_TOKEN"),
)
_LOCATION_ENV = {
    "tokyo": "GBP_TOKYO_LOCATION_NAME",
    "fukuoka": "GBP_FUKUOKA_LOCATION_NAME",
}
_LOCATION_NAME = re.compile(r"^locations/[A-Za-z0-9_-]+$")
_PROFILES = ("tokyo", "fukuoka")


class GbpReadError(Exception):
    """読み取りの失敗。detail に秘密情報は入れない。"""

    status = "error"

    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


class GbpReadNotConfigured(GbpReadError):
    status = "not_configured"


class GbpReadAuthError(GbpReadError):
    status = "auth"


class GbpReadPermissionError(GbpReadError):
    status = "permission"


class GbpReadNotFound(GbpReadError):
    status = "not_found"


def load_gbp_read_config(env=None):
    """環境変数名だけを読む。未設定は空文字。他の Google 変数は見ない。"""
    source = env if env is not None else os.environ
    config = {}
    for key, name in _OAUTH_ENV:
        config[key] = (source.get(name) or "").strip()
    config["locations"] = {
        profile: (source.get(env_name) or "").strip()
        for profile, env_name in _LOCATION_ENV.items()
    }
    return config


def missing_oauth_env(config):
    return [env_name for key, env_name in _OAUTH_ENV if not config.get(key)]


def location_config_error(config):
    """地域ごとの設定不備。取得前に返す。"""
    problems = {}
    names = config.get("locations") or {}
    for profile, env_name in _LOCATION_ENV.items():
        value = (names.get(profile) or "").strip()
        if not value:
            problems[profile] = GbpReadNotConfigured(f"{env_name} が未設定")
        elif not _LOCATION_NAME.fullmatch(value):
            problems[profile] = GbpReadNotConfigured(f"{env_name} は locations/ID の形式にしてください")
    tokyo = (names.get("tokyo") or "").strip()
    fukuoka = (names.get("fukuoka") or "").strip()
    if (
        tokyo
        and fukuoka
        and tokyo == fukuoka
        and "tokyo" not in problems
        and "fukuoka" not in problems
    ):
        message = "GBP_TOKYO_LOCATION_NAME と GBP_FUKUOKA_LOCATION_NAME が同じです"
        problems["tokyo"] = GbpReadNotConfigured(message)
        problems["fukuoka"] = GbpReadNotConfigured(message)
    return problems


def requests_exchange(method, url, *, headers=None, body=None, timeout=20):
    """GET とトークン更新の POST だけを想定した送受信。本文の生テキストは返さない。"""
    try:
        response = requests.request(method, url, headers=headers, data=body, timeout=timeout)
    except requests.RequestException:
        raise GbpReadError("読み取り失敗 接続できません")
    try:
        parsed = response.json()
    except ValueError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return response.status_code, parsed


def fetch_access_token(config, exchange):
    missing = missing_oauth_env(config)
    if missing:
        raise GbpReadNotConfigured("未設定: " + ", ".join(missing))
    status, body = exchange(
        "POST",
        OAUTH_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": config["refresh_token"],
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            }
        ),
    )
    token = body.get("access_token") if status == 200 else None
    if not isinstance(token, str) or not token:
        raise _classify(status, body, token_endpoint=True)
    return token


def read_location(profile, config, exchange, access_token):
    """指定地域のロケーションを1件 GET する。"""
    if profile not in _PROFILES:
        raise GbpReadNotConfigured("profile は tokyo または fukuoka です")
    problems = location_config_error(config)
    if profile in problems:
        raise problems[profile]
    name = config["locations"][profile]
    url = LOCATION_GET_URL.format(name=quote(name, safe="/"))
    url = f"{url}?readMask={quote(LOCATION_READ_MASK, safe=',')}"
    status, body = exchange(
        "GET",
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        body=None,
    )
    if status != 200:
        raise _classify(status, body, token_endpoint=False)
    returned = body.get("name") if isinstance(body.get("name"), str) else ""
    if returned != name:
        raise GbpReadError("応答のロケーション名が指定と一致しません")
    address = body.get("storefrontAddress") if isinstance(body.get("storefrontAddress"), dict) else {}
    return {
        "profile": profile,
        "status": "ok",
        "location_name": returned,
        "title": body.get("title") if isinstance(body.get("title"), str) else "",
        "locality": address.get("locality") if isinstance(address.get("locality"), str) else "",
        "administrative_area": address.get("administrativeArea") if isinstance(address.get("administrativeArea"), str) else "",
    }


def read_profiles(config, exchange):
    """東京と福岡を別々に読む。トークン更新の失敗は両方を認証失敗にする。"""
    missing = missing_oauth_env(config)
    if missing:
        detail = "未設定: " + ", ".join(missing)
        return {profile: _failure(profile, GbpReadNotConfigured(detail), config) for profile in _PROFILES}
    problems = location_config_error(config)
    if set(problems) == set(_PROFILES):
        return {profile: _failure(profile, problems[profile], config) for profile in _PROFILES}
    try:
        access_token = fetch_access_token(config, exchange)
    except GbpReadError as exc:
        return {
            profile: _failure(profile, problems.get(profile, exc), config)
            for profile in _PROFILES
        }
    results = {}
    for profile in _PROFILES:
        if profile in problems:
            results[profile] = _failure(profile, problems[profile], config)
            continue
        try:
            results[profile] = read_location(profile, config, exchange, access_token)
        except GbpReadError as exc:
            results[profile] = _failure(profile, exc, config)
    return results


def list_accounts(exchange, access_token):
    """見えるアカウントの resource name と type だけ。表示名は返さない。"""
    status, body = exchange(
        "GET",
        f"{ACCOUNT_LIST_URL}?pageSize={ACCOUNT_PAGE_SIZE}",
        headers={"Authorization": f"Bearer {access_token}"},
        body=None,
    )
    if status != 200:
        raise _classify(status, body, token_endpoint=False)
    accounts = []
    for item in body.get("accounts") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") if isinstance(item.get("name"), str) else ""
        kind = item.get("type") if isinstance(item.get("type"), str) else ""
        if name:
            accounts.append({"name": name, "type": kind})
    return {
        "accounts": accounts,
        "has_more": bool(body.get("nextPageToken")),
    }


def list_unassigned_locations(exchange, access_token):
    """ロケーション名が未設定のとき、候補の name と title だけを返す。地域への割り当てはしない。"""
    status, body = exchange(
        "GET",
        f"{LOCATION_LIST_URL}?readMask=name,title&pageSize={ACCOUNT_PAGE_SIZE}",
        headers={"Authorization": f"Bearer {access_token}"},
        body=None,
    )
    if status != 200:
        raise _classify(status, body, token_endpoint=False)
    locations = []
    for item in body.get("locations") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") if isinstance(item.get("name"), str) else ""
        title = item.get("title") if isinstance(item.get("title"), str) else ""
        if name:
            locations.append({"name": name, "title": title})
    return {
        "locations": locations,
        "has_more": bool(body.get("nextPageToken")),
    }


def _failure(profile, exc, config):
    names = (config.get("locations") or {}) if isinstance(config, dict) else {}
    location_name = names.get(profile) or ""
    if not _LOCATION_NAME.fullmatch(location_name):
        location_name = ""
    return {
        "profile": profile,
        "status": exc.status,
        "location_name": location_name,
        "title": "",
        "locality": "",
        "administrative_area": "",
        "detail": exc.detail,
    }


def _classify(status, body, *, token_endpoint):
    code = _error_status(body)
    auth_code = code in {"UNAUTHENTICATED", "invalid_grant", "invalid_client"}
    if auth_code or status == 401 or (token_endpoint and status == 400):
        label = "トークン更新" if token_endpoint else "ロケーション取得"
        return GbpReadAuthError(f"{label} 認証失敗 HTTP {status} {code}".strip())
    if status == 403 or code == "PERMISSION_DENIED":
        return GbpReadPermissionError(f"権限不足 HTTP {status} {code}".strip())
    if status == 404 or code == "NOT_FOUND":
        return GbpReadNotFound(f"プロフィール未取得 HTTP {status}")
    return GbpReadError(f"読み取り失敗 HTTP {status} {code}".strip())


def _error_status(body):
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, str):
        return error[:80]
    if isinstance(error, dict):
        value = error.get("status") or ""
        return str(value)[:80]
    return ""
