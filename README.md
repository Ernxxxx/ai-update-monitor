# AI Update Monitor - AI公式アップデート監視ツール

## 概要

OpenAI / Anthropic / Google Gemini の公式情報を定期監視し、新規・更新をLLMで日本語要約してDiscordに通知するツール。

## 機能

- **3社のAI公式ソースを監視**
  - OpenAI (news, blog, research)
  - Anthropic (news)
  - Google Gemini (changelog, blog)
- **Bot対策回避**: Playwrightによるブラウザ自動化
- **新規/更新の差分検知**: SQLiteで既読管理
- **LLMによる日本語要約**: OpenAI互換API対応
- **Discord Webhook通知**: リッチなフォーマット

## セットアップ

1. Python 3.11+ をインストール
2. 依存関係インストール:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
3. `.env.example` を `.env` にコピーして設定

## 使い方

```bash
# 1回実行
python -m app

# 明示的に1回だけ実行
python -m app --once

# 定期実行（10分間隔）
python -m app --loop

# 間隔を変更（5分=300秒）
python -m app --loop --interval 300

# ドライラン（Discord送信なし）
python -m app --dry-run

# LLM失敗時もタイトルだけで通知
python -m app --fallback

# 組み合わせ例
python -m app --dry-run --fallback  # 要約なしでもドライラン通知
python -m app --loop --interval 60 --fallback  # 1分間隔、要約失敗時もURL通知
```

## 環境変数

| 変数名              | 説明                   | 必須       |
| ------------------- | ---------------------- | ---------- |
| DISCORD_WEBHOOK_URL | Discord Webhook URL    | 必須       |
| LLM_BASE_URL        | OpenAI互換APIベースURL | 要約使用時 |
| LLM_API_KEY         | LLM APIキー            | 要約使用時 |
| LLM_MODEL           | 使用モデル名           | 要約使用時 |
| CHECK_INTERVAL      | チェック間隔（秒）     | オプション |
| DB_PATH             | SQLiteパス             | オプション |

## ディレクトリ構成

```
app/
  __init__.py
  main.py          # CLIエントリーポイント
  config.py        # 設定管理
  db.py            # SQLite操作
  discord.py       # Discord通知
  llm.py           # LLM要約
  utils.py         # ユーティリティ
  sources/
    __init__.py
    base.py            # 基底クラス
    playwright_base.py # Playwright共通処理
    openai_source.py   # OpenAIソース
    anthropic_source.py# Anthropicソース
    gemini_source.py   # Geminiソース
```

## 動作確認

```bash
# ドライランで動作確認
python -m app --dry-run
```

## 注意事項

- セレクタは公式サイト構造変更で動かなくなる可能性あり
- TODOコメントの箇所を適宜修正

## ライセンス

MIT
