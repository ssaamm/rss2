from urllib.parse import urlparse

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import MultiLabelBinarizer


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
