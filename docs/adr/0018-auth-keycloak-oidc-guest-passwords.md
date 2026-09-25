# Authentication: Keycloak OIDC, one signed Viewer cookie

**Status (2026-08-30): the OIDC path is built** — deployment 1 has real login.
The second login path is **capability links** (designed, deferred); they
supersede the app-local guest passwords this ADR originally specified (owner,
2026-08). The file name keeps the old title for link stability.

Personal DPB accounts authenticate via **OpenID Connect against the existing DPB
Keycloak realm** (authorization-code flow, implemented with **authlib**'s httpx
client). Visitors without a personal account will authenticate via a
**capability link** whose token mints the same cookie (revocation = revoke the
token). Both paths end the same way: the app mints the **signed Viewer cookie**
that `viewer_of` resolves fail-closed — tampered, expired, or absent collapses
to `Public`, exactly as before.

There are **no Django sessions, no `django.contrib.auth`, and no stored
tokens**. The domain authorizes via `Viewer`, so a `User` model would be a
second identity system ending in the same mapping. OIDC is used purely as an
authentication event: callback → validated claims → cookie. The transient
`state`/`nonce` ride a short-lived signed cookie across the redirect.

## What is built

| Piece | Module |
|---|---|
| Claims → `Viewer`, a pure function | `app/web/oidc.py` |
| Mint and verify the cookie | `app/web/viewers.py` (`mint_viewer_cookie`, `viewer_of`) |
| `GET /login`, `GET /oidc/callback`, `POST /logout` | `app/web/auth_views.py` |
| The realm adapter — the only authlib/httpx lines | `app/web/keycloak.py` |
| The anonymous gate, one middleware | `app/web/anonymous_gate.py` |
| Settings and the deploy checklist | `index/settings.py`, `docs/runbook.md` |

Not built, deliberately: capability links, Keycloak group mapping beyond the
forward-compatible `groups` parse, kiosk mode, the audit trail.

## Claims contract

| Login | Source | Viewer | Cookie lifetime |
|---|---|---|---|
| OIDC, realm role `Bundesarchiv` | `realm_access.roles` (roles client-scope mapped into the ID token) + `preferred_username` (profile client scope, ID token) | `Archivist(username)`, `unbekannt` when absent (ADR 0019) | 48h |
| OIDC, any other realm user | authentication itself, plus a `groups` claim when the realm maps one | `Member(groups=…)`, `()` when absent | 30d |
| Capability link (deferred) | the link's token | `Member(groups=<token>)` | the token's own expiry |
| none / invalid | — | `Public` | — |

Both lifetimes are enforced **on read**, not merely offered to the browser: an
archivist cookie past 48h resolves to `Public` even though the member window has
not run out.

The cookie carries the format version and the encoded viewer. Since format `v2`
(2026-09-25) an archivist's viewer includes the Keycloak username, the
`changed_by` of ADR 0019. The cookie is signed, not encrypted: whoever holds it
can read that name. A Member's cookie carries no name. `Archivist` and `Member`
stay inert value objects.

Consequences accepted deliberately:

- **No server-side revocation.** A minted cookie is valid until expiry; a
  demoted archivist keeps power for at most 48h. Emergency invalidation = bump
  the cookie format version (`_VIEWER_FORMAT_VERSION`), which invalidates every
  outstanding cookie at once. Capability-link revocation = revoke the token.
- **Group names are an external contract.** An article audience naming a group
  nobody carries simply matches nobody (fail-closed, unchanged domain
  semantics). No sync or validation against Keycloak.

## Unauthenticated requests: the anonymous gate

Anonymous requests are not answered. One middleware — not a per-view decorator —
redirects them to `/login?next=<current path>`, and it is blind to path, method
and would-be status: a real article, a made-up one and a route that does not
exist all get the same 302. Existence is therefore still only answerable after
authentication, but without the byte-uniformity contract this ADR first
demanded — that fell with the owner's 404 relaxation (2026-08). Status
assertions remain, as leak-matrix rows.

