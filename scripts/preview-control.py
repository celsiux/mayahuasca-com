#!/usr/bin/env python3
"""T453: prepare privately, then coordinator-only apply/rollback. Default is read-only."""

import argparse
import email.parser
import email.policy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error
import urllib.request

WORKER = "mayahuasca-site"
LIVE_VERSION = "fd0ccee1-3dfd-4525-8349-21494f473728"
LIVE_WORKER_SHA = "ad9c8f32133dae32b83ce14ec654a25be207409d45530389ce444668c80c1d3f"
BUCKET = "maya-site"
ZONE = "1917c91326fdf3209a53143cbe6b46a7"
SOURCE_APP = "3b7854cf-6567-422e-b00f-777a4894b721"
SOURCE_POLICY = "09478337-fdf8-4a24-a7fc-4b0363a31e94"
HOST = "mayahuasca.com"
DESTINATIONS = [
    {"type": "public", "uri": HOST + "/preview"},
    {"type": "public", "uri": HOST + "/preview/*"},
]
KEYS = [
    "preview/index.html",
    "preview/maya-tiktok-rendimiento-20261126.html",
    "preview/maya-tiktok-comentarios-20261126.html",
]
APP_NAME = "Maya reports preview T453"
DOCUMENT_HASHES = {
    KEYS[1]: "acccee4c1605eef4266268100092ed5413a7242a09c025a587a94b4fd51f809e",
    KEYS[2]: "d8279f44337952d96b34d947e4e3e568955e00bab71ce039362232d5bea35efe",
}
ROOT = Path(__file__).resolve().parent.parent


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_json(path, data):
    path = Path(path)
    # A journal update is durable before the next provider mutation.
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class CF:
    def __init__(self, writable=False):
        self.token = os.environ["CLOUDFLARE_API_TOKEN"]
        self.account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        self.writable = writable

    def call(self, method, path, body=None, content_type="application/json"):
        if method != "GET" and not self.writable:
            raise ValueError("Provider writes are disabled")
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": content_type,
        }
        data = (
            body
            if isinstance(body, bytes)
            else (json.dumps(body).encode() if body is not None else None)
        )
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4" + path,
            headers=headers,
            data=data,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                doc = json.loads(r.read(2000000))
        except urllib.error.HTTPError as exc:
            raise ValueError(
                "Cloudflare request failed: HTTP " + str(exc.code)
            ) from None
        if not doc.get("success"):
            raise ValueError("Cloudflare request unsuccessful")
        return doc.get("result")

    def object_exists(self, key):
        path = account_path(self, "/r2/buckets/" + BUCKET + "/objects/" + key)
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4" + path,
            headers={"Authorization": "Bearer " + self.token},
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise ValueError("Object preflight failed: HTTP " + str(exc.code)) from None

    def object_digest(self, key):
        path = account_path(self, "/r2/buckets/" + BUCKET + "/objects/" + key)
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4" + path,
            headers={"Authorization": "Bearer " + self.token},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(262145)
        if len(data) > 262144:
            raise ValueError("Report size exceeds bounded readback")
        return hashlib.sha256(data).hexdigest()

    def worker_digest(self):
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4" + script_path(self),
            headers={"Authorization": "Bearer " + self.token},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            ct = response.headers.get("Content-Type", "")
            data = response.read(1000001)
        if len(data) > 1000000:
            raise ValueError("Worker readback exceeds limit")
        message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
            ("Content-Type: " + ct + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + data
        )
        modules = [
            part.get_payload(decode=True)
            for part in message.iter_parts()
            if part.get_param("name", header="content-disposition") == "worker.js"
        ]
        if len(modules) != 1:
            raise ValueError("Unexpected Worker module readback")
        return hashlib.sha256(modules[0]).hexdigest()


def account_path(cf, suffix):
    return "/accounts/" + cf.account + suffix


def script_path(cf, suffix=""):
    return account_path(cf, "/workers/scripts/" + WORKER + suffix)


