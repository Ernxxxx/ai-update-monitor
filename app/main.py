"""CLI entry point for ai-update-monitor.

Provides command-line interface for running the update monitor.
"""

import argparse
import io
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.config import get_config, Config
from app.db import init_db, is_notified, save_article, batch_check_articles, purge_old_articles, get_notified_titles
from app.sources import get_all_sources, Article
from app.llm import summarize_article, generate_weekly_digest
from app.db import get_recent_articles
from app.discord import DiscordBot
from app.utils import compute_hash, format_datetime


# Windows環境でのUTF-8対応 (pytest実行時はキャプチャ機構と競合するためスキップ)
_is_testing = 'pytest' in sys.modules or '_pytest' in sys.modules

if sys.platform == 'win32' and not _is_testing:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


# StreamHandlerにUTF-8エンコーディングを明示的に設定
def _create_stream_handler() -> logging.StreamHandler:
    """Create a StreamHandler with UTF-8 encoding for Windows compatibility."""
    if sys.platform == 'win32' and not _is_testing:
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

    parser.add_argument(
        "--weekly-digest",
        action="store_true",
        help="Generate and send a weekly digest summary to #weekly-digest",
    )

    return parser.parse_args(args)


def _fetch_from_source(source) -> List[Article]:
    """Fetch articles from a single source (used by ThreadPoolExecutor).

    Args:
        source: Source instance to fetch from.

    Returns:
        List of Article objects, or empty list on failure.
    """
    try:
        logger.info(f"Fetching from {source.name}...")
        articles = source.fetch_articles(limit=10)
        logger.info(f"Found {len(articles)} articles from {source.name}")
        return articles
    except Exception as e:
        logger.error(f"Failed to fetch from {source.name}: {e}")
        return []


