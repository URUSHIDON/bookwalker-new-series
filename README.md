# 📚 bookwalker-new-series

BOOK☆WALKER に登録された電子書籍の中から、**マンガ・ライトノベルなどの第1巻・新シリーズ**を自動で収集・一覧表示する静的 Web サイトです。

---

## 概要

毎日深夜3時（JST）に GitHub Actions が自動実行され、BOOK☆WALKER の配信予定 CSV から 1巻・新シリーズを抽出して `data.json` に蓄積します。表紙画像は BOOK☆WALKER の各作品ページから OGP 画像を並列取得してキャッシュし、`index.html` で一覧表示します。

---

## 主な機能

### データ収集（`build.py`）
- BOOK☆WALKER の配信予定 CSV を自動ダウンロード
- タイトルの正規表現による **第1巻判定**（「1巻」「第1巻」「(1)」「①」等の多様な表記に対応）
- 過去のシリーズ履歴との比較による **新シリーズ判定**
- 取得対象は先月・今月・翌月の約3ヶ月分
- 試し読み・雑誌・サンプル等のノイズを除外
- 書影画像（OGP）の並列取得・キャッシュ管理（再取得・リトライ対応）
- **書籍ごとの初回登録日（`registered_at`）を永続管理**

### Web 閲覧画面（`index.html`）
- 対象月の切り替え（プルダウン）
- タイトル・出版社のキーワード検索
- カテゴリ別絞り込み（マンガ / ライトノベル等）
- **新着フィルタ**（全期間 / 24時間以内 / 3日以内 / 7日以内 / 14日以内に追加）
- **並び順の切り替え**（発売日順 昇順・降順 / 登録日順 新しい順・古い順）
- 書影画像・タイトルクリックで BOOK☆WALKER 商品ページへ遷移
- 直近3日以内に追加された作品への「NEW」バッジ表示
- 各カードに登録日・発売日などのサブ情報を表示

---

## ファイル構成

```
bookwalker-new-series/
├── build.py              # データ収集・生成スクリプト
├── index.html            # 閲覧用 Web ページ（静的 HTML）
├── data.json             # 生成された書籍データ（月別）
├── months.json           # 対象月リスト
├── cover_cache.json      # 書影 URL キャッシュ
├── series_history.json   # 既知シリーズ履歴（新シリーズ判定用）
├── last_updated.json     # 最終更新日時
└── .github/
    └── workflows/
        └── update.yml    # GitHub Actions 自動更新ワークフロー
```

---

## 動作の仕組み

```
[GitHub Actions: 毎日 JST 3:00]
        ↓
build.py 実行
        ↓
BOOK☆WALKER CSV ダウンロード
        ↓
1巻・新シリーズを抽出 + 書影画像取得
        ↓
data.json / months.json / last_updated.json を更新
        ↓
GitHub へ自動コミット・プッシュ
        ↓
index.html がデータを読み込んで表示
```

---

## ローカルでの実行方法

### 依存ライブラリのインストール
```bash
pip install pandas
```

### データ更新スクリプトの実行
```bash
python build.py
```

### ローカルで Web ページを確認
```bash
python -m http.server 8000
```
ブラウザで `http://localhost:8000` を開いてください。

> **Note:** `index.html` は `fetch()` を使って JSON を読み込むため、ファイルを直接ダブルクリックして開くと CORS エラーになります。必ずローカルサーバー経由で確認してください。

---

## 自動更新スケジュール

GitHub Actions により **毎日 午前3時（JST）** に自動実行されます。  
GitHub リポジトリの Actions タブから「Run workflow」ボタンで手動実行も可能です。

---

## 技術スタック

| 項目 | 技術 |
|------|------|
| データ収集 | Python 3.10 / pandas / urllib |
| フロントエンド | 静的 HTML + Vanilla JavaScript（フレームワーク不使用） |
| 自動化 | GitHub Actions |
| データ形式 | JSON |
