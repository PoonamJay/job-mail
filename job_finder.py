#!/usr/bin/env python3
"""Daily job-finding agent: fetch → filter → deduplicate → digest."""

import html as html_lib
import json
import os
import re
import sys
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import requests
import yaml


# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
CONFIG_FILE = ROOT / "config.yaml"
SEEN_JOBS_FILE = ROOT / "seen_jobs.json"
DIGEST_FILE = ROOT / "digest.md"
EMAIL_BODY_FILE = ROOT / "email_body.html"  # gitignored; read by the workflow


# ── Config ─────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


# ── Job Model ──────────────────────────────────────────────────────────────────
class Job:
    def __init__(
        self,
        *,
        job_id: str,
        title: str,
        company: str,
        location: str,
        url: str,
        description: str,
        source: str,
    ) -> None:
        self.job_id = job_id
        self.title = title
        self.company = company
        self.location = location
        self.url = url
        self.description = description
        self.source = source
        self.flags: list[str] = []

    @property
    def unique_key(self) -> str:
        return self.url or self.job_id


# ── Source Layer (extensible) ──────────────────────────────────────────────────
class JobSource(ABC):
    """Subclass this to add a new board (Greenhouse, Lever, etc.)."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.max_results: int = config.get("max_results_per_source", 50)

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Return up to self.max_results raw Job objects."""
        ...


