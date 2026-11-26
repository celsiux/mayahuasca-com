#!/usr/bin/env python3
"""T-502: sealed guarded update of the existing protected Worker and report objects.

Provider reads only by default. Never creates/changes Access or enables aliases.
The installation CLI and its journal are deliberately not reused or modified.
"""

import argparse
import hashlib
import urllib.request
import fcntl
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

spec = importlib.util.spec_from_file_location(
    "report_library", Path(__file__).with_name("report_library.py")
)
library = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library)
REGISTERED, c, validate_catalogue = (
    library.REGISTERED,
    library.control,
    library.validate_catalogue,
)

LIVE_VERSION = "3176bea5-7a54-4807-9b2d-bccb3e3c5646"
APP = "656f0876-c562-42db-921a-99ec35e0564e"
ORIGINAL_SEAL = "214338626bae624e3859941b0f06c57b4bf38b73731c28d03ddfe81ed1bffa6d"
DISABLED = {"enabled": False, "previews_enabled": False}


class UpdateCF(c.CF):
    def object_digest(self, key):
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4" + object_path(self, key),
            headers={"Authorization": "Bearer " + self.token},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(6000001)
        if len(data) > 6000000:
            raise ValueError("Private asset exceeds bounded readback")
        return hashlib.sha256(data).hexdigest()


def state(cf, original):
    """Read fixed control-plane resources; return no email values or secret bodies."""

    def get(suffix):
        return cf.call("GET", c.account_path(cf, suffix))

    source = get("/access/apps/" + c.SOURCE_APP)
    policy, emails, idps = c.inherited_policy(
        source, get("/access/apps/" + c.SOURCE_APP + "/policies")
    )
    if (
        c.digest({"policy": policy, "idps": idps})
        != original["origin"]["staff_policy_sha256"]
    ):
        raise ValueError("Original staff audience/providers drifted")
    app = get("/access/apps/" + APP)
    policies = get("/access/apps/" + APP + "/policies")
    if (
        app.get("destinations") != c.DESTINATIONS
        or app.get("domain") != c.HOST + "/preview"
        or app.get("allowed_idps") != idps
        or app.get("session_duration") != "24h"
        or app.get("type") != "self_hosted"
        or not app.get("aud")
        or len(policies) != 1
        or any(policies[0].get(k) != v for k, v in policy.items())
    ):
        raise ValueError("Existing preview app/audience drifted")
    apps = get("/access/apps?per_page=100")
    if len(apps) >= 100:
        raise ValueError("Access inventory requires pagination review")
    for candidate in apps:
        domains = [candidate.get("domain", "")] + [
            d.get("uri", "") for d in candidate.get("destinations", [])
        ]
        if candidate["id"] != APP and any(
            d.split("/")[0] in {c.HOST, "*." + c.HOST, "www." + c.HOST, "new." + c.HOST}
            for d in domains
        ):
            raise ValueError("Overlapping Access app")
    if get("/access/organizations").get("auth_domain") != "netuge.cloudflareaccess.com":
        raise ValueError("Issuer drift")
    providers = get("/access/identity_providers")
    if {x.get("type") for x in providers if x.get("id") in idps} != {
        "google",
        "onetimepin",
    }:
        raise ValueError("Provider drift")
    aliases = cf.call("GET", c.script_path(cf, "/subdomain"))
    if aliases != DISABLED:
        raise ValueError("Alternative Worker URLs are enabled")
    if get("/r2/buckets/" + c.BUCKET + "/domains/managed").get(
        "enabled"
    ) is not False or get("/r2/buckets/" + c.BUCKET + "/domains/custom").get("domains"):
        raise ValueError("R2 is public")
    domains = get("/workers/domains")
    relevant = sorted(
        [
            {
                k: x.get(k)
                for k in [
                    "hostname",
                    "service",
                    "id",
                    "enabled",
                    "previews_enabled",
                    "environment",
                ]
            }
            for x in domains
            if x["hostname"] in [c.HOST, "www." + c.HOST, "new." + c.HOST]
        ],
        key=lambda x: x["hostname"],
    )
    if relevant != original["origin"]["custom_domains"]:
        raise ValueError("Custom domains drifted")
    workers = get("/workers/scripts")
    if len(workers) > 100:
        raise ValueError("Worker inventory requires review")
    for worker in workers:
        if worker["id"] != c.WORKER and any(
            x.get("bucket_name") == c.BUCKET
            for x in get("/workers/scripts/" + worker["id"] + "/settings").get(
                "bindings", []
            )
        ):
            raise ValueError("Another Worker can read the bucket")
    settings = cf.call("GET", c.script_path(cf, "/settings"))
    if (
        settings.get("compatibility_date") != "2026-10-22"
        or settings.get("compatibility_flags")
        or settings.get("placement")
        or settings.get("logpush") is not False
        or settings.get("tail_consumers")
        or settings.get("tags")
        or settings.get("usage_model") != "standard"
    ):
        raise ValueError("Worker runtime/settings changed")
    bindings = {x["name"]: x for x in settings.get("bindings", [])}
    if (
        len(settings.get("bindings", [])) != 4
        or set(bindings)
        != {
            "SITE_BUCKET",
            "MAYA_PREVIEW_ACCESS_ISSUER",
            "MAYA_PREVIEW_ACCESS_AUD",
            "MAYA_PREVIEW_ALLOWED_EMAILS",
        }
        or bindings["SITE_BUCKET"].get("type") != "r2_bucket"
        or bindings["SITE_BUCKET"].get("bucket_name") != c.BUCKET
        or bindings["MAYA_PREVIEW_ACCESS_AUD"].get("type") != "plain_text"
        or bindings["MAYA_PREVIEW_ACCESS_AUD"].get("text") != app["aud"]
        or bindings["MAYA_PREVIEW_ACCESS_ISSUER"].get("type") != "plain_text"
        or bindings["MAYA_PREVIEW_ACCESS_ISSUER"].get("text")
        != original["origin"]["issuer"]
        or bindings["MAYA_PREVIEW_ALLOWED_EMAILS"].get("type") != "secret_text"
    ):
        raise ValueError("Existing auth bindings drifted")
    versions = cf.call("GET", c.script_path(cf, "/deployments"))["deployments"][0][
        "versions"
    ]
    if len(versions) != 1 or versions[0]["percentage"] != 100:
        raise ValueError("Split deployment")
    # Hash complete settings without persisting secret/auth values.
    snapshot = {
        "version": versions[0]["version_id"],
        "worker": cf.worker_digest(),
        "settings": c.digest(
            {
                **settings,
                "bindings": sorted(settings["bindings"], key=lambda x: x["name"]),
            }
        ),
        "app": c.digest(app),
        "policies": c.digest(policies),
        "staff": c.digest({"policy": policy, "idps": idps}),
        "domains": c.digest(relevant),
    }
    upload_bindings = [
        bindings["SITE_BUCKET"],
        bindings["MAYA_PREVIEW_ACCESS_ISSUER"],
        bindings["MAYA_PREVIEW_ACCESS_AUD"],
        {
            "type": "secret_text",
            "name": "MAYA_PREVIEW_ALLOWED_EMAILS",
            "text": json.dumps(emails),
        },
    ]
    return snapshot, upload_bindings


