# STAXIS

## Digital Media Intelligence

STAXIS is an independent digital audience measurement and intelligence platform focused initially on Indian news and media channels.

### Initial objective

Build a reliable measurement pipeline:

`Source APIs → STX Collector → Raw Observations → Normalizer → Time Series → Metrics → Rankings → Intelligence`

The first milestone is **M001 — Collector is Alive**:

- Maintain a registered channel universe.
- Discover recent uploads and active broadcasts without relying on third-party ranking providers.
- Collect permitted public YouTube metrics with timestamps.
- Persist observations without overwriting historical measurements.
- Log collection runs and failures.
- Make the collector restart-safe and testable.

### Repository layout

```text
collector/      Data-source collection code
config/         Channel/source configuration
 database/      Database models and migrations
metrics/        Derived measurement logic
tests/          Automated tests
docs/           Architecture and methodology
```

### Data-source principle

STAXIS does not depend on Ratingology, Data Beings, or another measurement provider as its primary data source. The platform is designed around direct collection from legitimate upstream sources and a source-adapter architecture so additional sources can be added later.

### Compliance

Collection, storage, retention, and derived metrics must follow the applicable source/API terms and policies. Secrets belong in environment variables or deployment secrets and must never be committed to Git.

## Development

Python 3.12+ is the initial implementation target.

See `.env.example` for required environment variables.