# ── Source: The Muse ───────────────────────────────────────────────────────────
class TheMuseSource(JobSource):
    """The Muse public API — no key required."""

    BASE_URL = "https://www.themuse.com/api/public/jobs"
    CATEGORIES = ["Data Science", "Analytics", "Business Intelligence"]

    @property
    def name(self) -> str:
        return "The Muse"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for category in self.CATEGORIES:
            page = 0
            while len(jobs) < self.max_results:
                try:
                    resp = requests.get(
                        self.BASE_URL,
                        params={"category": category, "page": page, "descending": "true"},
                        timeout=15,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    print(f"  [The Muse] Error on page {page} for '{category}': {exc}")
                    break

                results = data.get("results", [])
                if not results:
                    break

                for item in results:
                    raw_id = str(item.get("id", ""))
                    if raw_id in seen_ids:
                        continue
                    seen_ids.add(raw_id)

                    locations = [loc["name"] for loc in item.get("locations", [])]
                    jobs.append(Job(
                        job_id=f"muse_{raw_id}",
                        title=item.get("name", ""),
                        company=item.get("company", {}).get("name", "Unknown"),
                        location=", ".join(locations),
                        url=item.get("refs", {}).get("landing_page", ""),
                        description=_strip_html(item.get("contents", "")),
                        source=self.name,
                    ))

                page += 1
                total_pages = data.get("page_count", 0)
                if page >= total_pages:
                    break

            if len(jobs) >= self.max_results:
                break

        return jobs[: self.max_results]


# ── Source: Adzuna ─────────────────────────────────────────────────────────────
class AdzunaSource(JobSource):
    """Adzuna developer API — skipped gracefully if credentials are absent."""

    BASE_URL = "https://api.adzuna.com/v1/api/jobs/us/search/1"

    # Targeted search pairs to stay well within the free-tier call limit.
    SEARCHES = [
        ("data analyst", "New York"),
        ("business analyst", "New York"),
        ("data scientist", "New York"),
        ("analytics", "New Jersey"),
        ("data analyst", "remote"),
        ("business analyst", "remote"),
    ]

    @property
    def name(self) -> str:
        return "Adzuna"

    def fetch(self) -> list[Job]:
        app_id = os.environ.get("ADZUNA_APP_ID", "")
        app_key = os.environ.get("ADZUNA_APP_KEY", "")

        if not app_id or not app_key:
            print("  [Adzuna] Credentials not set — skipping source.")
            return []

        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for what, where in self.SEARCHES:
            if len(jobs) >= self.max_results:
                break
            try:
                resp = requests.get(
                    self.BASE_URL,
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "what": what,
                        "where": where,
                        "results_per_page": 10,
                        "content-type": "application/json",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                print(f"  [Adzuna] Error searching '{what}' in '{where}': {exc}")
                continue

            for item in data.get("results", []):
                raw_id = str(item.get("id", ""))
                if raw_id in seen_ids:
                    continue
                seen_ids.add(raw_id)

                loc = item.get("location", {})
                area = loc.get("area", [])
                # area is a list like ["US", "New York State", "New York City"]
                loc_str = ", ".join(area[-2:]) if len(area) >= 2 else loc.get("display_name", "")

                jobs.append(Job(
                    job_id=f"adzuna_{raw_id}",
                    title=item.get("title", ""),
                    company=item.get("company", {}).get("display_name", "Unknown"),
                    location=loc_str,
                    url=item.get("redirect_url", ""),
                    description=_strip_html(item.get("description", "")),
                    source=self.name,
                ))

        return jobs[: self.max_results]


# ── Future sources: uncomment and implement to add ─────────────────────────────
# class GreenhouseSource(JobSource):
#     @property
#     def name(self) -> str: return "Greenhouse"
#     def fetch(self) -> list[Job]: ...
#
# class LeverSource(JobSource):
#     @property
#     def name(self) -> str: return "Lever"
#     def fetch(self) -> list[Job]: ...


# ── Text Utilities ─────────────────────────────────────────────────────────────
def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return html_lib.unescape(text)


def _contains_any(text: str, phrases: list[str]) -> bool:
    tl = text.lower()
    return any(p.lower() in tl for p in phrases)


# ── Location Matching ──────────────────────────────────────────────────────────
_REMOTE_SIGNALS = ("remote", "flexible", "work from home", "wfh", "distributed", "anywhere")


def _is_remote(location: str) -> bool:
    ll = location.lower()
    return any(s in ll for s in _REMOTE_SIGNALS)


def _location_matches(job_location: str, targets: list[str]) -> bool:
    jl = job_location.lower()
    for target in targets:
        tl = target.lower()
        if "remote" in tl:
            if _is_remote(job_location):
                return True
        else:
            city = tl.split(",")[0].strip()
            if city and city in jl:
                return True
            if tl in jl or jl in tl:
                return True
    return False


# ── Filtering ──────────────────────────────────────────────────────────────────
def filter_jobs(jobs: list[Job], config: dict) -> list[Job]:
    keywords: list[str] = config["target_keywords"]
    locations: list[str] = config["target_locations"]
    hard_bar: list[str] = config["hard_bar_phrases"]
    no_sponsor: list[str] = config["no_sponsorship_phrases"]

    out: list[Job] = []
    for job in jobs:
        if not _contains_any(job.title, keywords):
            continue

        # Empty location ≈ unknown; we let it through rather than silently drop.
        if job.location and not _location_matches(job.location, locations):
            continue

        searchable = job.title + " " + job.description
        if _contains_any(searchable, hard_bar):
            continue

        if _contains_any(searchable, no_sponsor):
            job.flags = ["⚠️ (no future sponsorship)"]

        out.append(job)

    return out


# ── Deduplication ──────────────────────────────────────────────────────────────
def load_seen() -> set[str]:
    if SEEN_JOBS_FILE.exists():
        return set(json.loads(SEEN_JOBS_FILE.read_text()).get("seen", []))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_JOBS_FILE.write_text(json.dumps({"seen": sorted(seen)}, indent=2) + "\n")


def deduplicate(jobs: list[Job], seen: set[str]) -> tuple[list[Job], set[str]]:
    new: list[Job] = []
    for job in jobs:
        key = job.unique_key
        if key not in seen:
            new.append(job)
            seen.add(key)
    return new, seen


# ── Output: digest.md ──────────────────────────────────────────────────────────
def _group_by_location(jobs: list[Job], targets: list[str]) -> dict[str, list[Job]]:
    groups: dict[str, list[Job]] = {t: [] for t in targets}
    groups["Other"] = []

    for job in jobs:
        placed = False
        for target in targets:
            tl = target.lower()
            if "remote" in tl:
                if _is_remote(job.location):
                    groups[target].append(job)
                    placed = True
                    break
            else:
                city = tl.split(",")[0].strip()
                if city and city in job.location.lower():
                    groups[target].append(job)
                    placed = True
                    break
        if not placed:
            groups["Other"].append(job)

    return groups


def write_digest(jobs: list[Job], config: dict) -> None:
    today = date.today().strftime("%B %d, %Y")
    targets: list[str] = config["target_locations"]

    lines = [f"# Job Digest — {today}", "", f"**{len(jobs)} new posting(s) found.**", ""]

    if not jobs:
        lines.append("_No new relevant postings today._")
    else:
        groups = _group_by_location(jobs, targets)
        for loc in targets + ["Other"]:
            loc_jobs = groups.get(loc, [])
            if not loc_jobs:
                continue
            lines += [f"## {loc}", ""]
            for job in loc_jobs:
                flag_part = " " + " ".join(job.flags) if job.flags else ""
                lines.append(
                    f"- **[{job.title}]({job.url})**{flag_part}  \n"
                    f"  {job.company} — {job.location} — _{job.source}_"
                )
            lines.append("")

    DIGEST_FILE.write_text("\n".join(lines) + "\n")


# ── Output: email_body.html ────────────────────────────────────────────────────
def write_email(jobs: list[Job], config: dict) -> None:
    today = date.today().strftime("%B %d, %Y")
    targets: list[str] = config["target_locations"]

    def esc(s: str) -> str:
        return html_lib.escape(s)

    if not jobs:
        inner = (
            f"<p>No new relevant job postings were found for <strong>{esc(today)}</strong>.</p>"
            "<p>The agent will check again tomorrow morning.</p>"
        )
    else:
        groups = _group_by_location(jobs, targets)
        sections: list[str] = []
        for loc in targets + ["Other"]:
            loc_jobs = groups.get(loc, [])
            if not loc_jobs:
                continue
            items: list[str] = []
            for job in loc_jobs:
                flag_html = ""
                if job.flags:
                    flag_html = (
                        f' <span style="color:#b45309;font-weight:bold">'
                        f'{esc(" ".join(job.flags))}</span>'
                    )
                items.append(
                    f'<li style="margin-bottom:10px">'
                    f'<a href="{esc(job.url)}" style="font-size:15px;font-weight:bold;color:#1a73e8">'
                    f'{esc(job.title)}</a>{flag_html}<br>'
                    f'<span style="color:#555">{esc(job.company)}</span>'
                    f' &mdash; {esc(job.location)}'
                    f' &mdash; <em style="color:#888">{esc(job.source)}</em>'
                    f'</li>'
                )
            sections.append(
                f'<h3 style="margin-top:24px;border-bottom:2px solid #e8eaed;'
                f'padding-bottom:6px;color:#202124">{esc(loc)}</h3>'
                f'<ul style="list-style:none;padding:0">{"".join(items)}</ul>'
            )
        inner = "\n".join(sections)

    html = (
        '<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;'
        'max-width:640px;margin:0 auto;padding:20px;color:#333">'
        f'<h2 style="color:#1a73e8">&#128188; Job Digest &mdash; {esc(today)}</h2>'
        f'<p><strong>{len(jobs)} new posting(s)</strong> matching your profile.</p>'
        f"{inner}"
        '<hr style="margin-top:32px;border:none;border-top:1px solid #e8eaed">'
        '<p style="font-size:11px;color:#aaa">'
        "Generated by your GitHub Actions job-finder. "
        "&#9888;&#65039; = role mentions no future sponsorship but is still legal on your current work auth."
        "</p></body></html>"
    )
    EMAIL_BODY_FILE.write_text(html)


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> int:
    config = load_config()

    # ── Add new sources to this list ───────────────────────────────────────────
    sources: list[JobSource] = [
        TheMuseSource(config),
        AdzunaSource(config),
        # GreenhouseSource(config),
        # LeverSource(config),
    ]

    all_jobs: list[Job] = []
    for source in sources:
        print(f"\nFetching from {source.name}...")
        try:
            fetched = source.fetch()
            print(f"  {len(fetched)} raw results")
            all_jobs.extend(fetched)
        except Exception as exc:
            print(f"  [{source.name}] Unhandled error — skipping: {exc}")

    print(f"\nFiltering {len(all_jobs)} total raw jobs...")
    filtered = filter_jobs(all_jobs, config)
    print(f"  {len(filtered)} after keyword / location / hard-bar filter")

    seen = load_seen()
    new_jobs, updated_seen = deduplicate(filtered, seen)
    print(f"  {len(new_jobs)} new (not previously emailed)")

    save_seen(updated_seen)
    write_digest(new_jobs, config)
    write_email(new_jobs, config)

    # Expose count to the Actions workflow for the email subject line.
    gha_output = os.environ.get("GITHUB_OUTPUT", "")
    if gha_output:
        today_str = date.today().strftime("%B %d, %Y")
        with open(gha_output, "a") as fh:
            fh.write(f"new_count={len(new_jobs)}\n")
            fh.write(f"today={today_str}\n")

    print(f"\nDone — {len(new_jobs)} new posting(s). Digest written to {DIGEST_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
