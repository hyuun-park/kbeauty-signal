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

TARGET_SUBREDDITS = ["AsianBeauty", "SkincareAddiction", "kbeauty", "30PlusSkinCare"]
SEARCH_QUERY = "cream OR serum OR moisturizer"

COMPLAINT_KEYWORDS = [
    # 무겁고 기름진 텍스처
    "sticky", "greasy", "heavy", "too heavy", "thick", "too thick",
    "oily", "too oily", "shiny", "too shiny", "suffocating",
    "feels suffocating", "coated", "film-like", "sits on skin",
    "doesn't absorb", "not absorbing", "midday shine",
    "gets greasy later", "sticky after a few hours",
    "hydrating but heavy", "too greasy under makeup",
    "good for winter only", "too rich for daytime",
    # 민감/장벽 손상
    "reactive skin", "damaged barrier", "skin barrier",
    "over exfoliated", "raw skin", "sensitive now",
    "skin freaked out", "redness", "irritated", "stings",
    "burned", "allergic", "inflamed", "tight skin",
    "compromised barrier", "nothing works anymore",
    "trying to repair my barrier", "my skin became sensitive",
    "my skin is angry", "skin needs a reset",
    # 루틴 피로
    "overwhelmed", "too many steps", "routine fatigue",
    "minimal routine", "simplified my routine", "less is more",
    "skin cycling", "tired of layering", "skincare exhaustion",
    "i just want something simple", "my routine got out of control",
    "i quit using actives", "i need fewer products",
    # 기후/날씨
    "humid weather", "florida humidity", "summer skincare",
    "hot climate", "sweaty", "melts off", "too shiny in humidity",
    "works in winter but not summer", "too heavy for humid weather",
    "melts off during the day", "humid climate skincare",
    # 메이크업 궁합
    "makeup pills", "pilling", "layers badly", "separates foundation",
    "balls up", "doesn't layer well",
    "looks good alone but pills under makeup",
    "foundation separates after sunscreen",
    # 트러블
    "broke me out", "breaks me out", "clogs pores", "clogging",
    "milia", "purging", "forehead breakout", "fungal acne",
    "fa safe", "hydrating but clogs pores", "caused bumps",
    # 효과 없음
    "not effective", "disappointed", "overrated", "waste of money",
    "not worth it", "doesn't last", "too watery",
    "evaporates quickly", "light but ineffective",
    "felt nice but did nothing", "hydrating at first but disappears quickly",
    # 스킨케어 불안
    "skin anxiety", "afraid to try", "confused skin", "frustrated",
    "gave up on skincare", "my skin reacts to everything",
    "scared to try new products",
    # 소비자가 원하는 것 (긍정 신호)
    "breathable", "weightless", "comfortable", "calming", "soothing",
    "melts into skin", "healthy skin", "skin feels balanced",
    "lightweight hydration", "comfortable glow", "non greasy hydration",
    "cloud-like", "milky", "silky", "bouncy", "velvety", "cushiony",
    "watery gel", "elegant glow", "soft matte", "skin-like finish",
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
    headers = {"User-Agent": "Mozilla/5.0 kbeauty-signal-collector/1.0"}
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
CREDENTIALS_FILE = r"C:\Users\user\Downloads\kbeauty-signal-bc98d3cc8902.json"

def update_sheets(rows):
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
    elif os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, encoding="utf-8") as f:
            creds_dict = json.load(f)
    else:
        print("인증 파일을 찾을 수 없습니다.")
        sys.exit(1)
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
