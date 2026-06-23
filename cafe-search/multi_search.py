"""
Google Places API (New) で複数エリア×複数業種を検索し、
営業リスト index.html を生成するスクリプト

フィルター条件:
  - WebサイトURLが登録されていない
  - レビュー数 MIN_REVIEW_COUNT 件以上

2025年3月〜 新料金体系:
  - Basic SKU  : displayName / rating / userRatingCount / formattedAddress
  - Advanced SKU (Contact): websiteUri  ← サイトなし判定に必須
"""

import json
import math
import os
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime

import requests

PLACES_DB_FILE      = "places_db.json"
SEARCH_HISTORY_FILE = "search_history.json"

# グリッド設定（5km×5km の体系的な網羅）
GRID_STEP_KM    = 5      # グリッド間隔
GRID_RANGE_KM   = 25     # 中心からの探索半径（→ 11×11 = 121 点 / 都市）
SEARCH_RADIUS_M = 3500   # API 1回あたりの検索半径（5km グリッドに対し微小オーバーラップ）


def make_grid_steps(center_lat: float) -> list[tuple[float, float]]:
    """体系的グリッドの (dlat, dlon) オフセット一覧を生成。index 0 = 中心（後方互換）"""
    lat_step = GRID_STEP_KM / 111.0
    lon_step = GRID_STEP_KM / (111.0 * math.cos(math.radians(center_lat)))
    n = int(GRID_RANGE_KM / GRID_STEP_KM)
    steps: list[tuple[float, float]] = [(0.0, 0.0)]  # 中心を先頭（履歴 [0] と互換）
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            if i == 0 and j == 0:
                continue
            steps.append((i * lat_step, j * lon_step))
    return steps

# ═══════════════════════════════════════════════════════
#  API キー
# ═══════════════════════════════════════════════════════
PLACES_API_KEY = os.environ.get("PLACES_API_KEY", "AIzaSyCbbtEs5nch9n8LT663LC04ISju4duBgNc")

MIN_REVIEW_COUNT = 20
OUTPUT_FILE      = "index.html"
DEMO_BASE_URL    = "https://cafe-model.vercel.app"

# ═══════════════════════════════════════════════════════
#  業種リスト（英語エリア用）
# ═══════════════════════════════════════════════════════
BUSINESS_TYPES_EN = [
    {"label": "Plumber",      "search_mode": "text", "text_query": "plumber plumbing service"},
    {"label": "Electrician",  "search_mode": "text", "text_query": "electrician electrical service"},
    {"label": "Roofing",      "search_mode": "text", "text_query": "roofing roof repairs"},
    {"label": "HVAC",         "search_mode": "text", "text_query": "hvac heating cooling air conditioning"},
    {"label": "Landscaping",  "search_mode": "text", "text_query": "landscaping lawn mowing garden"},
    {"label": "Pest Control", "search_mode": "text", "text_query": "pest control termite inspection"},
]

# ═══════════════════════════════════════════════════════
#  業種リスト（日本語エリア用）
# ═══════════════════════════════════════════════════════
BUSINESS_TYPES_JA = [
    {"label": "カフェ",          "search_mode": "text", "text_query": "カフェ"},
    {"label": "歯科医院",        "search_mode": "text", "text_query": "歯科 歯医者"},
    {"label": "接骨院・整体",    "search_mode": "text", "text_query": "整体 接骨院"},
    {"label": "ピアノ教室",      "search_mode": "text", "text_query": "ピアノ教室"},
    {"label": "工務店",          "search_mode": "text", "text_query": "工務店 リフォーム"},
    {"label": "ペットサロン",    "search_mode": "text", "text_query": "ペットサロン トリミング"},
    {"label": "動物病院",        "search_mode": "text", "text_query": "動物病院 ペットクリニック"},
    {"label": "美容室",          "search_mode": "text", "text_query": "美容室 ヘアサロン"},
    {"label": "ヨガスタジオ",    "search_mode": "text", "text_query": "ヨガスタジオ"},
    {"label": "フラワーショップ", "search_mode": "text", "text_query": "フラワーショップ 花屋"},
]

# ═══════════════════════════════════════════════════════
#  候補エリアリスト（順番に自動展開）
#  同時並行で探索するエリア数を MAX_ACTIVE_AREAS で制御
# ═══════════════════════════════════════════════════════
MAX_ACTIVE_AREAS = 4   # 同時に進めるエリア数（1=直列, 2=2都市並行, ...）

