from typing import Union, List
from pydantic import BaseModel


class FeedNotFound(Exception):
    """Unable to find feed"""


class FeedResponse(BaseModel):
    url: str


class BaseCreateFeedRequest(BaseModel):
    type: str


class CreateCombinedFeedRequest(BaseModel):
    type = "combine"
    sources: List[str]
    title: str = "A combined feed"
    description: str = "A combination of feeds"


class CreateFilteredFeedRequest(BaseModel):
    type = "filter"
    source: str
    require_in_title: List[str] = []
    disallow_in_title: List[str] = []


CreateFeedRequest = Union[CreateCombinedFeedRequest, CreateFilteredFeedRequest]
