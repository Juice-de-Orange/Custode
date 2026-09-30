# Security Policy

## Supported versions

Custode is developed on `main`; fixes land there. Please test against the latest commit before
reporting.

## Reporting a vulnerability

Please **do not** open a public issue, discussion or pull request for security problems.

Report privately through GitHub's private vulnerability reporting on this repository:
**Security → Report a vulnerability**. Include a description, the commit you tested, the affected
module and steps to reproduce.

You will receive an acknowledgement within **7 days**. A fix or workaround is aimed for within
**90 days** of triage, followed by a GitHub security advisory.

## Scope

In scope: tenant isolation (row-level security policies, the four database roles, the maintenance
and operator paths), authentication (passkeys, TOTP, child PIN, invite codes, session cookies and
CSRF, the operator console's bearer auth), the client-side encrypted vault and the server-side
credential encryption, SSRF guards around recipe import and CalDAV, GDPR export/erasure and purge
jobs, the sync batch endpoint, uploads, the production compose stack and the Caddy configuration.

Out of scope: the security of third-party services an operator connects (SMTP, Oura, CalDAV
servers, LLM endpoints), and any host outside the compose stack.

## Design notes for researchers

The threat model and the security concept are in `KONFIG/KONZEPT.md` §8 and
`KONFIG/ARCHITECTURE.md` (German); the English summary is `docs/ARCHITECTURE.md`. The error
catalogue (`docs/errors.md`) tells you what a response is supposed to disclose.
