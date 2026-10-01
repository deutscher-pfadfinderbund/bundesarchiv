# Operations runbook

Production/operations detail that does not belong in the quick-start README.
Settings are env vars read by `bundesarchiv/index/settings.py`.

## Deploy

Komodo on the VPS runs `compose.yml` as the Stack `bundesarchiv`. It deploys
from its own checkout of this repository, so the data the repository must never
hold lives in a folder of its own:

```
/home/admin/bundesarchiv/
  canonical/                  THE ARCHIVE. Losing this loses everything.
  thumbnails/                 derived WebP cache, prunable
  pgdata/                     Postgres data: the search index and the job queue
```

Komodo owns its checkout and may re-clone it, so nothing in it may be data.
`compose.yml` names these three folders by absolute path.

Traefik in front terminates TLS and routes
`archiv.deutscher-pfadfinderbund.de` to the `nginx` service over the existing
external `web` network.

### First bring-up

Create the data folders:

```sh
sudo mkdir -p /home/admin/bundesarchiv/{canonical,thumbnails,pgdata}
sudo chown -R 1000:1000 /home/admin/bundesarchiv/canonical /home/admin/bundesarchiv/thumbnails
```

The app runs as uid 1000 inside the image, which is why the two writable mounts
must belong to that id. `pgdata` belongs to Postgres and needs no chown:
Postgres creates and owns its own `18/docker` subfolder inside it.

Then create the Stack in Komodo:

| Setting | Value |
| --- | --- |
| Name | `bundesarchiv` (the compose project, so containers are `bundesarchiv-app-1` etc.) |
| Source | git repo `deutscher-pfadfinderbund/bundesarchiv`, branch `main` |
| File paths | `compose.yml` |
| Environment | `deploy/production.env.example`, filled in (below) |
| Env file path | `production.env` |
| Auto update | on |

Komodo writes the environment as `production.env` next to `compose.yml` and
passes it to compose as `--env-file`. Compose needs both: the `env_file:` lines
hand it to app and worker, and the flag feeds the three `POSTGRES_*` values
`compose.yml` substitutes.

Deploy. The app container migrates the database, checks the index and then
serves; a failure to start is in the app's log and names what it missed.
Without `BUNDESARCHIV_SECRET_KEY` or `BUNDESARCHIV_ALLOWED_HOSTS` it refuses to
serve at all, by design.

### Filling the environment

`deploy/production.env.example` lists every variable with what it is for. Keep
the secrets in Komodo Secrets and reference them from the environment. Three
need thought:

- `BUNDESARCHIV_SECRET_KEY` and `BUNDESARCHIV_VIEWER_SIGNING_KEY` are two
  DIFFERENT secrets. Generate each with
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
- `BUNDESARCHIV_PG_DSN` carries the same password as `POSTGRES_PASSWORD`. The
  host is `postgres`, the compose service — Postgres publishes no port.
- `BUNDESARCHIV_MIRROR_DAV_URL` must point at a folder the app owns alone. The
  reconcile deletes everything under it that is not in canonical.

### Updating and rolling back

Komodo's "Global Auto Update" Procedure (daily at 03:00 unless its schedule
says otherwise) pulls `:latest` for `app` and `worker` and redeploys when the
image changed. So a push to `main` that passes CI is the deployment —
`.github/workflows/app-image.yml` publishes the image only after CI has gone
green on that commit.

A change to `compose.yml` or `deploy/nginx/nginx.conf` reaches the VPS only on a
Deploy of the Stack, which pulls the checkout first.

To roll back, pin the last good image instead of `:latest` in `compose.yml` —
both `app` and `worker` to `ghcr.io/…/bundesarchiv:sha-<sha>` — and deploy.
A pinned tag never has a newer image, so it stays pinned until someone un-pins
it. Pin rather than retag: the tag then says which commit is running.

### Backup

The owner's rsync copies `/home/admin/`. Exclude the two folders that are
derived and large:

```
bundesarchiv/pgdata
bundesarchiv/thumbnails
```

`canonical/` is the archive and must be in every backup. `pgdata` holds the
search index (rebuildable) and the job queue; a restore that loses it costs a
reindex, not data.

### Importing a canonical tree

