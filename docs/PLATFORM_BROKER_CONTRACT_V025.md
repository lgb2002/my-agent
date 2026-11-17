# ProjectAgain Platform v0.25 — Streamlit Agent OAuth Auto-Refresh Broker API Contract

**Platform code status:** implemented + isolated tests. **Production status:** NOT deployed, NOT end-to-end verified with Streamlit Cloud or live PostgreSQL multi-worker concurrency.

**Source requirement:** `ProjectAgain_Agent_OAuth_Auto_Refresh_Spec_v0181(1).md` (Agent v0.18 / Platform v0.23). This contract supersedes only the automatic-renewal extension; existing `ProjectAgain_Streamlit_OIDC_API_Contract_v023.md` remains valid for native OIDC / legacy API.

## 1. Architecture and invariants

- ProjectAgain remains OIDC issuer and retains existing users (`users.id` UUID), browser login, HttpOnly session cookie and CSRF checks. No new user DB or SSO provider.
- Existing `projectagain-streamlit` client with original `/oauth2callback` continues to work for `st.login()`. **New** `projectagain-streamlit-broker` confidential client has a fixed callback **on the ProjectAgain platform** `/api/v1/oauth/broker/callback`.
- Browser: ProjectAgain login → explicit consent → authorization code + S256 PKCE → broker callback → single-use ticket and client state → Streamlit return URL. No OAuth access/refresh tokens or broker session secret in browser URL.
- Streamlit backend creates and **durably** stores a random `session_proof` and `client_state` bound to a separate browser/login session (not merely user UUID), then sends only SHA-256(`session_proof`) in `intents`.
- Backend completes authorization code redemption *in-process* using the same v0.23 PKCE validation, stores access + rotating refresh ciphertext using Fernet; encryption key lives in Replit Secrets outside DB. The broker issues an opaque session credential to the authenticated Streamlit backend through the one-time ticket exchange. Refresh Token never enters Streamlit memory, state or HTTP response.
- Access tokens are opaque OAuth v0.23 credentials. Before each private API/AI action, ask broker `/access`. Broker checks expiry and refreshes when `expires_at <= server_now + 120s`, not on a timer. The token expires after 900 seconds; Refresh Token after up to 14 days, family after a maximum of 30 days. This is **not** a 30-day guaranteed login.
- Broker access uses registered confidential HTTP Basic authentication AND `x-broker-session` AND `session_proof`. Session row binds user UUID, session proof, scope, token family and user `auth_version`.
- In production `POST /access` locks the per-session DB row (`SELECT ... FOR UPDATE`) on PostgreSQL before deciding whether to refresh. The old refresh token is marked rotated and both new token ciphertext values are committed **in one DB transaction**. A replay of a previous refresh token is not attempted by broker. If DB transaction fails, roll back and return `503 temporarily_unavailable`; no blind retry of old raw credential.
- OAuth scopes are limited to `openid`, `profile`, `email`, `listing:read`, `buyer_profile:read`, `offer:read`, `offer:draft`. `offer:draft` requires explicit consent and continues through existing approval-pending workflow. No `offer:execute`, account mutation, private-file inspection, financial execution or right transfers.
- Legacy ServiceGrant and native OIDC endpoints remain functional during transition. No background refresh job.

## 2. Registered URLs and server settings

### Platform Replit Secrets

```ini
APP_ENV=production
DATABASE_URL=<unchanged existing PostgreSQL URL>
OAUTH_ENABLED=true
OAUTH_ISSUER=https://<EXACT-PROJECTAGAIN-PUBLIC-DOMAIN>
OAUTH_STREAMLIT_CLIENT_ID=projectagain-streamlit
OAUTH_STREAMLIT_CLIENT_SECRET=<existing stable native client secret>
OAUTH_STREAMLIT_REDIRECT_URI=https://projectagain.streamlit.app/oauth2callback
OIDC_SIGNING_PRIVATE_KEY_PEM=<existing persistent RSA private key>
OIDC_SIGNING_KID=<existing persistent kid>

# New v0.25 BFF only; first leave disabled until setup and integration testing:
OAUTH_BROKER_ENABLED=false
OAUTH_BROKER_CLIENT_ID=projectagain-streamlit-broker
OAUTH_BROKER_CLIENT_SECRET=<new independent 32+ character cryptographic random string>
OAUTH_BROKER_ENCRYPTION_KEY=<Fernet-generated base64url 32-byte symmetric key>
OAUTH_BROKER_STREAMLIT_RETURN_URI=https://projectagain.streamlit.app/
```

