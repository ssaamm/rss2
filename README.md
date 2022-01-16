# rss2

Tools for improving RSS feeds

## Resources

- [Architecture and plan](https://excalidraw.com/#json=fXAL5ssGidt8wckQMBM92,PsjtEn5L0fWutRw23Crdgg)

## Setup

```sh
python3 -m venv env
. env/bin/activate
pip install -r requirements.txt
cd src
python -m rsstool.initdb
```

## Running locally

```sh
cd src
RSS_USERNAME=unsafe RSS_PASSWORD=unsafe uvicorn rsstool.main:app --reload
```

## Running in Docker

```sh
docker build -t ssaamm/rss2 .
docker run -ti \
  -v "$(pwd)":/external \
  -e DB_LOC='/external/rss.db' \
  -e RSS_USERNAME='unsafe' \
  -e RSS_PASSWORD='unsafe' \
  -p 5001:5000 \
  ssaamm/rss2
```

## Sample requests

### Combined feed

```json
{
    "sources": [
        "https://onemileatatime.com/feed/",
        "https://frequentmiler.com/feed/",
        "https://milestomemories.com/feed/",
        "http://reddit.project.samueltaylor.org/sub/awardtravel?limit=10"
    ],
    "type": "combine"
}
```

### Filtered feed

```json
{
    "type": "filter",
    "source": "https://feeds.feedburner.com/HighScalability?format=xml",
    "disallow_in_title": ["Post: "]
}
```

# TODO list

- [x] Add ability for users to name/describe feed
- [ ] Pre-commit hooks -- formatting, isort
- [ ] lol write tests
- [ ] Update `last_accessed` when feed is accessed
- [ ] Allow deleting feeds
- [x] Put some kind of auth in front of feed creation/deletion
- [ ] Make sure podcast images come through
- [ ] Some abstraction around 'source'
- [ ] "Created date" on Feed object