The `?next=` return target is validated against a whitelist of *shape*: it must
be a local path, never a scheme-relative `//host` or its backslash variants, and
free of control characters. Exempt from the gate: the three auth routes and
static files.

An htmx request gets that same bounce as an `HX-Redirect` header instead of a
302: an XHR cannot follow a redirect to a cross-origin login, so a request whose
cookie has just expired would swap nothing and the control would look dead. For
the same reason — a dead end is worse than a detour — a callback whose *verified*
transient carries a different `state` (two tabs, one cookie) restarts the login
rather than answering the shared 404.

The gate is **on in the base settings and disabled only in `settings_dev`** —
the fail-closed direction. A production deploy that forgets its OIDC env vars
cannot fall open to anonymous browsing; it redirects to a login that itself
falls closed. Dev and the browser suites keep anonymous = `Public` and the dev
viewer-switcher.

## Logout

Both layers from day one, because shared computers (group rooms, archive
workstations) are the normal case:

- Local: delete the Viewer cookie.
- OIDC users additionally redirect through Keycloak's `end_session_endpoint` —
  otherwise the still-alive SSO session silently re-logs the previous person in
  on the next click.

The sign-out is offered to every signed-in viewer, Member included — it is not
archivist chrome. A Member's cookie is the longer-lived of the two tiers, so the
tier with the most to leave behind on a shared machine must be the one that can
end it.

**Open point.** Because the app stores no tokens, the end-session redirect
carries no `id_token_hint`, and Keycloak then asks the user to *confirm* the
logout instead of ending the session. An unconfirmed logout leaves the SSO
session alive while the local cookie is already gone — the next person is signed
back in as the last one. Closing it means keeping the ID token somewhere, i.e.
reopening "no stored tokens"; that is an owner decision, not one taken here.
Until then it is a documented smoke step (runbook, step 4).

There is no Abmelden landing page (owner, 2026-08-29): a logout lands on the
workbench as an anonymous visitor, which the gate turns into the login screen.
Logout is also the one route here that does **not** fail closed — with no realm
to return through, the local cookie still goes, because refusing to sign
somebody out is not a safe failure.

The same two pieces compose into a later **kiosk mode**: an archivist-only
action that ends their SSO session and mints a long-lived cookie for a
password-less, `kiosk`-flagged link entry (the public reading device inside an
archive room). Designed-for, not built now.

## Testing

Ours to test is small and server-free: the claims→Viewer mapping is a pure
function over a dict; the views are tested through a thin injected port
(`fetch_claims` and its two siblings) with an in-memory fake — the same
port-injection pattern the mirror tests use instead of live WebDAV. The ~10
declarative authlib lines behind the seam are not suite-tested: the realistic
failure is Keycloak *client misconfiguration* (missing roles mapper, wrong
redirect URI), which no stub or fake can catch because it would encode our own
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
  mixes poorly with the second, link-minted cookie path, which would need
  auth-bypass rules through the proxy.
- **Guest accounts inside Keycloak**: shared accounts fight the tool —
  brute-force lockout locks out a whole group, and a cross-site auto-login
  link still cannot carry a password safely.
- **Sessions in Postgres**: a session table is a second identity system
  alongside `Viewer` — the same objection as `contrib.auth`, and the reason
  that stands. *Not* an ephemerality argument: the owner ruled on 2026-08-30
  that Postgres may hold admin data (only the archive files must survive total
  loss). The cookie won on simplicity — no table, no migration, no cleanup job,
  no per-request query — not because the database would forget.

## Deferred (deliberately, with the door open)

Capability links (an HMAC-signed short-expiry link that mints the cookie, per
the 2026-08 access-model ruling); Keycloak group claims feeding `Member.groups`
— the parse exists, the realm mapper is the missing half; kiosk mode; per-item
links; an audit trail; a true internet-public tier for curated exhibitions (the
dormant `PUBLIC` audience rung stays reserved for it).
