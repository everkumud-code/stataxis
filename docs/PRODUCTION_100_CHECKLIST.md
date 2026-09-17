# StatAxis Production 100 Checklist

This checklist defines the remaining work from the current 95% product-maturity baseline to a defensible production-complete milestone. It deliberately separates platform readiness from future intelligence modules.

## Completed baseline

- Core digital-media intelligence architecture
- Timestamped observations and provenance
- Channel, stream, video and market intelligence
- STX Index v1 methodology and confidence/evidence semantics
- STAX9 product experience
- Production API hardening for channel-series windows
- Scalable monitoring-universe architecture
- Production deployment and launch surfaces

## 95 → 100 finish gate

### 1. Monitoring universe
- [ ] Load the approved initial 30-channel registry: 10 Hindi, 10 English, 10 International.
- [ ] Verify every channel has a real YouTube channel ID, language, region and active state.
- [ ] Confirm no duplicate channel IDs.
- [ ] Confirm collector logs configured, persisted-active and total targets.
- [ ] Confirm adding a channel does not require application-code changes.

### 2. Taxonomy
- [ ] Keep language, market and region independent.
- [ ] Populate UI filters dynamically from active catalog data rather than hard-coded language lists.
- [ ] Allow additional languages and channels without schema redesign.
- [ ] Define stable display labels while retaining source values.

### 3. Data integrity
- [ ] Preserve raw timestamped observations.
- [ ] Never zero-fill missing measurements.
- [ ] Verify staggered channel observations are handled using each channel's latest observation.
- [ ] Verify STX provenance, observation counts and confidence are exposed.
- [ ] Verify primary-stream vs all-stream calculations remain distinct.

### 4. Collector operations
- [ ] Validate YouTube credentials and quota before sustained collection.
- [ ] Verify per-channel error isolation.
- [ ] Verify CollectionRun status for success, partial and failed runs.
- [ ] Verify graceful worker shutdown and restart behavior.
- [ ] Verify collection interval and maximum-video controls are environment-driven.

### 5. API/frontend contract
- [ ] Verify all dashboard API calls against production response shapes.
- [ ] Verify empty-data states do not render invented values.
- [ ] Verify confidence and evidence are visible wherever intelligence is presented.
- [ ] Verify compare limits are UI limits, not monitoring-universe limits.
- [ ] Verify export/report endpoints preserve provenance.

### 6. Intelligence completion gate
- [ ] Ship a first-class “What Changed?” surface using only observed evidence.
- [ ] Explain STX movement through component contributions and evidence.
- [ ] Keep sentiment and narrative intelligence as separate versioned modules; do not silently fold them into STX v1.
- [ ] Version any future STX methodology change as STX v2 after validation.

### 7. Security and operational readiness
- [ ] Confirm secrets are environment-only and never committed.
- [ ] Confirm admin bootstrap credentials are not exposed in client assets.
- [ ] Confirm authentication/approval boundaries on live data.
- [ ] Confirm production error logs and health checks are usable.
- [ ] Confirm CI runs `ruff check .` and `pytest -q` on pushes and pull requests.

## Definition of 100%

StatAxis reaches the 100% milestone when the agreed current product scope is implemented, the approved 30-channel launch universe is onboarded and verified, production data integrity and operational gates pass, and the dashboard/API contracts are verified end-to-end. Future capabilities such as sentiment, narrative intelligence, alerts and enterprise controls remain versioned roadmap modules rather than hidden inside the percentage.
