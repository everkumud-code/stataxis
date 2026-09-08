# STAXIS database

The initial schema is created by `collector.storage.create_database()` using SQLAlchemy. The observation table is append-only by design: each collection pass creates a new timestamped row rather than overwriting prior measurements.

Production will use PostgreSQL. Local development may use SQLite by setting `DATABASE_URL=sqlite:///stataxis.db`.
