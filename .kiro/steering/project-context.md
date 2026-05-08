---
inclusion: auto
---

# EarningsEdge — Project Context

## What This Is
An AI-powered stock earnings prediction platform for retail investors. It predicts whether stocks will go up or down after reporting quarterly earnings, using XGBoost ML models trained on real market data.

## Live URLs
- Frontend: https://earningsedge-three.vercel.app
- Backend API: https://earningsedge-pnc9.onrender.com
- GitHub: https://github.com/danielbaudy-oss/earningsedge
- Database: Supabase (project: MIKAN, ref: kxbmlsbxnzvgzucxleoy)

## Tech Stack
- **Frontend**: Next.js 14, TypeScript, Tailwind CSS, Recharts
- **Backend**: Python FastAPI
- **ML**: XGBoost (3 models: beat classifier, direction classifier, magnitude regressor)
- **Database**: Supabase PostgreSQL
- **APIs**: Finnhub (earnings/metrics), Polygon (prices/financials), marketdata.app (options IV)
- **Deployment**: Vercel (frontend), Render free tier (backend), UptimeRobot (keep-alive)
- **Alerts**: Telegram bot (@EarningsEdgeBot, chat_id: 1005187450)

## How Predictions Work
1. Fetch stock data: earnings history, analyst revisions, insider transactions, momentum, IV from options
2. XGBoost model predicts: P(beat), P(stock goes up), expected move %
3. Scoring formula (current state 40%, beat prob 20%, direction 20%, fundamentals 10%, risk 10%)
4. Sanity check: if beat prob is low, direction gets capped (no contradictions)
5. Expected move: blends options IV (market-implied) with historical reactions + momentum multiplier
6. Recommendation: BUY (score >= 55, direction > 50%), SELL, or AVOID

## Key Design Decisions
- Expected move uses options straddle price from marketdata.app (100 req/day free plan)
- Price reactions measured using Polygon's `filing_date` (actual earnings report date), NOT fiscal period end
- Short interest amplifies expected moves (squeeze potential)
- Analyst revisions and insider buying feed into the score
- Wikipedia used for company descriptions (free, no rate limit)
- Daily cron via GitHub Actions at 6 AM UTC
- UptimeRobot pings every 5 min to prevent Render cold starts

## Current Model Performance (trained on 2457 samples)
- Beat accuracy: 58.9%
- Direction accuracy: 53.4%
- Move MAE: 2.59%

## Feedback Loop
- Predictions stored in `predictions` table
- After earnings pass: daily job fetches actual EPS + price reaction
- Compares predicted vs actual, stores `prediction_correct`
- Auto-retrains when 20+ outcomes accumulated

## Database Schema (key tables)
- `stocks`: ticker, company_name, description, sector, exchange
- `earnings_events`: stock_id, report_date, eps_estimate, eps_actual, eps_surprise_pct, price_change_pct
- `predictions`: stock_id, earnings_event_id, recommendation, confidence_score, beat_probability, price_up_probability, expected_move_pct, feature_importance
- `alerts`: stock_id, user_email, telegram_chat_id, days_before

## API Keys (in backend/.env)
- POLYGON_API_KEY (paid Starter plan — no rate limit)
- FINNHUB_API_KEY
- NEWS_API_KEY
- MARKETDATA_API_KEY (options IV, 100 req/day free after trial)
- SUPABASE_SERVICE_KEY
- TELEGRAM_BOT_TOKEN

## What's Running
- Daily job: syncs calendar, updates outcomes, backfills price data, retrains if needed, batch analyzes
- UptimeRobot: keeps Render awake 24/7
- GitHub Actions: triggers daily job at 6 AM UTC

## Known Issues / Next Steps
- Direction accuracy is only 53% — needs more data and features to improve
- Some small stocks don't have options IV data (marketdata.app doesn't cover them)
- Polygon paid plan active — remember to downgrade after bulk data collection is done
- Sector feature not yet added to XGBoost training (planned)
- News sentiment not yet integrated (Phase 3)
