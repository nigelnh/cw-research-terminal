# MASTER TECHNICAL & QUANTITATIVE AUDIT — TRADING RESEARCH PLATFORM

Act as a **Principal Software Engineer, Quantitative Developer, Data Platform Engineer, and Security/Infrastructure Reviewer** performing a production-readiness audit of this repository.

This is not a superficial code review.

The project is intended to become a **portfolio-quality trading research and backtesting platform** that I can deploy publicly and attach to my software engineering resume. It contains or may contain financial calculations, historical/realtime market-data pipelines, Black-Scholes pricing, implied volatility, Greeks, PnL-related calculations, APIs, frontend state, and supporting infrastructure.

My immediate development priorities after this audit are:

1. Correctness of the overall system design.
2. Correctness of all financial/quantitative calculations.
3. Correctness and efficiency of the data pipeline.
4. PostgreSQL persistence for historical FiinQuant data so repeated API calls are minimized.
5. Authentication.
6. Frontend/server state management.
7. A low-cost deployment architecture suitable for a public resume project.
8. Identification of unnecessary complexity or overengineering.
9. Identification of missing production-quality engineering practices.
10. A concrete implementation roadmap.

## CRITICAL RULE: AUDIT BEFORE MODIFYING

Do NOT modify application source code during the audit.

You may create audit documents under:

`audit/claude/`

but do not modify existing application files unless I explicitly approve implementation later.

Before anything else:

* run `git status`
* inspect repository structure
* inspect package manifests
* inspect Python dependencies
* inspect Docker files / Compose files
* inspect database code and migrations
* inspect environment-variable usage
* inspect API routes
* inspect services
* inspect tests
* inspect CI/CD configuration
* inspect README/docs
* inspect all financial calculation modules
* inspect market-data ingestion paths
* inspect frontend data-fetching/state patterns

Do not assume the architecture described in README files is correct.

**The code is the source of truth.**

Do not expose `.env` values, API keys, passwords, database credentials, FiinQuant credentials, private endpoints, or secrets in your reports.

Do NOT make unnecessary live calls to FiinQuant or other rate-limited APIs during the audit.

Prefer reading the integration code, mocks, fixtures, documentation, and existing responses.

Do not execute remote database migrations or destructive operations.

---

# AUDIT ORGANIZATION

If subagents are available, use separate subagents with independent context windows.

Create at minimum these auditors:

### 1. System Architecture Auditor

Responsible for:

* service boundaries
* frontend/backend responsibilities
* API design
* BFF architecture
* synchronous vs asynchronous communication
* websocket architecture
* event-driven architecture
* Kafka usage
* Redis usage
* PostgreSQL usage
* FastAPI responsibilities
* Node/TypeScript service responsibilities
* Next.js responsibilities
* n8n responsibilities
* deployment topology
* observability
* reliability
* concurrency
* scalability
* failure modes

### 2. Quantitative Finance Auditor

Responsible for every financial formula and financial assumption, including:

* Black-Scholes
* implied volatility
* Delta
* Gamma
* Vega
* Theta
* Rho if implemented
* historical volatility
* moneyness
* spreads
* theoretical price
* warrant / covered-warrant conversion ratios
* PnL
* hedge PnL
* realized/unrealized PnL
* Greeks-based PnL attribution
* corporate-action adjustments
* time-to-maturity
* annualization conventions
* risk-free rate
* dividends / dividend yield
* price and quantity units

This auditor must independently derive expected formulas rather than trusting comments or function names.

### 3. Market Data & Data Platform Auditor

Responsible for:

* FiinQuant integration
* historical data
* realtime data
* API call usage
* caching
* deduplication
* database persistence
* backfills
* incremental ingestion
* retries
* idempotency
* timestamp handling
* trading calendars
* adjusted/unadjusted prices
* source consistency
* stale data
* missing data
* gaps
* rate limits
* data lineage

### 4. Frontend / State / Authentication Auditor

Responsible for:

* React/Next.js architecture
* client vs server components
* server state
* client state
* duplicated state
* data fetching
* caching
* loading/error states
* session handling
* authentication
* authorization
* route protection
* user-specific data
* frontend performance
* unnecessary global state

### 5. Security & Deployment Auditor

