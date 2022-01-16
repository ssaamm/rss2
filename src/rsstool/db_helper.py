from typing import Optional, Dict
import aiosqlite as asql
import json
import datetime as dt
from collections import namedtuple

from rsstool.constants import DB_LOC


async def insert_feed(feed_id: str, type: str, config: Dict):
    async with asql.connect(DB_LOC) as db:
        params = {
            "id": feed_id,
            "type": type,
            "config": json.dumps(config),
            "last_accessed": None,
            "deleted": 0,
        }
        await db.execute(
            """INSERT INTO feed(id, type, config, last_accessed, deleted) VALUES (
            :id, :type, :config, :last_accessed, :deleted
        )""",
            params,
        )
        await db.commit()


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
        params = {"min_dt": (dt.datetime.now() - dt.timedelta(minutes=15)).timestamp()}
        await db.execute("DELETE FROM feed_cache WHERE created < :min_dt", params)

        params = {"id": feed_id, "value": rendered_feed, "created": dt.datetime.utcnow().timestamp()}
        await db.execute("INSERT INTO feed_cache(feed_id, value, created) VALUES (:id, :value, :created)", params)
        await db.commit()


Feed = namedtuple("Feed", ["feed_id", "type", "config", "last_accessed", "deleted"])


async def get_feed(feed_id) -> Optional[Feed]:
    async with asql.connect(DB_LOC) as db:
        params = {"id": feed_id}
        async with db.execute(
            "SELECT id, type, config, last_accessed, deleted FROM feed WHERE id = :id AND deleted = 0 LIMIT 1", params
        ) as cursor:
            async for row in cursor:
                return Feed(
                    feed_id=row[0],
                    type=row[1],
                    config=json.loads(row[2]),
                    last_accessed=None if not row[3] else dt.datetime.utcfromtimestamp(row[3]),
                    deleted=row[4],
                )
    return None
