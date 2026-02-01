"""CLI entry point for ai-update-monitor.

Provides command-line interface for running the update monitor.
"""

import argparse
import io
import logging
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

from app.config import get_config, Config
from app.db import init_db, is_notified, is_updated, save_article
from app.sources import get_all_sources, Article
from app.llm import summarize_article
from app.discord import send_notification, format_notification
from app.utils import compute_hash, format_datetime


# Windows環境でのUTF-8対応
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


# StreamHandlerにUTF-8エンコーディングを明示的に設定
def _create_stream_handler() -> logging.StreamHandler:
    """Create a StreamHandler with UTF-8 encoding for Windows compatibility."""
    if sys.platform == 'win32':
        stream = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
        handler = logging.StreamHandler(stream)
    else:
        handler = logging.StreamHandler(sys.stdout)
    return handler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[_create_stream_handler()],
)
logger = logging.getLogger(__name__)


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args: Command-line arguments (defaults to sys.argv).

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="AI Update Monitor - Track AI news and send Discord notifications",
        prog="ai-update-monitor",
    )

    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run in loop mode (continuous monitoring)",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Loop interval in seconds (overrides CHECK_INTERVAL from config)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log notifications instead of sending to Discord",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Explicitly run only once (default behavior)",
    )

    parser.add_argument(
        "--fallback",
        action="store_true",
        help="Send title+URL only if LLM summarization fails",
    )

    return parser.parse_args(args)


def fetch_all_articles() -> List[Article]:
    """Fetch articles from all sources.

    Returns:
        List of Article objects from all sources.
    """
    articles: List[Article] = []
    sources = get_all_sources()

    for source in sources:
        try:
            logger.info(f"Fetching from {source.name}...")
            source_articles = source.fetch_articles(limit=10)
            articles.extend(source_articles)
            logger.info(f"Found {len(source_articles)} articles from {source.name}")
        except Exception as e:
            logger.error(f"Failed to fetch from {source.name}: {e}")
            continue

    return articles


def process_articles(
    config: Config,
    dry_run: bool = False,
    fallback: bool = False,
) -> int:
    """Process articles from all sources.

    Args:
        config: Application configuration.
        dry_run: If True, log instead of sending to Discord.
        fallback: If True, send title+URL when LLM fails.

    Returns:
        Number of new articles processed.
    """
    logger.info("Fetching articles from all sources...")
    articles = fetch_all_articles()
    logger.info(f"Found {len(articles)} total articles")

    new_articles: List[Article] = []
    updated_articles: List[Article] = []

    for article in articles:
        content_hash = compute_hash(article.content)

        if not is_notified(config.db_path, article.url):
            new_articles.append(article)
        elif is_updated(config.db_path, article.url, content_hash):
            updated_articles.append(article)

    all_to_process = new_articles + updated_articles
    logger.info(f"Found {len(new_articles)} new, {len(updated_articles)} updated articles")

    if not all_to_process:
        logger.info("No new or updated articles to process")
        return 0

    processed_count = 0

    for article in all_to_process:
        is_update = article in updated_articles
        status_label = "updated" if is_update else "new"
        logger.info(f"Processing ({status_label}): {article.title}")

        summary: Optional[str] = None

        # Try LLM summarization
        if config.llm_api_key:
            try:
                summary = summarize_article(
                    base_url=config.llm_base_url,
                    api_key=config.llm_api_key,
                    model=config.llm_model,
                    title=article.title,
                    content=article.content,
                    url=article.url,
                    source=article.source,
                )
                if summary:
                    logger.info(f"Generated summary for: {article.title}")
                else:
                    logger.warning(f"LLM returned empty summary for: {article.title}")
            except Exception as e:
                logger.error(f"LLM summarization failed for {article.title}: {e}")
        else:
            logger.info("LLM API key not configured, skipping summarization")

        # Skip if no summary and fallback not enabled
        if summary is None and not fallback:
            logger.warning(f"Skipping article without summary (use --fallback to send anyway): {article.title}")
            continue

        # Prepare article dict for formatting
        article_dict = {
            "source": article.source,
            "title": article.title,
            "url": article.url,
        }

        # Format notification content
        notification_content = format_notification(article_dict, summary)

        if dry_run:
            logger.info(f"[DRY-RUN] Would send notification:")
            logger.info(f"---\n{notification_content}\n---")
        else:
            try:
                success = send_notification(
                    webhook_url=config.discord_webhook_url,
                    content=notification_content,
                    dry_run=False,
                )
                if success:
                    logger.info(f"Sent notification for: {article.title}")
                else:
                    logger.error(f"Failed to send notification for: {article.title}")
                    continue
            except Exception as e:
                logger.error(f"Failed to send Discord notification: {e}")
                continue

        # Save to database
        content_hash = compute_hash(article.content)
        now = format_datetime(datetime.now(timezone.utc))

        save_article(
            db_path=config.db_path,
            article={
                "url": article.url,
                "source": article.source,
                "title": article.title,
                "published_at": format_datetime(article.published_at) if article.published_at else None,
                "content_hash": content_hash,
                "notified_at": now,
            }
        )
        logger.info(f"Saved to database: {article.url}")
        processed_count += 1

    return processed_count


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI.

    Args:
        args: Command-line arguments (defaults to sys.argv).

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parsed_args = parse_args(args)

    try:
        config = get_config()
        logger.info("Configuration loaded successfully")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    try:
        init_db(config.db_path)
        logger.info(f"Database initialized at: {config.db_path}")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return 1

    interval = parsed_args.interval or config.check_interval

    if parsed_args.loop and not parsed_args.once:
        logger.info(f"Starting loop mode with {interval}s interval")
        while True:
            try:
                processed = process_articles(
                    config=config,
                    dry_run=parsed_args.dry_run,
                    fallback=parsed_args.fallback,
                )
                logger.info(f"Processed {processed} articles")
            except Exception as e:
                logger.error(f"Error during processing: {e}")

            logger.info(f"Sleeping for {interval} seconds...")
            time.sleep(interval)
    else:
        logger.info("Running single check...")
        try:
            processed = process_articles(
                config=config,
                dry_run=parsed_args.dry_run,
                fallback=parsed_args.fallback,
            )
            logger.info(f"Processed {processed} articles")
        except Exception as e:
            logger.error(f"Error during processing: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