- Broker OAuth callback is **derived only from issuer**: `https://<EXACT-PROJECTAGAIN-PUBLIC-DOMAIN>/api/v1/oauth/broker/callback`; no wildcard or user-supplied callback.
- `OAUTH_BROKER_STREAMLIT_RETURN_URI` must be an exact HTTPS URL with no pre-existing query/fragment. Browser callback appends `pa_broker_ticket` and `pa_broker_state`.
- `OAUTH_BROKER_ENCRYPTION_KEY`: generate securely (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) and save to secret manager, **not** to repository, browser, logs, Streamlit config, or chat. Keep the key stable across deployment. Unplanned rotation makes existing sessions undecryptable: implement an audited migration / planned global re-login for key rotation.
- `OAUTH_BROKER_CLIENT_SECRET`: generate separately from the native client (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), store in **both** Replit Secrets and Streamlit Secrets; never expose in browser UI or log.
- Production fails closed if HTTPS, PostgreSQL, registered client secret, or encryption key is missing. The original OIDC can be left enabled with the new broker disabled.

### Streamlit server-side configuration (names are a proposed Agent-side adapter contract)

```toml
PROJECTAGAIN_API_ORIGIN = "https://<EXACT-PROJECTAGAIN-PUBLIC-DOMAIN>"
PROJECTAGAIN_BROKER_CLIENT_ID = "projectagain-streamlit-broker"
PROJECTAGAIN_BROKER_CLIENT_SECRET = "<same as Replit OAUTH_BROKER_CLIENT_SECRET>"
PROJECTAGAIN_BROKER_REDIRECT_URL = "https://projectagain.streamlit.app/"
```

Agent retains its original `[auth]` OIDC config only for transitional native `st.login()` use; it **must not rely on `st.user.tokens.refresh` or claim native `st.login()` manages the broker's refresh**.

## 3. API request / response contracts

All URLs below are relative to `OAUTH_ISSUER`. Every broker response has `Cache-Control: no-store`. All server-to-server calls must use HTTPS in production and HTTP Basic with the registered broker client ID and secret. Headers must be redacted in diagnostics. Browser must **not** send Basic credentials or broker session secret.

### 3.1 `POST /api/v1/oauth/broker/intents` — Start (Streamlit server only)

Headers: `Authorization: Basic <base64(client_id:client_secret)>`, `Content-Type: application/json`.

Request:

```json
{
  "client_state":"RANDOM_URL_SAFE_16_TO_256_CHARACTERS",
  "session_binding_hash":"SHA256_LOWERCASE_HEX_OF_SERVER_ONLY_SESSION_PROOF",
  "scope":"openid profile email listing:read buyer_profile:read offer:read"
}
```

Default `scope` if omitted: `openid profile email listing:read buyer_profile:read`. Any unregistered or execution scope -> `400 invalid_scope`. State and proof are generated by Streamlit for EACH browser/login session, never derived solely from a user UUID. `session_binding_hash` must be 64 lowercase hex characters, `session_proof` must be URL-safe random 32–256 chars. The raw proof is **not sent** here.

`200` response:

```json
{"authorization_url":"https://<PLATFORM>/api/v1/oauth/authorize?response_type=code&...", "expires_in":300}
```

Streamlit redirects browser to `authorization_url`. Existing platform session cookie is used if present; otherwise existing `/login` handles login then consent. Authorization Code expires in 120 seconds and is usable once. OAuth state and PKCE verifier are generated on platform and retained only as hash/encrypted DB rows.

### 3.2 Browser-only authorization / callback

