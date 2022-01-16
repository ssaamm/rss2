from enum import Enum
from typing import Union, List
from pydantic import BaseModel


class FeedNotFound(Exception):
    """Unable to find feed"""


class FeedResponse(BaseModel):
    url: str


class BaseCreateFeedRequest(BaseModel):
    type: str


class CreateCombinedFeedRequest(BaseCreateFeedRequest):
    type = "combine"
    sources: List[str]
    title: str = "A combined feed"
    description: str = "A combination of feeds"


class CreateFilteredFeedRequest(BaseCreateFeedRequest):
    type = "filter"
    source: str
    require_in_title: List[str] = []
    disallow_in_title: List[str] = []


class CadenceEnum(str, Enum):
    hourly = "hourly"
    weekly = "weekly"
    daily = "daily"


class CreateDigestFeedRequest(BaseCreateFeedRequest):
    type = "digest"
    source: str
    cadence: CadenceEnum
    start_timestamp: float


CreateFeedRequest = Union[CreateCombinedFeedRequest, CreateDigestFeedRequest, CreateFilteredFeedRequest]
