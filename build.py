import pandas as pd
import json
import re
import os
import time
import glob
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

CSV_URL = "http://bookwalker.jp/csv/download.php"
HISTORY_FILE = "series_history.json"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "tmp_download")

def get_cover_image_url(book_url):
    if pd.isna(book_url):
        return ""
    match = re.search(r'bookwalker\.jp/([a-zA-Z0-9\-]+)', str(book_url))
    if match:
        uuid = match.group(1).rstrip('/')
        return f"https://c.bookwalker.jp/{uuid}/s.jpg"
    return ""

def is_title_v1(title):
    if pd.isna(title):
        return False
    patterns = [r'[（(【\s]1[）)\s】]', r'1巻', r'第1巻', r'[\s]1$']
    for pat in patterns:
        if re.search(pat, str(title)):
            return True
    return False

def load_series_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_series_history(history_set):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(history_set), f, ensure_ascii=False, indent=2)

def fetch_csv_dataframe():
    print("Headless Chromeを使ってCSVをダウンロード中...")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
    
    # 自動ダウンロード先ディレクトリの指定
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=options)
    
    try:
        # 1. FAQページにアクセスしてクッキー取得
        driver.get('https://help.bookwalker.jp/faq/301')
        time.sleep(3)
        
        # 2. CSVの直リンクへアクセスして自動ダウンロード発動
        driver.get(CSV_URL)
        time.sleep(10) # ダウンロード完了まで待機
    finally:
        driver.quit()

    # ダウンロードされたCSVファイルを検索
    csv_files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.csv"))
    if not csv_files:
        raise FileNotFoundError("CSVファイルのダウンロードに失敗しました。")

    downloaded_file = csv_files[0]
    print(f"ダウンロード完了: {downloaded_file}")

    # 文字コード判定と読み込み
    for enc in ['cp932', 'shift_jis', 'utf-8']:
        try:
            df = pd.read_csv(downloaded_file, encoding=enc)
            return df
        except Exception:
            continue
            
    raise ValueError("CSVのエンコーディング読み込みに失敗しました。")

def main():
    df = fetch_csv_dataframe()
    df.columns = df.columns.str.strip()

    category_col = [c for c in df.columns if 'カテゴリ' in c]
    cat_name = category_col[0] if category_col else df.columns[0]

    manga_df = df[df[cat_name].astype(str).str.contains('マンガ|コミック', na=False)].copy()

    known_series = load_series_history()
    is_initial_run = len(known_series) == 0

    new_series_set = set(known_series)
    result = {}

    title_col = [c for c in df.columns if 'タイトル' in c][0] if any('タイトル' in c for c in df.columns) else 'タイトル'
    series_col = [c for c in df.columns if 'シリーズ' in c][0] if any('シリーズ' in c for c in df.columns) else 'シリーズ'
    date_col = [c for c in df.columns if '配信日' in c][0] if any('配信日' in c for c in df.columns) else '配信日'
    url_col = [c for c in df.columns if 'URL' in c][0] if any('URL' in c for c in df.columns) else 'URL'

    for _, row in manga_df.iterrows():
        title = str(row.get(title_col, ''))
        series = str(row.get(series_col, '')).strip()
        rel_date = str(row.get(date_col, '')).strip().replace('/', '-')

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

            image_url = get_cover_image_url(row.get(url_col))

            result[month].append({
                "title": title,
                "url": str(row.get(url_col, '')),
                "image": image_url,
                "publisher": str(row.get('発行元', '')),
                "label": str(row.get('レーベル', '')),
                "series": series,
                "price": str(row.get('価格', '')),
                "release_date": rel_date,
                "is_new_series": is_new_series
            })

    for month in result:
        result[month].sort(key=lambda x: x['release_date'])

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    save_series_history(new_series_set)
    print("data.json および series_history.json の更新が正常に完了しました！")

if __name__ == '__main__':
    main()
