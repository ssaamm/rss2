import sqlite3
import contextlib
import json
import logging
import datetime as dt
from urllib.parse import urlparse

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import make_pipeline, Pipeline
from sklearn.compose import ColumnTransformer

from sklearn.feature_extraction.text import TfidfVectorizer, HashingVectorizer
from sklearn.preprocessing import MultiLabelBinarizer, OneHotEncoder, FunctionTransformer, StandardScaler
from sklearn.feature_selection import VarianceThreshold, SelectPercentile

from sklearn.model_selection import RandomizedSearchCV
import scipy.stats as st

import pandas as pd
import numpy as np

from rsstool.constants import DB_LOC, MODELS_LOC

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
MIN_ITEMS_FOR_MODEL = 30


def get_training_data(db_loc: str = DB_LOC) -> pd.DataFrame:
    rows = []
    cols = []
    query = """
    select *, click_count > 0 as has_clicks
    from feed_item
    where publish_date < :max_dt
    """

    with sqlite3.connect(db_loc) as conn:
        with contextlib.closing(conn.cursor()) as c:
            for row in c.execute("select max(publish_date) from feed_item"):
                max_pub_date = float(row[0])
            for row in c.execute(query, {"max_dt": max_pub_date - 24 * 60 * 60}):
                rows.append(row)
            cols = [col[0] for col in c.description]
    feed_items = pd.DataFrame(rows, columns=cols)
    feed_items["categories"] = feed_items["categories"].apply(json.loads)
    return feed_items


def get_netloc(url):
    if isinstance(url, str):
        return urlparse(url).netloc
    if isinstance(url, pd.Series):
        return url.apply(get_netloc).values.reshape(-1, 1)


def get_strlen(url):
    if isinstance(url, str):
        val = len(url)
    if isinstance(url, pd.Series):
        val = url.str.len()
    return np.log(val).values.reshape(-1, 1)


def build_model(feed_id, in_df):
    if (in_df["feed_id"] != feed_id).sum() > 0:
        raise ValueError(f"Expected all feed_id values to be {feed_id}")
    LOG.info(f"Building model for {feed_id}: {in_df.shape[0]} rows")
    return None


if __name__ == "__main__":
    start_time = dt.datetime.utcnow().timestamp()
    feed_items = get_training_data()
    feed_info = feed_items.groupby("feed_id")["has_clicks"].agg(["mean", "count"])

    too_small_ct = (feed_info["count"] < MIN_ITEMS_FOR_MODEL).sum()
    LOG.info(f"Will not train models for {too_small_ct} feeds (not enough training data)")

    for feed_id, count in feed_info["count"].iteritems():
        if count < MIN_ITEMS_FOR_MODEL:
            continue

        in_df = feed_items.query("feed_id == @feed_id")

        start_ctr = time.perf_counter()
        model = build_model(feed_id, in_df)
        meta = {
            "train_start": start_time,
            "train_duration": time.perf_counter() - start_ctr,
            "git_sha": "lol",  # TODO
            "n_rows": in_df.shape[0],
            "n_positives": in_df["has_clicks"].sum(),
            "nonzero_coef_ct": 0,  # TODO
            "best_params": {},  # TODO
            "best_score": 0.001,  # TODO
        }
        with open(MODELS_LOC / f"{feed_id}.pkl", "wb") as f:
            f.write({"model": model, "meta": meta})