Copy the tree into `canonical/` (keeping its own layout), fix ownership, then
rebuild the index:

```sh
sudo rsync -a /path/to/import/ /home/admin/bundesarchiv/canonical/
sudo chown -R 1000:1000 /home/admin/bundesarchiv/canonical
docker exec bundesarchiv-worker-1 python manage.py procrastinate defer full_rebuild
```

The hourly reconcile would find it too; the defer just does not wait.
`ensure_index_current` is NOT the command for this — it only reacts to a
changed FTS config version, and an empty index is not stale.

### Smoke after bring-up

1. Postgres writes into the folder this stack backs up, once, on the first
   bring-up:

   ```sh
   docker exec bundesarchiv-postgres-1 psql -U postgres -tAc "show data_directory"
   ```

   Expect `/var/lib/postgresql/18/docker`, and `ls /home/admin/bundesarchiv/pgdata/18/docker`
   showing the cluster. An empty `pgdata/` means the bind mount misses the data
   directory and the cluster lives in an anonymous volume nobody backs up.
2. The login walk, once per realm change: "Smoke test: one real login per realm
   change" below.
3. Range requests through nginx, on a large PDF. Copy the `__Host-access`
   and `__Host-refresh` cookies out of a logged-in browser (the refresh cookie
   covers an access token that expires mid-test):

   ```sh
   curl -r 0-99 -I -H 'Cookie: __Host-access=<a>; __Host-refresh=<r>' \
     https://archiv.deutscher-pfadfinderbund.de/media/<article-ulid>/<content-hash>
   ```

   Expect `206`, a `Content-Range: bytes 0-99/<size>`, and
   `Cache-Control: private, …`. A `200` with the whole file means the
   X-Accel-Redirect handoff is not happening — check
   `BUNDESARCHIV_X_ACCEL_PREFIX` against the `/_media/` media-key location in
   `deploy/nginx/nginx.conf`. A public `Cache-Control` means that location grew
   an `expires` or a `Cache-Control` header it must not have (ADR 0017).
   An anonymous upload POST to `/articles/<ulid>/media/upload` gets an
   immediate empty `404`, before any body is read. So does the same POST with
   the two cookies and `-H 'Origin: https://example.org'`.

## Authentication (Keycloak OIDC) — ADR 0018

Login is OIDC against the DPB Keycloak realm. The browser keeps Keycloak's
access token and offline refresh token in two cookies; the server stores no
token, no session, no user table. Every setting is optional in code and falls
closed: with any of them missing nobody can log in, and the anonymous gate turns
every request into a redirect to a login that answers 404. A half-configured
deploy authenticates nobody — it never falls open.

**Serve over HTTPS.** The cookies are `Secure`. Over plain http the login
appears to succeed and the very next request is anonymous again.

- `BUNDESARCHIV_VIEWER_SIGNING_KEY` — signs the transient login cookie.
  Generate one per deployment:
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`. Never
  `SECRET_KEY`, never the dev key. **Rotation = replace it and restart.** It
  does not sign anybody out of an OIDC login.
- `BUNDESARCHIV_OIDC_ISSUER` — `https://auth.deutscher-pfadfinderbund.de/realms/master`.
  It must equal the `iss` in the tokens exactly; the app reads
  `<issuer>/.well-known/openid-configuration` once per process and keeps it, so
  a re-pointed issuer needs a restart. A discovery fetch that FAILS is never
  kept: a realm that was restarting during one login is retried at the next,
  not remembered for the life of the process.
- `BUNDESARCHIV_OIDC_CLIENT_ID` / `BUNDESARCHIV_OIDC_CLIENT_SECRET` — the
  confidential client `bundesarchiv` and its secret.

The anonymous gate itself is a settings constant, on in production and off only
in `settings_dev` — deliberately not env-tunable.

**Emergency revocation of a person:** in Keycloak, disable the user or revoke
their offline session for `bundesarchiv`. The next refresh fails, at the latest
after the realm's access token lifespan (1 minute).

### Keycloak client checklist

- Client `bundesarchiv`: **client authentication on** (confidential), standard
  flow on, direct access grants off, service accounts off.
