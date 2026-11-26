import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "update", Path(__file__).parents[1] / "scripts/preview_update.py"
)
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
spec = importlib.util.spec_from_file_location(
    "original_tests", Path(__file__).with_name("test_preview_control.py")
)
original_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original_tests)
c = u.c


class Fake(original_tests.Fake):
    def __init__(self):
        super().__init__()
        self.aliases = copy.deepcopy(u.DISABLED)
        self.version = u.LIVE_VERSION
        self.app = {
            "id": u.APP,
            "type": "self_hosted",
            "domain": c.HOST + "/preview",
            "aud": "synthetic-audience",
            "destinations": c.DESTINATIONS,
            **self.source_app,
        }
        policy, _, _ = c.inherited_policy(self.source_app, [self.policy])
        self.new_policies = [policy]
        self.bindings += [
            {
                "type": "plain_text",
                "name": "MAYA_PREVIEW_ACCESS_ISSUER",
                "text": "https://netuge.cloudflareaccess.com",
            },
            {
                "type": "plain_text",
                "name": "MAYA_PREVIEW_ACCESS_AUD",
                "text": self.app["aud"],
            },
            {"type": "secret_text", "name": "MAYA_PREVIEW_ALLOWED_EMAILS"},
        ]
        self.objects = {key: b"old-document" for key in c.KEYS}
        self.readback_wrong = False

    def call(self, method, path, body=None, content_type=None):
        if method == "GET" and path == c.account_path(self, "/access/apps/" + u.APP):
            self.events.append((method, path, None))
            return copy.deepcopy(self.app)
        if method == "GET" and path == c.account_path(
            self, "/access/apps/" + u.APP + "/policies"
        ):
            self.events.append((method, path, None))
            return copy.deepcopy(self.new_policies)
        if method in {"PUT", "DELETE"} and "/objects/" in path:
            self.events.append((method, path, body))
            if self.fail_at and self.fail_at(method, path):
                raise ValueError("Synthetic failure")
            assert self.aliases == u.DISABLED and self.app["id"] == u.APP
            key = path.split("/objects/")[1]
            if method == "PUT":
                self.objects[key] = body
            else:
                self.objects.pop(key, None)
            return {}
        if method == "POST" and path.endswith("/deployments"):
            self.events.append((method, path, copy.deepcopy(body)))
            assert set(self.objects) == set(c.KEYS)
            assert all(v == b"old-document" for v in self.objects.values())
            self.version = body["versions"][0]["version_id"]
            self.bundle = b"old-worker"
            return {}
        return super().call(method, path, body, content_type)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        self.cf = Fake()
        policy, _, idps = c.inherited_policy(self.cf.source_app, [self.cf.policy])
        domains = self.cf.call("GET", c.account_path(self.cf, "/workers/domains"))
        domains.sort(key=lambda x: x["hostname"])
        self.old = {
            "origin": {
                "staff_policy_sha256": c.digest({"policy": policy, "idps": idps}),
                "custom_domains": domains,
                "issuer": "https://netuge.cloudflareaccess.com",
            },
            "files": {"worker.js": c.LIVE_WORKER_SHA},
        }
        before, _ = u.state(self.cf, self.old)
        for key in u.REGISTERED:
            (self.p / key.split("/")[1]).write_bytes(
                b"sealed-worker" if key.endswith(".js") else b"new-document"
            )
        for key in c.KEYS:
            (self.p / ("before-" + key.split("/")[1])).write_bytes(b"old-document")
        (self.p / "worker.js").write_bytes(b"sealed-worker")
        self.m = {
            "seal": "synthetic",
            "head": "synthetic-head",
            "before": before,
            "previous": {
                key: self.cf.object_digest(key) if key in c.KEYS else None
                for key in u.REGISTERED
            },
            "files": {p.name: c.file_sha(p) for p in self.p.iterdir()},
        }
        self.cf.events.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def mutations(self):
        return [e for e in self.cf.events if e[0] != "GET"]

    def test_preflight_reads_only_and_does_not_modify_original_installation(self):
        u.preflight(self.cf, self.m, self.old)
        self.assertEqual(self.mutations(), [])

    def test_update_keeps_existing_app_audience_aliases_and_publishes_index_last(self):
        result = u.update(self.cf, self.p, self.m, self.old)
        self.assertEqual(result["objects"], len(u.REGISTERED))
        self.assertEqual(self.cf.app["id"], u.APP)
        self.assertEqual(self.cf.aliases, u.DISABLED)
        events = self.mutations()
        self.assertTrue(events[0][1].endswith("/" + c.WORKER))
        self.assertTrue(events[-1][1].endswith("/preview/index.html"))
        self.assertFalse(
            any("/access/" in e[1] or "/subdomain" in e[1] for e in events)
        )
        self.assertEqual((self.p / "update-journal.json").stat().st_mode & 0o777, 0o600)

    def test_baseline_drift_stops_before_any_write(self):
        for mutate in [
            lambda: setattr(self.cf, "version", "other-version"),
            lambda: self.cf.objects.update({"preview/index.html": b"changed"}),
        ]:
            with self.subTest(mutate=mutate):
                before = copy.deepcopy(self.cf.__dict__)
                mutate()
                with self.assertRaises(ValueError):
                    u.update(self.cf, self.p, self.m, self.old)
                self.assertEqual(self.mutations(), [])
                self.cf.__dict__ = before

    def test_alias_public_bucket_other_reader_and_staff_change_fail_closed(self):
        for field, value in [
            ("aliases", {"enabled": True, "previews_enabled": False}),
            ("managed", {"enabled": True}),
            ("other_bucket_worker", True),
            ("custom_previews", True),
        ]:
            with (
                self.subTest(field=field),
                patch.object(self.cf, field, value),
                self.assertRaises(ValueError),
            ):
                u.preflight(self.cf, self.m, self.old)
        self.cf.policy["include"].append({"email": {"email": "third@example.invalid"}})
        with self.assertRaises(ValueError):
            u.preflight(self.cf, self.m, self.old)
        self.assertEqual(self.mutations(), [])

    def test_rollback_restores_only_protected_baseline_after_removing_new_assets(self):
        u.update(self.cf, self.p, self.m, self.old)
        u.rollback(self.cf, self.p, self.m, self.old)
        self.assertEqual(self.cf.version, u.LIVE_VERSION)
        self.assertEqual(set(self.cf.objects), set(c.KEYS))
        self.assertEqual(self.cf.aliases, u.DISABLED)
        self.assertEqual(self.cf.app["id"], u.APP)
        self.assertEqual(self.mutations()[-1][0], "POST")

    def test_changed_object_or_worker_prevents_rollback_mutations(self):
        u.update(self.cf, self.p, self.m, self.old)
        self.cf.objects["preview/index.html"] = b"another-owner"
        self.cf.events.clear()
        with self.assertRaises(ValueError):
            u.rollback(self.cf, self.p, self.m, self.old)
        self.assertEqual(self.mutations(), [])

    def test_reapply_refused(self):
        u.update(self.cf, self.p, self.m, self.old)
        self.cf.events.clear()
        with self.assertRaises(ValueError):
            u.update(self.cf, self.p, self.m, self.old)
        self.assertEqual(self.mutations(), [])

    def test_lost_upload_response_is_journaled_and_can_rollback(self):
        original = self.cf.call

        def lose_response(method, path, body=None, content_type=None):
            result = original(method, path, body, content_type)
            if method == "PUT" and path.endswith("/preview/videos.json"):
                raise ValueError("Lost response")
            return result

        with (
            patch.object(self.cf, "call", side_effect=lose_response),
            self.assertRaises(ValueError),
        ):
            u.update(self.cf, self.p, self.m, self.old)
        self.assertIn(
            "preview/videos.json",
            json.loads((self.p / "update-journal.json").read_text())["objects"],
        )
        u.rollback(self.cf, self.p, self.m, self.old)
        self.assertEqual(self.cf.version, u.LIVE_VERSION)

    def test_failed_asset_removal_never_restores_previous_worker(self):
        u.update(self.cf, self.p, self.m, self.old)
        self.cf.fail_at = lambda method, path: (
            method == "DELETE" and path.endswith("/preview/videos.json")
        )
        with self.assertRaises(ValueError):
            u.rollback(self.cf, self.p, self.m, self.old)
        self.assertNotEqual(self.cf.version, u.LIVE_VERSION)
        self.assertEqual(self.cf.aliases, u.DISABLED)

    def test_lost_worker_response_can_restore_protected_original(self):
        original = self.cf.call

        def lose_response(method, path, body=None, content_type=None):
            result = original(method, path, body, content_type)
            if method == "PUT" and path.endswith("/" + c.WORKER):
                raise ValueError("Lost worker response")
            return result

        with (
            patch.object(self.cf, "call", side_effect=lose_response),
            self.assertRaises(ValueError),
        ):
            u.update(self.cf, self.p, self.m, self.old)
        u.rollback(self.cf, self.p, self.m, self.old)
        self.assertEqual(self.cf.version, u.LIVE_VERSION)

    def test_prepare_and_validate_seals_live_baseline_original_journal_and_exact_files(
        self,
    ):
        original = self.p / "original"
        original.mkdir()
        (original / "apply-journal.json").write_text('{"original":"unchanged"}')
        for key in c.KEYS:
            (original / key.split("/")[1]).write_bytes(b"old-document")
            self.old["files"][key.split("/")[1]] = c.file_sha(
                original / key.split("/")[1]
            )
        catalogue = self.p / "catalogue.json"
        catalogue.write_text(
            json.dumps(
                [
                    {
                        "path": key,
                        "title": "Ejemplo",
                        "published": "2026-11-26",
                        "purpose": "Revisar resultados",
                        "coverage": None,
                        "category": "redes",
                    }
                    for key in u.library.REPORTS
                ]
            )
        )
        packet = self.p / "packet"
        with (
            patch.object(u, "clean_head", return_value="synthetic-head"),
            patch.object(u, "original_manifest", return_value=self.old),
        ):
            manifest = u.prepare(
                self.cf, packet, original, self.p, catalogue, self.p / "worker.js"
            )
            self.assertEqual(self.mutations(), [])
            self.assertEqual(manifest["before"]["version"], u.LIVE_VERSION)
            self.assertEqual(
                manifest["original_journal_sha256"],
                c.file_sha(original / "apply-journal.json"),
            )
            self.assertEqual(packet.stat().st_mode & 0o777, 0o700)
            u.validate(packet, manifest["seal"], "synthetic-head")
            with self.assertRaises(ValueError):
                u.validate(packet, "wrong-seal", "synthetic-head")
            (packet / "videos.json").write_text("tampered")
            with self.assertRaises(ValueError):
                u.validate(packet, manifest["seal"], "synthetic-head")

    def test_unregistered_provider_path_refused(self):
        with self.assertRaises(ValueError):
            u.object_path(self.cf, "preview/arbitrary-private.csv")


if __name__ == "__main__":
    unittest.main()
