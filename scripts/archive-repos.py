#!/usr/bin/env python3
"""
Clone every GitHub repository listed in README.md, run code2prompt on each,
and save the output as archive/{owner}/{repo}.txt.

Prerequisites:
    cargo install code2prompt

Usage:
    python scripts/archive-repos.py                        # archive all new repos
    python scripts/archive-repos.py --commit-every 5       # commit to git every 5 archives
    python scripts/archive-repos.py --workers 4            # control parallelism
    python scripts/archive-repos.py --no-skip-existing     # re-archive everything
    python scripts/archive-repos.py --owner-filter gmh5225 # only one owner
    python scripts/archive-repos.py --limit 10 --dry-run   # preview first 10
"""

import re
import shutil
import argparse
import tempfile
import threading
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

README_PATH = "README.md"
ARCHIVE_DIR = "archive"
GITHUB_REPO_PATTERN = re.compile(
    r"https://github\.com/([^/\s\)\]>\"']+)/([^/\s\)\]>\"'#]+)"
)
MAX_WORKERS = 3
CLONE_TIMEOUT = 180       # seconds
CODE2PROMPT_TIMEOUT = 60  # seconds — abandon large repos quickly
MAX_FILE_MB = 200         # skip output files larger than this


SCAN_START_MARKER = "## Game Engine"


def extract_github_repos(text: str) -> list[tuple[str, str]]:
    """Return unique (owner, repo) pairs from README, starting at SCAN_START_MARKER."""
    marker_pos = text.find(SCAN_START_MARKER)
    if marker_pos == -1:
        print(f"[WARN] Marker '{SCAN_START_MARKER}' not found — scanning full README.")
    else:
        text = text[marker_pos:]

    matches = GITHUB_REPO_PATTERN.findall(text)
    seen: set[tuple[str, str]] = set()
    result = []
    for owner, repo in matches:
        repo = repo.rstrip(".,;:")
        if owner == "gmh5225" and repo == "awesome-game-security":
            continue
        key = (owner.lower(), repo.lower())
        if key not in seen:
            seen.add(key)
            result.append((owner, repo))
    return result


def check_code2prompt() -> bool:
    return shutil.which("code2prompt") is not None


def install_code2prompt() -> bool:
    print("code2prompt not found — installing via cargo ...")
    try:
        subprocess.run(["cargo", "install", "code2prompt"], check=True, timeout=300)
        return True
    except Exception as e:
        print(f"  [ERROR] Install failed: {e}")
        return False


