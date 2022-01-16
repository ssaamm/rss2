from typing import Optional, Dict, List
import json
import datetime as dt
from collections import namedtuple
import asyncio

import aiosqlite as asql

from rsstool.constants import DB_LOC
import rsstool.models as mdl


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


async def _increment_click_count(feed_id: str, item_id: str, db):
    params = {"feed_id": feed_id, "item_id": item_id}
    await db.execute(
        "UPDATE feed_item SET click_count = click_count + 1 WHERE feed_id = :feed_id AND id = :item_id", params
    )


async def _get_link(feed_id: str, item_id: str, db):
    params = {"feed_id": feed_id, "item_id": item_id}
    async with db.execute(
        "SELECT link FROM feed_item WHERE id = :item_id and feed_id = :feed_id LIMIT 1", params
    ) as cursor:
        async for row in cursor:
            return row[0]


async def record_click_and_get_link(feed_id: str, item_id: str):
    async with asql.connect(DB_LOC) as db:
        tasks = [
            asyncio.ensure_future(_increment_click_count(feed_id, item_id, db)),
            asyncio.ensure_future(_get_link(feed_id, item_id, db)),
        ]
        _, link = await asyncio.gather(*tasks)
        await db.commit()
    return link


async def _get_feed_items_in_window(db, feed_id: str, start: dt.datetime, end: dt.datetime) -> List[FeedItem]:
    params = {"feed_id": feed_id, "start": start.timestamp(), "end": end.timestamp()}
    all_items = []
    async with db.execute(
        """SELECT 
            id, feed_id, link, title, author, categories, publish_date, click_count
            FROM feed_item
            WHERE feed_id = :feed_id
              AND publish_date >= :start AND publish_date < :end""",
        params,
    ) as cursor:
        async for row in cursor:
            all_items.append(
                FeedItem(
                    id=row[0],
                    feed_id=row[1],
                    link=row[2],
                    title=row[3],
                    author=row[4],
                    categories=json.loads(row[5]),
                    publish_date=dt.datetime.utcfromtimestamp(float(row[6])),
                    click_count=row[7],
                )
            )
    return all_items


async def get_windowed_items(feed: Feed, limit: int = 10):
    if feed.type != "digest":
        raise ValueError("can only get windowed items for digest feeds")

    start = dt.datetime.utcfromtimestamp(feed.config["start_timestamp"])
    now = dt.datetime.utcnow()
    window_size = {
        "hourly": dt.timedelta(hours=1),  # TODO use the enum?
        "daily": dt.timedelta(days=1),
        "weekly": dt.timedelta(days=7),
    }[feed.config["cadence"]]
    windows_completed = int((now - start) / window_size)
    # TODO what if < 1?

    first_window_start = start + (windows_completed - limit) * window_size
    window_dates = [
        (first_window_start + i * window_size, first_window_start + (i + 1) * window_size) for i in range(limit)
    ]
    async with asql.connect(DB_LOC) as db:
        tasks = [asyncio.ensure_future(_get_feed_items_in_window(db, feed.feed_id, s, e)) for s, e in window_dates]
        results = await asyncio.gather(*tasks)

    return {wd[0]: r for wd, r in zip(window_dates, results)}


async def update_digest_meta(feed: Feed, title, description):
    if "title" in feed.config and "description" in feed.config:
        return

    new_config = {**feed.config, "title": title, "description": description}
    async with asql.connect(DB_LOC) as db:
        params = {"config": json.dumps(new_config), "id": feed.feed_id}
        await db.execute("UPDATE feed SET config = :config WHERE id = :id", params)
        await db.commit()
