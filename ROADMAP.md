# Sports Portal — Roadmap to a Public Web App

This plan takes the current local Windows setup (Flask on `127.0.0.1:5003`,
Desktop folders, Task Scheduler, SQLite files) to a public site with many
users. It follows the rules in `PROJECT_CONTEXT.md`: small steps, test after
each one, keep existing routes and UI, never delete historical data or
previously saved odds, and leave `football_matcher.py` and the NFL code alone
unless there is a concrete reason.

Every phase ends with a working portal. No phase requires a rewrite.

---

## Where things stand

**Already in good shape**
- The collectors → DB → portal architecture is in place for football odds.
  `/`, `/api/markets`, `/api/league-cache` and `/api/cached-matches` read
  `football_odds.db` read-only.
- EuroLeague stats, player points, NFL and football stats are separate
  Blueprints.
- Passwords are hashed (werkzeug), and the updaters keep old odds when a
  fetch fails.

**Blockers for going public**

| # | Problem | Where |
|---|---------|-------|
| B1 | Code lives outside the repo. The NFL and football-stats Blueprints `exec` modules from `C:\Users\dkecm\Desktop\...` at import time, and the match/odds updaters (`kvote\football_matches_updater.py`, the odds updater) are not in git. The app cannot be deployed from this repo. | `nfl_portal.py`, `football_stats_portal.py`, `source_modules.py` |
| B2 | Paths are hard-coded to Windows. | `app.py:64`, `euroleague_portal.py:13`, `basketball_points_portal.py:11`, `nfl_portal.py:7`, `football_stats_portal.py:6` |
| B3 | The secret key is hard-coded, so anyone who reads the repo can forge a session, including `is_premium`. | `app.py:30` |
| B4 | Premium is not enforced. `is_premium` is a boolean read once at login and only changes a label. `/premium/1/3/6` are static pages. | `app.py:1818`, `users.py` |
| B5 | A user request still reaches a bookmaker. `/nfl/api/game/<key>` runs the legacy NFL collectors on request, which breaks the core rule. | `nfl_portal.py` |
| B6 | Dead collector code still loads with the web app: the `get_*_all` getters, `build_all_matches`, the bookmaker clients and kickoff-map fetchers. | `app.py:20-27`, `app.py:124-1045` |
| B7 | There are no tests, no dependency manifest and no CI. | repo root |
| B8 | Security basics are missing: no CSRF protection, no login rate limit, no secure cookie flags, and the dev server is used as production. | `app.py` |
| B9 | Meridian player props need a short-lived browser `MERIDIAN_ACCESS_TOKEN`, which cannot run unattended on a server. | `player props/` |
| B10 | Some queries are inefficient. `match_by_id` loads every match to find one, and every page load reads the whole `matches` table. | `app.py:1074` |

---

## Phase 0 — Safety net (no behavior change)

Goal: everything needed to run the portal is in git and can be tested.

1. **Bring missing source into the repo, unchanged** (fixes B1):
   - `kvote/`: `football_matches_updater.py`, the odds updater, and their
     collectors.
   - `player props/`: the NFL app, the collectors, `euroleague_updater.py`,
     `euroleague_stats.py` and `nfl_matcher.py`.
   - `fudbal statistika/app.py`.
   - Keep the Desktop folders and Task Scheduler as they are. The repo copy
     becomes the source of truth, and the Desktop folders sync from it.
2. **Add `requirements.txt`** with pinned versions of Flask, requests,
   werkzeug and so on, taken from `pip freeze` in the existing venvs.
3. **Add `config.py`**: every DB path and source dir is read from environment
   variables, with the current Windows paths as defaults (fixes B2 without
   breaking the local setup). Add `.env.example`.
4. **Read `SECRET_KEY` from the environment** and fail at startup in
   production if it is missing (fixes B3).
5. **Add smoke tests (pytest)**: build tiny fixture DBs with the documented
   schemas (`matches`, `current_odds`, `player_games`, `users`), then check
   that every route returns 200 and that `/api/markets` has the expected
   shape. Freeze the current output as a baseline.
6. **Add CI (GitHub Actions)**: syntax check, `pytest`, and `ruff` in
   report-only mode.

Exit criterion: `pytest` passes on a clean checkout on Linux with fixture DBs.