- **Valid redirect URI: exactly `https://<host>/oidc/callback`** — no wildcard.
  The app sends this URI in both the authorize and the token request; a
  mismatch is a refused login.
- Valid post-logout redirect URI: `https://<host>/`.
- **Role scope:** Client scopes → `bundesarchiv-dedicated` → Scope: only the
  realm roles `Bundesarchiv` and `offline_access`, "Full scope allowed" off. The
  access token sits in a cookie and carries no role the app does not read.
- Realm role **`Bundesarchiv`** exists and is assigned to the archivists.
  Renaming it in Keycloak revokes archivist access here (`ARCHIVIST_REALM_ROLE`
  in `app/web/oidc.py`).
- **Mappers in `bundesarchiv-dedicated`, each "Add to access token" on:**
  - realm roles → `realm_access.roles`. Without it every archivist logs in as a
    plain Member.
  - **Audience** (Add mapper → By configuration → Audience), Included Client
    Audience `bundesarchiv`. Without it every token check fails and nobody can
    log in.
  - **Group Membership**, claim `groups`.
- Client scopes: `profile` default (it carries `preferred_username`, the name
  each saved version records, ADR 0019; without it every archivist logs in as
  `unbekannt`), `email` optional, `offline_access` optional.
- Realm: "Revoke Refresh Token" off (two parallel refreshes must both succeed);
  offline session idle 30 days.
- Requested scope is `openid profile offline_access`.
- Check: Client scopes → Evaluate → a user → Generated access token. `aud`
  contains `bundesarchiv`, `realm_access.roles` holds at most the two roles,
  `groups` and `preferred_username` are present.

### Smoke test: one real login per realm change

Run after any change to the client, the mappers, the secret or the issuer. The
suite cannot replace it: it runs against an in-memory realm, which can only
encode our own assumptions (ADR 0018, "Testing").

1. Open `https://<host>/` in a fresh private window → Keycloak's login screen.
2. Log in as an **archivist** → the workbench, with "+ Neu …" in the header. A
   missing create menu means the login worked and the roles mapper did not.
3. Log in as a **non-archivist** → the workbench without "+ Neu …" but WITH
   "Abmelden": the sign-out belongs to everyone who is signed in.
4. Stay idle longer than 1 minute, then click anything → still signed in (the
   server refreshed the access token).
5. **Abmelden** → no Keycloak confirmation page, back at the login screen; going
   back in the browser must not restore the session, and the next login asks
   for the password.

A login lasts 30 days without use — the realm's offline session idle — for
Members and Archivists alike.

## Search index (Postgres)

The index is **derived and disposable** — canonical truth is the files store
(`BUNDESARCHIV_CANONICAL_ROOT`); `full_rebuild` recreates the index from it at any
time. The **database is not** the index: it also holds the worker's job tables,
and later admin data nothing can rebuild from the files (ADR 0003, update
2026-08-30). Rebuild the index; drop the database only in an emergency.
Postgres 18 with the German Hunspell dictionary baked in
(`docker/postgres/`). `compose.yml` is the VPS deploy stack ("Deploy" below);
local dev uses Apple's `container` CLI (README).

The VPS pulls `ghcr.io/deutscher-pfadfinderbund/bundesarchiv-postgres:latest`,
published by `.github/workflows/postgres-image.yml` from `docker/postgres/`.
Local dev builds that same Dockerfile itself with the `container` CLI.

- `BUNDESARCHIV_PG_DSN` — connection string (default
  `postgresql://postgres:postgres@localhost:5434/bundesarchiv`).
- DB-backed tests require a running Postgres and **fail** (not skip) if
  unreachable. They carry the `requires_pg` marker, derived from their fixture
  closure by `tests/conftest.py`; `mise run test:nodb` runs the DB-free rest for
  domain-only work.

## Background worker (Procrastinate) — ADR 0014

Postgres-backed worker: no broker, jobs live in Postgres tables applied by
`migrate`. Web write paths update the index synchronously; the worker is the
retry net for failed synchronous updates, plus the scheduled reconciles and
thumbnail generation. Run exactly ONE app process and one worker (ADR 0013
single-app-process rule).

```sh
uv run manage.py ensure_index_current   # deploy + worker startup: rebuild if config_version drifted
uv run manage.py procrastinate worker   # run the worker (single process)
```