- `GET /api/v1/oauth/authorize?...` → existing login / `/oauth/consent` and explicit scope consent.
- After approval: browser receives a `303` to **platform-internal** `GET /api/v1/oauth/broker/callback?code=...&state=...`. The callback consumes state and PKCE-bound code exactly once.
- The platform responds `303 Location: https://projectagain.streamlit.app/?pa_broker_ticket=<60-second single-use ticket>&pa_broker_state=<client_state>`.
- Cancellation returns `?pa_broker_error=access_denied&pa_broker_state=<client_state>`.
- No OAuth Access Token, Refresh Token or broker session credential is transmitted through browser query strings. Clear `pa_broker_ticket` and `pa_broker_state` from browser URL immediately after secure exchange; suppress query-string logging and referrer forwarding.

### 3.3 `POST /api/v1/oauth/broker/tickets/exchange` — Finish (Streamlit server only)

Headers: registered HTTP Basic, `Content-Type: application/json`.

Request:

```json
{"ticket":"<one-time ticket from browser callback>","client_state":"<client state from browser callback>","session_proof":"<random proof retained privately by Streamlit backend>"}
```

The Streamlit backend MUST first look up a pending state record in its **durable server-side pending-login store** and verify the authentic browser session it belongs to. Do not rely on `st.session_state` alone across a full redirect: Streamlit can reset it on WebSocket disconnection/reload. Use an independently authenticated browser session identity and encrypted per-session pending state. If no exact pending session is available, reject and restart login (fail closed).

`200` response:

```json
{"broker_session":"<opaque broker-session credential>","sub":"<immutable user UUID>","scope":"openid profile email listing:read buyer_profile:read","expires_at":"<UTC family expiry ISO8601>"}
```

The server persists the broker session credential and proof against the **same specific browser/login session**; never use an application-global cache indexed only by user ID. Validate `sub` against the pending expected identity, if an existing authenticated identity is present. Consumes the ticket atomically and rejects second exchange (`401 invalid_ticket`). No Refresh Token is returned.

### 3.4 `POST /api/v1/oauth/broker/access` — Ensure fresh token (Streamlit server only)

Headers: HTTP Basic, `x-broker-session: <opaque broker-session credential>`, `Content-Type: application/json`.

Request:

```json
{"session_proof":"<random proof for this exact browser/login session>"}
```

`200` response while valid:

```json
{"access_token":"<opaque v0.23 OAuth access token>","token_type":"Bearer","expires_in":740,"sub":"<immutable user UUID>","scope":"openid profile email listing:read buyer_profile:read","refreshed":false}
```

If 120 seconds or less remain (`expires_at <= now + 120s`), before a protected API call the broker rotates Refresh Token and Access Token **atomically** and responds `refreshed:true`, `expires_in:900`. Non-expired access >120s returns existing token unchanged. No periodic renewal occurs without API requests.

**Recovery after downstream private API `401`, for safe GET only:** the Agent may make **one** broker request with `{"session_proof":"...", "force_refresh":true, "observed_access_token_hash":"<sha256 hex of the Access Token that received 401>"}`. With the broker DB session lock, if another tab already rotated that observed token, it returns the latest token **without** rotating again (`refreshed:false`); otherwise rotates just once. Then retry GET **once**. Never use this to automatically repeat a POST or to bypass a 403/scope denial. Missing/wrong-format observed hash -> `400 invalid_request`.

Agent API wrapper: call `/broker/access` **before** private GET or AI/payment-incurring work. If broker request fails, do not call personal API or paid AI. On a downstream API 401, at most one recheck and **only safe GET** retry. For `POST /api/v1/agent-actions` or any non-idempotent action: **no automatic re-POST**; show the outcome ambiguity and ask for user decision. Never leak `access_token` to Streamlit UI/logs.

### 3.5 `POST /api/v1/oauth/broker/logout` — Revoke one broker login session

Same headers as `/access`. JSON `{"session_proof":"<session proof>"}`. `200 {"ok":true}`; broker marks current session revoked and revokes underlying OAuth token family using the same provider routine as `/api/v1/oauth/revoke`. Streamlit clears its associated proof/session/identity-specific cached data. This revokes **one** login session/family; other devices retain their own sessions unless account-wide revocation is requested.

### 3.6 Existing account-wide disconnection

