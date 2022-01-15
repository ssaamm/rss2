from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from rsstool.models import FeedResponse, CreateFeedRequest, FeedNotFound
from rsstool.helper import handle_create_feed_request, render_feed
from rsstool.constants import USERNAME, PASSWORD

app = FastAPI()
security = HTTPBasic()


@app.post("/api/v1/feed", response_model=FeedResponse)
async def create_feed(request: CreateFeedRequest, credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != USERNAME or credentials.password != PASSWORD:  # TODO compare_digest
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    return await handle_create_feed_request(request)


@app.get("/api/v1/feed/{feed_id}")
async def get_feed(feed_id):
    try:
        return await render_feed(feed_id)
    except FeedNotFound:
        raise HTTPException(status_code=404, detail="Feed not found")
