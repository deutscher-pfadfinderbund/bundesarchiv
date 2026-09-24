# Nextcloud WebDAV: measured behaviour of the StorageShare

What the archive's Nextcloud does over WebDAV. Measured on 2026-09-24 against the
StorageShare at `cloud.deutscher-pfadfinderbund.de`, Nextcloud 33.0.9, as the app user,
inside a throwaway folder that was deleted afterwards. Behaviour can change with a
Nextcloud upgrade. Re-run the probes below after one.

Decisions built on these results: [ADR 0019](adr/0019-canonical-layout-v1.md) (layout,
file names) and [ADR 0020](adr/0020-storage-topology-system-of-record.md) (topology,
reconcile).

## Endpoints

| Purpose | URL |
| --- | --- |
| Files | `https://<host>/remote.php/dav/files/<user>/<path>` |
| Chunked uploads | `https://<host>/remote.php/dav/uploads/<user>/<upload-id>/` |
| `SEARCH` | `https://<host>/remote.php/dav/` |
| Server version | `https://<host>/status.php` |
| Capabilities | `https://<host>/ocs/v1.php/cloud/capabilities?format=json`, header `OCS-APIRequest: true` |

Capabilities reported: `dav.chunking: "1.0"`, `dav.bulkupload: "1.0"`,
`files.bigfilechunking: true`. There is no `checksums` capability.

## Conditional writes

| Request | Result |
| --- | --- |
| `PUT` with a stale `If-Match` | `412`, file unchanged |
| `PUT` with the current `If-Match` | `204` |
| `PUT` with `If-None-Match: *`, key exists | `412` |
| `PUT` with `If-None-Match: *`, key free | `201` |
| `MOVE` with `Overwrite: F`, target exists | `412`, target unchanged |
| `MOVE` with `Overwrite: F`, target free | `201` |

Compare-and-swap and create-only writes both work.

## ETags

- A `PUT` answers with `ETag` and `OC-ETag` (same value) and `OC-FileId`.
- The `PUT` ETag equals the `getetag` a later `PROPFIND` reports, so a client can
  record the ETag without an extra request.
- A `PROPPATCH` of a property (`oc:favorite`) leaves the ETag unchanged.

## Listing

| Request | Result |
| --- | --- |
| `PROPFIND Depth: 1` | `207`, 78 ms median on a folder of 14 entries |
| `PROPFIND Depth: infinity` | allowed, returns the whole subtree |
| `SEARCH` with a `where` clause | `207`, every file of the subtree in one request, with the selected props (`getetag`, `getcontentlength`) |
| `SEARCH` without a `where` clause | `500` (`TypeError`) |
| `SEARCH` without `<d:limit>` | at most 100 results. `<d:nresults>` raises the limit, and `<ns:firstresult>` (namespace `https://github.com/icewind1991/SearchDAV/ns`) pages. 250 files came back complete both ways. |

Props available in `PROPFIND`: `getetag`, `getcontentlength`, `getlastmodified`,
`resourcetype`, `oc:fileid`, `oc:checksums`.

## Checksums

- `OC-Checksum: SHA256:<hex>` (also `SHA1`, `MD5`) on `PUT` is stored and returned in
  `oc:checksums`.
- The server does not verify it: a `PUT` with a wrong `SHA1` value was accepted (`201`).
- A stored checksum is therefore a claim by the uploader. Checking the bytes on the server
  needs a download.

## Range and chunked upload

- `GET` with `Range: bytes=0-99` on a 1000-byte file: `206`,
  `Content-Range: bytes 0-99/1000`, correct bytes.
- Chunked upload v2: `MKCOL` of the upload folder with `Destination`, then chunks
  `00001`…`00004` of 5 MiB each with `Destination` and `OC-Total-Length`, then `MOVE` of
  `.file` to the target. Result: `201` with an ETag, and the downloaded bytes' SHA-256
  matches.

## File names

- **Case-sensitive:** `Scan.pdf` and `scan.pdf` are kept as two files.
- **NFC-normalized:** a `PUT` under the NFD spelling of a name replaced the NFC file
  (`204`). Listings return NFC.
- **Length:** at most 250 bytes of UTF-8. 250 bytes succeeded and 251 bytes returned
  `400`, both for ASCII and for multi-byte names (127 characters, 250 bytes accepted;
  130 characters, 256 bytes refused).
- `#`, `%`, double spaces and umlauts round-trip when the URL is percent-encoded.

## At archive scale

A synthetic tree shaped like the legacy import: 2506 article folders, each with a 587-byte
`README.md` and `history/1.md`, and 843 with `media/scan.pdf`. 5855 files, 5857 folders.

