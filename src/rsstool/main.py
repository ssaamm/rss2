from fastapi import Depends, FastAPI, HTTPException, status, Response, BackgroundTasks
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import RedirectResponse

from rsstool.models import FeedResponse, CreateFeedRequest, FeedNotFound
import rsstool.helper as helper
import rsstool.db_helper as db
from rsstool.constants import USERNAME, PASSWORD

app = FastAPI()
security = HTTPBasic()


@app.post("/api/v1/feed", response_model=FeedResponse, status_code=status.HTTP_201_CREATED)
async def create_feed(
    request: CreateFeedRequest, bg: BackgroundTasks, credentials: HTTPBasicCredentials = Depends(security)
):
    if credentials.username != USERNAME or credentials.password != PASSWORD:  # TODO compare_digest
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    return await helper.handle_create_feed_request(request, bg)


@app.get("/api/v1/feed/{feed_id}")
async def get_feed(feed_id, bg: BackgroundTasks):
    try:
        rendered_feed = await helper.render_feed(feed_id, bg)
        return Response(content=rendered_feed, media_type="application/xml")
    except FeedNotFound:
        raise HTTPException(status_code=404, detail="Feed not found")


@app.get("/api/v1/feed/{feed_id}/item/{item_id}", response_class=RedirectResponse)
async def get_feed_item(feed_id, item_id):
    return await db.record_click_and_get_link(feed_id, item_id)
