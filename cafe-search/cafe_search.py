"""
Google Places API (New) でカフェを検索し、Googleスプレッドシートに書き込むスクリプト

フィルター条件:
  - WebサイトURLが登録されていない
  - レビュー数が20件以上

2025年3月〜の新料金体系メモ:
  - websiteUri は Contact Data SKU (Advanced) 扱いで基本より高い
  - 必要最小限の Field Mask を指定してコストを抑える
  - Nearby Search (New): maxResultCount は最大 20
"""

import os
import time
import urllib.parse

import gspread
import requests
from google.oauth2.service_account import Credentials

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
PLACES_API_KEY = os.environ.get("PLACES_API_KEY", "YOUR_PLACES_API_KEY")

# 検索中心座標（例: 渋谷駅）
SEARCH_LOCATION = {
   "latitude": -37.8400,   # 例：新宿駅周辺
    "longitude": 144.9935,
}
SEARCH_RADIUS_M = 50000  # 検索半径（メートル）

# Googleスプレッドシート
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1ESdP_FAd2ghCBG7KUHwsA23ntFAHLqQutYoCmj_yQ8Y")
SHEET_NAME = "カフェリスト"
SERVICE_ACCOUNT_JSON = "service_account.json"

# フィルター
MIN_REVIEW_COUNT = 20

# ─────────────────────────────────────────────
# Field Mask（コスト最小化）
# ─────────────────────────────────────────────
# Basic SKU : displayName, rating, userRatingCount, formattedAddress
# Advanced SKU (Contact): websiteUri ← サイトなし判定に必須なので含める
FIELD_MASK = ",".join([
    "places.displayName",
    "places.rating",
    "places.userRatingCount",
    "places.formattedAddress",
    "places.websiteUri",
    "nextPageToken",
])

PLACES_API_URL = "https://places.googleapis.com/v1/places:searchNearby"


# ─────────────────────────────────────────────
# Places API 呼び出し
# ─────────────────────────────────────────────
def search_nearby_cafes(page_token: str | None = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": PLACES_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    payload = {
        "includedTypes": ["cafe"],
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": SEARCH_LOCATION,
                "radius": float(SEARCH_RADIUS_M),
            }
        },
    }
    if page_token:
        payload["pageToken"] = page_token

    resp = requests.post(PLACES_API_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_cafes() -> list[dict]:
    """ページネーションで全件取得"""
    all_places = []
    next_token = None

    while True:
        data = search_nearby_cafes(next_token)
        places = data.get("places", [])
        all_places.extend(places)
        print(f"  取得済み: {len(all_places)} 件")

        next_token = data.get("nextPageToken")
        if not next_token:
            break
        time.sleep(2)  # ページネーション間隔

    return all_places


# ─────────────────────────────────────────────
# フィルタリング
# ─────────────────────────────────────────────
def filter_cafes(places: list[dict]) -> list[dict]:
    result = []
    for p in places:
        has_website = bool(p.get("websiteUri"))
        review_count = p.get("userRatingCount", 0)

        if not has_website and review_count >= MIN_REVIEW_COUNT:
            result.append(p)
    return result


# ─────────────────────────────────────────────
# Instagram 検索URL 生成
# ─────────────────────────────────────────────
def instagram_search_url(store_name: str) -> str:
    q = urllib.parse.quote(store_name)
    return f"https://www.instagram.com/explore/search/keyword/?q={q}"


# ─────────────────────────────────────────────
# Googleスプレッドシートへ書き込み
# ─────────────────────────────────────────────
def write_to_spreadsheet(cafes: list[dict]) -> None:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=scopes)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    # シートが存在しなければ作成
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)

    sheet.clear()

    headers = ["店名", "評価", "レビュー数", "住所", "Instagram検索URL"]
    rows = [headers]

    for cafe in cafes:
        name = cafe.get("displayName", {}).get("text", "")
        rating = cafe.get("rating", "")
        review_count = cafe.get("userRatingCount", "")
        address = cafe.get("formattedAddress", "")
        ig_url = instagram_search_url(name)
        rows.append([name, rating, review_count, address, ig_url])

    sheet.update("A1", rows)

    # ヘッダー行を太字にする
    sheet.format("A1:E1", {"textFormat": {"bold": True}})

    print(f"スプレッドシートに {len(cafes)} 件を書き込みました。")
    print(f"URL: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
def main():
    print("=== カフェ検索開始 ===")
    print(f"中心座標: {SEARCH_LOCATION}")
    print(f"半径: {SEARCH_RADIUS_M}m")
    print(f"条件: サイトなし & レビュー数 {MIN_REVIEW_COUNT}件以上\n")

    print("Places API で検索中...")
    all_places = fetch_all_cafes()
    print(f"合計取得: {len(all_places)} 件\n")

    filtered = filter_cafes(all_places)
    print(f"条件に合致: {len(filtered)} 件\n")

    if not filtered:
        print("条件に合う店舗が見つかりませんでした。")
        return

    write_to_spreadsheet(filtered)


if __name__ == "__main__":
    main()