| Measurement | Result |
| --- | --- |
| Sequential writes (`MKCOL` / `PUT`, first 50 articles) | 300 requests in 83.8 s, 279 ms per request |
| 16 parallel writers, remaining 2456 articles | 314 s, about 45 requests per second. 6 of them failed with `404` or `423`, although every writer used its own keys. |
| `PROPFIND Depth: infinity` on the whole tree | 11706 entries in 9.2 s, 4.6 MB response, same on a second run |
| `PROPFIND Depth: 1` on `articles/` (2506 children) | 1.4 s |
| `DELETE` of the whole tree | 1 s (moved to the Nextcloud trash bin) |

- Transient `404` and `423` on distinct keys mean every write needs retries, not only
  contended ones.
- A first push of about 12,000 small requests takes about 55 min sequentially, or about
  5 min with 16 parallel writers, from a home line. Media bytes come on top.

## Under contention

10 parallel clients against one key, 5 rounds each (6 for `MOVE`):

| Operation | Result |
| --- | --- |
| `PUT` with the same `If-Match` | never more than one `204`. The rest `423 Locked`. In one round all ten got `423` and nobody won. |
| `PUT` with `If-None-Match: *` on a free key | exactly one `201` per round. The rest `412`, `423`, and sometimes `404` |
| `MOVE` with `Overwrite: F` onto a free key | often `500` for every client even when one `MOVE` had succeeded. No source file was lost. |
| Upload to a temp name, then `MOVE` with `Overwrite: T` onto one key | all ten `MOVE`s `500`. One write landed and 8 temp files stayed. |

- `423 Locked` comes from Nextcloud's file locking. It means "try again", not "conflict".
- `MOVE` status codes under contention cannot be trusted, while conditional `PUT` behaves.

## Large files and atomicity

- A 1 GiB `PUT`, streamed with chunked transfer encoding and no `Content-Length`:
  - `204` in 191 s (45 Mbit/s up from a home line)
  - download 10 s, SHA-256 identical
- During that `PUT` over an existing 3-byte file, a reader made 37 `HEAD` requests and
  saw only the old 3-byte file. A plain `PUT` replaces a file atomically for readers.
- 64 MiB: 42 Mbit/s up, 621 Mbit/s down, from the same home line.

## Mapping to the storage port

The port semantics are in ADR 0019 ("Storage port additions"). The WebDAV adapter maps
them like this:

| Port | WebDAV |
| --- | --- |
| atomic replace | plain `PUT` (no temp file, no `MOVE`) |
| `create` | `PUT` with `If-None-Match: *`. `412` → `AlreadyExists` |
| conditional replace (stage B) | `PUT` with `If-Match: <version>`. `412` → `Conflict` |
| `version` token (stage B) | `getetag`, also returned by every `PUT` |
| listing with metadata | `PROPFIND Depth: infinity` with `getetag`, `getcontentlength` (9.2 s for the archive-sized tree). `SEARCH` needs paging past 100 results. |
| `Busy` | `423 Locked`. Also retry a transient `404` on a key the adapter just created. |
| large write | streamed `PUT`. Chunked upload v2 stays available if a size limit shows up. |

## Not measured

- A `PUT` or chunked upload of a full 4 GiB file, and uploads from the VPS.

## Probes

Each line is one check. `$DAV` is `https://<host>/remote.php/dav/files/<user>/<probe-folder>`,
and credentials are an app password in `$DAV_USER` / `$DAV_PASSWORD`.

```sh
A=(-u "$DAV_USER:$DAV_PASSWORD" -s -o /dev/null -w '%{http_code}\n')

curl "${A[@]}" -X MKCOL "$DAV"
curl "${A[@]}" -T a.txt "$DAV/a.txt" -D -                                  # ETag in the headers
curl "${A[@]}" -T a.txt "$DAV/a.txt" -H 'If-Match: "stale"'               # want 412
curl "${A[@]}" -T a.txt "$DAV/a.txt" -H 'If-None-Match: *'                # want 412
curl "${A[@]}" -X MOVE "$DAV/c.txt" -H "Destination: $DAV/a.txt" -H 'Overwrite: F'   # want 412
curl "${A[@]}" -r 0-99 "$DAV/a.bin"                                       # want 206
curl "${A[@]}" -X PROPFIND -H 'Depth: infinity' "$DAV"                    # want 207
curl "${A[@]}" -T x.bin "$DAV/x.bin" -H "OC-Checksum: SHA1:$(printf 0%.0s {1..40})"  # 201 = not verified
curl "${A[@]}" -X DELETE "$DAV"
```

`SEARCH` body, sent with `Content-Type: text/xml` to `https://<host>/remote.php/dav/`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<d:searchrequest xmlns:d="DAV:">
  <d:basicsearch>
    <d:select><d:prop><d:getetag/><d:getcontentlength/></d:prop></d:select>
    <d:from><d:scope>
      <d:href>/files/<user>/<folder></d:href><d:depth>infinity</d:depth>
    </d:scope></d:from>
    <d:where><d:not><d:is-collection/></d:not></d:where>
  </d:basicsearch>
</d:searchrequest>
```
