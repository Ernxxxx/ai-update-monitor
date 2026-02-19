"""SQLite database module for article read/notification management."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator


def init_db(db_path: str) -> None:
    """Create the articles table if it doesn't exist.

    Args:
        db_path: Path to the SQLite database file.
    """
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,
                title TEXT,
                published_at TEXT,
                content_hash TEXT,
                notified_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_title_date ON articles(title, published_at)"
        )
        conn.commit()


@contextmanager
def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection with context management.

    Args:
        db_path: Path to the SQLite database file.

    Yields:
        sqlite3.Connection: Database connection object.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def is_notified(
    db_path: str,
    url: str,
    *,
    title: str | None = None,
    published_at: str | None = None,
    check_title_date: bool = False,
) -> bool:
    """Check if an article has already been notified.

    Args:
        db_path: Path to the SQLite database file.
        url: Article URL to check.
        title: Article title (optional, used with check_title_date).
        published_at: Publication date (optional, used with check_title_date).
        check_title_date: If True, also check by title+published_at combination.

    Returns:
        True if the article has been notified, False otherwise.
    """
    with get_connection(db_path) as conn:
        # Check by URL first
        cursor = conn.execute(
            "SELECT notified_at FROM articles WHERE url = ?",
            (url,)
        )
        row = cursor.fetchone()
        if row is not None and row["notified_at"] is not None:
            return True

        # Optionally check by title + published_at
        if check_title_date and title is not None and published_at is not None:
            cursor = conn.execute(
                "SELECT notified_at FROM articles WHERE title = ? AND published_at = ?",
                (title, published_at)
            )
            row = cursor.fetchone()
            if row is not None and row["notified_at"] is not None:
                return True

        return False


def is_updated(db_path: str, url: str, content_hash: str) -> bool:
    """Check if an article has been updated by comparing content hashes.

    Args:
        db_path: Path to the SQLite database file.
        url: Article URL to check.
        content_hash: SHA256 hash of the current content.

    Returns:
        True if the article exists and has a different hash (updated),
        False if not found or hash matches.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT content_hash FROM articles WHERE url = ?",
            (url,)
        )
        row = cursor.fetchone()
        if row is None:
            return False
        return row["content_hash"] != content_hash


def save_article(
    db_path: str,
    article: dict,
    *,
    conflict_strategy: str = "url",
) -> None:
    """Save or update an article in the database.

    Args:
        db_path: Path to the SQLite database file.
        article: Dictionary containing article data with keys:
            - url (required): Article URL
            - source (required): Source name (openai/anthropic/gemini)
            - title (optional): Article title
            - published_at (optional): Publication date in ISO8601 format
            - content_hash (optional): SHA256 hash of content
            - notified_at (optional): Notification timestamp in ISO8601 format
        conflict_strategy: How to handle conflicts:
            - "url": Use URL as unique key (default)
            - "title_date": Use title+published_at as unique key
            - "both": Try URL first, fall back to title+date
    """
    with get_connection(db_path) as conn:
        url = article["url"]
        source = article["source"]
        title = article.get("title")
        published_at = article.get("published_at")
        content_hash = article.get("content_hash")
        notified_at = article.get("notified_at")

        if conflict_strategy == "url":
            conn.execute(
                """
                INSERT INTO articles (url, source, title, published_at, content_hash, notified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    source = excluded.source,
                    title = excluded.title,
                    published_at = excluded.published_at,
                    content_hash = excluded.content_hash,
                    notified_at = COALESCE(excluded.notified_at, articles.notified_at)
                """,
                (url, source, title, published_at, content_hash, notified_at),
            )
        elif conflict_strategy == "title_date":
            conn.execute(
                """
                INSERT INTO articles (url, source, title, published_at, content_hash, notified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(title, published_at) DO UPDATE SET
                    url = excluded.url,
                    source = excluded.source,
                    content_hash = excluded.content_hash,
                    notified_at = COALESCE(excluded.notified_at, articles.notified_at)
                """,
                (url, source, title, published_at, content_hash, notified_at),
            )
        elif conflict_strategy == "both":
            # Check if exists by title+date first
            existing = None
            if title is not None and published_at is not None:
                cursor = conn.execute(
                    "SELECT id FROM articles WHERE title = ? AND published_at = ?",
                    (title, published_at)
                )
                existing = cursor.fetchone()

            if existing:
                # Update existing record found by title+date
                conn.execute(
                    """
                    UPDATE articles SET
                        url = ?,
                        source = ?,
                        content_hash = ?,
                        notified_at = COALESCE(?, notified_at)
                    WHERE id = ?
                    """,
                    (url, source, content_hash, notified_at, existing["id"]),
                )
            else:
                # Try insert with URL conflict handling
                conn.execute(
                    """
                    INSERT INTO articles (url, source, title, published_at, content_hash, notified_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        source = excluded.source,
                        title = excluded.title,
                        published_at = excluded.published_at,
                        content_hash = excluded.content_hash,
                        notified_at = COALESCE(excluded.notified_at, articles.notified_at)
                    """,
                    (url, source, title, published_at, content_hash, notified_at),
                )
        else:
            raise ValueError(f"Unknown conflict_strategy: {conflict_strategy}")

        conn.commit()


