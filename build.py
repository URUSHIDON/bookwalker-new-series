import pandas as pd
import json
import re
import os
import time
import datetime
import subprocess
import urllib.request
import urllib.error
import unicodedata
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def fetch_single_og_image(item_url, delay=0.3, max_retries=2):
    if not isinstance(item_url, str) or not item_url.startswith("http"):
        return item_url, ""

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Referer': 'https://bookwalker.jp/',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1'
    }

    for attempt in range(max_retries + 1):
        if delay > 0:
            time.sleep(delay)

        try:
            req = urllib.request.Request(item_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as res:
                parser = OGImageParser()
                while True:
                    chunk = res.read(8192)
                    if not chunk:
                        break
                    parser.feed(chunk.decode('utf-8', errors='ignore'))
                    if parser.image_url:
                        break
                return item_url, parser.image_url
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                if attempt < max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if e.code == 429:
                    print(f"    ⚠️ [429 Too Many Requests] リクエスト過多エラー: {item_url}", flush=True)
                else:
                    print(f"    ⚠️ [403 Forbidden] アクセス拒否: {item_url}", flush=True)
            elif e.code == 404:
                print(f"    ⚠️ [404 Not Found] ページ未公開/未登録: {item_url}", flush=True)
                break
            else:
                if attempt < max_retries:
                    time.sleep(0.5)
                    continue
                print(f"    ⚠️ [HTTPエラー {e.code}] {item_url}", flush=True)
        except urllib.error.URLError as e:
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            print(f"    ⚠️ [接続/タイムアウトエラー: {e.reason}] {item_url}", flush=True)
        except Exception as e:
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            print(f"    ⚠️ [予期せぬエラー: {e}] {item_url}", flush=True)

    return item_url, ""

def fetch_all_og_images_parallel(url_list, cache, max_workers=3):
    targets = [url for url in set(url_list) if url and url.startswith("http") and not cache.get(url)]
    
    if targets:
        print(f">>> [画像取得] 未取得・再取得対象の {len(targets)} 件を並列通信で取得中 (並列数: {max_workers})...", flush=True)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(fetch_single_og_image, url, 0.3): url for url in targets}
            completed = 0
            success_count = 0
            for future in as_completed(future_to_url):
                url, img_url = future.result()
                if img_url:
                    cache[url] = img_url
                    success_count += 1
                completed += 1
                if completed % 50 == 0 or completed == len(targets):
                    print(f"    - {completed}/{len(targets)} 件完了 (成功: {success_count} 件)", flush=True)
    else:
        print(">>> [画像取得] すべてキャッシュから取得完了！", flush=True)

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
    if not title or pd.isna(title):
        return False
    
    # 1. 全角英数・全角スペース・全角記号を半角に正規化
    title_str = unicodedata.normalize('NFKC', str(title)).strip()
    
    # 文頭の【最新刊】などの接頭辞を除去
    title_clean = re.sub(r'^【最新刊】\s*', '', title_str)

    # -------------------------------------------------------------
    # ステップ1: 明確な【2巻以降・2話以降・他巻】の除外ルール
    # -------------------------------------------------------------
    # 1-1. 括弧内の2以上の数字: (2)〜, （11）, 【241】, [2] など
    if re.search(r'[（\(【\[]\s*(?:[2-9]|\d{2,})\s*[）\)】\]]', title_clean):
        return False

    # 1-2. 2以上の巻数・話数・エピソード単位
    # 例: 2巻, 第11巻, 61話, 第23話, 32コマ目, 31限目, 40流し目, 第94講義, 57発目 など
    ep_units = r'(?:巻|話|号(?!室|車)|コマ|コマ目|限目|流し目|発目|講義|狩|食|試合|回|弾)'
    if re.search(r'(?<!\d)(?:第\s*)?(?:[2-9]|\d{2,})\s*' + ep_units, title_clean):
        return False

    # 1-3. 英語表記のvol / season / part / ep / # + 2以上の数字 (例: vol.241, season 2, #2, ep.29, 2nd set)
    if re.search(r'(?i)(?:vol\.?|volume|ver\.?|part|season|#|ep\.?|episode)\s*(?:[2-9]|\d{2,})\b', title_clean):
        return False
    if re.search(r'(?i)(?:[2-9]|\d{2,})\s*(?:st|nd|rd|th)\s*(?:set|season|part|ep)', title_clean):
        return False

    # 1-4. ハイフン前の2以上の数字 (例: "10 - (1)", "11 - (1)")
    if re.search(r'(?<!\d)(?:[2-9]|\d{2,})\s*[-‐―ー]\s*[（\(【\[]1[）\)】\]]', title_clean):
        return False

    # 1-5. 末尾が2以上の数字、ローマ数字(II〜)、丸数字(②〜) (例: " 61", " 11", " 21", " 2", " II", " ②")
    if re.search(r'(?<!\d)(?:[2-9]|\d{2,3}|[2-9]\d{3,}(?<!20\d\d)(?<!19\d\d)|[Ⅱ-Ⅻ②-⑳])\s*$', title_clean):
        # 末尾の直前が単位（歳、年、日、分、秒、人、階級、度、章、位など）で終わっている場合は除外しない
        if not re.search(r'(?:階級|度|人|章|分|秒|日|年|位|歳)\s*$', title_clean):
            return False

    # -------------------------------------------------------------
    # ステップ2: 【巻数ではない1】の除外
    # -------------------------------------------------------------
    # 「SEASON 1」「PART 1」など（末尾にあり、かつ1巻/1話ではないもの）
    if re.search(r'(?i)(?:season|part|ver\.?|第)\s*1\s*$', title_clean):
        if not re.search(r'1\s*(?:巻|話)$', title_clean):
            return False
    # 「第1章」など
    if re.search(r'第\s*1\s*章', title_clean):
        return False

    # -------------------------------------------------------------
    # ステップ3: 明示的な【第1巻・第1話・第1弾】の合致判定 (True)
    # -------------------------------------------------------------
    # 3-1. 括弧で囲まれた1: (1), 【1】, [1]（※前後に数字が連続していないこと）
    if re.search(r'(?<!\d)[（\(【\[]\s*1\s*[）\)】\]](?!\d)', title_clean):
        return True

    # 3-2. 明示的な1巻・1話・第1巻・第1話: 1巻, 第1巻, 1話, 第1話, 1号
    if re.search(r'(?<!\d)(?:第\s*)?1\s*(?:巻|話|号)(?!\d)', title_clean):
        return True

    # 3-3. 【合冊版】1, 文頭の1巻/1話
    if re.search(r'【合冊版】\s*1(?!\d)', title_clean):
        return True
    if re.search(r'^1\s*(?:巻|話)(?!\d)', title_clean):
        return True

    # 3-4. vol.1, #1
    if re.search(r'(?i)(?:vol\.?|volume|#)\s*1(?!\d)', title_clean):
        return True

    # -------------------------------------------------------------
    # ステップ4: 【末尾の 1 / Ⅰ / ①】判定 (True)
    # -------------------------------------------------------------
    # 直前が英数字ではなく独立して置かれた 1 / Ⅰ / ① で終わる（例: "タイトル 1", "タイトル ①"）
    if re.search(r'(?<![0-9a-zA-Z])[1Ⅰ①]\s*$', title_clean):
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

    # 1. 日付判定（pd.to_datetime で厳密に日付型にして抽出）
    df['datetime_dt'] = pd.to_datetime(df[date_col], errors='coerce')
    
    today = datetime.date.today()
    start_date = pd.Timestamp(today.year, today.month, 1) - pd.DateOffset(months=1)
    end_date = (pd.Timestamp(today.year, today.month, 1) + pd.DateOffset(months=2)) - pd.Timedelta(days=1)

    df = df[(df['datetime_dt'] >= start_date) & (df['datetime_dt'] <= end_date)].copy()
    
    # 標準フォーマット (YYYY-MM-DD) に統一して日付列を上書き
    df[date_col] = df['datetime_dt'].dt.strftime('%Y-%m-%d')

    # 2. ノイズ除去
    ignore_pattern = (
        r'無料|期間限定|お試し|試読|特別版|サンプル|増量|立読み|立ち読み|閲覧用|プロモーション|'
        r'雑誌|定期購読|小冊子|先行|予告'
    )
    df = df[~df[title_col].astype(str).str.contains(ignore_pattern, regex=True, na=False)]

    print(f">>> [2/3] 絞り込み後の処理対象件数: {len(df)} 件", flush=True)

    # 既存の data.json から過去の初回登録日（registered_at）マップを復元
    existing_data = load_json_file('data.json')
    registered_map = {}
    if isinstance(existing_data, dict):
        for m_key, items in existing_data.items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get("url"):
                        registered_map[it["url"]] = it.get("registered_at") or today.strftime('%Y-%m-%d')

    known_series = set(load_json_file(HISTORY_FILE) if isinstance(load_json_file(HISTORY_FILE), list) else [])
    cover_cache = load_json_file(CACHE_FILE)
    if not isinstance(cover_cache, dict):
        cover_cache = {}

    is_initial_run = len(known_series) == 0
    new_series_set = set(known_series)
    target_items = []
    today_str = today.strftime('%Y-%m-%d')

    for _, row in df.iterrows():
        title = str(row.get(title_col, ''))
        raw_series = str(row.get(series_col, '')).strip()
        rel_date = str(row.get(date_col, '')).strip()

        if not rel_date or rel_date == 'nan':
            continue

        # シリーズ名から【最新刊】や(1)などの巻数表記を除去して正規化
        clean_series = re.sub(r'^【最新刊】\s*', '', raw_series)
        clean_series = re.sub(r'[（\(【\s\-_]*\d+[）\)】\s\-_話巻]*$', '', clean_series).strip()

        has_v1_title = is_title_v1(title)

        is_new_series = False
        if clean_series and clean_series != 'nan':
            # 1巻判定を通過している場合のみ「新シリーズ」判定を行う
            if clean_series not in known_series and not is_initial_run:
                if has_v1_title:
                    is_new_series = True
            new_series_set.add(clean_series)

        if has_v1_title or is_new_series:
            item_url = str(row.get(url_col, ''))
            reg_date = registered_map.get(item_url, today_str)
            target_items.append({
                "title": title,
                "url": item_url,
                "publisher": str(row.get('発行元', '')),
                "label": str(row.get('レーベル', '')),
                "category": str(row.get(category_col, '')).strip(),
                "series": raw_series,
                "price": str(row.get('価格', '')),
                "release_date": rel_date,
                "registered_at": reg_date,
                "is_v1": has_v1_title,
                "is_new_series": is_new_series
            })

    # 対象URLの画像を一括取得
    urls_to_fetch = [item["url"] for item in target_items]
    fetch_all_og_images_parallel(urls_to_fetch, cover_cache, max_workers=3)

    # 月ごとにグループ構築
    result = {}
    for item in target_items:
        month = item["release_date"][:7] # YYYY-MM
        if month not in result:
            result[month] = []

        item["image"] = cover_cache.get(item["url"], "")
        result[month].append(item)

    print(f">>> 最終抽出結果: {len(target_items)} 件のデータを登録しました。", flush=True)

    for month in result:
        result[month].sort(key=lambda x: x['release_date'])

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    months_list = sorted(list(result.keys()), reverse=True)
    with open('months.json', 'w', encoding='utf-8') as f:
        json.dump(months_list, f, ensure_ascii=False, indent=2)

    # 日本時間（JST）で現在日時を取得して出力
    jst = datetime.timezone(datetime.timedelta(hours=9))
    now_jst = datetime.datetime.now(jst)
    updated_str = now_jst.strftime('%Y年%m月%d日 %H:%M')

    # last_updated.json の出力（更新日時のみ）
    with open('last_updated.json', 'w', encoding='utf-8') as f:
        json.dump({
            "updated_at": updated_str
        }, f, ensure_ascii=False, indent=2)

    save_json_file(HISTORY_FILE, list(new_series_set))
    save_json_file(CACHE_FILE, {k: v for k, v in cover_cache.items() if v})

    if os.path.exists(LOCAL_CSV_PATH):
        os.remove(LOCAL_CSV_PATH)
    
    print(">>> すべての処理が正常完了しました！", flush=True)

if __name__ == '__main__':
    main()
