#!/usr/bin/env python3
"""
Clone every GitHub repository listed in README.md, run code2prompt on each,
and save the output as archive/{owner}/{repo}.txt.

Prerequisites:
    cargo install code2prompt
    (or: brew install code2prompt)

Usage:
    python scripts/archive-repos.py                  # archive all
    python scripts/archive-repos.py --workers 4      # control parallelism
    python scripts/archive-repos.py --skip-existing  # skip already archived repos
    python scripts/archive-repos.py --dry-run        # just print what would be done
"""

import re
import os
import shutil
import argparse
import tempfile
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

README_PATH = "README.md"
ARCHIVE_DIR = "archive"
GITHUB_REPO_PATTERN = re.compile(
    r"https://github\.com/([^/\s\)\]>\"']+)/([^/\s\)\]>\"'#]+)"
)
MAX_WORKERS = 3          # keep low: cloning is I/O heavy
CLONE_TIMEOUT = 120      # seconds per clone
CODE2PROMPT_TIMEOUT = 60 # seconds per code2prompt run


def extract_github_repos(text: str) -> list[tuple[str, str]]:
    """Return unique (owner, repo) pairs from text, excluding self-references."""
    matches = GITHUB_REPO_PATTERN.findall(text)
    seen: set[tuple[str, str]] = set()
    result = []
    for owner, repo in matches:
        repo = repo.rstrip(".,;:")
        # Skip meta / non-code links
        if owner in ("gmh5225",) and repo in ("awesome-game-security",):
            continue
        key = (owner.lower(), repo.lower())
        if key not in seen:
            seen.add(key)
            result.append((owner, repo))
    return result


def check_code2prompt() -> bool:
    """Return True if code2prompt is available on PATH."""
    return shutil.which("code2prompt") is not None


def install_code2prompt() -> bool:
    """Try to install code2prompt via cargo. Returns True on success."""
    print("code2prompt not found. Installing via cargo ...")
    try:
        subprocess.run(
            ["cargo", "install", "code2prompt"],
            check=True,
            timeout=300,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  [ERROR] Failed to install code2prompt: {e}")
        return False


def archive_repo(
    owner: str,
    repo: str,
    archive_dir: Path,
    skip_existing: bool,
    dry_run: bool,
) -> tuple[str, str, str]:
    """
    Clone owner/repo into a temp dir, run code2prompt, write to archive.
    Returns (owner/repo, status, message).
    """
    slug = f"{owner}/{repo}"
    out_dir = archive_dir / owner
    out_file = out_dir / f"{repo}.txt"

    if skip_existing and out_file.exists():
        return (slug, "SKIP", str(out_file))

    if dry_run:
        return (slug, "DRY", str(out_file))

    clone_url = f"https://github.com/{owner}/{repo}.git"
    tmp_dir = tempfile.mkdtemp(prefix=f"archive_{owner}_{repo}_")

    try:
        # --- clone ---
        result = subprocess.run(
            [
                "git", "clone",
                "--depth", "1",
                "--single-branch",
                "--quiet",
                clone_url,
                tmp_dir,
            ],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT,
        )
        if result.returncode != 0:
            return (slug, "FAIL", f"clone error: {result.stderr.strip()[:200]}")

        # --- code2prompt ---
        out_dir.mkdir(parents=True, exist_ok=True)
        cp_result = subprocess.run(
            ["code2prompt", "--output-file", str(out_file), tmp_dir],
            capture_output=True,
            text=True,
            timeout=CODE2PROMPT_TIMEOUT,
        )
        if cp_result.returncode != 0:
            return (slug, "FAIL", f"code2prompt error: {cp_result.stderr.strip()[:200]}")

        size = out_file.stat().st_size
        return (slug, "OK", f"{size / 1024:.1f} KB → {out_file}")

    except subprocess.TimeoutExpired as e:
        return (slug, "TIMEOUT", str(e))
    except Exception as e:
        return (slug, "ERROR", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone all GitHub repos from README.md and archive them as prompt files."
    )
    parser.add_argument("--readme", default=README_PATH)
    parser.add_argument("--archive-dir", default=ARCHIVE_DIR)
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Parallel workers (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip repos that already have an archive file (default: on)",
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Re-archive repos even if they already exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be archived without doing anything",
    )
    parser.add_argument(
        "--owner-filter",
        default="",
        help="Only archive repos matching this owner (e.g. gmh5225)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N repos (0 = unlimited, useful for testing)",
    )
    args = parser.parse_args()

    # ── sanity check ──────────────────────────────────────────────────────────
    if not args.dry_run:
        if not check_code2prompt():
            if not install_code2prompt():
                print("Abort: code2prompt is required.")
                raise SystemExit(1)
        print(f"code2prompt: {shutil.which('code2prompt')}")

    # ── parse README ──────────────────────────────────────────────────────────
    with open(args.readme, encoding="utf-8") as f:
        text = f.read()

    repos = extract_github_repos(text)

    if args.owner_filter:
        repos = [(o, r) for o, r in repos if o.lower() == args.owner_filter.lower()]

    if args.limit:
        repos = repos[: args.limit]

    archive_dir = Path(args.archive_dir)
    archive_dir.mkdir(exist_ok=True)

    print(f"Found {len(repos)} unique repos to archive → {archive_dir}/")
    if args.dry_run:
        for owner, repo in repos:
            print(f"  {owner}/{repo}")
        return

    # ── archive concurrently ──────────────────────────────────────────────────
    ok = fail = skip = timeout = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                archive_repo, owner, repo, archive_dir, args.skip_existing, False
            ): (owner, repo)
            for owner, repo in repos
        }
        total = len(futures)
        done = 0
        for future in as_completed(futures):
            slug, status, msg = future.result()
            done += 1
            if status == "OK":
                ok += 1
                print(f"  [OK    {done:4d}/{total}] {slug}  ({msg.split('→')[0].strip()})")
            elif status == "SKIP":
                skip += 1
                # suppress individual skip messages to keep output clean
            elif status == "TIMEOUT":
                timeout += 1
                print(f"  [TIME  {done:4d}/{total}] {slug}  {msg}")
            else:
                fail += 1
                print(f"  [FAIL  {done:4d}/{total}] {slug}  {msg}")

    print(
        f"\nDone.  OK={ok}  SKIP={skip}  TIMEOUT={timeout}  FAIL={fail}  "
        f"(total={total})"
    )


if __name__ == "__main__":
    main()