## Phase 1 — Make the portal a pure reader

1. **Move the NFL odds collection into a background updater** that writes to
   an `nfl_odds.db`, the same pattern as football. `/nfl/api/game/<key>` then
   reads the DB (fixes B5). The NFL matcher and collectors stay unchanged;
   only their call site moves.
2. **Delete the dead collector code from `app.py`** (fixes B6). It is still in
   git history and in the updaters, which are its real users.
3. **Query the DB instead of looping in Python**: `match_by_id` gets
   `WHERE match_id = ?`, and the index page filters `kickoff_ts > now` in SQL.
   Add indexes on `current_odds(match_id)` and `matches(league, kickoff_ts)`
   (fixes B10).
4. **Add a `collector_runs` table**: each updater writes bookmaker, start,
   end, status and row count. The portal can then show "odds updated N min
   ago", and monitoring can alert on stale data.

## Phase 2 — Structure the web app (same routes, same look)

1. **Use an app factory** (`create_app()`), a `sports_portal/` package, and
   one Blueprint per area: `auth`, `premium`, `football_odds`, plus the
   existing ones.
2. **Move the inline HTML strings into `templates/`**, starting with the
   ~600-line `HTML` in `app.py`, then portal, login, register and premium.
   Use one base layout with a shared header and a "← Sports Portal" link
   instead of `.replace("<body>", ...)` hacks.
3. **Move static CSS and JS to `static/`** so browsers can cache them.
4. **Keep URLs identical.** The Phase 0 smoke tests prove it.

## Phase 3 — Users, security, Premium

1. **Schema migration (additive only)**:
   - `users`: add `premium_until`, `email_verified_at`, `last_login_at` and
     `role`.
   - New tables: `subscriptions`, `payments` and `password_resets`.
   - Keep `is_premium` for compatibility and derive it from `premium_until`.
2. **Check Premium server-side on every request** with a
   `@premium_required` decorator and a helper that reads the DB rather than
   the session. Decide which content is free and which is Premium (for
   example: free = 1X2 + top leagues + L5; Premium = all markets, all leagues,
   L10 and season, player props) (fixes B4).
3. **Security hardening** (fixes B8):
   - CSRF protection on forms (Flask-WTF, or a small custom token).
   - Rate limits on login and register (Flask-Limiter).
   - `SESSION_COOKIE_SECURE`, `HTTPONLY` and `SAMESITE=Lax`.
   - Minimum password length.
   - Security headers.
4. **Account flows**: email verification and password reset through a
   transactional email service (Postmark, Brevo or Amazon SES).
   - Add an account page showing Premium status and expiry.
   - Let users delete their own account (a data-protection requirement).

## Phase 4 — Payments

1. **Choose a provider that can pay out to a Serbian business.** Stripe does
   not onboard Serbian merchants directly, so evaluate:
   - Merchant-of-record services such as Paddle or Lemon Squeezy. They handle
     VAT and invoicing; check that they accept betting-adjacent content.
   - Local card acquiring: Payten/NestPay (Banca Intesa, OTP), AllSecure,
     Monri. These can charge in RSD, but you invoice yourself.
2. **Integrate**: hosted checkout, then a webhook that sets `premium_until`
   and writes a `payments` row. Verify webhook signatures and make them
   idempotent. Premium is granted only by the webhook, never by the redirect
   back to the site.
3. **Keep current pricing**: 1 month = 600 RSD, 3 months = 1,500 RSD,
   6 months = 2,500 RSD.
   - Start with one-time packages; they are simpler than recurring billing.
   - Handle refunds and expiry reminders.

## Phase 5 — Data platform for production

1. **Database**
   - To start, keep SQLite with WAL mode on one server, with updaters and web
     on the same host. That is enough for the first thousands of users,
     because the portal only reads.
   - When there are several web instances, or writes become frequent, move
     to PostgreSQL. Tables and keys stay the same, so this is a port, not a
     redesign.
2. **Move the updaters to Linux jobs**: systemd timers or cron replace
   Windows Task Scheduler.
   - Keep the same cadence: matches every 15 min, odds on their current
     cadence, EuroLeague at 01:00, backup at 03:00.
   - Add a lock so two runs of the same job never overlap.