Responsible for:

* secret handling
* credential exposure
* CORS
* input validation
* API authorization
* SQL injection risk
* dependency/security issues
* rate limiting
* attack surface
* production environment configuration
* public deployment options
* cost
* operational complexity

Assume I want the public demo to cost approximately **$0–$5/month if realistically possible**.

Do not assume AWS is required.

Evaluate architectures involving services such as Vercel, Supabase, Neon, Railway, Render or equivalent where appropriate.

Distinguish between:

**FULL ENGINEERING ARCHITECTURE**

and

**LEAN PUBLIC DEMO ARCHITECTURE**

I do NOT need to keep every distributed systems component running 24/7 merely to impress recruiters.

### 6. Adversarial Verification Auditor

This agent should NOT design the system.

Its job is to challenge the conclusions produced by the other auditors.

Attempt to falsify findings.

Specifically look for:

* calculations that appear correct but have wrong units
* incorrect assumptions hidden behind correct formulas
* race conditions
* stale-data problems
* timestamp alignment problems
* duplicated calculations
* frontend/backend semantic mismatches
* incorrect scaling
* hidden failure cases
* unnecessary services
* false-positive audit findings

Do not trust another agent merely because it sounds confident.

---

# PART I — RECONSTRUCT THE ACTUAL SYSTEM

Build a complete current-state architecture from the repository.

Trace:

`external source -> ingestion -> processing -> persistence/cache -> API -> frontend`

for every major data flow you find.

Produce Mermaid diagrams.

For each service/module explain:

* responsibility
* inputs
* outputs
* state owned
* dependencies
* callers
* failure behavior
* whether it is actually necessary

For each significant infrastructure component ask:

> What concrete requirement does this component solve?

For example, if Kafka exists, determine whether the project actually requires:

* replay
* durable event log
* consumer groups
* multiple independent consumers
* backpressure
* event ordering
* decoupled producers/consumers

If none of those requirements exist, flag potential infrastructure overengineering.

Perform the same challenge for Redis, separate Node services, FastAPI services, Next.js BFF routes, n8n, and any other service.

If Kafka still uses ZooKeeper, identify whether this is legacy architecture and evaluate migration to current Kafka/KRaft architecture.

Do NOT recommend removing a technology merely to reduce the number of technologies.

Recommend simplification only when it improves engineering quality.

---

# PART II — FINANCIAL MODEL AUDIT

This section requires extreme rigor.

Find every location where financial calculations occur.

Create a table containing:

* formula/concept
* source file
* function/class
* inputs
* input units
* output
* output units
* expected financial definition
* implementation behavior
* verdict
* severity
* recommended verification test

## Black-Scholes

Verify the implementation independently.

Check the definitions of:

S = underlying price
K = strike/exercise price
r = annualized risk-free rate
q = dividend yield if applicable
sigma = annualized volatility
T = time to expiration in years

Verify:

d1
d2
option theoretical price
discounting
normal CDF/PDF usage

Do not stop at the mathematical formula.

Trace the origin of every parameter.

For example:

Where does S come from?

Is it:

* last trade
* bid
* ask
* midpoint
* official close
* stale cached value?

Where does K come from?

Is there any exercise ratio or warrant conversion ratio applied?

How is T calculated?

Check:

* calendar days vs trading days
* 365 vs 252
* timezone
* expiration timestamp
* intraday expiry behavior
* negative T
* zero T

Check r:

* decimal vs percent
* fixed configuration vs market source
* consistency across modules

Check q/dividends.

For covered warrants, determine whether standard Black-Scholes is being transformed correctly for instrument-specific:

* exercise ratio
* multiplier
* settlement terms
* price units
* underlying units

Do not assume standard equity-option semantics automatically apply.

---

# PART III — IMPLIED VOLATILITY

If Newton-Raphson or another iterative solver is used, audit:

* initial guess
* convergence tolerance
* maximum iterations
* derivative used
* Vega scaling
* zero/near-zero Vega
* non-convergence
* negative volatility
* absurdly high volatility
* deep ITM
* deep OTM
* very short maturity
* invalid market prices
* arbitrage bounds
* stale prices
* bid/ask spread
* last vs mid vs bid vs ask

