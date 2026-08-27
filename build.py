import pandas as pd
import json
import re
import os
import time
import glob
import datetime
import urllib.parse
import urllib.request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

CSV_URL = "http://bookwalker.jp/csv/download.php"
HISTORY_FILE = "series_history.json"
CACHE_FILE = "cover_cache.json"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "tmp_download")

def load_json_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_json_file(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_google_books_cover(title, publisher="", cache={}):
    """タイトルと出版社からGoogle Books APIを使って表紙画像URLを取得"""
    clean_title = re.sub(r'第?\d+[話巻].*', '', title)
    clean_title = re.sub(r'[（(【\[].*?[）)\]】]', '', clean_title).strip()
    if not clean_title:
        clean_title = title.strip()

    query_str = f"{clean_title} {publisher}".strip()
    
    if query_str in cache:
        return cache[query_str]

    encoded_query = urllib.parse.quote(query_str)
    url = f"https://www.googleapis.com/books/v1/volumes?q={encoded_query}&maxResults=1"
    
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode('utf-8'))
                
                if "items" in data and len(data["items"]) > 0:
                    volume_info = data["items"][0].get("volumeInfo", {})
                    image_links = volume_info.get("imageLinks", {})
                    
                    cover_url = image_links.get("thumbnail") or image_links.get("smallThumbnail") or ""
                    if cover_url:
                        cover_url = cover_url.replace("http://", "https://")
                        cache[query_str] = cover_url
                        time.sleep(0.3)
                        return cover_url
                
                cache[query_str] = ""
                time.sleep(0.3)
                return ""

        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait_time = (attempt + 1) * 3
                print(f"429 Limit. Waiting {wait_time}s for '{clean_title}'...")
                time.sleep(wait_time)
            else:
                break
        except Exception:
            break

    cache[query_str] = ""
    return ""

def is_title_v1(title):
    if pd.isna(title):
        return False
    patterns = [r'[（(【\s]1[）)\s】]', r'1巻', r'第1巻', r'[\s]1$']
    for pat in patterns:
        if re.search(pat, str(title)):
            return True
    return False

def is_trial_version(title):
    if pd.isna(title):
        return False
    ignore_keywords = [
        '無料', '期間限定', 'お試し', '試読', '特別版', 'サンプル', 
        '増量', '立読み', '立ち読み', '閲覧用', 'プロモーション',
        '単話', '分冊', '話売り', '【話】', '（話）', '(話)', '話：', '話 -',
        '小冊子', '特典', 'ペーパー', 'SS付き', 'イラスト付き',
        'マイクロ', '先行', '予告'
    ]
    title_str = str(title)
    return any(kw in title_str for kw in ignore_keywords)

def fetch_csv_dataframe():
    print("Headless Chromeを使ってCSVをダウンロード中...")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get('https://help.bookwalker.jp/faq/301')
        time.sleep(3)
        driver.get(CSV_URL)
        time.sleep(10)
    finally:
        driver.quit()

    csv_files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.csv"))
    if not csv_files:
        raise FileNotFoundError("CSVファイルのダウンロードに失敗しました。")

    downloaded_file = csv_files[0]

    for enc in ['cp932', 'shift_jis', 'utf-8']:
        try:
            return pd.read_csv(downloaded_file, encoding=enc, low_memory=False)
        except Exception:
            continue
            
    raise ValueError("CSVのエンコーディング読み込みに失敗しました。")

def main():
    df = fetch_csv_dataframe()
    df.columns = df.columns.str.strip()

    title_col = [c for c in df.columns if 'タイトル' in c][0]
    series_col = [c for c in df.columns if 'シリーズ' in c][0]
    date_col = [c for c in df.columns if '配信日' in c][0]
    url_col = [c for c in df.columns if 'URL' in c][0]
    category_col = [c for c in df.columns if 'カテゴリ' in c][0]

    # --- 高速化のための段階的フィルタリング ---

    # 1. カテゴリで絞り込み（マンガ・コミックのみ）
    df = df[df[category_col].astype(str).str.contains('マンガ|コミック', na=False)]

    # 2. 日付で絞り込み（先月〜来月までの3ヶ月分だけに限定）
    today = datetime.date.today()
    # 先月の1日
    start_date = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1).strftime('%Y-%m-%d')
    # 2ヶ月後の末日付近まで
    end_date = (today.replace(day=28) + datetime.timedelta(days=60)).strftime('%Y-%m-%d')

    df[date_col] = df[date_col].astype(str).str.replace('/', '-')
    df = df[(df[date_col] >= start_date) & (df[date_col] <= end_date)]

    print(f"対象期間（{start_date} 〜 {end_date}）のマンガ件数: {len(df)} 件")

    known_series = set(load_json_file(HISTORY_FILE) if isinstance(load_json_file(HISTORY_FILE), list) else [])
    cover_cache = load_json_file(CACHE_FILE)
    if not isinstance(cover_cache, dict):
        cover_cache = {}

    is_initial_run = len(known_series) == 0
    new_series_set = set(known_series)
    result = {}

    for _, row in df.iterrows():
        title = str(row.get(title_col, ''))

        # 3. 試し読み・単話・分冊・特典付きなどを除外
        if is_trial_version(title):
            continue

        series = str(row.get(series_col, '')).strip()
        rel_date = str(row.get(date_col, '')).strip()

        if not rel_date or len(rel_date) < 7:
            continue

        has_v1_title = is_title_v1(title)

        is_new_series = False
        if series and series != 'nan':
            if series not in known_series and not is_initial_run:
                is_new_series = True
            new_series_set.add(series)

        if has_v1_title or is_new_series:
            month = rel_date[:7]
            if month not in result:
                result[month] = []

            publisher = str(row.get('発行元', ''))
            category = str(row.get(category_col, '')).strip()
            
            # 必要な作品のみGoogle Books APIを叩く
            image_url = fetch_google_books_cover(title, publisher, cover_cache)

            result[month].append({
                "title": title,
                "url": str(row.get(url_col, '')),
                "image": image_url,
                "publisher": publisher,
                "label": str(row.get('レーベル', '')),
                "category": category,
                "series": series,
                "price": str(row.get('価格', '')),
                "release_date": rel_date,
                "is_new_series": is_new_series
            })

    for month in result:
        result[month].sort(key=lambda x: x['release_date'])

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    months_list = sorted(list(result.keys()), reverse=True)
    with open('months.json', 'w', encoding='utf-8') as f:
        json.dump(months_list, f, ensure_ascii=False, indent=2)

    save_json_file(HISTORY_FILE, list(new_series_set))
    save_json_file(CACHE_FILE, cover_cache)
    
    print("データ更新完了！")

if __name__ == '__main__':
    main()
