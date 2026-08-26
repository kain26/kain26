import tempfile
import unittest
from pathlib import Path

from scripts.update_readme import (
    FEATURED_END,
    FEATURED_START,
    PROJECTS_END,
    PROJECTS_START,
    SYNC_PATTERN,
    public_owned_repositories,
    update_readme,
)


def repository(
    name: str,
    *,
    stars: int = 0,
    forks: int = 0,
    private: bool = False,
    visibility: str = "public",
    owner: str = "kain26",
    is_fork: bool = False,
    archived: bool = False,
) -> dict:
    return {
        "name": name,
        "html_url": f"https://github.com/{owner}/{name}",
        "description": f"Description for {name}",
        "owner": {"login": owner},
        "private": private,
        "visibility": visibility,
        "fork": is_fork,
        "archived": archived,
        "stargazers_count": stars,
        "forks_count": forks,
    }


class UpdateReadmeTests(unittest.TestCase):
    def test_filters_every_private_repo_even_if_api_returns_it(self) -> None:
        repositories = [
            repository("public", stars=2),
            repository("secret", private=True, visibility="private", stars=99),
            repository("also-secret", private=True, visibility="public", stars=98),
            repository("private-visibility", visibility="private", stars=97),
            repository("someone-elses", owner="other"),
            repository("fork", is_fork=True),
            repository("kain26"),
        ]

        result = public_owned_repositories(repositories, "kain26")

        self.assertEqual([repo["name"] for repo in result], ["public"])

    def test_sorts_by_stars_then_forks_then_name(self) -> None:
        repositories = [
            repository("charlie", stars=1, forks=1),
            repository("bravo", stars=2, forks=0),
            repository("alpha", stars=1, forks=1),
        ]

        result = public_owned_repositories(repositories, "kain26")

        self.assertEqual([repo["name"] for repo in result], ["bravo", "alpha", "charlie"])

    def test_updates_both_blocks_with_live_badges(self) -> None:
        template = (
            f"before\n{FEATURED_START}\nold\n{FEATURED_END}\n"
            f"middle\n{PROJECTS_START}\nold\n{PROJECTS_END}\n"
            "<!-- PROJECTS_SYNC:2026-W34 -->\nafter\n"
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            readme = Path(temp_directory) / "README.md"
            readme.write_text(template, encoding="utf-8")

            changed = update_readme(
                readme,
                [
                    repository("public", stars=3, forks=2),
                    repository("do-not-publish", private=True, visibility="private"),
                ],
                "kain26",
                4,
                "2026-W35",
            )
            output = readme.read_text(encoding="utf-8")
            changed_again = update_readme(
                readme,
                [
                    repository("public", stars=3, forks=2),
                    repository("do-not-publish", private=True, visibility="private"),
                ],
                "kain26",
                4,
                "2026-W35",
            )

        self.assertTrue(changed)
        self.assertFalse(changed_again)
        self.assertIn("https://github.com/kain26/public", output)
        self.assertIn("img.shields.io/github/stars/kain26/public", output)
        self.assertIn("img.shields.io/github/forks/kain26/public", output)
        self.assertNotIn("do-not-publish", output)
        self.assertIn("<!-- PROJECTS_SYNC:2026-W35 -->", output)
        self.assertEqual(len(SYNC_PATTERN.findall(output)), 1)
        self.assertNotIn("\nold\n", output)


if __name__ == "__main__":
    unittest.main()
