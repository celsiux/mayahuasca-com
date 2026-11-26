"""Local-only browser checks for privately rendered report bytes; no live login."""

import argparse
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE_CSP = re.search(r'"(default-src[^"\n]+)"', (ROOT / "src/preview.js").read_text())[
    1
]
EXPLORER_CSP = (
    BASE_CSP
    + "; script-src https://mayahuasca.com/preview/video-explorer.js; connect-src https://mayahuasca.com/preview/videos.json"
)


def run(stage, evidence):
    evidence.mkdir(mode=0o700, exist_ok=True)
    dataset = json.loads((stage / "videos.json").read_text())
    assert len(dataset["videos"]) == 3284
    requests, external, checks = [], [], []
    fail = {"once": False}
    injection = {"enabled": False}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        context = browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=1
        )

        def route(request):
            url = request.request.url
            if not url.startswith("https://mayahuasca.com/preview/"):
                external.append(url)
                request.abort()
                return
            key = url.split("/preview/", 1)[1].split("?", 1)[0] or "index.html"
            requests.append(key)
            path = stage / key
            if path.name != key or not path.is_file():
                request.fulfill(status=404, body="Not found")
                return
            if key == "videos.json" and fail["once"]:
                fail["once"] = False
                request.fulfill(status=503, body="Unavailable")
                return
            body = path.read_bytes()
            if key == "videos.json" and injection["enabled"]:
                data = json.loads(body)
                data["videos"][0]["caption"] = (
                    "<img src=x onerror=alert(1)> texto literal"
                )
                data["videos"][0]["views"] = 999999999
                body = json.dumps(data).encode()
            content_type = (
                "application/json"
                if key.endswith(".json")
                else "application/javascript"
                if key.endswith(".js")
                else "text/html"
            )
            request.fulfill(
                body=body,
                headers={
                    "Content-Type": content_type + "; charset=utf-8",
                    "Cache-Control": "private, no-store, max-age=0",
                    "Content-Security-Policy": EXPLORER_CSP
                    if key == "videos.html"
                    else BASE_CSP,
                },
            )

        context.route("**/*", route)
        page = context.new_page()
        page.set_default_timeout(10000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        paths = [
            "index.html",
            "maya-tiktok-rendimiento-20261126.html",
            "maya-tiktok-comentarios-20261126.html",
            "maya-tiktok-historico.html",
            "videos.html",
        ]
        for width in [360, 390, 768, 1280]:
            page.set_viewport_size({"width": width, "height": 844})
            for path in paths:
                page.goto("https://mayahuasca.com/preview/" + path)
                if path == "videos.html":
                    page.locator(".video-card").first.wait_for()
                    assert page.locator(".video-card").count() == 24
                    assert page.locator(".video-primary dd").evaluate_all(
                        "nodes => nodes.every(n => n.scrollWidth <= n.clientWidth)"
                    )
                dimensions = page.evaluate(
                    "({body:document.body.scrollWidth, root:document.documentElement.scrollWidth, viewport:innerWidth})"
                )
                assert dimensions["root"] <= width and dimensions["body"] <= width, (
                    path,
                    dimensions,
                )
                assert page.locator("h1:visible").count() == 1
                assert page.locator(
                    "input:not([type=hidden]),select,button"
                ).evaluate_all(
                    "(nodes) => nodes.every(n => n.labels?.length || n.textContent.trim())"
                )
                checks.append(
                    {
                        "width": width,
                        "path": path,
                        "dimensions": dimensions,
                        "visible_h1": 1,
                    }
                )
                if width == 390:
                    page.screenshot(
                        path=str(evidence / (path.replace(".html", "") + "-390.png")),
                        full_page=path == "index.html",
                    )
                    if path == "maya-tiktok-historico.html":
                        page.locator(
                            ".history-table"
                        ).first.scroll_into_view_if_needed()
                        page.screenshot(path=str(evidence / "historical-table-390.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto("https://mayahuasca.com/preview/")
        page.keyboard.press("Tab")
        assert page.locator(":focus").inner_text() == "Ir a los informes"
        page.locator(".categories a").first.click()
        assert page.url.endswith("#categoria-redes")
        page.get_by_role(
            "link", name="Histórico de TikTok y prioridades de clipping", exact=True
        ).click()
        page.get_by_role(
            "link", name="Explorar todos los videos y buscar próximos clips ↗"
        ).click()
        page.locator(".video-card").first.wait_for()
        page.locator(".video-card").first.scroll_into_view_if_needed()
        page.screenshot(path=str(evidence / "explorer-cards-390.png"))
        assert "3,284" in page.locator(
            "#video-status"
        ).inner_text() or "3284" in page.locator("#video-status").inner_text().replace(
            ".", ""
        ).replace(",", "")
        page.get_by_label("Año", exact=True).select_option("2023")
        assert "138" in page.locator("#video-status").inner_text()
        page.get_by_role("button", name="Siguiente →").click()
        assert page.locator("#page-number").inner_text() == "Página 2 de 6"
        assert page.locator(":focus").get_attribute("id") == "video-status"
        page.get_by_label("Buscar en la descripción").fill("xyz-no-such-caption-zz")
        assert page.locator(".video-card").count() == 0
        assert "No hay videos" in page.locator("#video-results").inner_text()
        page.get_by_role("button", name="Restablecer filtros").click()
        page.wait_for_function('document.querySelectorAll(".video-card").length === 24')
        page.get_by_label("Solo los 30 candidatos de clipping").check()
        assert "30 videos" in page.locator("#video-status").inner_text()
        page.get_by_label("Ordenar por").select_option("oldest")
        assert (
            page.locator(".video-top time")
            .first.get_attribute("datetime")
            .startswith("2022")
        )
        page.locator(".video-card summary").first.click()
        assert page.locator(".video-detail").first.is_visible()
        assert "Tiempo medio visto" in page.locator(".video-detail").first.inner_text()
        page.screenshot(path=str(evidence / "explorer-details-390.png"))
        page.get_by_role("button", name="Restablecer filtros").click()
        page.wait_for_function('!document.querySelector("#video-candidates").checked')
        tag = page.locator("#video-tag option").nth(1).get_attribute("value")
        page.get_by_label("Hashtags frecuentes").select_option(tag)
        expected = sum(tag in row["tags"] for row in dataset["videos"])
        assert str(expected) in page.locator("#video-status").inner_text()
        fail["once"] = True
        page.reload()
        page.get_by_role("button", name="Volver a intentar").wait_for()
        assert "No se pudieron cargar" in page.locator("#video-status").inner_text()
        page.get_by_role("button", name="Volver a intentar").click()
        page.locator(".video-card").first.wait_for()
        injection["enabled"] = True
        page.reload()
        page.locator(".video-card").first.wait_for()
        assert (
            "<img src=x onerror=alert(1)>"
            in page.locator(".video-card h2").first.inner_text()
        )
        assert page.locator("img,iframe").count() == 0
        assert not errors, errors
        assert not external, external
        browser.close()
    result = {
        "status": "PASS_LOCAL_ONLY",
        "responsive": checks,
        "cards_per_page": 24,
        "dataset_rows": 3284,
        "candidates": 30,
        "functional_checks": [
            "category anchor",
            "library→report→explorer",
            "keyboard skip link",
            "year filter",
            "pagination/focus",
            "empty search",
            "reset",
            "candidate filter",
            "date sort",
            "details",
            "caption hashtag",
            "load error/retry",
            "caption HTML injection rendered as text",
        ],
        "external_requests": external,
        "page_errors": errors,
        "requested_resource_types": sorted(set(requests)),
    }
    (evidence / "browser-results.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                "status": result["status"],
                "responsive_checks": len(checks),
                "functional_checks": len(result["functional_checks"]),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    run(args.stage, args.evidence)
