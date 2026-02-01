"""Discord Webhook notification module.

Sends notifications to Discord via webhook.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

DISCORD_MAX_LENGTH = 2000
MAX_ARTICLES_PER_POST = 3
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff: 1s, 2s, 4s

SOURCE_DISPLAY_NAMES = {
    "openai": "OPENAI",
    "anthropic": "ANTHROPIC",
    "gemini": "GEMINI",
}


def send_notification(webhook_url: str, content: str, dry_run: bool = False) -> bool:
    """Send a notification to Discord via webhook.

    Args:
        webhook_url: Discord webhook URL.
        content: Message content to send.
        dry_run: If True, only log the message without sending.

    Returns:
        True if successful, False otherwise.
    """
    # Truncate content if exceeds Discord's limit
    if len(content) > DISCORD_MAX_LENGTH:
        truncated_content = content[: DISCORD_MAX_LENGTH - 3] + "..."
        logger.warning(
            f"Content truncated from {len(content)} to {DISCORD_MAX_LENGTH} characters"
        )
        content = truncated_content

    if dry_run:
        logger.info(f"[DRY RUN] Would send notification:\n{content}")
        return True

    payload = {"content": content}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            logger.info("Notification sent successfully")
            return True
        except requests.RequestException as e:
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)

    logger.error("Failed to send notification after all retries")
    return False


def format_notification(article: dict, summary: str | None) -> str:
    """Format a notification message for an article.

    Args:
        article: Article dict containing 'source', 'title', 'url' keys.
        summary: Summary text or None if no summary available.

    Returns:
        Formatted notification string.
    """
    source = article.get("source", "unknown").lower()
    source_display = SOURCE_DISPLAY_NAMES.get(source, source.upper())
    title = article.get("title", "No title")
    url = article.get("url", "")

    summary_text = summary if summary else "要約なし"

    return f"""**[{source_display}] 新規/更新: {title}**

{summary_text}

確度: 公式発表
ソース: {url}"""


def send_batch_notifications(
    webhook_url: str,
    articles: list[dict],
    summaries: list[str | None],
    dry_run: bool = False,
) -> int:
    """Send batch notifications for multiple articles.

    Articles are grouped into posts with maximum 3 articles per post.

    Args:
        webhook_url: Discord webhook URL.
        articles: List of article dicts.
        summaries: List of summaries corresponding to each article.
        dry_run: If True, only log without sending.

    Returns:
        Number of articles successfully notified.
    """
    if len(articles) != len(summaries):
        logger.error("Articles and summaries count mismatch")
        return 0

    if not articles:
        logger.info("No articles to notify")
        return 0

    success_count = 0

    # Process in batches of MAX_ARTICLES_PER_POST
    for i in range(0, len(articles), MAX_ARTICLES_PER_POST):
        batch_articles = articles[i : i + MAX_ARTICLES_PER_POST]
        batch_summaries = summaries[i : i + MAX_ARTICLES_PER_POST]

        # Format each article in the batch
        formatted_messages = []
        for article, summary in zip(batch_articles, batch_summaries):
            formatted_messages.append(format_notification(article, summary))

        # Join with separator
        combined_content = "\n\n---\n\n".join(formatted_messages)

        if send_notification(webhook_url, combined_content, dry_run):
            success_count += len(batch_articles)
            logger.info(
                f"Batch {i // MAX_ARTICLES_PER_POST + 1}: "
                f"Sent {len(batch_articles)} articles"
            )
        else:
            logger.error(
                f"Batch {i // MAX_ARTICLES_PER_POST + 1}: "
                f"Failed to send {len(batch_articles)} articles"
            )

        # Add small delay between batches to avoid rate limiting
        if i + MAX_ARTICLES_PER_POST < len(articles):
            time.sleep(0.5)

    logger.info(f"Total notifications sent: {success_count}/{len(articles)}")
    return success_count
