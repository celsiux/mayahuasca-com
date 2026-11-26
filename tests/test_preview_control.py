import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "control", Path(__file__).parents[1] / "scripts/preview-control.py"
)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class Fake:
    account = "synthetic-account"

    def __init__(self):
        self.events = []
        self.objects = {}
        self.aliases = {"enabled": True, "previews_enabled": True}
        self.managed = {"enabled": False}
        self.custom = {"domains": []}
        self.source_app = {
            "allowed_idps": ["google-id", "pin-id"],
            "session_duration": "24h",
        }
        self.policy = {
            "id": c.SOURCE_POLICY,
            "name": "Maya staff",
            "decision": "allow",
            "include": [
                {"email": {"email": "one@example.invalid"}},
                {"email": {"email": "two@example.invalid"}},
            ],
            "exclude": [],
            "require": [],
        }
        self.version = c.LIVE_VERSION
        self.bundle = b"old-worker"
        self.app = None
        self.new_policies = []
        self.bindings = [
            {"type": "r2_bucket", "name": "SITE_BUCKET", "bucket_name": c.BUCKET}
        ]
        self.fail_at = None
        self.provider_drift = False
        self.other_bucket_worker = False
        self.custom_previews = False

    def object_exists(self, key):
        return key in self.objects

    def object_digest(self, key):
        return hashlib.sha256(self.objects[key]).hexdigest()

    def worker_digest(self):
        if self.bundle == b"old-worker":
            return c.LIVE_WORKER_SHA
        return hashlib.sha256(self.bundle).hexdigest()

    def call(self, method, path, body=None, content_type=None):
        self.events.append((method, path, copy.deepcopy(body)))
        if self.fail_at and self.fail_at(method, path):
            raise ValueError("Synthetic provider failure")
        prefix = c.account_path(self, "")
        tail = path.removeprefix(prefix)
        if method == "GET":
            if tail == "/access/apps/" + c.SOURCE_APP:
                return copy.deepcopy(self.source_app)
            if tail == "/access/apps/" + c.SOURCE_APP + "/policies":
                return [copy.deepcopy(self.policy)]
            if tail == "/access/identity_providers":
                return [
                    {"id": "google-id", "type": "google"},
                    {"id": "pin-id", "type": "onetimepin"},
                ]
            if tail == "/access/organizations":
                return {"auth_domain": "netuge.cloudflareaccess.com"}
            if tail == "/access/apps?per_page=100":
                return [copy.deepcopy(self.app)] if self.app else []
            if tail == "/r2/buckets/maya-site/domains/managed":
                return self.managed
            if tail == "/r2/buckets/maya-site/domains/custom":
                return self.custom
            if tail.startswith("/r2/buckets/maya-site/objects?"):
                return list(self.objects)
            if tail == "/workers/scripts":
                return [{"id": c.WORKER}] + (
                    [{"id": "other"}] if self.other_bucket_worker else []
                )
            if tail == "/workers/domains":
                return [
                    {
                        "hostname": h,
                        "service": c.WORKER,
                        "id": h,
                        "enabled": True,
                        "previews_enabled": self.custom_previews,
                        "environment": "production",
                    }
                    for h in [c.HOST, "www." + c.HOST, "new." + c.HOST]
                ]
            if tail.endswith("/deployments"):
                return {
                    "deployments": [
                        {"versions": [{"version_id": self.version, "percentage": 100}]}
                    ]
                }
            if tail.endswith("/settings"):
                return {
                    "bindings": copy.deepcopy(self.bindings),
                    "compatibility_date": "2026-10-22",
                    "compatibility_flags": [],
                    "placement": {},
                    "logpush": False,
                    "tail_consumers": [],
                    "tags": [],
                    "usage_model": "standard",
                }
            if tail.endswith("/subdomain"):
                return copy.deepcopy(self.aliases)
            if tail == "/access/apps/created-app":
                app = copy.deepcopy(self.app)
                if self.provider_drift:
                    app["allowed_idps"] = ["different-idp"]
                return app
            if tail == "/access/apps/created-app/policies":
                return copy.deepcopy(self.new_policies)
        if method == "POST" and tail == "/access/apps":
            self.app = {**body, "id": "created-app", "aud": "created-audience"}
            return copy.deepcopy(self.app)
        if method == "POST" and tail == "/access/apps/created-app/policies":
            self.new_policies = [copy.deepcopy(body)]
            return {"id": "created-policy"}
        if method == "POST" and tail.endswith("/subdomain"):
            self.aliases = copy.deepcopy(body)
            return {}
        if method == "PUT" and tail == "/workers/scripts/" + c.WORKER:
            data = body.split(b"\r\n\r\n", 1)[1]
            meta = json.loads(data.split(b"\r\n--", 1)[0])
            self.bindings = meta["bindings"]
            for b in self.bindings:
                if b["type"] == "secret_text":
                    b.pop("text")
            self.bundle = b"sealed-worker"
            self.version = "new-version"
            return {}
        if method == "PUT" and "/objects/" in tail:
            # This assertion directly catches unsafe apply ordering.
            assert self.aliases == {"enabled": False, "previews_enabled": False}
            assert self.bundle == b"sealed-worker" and self.new_policies
            self.objects[tail.split("/objects/")[1]] = body
            return {}
        if method == "DELETE" and "/objects/" in tail:
            self.objects.pop(tail.split("/objects/")[1], None)
            return {}
        if method == "POST" and tail.endswith("/deployments"):
            assert not self.objects
            self.version = body["versions"][0]["version_id"]
            return {}
        if method == "DELETE" and tail == "/access/apps/created-app":
            self.app = None
            return {}
        raise AssertionError((method, tail))


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        self.cf = Fake()
        origin, *_ = c.collect_origin(self.cf)
        for key in c.KEYS:
            (self.p / key.split("/")[-1]).write_bytes(b"private-document")
        (self.p / "worker.js").write_bytes(b"sealed-worker")
        self.m = {
            "seal": "synthetic-seal",
            "head": "synthetic-head",
            "origin": origin,
            "files": {f.name: c.file_sha(f) for f in self.p.iterdir()},
        }
        self.cf.events = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_preflight_never_mutates(self):
        c.collect_origin(self.cf)
        self.assertTrue(all(e[0] == "GET" for e in self.cf.events))

    def test_exact_policy_inherited_not_a_new_audience(self):
        _, policy, emails, idps = c.collect_origin(self.cf)
        self.assertEqual(policy["include"], self.cf.policy["include"])
        self.assertEqual(len(emails), 2)
        self.assertEqual(idps, self.cf.source_app["allowed_idps"])

    def test_expanded_policy_refused_before_writes(self):
        self.cf.policy["include"].append({"email": {"email": "extra@example.invalid"}})
        with self.assertRaises(ValueError):
            c.collect_origin(self.cf)
        self.assertTrue(all(e[0] == "GET" for e in self.cf.events))

    def test_bypass_policy_refused(self):
        self.cf.policy["decision"] = "bypass"
        with self.assertRaises(ValueError):
            c.collect_origin(self.cf)

    def test_public_r2_refused(self):
        self.cf.managed["enabled"] = True
        with self.assertRaises(ValueError):
            c.collect_origin(self.cf)

    def test_custom_domain_preview_urls_refused(self):
        self.cf.custom_previews = True
        with self.assertRaises(ValueError):
            c.collect_origin(self.cf)

    def test_custom_r2_public_origin_refused(self):
        self.cf.custom["domains"] = [{"domain": "assets.example.invalid"}]
        with self.assertRaises(ValueError):
            c.collect_origin(self.cf)

    def test_other_bucket_consumer_refused(self):
        self.cf.other_bucket_worker = True
        with self.assertRaises(ValueError):
            c.collect_origin(self.cf)

    def test_existing_preview_not_overwritten(self):
        self.cf.objects["preview/other-report.html"] = b"other-report"
        with self.assertRaises(ValueError):
            c.collect_origin(self.cf)

    def test_provider_state_drift_stops_apply(self):
        self.cf.version = "somebody-else-version"
        with self.assertRaises(ValueError):
            c.apply_packet(self.cf, self.p, self.m)
        self.assertTrue(all(e[0] == "GET" for e in self.cf.events))

    def test_apply_order_and_no_public_website_upload(self):
        result = c.apply_packet(self.cf, self.p, self.m)
        self.assertEqual(result["objects"], 3)
        self.assertEqual(set(self.cf.objects), set(c.KEYS))
        self.assertEqual(self.cf.aliases, {"enabled": False, "previews_enabled": False})
        self.assertEqual(self.cf.new_policies[0]["include"], self.cf.policy["include"])
        self.assertEqual(self.cf.app["destinations"], c.DESTINATIONS)
        self.assertTrue(
            all("/dns_records" not in path for _, path, _ in self.cf.events)
        )
        self.assertEqual((self.p / "apply-journal.json").stat().st_mode & 0o777, 0o600)

    def test_application_readback_drift_stops_before_upload(self):
        self.cf.provider_drift = True
        with self.assertRaises(ValueError):
            c.apply_packet(self.cf, self.p, self.m)
        self.assertFalse(self.cf.objects)
        self.assertEqual(self.cf.bundle, b"old-worker")

    def test_failure_disabling_alternatives_never_uploads_documents(self):
        self.cf.fail_at = lambda method, path: (
            method == "POST" and path.endswith("/subdomain")
        )
        with self.assertRaises(ValueError):
            c.apply_packet(self.cf, self.p, self.m)
        self.assertFalse(self.cf.objects)
        self.assertEqual(self.cf.bundle, b"old-worker")

    def test_worker_readback_mismatch_never_uploads_documents(self):
        with patch.object(self.cf, "worker_digest", return_value="wrong"):
            with self.assertRaises(ValueError):
                c.apply_packet(self.cf, self.p, self.m)
        self.assertFalse(self.cf.objects)

    def test_rollback_deletes_documents_before_old_version(self):
        c.apply_packet(self.cf, self.p, self.m)
        c.rollback(self.cf, self.p, self.m)
        self.assertFalse(self.cf.objects)
        self.assertEqual(self.cf.version, c.LIVE_VERSION)
        self.assertEqual(self.cf.aliases, {"enabled": True, "previews_enabled": True})
        self.assertIsNone(self.cf.app)

    def test_failed_delete_keeps_guard_and_alternatives_disabled(self):
        c.apply_packet(self.cf, self.p, self.m)
        self.cf.fail_at = lambda method, path: (
            method == "DELETE" and "/objects/" in path
        )
        with self.assertRaises(ValueError):
            c.rollback(self.cf, self.p, self.m)
        self.assertEqual(self.cf.version, "new-version")
        self.assertFalse(self.cf.aliases["enabled"])
        self.assertIsNotNone(self.cf.app)

    def test_changed_report_requires_manual_rollback_review(self):
        c.apply_packet(self.cf, self.p, self.m)
        self.cf.objects[c.KEYS[0]] = b"somebody-else-edit"
        with self.assertRaises(ValueError):
            c.rollback(self.cf, self.p, self.m)
        self.assertEqual(self.cf.version, "new-version")
        self.assertIsNotNone(self.cf.app)

    def test_reapply_refused(self):
        c.apply_packet(self.cf, self.p, self.m)
        with self.assertRaises(ValueError):
            c.apply_packet(self.cf, self.p, self.m)

    def test_remaining_preview_objects_prevent_unguarded_rollback(self):
        c.apply_packet(self.cf, self.p, self.m)
        self.cf.objects["preview/later-report.html"] = b"later private content"
        with self.assertRaises(ValueError):
            c.rollback(self.cf, self.p, self.m)
        self.assertEqual(self.cf.version, "new-version")
        self.assertIsNotNone(self.cf.app)

    def test_uncertain_upload_that_did_not_land_can_restore_old_state(self):
        self.cf.fail_at = lambda method, path: (
            method == "PUT" and path.endswith("/" + c.WORKER)
        )
        with self.assertRaises(ValueError):
            c.apply_packet(self.cf, self.p, self.m)
        self.cf.fail_at = None
        c.rollback(self.cf, self.p, self.m)
        self.assertFalse(self.cf.objects)
        self.assertEqual(self.cf.version, c.LIVE_VERSION)
        self.assertTrue(self.cf.aliases["enabled"])

    def test_lost_object_upload_response_is_covered_by_journal(self):
        original = self.cf.call

        def lose_response(method, path, body=None, content_type=None):
            result = original(method, path, body, content_type)
            if method == "PUT" and "/objects/" in path:
                raise ValueError("Synthetic lost response")
            return result

        with patch.object(self.cf, "call", side_effect=lose_response):
            with self.assertRaises(ValueError):
                c.apply_packet(self.cf, self.p, self.m)
        self.assertEqual(len(self.cf.objects), 1)
        c.rollback(self.cf, self.p, self.m)
        self.assertFalse(self.cf.objects)


if __name__ == "__main__":
    unittest.main()
