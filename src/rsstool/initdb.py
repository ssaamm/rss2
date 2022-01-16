import textwrap
import asyncio

import aiosqlite as asql

from rsstool.constants import DB_LOC

queries = [
    """\
    CREATE TABLE feed (
        id TEXT PRIMARY KEY,
        type TEXT,
        config TEXT,
        last_accessed INTEGER,
        created INTEGER,
        deleted INTEGER
    ) WITHOUT ROWID;
    """,
    """\
    CREATE TABLE feed_cache (
        feed_id TEXT,
        value TEXT,
        created INTEGER,
        FOREIGN KEY(feed_id) REFERENCES feed(id)
    );
    """,
    """\
    CREATE TABLE feed_item (
        id TEXT PRIMARY KEY,
        feed_id TEXT,
        link TEXT,
        title TEXT,
        author TEXT,
        categories TEXT,
        publish_date TEXT,
        click_count INTEGER,
        FOREIGN KEY(feed_id) REFERENCES feed(id),
        UNIQUE (feed_id, link)
    ) WITHOUT ROWID;
    """,
]


async def initialize_db():
    async with asql.connect(DB_LOC) as db:
        for query in queries:
            q = textwrap.dedent(query)
            print(q)
            await db.execute(q)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(initialize_db())
