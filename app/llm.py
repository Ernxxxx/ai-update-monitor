"""LLM summarization client module.

Uses OpenAI-compatible API for article summarization.
"""

import logging

import requests

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたは技術ニュース要約の専門家です。
以下のルールに従って要約してください：
- 事実と推測を混ぜない
- 誇張しない
- 日本語で回答
- 公式発表としての確度を明記
- 出力フォーマット:
  1行目: 1文で要約
  2行目以降: 重要点を3つ箇条書き（- で始める）"""

USER_PROMPT_TEMPLATE = """以下の公式発表を要約してください。

ソース: {source}
タイトル: {title}
URL: {url}
本文:
{content}"""

DIGEST_SYSTEM_PROMPT = """あなたはAI業界の週次レポートを作成する専門アナリストです。
以下のルールに従って週次ダイジェストを作成してください：
- 事実と推測を明確に分ける
- 誇張しない
- 日本語で回答
- 各社ごとにセクション分けして要約
- 重要度が高いニュースを優先的に取り上げる
- 出力フォーマット:
  冒頭: 今週のハイライトを1-2文で
  各社セクション: **[会社名]** の見出しで区切る
  各ニュース: 1-2文で簡潔に要約（URLは含めない）
  末尾: 今週の注目ポイントを1文で"""

DIGEST_USER_TEMPLATE = """以下は今週（過去7日間）のAI関連ニュース一覧です。
週次ダイジェストを作成してください。

{articles_text}"""

REQUEST_TIMEOUT = 30


def summarize_article(
    base_url: str,
    api_key: str,
    model: str,
    title: str,
    content: str,
    url: str,
    source: str,
    max_content_length: int = 4000,
) -> str | None:
    """Summarize an article using LLM.

    Args:
        base_url: OpenAI-compatible API base URL.
        api_key: API key for authentication.
        model: Model name to use.
        title: Article title.
        content: Article content/body.
        url: Article URL.
        source: Article source (e.g., 'openai', 'anthropic').
        max_content_length: Maximum content length before truncation.

    Returns:
        Summary string if successful, None otherwise.
    """
    # Truncate content if too long
    if len(content) > max_content_length:
        content = content[:max_content_length]
        logger.info(f"Content truncated to {max_content_length} characters")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        source=source,
        title=title,
        url=url,
        content=content,
    )

    # Ensure base_url doesn't end with /
    base_url = base_url.rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        data = response.json()
        summary = data["choices"][0]["message"]["content"]
        logger.info(f"Successfully summarized article: {title}")
        return summary

    except requests.Timeout:
        logger.error(f"Timeout while summarizing article: {title}")
        return None
    except requests.RequestException as e:
        logger.error(f"Request error while summarizing article '{title}': {e}")
        return None
    except (KeyError, IndexError) as e:
        logger.error(f"Failed to parse LLM response for article '{title}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while summarizing article '{title}': {e}")
        return None


# Source display names for digest
_SOURCE_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Gemini / Google",
    "ai_news": "AI News (X)",
    "ai_tips": "AI Tips (X)",
}


def generate_weekly_digest(
    base_url: str,
    api_key: str,
    model: str,
    articles: list[dict],
) -> str | None:
    """Generate a weekly digest summary from a list of articles.

    Args:
        base_url: OpenAI-compatible API base URL.
        api_key: API key for authentication.
        model: Model name to use.
        articles: List of article dicts with url, source, title, published_at.

    Returns:
        Digest text if successful, None otherwise.
    """
    if not articles:
        logger.info("No articles for weekly digest")
        return None

    # Group articles by source
    by_source: dict[str, list[dict]] = {}
    for a in articles:
        by_source.setdefault(a["source"], []).append(a)

    # Build text block
    parts = []
    for source in ["openai", "anthropic", "gemini", "ai_news"]:
        items = by_source.get(source, [])
        if not items:
            continue
        name = _SOURCE_NAMES.get(source, source)
        parts.append(f"## {name} ({len(items)}件)")
        for item in items:
            date = (item.get("published_at") or "")[:10]
            parts.append(f"- [{date}] {item['title']}  {item['url']}")
        parts.append("")

    articles_text = "\n".join(parts)

    # Truncate if too long for LLM context
    if len(articles_text) > 12000:
        articles_text = articles_text[:12000] + "\n...(truncated)"

    user_prompt = DIGEST_USER_TEMPLATE.format(articles_text=articles_text)

    base_url = base_url.rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=60,  # longer timeout for digest
        )
        response.raise_for_status()

        data = response.json()
        digest = data["choices"][0]["message"]["content"]
        logger.info(f"Generated weekly digest ({len(digest)} chars)")
        return digest

    except requests.Timeout:
        logger.error("Timeout while generating weekly digest")
        return None
    except requests.RequestException as e:
        logger.error(f"Request error while generating weekly digest: {e}")
        return None
    except (KeyError, IndexError) as e:
        logger.error(f"Failed to parse LLM response for weekly digest: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while generating weekly digest: {e}")
        return None