def inherited_policy(app, policies):
    matches = [p for p in policies if p.get("id") == SOURCE_POLICY]
    if len(matches) != 1:
        raise ValueError("Existing staff policy not found")
    policy = matches[0]
    include = policy.get("include", [])
    if (
        policy.get("decision") != "allow"
        or len(include) != 2
        or policy.get("exclude")
        or policy.get("require")
        or any(
            set(rule) != {"email"} or set(rule["email"]) != {"email"}
            for rule in include
        )
    ):
        raise ValueError("Staff policy is no longer exactly two email rules")
    emails = [rule["email"]["email"] for rule in include]
    if len(set(emails)) != 2 or any("*" in x or "@" not in x for x in emails):
        raise ValueError("Invalid existing staff audience")
    idps = app.get("allowed_idps", [])
    if len(idps) != 2 or app.get("session_duration") != "24h":
        raise ValueError("Existing staff login configuration changed")
    return (
        {
            "name": policy["name"],
            "decision": "allow",
            "include": include,
            "exclude": [],
            "require": [],
            "precedence": 1,
        },
        emails,
        idps,
    )


def collect_origin(cf):
    def get(path):
        return cf.call("GET", path)

    app = get(account_path(cf, "/access/apps/" + SOURCE_APP))
    policies = get(account_path(cf, "/access/apps/" + SOURCE_APP + "/policies"))
    policy, emails, idps = inherited_policy(app, policies)
    providers = get(account_path(cf, "/access/identity_providers"))
    if {x.get("type") for x in providers if x.get("id") in idps} != {
        "google",
        "onetimepin",
    }:
        raise ValueError("Unexpected source identity providers")
    org = get(account_path(cf, "/access/organizations"))
    issuer = "https://" + org["auth_domain"]
    if issuer != "https://netuge.cloudflareaccess.com":
        raise ValueError("Existing Access organization changed")
    apps = get(account_path(cf, "/access/apps?per_page=100"))
    if len(apps) >= 100:
        raise ValueError("Access inventory needs pagination review")
    for x in apps:
        domains = [x.get("domain", "")] + [
            r.get("uri", "") for r in x.get("destinations", [])
        ]
        if any(d.split("/")[0] in [HOST, "*." + HOST, "www." + HOST] for d in domains):
            raise ValueError("Apex Access overlap: review before proceeding")
    managed = get(account_path(cf, "/r2/buckets/" + BUCKET + "/domains/managed"))
    custom = get(account_path(cf, "/r2/buckets/" + BUCKET + "/domains/custom"))
    if managed.get("enabled") is not False or custom.get("domains"):
        raise ValueError("R2 bucket has a public alternative")
    if get(
        account_path(
            cf, "/r2/buckets/" + BUCKET + "/objects?prefix=preview&per_page=10"
        )
    ):
        raise ValueError("An existing preview prefix must not be replaced")
    workers = get(account_path(cf, "/workers/scripts"))
    if len(workers) > 100:
        raise ValueError("Worker inventory exceeds bounded preflight")
    for w in workers:
        if w["id"] == WORKER:
            continue
        settings = get(account_path(cf, "/workers/scripts/" + w["id"] + "/settings"))
        if any(b.get("bucket_name") == BUCKET for b in settings.get("bindings", [])):
            raise ValueError("Another Worker can read the site bucket")
    domains = get(account_path(cf, "/workers/domains"))
    relevant = sorted(
        [
            {
                "hostname": x["hostname"],
                "service": x["service"],
                "id": x["id"],
                "enabled": x.get("enabled"),
                "previews_enabled": x.get("previews_enabled"),
                "environment": x.get("environment"),
            }
            for x in domains
            if x["hostname"] in [HOST, "www." + HOST, "new." + HOST]
        ],
        key=lambda x: x["hostname"],
    )
    if len(relevant) != 3 or any(
        x["service"] != WORKER
        or x["enabled"] is not True
        or x["previews_enabled"] is not False
        or x["environment"] != "production"
        for x in relevant
    ):
        raise ValueError("Site custom domains changed")
    deployments = get(script_path(cf, "/deployments"))["deployments"]
    versions = deployments[0]["versions"]
    if len(versions) != 1 or versions[0]["percentage"] != 100:
        raise ValueError("Site is using a split deployment")
    if (
        versions[0]["version_id"] != LIVE_VERSION
        or cf.worker_digest() != LIVE_WORKER_SHA
    ):
        raise ValueError(
            "Live Worker differs from the captured repository base; do not overwrite"
        )
    settings = get(script_path(cf, "/settings"))
    bindings = settings.get("bindings", [])
    if (
        len(bindings) != 1
        or bindings[0].get("type") != "r2_bucket"
        or bindings[0].get("bucket_name") != BUCKET
    ):
        raise ValueError("Site bindings changed")
    if settings.get("compatibility_date") != "2026-10-22" or settings.get(
        "compatibility_flags"
    ):
        raise ValueError("Worker runtime changed")
    if (
        settings.get("placement")
        or settings.get("logpush") is not False
        or settings.get("tail_consumers")
        or settings.get("tags")
        or settings.get("usage_model") != "standard"
    ):
        raise ValueError("Worker operational settings changed")
    aliases = get(script_path(cf, "/subdomain"))
    for key in KEYS:
        if cf.object_exists(key):
            raise ValueError("Reserved report key already exists; no overwrite")
    snapshot = {
        "version": versions[0]["version_id"],
        "custom_domains": relevant,
        "aliases": aliases,
        "staff_policy_sha256": digest({"policy": policy, "idps": idps}),
        "issuer": issuer,
        "bucket": BUCKET,
        "bucket_public": False,
        "compatibility_date": settings["compatibility_date"],
    }
    return snapshot, policy, emails, idps


