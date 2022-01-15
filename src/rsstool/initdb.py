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
