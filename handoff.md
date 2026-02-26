# Handoff - AI Update Monitor

更新: 2026-02-21 10:00 JST

## 今回やったこと

### 1. 重複送信バグ修正（3箇所）

#### a. URL正規化の追加

- `app/utils.py`: `normalize_url()` 関数追加
  - 末尾スラッシュ除去、www除去、HTTPS強制、UTMパラメータ除去
  - ホスト名小文字化、フラグメント保持
- `app/main.py`: `process_articles()` で全記事URLを正規化してから重複チェック
- `app/db.py`: `save_article()` でもURL正規化（DB保存時に統一）
- `tests/test_utils.py`: 9テスト追加（56 passed）

#### b. クラッシュウィンドウ修正

- `app/main.py`: Discord送信 **前に** DBに `notified_at=None` で保存
  - 送信成功後に `notified_at` を更新
  - プロセス死亡時でもDB側に記録が残り、次回再送信を防止

#### c. クロスソース重複検出強化

- `app/main.py`: `get_notified_titles()` のスコープをX源だけでなく全ソースに拡大
  - 同一記事が openai + ai_news 両方から検出されるケースを防止
  - X源の `seen_titles` によるバッチ内重複チェックは維持

### 2. 速度改善（3箇所）

#### a. Playwright個別記事取得の廃止

- `app/sources/openai_source.py`:
  - `_fetch_from_web_page()` と `_fetch_with_playwright()` で個別記事ページ取得を廃止
  - 新メソッド `_extract_nearby_text()` でリスティングページ内のテキストから概要抽出
  - 改善効果: 10記事 × 30秒 = 300秒 → 0秒（リスティングページのみで完結）

#### b. REQUEST_DELAY 短縮

- `app/sources/openai_source.py`: `REQUEST_DELAY` を 2秒 → 0.5秒 に変更
  - 改善効果: 10記事 × 1.5秒削減 = 15秒短縮

#### c. ThreadPoolExecutor タイムアウト延長

- `app/main.py`: `as_completed(timeout=)` を 120秒 → 300秒 に変更
  - Playwrightフォールバック時のタイムアウト防止

### 3. RSS/Atom フィード統合実装（前回セッション）

#### a. Google AI Blog: スクレイピング → RSS 切替

- `app/sources/gemini_source.py`: `_fetch_from_ai_blog()` でRSS優先、スクレイピングフォールバック
- RSS URL: `https://blog.google/technology/ai/rss/`
- 新メソッド: `_fetch_from_rss()` — feedparser による汎用RSSパーサー

#### b. Google DeepMind Blog: 新規追加（RSS）

- `app/sources/gemini_source.py`: `_fetch_from_deepmind()` 追加
- RSS URL: `https://deepmind.google/blog/rss.xml`

#### c. OpenAI Developer Changelog: 新規追加（RSS）

- `app/sources/openai_source.py`: `CHANGELOG_RSS` 定数追加、Strategy 1.5 として追加
- RSS URL: `https://developers.openai.com/changelog/rss.xml`

#### d. ステータスページ監視: 新規追加（3社）

- `app/sources/status_source.py`: 新規ファイル作成
  - OpenAI: `https://status.openai.com/feed.rss`
  - Anthropic: `https://status.claude.com/history.rss`
  - Google Cloud: `https://status.cloud.google.com/en/feed.atom`
- `app/discord.py`: `status` → `#status-alerts` チャンネル追加（色: 赤 0xE74C3C）
- `app/sources/__init__.py`: `StatusSource` 登録

## 前回やったこと

### 1. ai_tips を plain URL 送信に変更

- `app/main.py`: `bot.send_embed()` → `bot.send_url()` に分岐追加
- コミット: `6d5af1d`

### 2. Weekly Digest 機能追加（`--weekly-digest` フラグ）

- `app/db.py`: `get_recent_articles()` 追加
- `app/llm.py`: `generate_weekly_digest()` 追加
- VM cron: `0 0 * * 1`（月曜 0:00 UTC = JST 9:00）
- コミット: `95ec463`

### 3. Gemini changelog 重複修正

- タイトルからコンテンツヒントを除去
- コミット: `b58b268`

### 4. X ソースのタイトルのみ重複検出追加

- 4層重複検出完成
- コミット: `742654d`

## 現在の状態

- **テスト**: 56 passed（47 + 9 新規 normalize_url テスト）
- **未コミットの変更**:
  - `app/utils.py` — `normalize_url()` 追加
  - `app/db.py` — URL正規化適用
  - `app/main.py` — URL正規化 + クラッシュウィンドウ修正 + タイムアウト延長 + is_x_tweet 判定追加
  - `app/sources/openai_source.py` — Playwright個別取得廃止 + REQUEST_DELAY短縮 + `_extract_nearby_text()` 追加
  - `app/sources/status_source.py` — 新規ファイル
  - `app/sources/gemini_source.py` — RSS対応 + DeepMind追加
  - `app/sources/__init__.py` — StatusSource登録
  - `app/discord.py` — #status-alerts チャンネル追加
  - `app/sources/x_source.py` — 2アカウント追加（masahirochaen, ctgptlb）
  - `tests/test_utils.py` — 9テスト追加
- **VMデプロイ**: コミット `742654d` まで反映済み（今回の変更は未デプロイ）
- **VM cron**: 10分間隔の通常監視 + 週次ダイジェスト（月曜9:00 JST）
- **稼働チャンネル**: #openai-updates, #anthropic-updates, #gemini-updates, #ai-news, #ai-tips, #weekly-digest
- **新チャンネル（デプロイ後に自動作成）**: #status-alerts

