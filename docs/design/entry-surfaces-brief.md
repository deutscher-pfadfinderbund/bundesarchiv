# Entry surfaces — confirmed brief (D3)

Source: owner shape interview 2026-08-22 (rulings verbatim in
`docs/requirements/owner-interview-2026-08.md` §Entry-surface rulings).
Companion to ADR 0018 (auth: Keycloak OIDC + capability links — designed,
not built; this brief is the missing UI half). Precedent format:
`form-wave-brief.md`.

## Job and audience

Three arrivals, one door law: **no public browsing, ever** — the root is a
door, not a shop window.

1. A DPB member with a Keycloak account, on desktop or phone.
2. A member WITHOUT an account holding a secret capability link, typically
   on a phone, arriving from chat/mail. The product's most common first
   impression.
3. An archivist (always Keycloak). Same door as everyone.

Mode: Operate (the task is: get in). Phone-first for door and denied pages
(links arrive via chat/mail — existing law §D).

## Surfaces and rulings

### 1. The door (root, no session)
- Wordmark (the Kapitälchen serif mark) + ONE sentence of context (German
  copy decided at the gate; direction: "Das Archiv des Deutschen
  Pfadfinderbundes — Zugang für Mitglieder").
- **Anmelden** — the one primary action → Keycloak redirect, returning to
  the originally requested URL (or the workbench as default).
- A quiet line for the lost member: no account yet → **contact the
  archivists** (mailto/contact address — a human answers; no extra page).
- **Material role (G.17): TRUE SHEET** — one sheet resting on the empty
  desk carrying the archive's name; register row 8 applies (tint, hairline
  edge, contact shadow). Nothing else on the surface.

### 2. Capability-link landing
- **No surface at all.** Token mints the Viewer cookie silently; the
  target content renders immediately — the link IS the door.
- The guest sees the same views as everyone (shared-views ruling,
  2026-08-22); no guest marker, no identity chrome.

### 3. Denied / not-found (plain page, relaxed-404 ruling)
- One quiet page: it exists, it says access is not possible, it offers the
  door (Anmelden) and the contact hint. Reveals and changes nothing else.
- **Dead-link variant:** on the revoked/expired-token path ONLY, one
  additional line — "Dieser Zugangslink ist nicht mehr gültig" + contact
  hint. Ruled acceptable.
- Waldläuferzeichen state language stays an optional extension (recorded
  in design-system.md §Extensions) — not part of this wave's floor.

### 4. Session chrome
- **Header carries NO identity** — no name, tier, or login state, for any
  tier. Archivist identity is implicit in the capabilities on the page.
- **Abmelden lives in the footer**: a quiet line at every page's end,
  rendered only while a session exists.

## States to render (gallery, both modes, phone + desktop)

Door (logged out) · door with active session (footer shows Abmelden) ·
denied plain · denied dead-link · a capability-link arrival landing in the
reader · Keycloak round-trip failure (the auth layer's error surface —
copy TBD at the gate).

## Scope and boundaries

- This brief designs UI; the auth mechanics are ADR 0018's (amended:
  capability links instead of guest passwords). Build them together in the
  auth wave — the deployment-1 blocker.
- Untouched: workbench, reader, deny semantics (plain 404 law), the
  Viewer/audience model.
- Anti-goals: no marketing page, no feature tour, no public teaser of
  content, no identity chrome in the header, no interstitials on link
  arrival.

## Open decisions the builder must not invent

- Exact German copy: the door sentence, the denied texts, the dead-link
  line, the contact line (gate, on renders).
- The contact address itself (owner supplies; never fabricate).
- Where a COLLECTION-scoped link lands (single-article links → that
  article's reader; collection/group links → open: filtered workbench vs
  collection page — decide when capability-link scopes are built).
- Session-expiry mid-edit behavior (belongs to the auth wave + CAS flow,
  not this brief).
