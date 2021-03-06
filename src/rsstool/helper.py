import uuid
import json
import pickle
from typing import Dict, List
import itertools as it
import datetime as dt
import time
import logging
import os
import asyncio

import pandas as pd
from fastapi import BackgroundTasks
import aiohttp as ahttp
import PyRSS2Gen as rss
import feedparser

from rsstool.constants import DB_LOC, MODELS_LOC
import rsstool.db_helper as db
import rsstool.models as mdl
import rsstool.ml_base as mlb

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
            author=e.get("author", e.get("dc:creator", None)),
            categories=[tag["term"] for tag in e.get("tags", [])],
            pubDate=datetime_from_struct_time(e["published_parsed"]),
            source=None,
        )


async def fetch_feed(session, url) -> str:
    async with session.get(url) as response:
        return await response.text()


def build_link(feed: db.Feed):
    return "http://" + os.getenv("VIRTUAL_HOST", "localhost:8000") + "/api/v1/feed/" + feed.feed_id


def build_item_link(feed_item: db.FeedItem):
    host = os.getenv("VIRTUAL_HOST", "localhost:8000")
    return f"http://{host}/api/v1/feed/{feed_item.feed_id}/item/{feed_item.id}"


async def render_combined_feed(feed: db.Feed, _: BackgroundTasks):
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


async def render_filtered_feed(feed: db.Feed, _: BackgroundTasks) -> str:
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

        link = entry.get("link")
        if link is None or entry.get("itunes_episodetype"):
            link = entry.get("links", [{"href": feed.config["source"]}])[0]
            link = link["href"]

        filtered_items.append(
            rss.RSSItem(
                title=entry.get("title"),
                link=link,
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


def _render_one_item(item: db.FeedItem):
    if item.score:
        return f'<li>{item.score:.03f} / {item.publish_date} - <a href="{build_item_link(item)}">{item.title}</a> ({item.author})</li>'
    return f'<li>{item.publish_date} - <a href="{build_item_link(item)}">{item.title}</a> ({item.author})</li>'


def build_digest_entry(feed: db.Feed, window_start: dt.datetime, items_in_window: List[db.FeedItem]):
    content = "<p><ul>" + "".join(_render_one_item(i) for i in items_in_window) + "</ul></p>"
    combined_authors = ", ".join(frozenset(i.author or "Unknown author" for i in items_in_window))
    combined_categories = frozenset(it.chain.from_iterable(i.categories for i in items_in_window))
    return rss.RSSItem(
        title=f"Digest for {window_start}",
        link=build_link(feed),
        guid=f"{feed.feed_id}-{window_start:%Y%m%d%H%M%S}",
        description=content,
        author=combined_authors,
        categories=combined_categories,
        pubDate=window_start,
        source=None,
    )


async def render_digest_feed(feed: db.Feed, bg: BackgroundTasks) -> str:
    windows = await db.get_windowed_items(feed)
    bg.add_task(index_source, feed.feed_id)

    feed_title = feed.config.get("title", "an RSS feed")
    return rss.RSS2(
        title=f"{feed.config['cadence']} digest of {feed_title}",
        link=build_link(feed),
        description=feed.config.get("description", None),
        lastBuildDate=dt.datetime.utcnow(),
        items=[
            build_digest_entry(feed, window_start, items_in_window)
            for window_start, items_in_window in windows.items()
            if items_in_window
        ],
    ).to_xml()


async def render_feed(feed_id, bg: BackgroundTasks, skipcache: bool) -> str:
    tasks = [
        asyncio.ensure_future(db.maybe_get_cache(feed_id, skipcache)),
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
        "digest": render_digest_feed,
    }
    handler = handlers.get(feed.type)
    if handler is None:
        raise RuntimeError(f"Cannot render '{feed.type}' feed")

    rendered_feed = await handler(feed, bg)
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


def maybe_load_model(feed: db.Feed):
    try:
        with open(os.path.join(MODELS_LOC, feed.feed_id + ".pkl"), "rb") as f:
            model_with_meta = pickle.load(f)
        return model_with_meta["model"]
    except (FileNotFoundError,):
        return None


def score_items(items: List[db.FeedItem], model):
    df = pd.DataFrame(
        [
            {
                "title": i.title,
                "categories": i.categories,
                "author": i.author,
                "link": i.link,
            }
            for i in items
        ]
    )
    scores = model.predict_proba(df)[:, 1]
    return [i._replace(score=score) for i, score in zip(items, scores)]


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
            link=entry.get("link"),
            title=entry.get("title"),
            author=entry.get("author"),
            categories=list({tag["term"].lower() for tag in entry.get("tags", [])}),
            publish_date=datetime_from_struct_time(entry["published_parsed"]),
            click_count=0,
            score=None,
        )
        for entry in parsed_feed["entries"]
    ]

    model = maybe_load_model(feed)
    if model is not None:
        feed_items = score_items(feed_items, model)

    await db.update_digest_meta(
        feed, title=parsed_feed["feed"]["title"], description=parsed_feed["feed"]["description"]
    )
    await db.insert_feed_items(feed_items)


async def make_digest_feed(request: mdl.CreateDigestFeedRequest, bg: BackgroundTasks):
    feed_id = str(uuid.uuid4())
    await db.insert_feed(
        feed_id,
        request.type,
        {
            "source": request.source,
            "cadence": request.cadence,
            "length": request.length,
            "start_timestamp": request.start_timestamp,
        },
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