Determine whether the solver needs:

* bisection fallback
* Brent-style fallback
* bounded search
* explicit failure states

Construct test vectors where:

`known sigma -> Black-Scholes price -> IV solver -> recovered sigma`

and verify that the recovered volatility matches the original within an explicitly justified numerical tolerance.

---

# PART IV — GREEKS

Audit every Greek mathematically and semantically.

For each Greek determine whether its scale matches what the UI/API claims.

### Vega

Explicitly determine whether Vega represents:

change for:

`Δsigma = 1.0`

or:

`Δsigma = 0.01`

This is a potential factor-of-100 error.

### Theta

Determine whether Theta is:

* annual
* daily using /365
* trading-day using /252
* something else

Verify the frontend label matches backend semantics.

### Delta

Check:

* call/put convention
* ratio/multiplier scaling
* position-size scaling
* long/short sign

### Gamma

Check units carefully.

Validate analytic Greeks with finite-difference approximations.

For example:

Delta ≈ central difference of price with respect to S.

Gamma ≈ second finite difference with respect to S.

Vega ≈ finite difference with respect to sigma.

Theta ≈ finite difference with respect to T/time.

Report discrepancies.

---

# PART V — PNL

Find every PnL calculation.

Determine exactly how the system defines:

* instrument PnL
* realized PnL
* unrealized PnL
* hedge PnL
* portfolio PnL
* Delta PnL
* Gamma PnL
* Vega PnL
* Theta PnL
* residual/unexplained PnL

Check:

* position quantity
* instrument ratio
* multiplier
* underlying quantity
* long/short sign
* entry price
* mark price
* transaction costs
* price units
* VND scaling
* intraday reset rules
* timestamp alignment

If Greek attribution exists, examine whether it approximates:

ΔV ≈ Delta·ΔS
+ 0.5·Gamma·(ΔS)^2
+ Vega·Δsigma
+ Theta·Δt

Determine the units expected by every term.

Explain possible sources of residual PnL.

---

# PART VI — PROPERTY-BASED AND NUMERICAL TESTING

Do not rely only on manually selected examples.

Design invariants.

Examples include, when mathematically appropriate:

* call price should be nondecreasing in S
* option price should generally increase with sigma
* Gamma should be nonnegative for vanilla European options
* Vega should be nonnegative
* call Delta should normally remain in [0, 1]
* recovered IV should reproduce the market price
* no-arbitrage pricing bounds must hold

Identify cases where instrument-specific covered-warrant mechanics alter standard assumptions.

Generate a proposed quantitative test suite.

Separate tests into:

* known-value tests
* finite-difference tests
* property/invariant tests
* edge-case tests
* regression tests
* production-data sanity checks

An LLM opinion is NOT sufficient evidence that a formula is correct.

Whenever possible require objective numerical verification.

---

# PART VII — FIINQUANT HISTORICAL DATA + POSTGRESQL DESIGN

The project needs approximately a **2-year historical data window**, subject to the user's FiinQuant subscription/data entitlement.

The goal is to avoid wasting FiinQuant API calls.

Audit the current FiinQuant integration first.

Determine:

* available tickers/universe
* fields requested
* intervals/timeframes
* historical depth required
* current request pattern
* where duplicate calls happen
* whether calls occur per page request
* whether multiple requests can trigger the same upstream fetch
* whether there is already caching

Design a PostgreSQL-backed historical cache.

The desired conceptual flow is:

FIINQUANT
↓
controlled ingestion
↓
POSTGRESQL
↓
application APIs
↓
frontend

The normal frontend request should NOT trigger a complete upstream historical fetch.

Design:

### Initial backfill

One-time controlled ingestion of the required historical window.

Make it:

* resumable
* chunked
* idempotent
* observable
* safe to restart

### Incremental update

After the backfill, fetch only data newer than the latest confirmed stored timestamp, while also providing a strategy for correcting missing bars or revised data.

### Gap filling

If the DB lacks part of a requested range, determine whether the system should:

* return incomplete data
* enqueue a gap-fill
* synchronously retrieve the gap
* or use another policy

Choose explicitly.

Prevent concurrent users from independently causing duplicate upstream requests for the same missing range.

### Database design

Evaluate a schema similar conceptually to:

