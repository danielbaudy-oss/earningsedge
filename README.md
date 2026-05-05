# EarningsEdge - AI-Powered Stock Earnings Prediction Platform

A full-stack platform that predicts stock movements around earnings events, providing retail investors with simple "Buy / Sell / Avoid" recommendations before earnings announcements.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                         │
│  Stock Search │ Earnings Calendar │ Predictions │ Alerts │ Why?  │
└─────────────────────────┬───────────────────────────────────────┘
                          │ REST API
┌─────────────────────────▼───────────────────────────────────────┐
│                    Backend (FastAPI)                              │
│  /stocks │ /earnings │ /predictions │ /alerts │ /explanations    │
└──┬──────────┬──────────┬──────────────┬─────────────────────────┘
   │          │          │              │
   ▼          ▼          ▼              ▼
┌──────┐ ┌────────┐ ┌────────┐  ┌─────────────┐
│ Data │ │   ML   │ │ Alert  │  │  Scheduler  │
│Ingest│ │Pipeline│ │Service │  │  (Daily)    │
└──┬───┘ └───┬────┘ └───┬────┘  └──────┬──────┘
   │         │          │              │
   ▼         ▼          ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PostgreSQL Database                           │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

- **Frontend**: Next.js 14, TypeScript, Tailwind CSS, shadcn/ui
- **Backend**: Python FastAPI, SQLAlchemy, Alembic
- **ML**: XGBoost, scikit-learn, SHAP (explanations)
- **Database**: PostgreSQL
- **Task Queue**: Celery + Redis
- **APIs**: Polygon, Finnhub, SEC Edgar, News API, Reddit API

## Quick Start

### Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env  # Fill in API keys
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

### ML Pipeline
```bash
cd backend
python -m app.ml.train  # Initial model training
```

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes
│   │   ├── core/         # Config, security
│   │   ├── db/           # Database models, migrations
│   │   ├── ingestion/    # Data pipeline (APIs)
│   │   ├── ml/           # ML model training & inference
│   │   ├── services/     # Business logic
│   │   └── main.py
│   ├── alembic/          # DB migrations
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/          # Next.js app router
│   │   ├── components/   # UI components
│   │   ├── lib/          # API client, utils
│   │   └── types/        # TypeScript types
│   └── package.json
└── README.md
```
