# Dev and the tests log in through a dev realm

Status: Accepted (2026-10-18). Refines ADR 0018 (how dev and the tests reach a Viewer).

## Context

ADR 0018 puts the login realm behind a port, `oidc.Realm`, chosen by `viewers.realm()`:
`settings.BUNDESARCHIV_REALM` when set, else Keycloak. Its fake, `dev_realm.DevRealm`, signs its
own codes and tokens with `DEV_VIEWER_SIGNING_KEY`, a key production settings never define.

Before this ADR, `viewer_of` had two paths: the login's token cookies, and a `dev_viewer` cookie
that a dev-only switcher page set and the web tests signed directly. So production code carried a
second trust path that only dev used, dev never ran the real login, refresh or logout, and the
tests had two fakes for one boundary.

## Decision

- **One trust path.** `viewer_of` reads only the token cookies, checked by `realm()`. The
  `dev_viewer` cookie and its parser are gone from `src/`; such a cookie left in a browser names
  nobody.
- **Dev logs in through the dev realm.** `settings_dev` names the `DevRealm` in
  `BUNDESARCHIV_REALM` by dotted path (settings may not import `app`; `realm()` builds it), and
  sets a dev `VIEWER_SIGNING_KEY` (an environment value wins). A login in dev runs the real flow:
  `/login` → the dev realm's login page `/_dev/viewer/` → `/oidc/callback` → the token
  cookies. Logging out is the header's logout. A dev access token lives 60 seconds, so dev runs
  the server-side refresh every minute, as production does when Keycloak's token expires; a dev
  refresh token lives 30 days, the realm's offline session idle limit.
- **The login page answers only this site's callback.** `/_dev/viewer/` takes the authorize
  request's `state`, `nonce` and `redirect_uri`, lets the developer choose an Archivist (with a
  username) or a Member (with groups), and redirects to `redirect_uri` with a code bound to the
  nonce. A `redirect_uri` other than this site's own `oidc-callback` URL, exactly, is the plain
  404: the page is no open redirect. A GET without a login (a bookmark) starts one.
- **The tests log in the same way.** One mapping, `dev_realm.claims_of(viewer)`, turns an
  Archivist or a Member into Keycloak-shaped claims; `viewer_from_claims` reads them back as the
  same viewer. `client_as(viewer)`, the browser suites and the dev page all mint through it.
  `Public` is no login: no tokens.
- **The login cookies follow the https switch.** The access, refresh and login-state cookies are
  named in one place, `viewers.login_cookies()`, keyed on `CSRF_COOKIE_SECURE`, the repo's one
  "this site serves https" switch: on (production, the web tests) they are `__Host-` names with
  Secure (ADR 0018: no sibling host may shadow them); off (dev, the browser suites) they are
  `bundesarchiv_` names without Secure: WebKit drops a Secure cookie set over http, even on
  localhost (probed 2026-10-18), and browsers do not separate cookies by port, so a bare `access`
  would clash with another localhost app's, and a refresh failure here would delete it.
- **A whitespace-only username folds to `Archivist()`**, as Keycloak's would: the claims mapping
  treats a blank `preferred_username` as absent, where the old dev cookie kept it verbatim.

With the anonymous gate on in dev, the loop is `/login` → `/_dev/viewer/` → the gate → the door,
as it was with the old switcher.

## Consequences

- Production code has one request→Viewer path; dev and every web test exercise it.
- The production WSGI entry still refuses to serve with `BUNDESARCHIV_REALM` set (ADR 0018), and
  production settings define neither the realm nor its key.
- A web test that logs in without the test settings fails loudly: minting needs the dev key.

## Considered options

- **An in-process fake OIDC issuer** (discovery document, JWKS, signed JWTs) behind the Keycloak
  adapter. Rejected: much more code for the same proof, and ADR 0018 already keeps the Keycloak
  adapter's own tests on real signed test tokens.
- **Keep the dev cookie beside the tokens.** Rejected: a second trust path in production code that
  only dev uses.
- **Switch the cookie names on `DEBUG`.** Rejected: `CSRF_COOKIE_SECURE` already states whether
  the site serves https, and the browser suites run with `DEBUG` off over http.
