# Technology Stack

## Core Language & Runtime
- **Python (>=3.12):** Leveraging modern async features and type hinting.

## Data Management
- **SQLModel:** ORM for database interactions, combining SQLAlchemy and Pydantic.
- **PostgreSQL:** Primary relational database (accessed via `asyncpg` for async and `psycopg2-binary`).
- **Redis:** Used for messaging, heartbeats, and caching.

## Intelligence & Analysis
- **Google Gemini (google-genai):** Integrated for market analysis, news sentiment, and decision support.
- **pandas & pandas-ta:** For data manipulation and technical analysis indicator calculations.

## Frontend & Visualization
- **Reflex:** Full-stack framework for building the trading dashboard in pure Python.
- **Plotly & Matplotlib:** For financial charting and data visualization.

## Infrastructure & Utilities
- **HTTPX:** Async HTTP client for API interactions (IG, News services).
- **APScheduler:** For managing scheduled tasks and background jobs.
- **Loguru:** For structured and customizable logging.
- **Tenacity:** For robust retrying of transient failures.
- **Pydantic Settings:** For type-safe configuration management.

## Quality Assurance
- **Pytest & Pytest-Asyncio:** Primary testing frameworks.
- **Coverage.py:** For monitoring test code coverage.
- **Ruff:** For fast linting and code formatting.
