# PriceScope

E-commerce price intelligence platform. This repository currently contains the project skeleton, MongoDB data model, offline-tested scraping layer, and a MongoDB-backed health check; UI features are not implemented yet.

## Stack

- **Backend:** Python 3.11, Flask, MongoDB (pymongo), Firebase Authentication, BeautifulSoup, APScheduler
- **Frontend:** React with Vite
- **Tests:** pytest

## Repository layout

```text
PriceScope/
├── backend/
│   ├── app/
│   │   ├── __init__.py    # Flask app factory
│   │   ├── config.py      # Environment-based configuration
│   │   ├── db.py          # MongoDB client, database access, and ping
│   │   ├── models/        # Dataclasses, validation, and index setup
│   │   ├── routes/        # HTTP blueprints (health check for now)
│   │   ├── scrapers/      # Fetch policy, store parsers, and URL registry
│   │   ├── services/      # Business logic and authentication services (planned)
│   │   └── jobs/          # APScheduler scrape job and scheduler setup
│   ├── tests/             # pytest suite
│   ├── requirements.txt
│   ├── pytest.ini
│   └── .env.example
├── frontend/
│   ├── src/               # React application entry point
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
└── README.md
```

- **`app/models/`** defines BSON-safe dataclasses, validation helpers, enums, and MongoDB indexes.
- **`app/routes/`** exposes API endpoints as Flask blueprints.
- **`app/scrapers/`** contains the shared fetch policy, per-retailer parsers, and the URL-to-scraper registry.
- **`app/services/`** will hold reusable business logic such as authentication, price comparisons, and alerts.
- **`app/jobs/`** defines the APScheduler scrape job that periodically refreshes watched products.
- **`tests/`** contains backend tests, using an isolated test configuration.
- **`frontend/`** is the Vite + React client and currently only renders a placeholder page.

## Backend setup

Requires Python 3.11+ and a running MongoDB instance.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app app init-db
flask --app app run --debug
```

The API runs at `http://localhost:5000`. `init-db` is safe to run repeatedly.

### Data model

| Collection | Purpose | Indexes |
| --- | --- | --- |
| `products` | Current product metadata and latest price | Unique `url` |
| `price_history` | One document per price observation | `(product_id, scraped_at DESC)` |
| `watches` | User price watches and alert preferences | Unique `(user_id, product_id)` |
| `alerts` | Triggered price alerts and email status | None yet |
| `job_runs` | One summary per scrape run (counts, duration) | None yet |

Prices are stored as MongoDB `Decimal128` to avoid floating-point rounding errors. Datetimes are timezone-aware UTC. The Python models are plain frozen dataclasses with validation and BSON serialization helpers; there is no ORM.

`price_history` is a separate collection rather than an array on `products` because observations grow without bound, would eventually hit MongoDB's document size limit, and would make product updates increasingly expensive. A separate collection also allows efficient indexed queries for 30-day lows, retention policies, and aggregate price analytics without loading full product documents.

### Scraping

`BaseScraper.fetch()` uses a realistic browser User-Agent, a request timeout, retries with exponential backoff, a random 1–3 second gap between requests, and `robots.txt` checks. Flipkart and Myntra parsers read schema.org `application/ld+json` product data. Croma reads its JSON-LD offer and falls back to visible stock markers because its structured data omits availability.

Raw `curl` requests to Croma initially returned an Akamai `403`; the browser-like `requests.Session` User-Agent configured in `BaseScraper` was accepted. No proxy or captcha bypass is used. If a store starts blocking requests, `fetch()` raises `ScraperBlockedError`; the legal fallbacks are manually saved pages or replacing that store with a scraper-friendly retailer.

Scraper tests load saved fixtures from `backend/tests/fixtures/` and never access the internet. Fixture sources and retrieval details are documented in that directory.

### Scheduled scraping

Every `SCRAPE_INTERVAL_HOURS` (default 6) a background job refreshes every product that has at least one watch, using up to 3 worker threads and a 2-second gap between requests to the same store. One failing product never stops the run. Each run is logged and stored in `job_runs`. Run it manually with `flask --app app scrape-now`.

The scheduler is off unless `SCHEDULER_ENABLED=true`. It starts at most once per host: it is skipped in the Flask reloader's parent process, and a non-blocking file lock (`SCHEDULER_LOCK_PATH`) lets only one process (for example one gunicorn worker) own it. For several hosts, enable it on a single one.

### Health check

```http
GET /api/health
```

Successful response (`200`):

```json
{
  "status": "ok",
  "database": "ok"
}
```

If MongoDB cannot be reached, the endpoint returns `503`:

```json
{
  "status": "error",
  "database": "unavailable"
}
```

### Tests

```bash
cd backend
pytest
```

The tests mock the MongoDB ping, use `mongomock` for index tests, and parse saved HTML fixtures, so they do not require a running database or network access.

## Frontend setup

Requires Node.js 18+.

```bash
cd frontend
npm install
npm run dev
```

The Vite development server runs at `http://localhost:5173` and proxies `/api` requests to the Flask backend.

## Environment variables

See `backend/.env.example`. The key settings are:

| Variable | Purpose | Default |
| --- | --- | --- |
| `MONGO_URI` | MongoDB connection string | `mongodb://localhost:27017/` |
| `MONGO_DB_NAME` | Database name | `pricescope` |
| `MONGO_SERVER_SELECTION_TIMEOUT_MS` | MongoDB connection timeout | `2000` |
| `SECRET_KEY` | Flask secret key | Development placeholder |
| `FIREBASE_CREDENTIALS_PATH` | Path to Firebase service account JSON | Empty |
| `SCHEDULER_ENABLED` | Start the background scraper in the server process | `false` |
| `SCRAPE_INTERVAL_HOURS` | Hours between scheduled scrape runs | `6` |

Never commit the real `.env` or Firebase credentials.
