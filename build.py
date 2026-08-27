import pandas as pd
import json
import re
import os
import requests
import io

# BOOK☆WALKER全商品CSVの直接ダウンロードURL
CSV_URL = "http://bookwalker.jp/csv/download.php"
HISTORY_FILE = "series_history.json"

def get_cover_image_url(book_url):
    """作品URLから表紙画像サムネイルURLを生成"""
    if pd.isna(book_url):
        return ""
    match = re.search(r'bookwalker\.jp/([a-zA-Z0-9\-]+)', str(book_url))
    if match:
        uuid = match.group(1).rstrip('/')
        return f"https://c.bookwalker.jp/{uuid}/s.jpg"
    return ""

def is_title_v1(title):
    """タイトルから「1巻」表記を判定"""
    if pd.isna(title):
        return False
    patterns = [r'[（(【\s]1[）)\s】]', r'1巻', r'第1巻', r'[\s]1$']
    for pat in patterns:
        if re.search(pat, str(title)):
            return True
    return False

def load_series_history():
    """過去のシリーズ一覧履歴を読み込む"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_series_history(history_set):
    """更新されたシリーズ一覧履歴を保存する"""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(history_set), f, ensure_ascii=False, indent=2)

def fetch_csv_dataframe():
    """URLからCSVを取得してPandas DataFrameにする"""
    print(f"CSVを取得中: {CSV_URL}")
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(CSV_URL, headers=headers)
    res.raise_for_status()
    
    # CP932 / Shift_JIS または UTF-8 で読み込み
    try:
        return pd.read_csv(io.BytesIO(res.content), encoding='cp932')
    except Exception:
        return pd.read_csv(io.BytesIO(res.content), encoding='utf-8')

def main():
    # 1. CSVデータの取得
    df = fetch_csv_dataframe()
    df.columns = df.columns.str.strip()

    # 2. カテゴリでマンガのみ抽出
    manga_df = df[df['カテゴリ'].astype(str).str.contains('マンガ|コミック', na=False)].copy()

    # 3. 過去のシリーズ履歴をロード
    known_series = load_series_history()
    is_initial_run = len(known_series) == 0  # 初回実行フラグ

    new_series_set = set(known_series)
    result = {}

    for _, row in manga_df.iterrows():
        title = str(row.get('タイトル', ''))
        series = str(row.get('シリーズ', '')).strip()
        rel_date = str(row.get('配信日', '')).strip().replace('/', '-')

        if not rel_date or len(rel_date) < 7:
            continue

        # 判定1: タイトルに「1巻」表記があるか
        has_v1_title = is_title_v1(title)

        # 判定2: 過去に存在しない「新シリーズ」かどうか
        is_new_series = False
        if series and series != 'nan':
            if series not in known_series and not is_initial_run:
                is_new_series = True
            new_series_set.add(series)

        # 1巻または新シリーズの場合のみ抽出
        if has_v1_title or is_new_series:
            month = rel_date[:7] # YYYY-MM
            if month not in result:
                result[month] = []

            image_url = get_cover_image_url(row.get('URL'))

            result[month].append({
                "title": title,
                "url": str(row.get('URL', '')),
                "image": image_url,
                "publisher": str(row.get('発行元', '')),
                "label": str(row.get('レーベル', '')),
                "series": series,
                "price": str(row.get('価格', '')),
                "release_date": rel_date,
                "is_new_series": is_new_series
            })

    # 日付順にソート
    for month in result:
        result[month].sort(key=lambda x: x['release_date'])

    # Web表示用の JSON 出力
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 累積シリーズ履歴の保存
    save_series_history(new_series_set)

    print("data.json および series_history.json の更新が正常に完了しました！")

if __name__ == '__main__':
    main()