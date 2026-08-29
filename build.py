import pandas as pd
import json
import re
import os
import datetime
import subprocess
import time
import urllib.request
from html.parser import HTMLParser

CSV_URL = "https://bookwalker.jp/csv/download.php"
FAQ_URL = "https://help.bookwalker.jp/faq/301"
LOCAL_CSV_PATH = "downloaded_data.csv"
HISTORY_FILE = "series_history.json"
CACHE_FILE = "cover_cache.json"

class OGImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image_url = ""

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            attrs_dict = dict(attrs)
            if attrs_dict.get("property") == "og:image":
                self.image_url = attrs_dict.get("content", "")

def fetch_bookwalker_og_image(item_url, cache={}):
    """作品ページから og:image（公式表紙画像URL）を取得"""
    if not isinstance(item_url, str) or not item_url.startswith("http"):
        return ""
    
    # キャッシュに存在するなら通信せずに返す
    if item_url in cache:
        return cache[item_url]

    try:
        req = urllib.request.Request(item_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=5) as res:
            html = res.read().decode('utf-8', errors='ignore')
            parser = OGImageParser()
            parser.feed(html)
            
            image_url = parser.image_url
            if image_url:
                cache[item_url] = image_url
                time.sleep(0.1)  # サーバー負荷軽減用ウェイト
                return image_url
    except Exception:
        pass

    cache[item_url] = ""
    time.sleep(0.05)
    return ""

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

def is_title_v1(title):
    if pd.isna(title):
        return False
    patterns = [r'[（(【\s]1[）)\s】]', r'1巻', r'第1巻', r'[\s]1$']
    for pat in patterns:
        if re.search(pat, str(title)):
            return True
    return False

def download_csv_with_curl():
    print(">>> [1/3] curl コマンドで CSV ファイルをダウンロード中...", flush=True)
    cmd = [
        "curl", "-sL",
        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-e", FAQ_URL,
        "--connect-timeout", "10",
        "--max-time", "30",
        "-o", LOCAL_CSV_PATH,
        CSV_URL
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0 or not os.path.exists(LOCAL_CSV_PATH) or os.path.getsize(LOCAL_CSV_PATH) == 0:
        raise RuntimeError(f"curl での CSV ダウンロードに失敗しました (Exit status: {result.returncode})")
    print(">>> CSVのダウンロード完了！", flush=True)

def fetch_csv_dataframe():
    download_csv_with_curl()

    for enc in ['cp932', 'shift_jis', 'utf-8']:
        try:
            return pd.read_csv(LOCAL_CSV_PATH, encoding=enc, low_memory=False)
        except Exception:
            continue

    raise ValueError("CSVのエンコーディング読み込みに失敗しました。")

def main():
    print(">>> スクリプト開始", flush=True)
    df = fetch_csv_dataframe()
    df.columns = df.columns.str.strip()

    title_col = [c for c in df.columns if 'タイトル' in c][0]
    series_col = [c for c in df.columns if 'シリーズ' in c][0]
    date_col = [c for c in df.columns if '配信日' in c][0]
    url_col = [c for c in df.columns if 'URL' in c][0]
    category_col = [c for c in df.columns if 'カテゴリ' in c][0]

    print(f">>> 元データ全件数: {len(df)} 件", flush=True)

    # 1. カテゴリ絞り込み（マンガ・コミックを対象）
    df = df[df[category_col].astype(str).str.contains('マンガ|コミック', na=False)]

    # 2. 日付絞り込み（先月〜来月）
    today = datetime.date.today()
    start_date = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1).strftime('%Y-%m-%d')
    end_date = (today.replace(day=28) + datetime.timedelta(days=60)).strftime('%Y-%m-%d')

    df[date_col] = df[date_col].astype(str).str.replace('/', '-')
    df = df[(df[date_col] >= start_date) & (df[date_col] <= end_date)]

    # 3. ノイズ除去（「話」「連載」「分冊」などをデフォルト除外）
    ignore_pattern = (
        r'無料|期間限定|お試し|試読|特別版|サンプル|増量|立読み|立ち読み|閲覧用|プロモーション|'
        r'単話|分冊|話売り|話版|【話】|（話）|\(話\)|話：|話\s*-|話\)|第\d+話|'
        r'連載|雑誌|定期購読|小冊子|特典|ペーパー|SS付き|イラスト付き|マイクロ|先行|予告'
    )
    df = df[~df[title_col].astype(str).str.contains(ignore_pattern, regex=True, na=False)]

    print(f">>> [2/3] 絞り込み後の処理対象件数: {len(df)} 件", flush=True)

    known_series = set(load_json_file(HISTORY_FILE) if isinstance(load_json_file(HISTORY_FILE), list) else [])
    cover_cache = load_json_file(CACHE_FILE)
    if not isinstance(cover_cache, dict):
        cover_cache = {}

    is_initial_run = len(known_series) == 0
    new_series_set = set(known_series)
    result = {}

    processed_count = 0

    print(">>> [3/3] BOOK☆WALKER ページから表紙画像URLを取得中...", flush=True)
    for _, row in df.iterrows():
        title = str(row.get(title_col, ''))
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

            item_url = str(row.get(url_col, ''))
            image_url = fetch_bookwalker_og_image(item_url, cover_cache)

            result[month].append({
                "title": title,
                "url": item_url,
                "image": image_url,
                "publisher": str(row.get('発行元', '')),
                "label": str(row.get('レーベル', '')),
                "category": str(row.get(category_col, '')).strip(),
                "series": series,
                "price": str(row.get('価格', '')),
                "release_date": rel_date,
                "is_new_series": is_new_series
            })
            processed_count += 1
            if processed_count % 50 == 0:
                print(f"    - {processed_count} 件処理完了...", flush=True)

    print(f">>> 最終抽出結果: {processed_count} 件のデータを登録しました。", flush=True)

    for month in result:
        result[month].sort(key=lambda x: x['release_date'])

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    months_list = sorted(list(result.keys()), reverse=True)
    with open('months.json', 'w', encoding='utf-8') as f:
        json.dump(months_list, f, ensure_ascii=False, indent=2)

    # 履歴と画像キャッシュを保存
    save_json_file(HISTORY_FILE, list(new_series_set))
    save_json_file(CACHE_FILE, cover_cache)

    if os.path.exists(LOCAL_CSV_PATH):
        os.remove(LOCAL_CSV_PATH)
    
    print(">>> すべての処理が正常完了しました！", flush=True)

if __name__ == '__main__':
    main()
