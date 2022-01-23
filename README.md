# rss2

Tools for improving RSS feeds

## Resources

- [Architecture and plan](https://excalidraw.com/#json=4oijGCFBDymhHR0P8rdOX,56XpSQsakM0TOo4LkOeIdA)

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

## Useful queries

Most recently accessed feeds
```sql
select datetime(last_accessed, 'unixepoch', 'localtime') as last_access_local
  , *
  from feed
  order by 1 desc
  limit 100
```

# TODO list

- [x] Add ability for users to name/describe feed
- [x] Put some kind of auth in front of feed creation/deletion
- [x] Update `last_accessed` when feed is accessed
- [x] "Created date" on Feed object
- [ ] Make sure podcast images come through
- [ ] Some abstraction around 'source'
- [ ] Allow deleting feeds
- [ ] Pre-commit hooks -- formatting, isort
- [ ] lol write tests

## ML sorting

- Feed digest config: add attrs `user_sort_preference`, `model_available`
  (bool)
- `feed_item`: add col "score"
- Scheduled job: (in container)
  - For each feed w/ at least 30 items
  - Do this CV thing
  - If AU-ROC >= 0.7, set `model_available=True`
  - Pickle models to resources dir (name: <feed_id>.pkl)
  - Write to a table `train_job`
    - (`feed_id`, `git_sha`, `train_start`, `train_duration`, `n_rows`,
      `n_positives`, `nonzero_coef_ct`, `best_params`, `best_score`)
- Update the indexing job
  - For each item, if `model_available`, attempt to load model, then score it
    (write to score col)
  - Also write to a `feed_item_score` table
    - (`item_id`, `score`, `time_scored`)
