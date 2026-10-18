#!/usr/bin/env python3
"""GBP東京・福岡の読み取り確認。

値は出さない。投稿もしない。両方が ok のときだけ終了コード 0。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import gbp_read


def line(label, result):
    status = result["status"]
    if status == "ok":
        bits = [result["title"] or "(titleなし)", result["location_name"]]
        place = " ".join(part for part in (result["administrative_area"], result["locality"]) if part)
        if place:
            bits.append(place)
        print(f"{label}: ok | " + " | ".join(bits))
        return
    detail = result.get("detail") or ""
    print(f"{label}: {status}" + (f" | {detail}" if detail else ""))


def _safe_error(body):
    """原因の判別に使う項目だけ。トークンや認証ヘッダーは含めない。"""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, str):
        return error[:300]
    if not isinstance(error, dict):
        return ""
    reasons = []
    services = []
    for detail in error.get("details") or []:
        if not isinstance(detail, dict):
            continue
        reason = detail.get("reason")
        if isinstance(reason, str) and reason:
            reasons.append(reason)
        metadata = detail.get("metadata") if isinstance(detail.get("metadata"), dict) else {}
        service = metadata.get("service")
        if isinstance(service, str) and service:
            services.append(service)
    parts = [
        str(error.get("status") or ""),
        ",".join(reasons),
        ",".join(services),
        str(error.get("message") or ""),
    ]
    return " | ".join(part for part in parts if part)[:500]


def _probe(label, url, token):
    status, body = gbp_read.requests_exchange(
        "GET",
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    path = url.split("?", 1)[0]
    if status == 200:
        return status, body, f"{label}: ok | GET {path}"
    kind = "permission" if status == 403 else "error"
    if status == 401:
        kind = "auth"
    elif status == 404:
        kind = "not_found"
    detail = _safe_error(body)
    line = f"{label}: {kind} | GET {path} | HTTP {status}"
    if detail:
        line = f"{line} | {detail}"
    return status, body, line


def main() -> int:
    config = gbp_read.load_gbp_read_config()
    missing = gbp_read.missing_oauth_env(config)
    results = gbp_read.read_profiles(config, gbp_read.requests_exchange)
    token_used = any(item["status"] in {"ok", "permission", "not_found", "error"} for item in results.values())
    both_auth = results["tokyo"]["status"] == "auth" and results["fukuoka"]["status"] == "auth"
    need_names = any(
        item["status"] == "not_configured" and "LOCATION_NAME" in item.get("detail", "")
        for item in results.values()
    )
    listing = []
    if missing:
        oauth_line = "oauth: not_configured | 未設定: " + ", ".join(missing)
    elif both_auth:
        oauth_line = "oauth: auth | " + results["tokyo"]["detail"]
    elif token_used:
        oauth_line = "oauth: ok"
    else:
        try:
            gbp_read.fetch_access_token(config, gbp_read.requests_exchange)
        except gbp_read.GbpReadError as exc:
            oauth_line = f"oauth: {exc.status} | {exc.detail}"
        else:
            oauth_line = "oauth: ok"

    if need_names and oauth_line.startswith("oauth: ok"):
        try:
            token = gbp_read.fetch_access_token(config, gbp_read.requests_exchange)
        except gbp_read.GbpReadError as exc:
            listing = [f"accounts: {exc.status} | {exc.detail}"]
        else:
            account_status, account_body, account_line = _probe(
                "accounts",
                f"{gbp_read.ACCOUNT_LIST_URL}?pageSize={gbp_read.ACCOUNT_PAGE_SIZE}",
                token,
            )
            listing.append(account_line)
            if account_status == 200:
                names = []
                for item in account_body.get("accounts") or []:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        kind = item.get("type") if isinstance(item.get("type"), str) else ""
                        names.append(f"{item['name']} {kind}".strip())
                listing.append("accounts_visible: " + (", ".join(names) or "(なし)"))
            location_status, location_body, location_line = _probe(
                "locations",
                f"{gbp_read.LOCATION_LIST_URL}?readMask=name,title&pageSize={gbp_read.ACCOUNT_PAGE_SIZE}",
                token,
            )
            listing.append(location_line)
            if location_status == 200:
                listing.append("unassigned_locations: 地域へは割り当てていません")
                for item in location_body.get("locations") or []:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") if isinstance(item.get("name"), str) else ""
                    title = item.get("title") if isinstance(item.get("title"), str) else ""
                    if name:
                        listing.append(f"- {name} | {title}")
                if location_body.get("nextPageToken"):
                    listing.append("- 続きあり")

    print(oauth_line)
    line("tokyo", results["tokyo"])
    line("fukuoka", results["fukuoka"])
    for item in listing:
        print(item)

    ok = results["tokyo"]["status"] == "ok" and results["fukuoka"]["status"] == "ok"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
