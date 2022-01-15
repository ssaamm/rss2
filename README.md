# rss2

Tools for improving RSS feeds

## Resources

- [Architecture and plan](https://excalidraw.com/#json=fXAL5ssGidt8wckQMBM92,PsjtEn5L0fWutRw23Crdgg)

## Setup

```sh
python3 -m venv env
. env/bin/activate
pip install -r requirements.txt
cd src/rsstool
python initdb.py
```

## Running locally

```sh
uvicorn main:app --reload
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

- [ ] Add ability for users to name/describe feed
- [ ] Pre-commit hooks -- formatting, isort
- [ ] lol write tests
- [ ] Update `last_accessed` when feed is accessed
- [ ] Allow deleting feeds
- [ ] Put some kind of auth in front of feed creation/deletion
