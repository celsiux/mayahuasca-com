#!/usr/bin/env python3
"""Compile a bounded, private explorer dataset from reviewed CSV, never raw responses."""

import argparse
import csv
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location(
    "library", Path(__file__).with_name("report_library.py")
)
library = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library)


def numeric(value, positive_only=False):
    if value in (None, ""):
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("Invalid metric")
    if positive_only and result == 0:
        return None
    return int(result) if result.is_integer() else result


def compile_rows(rows, queue):
    if len(rows) > 5000 or len(queue) != 30 or len(set(queue)) != 30:
        raise ValueError("Unexpected dataset or candidate queue size")
    videos, seen, redacted, excerpts = [], set(), 0, 0
    fields = {
        "duration": "videoDuration",
        "views": "videoViews",
        "likes": "likeCount",
        "comments": "commentsCount",
        "shares": "shareCount",
        "saves": "favorites",
        "followers": "newFollowers",
    }
    watch_fields = {
        "averageWatch": "averageTimeWatched",
        "completion": "fullVideoWatchedRate",
        "totalWatch": "totalTimeWatched",
        "reach": "reach",
    }
    for row in rows:
        video_id = row["id"]
        url = row["postUrl"]
        if (
            not re.fullmatch(r"[1-9]\d{18}", video_id)
            or video_id in seen
            or not library.TIKTOK.fullmatch(url)
            or not url.endswith("/" + video_id)
        ):
            raise ValueError("Invalid/duplicate native ID or permalink")
        seen.add(video_id)
        published = row["created"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", published):
            raise ValueError("Unexpected publication date")
        datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")
        caption = row.get("post", "")
        if len(caption) > 2000:
            caption = caption[:1999] + "…"
            excerpts += 1
        # Any PII-like text is explicitly redacted, never encoded to evade guards.
        for pattern in library.FORBIDDEN:
            caption, count = pattern.subn("[dato omitido]", caption)
            redacted += count
        tags = list(
            dict.fromkeys(re.findall(r"#[\w]{1,60}", caption, flags=re.UNICODE))
        )[:40]
        video = {
            "id": video_id,
            "caption": caption,
            "published": published,
            "url": url,
            "tags": tags,
            "candidate": queue.index(video_id) + 1 if video_id in queue else None,
        }
        video.update(
            {field: numeric(row.get(source)) for field, source in fields.items()}
        )
        # These fields can carry provider default zeros; never label those as measured 0%.
        video.update(
            {
                field: numeric(row.get(source), positive_only=True)
                for field, source in watch_fields.items()
            }
        )
        if video["completion"] is not None and video["completion"] > 1:
            raise ValueError("Completion proportion outside fraction scale")
        videos.append(video)
    if not set(queue).issubset(seen):
        raise ValueError("Candidate not in dataset")
    return {"schema": 1, "videos": videos}, {
        "count": len(videos),
        "candidates": len(queue),
        "caption_redactions": redacted,
        "caption_excerpts": excerpts,
        "cover_field_in_csv": False,
        "profile_views_omitted": "Only zero/default or missing values in supplied source",
        "watch_zero_policy": "Provider-default zero watch/reach values treated as unavailable; positive values preserved",
        "completion_scale": "fraction [0,1], displayed as percentage x100",
    }


def build(source, queue_path, output):
    with Path(source).open(newline="") as f:
        rows = list(csv.DictReader(f))
    with Path(queue_path).open(newline="") as f:
        queue = [row["id"] for row in csv.DictReader(f)]
    data, audit = compile_rows(rows, queue)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode()) > 6000000:
        raise ValueError("Dataset exceeds 6 MB bound")
    p = Path(output)
    if p.resolve().is_relative_to(library.ROOT):
        raise ValueError("Keep private data outside the public repository")
    p.write_text(encoded)
    p.chmod(0o600)
    audit["bytes"] = p.stat().st_size
    audit["source_sha256"] = library.control.file_sha(source)
    audit["queue_sha256"] = library.control.file_sha(queue_path)
    audit["dataset_sha256"] = library.control.file_sha(p)
    content = (library.ROOT / "templates/video-explorer.html").read_text()
    replacements = {
        "{{COUNT}}": f"{len(rows):,}".replace(",", "."),
        "{{START}}": library.display_date(min(row["created"] for row in rows)[:10]),
        "{{END}}": library.display_date(max(row["created"] for row in rows)[:10]),
        "{{ASOF}}": library.display_date(
            max(row["metrics_asof_utc"] for row in rows)[:10]
        ),
    }
    for key, value in replacements.items():
        content = content.replace(key, library.esc(value))
    page = p.with_name("videos.html")
    page.write_text(library.page("Archivo de videos · Maya", content, "explorer"))
    page.chmod(0o600)
    script = p.with_name("video-explorer.js")
    script.write_bytes((library.ROOT / "src/video-explorer.js").read_bytes())
    script.chmod(0o600)
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.queue, args.output)))
