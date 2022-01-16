from typing import Optional, Dict, List
import aiosqlite as asql
import json
import datetime as dt
from collections import namedtuple

from rsstool.constants import DB_LOC


async def maybe_get_cache(feed_id: str):
    async with asql.connect(DB_LOC) as db:
        params = {"id": feed_id, "min_dt": (dt.datetime.utcnow() - dt.timedelta(minutes=15)).timestamp()}
        async with db.execute(
            "SELECT value FROM feed_cache WHERE feed_id = :id AND created >= :min_dt ORDER BY created DESC LIMIT 1",
            params,
        ) as cursor:
            async for row in cursor:
                return row[0]
    return None


async def save_to_cache(feed_id, rendered_feed: str):
    async with asql.connect(DB_LOC) as db:
        params = {"min_dt": (dt.datetime.utcnow() - dt.timedelta(minutes=15)).timestamp()}
        await db.execute("DELETE FROM feed_cache WHERE created < :min_dt", params)

        params = {"id": feed_id, "value": rendered_feed, "created": dt.datetime.utcnow().timestamp()}
        await db.execute("INSERT INTO feed_cache(feed_id, value, created) VALUES (:id, :value, :created)", params)
        await db.commit()


Feed = namedtuple("Feed", ["feed_id", "type", "config", "last_accessed", "created"])


async def insert_feed(feed_id: str, type: str, config: Dict, created: Optional[dt.datetime] = None):
    if created is None:
        created = dt.datetime.utcnow()

    async with asql.connect(DB_LOC) as db:
        params = {
            "id": feed_id,
            "type": type,
            "config": json.dumps(config),
            "last_accessed": None,
            "created": created.timestamp(),
            "deleted": 0,
        }
        await db.execute(
            """INSERT INTO feed(id, type, config, last_accessed, created, deleted) VALUES (
            :id, :type, :config, :last_accessed, :created, :deleted
        )""",
            params,
        )
        await db.commit()


async def get_feed(feed_id) -> Optional[Feed]:
    async with asql.connect(DB_LOC) as db:
        params = {"id": feed_id}
        async with db.execute(
            "SELECT id, type, config, last_accessed, created FROM feed WHERE id = :id AND deleted = 0 LIMIT 1", params
        ) as cursor:
            async for row in cursor:
                return Feed(
                    feed_id=row[0],
                    type=row[1],
                    config=json.loads(row[2]),
                    last_accessed=None if not row[3] else dt.datetime.utcfromtimestamp(row[3]),
                    created=dt.datetime.utcfromtimestamp(row[4]),
                )
    return None


async def record_feed_access(feed_id: str):
    async with asql.connect(DB_LOC) as db:
        params = {"id": feed_id, "now": dt.datetime.utcnow().timestamp()}
        await db.execute("UPDATE feed SET last_accessed = :now WHERE id = :id", params)
        await db.commit()


FeedItem = namedtuple(
    "FeedItem", ["id", "feed_id", "link", "title", "author", "categories", "publish_date", "click_count"]
)


async def insert_feed_items(feed_items: List[FeedItem]):
    async with asql.connect(DB_LOC) as db:
        await db.execute("BEGIN")
        all_params = [
            {
                "id": fi.id,
                "feed_id": fi.feed_id,
                "link": fi.link,
                "title": fi.title,
                "author": fi.author,
                "categories": json.dumps(fi.categories),
                "publish_date": fi.publish_date.timestamp(),
                "click_count": fi.click_count,
            }
            for fi in feed_items
        ]
        await db.executemany(
            """INSERT INTO feed_item(id, feed_id, link, title, author, categories, publish_date, click_count)
            VALUES (:id, :feed_id, :link, :title, :author, :categories, :publish_date, :click_count)
            ON CONFLICT(feed_id, link) DO UPDATE SET
              title = excluded.title,
              author = excluded.author,
              categories = excluded.categories,
              publish_date = excluded.publish_date""",
            all_params,
        )
        await db.commit()
