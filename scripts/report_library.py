#!/usr/bin/env python3
"""Offline presentation of explicitly registered, privately supplied reports."""

import argparse
from datetime import date
import html
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "preview_control", ROOT / "scripts/preview-control.py"
)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
CATEGORIES = {
    "redes": "Redes y contenido",
    "finanzas": "Finanzas y pagos",
    "operacion": "Operación y atención",
    "tecnologia": "Tecnología y proyectos",
}
REGISTERED = json.loads((ROOT / "src/report-files.json").read_text())
REPORTS = [
    key
    for key in REGISTERED
    if key.startswith("preview/maya-") and key.endswith(".html")
]
MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


TIKTOK = re.compile(r"https://www\.tiktok\.com/@mayahuasca\.gracias/video/[1-9]\d{18}")
FORBIDDEN = [
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"\+\d[\d \-]{7,}\d|\b\d{10,}\b"),
    re.compile(
        r"(?:Bearer\s+|eyJ[a-zA-Z0-9_-]+\.eyJ|-----BEGIN .*PRIVATE KEY|(?:api[_-]?key|token|secret)\s*[=:]\s*\S+)",
        re.I,
    ),
]


def private_guard(value):
    if any(rx.search(value) for rx in FORBIDDEN):
        raise ValueError("Private identifier or credential pattern in publication")


def safe_link(value):
    if TIKTOK.fullmatch(value):
        return
    if value.startswith(("https://www.ayrshare.com/docs/", "#")) and not any(
        c in value for c in '<>"\\\r\n'
    ):
        private_guard(value)
        return
    raise ValueError("Only canonical native TikTok and documentation links are allowed")


def text(value, limit=240):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Invalid catalogue text")
    private_guard(value)
    return value


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use an ISO publication date")
    return date.fromisoformat(value)


def display_date(value):
    d = iso_date(value)
    return f"{d.day} de {MONTHS[d.month - 1]} de {d.year}"


def validate_catalogue(items):
    if not isinstance(items, list):
        raise ValueError("Catalogue must be an array")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "title",
            "published",
            "purpose",
            "category",
            "coverage",
        }:
            raise ValueError("Unexpected catalogue fields")
        path = item["path"]
        if (
            not isinstance(path, str)
            or not re.fullmatch(r"preview/[a-z0-9]+(?:-[a-z0-9]+)*\.html", path)
            or path not in REPORTS
            or path in seen
        ):
            raise ValueError("Report path must be unique and explicitly registered")
        seen.add(path)
        text(item["title"], 140)
        text(item["purpose"])
        iso_date(item["published"])
        if not isinstance(item["category"], str) or item["category"] not in CATEGORIES:
            raise ValueError("Unknown category")
        if item["coverage"] is not None:
            text(item["coverage"])
    return sorted(items, key=lambda x: (x["published"], x["path"]), reverse=True)


def esc(value):
    return html.escape(value, quote=True)


def metadata(item):
    coverage = (
        f"<div><dt>Período analizado</dt><dd>{esc(item['coverage'])}</dd></div>"
        if item["coverage"]
        else ""
    )
    return (
        f'<dl class="report-meta"><div><dt>Publicado</dt><dd><time datetime="{item["published"]}">'
        f"{display_date(item['published'])}</time></dd></div>{coverage}</dl>"
    )


def brand():
    return '<header class="brand"><a href="/preview/" aria-label="Mayahuasca · Biblioteca de informes"><span class="brand-mark" aria-hidden="true">m</span><span>mayahuasca<span class="brand-note">Biblioteca privada</span></span></a></header>'


def page(title, content, page_class="library"):
    template = (ROOT / "templates/preview-index.html").read_text()
    return (
        template.replace("{{TITLE}}", esc(title))
        .replace("{{STYLE}}", (ROOT / "templates/report-library.css").read_text())
        .replace("{{CLASS}}", page_class)
        .replace("{{CONTENT}}", brand() + content)
    )