def fetch_all_articles() -> List[Article]:
    """Fetch articles from all sources in parallel.

    Uses ThreadPoolExecutor to fetch from all sources concurrently.
    Total time = slowest source (instead of sum of all sources).

    Returns:
        List of Article objects from all sources.
    """
    articles: List[Article] = []
    sources = get_all_sources()

    with ThreadPoolExecutor(max_workers=len(sources), thread_name_prefix="fetch") as executor:
        futures = {executor.submit(_fetch_from_source, s): s for s in sources}

        for future in as_completed(futures, timeout=120):
            source = futures[future]
            try:
                result = future.result()
                articles.extend(result)
            except Exception as e:
                logger.error(f"Unexpected error from {source.name}: {e}")

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

    # Filter out articles older than MAX_AGE_DAYS
    MAX_AGE_DAYS = 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    fresh_articles = []
    for article in articles:
        if article.published_at is not None:
            pub = article.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub < cutoff:
                logger.debug(f"Skipping old article: {article.title} ({pub})")
                continue
        fresh_articles.append(article)
    logger.info(f"After date filter: {len(fresh_articles)} of {len(articles)} articles")
    articles = fresh_articles

    # Batch check all articles in 1-2 queries instead of N+1
    urls = [a.url for a in articles]
    titles_dates = [
        (a.title, format_datetime(a.published_at) if a.published_at else None)
        for a in articles
    ]
    existing = batch_check_articles(config.db_path, urls, titles_dates)

    # For X sources: also check title-only matches to catch repeated promo tweets
    # (same text content posted as different tweet IDs)
    x_sources = {"ai_news", "ai_tips"}
    x_titles = [a.title for a in articles if a.source in x_sources and a.title]
    notified_titles = get_notified_titles(config.db_path, x_titles) if x_titles else set()

    new_articles: List[Article] = []
    skipped_url = 0
    skipped_title_date = 0
    skipped_title = 0
    seen_titles: set[str] = set()  # In-batch dedup for same-text tweets

    for article in articles:
        pub_str = format_datetime(article.published_at) if article.published_at else None

        # Check if already notified (by URL or title+date)
        row = existing.get(article.url)
        title_date_key = f"{article.title}::{pub_str}" if article.title and pub_str else None
        title_date_row = existing.get(title_date_key) if title_date_key else None

        if row and row.get("notified_at"):
            # Already notified by URL -- skip entirely.
            # Content hash changes are cosmetic (dynamic web content) and
            # should NOT trigger re-posting.
            skipped_url += 1
        elif title_date_row and title_date_row.get("notified_at"):
            # Already notified by title+date (different URL, same article)
            skipped_title_date += 1
        elif article.source in x_sources and article.title and (
            article.title in notified_titles or article.title in seen_titles
        ):
            # X source: same tweet text already notified or in current batch
            skipped_title += 1
        else:
            if article.source in x_sources and article.title:
                seen_titles.add(article.title)
            new_articles.append(article)

    logger.info(
        f"Found {len(new_articles)} new articles "
        f"(skipped: {skipped_url} by URL, {skipped_title_date} by title+date"
        f", {skipped_title} by title)" if skipped_title else
        f"Found {len(new_articles)} new articles "
        f"(skipped: {skipped_url} by URL, {skipped_title_date} by title+date)"
    )

    if not new_articles:
        logger.info("No new articles to process")
        return 0

    # Initialize Discord Bot and ensure channels exist
    bot = DiscordBot(token=config.discord_bot_token, guild_id=config.discord_guild_id)
    if not dry_run:
        bot.ensure_channels()

    processed_count = 0

    for article in new_articles:
        logger.info(f"Processing: {article.title}")

        summary: Optional[str] = None

        # X sources: skip LLM. Tips = URL only, News = tweet text.
        if article.source == "ai_tips":
            summary = ""
        elif article.source == "ai_news":
            summary = article.content
        elif config.llm_api_key:
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

        # Send to Discord
        try:
            if article.source == "ai_tips":
                # Tips: plain URL only (Discord auto-generates preview card)
                success = bot.send_url(
                    source=article.source,
                    url=article.url,
                    dry_run=dry_run,
                )
            else:
                # Other sources: rich embed with summary
                success = bot.send_embed(
                    source=article.source,
                    title=article.title,
                    summary=summary,
                    url=article.url,
                    dry_run=dry_run,
                )
            if success:
                logger.info(f"Sent to #{article.source}: {article.title}")
            else:
                logger.error(f"Failed to send for: {article.title}")
                continue
        except Exception as e:
            logger.error(f"Failed to send to Discord: {e}")
            continue

        # Save to database (skip in dry-run mode)
        if not dry_run:
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

    # Purge articles older than 30 days to prevent DB bloat
    if not dry_run:
        deleted = purge_old_articles(config.db_path, days=30)
        if deleted > 0:
            logger.info(f"Purged {deleted} articles older than 30 days")

    return processed_count


def send_weekly_digest(
    config: Config,
    dry_run: bool = False,
) -> bool:
    """Generate and send a weekly digest to #weekly-digest.

    Args:
        config: Application configuration.
        dry_run: If True, log instead of sending to Discord.

    Returns:
        True if digest was sent successfully.
    """
    logger.info("Generating weekly digest...")

    # Get articles from the past 7 days (official 3 + ai_news)
    digest_sources = ["openai", "anthropic", "gemini", "ai_news"]
    articles = get_recent_articles(config.db_path, days=7, sources=digest_sources)

    if not articles:
        logger.info("No articles found for weekly digest")
        return False

    logger.info(f"Found {len(articles)} articles for weekly digest")

    if not config.llm_api_key:
        logger.error("LLM API key required for weekly digest")
        return False

    digest = generate_weekly_digest(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model=config.llm_model,
        articles=articles,
    )

    if not digest:
        logger.error("Failed to generate weekly digest")
        return False

    bot = DiscordBot(token=config.discord_bot_token, guild_id=config.discord_guild_id)
    if not dry_run:
        bot.ensure_channels()

    success = bot.send_embed(
        source="weekly_digest",
        title="Weekly AI Digest",
        summary=digest,
        url="",
        dry_run=dry_run,
    )

    if success:
        logger.info("Weekly digest sent successfully")
    else:
        logger.error("Failed to send weekly digest")

    return success


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

    # Weekly digest mode
    if parsed_args.weekly_digest:
        logger.info("Running weekly digest...")
        try:
            success = send_weekly_digest(config=config, dry_run=parsed_args.dry_run)
            return 0 if success else 1
        except Exception as e:
            logger.error(f"Error during weekly digest: {e}")
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
