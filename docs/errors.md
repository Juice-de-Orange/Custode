# Error reference catalogue (RFC 9457)

> Every API error response is `application/problem+json` with a **stable `type`** (clients
> branch on it, never on message strings) and a **`reference`** (a short code derived from the
> `request_id` that the user can copy → trace/logs/Sentry, ARCHITECTURE §12). Convention:
> `type = https://github.com/Juice-de-Orange/Custode/blob/main/docs/errors.md#<slug>`.

Response shape (example):

```json
{
  "type": "https://github.com/Juice-de-Orange/Custode/blob/main/docs/errors.md#validation",
  "title": "Invalid input",
  "status": 422,
  "detail": "Validation failed.",
  "reference": "CUS-7Q2F-9K",
  "errors": [{ "type": "missing", "loc": ["body", "email"], "msg": "Field required" }]
}
```

`title` and `detail` are English. They are for API users, scripts and the logs; the web app
does not show them — it translates by slug through its own catalogs (German and English).

`errors` is Pydantic's raw format — not `{field, code}`, as this example claimed until 11-A2.
Additional members are merged **flat** into the body, not nested; today there are three:
`households` (on `last_admin`), `category` (on `caldav_write_failed`) and `field` (on
`external_field_readonly`).

## The rule and the gate

New codes are added here **before** they are used in the code — and since 11-A2 that no longer
depends on discipline: `backend/tests/test_error_catalogue.py` holds catalogue and code against
each other in **both** directions. A slug in the code without an entry turns CI red; so does an
entry without a producer. The second direction is the less conspicuous one — a documented error
that does not exist looks like coverage. That is exactly how `ssrf_blocked`, `payload_too_large`
and `idempotency_replay` stood here while the code raised `import_url_blocked`, `file_too_large`
and nothing at all.

A `slug=` that is not a literal escapes the gate and has to be acknowledged there explicitly
(`_DYNAMIC_SLUGS`). Today there is exactly one case: `only_children`.

---

## Cross-cutting (`kernel`) — any route can return these

| slug | HTTP | Meaning |
|---|---|---|
| `validation` | 422 | Pydantic/schema validation failed; `errors` carries the raw details |
| `unauthorized` | 401 | Not authenticated (access cookie missing, expired or unknown) |
| `forbidden` | 403 | Authenticated, but the role/permission is missing (AuthZ matrix) — also without an active household |
| `not_found` | 404 | The resource does not exist — or belongs to another household (RLS answers as if it were not there) |
| `bad_request` | 400 | Starlette's own 400 (malformed request before the domain layer) |
| `conflict` | 409 | Starlette's own 409 without a domain slug |
| `conflict_version` | 412 | Starlette's own 412. **The domain path is called `precondition_failed`** |
| `rate_limited` | 429 | Starlette's own 429. **The case that is actually built is called `too_many_attempts`** |
| `error` | — | Fallback for an `HTTPException` with an unknown status |
| `internal` | 500 | Unexpected error. Built since 11-A2: `problem+json` **with** `reference`, without exception type and without message — the details are in the log, not in the response |

### Conditional requests (ETag/If-Match, ADR-0034)

| slug | HTTP | Meaning |
|---|---|---|
| `precondition_required` | 428 | `If-Match` is missing on a write that requires it |
| `precondition_failed` | 412 | `If-Match` does not match the current `version` — a lost update was prevented |

### Sync batch (ARCHITECTURE §10)

| slug | HTTP | Meaning |
|---|---|---|
| `sync_unknown_entity` | 422 | The batch names an entity type the module spec does not know |
| `sync_unknown_field` | 422 | Field outside the entity's `fields` — the client writes something it may not write |
| `sync_invalid_field` | 422 | Field value has the wrong type/format |
| `sync_missing_fields` | 422 | A `create` without the fields listed in `required_on_create` |
| `resync_required` | 410 | The pull cursor is too old; the client has to load from scratch |

### Files and images

| slug | HTTP | Meaning |
|---|---|---|
| `file_too_large` | 413 | Upload above the limit (recipe photo, guide attachment) |
| `invalid_image` | 422 | Not a decodable image, or a format we do not re-encode |
| `storage_unavailable` | 503 | No blob storage configured (null adapter) — uploads are off, reading still works |
| `export_too_large` | 413 | The data export exceeds the row limit; the refusal comes while **collecting**, not on the finished archive (ADR-0083) |

### Outgoing fetches (recipe import, `kernel/fetch`)