def git_commit_and_push(archive_dir: Path, count: int, push_retries: int = 5) -> None:
    """Stage archive dir and push a commit. Called with the commit lock held.

    If the push is rejected because the remote moved ahead (concurrent pushes),
    pull --rebase and retry up to push_retries times.
    """
    try:
        subprocess.run(["git", "add", str(archive_dir)], check=True, capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if result.returncode == 0:
            return  # nothing staged

        subprocess.run(
            ["git", "commit", "-m",
             f"archive: add {count} repo prompt(s) [skip ci]"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  [GIT ERROR] commit: {e.stderr.decode().strip()[:200] if e.stderr else e}")
        return

    for attempt in range(1, push_retries + 1):
        try:
            subprocess.run(["git", "push"], check=True, capture_output=True)
            print(f"  [GIT] Committed and pushed {count} archive(s)")
            return
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode().strip() if e.stderr else str(e)
            # Rejected because remote moved ahead — rebase on top and retry
            if "rejected" in err or "fetch first" in err or "non-fast-forward" in err:
                print(f"  [GIT] Push rejected (attempt {attempt}/{push_retries}), rebasing ...")
                try:
                    subprocess.run(
                        ["git", "pull", "--rebase", "origin", "main"],
                        check=True, capture_output=True,
                    )
                except subprocess.CalledProcessError as re_err:
                    re_msg = re_err.stderr.decode().strip()[:200] if re_err.stderr else str(re_err)
                    print(f"  [GIT ERROR] rebase failed: {re_msg}")
                    return
            else:
                print(f"  [GIT ERROR] push: {err[:200]}")
                return

    print(f"  [GIT ERROR] push failed after {push_retries} retries — giving up")


def archive_repo(
    owner: str,
    repo: str,
    archive_dir: Path,
    skip_existing: bool,
) -> tuple[str, str, str]:
    """
    Clone owner/repo, run code2prompt, write to archive.
    Returns (slug, status, message).
    status: OK | SKIP | FAIL | TIMEOUT | TOOLARGE
    """
    slug = f"{owner}/{repo}"
    out_dir = archive_dir / owner
    out_file = out_dir / f"{repo}.txt"

    if skip_existing and out_file.exists():
        return (slug, "SKIP", "")

    clone_url = f"https://github.com/{owner}/{repo}.git"
    tmp_dir = tempfile.mkdtemp(prefix=f"arc_{owner}_{repo}_")

    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", "--quiet",
             clone_url, tmp_dir],
            capture_output=True, text=True, timeout=CLONE_TIMEOUT,
        )
        if r.returncode != 0:
            return (slug, "FAIL", f"clone: {r.stderr.strip()[:200]}")

        out_dir.mkdir(parents=True, exist_ok=True)
        cp = subprocess.run(
            ["code2prompt", "--output-file", str(out_file), tmp_dir],
            capture_output=True, text=True, timeout=CODE2PROMPT_TIMEOUT,
        )
        if cp.returncode != 0:
            return (slug, "FAIL", f"code2prompt: {cp.stderr.strip()[:200]}")

        size_bytes = out_file.stat().st_size
        size_mb = size_bytes / 1024 / 1024
        if size_mb > MAX_FILE_MB:
            out_file.unlink(missing_ok=True)
            return (slug, "TOOLARGE", f"{size_mb:.1f} MB > limit {MAX_FILE_MB} MB")

        return (slug, "OK", f"{size_bytes / 1024:.1f} KB")

    except subprocess.TimeoutExpired:
        return (slug, "TIMEOUT", "exceeded timeout")
    except Exception as e:
        return (slug, "ERROR", str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive GitHub repos from README.md as code2prompt text files."
    )
    parser.add_argument("--readme", default=README_PATH)
    parser.add_argument("--archive-dir", default=ARCHIVE_DIR)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--owner-filter", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--commit-every",
        type=int,
        default=0,
        metavar="N",
        help="Commit and push to git after every N successful archives (0 = disabled)",
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        metavar="OWNER/REPO",
        help="Archive only these specific repos (e.g. --repos torvalds/linux foo/bar). "
             "Skips README scanning entirely.",
    )
    args = parser.parse_args()

    # ── preflight ─────────────────────────────────────────────────────────────
    if not args.dry_run:
        if not check_code2prompt():
            if not install_code2prompt():
                raise SystemExit("Abort: code2prompt is required.")
        print(f"code2prompt: {shutil.which('code2prompt')}")

    # ── resolve repo list ─────────────────────────────────────────────────────
    if args.repos:
        # Explicit list supplied — skip README scanning
        repos = []
        for slug in args.repos:
            parts = slug.strip().split("/")
            if len(parts) == 2:
                repos.append((parts[0], parts[1]))
            else:
                print(f"[WARN] Ignoring invalid repo slug: {slug!r}")
    else:
        # Default: scan README
        with open(args.readme, encoding="utf-8") as f:
            repos = extract_github_repos(f.read())

    if args.owner_filter:
        repos = [(o, r) for o, r in repos if o.lower() == args.owner_filter.lower()]
    if args.limit:
        repos = repos[: args.limit]

    archive_dir = Path(args.archive_dir)
    archive_dir.mkdir(exist_ok=True)
    print(f"Repos to process: {len(repos)}  →  {archive_dir}/")

    if args.dry_run:
        for owner, repo in repos:
            flag = "SKIP" if (archive_dir / owner / f"{repo}.txt").exists() else "TODO"
            print(f"  [{flag}] {owner}/{repo}")
        return

    # ── archive with optional periodic git commits ────────────────────────────
    counters = {"ok": 0, "fail": 0, "skip": 0, "timeout": 0, "toolarge": 0}
    since_last_commit = 0            # OK archives since last commit
    commit_lock = threading.Lock()   # serialise git operations

    def on_ok(slug: str, msg: str, done: int, total: int) -> None:
        nonlocal since_last_commit
        counters["ok"] += 1
        since_last_commit += 1
        print(f"  [OK    {done:4d}/{total}] {slug}  ({msg})")
        if args.commit_every and since_last_commit >= args.commit_every:
            with commit_lock:
                batch = since_last_commit
                since_last_commit = 0
            git_commit_and_push(archive_dir, batch)

    total = len(repos)
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                archive_repo, owner, repo, archive_dir, args.skip_existing
            ): (owner, repo)
            for owner, repo in repos
        }
        for future in as_completed(futures):
            slug, status, msg = future.result()
            done += 1
            if status == "OK":
                on_ok(slug, msg, done, total)
            elif status == "SKIP":
                counters["skip"] += 1
            elif status == "TIMEOUT":
                counters["timeout"] += 1
                print(f"  [TIME  {done:4d}/{total}] {slug}")
            elif status == "TOOLARGE":
                counters["toolarge"] += 1
                print(f"  [BIG   {done:4d}/{total}] {slug}  {msg}")
            else:
                counters["fail"] += 1
                print(f"  [FAIL  {done:4d}/{total}] {slug}  {msg}")

    # ── final commit for any remaining uncommitted archives ───────────────────
    if args.commit_every and since_last_commit > 0:
        with commit_lock:
            git_commit_and_push(archive_dir, since_last_commit)

    print(
        f"\nDone.  OK={counters['ok']}  SKIP={counters['skip']}  "
        f"TIMEOUT={counters['timeout']}  TOOLARGE={counters['toolarge']}  "
        f"FAIL={counters['fail']}  (total={total})"
    )


if __name__ == "__main__":
    main()