## 残りのタスク

### バグ修正（優先度高）

- [x] Discord送信前にDB保存し記事永久消失を防止（クラッシュウィンドウ修正）
- [ ] APIキーがログに漏れる可能性の修正
- [ ] LLM APIの429リトライ未実装

### 重複修正（完了）

- [x] URL正規化追加（末尾スラッシュ、UTM、scheme統一）
- [x] クラッシュウィンドウ修正（DB先行保存 → Discord送信 → notified_at更新）
- [x] クロスソース重複検出（全ソースでタイトルマッチ）

### 速度改善（完了）

- [x] Playwright個別記事取得廃止（リスティングページ内テキスト抽出に変更）
- [x] REQUEST_DELAY 2秒 → 0.5秒
- [x] ThreadPoolExecutor timeout 120秒 → 300秒

### RSS切替（完了）

- [x] OpenAI ソースを RSS に切替（元々実装済み）
- [x] Google AI Blog を RSS に切替（`blog.google/technology/ai/rss/`）
- [x] OpenAI Developer Changelog 追加（`developers.openai.com/changelog/rss.xml`）
- [x] Google DeepMind Blog 追加（`deepmind.google/blog/rss.xml`）
- [x] ステータスページ監視（3社）
- Anthropic / Gemini Changelog → 公式RSSなし、スクレイピング続行

### Discord拡張（優先度低）

- [ ] Link Buttons（記事embedに「原文を読む」ボタン）
- [ ] Auto-Reactions（投稿後に自動リアクション）
- [ ] 緊急度スコアリング（LLMでBreaking/Important/Routine分類）
- [ ] Slash Commands（HTTPインタラクション、VMにHTTPS必要）

### その他

- [ ] X API のコスト監視
- [ ] Bot 権限を ADMINISTRATOR から最低限に絞る
- [ ] 未コミット変更をコミット → VMデプロイ
- [ ] VM cron間隔を10分 → 3-5分に短縮（デプロイ時に変更推奨）

## 注意点

- `.env` にシークレットあり（DISCORD_BOT_TOKEN, LLM_API_KEY, X_BEARER_TOKEN）→ git に含めないこと
- VM SSH: `"C:/Windows/System32/OpenSSH/ssh.exe" -i "C:/Users/longs/Downloads/ssh-key-2026-01-23.key" ubuntu@141.147.184.121`
- VM パス: `/home/ubuntu/ai-update-monitor/`
- VM venv: `source venv/bin/activate`（`.venv/` ではない）
- VM DB: `state.db`（.env の DB_PATH）
- dotenv の frame assertion エラー: VM で inline Python 実行時に `load_dotenv()` が壊れる → `open('.env')` で手動読込
- OpenAI RSS: `feedparser` に直接 URL を渡すと 403 → `requests.get()` → `feedparser.parse(resp.text)` の順で
- Gemini: `.devsite-article-body` クラスは静的 HTML に存在しない。`h2` 直接選択が正解
- Gemini changelog: サイト構造変更リスクあり（TODO コメント4箇所）
- Anthropic: 公式RSSなし、Next.js SPAなのでスクレイピングが壊れやすい
- X API `max_results` は 10〜100 の範囲制限あり（10未満で 400 エラー）
- Discord Bot 再招待URL: `client_id=1473275741771661484`
- Git の bash では SSH が空出力になる → `C:/Windows/System32/OpenSSH/ssh.exe` を使うこと
- pytest実行時: `app/main.py` の `_is_testing` ガードにより stdout TextIOWrapper 競合を回避
- **Status feeds**: Statuspage.io（OpenAI, Anthropic）とGoogle Cloud Statusで形式が異なるがfeedparserが吸収
- **URL正規化**: DB保存時とprocess_articles()の両方で正規化。既存DBデータは正規化前のURLだが、新規保存時に上書きされる
- **クラッシュウィンドウ**: notified_at=None のレコードは「見つけたが通知未完了」を意味する。次回実行時にnotified_atチェックで再取得される設計

## 関連ファイル

- `app/main.py` - CLIエントリ、5層重複検出（URL正規化+クラッシュウィンドウ修正済み）、週次ダイジェスト処理
- `app/db.py` - SQLite操作（URL正規化適用、batch_check, get_notified_titles, get_recent_articles, purge）
- `app/utils.py` - ユーティリティ（normalize_url, compute_hash, sanitize_for_log）
- `app/discord.py` - Discord REST API（send_embed, send_url, 8チャンネル管理）
- `app/llm.py` - LLM要約 + 週次ダイジェスト生成
- `app/config.py` - 設定クラス
- `app/sources/__init__.py` - ソース登録（5ソース: openai, anthropic, gemini, status, x）
- `app/sources/http_client.py` - 共通HTTPクライアント（retry/backoff/ヘッダー管理）
- `app/sources/openai_source.py` - OpenAI パーサー（Blog RSS + Changelog RSS + 高速スクレイピング）
- `app/sources/anthropic_source.py` - Anthropic パーサー（Brotli修正済み、RSS無し）
- `app/sources/gemini_source.py` - Gemini changelog(スクレイピング) + AI Blog(RSS) + DeepMind(RSS)
- `app/sources/status_source.py` - ステータスページ監視（OpenAI, Anthropic, Google Cloud）
- `app/sources/x_source.py` - X/Twitter ソース
- `app/sources/playwright_base.py` - Playwright共通処理
- `tests/` - テストスイート（56テスト）
