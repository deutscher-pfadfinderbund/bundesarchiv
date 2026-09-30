# Authentication: Keycloak OIDC, tokens held by the browser

**Status.** Built 2026-08-30: OIDC login that minted one signed Viewer cookie.
Reworked 2026-09-26 (owner): an OIDC login keeps Keycloak's tokens in the
browser and the server refreshes them; built 2026-09-26. The signed Viewer
cookie was removed 2026-09-29 (owner). The second login path is **capability
links** (deferred, issue #58); they supersede the app-local guest passwords
this ADR first specified (owner, 2026-08) and choose their session mechanism
when built. The file name keeps the old title for link stability.

## Context

The first design turned a login into one signed Viewer cookie: 30 days for a
Member, 48 hours for an Archivist. Two gaps followed from it:

- **Changes in Keycloak arrived late.** A person removed from a group, demoted,
  or disabled kept the cookie's rights until it expired: up to 30 days.
- **Logout needed a confirmation.** The app kept no ID token, so the
  end-session redirect carried no `id_token_hint`, and Keycloak asked the user
  to confirm. An unconfirmed logout left the Keycloak session alive, and on a
  shared computer the next person was signed back in as the last one.

"No stored tokens" meant: the server stores none (owner, 2026-09-26). Tokens
held by the browser are within that rule.

## Decision

Personal DPB accounts log in via **OpenID Connect against the DPB Keycloak
realm** (authorization-code flow, confidential client `bundesarchiv`,
**authlib**'s httpx client).

- **The browser holds the tokens.** After the callback, Keycloak's access
  token and its **offline** refresh token (scope `openid profile
  offline_access`) go into two cookies: `HttpOnly`, `Secure`, `SameSite=Lax`.
  The server stores no token, no session, no user row.
- **Every request checks the access token.** The signature against the realm's
  keys, the algorithm pinned to `RS256`, `iss` equal to the configured issuer,
  `aud` containing `bundesarchiv`, and `exp`. The realm is shared with other DPB
  apps and signs their tokens with the same keys, so a check without `aud` would
  accept another app's token. The claims then pass through the existing pure
  claims→Viewer mapping.
- **The server refreshes.** A request whose access token has expired uses the
  refresh cookie at Keycloak's token endpoint, sets both cookies anew on the
  response, and resolves the Viewer from the new token. A failed refresh, and
  any token that fails a check, resolves to `Public`.
- **Keycloak's changes take effect at the next refresh**, bounded by the realm's
  access token lifespan (1 min on 2026-09-26). This covers a lost group, a lost
  `Bundesarchiv` role, and a disabled account.
- **A login lasts 30 days without use**, for Members and Archivists alike
  (owner, 2026-09-26). The limit is the realm's offline session idle (30 days,
  no maximum, on 2026-09-26), not a cookie lifetime of ours.
- `BUNDESARCHIV_VIEWER_SIGNING_KEY` signs the transient `state`/`nonce`
  cookie across the login redirect.

Why the server refreshes and not the browser:

- To refresh, a script must read the refresh token, so it could not be
  `HttpOnly`, and one XSS would steal a 30-day offline token.
- Links, form posts, images and media requests carry no `Authorization` header,
  so the server needs the token in a cookie anyway.
- The first request after a pause always arrives with an expired access token;
  the server must handle that case in any design.

## Realm contract

External configuration the app depends on. A change to any of it is a change
to this ADR.

- **Role scope of `bundesarchiv`:** only the realm roles `Bundesarchiv` and
  `offline_access`. The access token sits in a cookie, so it must carry no role
  the app does not read.
- **Mappers in `bundesarchiv-dedicated`:** an audience mapper for
  `bundesarchiv`; `realm_access.roles`; a Group Membership mapper, claim
  `groups`; all into the access token.
- **`offline_access`** is an optional client scope of `bundesarchiv` and a
  default realm role.
- **Refresh token rotation ("Revoke Refresh Token") stays off.** Two requests
  that refresh at once (two tabs, parallel htmx requests) then both succeed.
  With rotation on, the second would fail and sign the user out. The upload
  gate (ADR 0017) refreshes in its own subrequest, whose new cookies nginx
  drops, so the upload refreshes again with the same token: if rotation is ever
  turned on, the gate must not refresh.
- **Group names are an external contract.** An article audience naming a group
  nobody carries matches nobody (fail-closed). No sync or validation against
  Keycloak.

## Claims contract

| Login | Source (access token) | Viewer |
|---|---|---|
| OIDC, realm role `Bundesarchiv` | `realm_access.roles`, `preferred_username` | `Archivist(username)`, `unbekannt` when absent (ADR 0019) |
| OIDC, any other realm user | `groups` | `Member(groups=…)`, `()` when absent |
| Capability link (deferred) | the link's token | `Member(groups=<token>)` |
| none / invalid / refresh failed | — | `Public` |

`Archivist` and `Member` stay inert value objects.

Consequences accepted deliberately:

- **The access-token cookie is readable by whoever holds it.** It carries the
  username and the name from the `profile` scope (the `email` scope is optional
  and not requested). `HttpOnly` keeps it from scripts.
- **A forgotten logout on a shared computer** leaves a 30-day login, an
  Archivist's included (owner, 2026-09-26).
- **Each active user causes one refresh call per access token lifespan.**
  Keycloak runs on the same server; its outage takes the app down with it and
  is not a failure mode of its own (owner, 2026-09-26).
- **Emergency revocation happens in Keycloak:** disable the user or revoke
  their offline session, and the next refresh fails. Rotating
  `BUNDESARCHIV_VIEWER_SIGNING_KEY` no longer signs anybody out of an OIDC login.

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

Shared computers (group rooms, archive workstations) are the normal case, so a
logout ends the Keycloak session as well as ours:

1. Refresh once, for a current ID token.
2. Revoke the offline token at the realm's `revocation_endpoint`.
3. Redirect to the `end_session_endpoint` with that `id_token_hint`, so Keycloak
   ends its browser session without asking.
4. Delete both token cookies.

Logout is the one route here that does **not** fail closed: when a Keycloak
step fails, the cookies still go, because refusing to sign somebody out is not
a safe failure. The sign-out is offered to every signed-in viewer, Member
included.

Verified against the real realm on 2026-09-26 (Keycloak 26.5.2, local run):

- Keycloak's token preview: the access token carries `aud` `bundesarchiv`, only
  the role-scope roles, `groups` and `preferred_username`.
- Login sets the two token cookies and no Viewer cookie. Sizes: access token
  1.3 kB, refresh token 0.7 kB.
- After more than one minute idle, the next click carries a new access token.
- Logout shows no confirmation page, removes both cookies, and leaves no
  Keycloak session (offline included); the next login asks for the password.

Not run: two tabs refreshing at once.

There is no Abmelden landing page (owner, 2026-08-29): a logout lands on the
workbench as an anonymous visitor, which the gate turns into the login screen.

The same two pieces compose into a later **kiosk mode**: an archivist-only
action that ends their SSO session and mints a long-lived cookie for a
password-less, `kiosk`-flagged link entry (the public reading device inside an
archive room). Designed-for, not built now.

## Testing

Ours to test is small and server-free:

- The claims→Viewer mapping is a pure function over a dict.
- The token check: an expired, tampered, wrong-algorithm, wrong-issuer or
  wrong-audience token resolves to `Public`. Tokens signed with a test key.
- The views, the refresh and the logout run through a thin injected port with
  an in-memory fake, the pattern the mirror tests use instead of live WebDAV.

The declarative authlib lines behind the port are not suite-tested: the
realistic failure is Keycloak *client misconfiguration* (a missing mapper, a
wrong redirect URI), which no fake can catch because it would encode our own
assumptions. That is a deploy-runbook smoke step: one real login per realm
change.

## Considered options

- **The browser refreshes its own token** (a public client, script-driven
  refresh): see "Why the server refreshes" above.
- **The signed Viewer cookie, re-minted at a shorter lifetime:** closes the
  group gap only by forcing re-logins, and leaves logout without an
  `id_token_hint`.
- **Hand-rolled OIDC or JWT checks on httpx** (ADR 0007 precedent): auth is
  where an unmaintained bug is most expensive; authlib provides state, nonce,
  PKCE, JWKS, issuer and algorithm checks as its whole job.
- **mozilla-django-oidc / django-allauth**: require `contrib.auth` and
  SessionMiddleware, a parallel identity system this app does not have.
- **oauth2-proxy in front of the app**: authorizes on trusted-header contracts
  (a misconfiguration foot-gun) and would have to let capability links past
  it.
- **Guest accounts inside Keycloak**: brute-force lockout locks out a whole
  group, and a cross-site auto-login link cannot carry a password safely.
- **Sessions in Postgres**: a second identity system alongside `Viewer`. Not an
  ephemerality argument: Postgres may hold admin data (owner, 2026-08-30).

## Deferred (deliberately, with the door open)

Capability links (issue #58: an HMAC-signed short-expiry link that lands the
reader in content with no prompt, per the 2026-08 access-model ruling; the
session mechanism is chosen when built); kiosk mode; per-item links; a
true internet-public tier for curated exhibitions (the dormant `PUBLIC`
audience rung stays reserved for it).