ALL_CANDIDATE_LOCATIONS = [
    # ── 英語圏（オーストラリア） ──────────────────────────
    {"name": "Melbourne",      "latitude": -37.8136, "longitude": 144.9631, "business_types": BUSINESS_TYPES_EN},
    {"name": "Sydney",         "latitude": -33.8688, "longitude": 151.2093, "business_types": BUSINESS_TYPES_EN},
    {"name": "Brisbane",       "latitude": -27.4698, "longitude": 153.0251, "business_types": BUSINESS_TYPES_EN},
    {"name": "Perth",          "latitude": -31.9505, "longitude": 115.8605, "business_types": BUSINESS_TYPES_EN},
    {"name": "Adelaide",       "latitude": -34.9285, "longitude": 138.6007, "business_types": BUSINESS_TYPES_EN},
    {"name": "Gold Coast",     "latitude": -28.0167, "longitude": 153.4000, "business_types": BUSINESS_TYPES_EN},
    {"name": "Canberra",       "latitude": -35.2809, "longitude": 149.1300, "business_types": BUSINESS_TYPES_EN},
    {"name": "Newcastle",      "latitude": -32.9283, "longitude": 151.7817, "business_types": BUSINESS_TYPES_EN},
    {"name": "Wollongong",     "latitude": -34.4278, "longitude": 150.8931, "business_types": BUSINESS_TYPES_EN},
    {"name": "Geelong",        "latitude": -38.1499, "longitude": 144.3617, "business_types": BUSINESS_TYPES_EN},
    {"name": "Hobart",         "latitude": -42.8821, "longitude": 147.3272, "business_types": BUSINESS_TYPES_EN},
    {"name": "Sunshine Coast", "latitude": -26.6500, "longitude": 153.0667, "business_types": BUSINESS_TYPES_EN},
    {"name": "Cairns",         "latitude": -16.9186, "longitude": 145.7781, "business_types": BUSINESS_TYPES_EN},
    {"name": "Townsville",     "latitude": -19.2576, "longitude": 146.8239, "business_types": BUSINESS_TYPES_EN},
    {"name": "Ballarat",       "latitude": -37.5622, "longitude": 143.8503, "business_types": BUSINESS_TYPES_EN},
    {"name": "Darwin",         "latitude": -12.4634, "longitude": 130.8456, "business_types": BUSINESS_TYPES_EN},
    # ── 日本語圏 ─────────────────────────────────────────
    {"name": "広島",   "latitude": 34.3853, "longitude": 132.4553, "business_types": BUSINESS_TYPES_JA},
    {"name": "福岡",   "latitude": 33.5902, "longitude": 130.4017, "business_types": BUSINESS_TYPES_JA},
    {"name": "名古屋", "latitude": 35.1815, "longitude": 136.9066, "business_types": BUSINESS_TYPES_JA},
    {"name": "大阪",   "latitude": 34.6937, "longitude": 135.5023, "business_types": BUSINESS_TYPES_JA},
    {"name": "京都",   "latitude": 35.0116, "longitude": 135.7681, "business_types": BUSINESS_TYPES_JA},
    {"name": "神戸",   "latitude": 34.6901, "longitude": 135.1956, "business_types": BUSINESS_TYPES_JA},
    {"name": "仙台",   "latitude": 38.2682, "longitude": 140.8694, "business_types": BUSINESS_TYPES_JA},
    {"name": "札幌",   "latitude": 43.0618, "longitude": 141.3545, "business_types": BUSINESS_TYPES_JA},
    {"name": "横浜",   "latitude": 35.4437, "longitude": 139.6380, "business_types": BUSINESS_TYPES_JA},
    {"name": "東京",   "latitude": 35.6762, "longitude": 139.6503, "business_types": BUSINESS_TYPES_JA},
    {"name": "千葉",   "latitude": 35.6073, "longitude": 140.1063, "business_types": BUSINESS_TYPES_JA},
    {"name": "岡山",   "latitude": 34.6551, "longitude": 133.9195, "business_types": BUSINESS_TYPES_JA},
    {"name": "熊本",   "latitude": 32.8031, "longitude": 130.7079, "business_types": BUSINESS_TYPES_JA},
    {"name": "静岡",   "latitude": 34.9769, "longitude": 138.3831, "business_types": BUSINESS_TYPES_JA},
    {"name": "新潟",   "latitude": 37.9161, "longitude": 139.0364, "business_types": BUSINESS_TYPES_JA},
    {"name": "松山",   "latitude": 33.8395, "longitude": 132.7654, "business_types": BUSINESS_TYPES_JA},
    {"name": "那覇",   "latitude": 26.2124, "longitude": 127.6809, "business_types": BUSINESS_TYPES_JA},
    {"name": "鹿児島", "latitude": 31.5966, "longitude": 130.5571, "business_types": BUSINESS_TYPES_JA},
]

# 後方互換：SEARCH_LOCATIONS はそのまま残すが main() は ALL_CANDIDATE_LOCATIONS を使う
SEARCH_LOCATIONS = ALL_CANDIDATE_LOCATIONS