def render_library(items):
    items = validate_catalogue(items)
    groups = [
        (key, label, [x for x in items if x["category"] == key])
        for key, label in CATEGORIES.items()
    ]
    groups = [(key, label, rows) for key, label, rows in groups if rows]
    navigation = (
        (
            '<nav class="categories" aria-label="Categorías de informes">'
            + "".join(
                f'<a href="#categoria-{key}">{label}</a>' for key, label, _ in groups
            )
            + "</nav>"
        )
        if groups
        else ""
    )
    sections = []
    for key, label, rows in groups:
        cards = "".join(
            f'<article class="report-card"><span class="category-label">{label}</span><h3><a href="/{item["path"]}">{esc(item["title"])}</a></h3><p class="purpose">{esc(item["purpose"])}</p>{metadata(item)}<a class="read-report" href="/{item["path"]}" aria-label="Leer informe: {esc(item["title"])}">Leer informe <span aria-hidden="true">↗</span></a></article>'
            for item in rows
        )
        sections.append(
            f'<section class="category-section" id="categoria-{key}" aria-labelledby="titulo-{key}"><div class="section-heading"><h2 id="titulo-{key}">{label}</h2><span>{len(rows)} {"informe" if len(rows) == 1 else "informes"}</span></div><div class="report-grid">{cards}</div></section>'
        )
    body = (
        "".join(sections)
        or '<section class="empty"><h2>Aún no hay informes publicados</h2><p>Los informes aparecerán aquí cuando estén listos para consultar.</p></section>'
    )
    return page(
        "Informes de Maya",
        '<main id="contenido"><section class="intro"><p class="eyebrow">Mayahuasca · Informes</p><h1>Una mirada clara.<br><em>El siguiente paso.</em></h1><p>Informes para entender lo que pasa y orientar las próximas acciones.</p></section>'
        + navigation
        + body
        + '</main><footer class="library-footer">Mayahuasca · Un espacio para consultar y volver.</footer>',
    )


class SafeDocument(HTMLParser):
    """Reports are trusted reviewed inputs, but never admit executable markup."""

    def handle_starttag(self, tag, attrs):
        if tag in {
            "script",
            "iframe",
            "object",
            "embed",
            "form",
            "input",
            "button",
            "select",
            "link",
            "base",
            "svg",
            "math",
        }:
            raise ValueError("Active report markup is forbidden")
        for key, value in attrs:
            if key.startswith("on") or key in {"src", "srcdoc"}:
                raise ValueError("Active report attribute is forbidden")
            if key == "href":
                safe_link(value or "")
            elif value:
                private_guard(value)

    def handle_data(self, data):
        private_guard(data)


def render_report(item, source):
    validate_catalogue([item])
    SafeDocument().feed(source)
    if (
        len(source.encode()) > 262144
        or source.count("<body>") != 1
        or source.count("</head>") != 1
        or source.count("</body>") != 1
    ):
        raise ValueError("Unexpected report document")
    explorer = (
        '<a class="explore-link" href="/preview/videos.html">Explorar todos los videos y buscar próximos clips ↗</a>'
        if item["path"] == "preview/maya-tiktok-historico.html"
        else ""
    )
    heading = (
        brand()
        + '<div class="document-intro"><a class="back-link" href="/preview/">← Todos los informes</a>'
        f'<p class="category-label">{CATEGORIES[item["category"]]}</p><h1>{esc(item["title"])}</h1>'
        f'<p class="purpose">{esc(item["purpose"])}</p>{metadata(item)}{explorer}</div>'
    )
    # Preserve the complete reviewed body byte-for-byte, adding only presentation.
    css = (ROOT / "templates/report-library.css").read_text()
    return (
        source.replace("</head>", "<style>" + css + "</style></head>")
        .replace(
            "<body>",
            '<body class="document"><a class="skip" href="#informe">Ir al informe</a>'
            + heading,
        )
        .replace("<main>", '<main id="informe">', 1)
    )