- `GET /api/v1/oauth/connections` — cookie login, returns both legacy OIDC and broker connection summaries, no secret values.
- `POST /api/v1/oauth/connections/revoke` — cookie+CSRF, revokes all native and broker OAuth families for that user. Existing ServiceGrant tokens are **separately managed**.
- User `auth_version` change/password reset/account deletion invalidates broker sessions. Account erasure clears encrypted broker credentials as part of the existing deletion workflow.
- `POST /api/v1/auth/logout` clears the **website cookie** only; do not confuse this with the Streamlit broker logout action. Streamlit Logout MUST call `/broker/logout`. If the user wants account-wide disconnection, call `/oauth/connections/revoke` from the logged-in platform.

## 4. Errors and security actions

| Status | `error` | Agent action |
|---|---|---|
| 400 | `invalid_request`, `invalid_scope` | Fix payload; no private API call |
| 400 | `invalid_state`, `invalid_grant` during browser callback | Stop; start a fresh login |
| 401 | `invalid_client` | Stop; check server secret, never show secret |
| 401 | `invalid_ticket` | Ticket already consumed/expired/wrong session; restart login |
| 401 | `reauth_required` | Clear broker session, protect data, show “다시 로그인” |
| 503 | `temporarily_unavailable` | Do not retry stale refresh token directly; fail closed, allow later fresh `/access` request |
| 503 | `broker_key_unavailable` or setup error | Stop; do not silently fall back to anonymous or wrong user's credentials |

Broker-owned JSON failures use `{ "error":"<string>" }`; global FastAPI `HTTPException` errors may use `{ "error": {"code":"401","message":"invalid_client", "request_id":"..."} }`. Agent should parse both shapes, never display HTTP headers or raw tokens. Login callback failures return a fixed error redirect or HTTP 400.

- Network ambiguity of the old external Refresh Token exchange is eliminated: token rotation is an **in-process provider routine in the SAME DB transaction** as ciphertext replacement. A database failure rolls back both operations and returns 503. If connection/commit result is uncertain, a new `/access` reads the latest DB state and must never replay a cached previous raw Refresh Token.
- If the server revokes a family, changes auth version, or expires the refresh/family, broker returns 401 and does not use stale tokens. No privilege-escalating fallback to legacy manual grants.
- Never log credentials, ticket URLs, client secrets, ID Token or private keys. Keep HTTPS/HSTS at deployment edge; apply CSP and rate limits to public login flows where appropriate.

## 5. Persistence schema and concurrency

New migration **`0011_oauth_broker`** (after v0.23 `0010_oauth_oidc`) creates:

- `oauth_broker_intents`: hashed internal OAuth state and hashed client state, encrypted PKCE verifier and client state, scopes, proof hash, 5-minute expiry and consumed flag.
- `oauth_broker_sessions`: hashed opaque session credential, hashed server-session proof, immutable user UUID, client ID, scope, `auth_version`, OAuth family ID, encrypted access/refresh values, both expiries, generation counter, revocation.
- `oauth_broker_tickets`: hashed random ticket, intent/session foreign keys, 60-second expiry, single use.

An OAuth family belongs to one broker session. `/access` selects that broker session with `FOR UPDATE` under PostgreSQL before refresh, then marks the exact current Refresh Token rotated and replaces encrypted credentials atomically. Other requests for that session wait and then see the new generation. SQLite does not support these production row locks: isolated tests confirm logic only, **not** real cross-process PostgreSQL concurrency.

## 6. Current verification status

**Verified in isolated temporary SQLite tests (current package):**

- Existing ProjectAgain browser login → OIDC/PKCE consent → broker callback → one-time ticket → Streamlit-server-style ticket exchange → private API access.
- 12-minute-equivalent access remaining 180 seconds: no refresh; 13-minute-equivalent access remaining 115 seconds: refresh once; subsequent request same new token.
- Expired access: pre-call refresh; different users and scopes isolated; no transaction execution/sensitive access scope escalation.
- Wrong/expired/replayed ticket and proof rejected, browser callback state consumed, consent cancellation handled.
- One-session logout and account-wide disconnect invalidated access immediately; `auth_version` invalidation and expired Refresh Token fail closed; injected DB refresh error rolls back without revoking a valid token family; account erasure clears ciphertext.
- Existing v0.23 OAuth/OIDC regression tests still pass, new migration reaches `0011` on temporary SQLite DB.

