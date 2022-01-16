import uuid
import json
import pickle
from typing import Dict
import itertools as it
import datetime as dt
import time
import logging
import os

from fastapi import BackgroundTasks
import asyncio
import aiohttp as ahttp
import PyRSS2Gen as rss
import feedparser

from rsstool.constants import DB_LOC
import rsstool.db_helper as db
import rsstool.models as mdl

HEADERS = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:95.0) Gecko/20100101 Firefox/95.0"}
LOG = logging.getLogger(__name__)


async def make_combined_feed(request: mdl.CreateCombinedFeedRequest, _: BackgroundTasks):
    # TODO validate feed sources
    feed_id = str(uuid.uuid4())
    await db.insert_feed(
        feed_id, request.type, {"sources": request.sources, "title": request.title, "description": request.description}
    )
    return mdl.FeedResponse(url=f"/api/v1/feed/{feed_id}")


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


async def fetch_feed(session, url) -> str:
    async with session.get(url) as response:
        return await response.text()


def build_link(feed: db.Feed):
    return "http://" + os.getenv("VIRTUAL_HOST", "localhost:8000") + "/api/v1/feed/" + feed.feed_id


async def render_combined_feed(feed: db.Feed):
    bodies = []
    async with ahttp.ClientSession(headers=HEADERS) as session:
        tasks = [asyncio.ensure_future(fetch_feed(session, url)) for url in feed.config["sources"]]
        bodies = await asyncio.gather(*tasks)

    feeds = [feedparser.parse(b) for b in bodies]
    all_items = sorted(it.chain.from_iterable(build_entries(f["entries"]) for f in feeds), key=lambda ri: ri.pubDate)
    return rss.RSS2(
        title=feed.config.get("title", "A combined feed"),
        link=build_link(feed),
        description=feed.config.get("description", "A combined feed"),
        lastBuildDate=dt.datetime.utcnow(),
        items=all_items,
    ).to_xml()


async def render_filtered_feed(feed: db.Feed) -> str:
    async with ahttp.ClientSession(headers=HEADERS) as session:
        body = await fetch_feed(session, feed.config["source"])
    parsed_feed = feedparser.parse(body)
    filtered_items = []
    for entry in parsed_feed["entries"]:
        if feed.config["require_in_title"] and any(
            kw.lower() not in entry["title"].lower() for kw in feed.config["require_in_title"]
        ):
            continue
        if feed.config["disallow_in_title"] and any(
            kw.lower() in entry["title"].lower() for kw in feed.config["disallow_in_title"]
        ):
            continue

        filtered_items.append(
            rss.RSSItem(
                title=entry["title"],
                link=entry.get("link", feed.config["source"]),
                description=get_description(entry),
                author=entry["author"],
                categories=[tag["term"] for tag in entry.get("tags", [])],
                pubDate=datetime_from_struct_time(entry["published_parsed"]),
                source=None,
            )
        )
    return rss.RSS2(
        title=parsed_feed["feed"]["title"],
        link=parsed_feed["feed"]["link"],
        description=parsed_feed["feed"]["subtitle"],
        lastBuildDate=dt.datetime.utcnow(),
        items=filtered_items,
    ).to_xml()


async def render_feed(feed_id) -> str:
    tasks = [
        asyncio.ensure_future(db.maybe_get_cache(feed_id)),
        asyncio.ensure_future(db.record_feed_access(feed_id)),
    ]
    # The order of result values corresponds to the order of awaitables
    # https://docs.python.org/3/library/asyncio-task.html#asyncio.gather
    cached_value, _ = await asyncio.gather(*tasks)
    if cached_value is not None:
        return cached_value

    feed = await db.get_feed(feed_id)
    if feed is None:
        raise mdl.FeedNotFound()

    handlers = {
        "combine": render_combined_feed,
        "filter": render_filtered_feed,
    }
    handler = handlers.get(feed.type)
    if handler is None:
        raise RuntimeError(f"Cannot render feed for {row[0]}")

    rendered_feed = await handler(feed)
    await db.save_to_cache(feed_id, rendered_feed)
    return rendered_feed


async def make_filtered_feed(request: mdl.CreateCombinedFeedRequest, _: BackgroundTasks):
    feed_id = str(uuid.uuid4())
    await db.insert_feed(
        feed_id,
        request.type,
        {
            "source": request.source,
            "disallow_in_title": request.disallow_in_title,
            "require_in_title": request.require_in_title,
        },
    )
    return mdl.FeedResponse(url=f"/api/v1/feed/{feed_id}")


async def index_source(feed_id: str):
    feed = await db.get_feed(feed_id)
    if feed.type != "digest":
        raise ValueError("can only index 'digest' feeds")

    async with ahttp.ClientSession(headers=HEADERS) as session:
        body = await fetch_feed(session, feed.config["source"])
    parsed_feed = feedparser.parse(body)

    feed_items = [
        db.FeedItem(
            id=str(uuid.uuid4()),
            feed_id=feed_id,
            link=entry["link"],
            title=entry["title"],
            author=entry["author"],
            categories=[tag["term"] for tag in entry.get("tags", [])],
            publish_date=datetime_from_struct_time(entry["published_parsed"]),
            click_count=0,
        )
        for entry in parsed_feed["entries"]
    ]
    await db.insert_feed_items(feed_items)


async def make_digest_feed(request: mdl.CreateDigestFeedRequest, bg: BackgroundTasks):
    feed_id = str(uuid.uuid4())
    await db.insert_feed(
        feed_id,
        request.type,
        {"source": request.source, "cadence": request.cadence, "start_timestamp": request.start_timestamp},
    )
    bg.add_task(index_source, feed_id)
    return mdl.FeedResponse(url=f"/api/v1/feed/{feed_id}")


def validate_feed_request(r):
    known_types = {
        mdl.CreateFilteredFeedRequest: "filter",
        mdl.CreateCombinedFeedRequest: "combine",
        mdl.CreateDigestFeedRequest: "digest",
    }
    for request_type, type_value in known_types.items():
        if isinstance(r, request_type):
            if r.type == type_value:
                return
            else:
                raise ValueError(f"type should be '{type_value}' for {type(r)}")
    raise ValueError(f"Unknown type {type(r)}")


async def handle_create_feed_request(request: mdl.CreateFeedRequest, bg: BackgroundTasks):
    validate_feed_request(request)

    handlers = {
        mdl.CreateCombinedFeedRequest: make_combined_feed,
        mdl.CreateFilteredFeedRequest: make_filtered_feed,
        mdl.CreateDigestFeedRequest: make_digest_feed,
    }
    this_handler = None
    for type, handler in handlers.items():
        if isinstance(request, type):
            this_handler = handler
            break

    if this_handler is None:
        raise RuntimeError("cannot handle this feed request")

    return await this_handler(request, bg)
