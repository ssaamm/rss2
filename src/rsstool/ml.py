import sqlite3
import contextlib
import pickle
import os
import json
import logging
import datetime as dt
import time
from urllib.parse import urlparse

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import make_pipeline, Pipeline
from sklearn.compose import ColumnTransformer

from sklearn.feature_extraction.text import TfidfVectorizer, HashingVectorizer
from sklearn.preprocessing import MultiLabelBinarizer, OneHotEncoder, FunctionTransformer, StandardScaler
from sklearn.feature_selection import VarianceThreshold, SelectPercentile
from sklearn.linear_model import LogisticRegression

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


class MLBWrapper(BaseEstimator, TransformerMixin):
    def __init__(self):
        self.mlb = MultiLabelBinarizer()

    def fit(self, X, y=None):
        self.mlb.fit(X)
        return self

    def transform(self, X):
        return self.mlb.transform(X)


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


def build_model(feed_id, in_df, n_iter=1_000, n_jobs=4):
    if (in_df["feed_id"] != feed_id).sum() > 0:
        raise ValueError(f"Expected all feed_id values to be {feed_id}")
    LOG.info(f"Building model for {feed_id}: {in_df.shape[0]} rows")

    tr = ColumnTransformer(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2)), "title"),
            ("hashing", HashingVectorizer(), "title"),
            ("mlb", MLBWrapper(), "categories"),
            ("ohe", OneHotEncoder(handle_unknown="ignore"), ["author"]),
            ("domain", make_pipeline(FunctionTransformer(get_netloc), OneHotEncoder(handle_unknown="ignore")), "link"),
            ("url_len", FunctionTransformer(get_strlen), "link"),
            ("title_len", FunctionTransformer(get_strlen), "title"),
        ],
        remainder="drop",
        n_jobs=1,
        sparse_threshold=0,
    )

    p = Pipeline(
        [
            ("tr", tr),
            ("scale", StandardScaler()),
            ("sel_var", VarianceThreshold(threshold=1e-3)),
            ("sel_fcl", SelectPercentile(percentile=10)),
            ("clf", LogisticRegression(n_jobs=2, solver="saga", penalty="elasticnet", tol=1e-3, max_iter=100_000)),
        ]
    )

    search = RandomizedSearchCV(
        p,
        {
            "tr__tfidf__ngram_range": [(1, 1), (1, 2)],
            "tr__hashing__n_features": st.randint(10, 300),
            "tr__hashing__norm": ["l1", "l2"],
            "tr__hashing__binary": [True, False],
            "sel_var__threshold": st.uniform(0, 1),
            "sel_fcl__percentile": st.randint(10, 90),
            "clf__C": st.uniform(0.1, 0.99),
            "clf__l1_ratio": st.uniform(0, 1),
            "clf__class_weight": [None, "balanced"],
        },
        scoring="roc_auc",
        cv=5,
        n_jobs=n_jobs,
        n_iter=n_iter,
    )

    search.fit(in_df, in_df["has_clicks"])

    LOG.info(f"{feed_id} params: {search.best_params_}")
    LOG.info(f"{feed_id} score: {search.best_score_:.03f}")

    return search


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
        model = build_model(feed_id, in_df, n_iter=4)
        meta = {
            "train_start": start_time,
            "train_duration": time.perf_counter() - start_ctr,
            "git_sha": "lol",  # TODO
            "n_rows": in_df.shape[0],
            "n_positives": in_df["has_clicks"].sum(),
            "nonzero_coef_ct": 0,  # TODO
            "best_params": model.best_params_,
            "best_score": model.best_score_,
        }
        with open(os.path.join(MODELS_LOC, f"{feed_id}.pkl"), "wb") as f:
            pickle.dump({"model": model, "meta": meta}, f)