**Not yet verified:** real Replit PostgreSQL 3+ concurrent requests/multiple worker lock behavior; network partition and ambiguous PostgreSQL commit; Streamlit Cloud native browser tab binding/pending login persistence; Streamlit restart/redeployment; real browser full E2E; frontend `npm run build` (this environment's npm cache cannot fetch all packages). The platform is **not ready to be declared production E2E complete** until these are tested.

## 7. Required Streamlit Agent v0.18+ implementation work

1. Add server-only broker client credentials and a durable pending state store keyed by random `client_state` **AND** the authenticated browser session; data contains encrypted proof, expiry, initiating user context. Do not store raw Refresh Token anywhere.
2. Replace the native `st.login()` access-token-only flow for automatic renewal with the broker's authorization URL; the legacy native login can remain during transition but does not automatically upgrade an existing token to a broker session.
3. On return, verify browser session and pending state, exchange ticket server-to-server, check `sub`, save broker credential under that session, and immediately clear URL query parameters.
4. Implement `ensure_fresh_access(expiry_margin=120)` for each private API call; broker itself makes the renewal decision. Never call private API or paid AI if broker denies authentication.
5. Retry at most one safe GET on a downstream 401, no automatic retry for non-idempotent POST. `offer:draft` must still require consent and approval-pending policy.
6. On logout/account switch, call `/broker/logout`, discard previous user memory/API cache, preserve only nonsensitive draft content; do not reuse another user's broker credential.
7. Test real platform + Streamlit Cloud browser and 3 concurrent calls on PostgreSQL; verify no duplicate rotation, failed refresh no token leak, and E2E restart survival.

## 8. Safe deployment/restart (full ProjectAgain ZIP only)

1. Stop Replit run process. Upload the **complete** v0.25 ZIP under `~/workspace`. Do not use patch workflow.
2. Back up `DATABASE_URL` PostgreSQL via `pg_dump --format=custom`, confirm file via `pg_restore -l`, back up private files/other storage and preserve root `.replit` and Secrets.
3. `cd ~/workspace && mv projectagain "projectagain_backup_$(date +%Y%m%d_%H%M%S)" && unzip ProjectAgain_v0.25_OAuth_Broker_20261117.zip -d ~/workspace`
4. Configure Replit Secrets (new broker vars above, default `OAUTH_BROKER_ENABLED=false`), preserve all old keys.
5. `cd ~/workspace/projectagain && bash scripts/setup_replit.sh` (frontend build + `0011` migration). Stop on failure.
6. `cd ~/workspace/projectagain/frontend && npm run build`; then `cd ../backend && ../.venv/bin/python -m alembic current` → `0011_oauth_broker (head)`.
7. `cd ~/workspace/projectagain && bash scripts/check_broker_v025.sh`; run `AGENT_WRITE_MODE=demo_only bash scripts/check_project_v013.sh` for legacy regression.
8. Shell 1: `cd ~/workspace/projectagain && bash scripts/run_replit.sh`; Shell 2: `curl -i http://127.0.0.1:5000/health`; Shell 3 (if configured): `cd ~/workspace/projectagain && bash scripts/run_notification_worker.sh`.
9. After separate Streamlit integration and config + security tests, set `OAUTH_BROKER_ENABLED=true`, restart development server; Replit Publishing **Republish**; keep long-lived worker separately managed for production.
10. If new integration fails, keep broker disabled and continue native `st.login()` / manual grants; do not delete DB tables or rotate encryption key during rollback.

## Reference

- Agent spec uploaded 2026-11-17: `ProjectAgain_Agent_OAuth_Auto_Refresh_Spec_v0181(1).md`
- RFC 9700 OAuth 2.0 Security BCP: https://www.rfc-editor.org/rfc/rfc9700
- Streamlit `st.user` and session-state docs: https://docs.streamlit.io/develop/api-reference/user/st.user ; https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