def object_path(cf, key):
    if key not in REGISTERED:
        raise ValueError("Unregistered object")
    return c.account_path(cf, "/r2/buckets/" + c.BUCKET + "/objects/" + key)


def object_hash(cf, key):
    return cf.object_digest(key) if cf.object_exists(key) else None


def original_manifest(path):
    path = Path(path)
    m = json.loads((path / "manifest.json").read_text())
    if (
        m.get("seal") != ORIGINAL_SEAL
        or c.digest({k: v for k, v in m.items() if k != "seal"}) != ORIGINAL_SEAL
    ):
        raise ValueError("Original packet seal mismatch")
    journal = json.loads((path / "apply-journal.json").read_text())
    if (
        journal.get("app_id") != APP
        or journal.get("seal") != ORIGINAL_SEAL
        or journal.get("objects") != c.KEYS
    ):
        raise ValueError("Original installation journal mismatch")
    for name, digest in m["files"].items():
        if c.file_sha(path / name) != digest:
            raise ValueError("Original backup mismatch")
    return m


def clean_head(head=None):
    actual = subprocess.check_output(
        ["git", "-C", str(c.ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    if (head and head != actual) or subprocess.check_output(
        ["git", "-C", str(c.ROOT), "status", "--porcelain"], text=True
    ).strip():
        raise ValueError("Use clean reviewed source head")
    return actual


def check_control(now, expected, worker=None):
    fields = ["settings", "app", "policies", "staff", "domains"]
    if any(now[k] != expected[k] for k in fields) or (
        worker and now["worker"] != worker
    ):
        raise ValueError("Live control plane drift; stop with protection intact")


def prepare(cf, packet, original, rendered, catalogue, bundle):
    head = clean_head()
    old = original_manifest(original)
    before, _ = state(cf, old)
    if (
        before["version"] != LIVE_VERSION
        or before["worker"] != old["files"]["worker.js"]
    ):
        raise ValueError(
            "Current protected version/source differs from verified baseline"
        )
    items = validate_catalogue(json.loads(Path(catalogue).read_text()))
    if {x["path"] for x in items} != set(library.REPORTS):
        raise ValueError("Catalogue must include all registered reports")
    previous = {
        key: old["files"][key.split("/")[1]] if key in c.KEYS else None
        for key in REGISTERED
    }
    if any(object_hash(cf, key) != sha for key, sha in previous.items()):
        raise ValueError("Live objects differ from baseline")
    p = Path(packet)
    if p.resolve().is_relative_to(c.ROOT):
        raise ValueError("Keep private packet outside the public repository")
    p.mkdir(mode=0o700)
    files = {}
    sources = [
        (Path(rendered) / key.split("/")[1], key.split("/")[1]) for key in REGISTERED
    ]
    sources += [(Path(catalogue), "catalogue.json"), (Path(bundle), "worker.js")]
    sources += [
        (Path(original) / key.split("/")[1], "before-" + key.split("/")[1])
        for key in c.KEYS
    ]
    for src, name in sources:
        if src.is_symlink() or not src.is_file() or src.stat().st_size > 6000000:
            raise ValueError("Invalid packet source")
        shutil.copyfile(src, p / name)
        (p / name).chmod(0o600)
        files[name] = c.file_sha(p / name)
    m = {
        "schema": 1,
        "head": head,
        "original": str(Path(original).resolve()),
        "original_seal": ORIGINAL_SEAL,
        "original_journal_sha256": c.file_sha(Path(original) / "apply-journal.json"),
        "before": before,
        "previous": previous,
        "keys": REGISTERED,
        "files": files,
    }
    m["seal"] = c.digest(m)
    c.private_json(p / "manifest.json", m)
    return m


def validate(packet, seal, head):
    clean_head(head)
    p = Path(packet)
    m = json.loads((p / "manifest.json").read_text())
    if (
        c.digest({k: v for k, v in m.items() if k != "seal"}) != seal
        or m["seal"] != seal
        or m["head"] != head
        or m["keys"] != REGISTERED
    ):
        raise ValueError("Reviewed packet/head/seal mismatch")
    expected = (
        {key.split("/")[1] for key in REGISTERED}
        | {"before-" + key.split("/")[1] for key in c.KEYS}
        | {"catalogue.json", "worker.js"}
    )
    if set(m["files"]) != expected:
        raise ValueError("Unexpected packet files")
    for name, sha in m["files"].items():
        if (
            Path(name).name != name
            or (p / name).is_symlink()
            or c.file_sha(p / name) != sha
        ):
            raise ValueError("Packet hash mismatch")
    old = original_manifest(m["original"])
    if (
        c.file_sha(Path(m["original"]) / "apply-journal.json")
        != m["original_journal_sha256"]
    ):
        raise ValueError("Original journal changed")
    return m, old


def preflight(cf, m, old):
    now, bindings = state(cf, old)
    if now != m["before"] or any(
        object_hash(cf, key) != sha for key, sha in m["previous"].items()
    ):
        raise ValueError("Live state drift; prepare and review again")
    return bindings


def update(cf, packet, m, old):
    p = Path(packet)
    journal_path = p / "update-journal.json"
    if journal_path.exists():
        raise ValueError("Update journal exists; never blindly reapply")
    bindings = preflight(cf, m, old)
    journal = {
        "seal": m["seal"],
        "head": m["head"],
        "worker_intent": True,
        "objects": [],
        "status": "STARTED",
    }
    c.private_json(journal_path, journal)
    body, ct = c.multipart((p / "worker.js").read_bytes(), bindings)
    cf.call("PUT", c.script_path(cf), body, ct)
    now, _ = state(cf, old)
    check_control(now, m["before"], m["files"]["worker.js"])
    journal["version"] = now["version"]
    c.private_json(journal_path, journal)
    assets = ["preview/videos.json", "preview/video-explorer.js", "preview/videos.html"]
    documents = [
        key for key in REGISTERED if key not in assets + ["preview/index.html"]
    ]
    for key in assets + documents + ["preview/index.html"]:
        current, _ = state(cf, old)
        check_control(current, m["before"], m["files"]["worker.js"])
        if current["version"] != journal["version"]:
            raise ValueError("Deployment changed before object upload")
        if object_hash(cf, key) != m["previous"][key]:
            raise ValueError("Object changed before upload")
        journal["objects"].append(key)
        c.private_json(journal_path, journal)
        cf.call(
            "PUT",
            object_path(cf, key),
            (p / key.split("/")[1]).read_bytes(),
            "text/html; charset=utf-8",
        )
        if object_hash(cf, key) != m["files"][key.split("/")[1]]:
            raise ValueError("Object readback mismatch")
    now, _ = state(cf, old)
    check_control(now, m["before"], m["files"]["worker.js"])
    if now["version"] != journal["version"]:
        raise ValueError("Deployment drift")
    journal["status"] = "UPDATED_AUTHENTICATED_VERIFICATION_PENDING"
    c.private_json(journal_path, journal)
    return {
        "status": journal["status"],
        "version": now["version"],
        "objects": len(REGISTERED),
    }


def rollback(cf, packet, m, old):
    p = Path(packet)
    journal_path = p / "update-journal.json"
    journal = json.loads(journal_path.read_text())
    if (
        journal.get("seal") != m["seal"]
        or journal.get("head") != m["head"]
        or journal.get("status") == "ROLLED_BACK"
    ):
        raise ValueError("Wrong or completed update journal")
    now, _ = state(cf, old)
    check_control(now, m["before"])
    if not (
        (
            now["worker"] == m["files"]["worker.js"]
            and (not journal.get("version") or now["version"] == journal["version"])
        )
        or (now["worker"] == m["before"]["worker"] and now["version"] == LIVE_VERSION)
    ):
        raise ValueError("Unowned Worker; manual review required")
    # Check every object before mutation; changed unrelated content stops recovery.
    for key in REGISTERED:
        allowed = {m["previous"][key]}
        if key in journal["objects"]:
            allowed.add(m["files"][key.split("/")[1]])
        if object_hash(cf, key) not in allowed:
            raise ValueError("Unowned object; manual review required")
    for key in reversed(journal["objects"]):
        journal["rollback_intent"] = key
        c.private_json(journal_path, journal)
        if m["previous"][key] is None:
            cf.call("DELETE", object_path(cf, key))
        else:
            cf.call(
                "PUT",
                object_path(cf, key),
                (p / ("before-" + key.split("/")[1])).read_bytes(),
                "text/html; charset=utf-8",
            )
        if object_hash(cf, key) != m["previous"][key]:
            raise ValueError("Rollback object readback mismatch; retain guard")
    now, _ = state(cf, old)
    check_control(now, m["before"])
    if now["worker"] not in {m["before"]["worker"], m["files"]["worker.js"]}:
        raise ValueError("Worker changed during recovery")
    if now["version"] != LIVE_VERSION:
        journal["rollback_worker_intent"] = True
        c.private_json(journal_path, journal)
        cf.call(
            "POST",
            c.script_path(cf, "/deployments"),
            {
                "strategy": "percentage",
                "versions": [{"version_id": LIVE_VERSION, "percentage": 100}],
            },
        )
    final, _ = state(cf, old)
    if final != m["before"] or any(
        object_hash(cf, key) != sha for key, sha in m["previous"].items()
    ):
        raise ValueError("Rollback readback mismatch")
    journal["status"] = "ROLLED_BACK"
    c.private_json(journal_path, journal)
    return {"status": "ROLLED_BACK_PROTECTED_BASELINE", "version": LIVE_VERSION}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare", "preflight", "update", "rollback"]
    )
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--rendered", type=Path)
    parser.add_argument("--catalogue", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--seal")
    parser.add_argument("--review-head")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    writes = args.action in {"update", "rollback"}
    if writes and not args.apply:
        parser.error("Mutation requires independent exact-head/seal review and --apply")
    cf = UpdateCF(writable=writes and args.apply)
    if args.action == "prepare":
        if not all([args.original, args.rendered, args.catalogue, args.bundle]):
            parser.error(
                "prepare requires original packet, rendered reports, catalogue and bundle"
            )
        m = prepare(
            cf, args.packet, args.original, args.rendered, args.catalogue, args.bundle
        )
        print(
            json.dumps(
                {"status": "PREPARED_NO_WRITES", "seal": m["seal"], "head": m["head"]}
            )
        )
        return
    m, old = validate(args.packet, args.seal, args.review_head)
    if args.action == "preflight":
        preflight(cf, m, old)
        print(json.dumps({"status": "PREFLIGHT_PASS_NO_WRITES", "seal": m["seal"]}))
        return
    fd = os.open(args.packet / ".update.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(
            json.dumps(
                (update if args.action == "update" else rollback)(
                    cf, args.packet, m, old
                )
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError):
        print("STOP: packet, live-state or transport check failed; no automatic retry")
        raise SystemExit(2) from None