def inline(value):
    # Escape raw HTML before interpreting this deliberately small Markdown subset.
    parts = re.split(r"(\[[^\]\n]+\]\([^\s)]+\))", value)
    result = []
    for part in parts:
        link = re.fullmatch(r"\[([^\]\n]+)\]\(([^\s)]+)\)", part)
        if link:
            label, href = link.groups()
            safe_link(href)
            private_guard(label)
            result.append(f'<a href="{esc(href)}" rel="noreferrer">{esc(label)}</a>')
        else:
            private_guard(part)
            escaped = esc(part)
            escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
            escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
            result.append(escaped)
    return "".join(result)


def markdown_document(source, title):
    """Render prose and data as semantic HTML; raw HTML is always escaped."""
    lines = source.splitlines()
    output = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(
                    [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
                )
                i += 1
            if len(rows) < 3 or not all(re.fullmatch(r":?-+:?", x) for x in rows[1]):
                raise ValueError("Malformed report table")
            labels = rows[0]
            table = (
                '<table class="history-table"><thead><tr>'
                + "".join(f'<th scope="col">{inline(label)}</th>' for label in labels)
                + "</tr></thead><tbody>"
            )
            for row in rows[2:]:
                if len(row) != len(labels):
                    raise ValueError("Inconsistent report table")
                table += (
                    "<tr>"
                    + "".join(
                        f'<td data-label="{esc(label)}">{inline(cell)}</td>'
                        for label, cell in zip(labels, row)
                    )
                    + "</tr>"
                )
            output.append(table + "</tbody></table>")
            continue
        heading = re.match(r"^(#{1,3}) (.+)$", line)
        if heading:
            level, content = len(heading[1]), heading[2]
            output.append(f"<h{level}>{inline(content)}</h{level}>")
        elif line.startswith("> "):
            output.append("<blockquote><p>" + inline(line[2:]) + "</p></blockquote>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append("<li>" + inline(lines[i][2:]) + "</li>")
                i += 1
            output.append("<ul>" + "".join(items) + "</ul>")
            continue
        else:
            paragraph = [line]
            while (
                i + 1 < len(lines)
                and lines[i + 1].strip()
                and not lines[i + 1].startswith(("#", "|", "> ", "- "))
            ):
                i += 1
                paragraph.append(lines[i])
            output.append("<p>" + inline(" ".join(paragraph)) + "</p>")
        i += 1
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>'
        + esc(title)
        + "</title></head><body><main>"
        + "".join(output)
        + "</main></body></html>"
    )


def render(catalogue, source_dir, output, history=None, history_sha=None):
    items = validate_catalogue(json.loads(Path(catalogue).read_text()))
    if {x["path"] for x in items} != set(REPORTS):
        raise ValueError("Include every registered report; preserve dated documents")
    rendered = {"index.html": render_library(items)}
    for item in items:
        name = item["path"].split("/")[1]
        src = Path(source_dir) / name
        if item["path"] in control.DOCUMENT_HASHES:
            if (
                src.is_symlink()
                or control.file_sha(src) != control.DOCUMENT_HASHES[item["path"]]
            ):
                raise ValueError(
                    "Source differs from reviewed document; new content needs explicit review"
                )
            rendered[name] = render_report(item, src.read_text())
        else:
            if (
                not history
                or not history_sha
                or Path(history).is_symlink()
                or control.file_sha(history) != history_sha
            ):
                raise ValueError(
                    "Historical source requires its reviewed explicit SHA-256"
                )
            rendered[name] = render_report(
                item, markdown_document(Path(history).read_text(), item["title"])
            )
    output = Path(output)
    if output.resolve().is_relative_to(ROOT):
        raise ValueError("Keep private reports outside the public repository")
    output.mkdir(mode=0o700)
    for name, content in rendered.items():
        path = output / name
        path.write_text(content)
        path.chmod(0o600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--history-sha")
    args = parser.parse_args()
    render(args.catalogue, args.source_dir, args.output, args.history, args.history_sha)
