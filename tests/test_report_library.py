import copy
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lib = load("report_library")
dataset = load("video_dataset")


def item(**kwargs):
    return {
        "path": lib.REPORTS[0],
        "title": "Informe de ejemplo",
        "published": "2026-11-26",
        "purpose": "Revisar los resultados observados.",
        "category": "redes",
        "coverage": "2022–2026",
        **kwargs,
    }


class LibraryTests(unittest.TestCase):
    def test_metadata_separates_publication_date_from_coverage(self):
        rendered = lib.render_library([item()])
        self.assertIn(
            '<time datetime="2026-11-26">26 de noviembre de 2026</time>', rendered
        )
        self.assertIn("<dt>Período analizado</dt><dd>2022–2026</dd>", rendered)
        self.assertNotIn("Finanzas y pagos", rendered)
        self.assertNotIn("{{", rendered)

    def test_only_populated_categories_and_functional_native_links(self):
        rows = [item(), item(path=lib.REPORTS[1], category="finanzas", coverage=None)]
        rendered = lib.render_library(rows)
        self.assertIn('href="#categoria-finanzas"', rendered)
        self.assertIn('id="categoria-finanzas"', rendered)
        self.assertIn("Finanzas y pagos", rendered)
        self.assertNotIn("Tecnología y proyectos", rendered)
        self.assertNotIn("<button", rendered)

    def test_empty_catalogue_has_honest_empty_state_and_no_fake_categories(self):
        rendered = lib.render_library([])
        self.assertIn("Aún no hay informes publicados", rendered)
        self.assertNotIn('class="categories"', rendered)
        self.assertNotIn("Leer informe", rendered)

    def test_optional_period_is_omitted_not_replaced_with_publication_date(self):
        self.assertNotIn("Período analizado", lib.render_library([item(coverage=None)]))

    def test_real_calendar_and_strict_iso_dates(self):
        self.assertEqual(lib.display_date("2024-02-29"), "29 de febrero de 2024")
        for value in ["2026-02-29", "2026-11-31", "26/11/2026", "2026-1-01", "", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                lib.validate_catalogue([item(published=value)])

    def test_metadata_escapes_html_and_attributes(self):
        rendered = lib.render_library(
            [
                item(
                    title='"<img onerror=x> & ejemplo',
                    purpose="<script>alert(1)</script>",
                )
            ]
        )
        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&quot;&lt;img onerror=x&gt;", rendered)

    def test_unsafe_or_unregistered_paths_duplicates_and_unknown_categories_refused(
        self,
    ):
        for value in [
            "preview/../secret.html",
            "preview/new.html",
            "preview/%2e.html",
            "/preview/index.html",
            "preview/videos.json",
            "https://evil.test/x",
            "preview/index.html",
        ]:
            with self.subTest(path=value), self.assertRaises(ValueError):
                lib.validate_catalogue([item(path=value)])
        with self.assertRaises(ValueError):
            lib.validate_catalogue([item(), item()])
        for value in ["publicidad", [], None]:
            with self.subTest(category=value), self.assertRaises(ValueError):
                lib.validate_catalogue([item(category=value)])

    def test_private_patterns_in_metadata_and_document_rejected(self):
        for value in [
            "staff@example.invalid",
            "192.168.1.2",
            "+51123456789",
            "123456789012",
            "Bearer some-token",
            "token=private",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                lib.render_library([item(purpose=value)])
            with self.assertRaises(ValueError):
                lib.SafeDocument().feed("<p>" + value + "</p>")

    def test_only_exact_canonical_tiktok_native_href_exempts_long_id(self):
        good = "https://www.tiktok.com/@mayahuasca.gracias/video/7000000000000000001"
        lib.SafeDocument().feed('<a href="' + good + '">Ver video</a>')
        for bad in [
            good + "?token=x",
            good + "#x",
            good.replace("www.tiktok.com", "www.tiktok.com.evil.test"),
            good.replace("https:", "http:"),
            good.replace("gracias", "other"),
            "javascript:alert(1)",
            "//evil.test",
            good.replace("/video/", "/video/%37"),
        ]:
            with self.subTest(value=bad), self.assertRaises(ValueError):
                lib.SafeDocument().feed('<a href="' + bad + '">Ver video</a>')
        with self.assertRaises(ValueError):
            lib.SafeDocument().feed('<a href="' + good + '">7000000000000000001</a>')

    def test_comparison_type_and_scope_are_distinct_from_a_period(self):
        rendered = lib.render_library(
            [item(coverage=None, type="Comparativa", scope="Capacidades de plataforma")]
        )
        self.assertIn("<dt>Tipo</dt><dd>Comparativa</dd>", rendered)
        self.assertIn("<dt>Alcance</dt><dd>Capacidades de plataforma</dd>", rendered)
        self.assertNotIn("Período analizado", rendered)

    def test_official_documentation_links_are_explicit_and_do_not_widen_tiktok_exception(
        self,
    ):
        for url in [
            "https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights",
            "https://developers.google.com/google-ads/api/docs/campaigns/overview",
            "https://www.ayrshare.com/docs/apis/ads/overview#supported-platforms",
        ]:
            lib.safe_link(url)
        for url in [
            "https://developers.google.com.evil.test/google-ads/api/docs/",
            "https://developers.facebook.com/redirect?url=bad",
            "https://developers.google.com/google-ads/api/../redirect",
            "https://www.ayrshare.com/docs/%2e%2e/redirect",
            "https://www.ayrshare.com/docs/apis/ads?token=example",
            "https://github.com/unrelated/project",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                lib.safe_link(url)

    def test_youtube_sources_are_plain_canonical_anchors_not_embeds_or_tracking_links(
        self,
    ):
        for url in [
            "https://www.youtube.com/watch?v=ABCDEFGHIJK",
            "https://www.youtube.com/channel/UC" + "A" * 22,
            "https://support.google.com/youtube/answer/9313698?hl=es",
        ]:
            lib.safe_link(url)
        for url in [
            "https://www.youtube.com/watch?v=ABCDEFGHIJK&token=private",
            "https://www.youtube.com/embed/ABCDEFGHIJK",
            "https://www.youtube.com.evil.test/watch?v=ABCDEFGHIJK",
            "https://support.google.com/youtube/answer/9313698?redirect=evil",
            "https://mayahuasca.com/preview/private.json",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                lib.safe_link(url)
        rendered = lib.markdown_document(
            "# Ejemplo\n\n## Anexo de método\n\nUna nota de método.", "Ejemplo"
        )
        self.assertIn(
            '<details class="report-appendix"><summary>Anexos y fuentes</summary>',
            rendered,
        )
        self.assertIn("<h2>Anexo de método</h2>", rendered)
        self.assertIn("Una nota de método.", rendered)

    def test_scripts_and_event_attributes_are_refused(self):
        for source in [
            "<script>x</script>",
            '<p onclick="x">x</p>',
            '<img src="https://evil.test/x">',
            "<iframe></iframe>",
            "<form></form>",
        ]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                lib.SafeDocument().feed(source)

    def test_document_retains_complete_original_body_markup_and_adds_brand_navigation(
        self,
    ):
        original = '<h1>Original</h1><p>42 vistas</p><article class="card"><h2>Resultado</h2><p>Texto &amp; datos.</p></article>'
        source = (
            "<html><head><title>Original</title></head><body><main>"
            + original
            + "</main></body></html>"
        )
        rendered = lib.render_report(item(), source)
        self.assertIn(original, rendered)
        self.assertIn('href="/preview/"', rendered)
        self.assertIn('id="informe"', rendered)

    def test_private_source_map_adds_reports_without_rewriting_the_layout_and_pins_each_hash(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalogue = root / "catalogue.json"
            catalogue.write_text(json.dumps([item(path=key) for key in lib.REPORTS]))
            originals = root / "originals"
            originals.mkdir()
            hashes, sources = {}, {}
            for key in lib.REPORTS:
                if key in lib.control.DOCUMENT_HASHES:
                    source = originals / key.split("/")[1]
                    source.write_text(
                        "<html><head><title>Original</title></head><body><main><h1>Original</h1><p>42 vistas</p></main></body></html>"
                    )
                    hashes[key] = lib.control.file_sha(source)
                else:
                    source = root / (key.split("/")[1] + ".md")
                    source.write_text(
                        "# Ejemplo\n\nUn informe adicional con datos observados."
                    )
                    sources[key] = {
                        "file": str(source),
                        "sha256": lib.control.file_sha(source),
                    }
            source_map = root / "sources.json"
            source_map.write_text(json.dumps(sources))
            with patch.dict(lib.control.DOCUMENT_HASHES, hashes, clear=True):
                lib.render(catalogue, originals, root / "rendered", sources=source_map)
                self.assertEqual(
                    len(list((root / "rendered").glob("*.html"))), len(lib.REPORTS) + 1
                )
                next(iter(sources.values()))["sha256"] = "0" * 64
                source_map.write_text(json.dumps(sources))
                with self.assertRaises(ValueError):
                    lib.render(
                        catalogue, originals, root / "refused", sources=source_map
                    )

    def test_markdown_renders_tables_and_safe_links_while_escaping_raw_html(self):
        source = '# Título\n\n<p onclick="bad">texto</p>\n\n| Video | Vistas |\n|---|---:|\n| [Ver](https://www.tiktok.com/@mayahuasca.gracias/video/7000000000000000001) | **42** |'
        rendered = lib.markdown_document(source, "Ejemplo")
        self.assertIn("&lt;p onclick=", rendered)
        self.assertNotIn("<p onclick=", rendered)
        self.assertIn('<th scope="col">Vistas</th>', rendered)
        self.assertIn('data-label="Vistas"><strong>42</strong>', rendered)
        self.assertIn("<span>Fuentes</span>", lib.inline("[Fuentes](SOURCES.md)"))
        self.assertNotIn("<a", lib.inline("[Fuentes](SOURCES.md)"))
        with self.assertRaises(ValueError):
            lib.inline("[Fuentes](../SOURCES.md)")
        with self.assertRaises(ValueError):
            lib.markdown_document("| A |\n|---|\n| B | C |", "Ejemplo")


class DatasetTests(unittest.TestCase):
    def rows(self):
        return [
            {
                "id": str(7000000000000000000 + i),
                "postUrl": "https://www.tiktok.com/@mayahuasca.gracias/video/"
                + str(7000000000000000000 + i),
                "post": "Educación #arte",
                "created": "2023-01-01T00:00:00Z",
                "videoDuration": "60",
                "videoViews": "100",
                "likeCount": "0",
                "commentsCount": "",
                "shareCount": "2",
                "favorites": "",
                "newFollowers": "",
                "averageTimeWatched": "0",
                "fullVideoWatchedRate": "0",
                "totalTimeWatched": "0",
                "reach": "0",
            }
            for i in range(1, 31)
        ]

    def compile(self, rows):
        return dataset.compile_rows(
            rows, [str(7000000000000000000 + i) for i in range(1, 31)]
        )

    def test_zeros_missing_units_and_queue_preserved(self):
        rows = self.rows()
        rows[1].update(
            averageTimeWatched="12.4",
            fullVideoWatchedRate="0.211",
            totalTimeWatched="1200",
            reach="87",
        )
        data, audit = self.compile(rows)
        first, second = data["videos"][:2]
        self.assertEqual(first["likes"], 0)
        self.assertIsNone(first["comments"])
        self.assertIsNone(first["saves"])
        self.assertIsNone(first["averageWatch"])
        self.assertEqual(second["averageWatch"], 12.4)
        self.assertEqual(second["completion"], 0.211)
        self.assertEqual(second["totalWatch"], 1200)
        self.assertEqual(second["candidate"], 2)
        self.assertEqual(first["tags"], ["#arte"])
        self.assertNotIn("profileViews", first)
        self.assertEqual(audit["candidates"], 30)

    def test_pii_redaction_is_explicit_and_raw_input_unchanged(self):
        rows = self.rows()
        rows[0]["post"] = "staff@example.invalid +51123456789"
        data, audit = self.compile(rows)
        self.assertEqual(audit["caption_redactions"], 2)
        self.assertNotIn("@", data["videos"][0]["caption"])
        self.assertEqual(rows[0]["post"], "staff@example.invalid +51123456789")

    def test_bad_native_links_metrics_and_dates_refused(self):
        for change in [
            {"postUrl": "javascript:x"},
            {"videoViews": "-1"},
            {"videoViews": "nan"},
            {"fullVideoWatchedRate": "21.1"},
            {"created": "2023-02-31T00:00:00Z"},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                rows = self.rows()
                rows[0].update(change)
                self.compile(rows)

    def test_candidate_membership_duplicates_and_size_bounds(self):
        rows = self.rows()
        with self.assertRaises(ValueError):
            dataset.compile_rows(rows, ["not-an-id"] * 30)
        with self.assertRaises(ValueError):
            self.compile(rows + [copy.deepcopy(rows[0])])
        with self.assertRaises(ValueError):
            self.compile(rows * 200)


if __name__ == "__main__":
    unittest.main()
