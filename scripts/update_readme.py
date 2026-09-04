#!/usr/bin/env python3
"""Regenerate the public project sections in the profile README."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.github.com/users/{username}/repos"
FEATURED_START = "<!-- FEATURED_PROJECTS:START -->"
FEATURED_END = "<!-- FEATURED_PROJECTS:END -->"
PROJECTS_START = "<!-- PROJECTS:START -->"
PROJECTS_END = "<!-- PROJECTS:END -->"
SYNC_PATTERN = re.compile(r"<!-- PROJECTS_SYNC:[0-9]{4}-W[0-9]{2} -->")
DESCRIPTION_LIMIT = 150


def fetch_repositories(username: str, token: str | None = None) -> list[dict[str, Any]]:
    """Fetch public repositories from GitHub's public user endpoint.

    Authentication only raises the API rate limit here. Unlike /user/repos,
    /users/{username}/repos is documented to return public repositories.
    """
    repositories: list[dict[str, Any]] = []
    page = 1

    while True:
        query = urlencode(
            {
                "type": "owner",
                "sort": "updated",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            }
        )
        request = Request(
            f"{API_URL.format(username=quote(username))}?{query}",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "profile-readme-updater",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                batch = json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API returned HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"Could not reach the GitHub API: {error.reason}") from error

        if not isinstance(batch, list):
            raise RuntimeError("GitHub API returned an unexpected response")

        repositories.extend(batch)
        if len(batch) < 100:
            return repositories
        page += 1


def public_owned_repositories(
    repositories: Iterable[dict[str, Any]], username: str
) -> list[dict[str, Any]]:
    """Return safe-to-publish source repositories owned by the profile user.

    The privacy checks are intentionally redundant. They prevent a token with
    private-repository access from ever leaking private repository metadata into
    the public profile README.
    """
    username_key = username.casefold()
    public_repositories = []

    for repository in repositories:
        owner = repository.get("owner") or {}
        if owner.get("login", "").casefold() != username_key:
            continue
        if repository.get("private") is not False:
            continue
        if repository.get("visibility") != "public":
            continue
        if repository.get("fork") is not False:
            continue
        if repository.get("name", "").casefold() == username_key:
            continue
        public_repositories.append(repository)

    return sorted(
        public_repositories,
        key=lambda repository: (
            -int(repository.get("stargazers_count") or 0),
            -int(repository.get("forks_count") or 0),
            repository.get("name", "").casefold(),
        ),
    )


def plain_text(value: str | None, fallback: str = "No description yet.") -> str:
    """Normalize API text for compact project cards."""
    if not value:
        return fallback
    return " ".join(value.split())


def compact_description(value: str | None, limit: int = DESCRIPTION_LIMIT) -> str:
    """Keep generated project cards readable when a repository has a long bio."""
    description = plain_text(value)
    if len(description) <= limit:
        return description
    return f"{description[: limit - 1].rstrip()}…"


def html_text(value: str | None, fallback: str = "No description yet.") -> str:
    """Escape normalized API text before inserting it into an HTML card."""
    return html.escape(compact_description(value) or fallback)


def metric_badge(username: str, repository: str, metric: str) -> str:
    """Build a live shields.io image for stars or forks."""
    owner = quote(username, safe="")
    repo = quote(repository, safe="")
    label = "Stars" if metric == "stars" else "Forks"
    source = (
        f"https://img.shields.io/github/{metric}/{owner}/{repo}"
        f"?style=flat-square&label={label}&cacheSeconds=1800"
    )
    return f'<img alt="{label}" src="{source}">'


def render_featured(repositories: list[dict[str, Any]], username: str, count: int = 4) -> str:
    """Render the highest-starred active projects as two-column cards."""
    featured = [repository for repository in repositories if not repository.get("archived")][
        :count
    ]
    if not featured:
        return "_No public projects yet._"

    cells = []
    for repository in featured:
        name = repository["name"]
        url = repository.get("html_url") or f"https://github.com/{username}/{name}"
        description = html_text(repository.get("description"))
        stars = metric_badge(username, name, "stars")
        forks = metric_badge(username, name, "forks")
        cells.append(
            "\n".join(
                [
                    '<td width="50%" valign="top">',
                    f'<h3><a href="{html.escape(url, quote=True)}">{html.escape(name)}</a></h3>',
                    f"<p>{description}</p>",
                    f"<p>{stars}&nbsp; {forks}</p>",
                    "</td>",
                ]
            )
        )

    if len(cells) % 2:
        cells.append('<td width="50%" valign="top"></td>')

    rows = []
    for index in range(0, len(cells), 2):
        rows.append("\n".join(["<tr>", cells[index], cells[index + 1], "</tr>"]))
    return "\n".join(["<table>", *rows, "</table>"])


def render_projects(repositories: list[dict[str, Any]], username: str) -> str:
    """Render all public projects in a compact, collapsible list."""
    if not repositories:
        return "_No public projects yet._"

    rows = [
        "<details>",
        f"<summary><strong>Browse all {len(repositories)} public projects</strong></summary>",
        "<br>",
        "<table>",
    ]
    for repository in repositories:
        name = repository["name"]
        url = repository.get("html_url") or f"https://github.com/{username}/{name}"
        description = html_text(repository.get("description"))
        if repository.get("archived"):
            description = f"<em>Archived</em> · {description}"
        rows.append(
            "<tr>"
            '<td valign="top">'
            f'<a href="{html.escape(url, quote=True)}"><strong>{html.escape(name)}</strong></a>'
            f"<br><sub>{description}</sub>"
            "</td>"
            '<td align="right" valign="top">'
            f"{metric_badge(username, name, 'stars')}<br>"
            f"{metric_badge(username, name, 'forks')}"
            "</td>"
            "</tr>"
        )
    rows.extend(["</table>", "</details>"])
    return "\n".join(rows)


def replace_section(content: str, start: str, end: str, replacement: str) -> str:
    """Replace a generated block while preserving its marker comments."""
    if content.count(start) != 1 or content.count(end) != 1:
        raise ValueError(f"README must contain exactly one {start} and one {end}")
    start_index = content.index(start) + len(start)
    end_index = content.index(end, start_index)
    return f"{content[:start_index]}\n{replacement.rstrip()}\n{content[end_index:]}"


def current_sync_period() -> str:
    """Return the current UTC ISO week for a low-noise keepalive commit."""
    iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def replace_sync_period(content: str, sync_period: str) -> str:
    """Refresh the hidden weekly marker that keeps scheduled workflows active."""
    matches = SYNC_PATTERN.findall(content)
    if len(matches) != 1:
        raise ValueError("README must contain exactly one PROJECTS_SYNC marker")
    return SYNC_PATTERN.sub(f"<!-- PROJECTS_SYNC:{sync_period} -->", content)


def update_readme(
    readme: Path,
    repositories: Iterable[dict[str, Any]],
    username: str,
    featured_count: int,
    sync_period: str | None = None,
) -> bool:
    """Update generated sections and return whether the file changed."""
    filtered = public_owned_repositories(repositories, username)
    original = readme.read_text(encoding="utf-8")
    updated = replace_section(
        original,
        FEATURED_START,
        FEATURED_END,
        render_featured(filtered, username, featured_count),
    )
    updated = replace_section(
        updated,
        PROJECTS_START,
        PROJECTS_END,
        render_projects(filtered, username),
    )
    updated = replace_sync_period(updated, sync_period or current_sync_period())
    if updated == original:
        return False
    readme.write_text(updated, encoding="utf-8")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username",
        default=os.getenv("PROFILE_USERNAME")
        or os.getenv("GITHUB_REPOSITORY_OWNER")
        or "kain26",
    )
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--featured-count", type=int, default=4)
    parser.add_argument(
        "--data-file",
        type=Path,
        help="Read a saved GitHub API response instead of making a network request",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.featured_count < 0:
        raise SystemExit("--featured-count must be non-negative")

    if args.data_file:
        repositories = json.loads(args.data_file.read_text(encoding="utf-8"))
    else:
        repositories = fetch_repositories(args.username, os.getenv("GITHUB_TOKEN"))

    changed = update_readme(
        args.readme, repositories, args.username, args.featured_count
    )
    print(f"README {'updated' if changed else 'already up to date'}")


if __name__ == "__main__":
    main()
