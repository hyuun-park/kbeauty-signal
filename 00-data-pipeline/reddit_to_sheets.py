"""
K-Beauty Reddit Collector → Google Sheets 자동 업데이트
매일 실행: 새 데이터만 1_Raw_Reviews 탭에 추가
"""

import json
import csv
import sys
import time
import os
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

import gspread
from google.oauth2.service_account import Credentials

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
SPREADSHEET_ID = "1sCzfdGTJg7C-vn6s8sKOXi4sikIzobKFunF0LtXPkYk"
SHEET_TAB_NAME = "1_Raw_Reviews"

TARGET_SUBREDDITS = ["AsianBeauty", "SkincareAddiction", "kbeauty"]
SEARCH_QUERY = "cream OR serum OR moisturizer"

COMPLAINT_KEYWORDS = [
    "heavy", "sticky", "greasy", "pilling", "broke me out",
    "not worth", "too thick", "clogs pores", "white cast",
    "doesn't absorb", "not absorbing", "flashback", "milia",
    "allergic", "irritated", "burned", "stings",
    "not effective", "disappointed", "waste", "overrated",
    "too oily", "breaks me out", "purging", "redness",
]

K_BEAUTY_BRANDS = [
    "cosrx", "laneige", "innisfree", "etude", "missha",
    "some by mi", "beauty of joseon", "anua", "skin1004",
    "dr.jart", "klairs", "round lab", "purito", "isntree",
    "abib", "axis-y", "mediheal", "torriden", "ma:nyo",
    "numbuzin", "aestura", "pyunkang yul",
]

PRODUCT_KEYWORDS = [
    "cream", "serum", "moisturizer", "essence", "ampoule",
    "gel cream", "sleeping mask", "toner", "sunscreen",
]

POSTS_PER_SUBREDDIT = 100
DELAY_SECONDS = 2


# ──────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────
def contains_any(text, keywords):
    t = text.lower()
    return any(k in t for k in keywords)

def detect_brand(text):
    t = text.lower()
    for brand in K_BEAUTY_BRANDS:
        if brand in t:
            return brand.title()
    return "Unknown"

def detect_product(text):
    t = text.lower()
    for kw in PRODUCT_KEYWORDS:
        if kw in t:
            return kw
    return "general"

def clean_text(text):
    return text.replace("\n", " ").replace("\t", " ").strip()[:500]

def epoch_to_date(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

def fetch_json(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode("utf-8"))


# ──────────────────────────────────────────────
# Reddit 수집
# ──────────────────────────────────────────────
def collect():
    rows = []
    for sub in TARGET_SUBREDDITS:
        print(f"[r/{sub}] 수집 중...")
        after = None
        collected = 0

        while collected < POSTS_PER_SUBREDDIT:
            url = (
                f"https://www.reddit.com/r/{sub}/search.json"
                f"?q={SEARCH_QUERY.replace(' ', '+')}"
                f"&sort=new&t=week&limit=25&restrict_sr=1"
            )
            if after:
                url += f"&after={after}"

            try:
                data = fetch_json(url)
            except URLError as e:
                print(f"  오류: {e}")
                break

            posts = data.get("data", {}).get("children", [])
            if not posts:
                break

            for post in posts:
                p = post.get("data", {})
                title = p.get("title", "")
                body = p.get("selftext", "")
                full_text = f"{title} {body}"

                if not contains_any(full_text, COMPLAINT_KEYWORDS):
                    continue

                rows.append([
                    epoch_to_date(p.get("created_utc", 0)),
                    "Reddit",
                    f"r/{sub}",
                    detect_product(full_text),
                    detect_brand(full_text),
                    "N/A",
                    clean_text(f"{title} — {body}"),
                    f"https://reddit.com{p.get('permalink', '')}",
                ])
                collected += 1

            after = data.get("data", {}).get("after")
            if not after:
                break
            time.sleep(DELAY_SECONDS)

        print(f"  완료: {len(rows)}개 누적")

    return rows


# ──────────────────────────────────────────────
# Google Sheets 업데이트
# ──────────────────────────────────────────────
def update_sheets(rows):
    # GitHub Actions에서는 환경변수로 서비스 계정 JSON 주입
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        print("GOOGLE_CREDENTIALS 환경변수가 없습니다.")
        sys.exit(1)

    creds_dict = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)

    sheet = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_TAB_NAME)

    # 기존 링크 목록 가져오기 (중복 방지)
    existing = sheet.col_values(8)  # Link 열 (H열 = 8번째)
    existing_links = set(existing[1:])  # 헤더 제외

    new_rows = [r for r in rows if r[7] not in existing_links]

    if not new_rows:
        print("새로운 데이터 없음 — 시트 업데이트 건너뜀")
        return

    sheet.append_rows(new_rows, value_input_option="USER_ENTERED")
    print(f"시트에 {len(new_rows)}개 추가 완료")


# ──────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────
def main():
    print(f"실행 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    rows = collect()

    if not rows:
        print("수집된 데이터 없음")
        return

    print(f"\n총 {len(rows)}개 수집 → 시트 업데이트 중...")
    update_sheets(rows)
    print("완료")


if __name__ == "__main__":
    main()
