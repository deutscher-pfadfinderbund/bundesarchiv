# Authentication: Keycloak OIDC + app-local guest passwords, one signed Viewer cookie

Two login paths, one trust artifact. Personal DPB accounts authenticate via
**OpenID Connect against the existing DPB Keycloak realm** (authorization-code
flow, implemented with **authlib**'s httpx client). Visitors without a
personal account authenticate via **app-local shared guest passwords** (a
settings-pointed file of `label → scrypt hash + groups` entries; stdlib
`hashlib.scrypt`, no new dependency; rotation = edit file + restart). Both
paths end the same way: the app mints the **signed Viewer cookie** that
`viewer_of` already resolves fail-closed — tampered, expired, or absent
collapses to `Public`, exactly as today.

There are **no Django sessions, no `django.contrib.auth`, and no stored
tokens**. The index Postgres is disposable (ADR 0003), so login state may not
live there; the domain authorizes via `Viewer`, so a `User` model would be a
second identity system ending in the same mapping. OIDC is used purely as an
authentication event: callback → validated claims → cookie. The transient
`state`/`nonce` ride a short-lived signed cookie across the redirect.

## Claims contract

| Login | Source | Viewer | Cookie lifetime |
|---|---|---|---|
| OIDC, realm role `Bundesarchiv` | `realm_access.roles` (roles client-scope mapped into the token) | `Archivist` | 48h |
| OIDC, any other realm user | authentication itself | `Member(groups=())` — Keycloak groups unused for now | 30d |
| Guest password | config entry | `Member(groups=<entry>)`, e.g. `("Orden St. Georg",)` | 90d |
| none / invalid | — | `Public` | — |

The cookie additionally carries `preferred_username` (or the guest label) for
request logging and future audit — it never enters domain objects; `Archivist`
and `Member` stay inert value objects.

Consequences accepted deliberately:

- **No server-side revocation.** A minted cookie is valid until expiry; a
  demoted archivist keeps power for at most 48h. Emergency invalidation =
  bump the cookie format version. Guest revocation = rotate the password.
- **Group names are an external contract.** An article audience naming a
  group nobody carries simply matches nobody (fail-closed, unchanged domain
  semantics). No sync or validation against Keycloak.

## Unauthenticated requests: uniform redirect, then the 404 law

Anonymous requests get a **302 to the login screen, byte-identical across all
content routes** — `/artikel/<real>` and `/artikel/<garbage>` redirect
identically, so existence is still only answerable after authentication. The
`?next=` return target is validated against a same-origin path whitelist. For
every authenticated tier the byte-identical-404 law (ADR 0001, 0012) applies
unchanged. The route × tier leak matrix gains this as a tested contract: an
anonymous row asserting redirect uniformity, guest-tier rows, cookie-tamper
rows.

## Logout

Both layers from day one, because shared computers (group rooms, archive
workstations) are the normal case:

- Local: delete the Viewer cookie (guests and OIDC users).
- OIDC users additionally redirect through Keycloak's
  `end_session_endpoint` — otherwise the still-alive SSO session silently
  re-logs the previous person in on the next click.

The same two pieces compose into a later **kiosk mode**: an archivist-only
action that ends their SSO session and mints a long-lived cookie for a
password-less, `kiosk`-flagged guest entry (the public reading device inside
an archive room). Designed-for, not built now.

## Testing

Ours to test is small and server-free: the claims→Viewer mapping is a pure
function over a dict; the callback view is tested through a thin injected
port (`fetch_claims`) with an in-memory fake — the same port-injection
pattern the mirror tests use instead of live WebDAV. The ~10 declarative
authlib lines behind the seam are not suite-tested: the realistic failure is
Keycloak *client misconfiguration* (missing roles mapper, wrong redirect
URI), which no stub or fake can catch because it would encode our own
assumptions. That is a deploy-runbook smoke step: one real login per realm
change.

## Considered options

- **Hand-rolled OIDC on httpx** (ADR 0007 precedent): the flow is small, but
  auth is where an unmaintained bug is most expensive; authlib provides
  state/nonce/PKCE/JWKS/issuer validation as its whole job. The dependency
  diet yields here.
- **mozilla-django-oidc / django-allauth**: require `contrib.auth` +
  SessionMiddleware — a parallel identity system this app deliberately does
  not have.
- **oauth2-proxy in front of the app**: moves the flow out of Python, but
  authorizes on trusted-header contracts (a misconfiguration foot-gun) and
  mixes poorly with the guest-cookie path, which would need auth-bypass rules
  through the proxy.
- **Guest accounts inside Keycloak**: shared accounts fight the tool —
  brute-force lockout locks out a whole group, and a cross-site auto-login
  link still cannot carry a password safely.
- **Sessions in Postgres**: logins would vanish whenever the disposable
  index is rebuilt.

## Deferred (deliberately, with the door open)

Link-only guest onboarding (website issues an HMAC-signed short-expiry link
that mints the guest cookie — no coupling built yet); Keycloak group claims
feeding `Member.groups`; kiosk mode; a true internet-public tier for curated
exhibitions (the dormant `PUBLIC` audience rung stays reserved for it).
