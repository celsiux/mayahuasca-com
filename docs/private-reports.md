# Private report preview — T453

Ticket T453 / f76d7df8-6ff1-40eb-8896-338bcaf007e3; related T454 / fb5a63a6-9105-4108-b428-7f3ca61277f0.

## Scope and origin

The existing `mayahuasca-site` Worker serves the apex, www and new custom domains from the existing private `maya-site` R2 bucket. This change reserves `/preview`, `/preview/` and its descendants. The public object handler is otherwise unchanged. It adds neither a website nor a bucket, DNS record, tunnel, model call or provider subscription. The generic index template is versioned; the two actual Spanish documents, their CSVs and evidence are **never committed to this public repository** or placed in `dist/`.

The read-only discovery found Custom Domain bindings; an empty zone Workers Routes list alone did not identify the origin. The captured live version's source map matches the repository base `src/worker.js` byte for byte. Preserve that evidence and current version/settings outside this worktree for review. Do not use the unrelated FAQ Pages project.

## Authorization boundary

The coordinator creates one Access application with explicit destinations `mayahuasca.com/preview` and `mayahuasca.com/preview/*`. Its one allow policy is copied **in memory** from the exact existing Maya staff policy. The helper refuses anything other than its current two explicit email rules, no exclusions/requirements, existing Google + OTP providers and 24-hour session. It never edits that source policy or adds a member/provider. No addresses are committed or logged.

The Worker also verifies the Access assertion using `jose` and the existing account's rotating JWK endpoint: RS256 signature, issuer, application audience, expiration, issued-at, subject and exact staff email. The copied staff list is a `secret_text` Worker binding, not a public config file. Missing configuration, identity-only headers, another application and another user fail closed. Every preview request, including HEAD, unknown assets and encoded aliases, reaches this boundary before R2. Only the index and two named HTML documents can be read. Responses use private/no-store, noindex and a restrictive CSP. All noncanonical hosts are denied on this prefix even with a staff assertion.

The website's `workers.dev` **and version URLs** are presently enabled. Older versions also have the R2 binding and could expose later private keys. Both classes must be disabled account-side and in Wrangler config **before uploading documents**. R2's managed public URL must stay disabled, with no public custom domains or other Worker consumers. The helper checks these facts. These settings are intentionally explicit; an unlisted/version URL is not access control.

## Local gates

```sh
npm ci --ignore-scripts
npm run test
npm run check
npm run typecheck
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_preview_control.py -v
ruff check scripts/preview-control.py tests/test_preview_control.py
WRANGLER_SEND_METRICS=false CI=true node node_modules/wrangler/bin/wrangler.js deploy --dry-run --outdir <private-build-dir>
```

These use synthetic identities, locally generated signing keys, fake provider responses and a fake R2 binding. They never contact TikTok or call models. The build is offline; no `deploy`, `versions upload`, R2 put or Access mutation is part of a gate. For heavy browser checks use the shared host gate slot.

## Prepare a private packet

After committing, use a clean worktree at the exact review head. Use a new private directory **outside the repository**. Keep the checked dry-run `worker.js`; do not run the normal site deploy, which syncs all public assets.

```sh
<vertixos>/scripts/vertix-infisical-run --path /infra/cloudflare --env prod -- \
  python3 -I scripts/preview-control.py prepare \
  --analytics <approved-analytics.html> --comments <approved-comments.html> \
  --bundle <private-build-dir>/worker.js --packet <private-packet>
```

`prepare` is read-only at the provider. It pins both approved document hashes, copies them and the index, records the compiled Worker hash and repository head, and seals a sanitized live-origin snapshot. It refuses an existing preview prefix, a public R2 alternative, another bucket reader, overlapping apex Access application, unexpected source policy, split deployment, binding changes or a dirty worktree. The packet is 0700 with 0600 files and contains no staff addresses, cookies or tokens. Source-control changes require a new head/packet/review; source policy or origin drift requires fresh preparation and review.

