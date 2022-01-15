from typing import Union, List

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class FeedResponse(BaseModel):
    url: str


class BaseCreateFeedRequest(BaseModel):
    type: str


class CreateCombinedFeedRequest(BaseModel):
    type = "combine"
    sources: List[str]


class CreateFilteredFeedRequest(BaseModel):
    type = "filter"
    require_in_title: List[str]
    disallow_in_title: List[str]


CreateFeedRequest = Union[CreateCombinedFeedRequest, CreateFilteredFeedRequest]


def validate_feed_request(r):
    if isinstance(r, CreateFilteredFeedRequest) and r.type != "filter":
        raise ValueError("type should be filter")
    if isinstance(r, CreateCombinedFeedRequest) and r.type != "combine":
        raise ValueError("type should be combine")
    elif not isinstance(r, (CreateFilteredFeedRequest, CreateCombinedFeedRequest)):
        raise ValueError("unknown type")


@app.post("/api/v1/feed", response_model=FeedResponse)
async def create_feed(request: CreateFeedRequest):
    validate_feed_request(request)
    return FeedResponse(url="http://example.com/")