3. **Check where the data sources can be reached from.** Serbian bookmaker
   APIs may block datacenter or foreign IPs. Test every collector from the
   target host before migrating. You may need a Serbian VPS, or to keep the
   collectors on a home or office machine that pushes to the server.
4. **Find a replacement for the Meridian token (B9)**: either an endpoint
   that works without the token, or leave Meridian props out of automatic
   refresh.
5. **Odds history (optional, later)**: an append-only `odds_history` table
   for line-movement charts, a good Premium feature. `current_odds` stays as
   it is.
6. **API cache**: short-lived in-process or Redis cache for league/match
   JSON, invalidated when the matching `collector_runs` row updates.

## Phase 6 — Deployment and operations

1. **Hosting**: one Linux VPS to start (location chosen per 5.3).
   - Docker Compose with services `web`, `updaters` and later `db`.
   - The `web` service runs gunicorn behind Caddy or nginx.
2. **Domain and TLS**: register a domain; Caddy or Let's Encrypt handles
   HTTPS.
3. **Deploys**: GitHub Actions runs the tests, then deploys over SSH or
   through a container registry. Migrations run before the app restarts.
4. **Backups**
   - Take nightly consistent snapshots (`sqlite3 .backup` or `pg_dump`) and
     copy them off-site (Backblaze B2, S3 or Google Drive via rclone).
   - Keep 30 days.
   - Test a restore every month.
   - The current Windows backup job keeps running until the server is the
     primary system.
5. **Monitoring**
   - Sentry for errors.
   - An uptime check on `/healthz`.
   - An alert when `collector_runs` shows a bookmaker stale for more than
     X minutes.
   - Structured logs with rotation.

## Phase 7 — Legal and compliance (start in parallel with Phase 3)

Get advice from a Serbian lawyer before launch. At minimum, cover:

- **Gambling rules**: the Serbian law on games of chance (Zakon o igrama na
  sreću) and its advertising restrictions.
  - Add an 18+ notice and responsible-gambling links.
  - Affiliate links to bookmakers can count as advertising and may need
    their own review.
- **Bookmaker terms**: collecting their public odds may conflict with their
  terms. Consider data or affiliate agreements with the bookmakers you use.
- **Personal data**: Serbia's data protection law (ZZPL, modelled on the
  GDPR), plus the GDPR itself for EU visitors.
  - Privacy policy and cookie notice.
  - Data processing agreements with email and payment providers.
  - A way for users to export and delete their data.
- **Business**: a registered entity (preduzetnik or d.o.o.), terms of
  service, fiscal invoices, and VAT (PDV) once over the threshold.

## Phase 8 — Product growth

- **Mobile-first pass** of the odds tables. Most betting traffic is mobile.
- **More leagues and sports**, added as new updaters plus a Blueprint each,
  following the existing pattern.
- **Premium features**: line movement, value/arbitrage highlights, alerts
  (email or Telegram) and favourites.
- **SEO**: server-rendered league and match pages with clean URLs and a
  sitemap.
- **Languages**: Serbian first, English optional (Flask-Babel).
- **Analytics** that respect privacy (Plausible or Umami).

---

## Suggested order and size

| Step | Phase | Size | Can ship alone |
|------|-------|------|----------------|
| 1 | 0.1–0.4 Source into repo, config, secret key | S | yes |
| 2 | 0.5–0.6 Tests + CI | M | yes |
| 3 | 1.2–1.3 Remove dead code, SQL filters | S | yes |
| 4 | 1.1 NFL background updater | M | yes |
| 5 | 1.4 `collector_runs` + freshness badge | S | yes |
| 6 | 3.1–3.3 Premium enforcement + security | M | yes |
| 7 | 2.x Templates / app factory | M | yes |
| 8 | 6.x Staging server, Linux updaters, backups | M | yes, as staging |
| 9 | 7.x Legal review | — | parallel |
| 10 | 3.4 + 4.x Email flows + payments | L | launch gate |
| 11 | Public launch | — | — |
| 12 | 5.5, 8.x Growth features | ongoing | — |

**Launch gate** (all must be true before the public goes live):
- B1–B9 are resolved.
- HTTPS is on.
- Premium is enforced server-side and paid for through verified webhooks.
- Backups are running and a restore has been tested.
- The legal pages are published.
- Monitoring and alerting are active.
