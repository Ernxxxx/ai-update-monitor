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
