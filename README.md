# PriceScope

E-commerce price intelligence platform. This repository currently contains the project skeleton and a MongoDB-backed health check; product features are not implemented yet.

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
│   │   ├── routes/        # HTTP blueprints (health check for now)
│   │   ├── scrapers/      # Retailer scraping modules (planned)
│   │   ├── services/      # Business logic and authentication services (planned)
│   │   └── jobs/          # APScheduler jobs and schedules (planned)
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

- **`app/routes/`** exposes API endpoints as Flask blueprints.
- **`app/scrapers/`** will contain one module per retailer, responsible for fetching and parsing product pages.
- **`app/services/`** will hold reusable business logic such as authentication, price comparisons, and alerts.
- **`app/jobs/`** will define scheduled APScheduler tasks, such as recurring price refreshes.
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
flask --app app run --debug
```

The API runs at `http://localhost:5000`.

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

The tests mock the MongoDB ping, so they do not require a running database.

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

Never commit the real `.env` or Firebase credentials.