def validate_packet(packet, seal, head):
    p = Path(packet)
    m = json.loads((p / "manifest.json").read_text())
    unsigned = {k: v for k, v in m.items() if k != "seal"}
    if digest(unsigned) != seal or m["seal"] != seal or m["head"] != head:
        raise ValueError("Packet seal/review head mismatch")
    actual = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
    ).strip()
    if actual != head or dirty:
        raise ValueError("Run from the clean reviewed repository head")
    for name, expected in m["files"].items():
        if Path(name).name != name or file_sha(p / name) != expected:
            raise ValueError("Packet file hash mismatch")
    return m


def multipart(bundle, bindings):
    boundary = "t453-reviewed-worker"
    metadata = {
        "main_module": "worker.js",
        "compatibility_date": "2026-10-22",
        "compatibility_flags": [],
        "usage_model": "standard",
        "logpush": False,
        "tail_consumers": [],
        "tags": [],
        "bindings": bindings,
    }
    payload = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\nContent-Type: application/json\r\n\r\n'.encode()
        + json.dumps(metadata).encode()
        + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="worker.js"; filename="worker.js"\r\nContent-Type: application/javascript+module\r\n\r\n'.encode()
        + bundle
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return payload, "multipart/form-data; boundary=" + boundary


def apply_packet(cf, packet, m):
    p = Path(packet)
    journal_path = p / "apply-journal.json"
    if journal_path.exists():
        raise ValueError("Existing journal: inspect/rollback; never blindly reapply")
    origin, policy, emails, idps = collect_origin(cf)
    if origin != m["origin"]:
        raise ValueError("Origin or policy drift; prepare and review again")
    journal = {
        "seal": m["seal"],
        "head": m["head"],
        "origin": origin,
        "objects": [],
        "app_id": None,
        "worker_uploaded": False,
        "aliases_disabled": False,
        "app_create_intent": True,
    }
    private_json(journal_path, journal)
    app = cf.call(
        "POST",
        account_path(cf, "/access/apps"),
        {
            "name": APP_NAME,
            "type": "self_hosted",
            "domain": HOST + "/preview",
            "destinations": DESTINATIONS,
            "allowed_idps": idps,
            "session_duration": "24h",
            "app_launcher_visible": False,
            "auto_redirect_to_identity": False,
        },
    )
    journal["app_id"] = app["id"]
    private_json(journal_path, journal)
    verified_app = cf.call("GET", account_path(cf, "/access/apps/" + app["id"]))
    if (
        verified_app.get("destinations") != DESTINATIONS
        or verified_app.get("allowed_idps") != idps
        or verified_app.get("session_duration") != "24h"
        or not verified_app.get("aud")
    ):
        raise ValueError("Access scope/provider readback mismatch")
    cf.call("POST", account_path(cf, "/access/apps/" + app["id"] + "/policies"), policy)
    got = cf.call("GET", account_path(cf, "/access/apps/" + app["id"] + "/policies"))
    if (
        len(got) != 1
        or any(
            got[0].get(k, []) != policy[k] for k in ["include", "exclude", "require"]
        )
        or got[0].get("decision") != "allow"
    ):
        raise ValueError("Inherited policy readback mismatch")
    # Old versions also read this bucket. Disable ALL alternative/version URLs
    # before any private object exists, and verify this global setting.
    journal["aliases_disabled"] = True
    private_json(journal_path, journal)
    cf.call(
        "POST",
        script_path(cf, "/subdomain"),
        {"enabled": False, "previews_enabled": False},
    )
    if cf.call("GET", script_path(cf, "/subdomain")) != {
        "enabled": False,
        "previews_enabled": False,
    }:
        raise ValueError("Alternative URLs are still enabled")
    bindings = [
        {"type": "r2_bucket", "name": "SITE_BUCKET", "bucket_name": BUCKET},
        {
            "type": "plain_text",
            "name": "MAYA_PREVIEW_ACCESS_ISSUER",
            "text": origin["issuer"],
        },
        {
            "type": "plain_text",
            "name": "MAYA_PREVIEW_ACCESS_AUD",
            "text": verified_app["aud"],
        },
        {
            "type": "secret_text",
            "name": "MAYA_PREVIEW_ALLOWED_EMAILS",
            "text": json.dumps(emails),
        },
    ]
    body, ct = multipart((p / "worker.js").read_bytes(), bindings)
    journal["worker_uploaded"] = True
    private_json(journal_path, journal)
    cf.call("PUT", script_path(cf), body, ct)
    if cf.worker_digest() != m["files"]["worker.js"]:
        raise ValueError("Worker source readback mismatch; do not upload documents")
    settings = cf.call("GET", script_path(cf, "/settings"))
    current_bindings = {b["name"]: b for b in settings.get("bindings", [])}
    if (
        set(current_bindings) != {b["name"] for b in bindings}
        or current_bindings["MAYA_PREVIEW_ALLOWED_EMAILS"].get("type") != "secret_text"
        or current_bindings["MAYA_PREVIEW_ACCESS_AUD"].get("text")
        != verified_app["aud"]
        or current_bindings["MAYA_PREVIEW_ACCESS_ISSUER"].get("text")
        != origin["issuer"]
    ):
        raise ValueError("Worker authorization binding readback mismatch")
    # Explicitly recheck alternatives and bucket privacy after script upload.
    if cf.call("GET", script_path(cf, "/subdomain")) != {
        "enabled": False,
        "previews_enabled": False,
    }:
        raise ValueError("Upload re-enabled alternative URLs")
    if (
        cf.call(
            "GET", account_path(cf, "/r2/buckets/" + BUCKET + "/domains/managed")
        ).get("enabled")
        is not False
    ):
        raise ValueError("Bucket became public")
    if cf.call(
        "GET", account_path(cf, "/r2/buckets/" + BUCKET + "/domains/custom")
    ).get("domains"):
        raise ValueError("Bucket acquired a custom public domain")
    for key in KEYS:
        # Journal intent before PUT, so a lost response is also rollback-safe.
        journal["objects"].append(key)
        private_json(journal_path, journal)
        cf.call(
            "PUT",
            account_path(cf, "/r2/buckets/" + BUCKET + "/objects/" + key),
            (p / key.split("/")[-1]).read_bytes(),
            "text/html; charset=utf-8",
        )
        if cf.object_digest(key) != m["files"][key.split("/")[-1]]:
            raise ValueError(
                "Uploaded report hash mismatch; keep protection and rollback"
            )
    journal["status"] = "APPLIED_AUTHENTICATED_VERIFICATION_PENDING"
    private_json(journal_path, journal)
    return {"status": journal["status"], "app_id": app["id"], "objects": len(KEYS)}