def get_active_locations(history: dict) -> list[dict]:
    """
    アクティブエリアを決定するルール:
      1. すでに検索を開始している（done > 0）エリアを優先的に継続
      2. 空きスロットが残っていれば、未着手エリアを順番に追加
      3. 合計 MAX_ACTIVE_AREAS 件を上限とする
    完了 = 全グリッドステップが history に記録済み → スキップ
    """
    in_progress: list[dict] = []
    not_started: list[dict] = []
    completed:   list[str]  = []

    for loc in ALL_CANDIDATE_LOCATIONS:
        grid_steps = make_grid_steps(loc["latitude"])
        done_cnt   = len(history.get(loc["name"], []))
        total      = len(grid_steps)
        if done_cnt >= total:
            completed.append(loc["name"])
        elif done_cnt > 0:
            in_progress.append(loc)   # 進行中 → 優先継続
        else:
            not_started.append(loc)   # 未着手 → スロットに余裕があれば追加

    # 進行中を優先 → 空きスロット分だけ未着手を追加
    active = in_progress[:MAX_ACTIVE_AREAS]
    remaining_slots = MAX_ACTIVE_AREAS - len(active)
    if remaining_slots > 0:
        active.extend(not_started[:remaining_slots])

    if completed:
        print(f"✅ 完了済みエリア ({len(completed)}): {', '.join(completed)}")
    if in_progress:
        print(f"🔄 進行中エリア ({len(in_progress)}): {', '.join(l['name'] for l in in_progress)}")
    if active and remaining_slots > 0 and not_started:
        new_areas = not_started[:remaining_slots]
        print(f"🆕 新規開始エリア: {', '.join(l['name'] for l in new_areas)}")
    if active:
        print(f"🔍 今回アクティブ ({len(active)}): {', '.join(l['name'] for l in active)}")
    else:
        print("🎉 ALL_CANDIDATE_LOCATIONS の全エリアを探し尽くしました！")
    return active

# ═══════════════════════════════════════════════════════
#  Field Mask（コスト最小化）
# ═══════════════════════════════════════════════════════
FIELD_MASK = ",".join([
    "places.id",              # 重複排除に使用
    "places.displayName",
    "places.rating",
    "places.userRatingCount",
    "places.formattedAddress",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "nextPageToken",
])

TEXT_URL = "https://places.googleapis.com/v1/places:searchText"


# ═══════════════════════════════════════════════════════
#  Places API
# ═══════════════════════════════════════════════════════
def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": PLACES_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }

def _center(loc: dict) -> dict:
    return {"latitude": loc["latitude"], "longitude": loc["longitude"]}

MAX_PAGES = 3