| slug | HTTP | Meaning |
|---|---|---|
| `import_url_blocked` | 400 | The target is private/not allowed, the scheme is wrong, or a redirect would leave the origin. **One** opaque slug for every SSRF refusal — the response deliberately does not reveal which rule applied |
| `import_fetch_failed` | 400 | The source did not answer or answered with an error |
| `import_too_large` | 400 | Response above the size limit |
| `import_too_many_redirects` | 400 | Redirect chain too long |

### Server-side encryption (ADR-0077)

| slug | HTTP | Meaning |
|---|---|---|
| `crypto_unconfigured` | 503 | `CUSTODE_CRYPTO_KEY` is missing — features that store third-party credentials (CalDAV, wearables) answer 503 instead of failing silently |

---

## `accounts` / auth (Phase 1)

| slug | HTTP | Meaning |
|---|---|---|
| `invalid_credentials` | 401 | Wrong e-mail/password — **or** the account is marked for deletion. Deliberately the same answer: a separate slug would reveal that the account existed. Constant time, no enumeration |
| `invalid_token` | 401 | Refresh token unknown, or the refresh cookie is missing |
| `expired_token` | 401 | Refresh token expired |
| `token_reuse` | 401 | An already used refresh token was presented again → theft signal, the **whole** family is revoked |
| `csrf_failed` | 403 | Double-submit token missing or not matching |
| `weak_password` | 422 | The password does not meet the policy |
| `pwned_password` | 422 | The password is on a known breach list (HIBP k-anonymity) |
| `email_taken` | 409 | E-mail already registered |
| `username_taken` | 409 | Username already taken in the household (child account) |
| `weak_pin` | 422 | Child PIN too simple |
| `invalid_pin` | 401 | Wrong child PIN |
| `too_many_attempts` | 429 | Too many failed PIN attempts — the 429 that is actually built |
| `reset_invalid` | 400 | Password-reset token unknown, used or expired |
| `verify_invalid` | 400 | E-mail verification token unknown, used or expired |
| `mail_unavailable` | 503 | Resend of the verification e-mail on a server without SMTP (null adapter) — no mail can be sent; `/v1/auth/me` reports `mail_enabled: false` |
| `invite_expired` | 410 | Invitation code expired |
| `invite_exhausted` | 409 | Invitation code is used up (`max_uses`) |
| `already_member` | 409 | Already a member of this household |
| `totp_required` | 401 | Login needs a TOTP or recovery code (the password was correct) |
| `totp_invalid` | 422 | Wrong TOTP/recovery code |
| `totp_already_enabled` | 409 | 2FA is already enabled |
| `totp_not_set_up` | 409 | Enabling without a preceding `setup` |
| `totp_not_enabled` | 409 | Disabling/recovery codes without active 2FA |
| `passkey_challenge_expired` | 400 | The WebAuthn challenge expired (Redis TTL) — restart the ceremony |
| `passkey_invalid` | 400/401 | Attestation/assertion invalid |
| `passkey_exists` | 409 | This authenticator is already registered |

### Leaving, account deletion, dissolving a household (Phase 11)

Four refusals that look alike and **mean different things**. The difference decides what the
person can do next — folding them into one "that does not work" would mean telling someone to
hand a role to a person who does not exist.

| slug | HTTP | Meaning | Way out |
|---|---|---|---|
| `last_admin` | 409 | Last admin of a household that still has **adults**. `extra.households` names the affected households | **Fixable:** hand over the role under `/account` |
| `only_children` | 409 | Apart from the person, only children or guests live there — nobody *can* take over. Produced via `slug=reason` (`exit_blocker_reason`), not as a literal | **Dissolve the household** (`POST /v1/household/dissolve`) |
| `sole_member` | 409 | Alone in the household: you do not leave, you dissolve. **Only** on leaving — account deletion deliberately allows the case, because Art. 17 is a right and there is no "instead" there | **Dissolve the household** |
| `child_cannot_leave` | 409 | A child account cannot leave by itself: it has neither e-mail nor password and would never get back in | An admin removes the member |
| `already_dissolved` | 409 | The household is already dissolved | — |
| `name_mismatch` | 422 | The typed household name does not match — the confirmation of the dissolution | Type the name exactly |
| `household_dissolved` | 410 | The household was dissolved; access has ended | Create or join a new household |

---

## `backoffice` / operator console (`/ops`, Phase 8)

Its own auth stack: an opaque **bearer** token (no cookie/CSRF). Errors fail closed — every auth
failure is a 401, without operator enumeration.