`instruments`

`market_bars`

`ingestion_runs`

`ingestion_state`

but do NOT blindly implement these names if a better model fits the existing repository.

For market bars evaluate fields such as:

* instrument
* timestamp
* timeframe
* open
* high
* low
* close
* volume
* adjusted/unadjusted
* source
* ingestion timestamp

Determine correct unique constraints.

Potential logical identity might resemble:

`(instrument_id, timeframe, timestamp, adjusted, source)`

but derive the actual correct key.

Evaluate:

* indexes
* query patterns
* upserts
* batch inserts
* connection pooling
* migrations
* retention
* data corrections
* timezone normalization

Estimate expected row count and approximate storage BEFORE recommending hosting.

Specifically estimate separately for:

* daily bars
* 1-hour bars if applicable
* 5-minute bars if applicable
* 1-minute bars if applicable

for the actual instrument universe.

Do not assume that a free 500 MB PostgreSQL tier will fit millions of minute bars.

If storing minute-level history in PostgreSQL becomes economically or architecturally inefficient, explain alternatives such as:

* reduced hosted history
* local/full research dataset
* compressed/columnar historical storage
* Parquet/object storage
* hybrid PostgreSQL + analytical storage

without changing technology merely for novelty.

---

# PART VIII — DATA LICENSING / PUBLIC DEPLOYMENT

This project will potentially be visible publicly.

Identify any risk that market-data provider credentials or licensed/raw market data could be redistributed improperly.

FIINQUANT CREDENTIALS MUST NEVER REACH THE BROWSER.

Treat external market-data credentials as backend-only secrets.

If provider terms cannot be verified from the repository, explicitly mark:

`EXTERNAL LEGAL / LICENSING VERIFICATION REQUIRED`

Do not invent permissions.

Distinguish between:

* using source data internally for calculations
* displaying derived analytics
* redistributing raw historical data
* exposing an API that allows third parties to retrieve provider data

---

# PART IX — AUTHENTICATION

Determine what actually needs authentication.

A recruiter visiting the public portfolio link should ideally be able to see core project functionality without being forced to create an account.

Authentication should be used for user-specific functionality such as:

* saved research
* portfolios
* watchlists
* saved backtests
* preferences
* private datasets

Evaluate the simplest appropriate solution based on the deployed architecture.

Potential approaches may include:

* Supabase Auth
* Clerk
* Better Auth
* another justified solution

Do not add auth complexity solely for resume buzzwords.

Audit:

* session lifecycle
* JWT/session validation
* server-side authorization
* user ownership
* database row-level access
* route protection
* CSRF where applicable
* secure cookies
* password handling
* OAuth configuration

Frontend hiding is NOT authorization.

If a backend endpoint requires authorization, enforce it server-side.

---

# PART X — STATE MANAGEMENT

Do NOT automatically recommend Redux, Zustand, Context, or another library.

First classify every piece of state into:

### Server state

Examples:

* historical prices
* Greeks
* research data
* backtest results
* portfolios stored remotely

Evaluate TanStack Query / framework-native data fetching for caching, revalidation, invalidation, retries, and server synchronization.

### URL state

Examples:

* ticker
* timeframe
* date range
* tab
* filters

Prefer URL state when it should be bookmarkable/shareable.

### Local component state

Examples:

* dialog state
* temporary input
* form controls

Keep local if possible.

### Global client-only state

Only introduce Zustand or another client store if genuine cross-component/client-only state remains after server state and URL state are modeled correctly.

Detect duplicated server state stored unnecessarily in client stores.

---

# PART XI — DEPLOYMENT

The immediate goal is:

**public working resume demo with minimal cost**

not maximum infrastructure complexity.

Evaluate whether the application can use a lean deployment similar conceptually to:

Browser
↓
Next.js
↓
API/BFF
├── PostgreSQL
└── Python quant service where necessary

while keeping heavier infrastructure locally or documented if it is not required by the public demo.

Evaluate:

* Vercel
* Supabase
* Neon
* Railway
* Render
* equivalent services

against:

* cost
* free-tier limitations
* sleep/cold starts
* database storage
* authentication
* Python support
* websocket support
* background processing
* scheduled ingestion
* secrets
* deployment complexity
* recruiter-demo reliability

