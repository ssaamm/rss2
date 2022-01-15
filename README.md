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

# TODO list

- [ ] Add ability for users to name/describe feed