def get_article(db_path: str, url: str) -> dict | None:
    """Retrieve an article from the database by URL.

    Args:
        db_path: Path to the SQLite database file.
        url: Article URL to retrieve.

    Returns:
        Dictionary containing article data if found, None otherwise.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, url, source, title, published_at, content_hash, notified_at, created_at
            FROM articles
            WHERE url = ?
            """,
            (url,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)


def batch_check_articles(
    db_path: str,
    urls: list[str],
    titles_dates: list[tuple[str | None, str | None]] | None = None,
) -> dict[str, dict]:
    """Batch check article status for multiple URLs in a single query.

    Returns a mapping of URL -> row dict for all existing articles.
    Also checks title+date combinations if provided.

    Args:
        db_path: Path to the SQLite database file.
        urls: List of article URLs to check.
        titles_dates: Optional list of (title, published_at) tuples.

    Returns:
        Dict mapping URL to article row dict. Also includes entries keyed
        by "title::date" for title+date matches.
    """
    if not urls:
        return {}

    result: dict[str, dict] = {}

    with get_connection(db_path) as conn:
        # Batch query by URL
        placeholders = ",".join("?" * len(urls))
        cursor = conn.execute(
            f"SELECT url, title, published_at, content_hash, notified_at "
            f"FROM articles WHERE url IN ({placeholders})",
            urls,
        )
        for row in cursor.fetchall():
            row_dict = dict(row)
            result[row_dict["url"]] = row_dict

        # Batch query by title+date
        if titles_dates:
            pairs = [
                (t, d) for t, d in titles_dates
                if t is not None and d is not None
            ]
            if pairs:
                or_clauses = " OR ".join(
                    "(title = ? AND published_at = ?)" for _ in pairs
                )
                params = []
                for t, d in pairs:
                    params.extend([t, d])
                cursor = conn.execute(
                    f"SELECT url, title, published_at, content_hash, notified_at "
                    f"FROM articles WHERE {or_clauses}",
                    params,
                )
                for row in cursor.fetchall():
                    row_dict = dict(row)
                    key = f"{row_dict['title']}::{row_dict['published_at']}"
                    if key not in result:
                        result[key] = row_dict

    return result


def purge_old_articles(db_path: str, days: int = 30) -> int:
    """Delete articles older than the specified number of days.

    Args:
        db_path: Path to the SQLite database file.
        days: Maximum age of articles to keep.

    Returns:
        Number of articles deleted.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM articles WHERE created_at < ?",
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount


def get_article_by_title_date(
    db_path: str, title: str, published_at: str
) -> dict | None:
    """Retrieve an article from the database by title and published date.

    Args:
        db_path: Path to the SQLite database file.
        title: Article title to search.
        published_at: Publication date in ISO8601 format.

    Returns:
        Dictionary containing article data if found, None otherwise.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, url, source, title, published_at, content_hash, notified_at, created_at
            FROM articles
            WHERE title = ? AND published_at = ?
            """,
            (title, published_at)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)


def get_recent_articles(
    db_path: str,
    days: int = 7,
    sources: list[str] | None = None,
) -> list[dict]:
    """Get articles from the past N days, optionally filtered by source.

    Args:
        db_path: Path to the SQLite database file.
        days: Number of days to look back.
        sources: Optional list of source names to filter by.

    Returns:
        List of article dicts ordered by source then published_at.
    """
    from datetime import timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with get_connection(db_path) as conn:
        if sources:
            placeholders = ",".join("?" * len(sources))
            cursor = conn.execute(
                f"SELECT url, source, title, published_at, notified_at "
                f"FROM articles "
                f"WHERE notified_at IS NOT NULL AND created_at >= ? "
                f"AND source IN ({placeholders}) "
                f"ORDER BY source, published_at DESC",
                [cutoff] + sources,
            )
        else:
            cursor = conn.execute(
                "SELECT url, source, title, published_at, notified_at "
                "FROM articles "
                "WHERE notified_at IS NOT NULL AND created_at >= ? "
                "ORDER BY source, published_at DESC",
                (cutoff,),
            )
        return [dict(row) for row in cursor.fetchall()]


def reset_db(db_path: str) -> None:
    """Drop and recreate the articles table. USE WITH CAUTION.

    Args:
        db_path: Path to the SQLite database file.
    """
    with get_connection(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS articles")
        conn.commit()
    init_db(db_path)


def delete_db(db_path: str) -> bool:
    """Delete the database file if it exists.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        True if file was deleted, False if it didn't exist.
    """
    import os
    if os.path.exists(db_path):
        os.remove(db_path)
        return True
    return False
