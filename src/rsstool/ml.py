import sqlite3
import contextlib
import pickle
import os
import json
import logging
import datetime as dt
import time
import subprocess
import sys

from sklearn.pipeline import make_pipeline, Pipeline
from sklearn.compose import ColumnTransformer

from sklearn.feature_extraction.text import TfidfVectorizer, HashingVectorizer
from sklearn.preprocessing import OneHotEncoder, FunctionTransformer, StandardScaler
from sklearn.feature_selection import VarianceThreshold, SelectPercentile
from sklearn.linear_model import LogisticRegression

from sklearn.model_selection import RandomizedSearchCV
import scipy.stats as st

import pandas as pd
import numpy as np

from rsstool.constants import DB_LOC, MODELS_LOC
import rsstool.ml_base as mlb

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
MIN_ITEMS_FOR_MODEL = 30
EPSILON = 1e-6


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


def build_model(feed_id, in_df, n_iter=1_000, n_jobs=4):
    if (in_df["feed_id"] != feed_id).sum() > 0:
        raise ValueError(f"Expected all feed_id values to be {feed_id}")
    LOG.info(f"Building model for {feed_id}: {in_df.shape[0]} rows")

    tr = ColumnTransformer(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2)), "title"),
            ("hashing", HashingVectorizer(), "title"),
            ("mlb", mlb.MLBWrapper(), "categories"),
            ("ohe", OneHotEncoder(handle_unknown="ignore"), ["author"]),
            (
                "domain",
                make_pipeline(FunctionTransformer(mlb.get_netloc), OneHotEncoder(handle_unknown="ignore")),
                "link",
            ),
            ("url_len", FunctionTransformer(mlb.get_strlen), "link"),
            ("title_len", FunctionTransformer(mlb.get_strlen), "title"),
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
            ("clf", LogisticRegression(n_jobs=1, solver="saga", penalty="elasticnet", tol=1e-3, max_iter=100_000)),
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


def get_coef_ct(est, effectively_zero=EPSILON):
    clf = est.named_steps["clf"]
    nonzero = (np.abs(clf.coef_) > effectively_zero).sum() + (np.abs(clf.intercept_) > effectively_zero).sum()
    total = 1 + clf.coef_.shape[1]
    return {"total": int(total), "nonzero": int(nonzero), "ratio": nonzero / total}


def store_meta(meta, db_loc: str = DB_LOC):
    params = {
        k: meta[k]
        for k in ["feed_id", "git_sha", "train_start", "train_duration", "n_rows", "n_positives", "best_score"]
    }
    params["nonzero_coef_ct"] = meta["coef_ct"]["nonzero"]
    params["best_params"] = json.dumps(meta["best_params"])
    with sqlite3.connect(db_loc) as conn:
        with contextlib.closing(conn.cursor()) as c:
            c.execute(
                """INSERT INTO train_job(feed_id, git_sha, train_start, train_duration, n_rows, n_positives, nonzero_coef_ct, best_params, best_score)
                    VALUES (:feed_id, :git_sha, :train_start, :train_duration, :n_rows, :n_positives, :nonzero_coef_ct, :best_params, :best_score)""",
                params,
            )


def get_git_hash():
    git_hash = os.getenv("GIT_HASH", None)
    if git_hash is None:
        try:
            git_hash = (
                subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True)
                .stdout.decode("utf-8")
                .strip()
            )
        except subprocess.CalledProcessError:
            pass
    return git_hash


def build_all_models(n_iter, n_jobs):
    LOG.info(f"Building models with {n_iter} iters, {n_jobs} jobs")
    start_time = dt.datetime.utcnow().timestamp()
    feed_items = get_training_data()
    git_hash = get_git_hash()
    feed_info = feed_items.groupby("feed_id")["has_clicks"].agg(["mean", "count"])

    for feed_id, count in feed_info["count"].iteritems():
        if count < MIN_ITEMS_FOR_MODEL:
            LOG.info(f"Skipping training for {feed_id} (not enough data)")
            continue

        in_df = feed_items.query("feed_id == @feed_id")

        start_ctr = time.perf_counter()
        try:
            model = build_model(feed_id, in_df, n_iter=n_iter, n_jobs=n_jobs)
        except:
            LOG.exception(f"Problem building model for {feed_id}")
            continue

        meta = {
            "feed_id": feed_id,
            "train_start": start_time,
            "train_duration": time.perf_counter() - start_ctr,
            "git_sha": git_hash,
            "n_rows": in_df.shape[0],
            "n_positives": int(in_df["has_clicks"].sum()),
            "coef_ct": get_coef_ct(model.best_estimator_),
            "n_iter": n_iter,
            "best_params": model.best_params_,
            "best_score": model.best_score_,
        }
        store_meta(meta)
        with open(os.path.join(MODELS_LOC, f"{feed_id}.pkl"), "wb") as f:
            pickle.dump({"model": model, "meta": meta}, f)


def describe_all_models():
    for fn in os.listdir(MODELS_LOC):
        LOG.info(fn)
        with open(os.path.join(MODELS_LOC, fn), "rb") as f:
            model = pickle.load(f)
            for k, v in model["meta"].items():
                LOG.info(f"* {k}: {v}")
        LOG.info("")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        n_iter, n_jobs = 10, 2
        if len(sys.argv) > 3:
            n_iter, n_jobs = int(sys.argv[2]), int(sys.argv[3])
        build_all_models(n_iter, n_jobs)
    else:
        describe_all_models()