def _search_text(loc: dict, text_query: str, page_token=None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": PLACES_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    payload = {
        "textQuery": text_query,
        "locationBias": {
            "circle": {
                "center": {"latitude": loc["latitude"], "longitude": loc["longitude"]},
                "radius": float(SEARCH_RADIUS_M),
            }
        },
    }
    if page_token:
        payload["pageToken"] = page_token
    resp = requests.post(TEXT_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()

def fetch_all(loc: dict, biz: dict) -> list:
    all_places, next_token, page = [], None, 0
    while page < MAX_PAGES:
        data = _search_text(loc, biz["text_query"], next_token)
        all_places.extend(data.get("places", []))
        page += 1
        next_token = data.get("nextPageToken")
        if not next_token:
            break
        time.sleep(2)
    return all_places

def filter_places(places: list) -> list:
    return [
        p for p in places
        if not p.get("websiteUri") and p.get("userRatingCount", 0) >= MIN_REVIEW_COUNT
    ]


def load_history() -> dict:
    """検索履歴をロード: {loc_name: [step_index, ...]}"""
    if os.path.exists(SEARCH_HISTORY_FILE):
        with open(SEARCH_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history: dict) -> None:
    with open(SEARCH_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_db() -> list[dict]:
    if os.path.exists(PLACES_DB_FILE):
        with open(PLACES_DB_FILE, "r", encoding="utf-8") as f:
            records = json.load(f)
        for r in records:
            if "contacted" not in r:
                r["contacted"] = False
        return records
    return []

def save_db(records: list[dict]) -> None:
    with open(PLACES_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


SERVICES_JSON_FILE = "lib/services.json"

def extract_suburb(address: str) -> str:
    """'123 Chapel St, South Yarra VIC 3141, Australia' → 'South Yarra'"""
    import re
    m = re.search(r",\s*([^,]+?)\s+(?:VIC|NSW|QLD|SA|WA|TAS|NT|ACT)\s+\d{4}", address)
    return m.group(1).strip() if m else address.split(",")[1].strip() if "," in address else address


def save_services_json(records: list[dict]) -> None:
    """places_db の内容を lib/services.json（新index.html用フォーマット）に書き出す"""
    os.makedirs("lib", exist_ok=True)

    # lib/services.json を読み込み、手動追加分（draftUrl / notes がある行）を保持する
    existing: dict[str, dict] = {}
    if os.path.exists(SERVICES_JSON_FILE):
        with open(SERVICES_JSON_FILE, "r", encoding="utf-8") as f:
            for item in json.load(f):
                existing[item["id"]] = item

    services = []
    processed_ids = set()

    for r in records:
        sid = r["id"]
        location = r.get("location", "")
        address  = r.get("address", "")
        suburb   = extract_suburb(address) or location
        gmaps    = f"https://www.google.com/maps/search/{urllib.parse.quote(r['name'] + ' ' + suburb)}"
        prev     = existing.get(sid, {})
        services.append({
            "id":            sid,
            "name":          r["name"],
            "category":      r["category"],
            "location":      location,
            "suburb":        suburb,
            "rating":        r.get("rating") or None,
            "reviewCount":   r.get("reviewCount") or None,
            "phone":         r.get("phone", ""),
            "status":        prev.get("status", "no_website"),
            "googleMapsUrl": prev.get("googleMapsUrl") or gmaps,
            "draftUrl":      prev.get("draftUrl", ""),
            "notes":         prev.get("notes", ""),
        })
        processed_ids.add(sid)

    # places_db にない既存レコード（手動追加分）を末尾に保持
    for sid, item in existing.items():
        if sid not in processed_ids:
            services.append(item)

    with open(SERVICES_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(services, f, ensure_ascii=False, indent=2)
    print(f"✅ {SERVICES_JSON_FILE} 保存完了 ({len(services)} 件)")

def record_from_place(p: dict, loc_name: str, label: str, is_ja: bool) -> dict:
    name = p.get("displayName", {}).get("text", "")
    return {
        "id":           p.get("id", ""),
        "name":         name,
        "location":     loc_name,
        "category":     label,
        "rating":       p.get("rating", ""),
        "reviewCount":  p.get("userRatingCount", ""),
        "address":      p.get("formattedAddress", ""),
        "phone":        p.get("nationalPhoneNumber", ""),
        "contacted":    False,
        "instagramUrl": instagram_url(name),
        "mailUrl":      mail_url_ja(name) if is_ja else mail_url(name),
    }


# ═══════════════════════════════════════════════════════
#  スラッグ生成
# ═══════════════════════════════════════════════════════
def slugify(name: str) -> str:
    """カフェ名 → URL スラッグ (例: "Café Felice" → "cafe-felice")"""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


# ═══════════════════════════════════════════════════════
#  URL 生成
# ═══════════════════════════════════════════════════════
def instagram_url(name: str) -> str:
    return f"https://www.instagram.com/explore/search/keyword/?q={urllib.parse.quote(name)}"

def mail_url(name: str, review_count: str = "") -> str:
    demo    = f"{DEMO_BASE_URL}/{slugify(name)}"
    subject = urllib.parse.quote(
        f"Free website demo for {name} — {review_count + ' reviews deserve a website' if review_count else 'Website Design Proposal'}"
    )
    body = urllib.parse.quote(
        f"Hi {name} team,\n\n"
        f"I came across {name} on Google Maps{' — ' + review_count + ' reviews and clearly a great spot!' if review_count else '!'} "
        "I noticed you don't have a website yet.\n\n"
        f"I built a free demo for you:\n{demo}\n\n"
        "A professional website could help you:\n"
        "  • Show up in Google searches (\"cafe near me\")\n"
        "  • Let customers check your menu & hours before visiting\n"
        "  • Accept online bookings\n\n"
        "Happy to chat for 10 minutes about it — no obligation.\n\n"
        "Best,\nMio"
    )
    # Gmail Webで開く（macOSでメールアプリ未設定でも動く）
    return f"https://mail.google.com/mail/?view=cm&fs=1&su={subject}&body={body}"

def mail_url_ja(name: str) -> str:
    demo    = f"{DEMO_BASE_URL}/{slugify(name)}"
    subject = urllib.parse.quote(f"{name}様 ／ ホームページ制作のご提案")
    body = urllib.parse.quote(
        f"はじめまして。\n\n{name}様のお店を拝見し、ご連絡いたしました。\n\n"
        f"貴店をイメージしたデモサイトをご用意しました：\n{demo}\n\n"
        "現在、貴店のホームページが見当たらなかったため、\n"
        "集客強化のためのWebサイト制作をご提案できればと思いご連絡しました。\n\n"
        "・スマートフォン対応のデザイン\n"
        "・Googleマップとの連携\n"
        "・SEO対策\n\n"
        "ご興味がございましたら、ぜひ一度お話しさせてください。\n\n"
        "よろしくお願いいたします。"
    )
    return f"https://mail.google.com/mail/?view=cm&fs=1&su={subject}&body={body}"


# ═══════════════════════════════════════════════════════
#  HTML 生成
# ═══════════════════════════════════════════════════════
CATEGORY_COLORS = {
    # 日本語
    "カフェ":          "bg-amber-100 text-amber-800",
    "歯科医院":        "bg-blue-100 text-blue-800",
    "接骨院・整体":    "bg-green-100 text-green-800",
    "ピアノ教室":      "bg-purple-100 text-purple-800",
    "工務店":          "bg-orange-100 text-orange-800",
    "ペットサロン":    "bg-pink-100 text-pink-800",
    "動物病院":        "bg-teal-100 text-teal-800",
    "美容室":          "bg-rose-100 text-rose-800",
    "ヨガスタジオ":    "bg-violet-100 text-violet-800",
    "フラワーショップ":"bg-lime-100 text-lime-800",
    # English
    "Cafe":         "bg-amber-100 text-amber-800",
    "Dentist":      "bg-blue-100 text-blue-800",
    "Chiropractor": "bg-green-100 text-green-800",
    "Music School": "bg-purple-100 text-purple-800",
    "Builder":      "bg-orange-100 text-orange-800",
    "Pet Grooming": "bg-pink-100 text-pink-800",
    "Vet":          "bg-teal-100 text-teal-800",
    "Hair Salon":   "bg-rose-100 text-rose-800",
    "Yoga Studio":  "bg-violet-100 text-violet-800",
    "Florist":      "bg-lime-100 text-lime-800",
}

LOCATION_COLORS = {
    "Melbourne": "bg-sky-100 text-sky-800",
    "広島":      "bg-rose-100 text-rose-800",
}

def build_places_json(records: list[dict]) -> str:
    # mailUrl はJS側の buildMailUrl() で動的生成するため除外（JSON軽量化）
    slim = [{k: v for k, v in r.items() if k != "mailUrl"} for r in records]
    # </script> がデータに含まれると HTML パーサーが script タグを早期終了させるため置換
    return json.dumps(slim, ensure_ascii=False).replace("</", "<\\/")

def generate_html(records: list[dict], generated_at: str) -> str:
    places_json = build_places_json(records)
    total       = len(records)
    locations   = list(dict.fromkeys(r["location"] for r in records))
    categories  = list(dict.fromkeys(r["category"] for r in records))

    def tab_buttons(items, filter_fn, extra_class=""):
        return "\n".join(
            f'<button onclick="{filter_fn}(\'{c}\')" data-val="{c}" '
            f'class="filter-btn {extra_class} px-3 py-1.5 rounded-full text-sm font-medium '
            f'border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 transition">{c}</button>'
            for c in items
        )

    loc_tabs = tab_buttons(locations, "setLocation", "loc-btn")
    cat_tabs = tab_buttons(categories, "setCategory", "cat-btn")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>営業リスト</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    .filter-btn.active {{ background:#1d4ed8; color:#fff; border-color:#1d4ed8; }}
    .tab-btn {{ border-bottom: 2px solid transparent; }}
    .tab-btn.tab-active {{ border-color:#1d4ed8; color:#1d4ed8; font-weight:600; }}
  </style>
</head>
<body class="bg-gray-50 min-h-screen">

  <!-- ヘッダー -->
  <div class="bg-gradient-to-r from-blue-700 to-indigo-700 text-white px-4 py-6 shadow">
    <div class="max-w-5xl mx-auto">
      <h1 class="text-2xl font-bold tracking-tight">🎯 営業リスト</h1>
      <p class="text-blue-200 text-sm mt-1">サイトなし店舗 ／ 生成日: {generated_at}</p>
      <div class="mt-3 flex flex-wrap gap-3 text-sm">
        <span class="bg-white/20 rounded-full px-3 py-1">全 <strong>{total}</strong> 件</span>
        <span class="bg-white/20 rounded-full px-3 py-1">表示中 <strong id="visibleCount">{total}</strong> 件</span>
        <button onclick="restoreAll()"
          class="bg-white/20 hover:bg-white/30 rounded-full px-3 py-1 transition text-xs">
          🔄 削除済みを復元
        </button>
        <button onclick="exportContacted()"
          class="bg-green-400/30 hover:bg-green-400/50 rounded-full px-3 py-1 transition text-xs">
          💾 送信済みIDを保存
        </button>
      </div>
    </div>
  </div>

  <!-- フィルター -->
  <div class="max-w-5xl mx-auto px-4 pt-4 space-y-2">
    <!-- エリア -->
    <div class="flex flex-wrap gap-2 items-center">
      <span class="text-xs text-gray-400 font-semibold w-10">エリア</span>
      <button onclick="setLocation('all')" data-val="all"
        class="filter-btn loc-btn active px-3 py-1.5 rounded-full text-sm font-medium border transition">
        すべて
      </button>
      {loc_tabs}
    </div>
    <!-- 業種 -->
    <div class="flex flex-wrap gap-2 items-center pb-2">
      <span class="text-xs text-gray-400 font-semibold w-10">業種</span>
      <button onclick="setCategory('all')" data-val="all"
        class="filter-btn cat-btn active px-3 py-1.5 rounded-full text-sm font-medium border transition">
        すべて
      </button>
      {cat_tabs}
    </div>
  </div>

  <!-- タブ -->
  <div class="max-w-5xl mx-auto px-4 flex gap-6 border-b border-gray-200 mt-3">
    <button id="tab-unsent" onclick="setTab('unsent')"
      class="tab-btn tab-active pb-2 pt-1 text-sm text-blue-600 transition whitespace-nowrap">
      📋 未送信 <span id="unsentCount">-</span>件
    </button>
    <button id="tab-sent" onclick="setTab('sent')"
      class="tab-btn pb-2 pt-1 text-sm text-gray-400 hover:text-gray-600 transition whitespace-nowrap">
      ✅ 送信済み <span id="sentCount">0</span>件
    </button>
  </div>

  <!-- カードグリッド -->
  <div id="cardGrid"
    class="max-w-5xl mx-auto px-4 py-4 pb-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
  </div>

  <script>
  const PLACES = {places_json};
  const DELETED_KEY = "sales_list_deleted_v2";
  const SENT_KEY    = "sales_list_sent_v1";
  const DEMO_BASE   = "https://cafe-model.vercel.app";
  let currentLocation = "all";
  let currentCategory = "all";
  let currentTab = "unsent";

  function slugify(s) {{
    return s.toLowerCase()
      .normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }}

  function buildMailUrl(p) {{
    const slug    = slugify(p.name);
    const demoUrl = `${{DEMO_BASE}}/${{slug}}`;
    const isJa    = p.location === "広島";
    let subject, body;
    if (isJa) {{
      subject = `${{p.name}}様 ／ ホームページ制作のご提案`;
      body =
        `はじめまして。\n\n${{p.name}}様のお店を拝見し、ご連絡いたしました。\n\n` +
        `貴店をイメージしたデモサイトをご用意しました：\n${{demoUrl}}\n\n` +
        `現在、貴店のホームページが見当たらなかったため、集客強化のためのWebサイト制作をご提案できればと思いご連絡しました。\n\n` +
        `・スマートフォン対応のデザイン\n・Googleマップとの連携\n・SEO対策\n\n` +
        `ご興味がございましたら、ぜひ一度お話しさせてください。\n\nよろしくお願いいたします。`;
    }} else {{
      subject = `Free website demo for ${{p.name}} — ${{p.reviewCount || ""}} reviews deserve a website`;
      body =
        `Hi ${{p.name}} team,\n\nI came across ${{p.name}} on Google Maps — ${{p.reviewCount || "many"}} reviews and clearly a great spot! I noticed you don't have a website yet.\n\n` +
        `I built a free demo for you:\n${{demoUrl}}\n\n` +
        `A professional website could help you:\n` +
        `  • Show up in Google searches ("cafe near me")\n` +
        `  • Let customers check your menu & hours before visiting\n` +
        `  • Accept online bookings\n\n` +
        `Happy to chat for 10 minutes about it — no obligation.\n\nBest,\nMio`;
    }}
    // Gmail Webで開く（macOSでメールアプリ未設定でも動く）
    const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1` +
      `&su=${{encodeURIComponent(subject)}}` +
      `&body=${{encodeURIComponent(body)}}`;
    return gmailUrl;
  }}

  const CAT_COLORS = {json.dumps(CATEGORY_COLORS, ensure_ascii=False)};
  const LOC_COLORS = {json.dumps(LOCATION_COLORS, ensure_ascii=False)};

  function getDeleted() {{ return new Set(JSON.parse(localStorage.getItem(DELETED_KEY) || "[]")); }}
  function saveDeleted(s) {{ localStorage.setItem(DELETED_KEY, JSON.stringify([...s])); }}
  function getSent() {{ return new Set(JSON.parse(localStorage.getItem(SENT_KEY) || "[]")); }}
  function saveSent(s) {{ localStorage.setItem(SENT_KEY, JSON.stringify([...s])); }}

  function renderCard(p, sent) {{
    const catColor = CAT_COLORS[p.category] || "bg-gray-100 text-gray-700";
    const locColor = LOC_COLORS[p.location]  || "bg-slate-100 text-slate-700";
    const stars = p.rating
      ? `<span class="text-yellow-400">${{"★".repeat(Math.round(p.rating))}}</span>
         <span class="font-semibold text-gray-700 ml-1">${{p.rating}}</span>`
      : `<span class="text-gray-400 text-xs">No rating</span>`;
    const reviews = p.reviewCount ? `<span class="text-gray-400 text-xs ml-2">(${{p.reviewCount}})</span>` : "";
    const isSent = p.contacted === true || sent.has(p.id);
    const cardBorder = isSent ? "border-green-300 bg-green-50" : "border-gray-100 bg-white";
    const sentBtn = isSent
      ? `<button onclick="toggleSent('${{p.id}}')" class="w-full text-center text-sm font-medium bg-green-500 text-white rounded-xl py-2 hover:bg-green-600 transition">✅ 送信済み</button>`
      : `<button onclick="toggleSent('${{p.id}}')" class="w-full text-center text-sm font-medium bg-gray-100 text-gray-500 rounded-xl py-2 hover:bg-gray-200 transition">📤 送信済みにする</button>`;

    return `
      <div id="card-${{p.id}}" data-loc="${{p.location}}" data-cat="${{p.category}}"
        class="rounded-2xl shadow-sm border ${{cardBorder}} p-4 flex flex-col gap-3">
        <div class="flex items-start justify-between gap-2">
          <div class="flex flex-wrap gap-1">
            <span class="text-xs font-semibold px-2 py-0.5 rounded-full ${{locColor}}">${{p.location}}</span>
            <span class="text-xs font-semibold px-2 py-0.5 rounded-full ${{catColor}}">${{p.category}}</span>
          </div>
          <button onclick="deleteCard('${{p.id}}')"
            class="text-gray-300 hover:text-red-400 text-xl leading-none font-bold shrink-0"
            title="削除">×</button>
        </div>

        <div>
          <h2 class="text-base font-bold text-gray-900 leading-snug">${{p.name}}</h2>
          <div class="flex items-center mt-1">${{stars}}${{reviews}}</div>
        </div>

        <p class="text-gray-500 text-xs leading-relaxed">📍 ${{p.address || "—"}}</p>

        <div class="flex gap-2 pt-1 mt-auto">
          <a href="${{p.instagramUrl}}" target="_blank"
            class="flex-1 text-center text-sm font-medium bg-gradient-to-r from-pink-500 to-purple-500
                   text-white rounded-xl py-2 hover:opacity-90 transition">
            📸 Instagram
          </a>
          <a href="${{buildMailUrl(p)}}"
            class="flex-1 text-center text-sm font-medium bg-blue-600 text-white
                   rounded-xl py-2 hover:bg-blue-700 transition">
            ✉ メール送信
          </a>
        </div>
        <div>${{sentBtn}}</div>
      </div>`;
  }}

  function setTab(tab) {{
    currentTab = tab;
    const uBtn = document.getElementById("tab-unsent");
    const sBtn = document.getElementById("tab-sent");
    uBtn.classList.toggle("tab-active", tab === "unsent");
    uBtn.classList.toggle("text-blue-600", tab === "unsent");
    uBtn.classList.toggle("text-gray-400", tab !== "unsent");
    sBtn.classList.toggle("tab-active", tab === "sent");
    sBtn.classList.toggle("text-blue-600", tab === "sent");
    sBtn.classList.toggle("text-gray-400", tab !== "sent");
    render();
  }}

  function render() {{
    const deleted = getDeleted();
    const sent    = getSent();
    const grid    = document.getElementById("cardGrid");
    grid.innerHTML = "";
    let unsentTotal = 0, sentTotal = 0, shown = 0;

    PLACES.forEach(p => {{
      if (deleted.has(p.id)) return;
      if (currentLocation !== "all" && p.location !== currentLocation) return;
      if (currentCategory !== "all" && p.category !== currentCategory) return;

      const isSent = p.contacted === true || sent.has(p.id);
      if (isSent) sentTotal++; else unsentTotal++;

      if ((currentTab === "unsent" && !isSent) || (currentTab === "sent" && isSent)) {{
        grid.insertAdjacentHTML("beforeend", renderCard(p, sent));
        shown++;
      }}
    }});

    document.getElementById("unsentCount").textContent = unsentTotal;
    document.getElementById("sentCount").textContent   = sentTotal;
    document.getElementById("visibleCount").textContent = shown;

    if (shown === 0) {{
      const msg = currentTab === "unsent"
        ? (unsentTotal === 0 ? "✅ この条件の送信がすべて完了しました" : "該当する店舗がありません")
        : "送信済みの店舗がありません";
      grid.innerHTML = `<div class="col-span-3 text-center py-20 text-gray-400 text-sm">${{msg}}</div>`;
      if (currentTab === "unsent" && unsentTotal === 0) checkAutoAdvance();
    }}
  }}

  function checkAutoAdvance() {{
    if (currentLocation === "all") return;
    const locs = [...document.querySelectorAll(".loc-btn")]
      .map(b => b.dataset.val).filter(v => v !== "all");
    const idx = locs.indexOf(currentLocation);
    if (idx >= 0 && idx < locs.length - 1) {{
      const next = locs[idx + 1];
      setTimeout(() => {{
        if (confirm(`「${{currentLocation}}」の送信が完了！\n次のエリア「${{next}}」に切り替えますか？`)) {{
          setLocation(next);
        }}
      }}, 400);
    }} else if (idx === locs.length - 1) {{
      setTimeout(() => {{
        alert("すべてのエリアの送信が完了しました！\\nmulti_search.py を実行して新しいエリアを追加してください。");
      }}, 400);
    }}
  }}

  function deleteCard(id) {{
    const d = getDeleted(); d.add(id); saveDeleted(d); render();
  }}
  function toggleSent(id) {{
    const s = getSent();
    if (s.has(id)) {{
      s.delete(id);
    }} else {{
      s.add(id);
      const p = PLACES.find(p => p.id === id);
      if (p) window.open(buildMailUrl(p), "_blank");
    }}
    saveSent(s); render();
  }}
  function restoreAll() {{ localStorage.removeItem(DELETED_KEY); render(); }}

  function exportContacted() {{
    const sent = getSent();
    // JSON contacted の true なものも含める
    const contactedIds = PLACES
      .filter(p => p.contacted === true || sent.has(p.id))
      .map(p => p.id);
    if (contactedIds.length === 0) {{ alert("送信済みの店舗がありません"); return; }}
    const blob = new Blob([JSON.stringify(contactedIds, null, 2)], {{type: "application/json"}});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "contacted_ids.json";
    a.click();
    alert(`${{contactedIds.length}}件の送信済みIDを保存しました。\\ncafе-search フォルダに contacted_ids.json を置いて\\npython multi_search.py を実行すると次回も反映されます。`);
  }}

  function setLocation(val) {{
    currentLocation = val;
    document.querySelectorAll(".loc-btn").forEach(b => b.classList.toggle("active", b.dataset.val === val));
    setTab("unsent");
  }}
  function setCategory(val) {{
    currentCategory = val;
    document.querySelectorAll(".cat-btn").forEach(b => b.classList.toggle("active", b.dataset.val === val));
    render();
  }}

  render();
  </script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════
#  メイン
# ═══════════════════════════════════════════════════════
CONTACTED_IDS_FILE = "contacted_ids.json"


def load_contacted_ids() -> set[str]:
    """ブラウザからエクスポートした送信済みIDセットを読み込む"""
    if os.path.exists(CONTACTED_IDS_FILE):
        with open(CONTACTED_IDS_FILE, "r", encoding="utf-8") as f:
            ids = json.load(f)
        print(f"📩 {CONTACTED_IDS_FILE} から {len(ids)} 件の送信済みIDを読み込みました")
        return set(ids)
    return set()


def main():
    history = load_history()

    # ── アクティブエリアを自動決定（完了済みはスキップして次の都市へ）──
    active_locations = get_active_locations(history)
    if not active_locations:
        print("🎉 ALL_CANDIDATE_LOCATIONS の全エリアを探し尽くしました！")
        print("   新しい都市を ALL_CANDIDATE_LOCATIONS に追加してください。")
        return

    # 各アクティブエリアで次に検索すべきグリッドステップを決定
    search_plan = []
    for loc in active_locations:
        grid_steps = make_grid_steps(loc["latitude"])
        done = set(history.get(loc["name"], []))
        for i, (dlat, dlon) in enumerate(grid_steps):
            if i not in done:
                search_plan.append((loc, i, dlat, dlon))
                break

    if not search_plan:
        print("すべてのアクティブエリアの検索が完了しています。")
        return

    print(f"=== 営業リスト生成 ===")
    for loc, step_i, dlat, dlon in search_plan:
        lat = loc["latitude"] + dlat
        lon = loc["longitude"] + dlon
        grid_steps = make_grid_steps(loc["latitude"])
        print(f"📍 {loc['name']} グリッド[{step_i}/{len(grid_steps)-1}] ({lat:.4f}, {lon:.4f}), 半径 {SEARCH_RADIUS_M}m")
    total_api_calls = sum(len(loc["business_types"]) for loc, *_ in search_plan)
    print(f"予定APIコール数: {total_api_calls}+\n")

    db        = load_db()
    seen_ids  = {r["id"] for r in db if r.get("id")}
    seen_keys = {(r["name"], r["address"]) for r in db}

    # contacted_ids.json があれば送信済みフラグを反映
    contacted_ids = load_contacted_ids()
    if contacted_ids:
        for r in db:
            if r["id"] in contacted_ids:
                r["contacted"] = True
        print(f"  ✅ contacted=True に設定: {sum(1 for r in db if r['contacted'])} 件\n")

    print(f"📂 既存DB: {len(db)} 件 ({PLACES_DB_FILE})\n")

    call_count = 0
    new_count  = 0

    for loc, step_i, dlat, dlon in search_plan:
        search_loc = {
            **loc,
            "latitude":  loc["latitude"]  + dlat,
            "longitude": loc["longitude"] + dlon,
        }
        is_ja = loc["business_types"] is BUSINESS_TYPES_JA
        grid_steps = make_grid_steps(loc["latitude"])
        print(f"\n📍 {loc['name']} グリッド[{step_i}/{len(grid_steps)-1}] ({search_loc['latitude']:.4f}, {search_loc['longitude']:.4f})")

        for biz in loc["business_types"]:
            call_count += 1
            label = biz["label"]
            print(f"  [{call_count}/{total_api_calls}] {label} ...", end=" ", flush=True)
            try:
                places   = fetch_all(search_loc, biz)
                filtered = filter_places(places)
                added = []
                for p in filtered:
                    pid  = p.get("id", "")
                    name = p.get("displayName", {}).get("text", "")
                    addr = p.get("formattedAddress", "")
                    key  = (name, addr)
                    if pid and pid not in seen_ids and key not in seen_keys:
                        seen_ids.add(pid)
                        seen_keys.add(key)
                        rec = record_from_place(p, loc["name"], label, is_ja)
                        db.append(rec)
                        added.append(rec)
                new_count += len(added)
                print(f"{len(places)}件取得 → フィルター{len(filtered)}件 → 新規追加{len(added)}件")
            except requests.HTTPError as e:
                print(f"ERROR {e.response.status_code}: {e.response.text[:120]}")
            time.sleep(1)

        # このステップを完了済みに記録
        if loc["name"] not in history:
            history[loc["name"]] = []
        history[loc["name"]].append(step_i)

    print(f"\n今回の新規追加: {new_count} 件 / 累積合計: {len(db)} 件")
    save_db(db)
    print(f"💾 {PLACES_DB_FILE} 保存完了")

    save_history(history)
    print(f"💾 {SEARCH_HISTORY_FILE} 保存完了")

    # ── 進捗サマリー ─────────────────────────────────────
    print("\n📊 グリッド検索状況 (全候補エリア):")
    total_areas    = len(ALL_CANDIDATE_LOCATIONS)
    completed_cnt  = 0
    active_cnt     = 0
    for loc in ALL_CANDIDATE_LOCATIONS:
        grid_steps = make_grid_steps(loc["latitude"])
        done_cnt   = len(history.get(loc["name"], []))
        remain     = len(grid_steps) - done_cnt
        if remain == 0:
            status = "✅ 完了"
            completed_cnt += 1
        elif done_cnt > 0:
            status = f"🔍 進行中"
            active_cnt += 1
        else:
            status = "⏳ 未開始"
        print(f"  {loc['name']:10s}: {done_cnt:3d}/{len(grid_steps)} 完了 (残{remain:3d}) {status}")

    # 次に自動開始されるエリアを表示
    next_locs = get_active_locations(history)
    if next_locs:
        print(f"\n▶ 次回実行時のアクティブエリア: {', '.join(l['name'] for l in next_locs)}")
    print(f"\n合計: {completed_cnt}/{total_areas} エリア完了")

    save_services_json(db)
    print(f"Vercel: cd cafe-search && vercel --yes")


if __name__ == "__main__":
    main()
