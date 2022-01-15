from fastapi import FastAPI, HTTPException
from models import FeedResponse, CreateFeedRequest, FeedNotFound
from helper import handle_create_feed_request, render_feed

app = FastAPI()


# TODO require some auth here
@app.post("/api/v1/feed", response_model=FeedResponse)
async def create_feed(request: CreateFeedRequest):
    return await handle_create_feed_request(request)


@app.get("/api/v1/feed/{feed_id}")
async def get_feed(feed_id):
    try:
        return await render_feed(feed_id)
    except FeedNotFound:
        raise HTTPException(status_code=404, detail="Feed not found")