If FastAPI only handles ordinary request/response quant calculations, evaluate serverless deployment.

If it depends on:

* long-lived websocket connections
* workers
* perpetual consumers
* Kafka consumers
* persistent processes

then explicitly state why serverless may be inappropriate.

Separate the architecture into:

### DEVELOPMENT / FULL SYSTEM MODE

Can contain architecture required for deeper engineering experimentation.

### PUBLIC DEMO MODE

Should contain only the components required to demonstrate the platform reliably.

Do not recommend hosting Kafka, Redis, workers, and multiple microservices merely to make the architecture look impressive on a resume.

---

# PART XII — ENGINEERING QUALITY

Audit:

* directory structure
* modularity
* typing
* abstraction quality
* error handling
* logging
* configuration
* tests
* dependency management
* duplicated code
* dead code
* API contracts
* schema validation
* migrations
* observability
* CI
* linting
* formatting
* documentation

Look specifically for code that appears to have been AI-generated without proper architectural integration.

Flag:

* speculative abstraction
* wrapper layers with no value
* giant functions
* duplicated models
* hidden coupling
* inconsistent naming
* magic numbers
* formulas implemented multiple times
* business logic in UI components
* network calls inside calculation modules
* financial logic duplicated across languages

---

# SEVERITY SYSTEM

Every finding must be assigned:

**P0 — Critical**

Can produce materially incorrect financial results, serious security issues, data loss, or fundamentally broken architecture.

**P1 — High**

Likely correctness, reliability, scalability, maintainability, or deployment problem.

**P2 — Medium**

Technical debt or design problem that should be fixed but is not blocking correctness.

**P3 — Low**

Cleanup, polish, optimization, documentation, or optional improvement.

Also include:

* confidence: High / Medium / Low
* evidence
* affected files
* verification method

Do not classify stylistic opinions as high-severity findings.

---

# REQUIRED DELIVERABLES

Create:

`audit/claude/00-executive-summary.md`

Include:

* current architecture in plain English
* overall engineering assessment
* overall quant correctness assessment
* top risks
* top strengths
* top 10 actions

Create:

`audit/claude/01-system-architecture.md`

Include current architecture diagrams and proposed architecture where appropriate.

Create:

`audit/claude/02-quant-financial-models.md`

Include every financial finding and numerical verification strategy.

Create:

`audit/claude/03-data-pipeline-postgres.md`

Include FiinQuant usage analysis, proposed historical persistence architecture, schema design, indexes, backfill strategy, incremental strategy, and estimated storage.

Create:

`audit/claude/04-auth-state-frontend.md`

Include authentication and state-management recommendations.

Create:

`audit/claude/05-deployment.md`

Include at least:

* zero/near-zero-cost public deployment
* slightly paid but more reliable option
* tradeoffs
* what NOT to deploy

Create:

`audit/claude/06-test-strategy.md`

Include the quantitative and software verification test matrix.

Create:

`audit/claude/07-implementation-roadmap.md`

Organize work into dependency-aware phases.

For example, determine whether the correct order resembles:

architecture/correctness fixes
→ quantitative correctness tests
→ persistence/data pipeline
→ state/data fetching
→ authentication
→ deployment
→ polish/observability

but derive the actual ordering from the repository.

For every implementation phase provide:

* exact objective
* affected modules
* dependencies
* expected difficulty
* risks
* acceptance criteria
* tests required

---

# FINAL SYNTHESIS REQUIREMENTS

After all subagents finish, synthesize their work.

Do not merely concatenate their reports.

Resolve conflicts.

If two auditors disagree:

1. state the disagreement
2. inspect the code/evidence again
3. attempt objective verification
4. state the final conclusion
5. preserve uncertainty if it cannot be proven

At the end, print a concise terminal summary containing:

* P0 count
* P1 count
* P2 count
* P3 count
* top 5 correctness risks
* top 5 architecture actions
* recommended PostgreSQL strategy
* recommended auth strategy
* recommended state-management strategy
* recommended public deployment architecture
* recommended first implementation task

Again:

**DO NOT IMPLEMENT THE FIXES YET.**

Complete the audit and wait for my approval before changing application source code.