- `BUNDESARCHIV_CANONICAL_ROOT` — the canonical files store worker jobs re-read
  truth from (jobs carry only references, never payloads).
- `BUNDESARCHIV_RECONCILE_CRON` — scheduled full-rebuild cadence (default
  `0 * * * *`, hourly; bounds worst-case staleness after any missed incremental
  update).
- Job-table hygiene: prune finished `procrastinate_jobs` rows periodically (the
  worker's `db_cleanup` periodic task / the `procrastinate` CLI).
- One index-writer advisory lock serializes every index writer
  (`indexer._INDEX_WRITER_LOCK_KEY`); do not reuse that key elsewhere.

## Media serving + thumbnails (Part 4.3) — ADR 0005

Every media/thumbnail byte is served ONLY by the authorized view at
`/media/<article-ulid>/<content-hash>` (+ `/thumb`), which resolves the viewer and
calls `can_view` on the resolved Collection chain before handing off to the one
`media_response` seam. The media tree is never web-root reachable;
denials/absence are byte-identical 404s.

- `BUNDESARCHIV_X_ACCEL_PREFIX` — set in production (behind nginx):
  `media_response` returns an `X-Accel-Redirect` to
  `<prefix>/<store-relative blob path>` and nginx serves the bytes from an
  `internal;` location over the media tree (nginx handles HTTP Range). Leave
  UNSET in dev — the seam then streams the blob directly via `FileResponse`
  (no Range support in dev).
- `BUNDESARCHIV_THUMBNAIL_ROOT` — the LOCAL derived thumbnail cache (default
  `var/thumbnails`). Content-hash-keyed WebP files generated by the
  `generate_thumbnail` worker job from canonical image blobs (JPEG/PNG/TIFF via
  Pillow; non-images no-op). This cache is **NOT** the ObjectStore, **NOT**
  canonical, **NOT** mirrored, **NOT** backed up, and freely **prunable** — a
  pruned/never-generated thumbnail simply 404s (byte-identically) until the job
  regenerates it. Safe to `rm -rf` between runs.

## WebDAV mirror (Part 4.9) — ADR 0005

An OPTIONAL Nextcloud/WebDAV **browse-only convenience** copy of the canonical
store. The mirror is **never a read path** and **is NOT backup** — durability is
restic (the go-live gate). Leave it UNSET (the default) and all mirror machinery
no-ops cleanly.

**Amended 2026-09-19** (`docs/requirements/owner-interview-2026-08.md`): backup is
outside this project's scope and restic is not an owner requirement, so it is no longer
a go-live gate. The mirror is still not a read path and still not durability.

Write paths enqueue an async `mirror_push` reference job per touched canonical
key (out-of-band — never blocks or fails the save); a periodic `mirror_reconcile`
sweeps the whole store to re-push anything missed and delete mirror-only
stragglers. Jobs are references (they carry a key and re-read canonical at run),
so a stale push whose key was deleted deletes it from the mirror too. A down/slow
mirror retries with bounded exponential backoff, then parks — the next reconcile
heals it.

- `BUNDESARCHIV_MIRROR_DAV_URL` — the WebDAV base URL. **Unset ⇒ mirror off** (no
  store built, no jobs enqueued, reconcile no-ops).
  **WARNING: point this at a dedicated folder the app owns exclusively. Reconcile
  deletes everything under this root that is not in canonical — never share it
  with human-managed files.** (An anomalously large delete sweep logs a warning
  naming the deleted keys.)
- `BUNDESARCHIV_MIRROR_DAV_USER` / `BUNDESARCHIV_MIRROR_DAV_PASSWORD` — mirror
  credentials.
- `BUNDESARCHIV_MIRROR_RECONCILE_CRON` — the scheduled full-sweep cadence
  (default `0 3 * * *`, daily; coarser than the hourly index reconcile because a
  briefly-stale browse copy harms nothing). The `mirror_reconcile` task logs and
  returns a `{pushed, deleted, failed}` summary.

A live-Nextcloud mirror smoke is a Part 6 runbook item; the in-repo tests cover
the logic against both the in-memory double and the real WebDAV adapter (the
ObjectStore port is the seam).
