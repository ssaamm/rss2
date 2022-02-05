from typing import List
import textwrap
import asyncio
import sys

import aiosqlite as asql

from rsstool.constants import DB_LOC

migrations = {
    "init": [
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
    ],
    "add_ml": [
        """\
    ALTER TABLE feed_item ADD COLUMN score REAL;
        """,
        """\
    CREATE TABLE train_job (
        feed_id TEXT,
        git_sha TEXT,
        train_start INTEGER,
        train_duration INTEGER,
        n_rows INTEGER,
        n_positives INTEGER,
        nonzero_coef_ct INTEGER,
        best_params TEXT,
        best_score REAL,
        FOREIGN KEY(feed_id) REFERENCES feed(id)
    );
        """,
        """\
    CREATE TABLE feed_item_score (
        item_id TEXT,
        score REAL,
        time_scored INTEGER,
        FOREIGN KEY(item_id) REFERENCES feed_item(id)
    );
        """,
    ],
}


async def run_migrations(names: List[str]):
    async with asql.connect(DB_LOC) as db:
        for name in names:
            queries = ["BEGIN"] + migrations[name] + ["COMMIT"]
            for query in queries:
                q = textwrap.dedent(query)
                print("Running query:", q)
                await db.execute(q)
            await db.commit()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        if len(sys.argv) <= 2:
            raise RuntimeError("must specify migrations to run")
        asyncio.run(run_migrations(sys.argv[2:]))
    elif len(sys.argv) == 1:
        asyncio.run(run_migrations(["init"]))
    else:
        raise RuntimeError("not sure what you are trying to do")
