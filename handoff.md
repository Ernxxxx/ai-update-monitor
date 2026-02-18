# Handoff - AI Update Monitor

更新: 2026-02-18 20:00 JST

## 今回やったこと

### 1. Anthropic修正 + Playwright整理 (パフォーマンス: 2分+ → 1.6秒)
- **根本原因**: `Accept-Encoding: gzip, deflate, br` の Brotli がデコード不能 → HTML スクレイピング失敗 → Playwright フォールバック
- `http_client.py` で `Accept-Encoding` から `br` を除去
- Playwright fallback 時の個別記事コンテンツ取得を廃止 (リスティングページのみ使用)
- RSS_URLS を6→2に削減 (有効なフィードのみ)
- `atexit.register()` で Playwright ブラウザのリーク防止

### 2. 共通HTTPクライアント (`app/sources/http_client.py` 新規作成)
- `DEFAULT_HEADERS` / `RSS_HEADERS` を一元管理 (Brotli除外を保証)
- `create_session()` でセッション生成を標準化
- `fetch_with_retry()` で指数バックオフ付きリトライ (429/5xx/接続エラー対応)
- 全3ソース (openai/anthropic/gemini) を共通クライアントに移行

### 3. ソース並列フェッチ (ThreadPoolExecutor)
- `fetch_all_articles()` を ThreadPoolExecutor で並列化
- 実行時間: 全ソース合計 → 最も遅いソースに短縮 (~5.9秒)
- ソース単位でエラーを隔離 (1つ失敗しても他は継続)

### 4. SQLite N+1修正 + DBパージ
- `batch_check_articles()` 追加: 全URLを1クエリ、title+dateも1クエリで一括チェック
- N+1ループ (記事ごとに2クエリ) → バッチ (全記事で2クエリ) に削減
- `purge_old_articles()` 追加: 30日超の古い記事を自動削除 (DB肥大化防止)

### 5. ミニマルテストスイート (46テスト, 1.1秒)
- `tests/test_db.py` (17件): save/get/is_notified/is_updated/batch_check/purge
- `tests/test_utils.py` (11件): hash/truncate/datetime/sanitize
- `tests/test_http_client.py` (9件): session作成/retry/backoff/429/4xx
- `tests/test_main.py` (6件): dry-run/skip/parallel fetch/failure handling
- `app/main.py`: pytest互換性修正 (`_is_testing` ガードで TextIOWrapper 競合回避)

### 前回: Discord サーバー整備 + 重複投稿修正
- カテゴリ構成を全面整理: [一般] / [横田] / [三島] / [岩田] / [AI Updates] / [Bot] / [ボイスチャンネル]
- 個人ロール作成: @横田(赤), @三島(緑), @岩田(橙) + カテゴリ閲覧制限
- x_source.py: #ai-news から OpenAI/Anthropic/Google を除外
- gemini_source.py: URL アンカーからコンテンツハッシュを除去 → 日付ベース
- 全ソースに日付フィルタ追加、title+date 重複チェック追加

## 現在の状態

- **テスト**: 46 passed (1.1秒)、外部I/Oは全てモック
- **dry-run確認済み**: 41記事取得→日付フィルタ後32件→既存記事のため0件処理
- VM cron: `*/10 * * * *` で自動実行中 (SHELL=/bin/bash)
- 全5チャンネル稼働: #openai-updates, #anthropic-updates, #gemini-updates, #ai-news, #ai-tips
- Discord サーバー: 7カテゴリ、14テキストチャンネル、1ボイスチャンネル

## 残りのタスク

- [ ] X API のコスト監視（X Developer Console で使用状況を定期確認）
- [ ] 各メンバーに個人ロール (@横田/@三島/@岩田) を手動で割り当て (Bot にメンバーリスト権限なし)
- [ ] AI Update Monitor Bot の権限を ADMINISTRATOR から必要最低限に戻す (整備完了後)
- [x] ~~Anthropic の HTML スクレイピングが毎回失敗し Playwright フォールバック~~ → Brotli除去で解決
- [x] ~~dry-run モードで DB に記事が保存される問題~~ → 修正済み
- [x] ~~ai-news/ai-tips に3社アプデ情報が混入~~ → 修正済み
- [x] ~~公式アプデチャンネルの重複投稿~~ → 修正済み

## 注意点

- `.env` にシークレットあり（DISCORD_BOT_TOKEN, LLM_API_KEY, X_BEARER_TOKEN）→ git に含めないこと
- VM の SSH キー: `C:\Users\longs\Downloads\ssh-key-2026-01-23.key`
- VM SSH コマンド: `"C:/Windows/System32/OpenSSH/ssh.exe" -i "C:/Users/longs/Downloads/ssh-key-2026-01-23.key" ubuntu@141.147.184.121`
- VM パス: `/home/ubuntu/ai-update-monitor/`
- X API `max_results` は 10〜100 の範囲制限あり（10未満だと 400 エラー）
- OpenAI RSS: `feedparser` に直接 URL を渡すと 403 になる。必ず `requests.get()` → `feedparser.parse(resp.text)` の順で
- Gemini: `.devsite-article-body` クラスは静的 HTML に存在しない。`h2` 直接選択が正解
- Discord Bot 再招待URL (権限変更時): `client_id=1473275741771661484`
- Git の bash では SSH が空出力になる → `C:/Windows/System32/OpenSSH/ssh.exe` を使うこと
- pytest実行時: `app/main.py` の `_is_testing` ガードにより stdout TextIOWrapper 競合を回避

## 関連ファイル

- `.env.example` - 環境変数テンプレート
- `app/config.py` - 設定クラス
- `app/discord.py` - Discord Bot REST API クライアント
- `app/main.py` - メインループ（並列フェッチ・バッチチェック・日付フィルタ・パージ）
- `app/db.py` - SQLite操作（batch_check_articles・purge_old_articles追加）
- `app/sources/__init__.py` - ソース登録
- `app/sources/http_client.py` - 共通HTTPクライアント（retry・backoff・ヘッダー管理）
- `app/sources/openai_source.py` - OpenAI RSS パーサー
- `app/sources/anthropic_source.py` - Anthropic パーサー（Brotli修正済み）
- `app/sources/gemini_source.py` - Gemini changelog パーサー
- `app/sources/x_source.py` - X (Twitter) ソース
- `app/sources/playwright_base.py` - Playwright共通処理（atexit cleanup追加）
- `tests/` - テストスイート（46テスト）
- `scripts/run-monitor.cmd` - Windows 起動スクリプト