An independent **security APPROVE** on the exact head and packet seal is required before the coordinator applies anything. Supply full base/head diff, gate logs, the sealed packet and complete minimal existing-route context outside the worktree. The program's explicit `--apply` is a mutation gate, not a substitute for that review.

## Coordinator preflight and apply — not worker actions

Run each command under the existing Infisical wrapper, from the clean reviewed source:

```sh
python3 -I scripts/preview-control.py preflight --packet <private-packet> --seal <seal> --review-head <head>
python3 -I scripts/preview-control.py apply --packet <private-packet> --seal <seal> --review-head <head> --apply
```

Order enforced by `apply`:

1. Recheck live version/custom domains, bucket privacy/empty prefix and inherited staff configuration against the sealed snapshot. Create a durable private journal before the first write.
2. Create the path-specific Access application and policy, then verify scope, providers and policy membership readback.
3. Disable production workers.dev and version/alias URLs; verify flags false. No private objects yet.
4. Upload the reviewed Worker bundle only, preserving the existing R2 binding. Set the new audience, existing issuer and inherited staff binding privately. Verify compiled source hash and binding metadata. Recheck alternatives and bucket privacy.
5. Upload only the index and two HTML keys to the existing bucket, with intent journaled before each PUT. Verify every object hash using an authenticated provider read.

No DNS, custom-domain, public-site object, source staff-policy, Pages or billing mutation is issued. A partial/uncertain write stops; never rerun apply blindly. Use its journal to inspect/rollback. The helper takes an exclusive packet lock. Normal future site deployments use `--keep-vars` so they retain the privately supplied authorization variables; `workers_dev:false` and `preview_urls:false` prevent accidental alias reopening. Future staff changes need explicit reconciliation/review; they are not silently synchronized or expanded.

## Verification before retiring the previous report links

The apply result is **authenticated verification pending**, not a verified-live receipt. Keep the prior internal links until all checks pass:

- Signed out: apex `/preview`, `/preview/`, each HTML and an unknown descendant deny or challenge; no private body on a challenge/error.
- Allowed existing staff session: canonical URLs return 200; exact title/metrics and the two reviewed document hashes match. Verify the index links at 390px and that public `/`, offer, robots, sitemap and images remain unchanged.
- Other identity: denied. Do not add a test identity to production; use a currently available unauthorized session or retain this as unverified if none is authorized for testing. The offline signed-other-user case is separate evidence.
- Check www/new preview paths, production workers.dev, old version URLs and version aliases, plus R2 managed/custom alternatives. Provider flags must be disabled even where this host's Cloudflare 403 prevents meaningful browser verification. Do not treat that generic 403 as authenticated proof.
- Confirm no more-specific overlapping Access rule appeared, and record deployment version, app/policy IDs, artifact hashes, test time and the required operational receipt on T453/T454. Do not extract browser cookies or tokens.

## Coordinator rollback

```sh
python3 -I scripts/preview-control.py rollback --packet <private-packet> --seal <seal> --review-head <head> --apply
```

The helper removes only its three journaled object keys (refuses modified objects), confirms their absence and an empty reserved prefix, then restores the previous Worker version and alias settings. Only then may it delete its exact new Access application. If deletion fails, another preview object exists, the Worker changed unexpectedly or ownership/scope differs, it stops with protection retained for manual review. Restoring an unguarded version while private objects remain is prohibited. A lost create/upload response is never retried automatically. Record rollback proof with the existing receipt workflow. Original public website assets and the prior polly-status report copies are not deleted.

## Provider references

- https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- https://developers.cloudflare.com/workers/versions-and-deployments/version-urls/
- https://developers.cloudflare.com/workers/configuration/routing/workers-dev/

Checked against current docs on 2026-11-26. Existing account has Workers Paid and R2; preparation makes no resource purchases/upgrades and applies nothing. Future serving uses those existing metered plans; the packet creates no new Worker, bucket, tunnel or login provider.