def rollback(cf, packet, m):
    p = Path(packet)
    path = p / "apply-journal.json"
    journal = json.loads(path.read_text())
    if journal["seal"] != m["seal"] or journal["head"] != m["head"]:
        raise ValueError("Journal belongs to a different packet")
    if journal.get("app_create_intent") and not journal["app_id"]:
        # An uncertain POST is never repeated. Recover its ID from the exact
        # unique name/path before deleting anything, or stop for manual audit.
        apps = cf.call("GET", account_path(cf, "/access/apps?per_page=100"))
        matches = [
            x
            for x in apps
            if x.get("name") == APP_NAME and x.get("destinations") == DESTINATIONS
        ]
        if len(matches) > 1 or len(apps) >= 100:
            raise ValueError("Ambiguous Access creation; manual audit needed")
        if matches:
            journal["app_id"] = matches[0]["id"]
            private_json(path, journal)
    # Never restore an unguarded old version while private objects survive.
    for key in journal["objects"]:
        if key not in KEYS:
            raise ValueError("Journal contains an unrelated object")
        if cf.object_exists(key):
            if cf.object_digest(key) != m["files"][key.split("/")[-1]]:
                raise ValueError(
                    "Object changed since apply; manual rollback review needed"
                )
            cf.call(
                "DELETE", account_path(cf, "/r2/buckets/" + BUCKET + "/objects/" + key)
            )
        if cf.object_exists(key):
            raise ValueError("Object survives deletion; keep protection in place")
    if cf.call(
        "GET",
        account_path(
            cf, "/r2/buckets/" + BUCKET + "/objects?prefix=preview&per_page=10"
        ),
    ):
        raise ValueError("Other preview objects remain; keep guarded Worker and Access")
    if journal["worker_uploaded"]:
        if cf.worker_digest() == m["files"]["worker.js"]:
            cf.call(
                "POST",
                script_path(cf, "/deployments"),
                {
                    "strategy": "percentage",
                    "versions": [
                        {"version_id": journal["origin"]["version"], "percentage": 100}
                    ],
                },
            )
        else:
            versions = cf.call("GET", script_path(cf, "/deployments"))["deployments"][
                0
            ]["versions"]
            if versions != [
                {"version_id": journal["origin"]["version"], "percentage": 100}
            ]:
                raise ValueError(
                    "Worker changed or upload uncertain; keep Access and inspect version"
                )
    if journal["aliases_disabled"]:
        cf.call("POST", script_path(cf, "/subdomain"), journal["origin"]["aliases"])
    if journal["app_id"]:
        app = cf.call("GET", account_path(cf, "/access/apps/" + journal["app_id"]))
        if app.get("name") != APP_NAME or app.get("destinations") != DESTINATIONS:
            raise ValueError(
                "Access application changed; manual rollback review needed"
            )
        cf.call("DELETE", account_path(cf, "/access/apps/" + journal["app_id"]))
    journal["status"] = "ROLLED_BACK"
    private_json(path, journal)
    return {"status": "ROLLED_BACK"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "preflight", "apply", "rollback"])
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--analytics", type=Path)
    parser.add_argument("--comments", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--seal")
    parser.add_argument("--review-head")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.action in ["apply", "rollback"] and not args.apply:
        parser.error("Provider mutation requires --apply and a reviewed head/seal")
    cf = CF(writable=args.action in ["apply", "rollback"] and args.apply)
    if args.action == "prepare":
        if not all([args.analytics, args.comments, args.bundle]):
            parser.error("prepare requires both documents and bundle")
        if args.packet.exists():
            raise ValueError("Use a new private packet directory")
        for source, key in [(args.analytics, KEYS[1]), (args.comments, KEYS[2])]:
            if (
                file_sha(source) != DOCUMENT_HASHES[key]
                or source.stat().st_size > 262144
            ):
                raise ValueError("Document differs from the approved Main revision")
        origin, _, _, _ = collect_origin(cf)
        head = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
        if subprocess.check_output(
            ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
        ).strip():
            raise ValueError("Commit and review a clean source head before preparing")
        args.packet.mkdir(mode=0o700)
        copies = [
            (ROOT / "templates/preview-index.html", "index.html"),
            (args.analytics, KEYS[1].split("/")[-1]),
            (args.comments, KEYS[2].split("/")[-1]),
            (args.bundle, "worker.js"),
        ]
        for src, name in copies:
            shutil.copyfile(src, args.packet / name)
            (args.packet / name).chmod(0o600)
        m = {
            "schema": 1,
            "head": head,
            "origin": origin,
            "files": {name: file_sha(args.packet / name) for _, name in copies},
        }
        m["seal"] = digest(m)
        private_json(args.packet / "manifest.json", m)
        print(
            json.dumps(
                {"status": "PREPARED_NO_WRITES", "head": head, "seal": m["seal"]}
            )
        )
        return
    m = validate_packet(args.packet, args.seal, args.review_head)
    if args.action == "preflight":
        origin, _, _, _ = collect_origin(cf)
        if origin != m["origin"]:
            raise ValueError("Origin/policy drift")
        print(json.dumps({"status": "PREFLIGHT_PASS_NO_WRITES", "seal": m["seal"]}))
    else:
        fd = os.open(args.packet / ".operation.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "apply":
                print(json.dumps(apply_packet(cf, args.packet, m)))
            else:
                print(json.dumps(rollback(cf, args.packet, m)))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        # Do not print upstream response bodies, policy contents or credentials.
        print(
            "STOP: " + str(exc)
            if isinstance(exc, ValueError)
            else "STOP: local/transport/configuration error"
        )
        raise SystemExit(2) from None
