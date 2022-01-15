import uuid
import json
import pickle
from typing import Dict
import itertools as it
import datetime as dt
import time
import logging

import asyncio
import aiosqlite as asql
import aiohttp as ahttp
import PyRSS2Gen as rss
import feedparser

from constants import DB_LOC
from models import CreateFeedRequest, CreateCombinedFeedRequest, CreateFilteredFeedRequest, FeedResponse, FeedNotFound

HEADERS = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:95.0) Gecko/20100101 Firefox/95.0"}
LOG = logging.getLogger(__name__)


async def make_combined_feed(request: CreateCombinedFeedRequest):
    # TODO validate feed sources
    feed_id = str(uuid.uuid4())
    async with asql.connect(DB_LOC) as db:
        params = {
            "id": feed_id,
            "type": request.type,
            "config": json.dumps({"sources": request.sources}),
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
    return FeedResponse(url=f"/api/v1/feed/{feed_id}")


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


def datetime_from_struct_time(st: time.struct_time) -> dt.datetime:
    return dt.datetime(
        year=st.tm_year,
        month=st.tm_mon,
        day=st.tm_mday,
        hour=st.tm_hour,
        minute=st.tm_min,
        second=st.tm_sec,
    )


def get_description(e):
    description = e["summary"]
    if "content" in e:
        if len(e["content"]) > 1:
            LOG.warning("more content than expected")
        description = "<br>".join(c["value"] for c in e["content"] if c["type"] == "text/html")
    return description


def build_entries(entries):
    for e in entries:
        yield rss.RSSItem(
            title=e["title"],
            link=e["link"],
            description=get_description(e),
            author=e["author"],
            categories=[tag["term"] for tag in e.get("tags", [])],
            pubDate=datetime_from_struct_time(e["published_parsed"]),
            source=None,
        )


async def get_feed(session, url) -> str:
    async with session.get(url) as response:
        return await response.text()


async def render_combined_feed(config: Dict):
    bodies = []
    async with ahttp.ClientSession(headers=HEADERS) as session:
        tasks = [asyncio.ensure_future(get_feed(session, url)) for url in config["sources"]]
        bodies = await asyncio.gather(*tasks)

    feeds = [feedparser.parse(b) for b in bodies]
    all_items = sorted(it.chain.from_iterable(build_entries(f["entries"]) for f in feeds), key=lambda ri: ri.pubDate)
    return rss.RSS2(
        title="TODO", link="TODO", description="TODO", lastBuildDate=dt.datetime.utcnow(), items=all_items
    ).to_xml()


async def save_to_cache(feed_id, rendered_feed: str):
    async with asql.connect(DB_LOC) as db:
        params = {"id": feed_id, "value": rendered_feed, "created": dt.datetime.utcnow().timestamp()}
        await db.execute("INSERT INTO feed_cache(feed_id, value, created) VALUES (:id, :value, :created)", params)
        await db.commit()
        # TODO delete old values out of cache


async def render_filtered_feed(config: Dict) -> str:
    async with ahttp.ClientSession(headers=HEADERS) as session:
        body = await get_feed(session, config["source"])
    feed = feedparser.parse(body)
    filtered_items = []
    for entry in feed["entries"]:
        if config["require_in_title"] and any(
            kw.lower() not in entry["title"].lower() for kw in config["require_in_title"]
        ):
            continue
        if config["disallow_in_title"] and any(
            kw.lower() in entry["title"].lower() for kw in config["disallow_in_title"]
        ):
            continue

        filtered_items.append(
            rss.RSSItem(
                title=entry["title"],
                link=entry["link"],
                description=get_description(entry),
                author=entry["author"],
                categories=[tag["term"] for tag in entry.get("tags", [])],
                pubDate=datetime_from_struct_time(entry["published_parsed"]),
                source=None,
            )
        )
    return rss.RSS2(
        title=feed["feed"]["title"],
        link=feed["feed"]["link"],
        description=feed["feed"]["subtitle"],
        lastBuildDate=dt.datetime.utcnow(),
        items=filtered_items,
    ).to_xml()


async def render_feed(feed_id) -> str:
    cached_value = await maybe_get_cache(feed_id)
    if cached_value is not None:
        return cached_value

    handlers = {
        "combine": render_combined_feed,
        "filter": render_filtered_feed,
    }
    async with asql.connect(DB_LOC) as db:
        params = {"id": feed_id}
        async with db.execute("SELECT type, config FROM feed WHERE id = :id AND deleted = 0 LIMIT 1", params) as cursor:
            async for row in cursor:
                handler = handlers.get(row[0])
                if handler is None:
                    raise RuntimeError(f"Cannot render feed for {row[0]}")

                rendered_feed = await handler(json.loads(row[1]))
                await save_to_cache(feed_id, rendered_feed)
                return rendered_feed
    raise FeedNotFound()


async def make_filtered_feed(request: CreateCombinedFeedRequest):
    feed_id = str(uuid.uuid4())
    async with asql.connect(DB_LOC) as db:
        params = {
            "id": feed_id,
            "type": request.type,
            "config": json.dumps(
                {
                    "source": request.source,
                    "disallow_in_title": request.disallow_in_title,
                    "require_in_title": request.require_in_title,
                }
            ),
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
    return FeedResponse(url=f"/api/v1/feed/{feed_id}")


def validate_feed_request(r):
    if isinstance(r, CreateFilteredFeedRequest) and r.type != "filter":
        raise ValueError("type should be filter")
    if isinstance(r, CreateCombinedFeedRequest) and r.type != "combine":
        raise ValueError("type should be combine")
    elif not isinstance(r, (CreateFilteredFeedRequest, CreateCombinedFeedRequest)):
        raise ValueError("unknown type")


async def handle_create_feed_request(request: CreateFeedRequest):
    validate_feed_request(request)

    handlers = {
        CreateCombinedFeedRequest: make_combined_feed,
        CreateFilteredFeedRequest: make_filtered_feed,
    }
    this_handler = None
    for type, handler in handlers.items():
        if isinstance(request, type):
            this_handler = handler
            break

    if this_handler is None:
        raise RuntimeError("cannot handle this feed request")

    return await this_handler(request)