| slug | HTTP | Meaning |
|---|---|---|
| `invalid_credentials` | 401 | Wrong operator login (password **or** TOTP; constant time) |
| `unauthorized` | 401 | Bearer token missing, expired, unknown — or the operator is inactive |
| `invalid_flag` | 422 | Unknown flag key |
| `cannot_deactivate_self` | 409 | An operator cannot deactivate themselves |
| `cannot_deactivate_last` | 409 | The last active operator stays — otherwise there would be no way back into the console |
| `not_found` | 404 | Unknown banner or unknown household |

KPIs, support search and the feedback inbox read aggregate views only and have no errors of their
own beyond auth.

---

## `tasks` (Phase 4)

| slug | HTTP | Meaning |
|---|---|---|
| `title_required` | 422 | Ad-hoc instance without a title (from a template it comes from the snapshot) |
| `invalid_state` | 409 | State machine: completing/assigning requires `open` |

---

## `economy` (Phase 4)

| slug | HTTP | Meaning |
|---|---|---|
| `insufficient_funds` | 422 | The ledger's coverage check — the balance does not carry the booking. The invariant "no negative balances" (KONZEPT §5.9) is enforced here, not just claimed |
| `invalid_amount` | 422 | Amount ≤ 0 where a positive amount is required, or 0 for an adjustment |
| `invalid_transfer` | 422 | Source == target, or a booking that must not exist |
| `reward_inactive` | 409 | The reward is switched off |
| `out_of_stock` | 409 | The reward is used up (`stock`) |
| `cooldown_active` | 409 | The reward has a cooldown that is still running |
| `thanks_cap_reached` | 422 | The weekly limit for thank-you points (per member, per ISO week) is reached |
| `invalid_state` | 409 | The redemption is not in the expected state |

---

## `marketplace` (Phase 4)

| slug | HTTP | Meaning |
|---|---|---|
| `not_your_task` | 403 | Only the assigned person can offer their task |
| `already_listed` | 409 | There is already an open listing for this instance |
| `not_seller` | 403 | Only the seller may withdraw |
| `invalid_state` | 409 | The listing is not in the expected state (open/accepted) |
| `invalid_transfer` | 422 | Accepting your own listing |
| `task_not_done` | 409 | Settling requires a completed task |
| `task_already_done` | 409 | Reversing a **fulfilled** task. A completed trade is settled, not reversed — otherwise the seller would get back the work **and** their points (11-B1). No endpoint reaches this path today; the guard is there for the escrow-expiry cron |

---

## `calendar` (Phase 5 + 9)

| slug | HTTP | Meaning |
|---|---|---|
| `not_owner` | 403 | Personal events are changed only by their owner |
| `invalid_rrule` | 422 | Recurrence rule cannot be interpreted |
| `invalid_tzid` | 422 | Unknown time zone |
| `invalid_range` | 422 | End before start, or a time window outside the allowed span |
| `not_a_series` | 422 | Series operation on a single event |
| `not_an_occurrence` | 422 | The given point in time is not an occurrence of the series |
| `occurrence_cancelled` | 422 | The occurrence is cancelled |
| `subscription_exists` | 409 | This CalDAV URL is already subscribed in the household |
| `external_event_read_only` | 409 | Mirrored external events are not changed locally |
| `external_field_readonly` | 422 | The write-back does not carry this field back; `extra.field` names it |
| `external_not_synced` | 409 | The event is not (yet) reconciled with the external server |
| `external_conflict` | 409 | The external server has changed the event in the meantime (ETag conflict) |
| `external_kind_unsupported` | 422 | The external server delivers an object type we do not mirror |
| `external_tzid_unsupported` | 422 | The external event's time zone cannot be resolved |
| `caldav_disabled` | 503 | Kill switch off — no outgoing sync |
| `caldav_write_failed` | 502 | The external server rejected the write-back; `extra.category` names the class |

---

## `scheduling` (Phase 5)

| slug | HTTP | Meaning |
|---|---|---|
| `invalid_hours` | 422 | Working/blocked hours cannot be interpreted |
| `invalid_range` | 422 | Invalid time window |

---

## `mealplanner` (Phase 6)

| slug | HTTP | Meaning |
|---|---|---|
| `no_candidate` | 404/422 | The automatic planner finds no dish within the constraints |
| `no_recipe` | 422 | The slot carries no recipe |
| `no_dish` | 422 | No dish planned for cooking |
| `no_prep` | 422 | No preparation task to create |

---

## `recipes` (Phase 2)

| slug | HTTP | Meaning |
|---|---|---|
| `import_no_recipe` | 422 | No recognisable recipe at the URL |

The other import errors (`import_url_blocked`, `import_fetch_failed`, `import_too_large`,
`import_too_many_redirects`) come from `kernel/fetch` and are listed under cross-cutting.

---

## `capture` — quick capture (Phase 4/7)

| slug | HTTP | Meaning |
|---|---|---|
| `invalid_state` | 409 | The entry is already confirmed or discarded |
| `no_target` | 409 | The suggestion names no target that could be created |

---

## `links` (Phase 7)

| slug | HTTP | Meaning |
|---|---|---|
| `invalid` | 422 | Link to itself, or an unknown object type |

---

## `vault` (Phase 7)

| slug | HTTP | Meaning | What the person can do |
|---|---|---|---|
| `vault_already_set_up` | 409 | The household already has a recovery envelope; `PUT /v1/vault/keys` with `kind=recovery` never replaces it. The server cannot check whether a second envelope carries the same household key (opaque) — replacing it would swap the key under all other members | **Join** the existing vault: enter the household's recovery code, set your own passphrase |
| `client_outdated` | 409 | A member's first passphrase envelope (`PUT /v1/vault/keys`, `kind=passphrase`) does not name the household's live recovery envelope in `wrap_meta.recovery_envelope_id`. Only an outdated client (old setup order) writes like this, and it would otherwise store a key nobody else in the household has. Nothing is stored | Reload the app (close and reopen the installed app, or "Reload" in the update notice), then try again |

---

## `wearables` (Phase 9)

| slug | HTTP | Meaning |
|---|---|---|
| `feature_disabled` | 403 | Household flag `wearables` off (default), only when connecting. **Reading and deleting stay open** — a switched-off flag must not lock anyone out of their own data |
| `connection_exists` | 409 | This member already has a connection |
| `crypto_unconfigured` | 503 | Without a server key no third-party tokens are stored. Deliberately **before** the redirect to the provider |
| `wearables_disabled` | 503 | Kill switch off or operator credentials missing → null adapter |
| `not_found` | 404 | Someone else's/unknown connection — **for admins too** (N-2: the answer does not even confirm that it exists) |

### Callback codes (not `problem+json`)

`GET /v1/wearables/oura/callback` answers a browser with a **302**, never with problem+json — a
top-level navigation cannot show an error body. The same causes travel as an `?error=` query to
`<public_base_url>/profile`. These are **not** slugs in the sense above and are therefore not
under the gate:

`denied` (the user declined at the provider) · `state_invalid` (unknown, expired, reused, or the
cookie belongs to another browser) · `exchange_failed` · `forbidden` (the role changed to `child`
within the callback window) · `crypto_unconfigured`.
Neither the token nor `code` nor `state` appears in the redirect target.

---

## Phase-8 endpoints (app side)

`/v1/feedback`, `/v1/banners`, `/v1/household/digest`, `/v1/notes/trash` + `/v1/notes/{id}/untrash`
use cross-cutting slugs only: `validation` (e.g. unknown feedback category), `forbidden` (not an
admin, or no active household on the digest toggle), `not_found` (e.g. `untrash` of a note that
is not in the trash).

---

## Demo mode

`CUSTODE_DEMO_MODE=on`, `app/demo.py`, [demo.md](demo.md). Only a public demo instance produces these; with the flag off they do not exist. The middleware
answers before routing, so the codes apply to every path in its list, whatever module owns it.

| slug | HTTP | Meaning |
|---|---|---|
| `demo_disabled` | 403 | The demo does not allow this action: sign-up, password reset, e-mail, invites, child accounts, membership changes, TOTP/passkeys/profile of the shared account, uploads, imports, ICS feeds, CalDAV, vault, Oura, weather lookups, feedback, live updates, operator console. The list is `BLOCKED` in `app/demo.py` |
| `demo_payload_too_large` | 413 | Request body over `CUSTODE_DEMO_MAX_BODY_BYTES` (default 256 KiB) |
| `demo_rate_limited` | 429 | More than `CUSTODE_DEMO_RATE_LIMIT` requests from one client address in one window; `Retry-After` says how long to wait |

---

## `feature_disabled` as cross-cutting

Today produced only by `wearables`. With flag enforcement (roadmap Phase 11) it becomes the slug
of **every** switched-off module — then it belongs under cross-cutting, not here.

---

## Rules

- Never stack traces to the outside; never content/PII in `detail`.
- **Every 5xx carries a `reference` code** — since 11-A2 the unexpected one too.
- Clients branch on `type`, never on `title`/`detail`. Both are display texts (English) and may
  change without breaking a client.
