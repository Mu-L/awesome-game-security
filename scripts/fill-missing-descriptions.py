#!/usr/bin/env python3

"""Fill missing repository descriptions from README metadata and local archives.

This script scans GitHub repositories referenced in README.md, then creates
description/{owner}/{repo}/description_en.txt for entries that do not already
have one. It prefers the README annotation, then falls back to the embedded
top-level README inside archive/{owner}/{repo}.txt, and finally category-based
context when little source material is available.
"""

from __future__ import annotations

import argparse
import html
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
README_PATH = ROOT_DIR / "README.md"
ARCHIVE_DIR = ROOT_DIR / "archive"
DESC_DIR = ROOT_DIR / "description"
SCAN_START_MARKER = "## Game Engine"

REPO_URL_RE = re.compile(
    r"https://github\.com/([^/\s\)\]>\"']+)/([^/\s\)\]>\"'#]+)"
)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://github\.com/[^)]+)\)")
README_BLOCK_RE = re.compile(
    r"`README[^`]*`:\s*\n\n```(?:\w+)?\n(.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)
TREE_BLOCK_RE = re.compile(
    r"Source Tree:\s*\n\n```txt\n(.*?)\n```",
    re.DOTALL,
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


GENERIC_ANNOTATIONS = {
    "unreal",
    "unity",
    "shader",
    "render",
    "opengl",
    "directx",
    "mobile game",
    "golang",
    "rust",
    "2d",
    "3d",
    "html5",
    "c++",
    "c#",
    ".net",
    "gameboy",
}

EXTENSION_LANGUAGES = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".h": "C/C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".go": "Go",
    ".rs": "Rust",
    ".cs": "C#",
    ".py": "Python",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".lua": "Lua",
    ".gd": "GDScript",
    ".zig": "Zig",
    ".sh": "Shell",
    ".ps1": "PowerShell",
    ".cmake": "CMake",
}

FEATURE_PATTERNS = [
    ("anti-cheat", "anti-cheat research"),
    ("reverse engineering", "reverse engineering"),
    ("reverse-engineering", "reverse engineering"),
    ("kernel", "kernel-level work"),
    ("driver", "driver development"),
    ("directx", "DirectX"),
    ("opengl", "OpenGL"),
    ("vulkan", "Vulkan"),
    ("shader", "shader work"),
    ("render", "rendering"),
    ("graphics", "graphics"),
    ("audio", "audio systems"),
    ("network", "networking"),
    ("physics", "physics"),
    ("animation", "animation"),
    ("asset", "asset pipelines"),
    ("editor", "editor tooling"),
    ("plugin", "plugin development"),
    ("mod", "modding"),
    ("unity", "Unity"),
    ("unreal", "Unreal Engine"),
    ("godot", "Godot"),
    ("il2cpp", "IL2CPP analysis"),
    ("sdk", "SDK generation"),
    ("hook", "hooking"),
    ("overlay", "overlays"),
    ("memory", "memory analysis"),
    ("emulator", "emulation"),
    ("debug", "debugging"),
]

AUDIENCE_BY_CATEGORY = {
    "Game Engine": "game developers, engine programmers, and graphics researchers",
    "Mathematics": "engine programmers and gameplay or simulation developers",
    "Renderer": "graphics programmers and rendering researchers",
    "3D Graphics": "graphics programmers, technical artists, and engine developers",
    "AI": "game AI and tooling developers",
    "Image Codec": "engine and tooling developers working on asset pipelines",
    "Wavefront Obj": "asset pipeline and tooling developers",
    "Task Scheduler": "engine programmers building job systems and runtime infrastructure",
    "Game Network": "backend, multiplayer, and online game developers",
    "PhysX SDK": "physics and gameplay engineers",
    "Game Develop": "game developers, reverse engineers, and tooling builders",
    "Game Assets": "content pipeline and modding developers",
    "Game Hot Patch": "live-update and patching workflow developers",
    "Game Testing": "QA automation and testing engineers",
    "Game Tools": "tooling developers and reverse engineers",
    "Game Manager": "launcher, patcher, and infrastructure developers",
    "Game CI": "build, release, and automation engineers",
    "DirectX": "graphics programmers and Windows game tooling developers",
    "OpenGL": "graphics programmers and cross-platform renderer developers",
    "Vulkan": "low-level graphics programmers and performance-focused engine developers",
    "Cheat": "game security researchers and reverse engineers studying offensive techniques",
    "Anti Cheat": "anti-cheat engineers and defensive security researchers",
    "Some Tricks": "low-level Windows, Linux, and mobile researchers",
    "Windows Security Features": "Windows kernel and platform security researchers",
    "WSL": "Windows subsystem and developer-environment researchers",
    "WSA": "Android-on-Windows and platform integration researchers",
    "Windows Emulator": "emulator developers and Windows platform researchers",
    "Linux Emulator": "emulator developers and Linux platform researchers",
    "Android Emulator": "mobile platform and emulator researchers",
    "IOS Emulator": "iOS platform and emulator researchers",
    "Game Boy": "retro handheld emulator developers and reverse engineers",
    "Nintendo Switch": "console emulator developers and Switch researchers",
    "Xbox": "console emulator developers and Xbox researchers",
    "PlayStation": "console emulator developers and PlayStation researchers",
}


@dataclass(frozen=True)
class RepoEntry:
    owner: str
    repo: str
    category: str
    subcategory: str
    annotation: str
    line_text: str


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def ensure_period(text: str) -> str:
    text = clean_whitespace(text).rstrip(".;:,")
    if not text:
        return ""
    if text[-1] in ".!?":
        return text
    return f"{text}."


def strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = text.replace("**", " ").replace("__", " ")
    text = text.replace("*", " ")
    text = html.unescape(text)
    return clean_whitespace(text)


def is_generic_annotation(text: str) -> bool:
    lowered = clean_whitespace(text).lower()
    return lowered in GENERIC_ANNOTATIONS or len(lowered.split()) <= 2 and lowered in GENERIC_ANNOTATIONS


def normalize_fragment(fragment: str) -> str:
    fragment = strip_markdown(fragment).strip()
    fragment = fragment.strip("[]() ")
    fragment = clean_whitespace(fragment)
    return fragment.rstrip(".")


def sentence_case(fragment: str) -> str:
    fragment = clean_whitespace(fragment)
    if not fragment:
        return ""
    return fragment[0].lower() + fragment[1:]


def natural_case(fragment: str) -> str:
    fragment = clean_whitespace(fragment)
    if not fragment:
        return ""

    words: list[str] = []
    for word in fragment.split():
        if word.lower() in {"a", "an", "the"}:
            words.append(word.lower())
            continue
        if any(char.isdigit() for char in word):
            words.append(word)
            continue
        if any(char.islower() for char in word) and any(char.isupper() for char in word[1:]):
            words.append(word)
            continue
        if word.isupper() or "#" in word or "+" in word:
            words.append(word)
            continue
        words.append(word.lower())
    return " ".join(words)


def mostly_ascii_letters(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return True
    ascii_letters = sum(char.isascii() for char in letters)
    return ascii_letters / len(letters) >= 0.8


def humanize_repo_name(repo: str) -> str:
    repo = repo.replace("-", " ").replace("_", " ")
    repo = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", repo)
    return clean_whitespace(repo)


def normalized_compare(text: str) -> str:
    text = humanize_repo_name(text)
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text)
    return clean_whitespace(text).lower()


def is_descriptive_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    prefixes = (
        "a ",
        "an ",
        "the ",
        "this ",
        "it ",
        "curated ",
        "comprehensive ",
        "lightweight ",
        "small ",
        "simple ",
        "open-source ",
        "open source ",
    )
    tokens = (
        " is ",
        " are ",
        " provides",
        " provide",
        " offers",
        " includes",
        " contains",
        " supports",
        " allows",
        " helps",
        " enables",
        " documents",
        " collects",
        " implements",
        " uses",
        " written in",
        " built with",
        " designed for",
        " based on",
        " moved to",
    )
    return lowered.startswith(prefixes) or any(token in lowered for token in tokens)


def fragment_to_sentence(fragment: str, repo: str) -> str:
    fragment = normalize_fragment(fragment)
    fragment = SENTENCE_SPLIT_RE.split(fragment, maxsplit=1)[0]
    if not fragment:
        return ""

    repo_name = repo.replace("-", " ").replace("_", " ")
    lowered = fragment.lower()
    cleaned_fragment = natural_case(fragment.replace("&", "and"))

    if lowered.startswith("awesome "):
        topic = natural_case(fragment[8:])
        return ensure_period(f"This project is a curated resource collection for {topic}")

    if "lists" in lowered:
        return ensure_period(f"This project collects {cleaned_fragment}")

    if any(token in lowered for token in ("list", "guide", "tutorial", "notes", "reference", "cheat sheet", "book")):
        if lowered.startswith(("curated ", "comprehensive ")):
            return ensure_period(f"This project is a {cleaned_fragment}")
        return ensure_period(f"This project provides {cleaned_fragment}")

    if lowered.startswith(("a ", "an ", "the ")):
        return ensure_period(f"This project is {sentence_case(fragment)}")

    repo_prefix = re.compile(rf"^{re.escape(repo_name)}\s+is\s+", re.IGNORECASE)
    if repo_prefix.match(fragment):
        return ensure_period("This project is " + repo_prefix.sub("", fragment))

    repo_token_prefix = re.compile(rf"^{re.escape(repo)}\s+is\s+", re.IGNORECASE)
    if repo_token_prefix.match(fragment):
        return ensure_period("This project is " + repo_token_prefix.sub("", fragment))

    leading_verb = re.compile(
        r"^(provides|offers|implements|contains|collects|documents|explains|generates|includes|showcases|serves as|acts as|helps|enables|focuses on|targets)\b",
        re.IGNORECASE,
    )
    if leading_verb.match(fragment):
        return ensure_period(f"This project {sentence_case(fragment)}")

    return ensure_period(f"This project focuses on {sentence_case(fragment)}")


def pretty_repo_name(repo: str) -> str:
    return humanize_repo_name(repo)


def context_focus(category: str, subcategory: str) -> str:
    focus = f"{category}"
    if subcategory:
        focus = f"{category} / {subcategory}"
    return focus


def extract_annotation(line: str, repo_url: str) -> str:
    annotation = ""
    for label, url in MARKDOWN_LINK_RE.findall(line):
        if url.rstrip("/)") == repo_url.rstrip("/"):
            annotation = normalize_fragment(label)
            break

    if annotation:
        return annotation

    after = line.split(repo_url, 1)[1]
    match = re.search(r"\[([^\]]+)\]", after)
    if match:
        return normalize_fragment(match.group(1))
    return ""


def parse_readme_entries(text: str) -> list[RepoEntry]:
    marker_pos = text.find(SCAN_START_MARKER)
    scan_text = text[marker_pos:] if marker_pos != -1 else text

    category = "Uncategorized"
    subcategory = ""
    seen: set[tuple[str, str]] = set()
    entries: list[RepoEntry] = []

    for line in scan_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            category = stripped[3:].strip()
            subcategory = ""
            continue
        if stripped.startswith(">"):
            subcategory = stripped[1:].strip()
            continue

        for match in REPO_URL_RE.finditer(line):
            owner = match.group(1)
            repo = match.group(2).rstrip(".,;:")
            if owner == "gmh5225" and repo == "awesome-game-security":
                continue
            if owner == "stars":
                continue

            key = (owner.lower(), repo.lower())
            if key in seen:
                continue
            seen.add(key)

            repo_url = match.group(0).rstrip(".,;:")
            entries.append(
                RepoEntry(
                    owner=owner,
                    repo=repo,
                    category=category,
                    subcategory=subcategory,
                    annotation=extract_annotation(line, repo_url),
                    line_text=clean_whitespace(line),
                )
            )
    return entries


def archive_path(owner: str, repo: str) -> Path:
    return ARCHIVE_DIR / owner / f"{repo}.txt"


def description_path(owner: str, repo: str) -> Path:
    return DESC_DIR / owner / repo / "description_en.txt"


def read_archive_text(owner: str, repo: str) -> str:
    path = archive_path(owner, repo)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_archive_readme(archive_text: str) -> str:
    match = README_BLOCK_RE.search(archive_text)
    if not match:
        return ""
    return match.group(1)


def extract_source_tree(archive_text: str) -> str:
    match = TREE_BLOCK_RE.search(archive_text)
    if not match:
        return ""
    return match.group(1)


def paragraph_candidates(readme_text: str) -> list[str]:
    if not readme_text:
        return []

    lines: list[str] = []
    in_code = False
    for raw in readme_text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith(("- ", "* ", "+ ")):
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            continue

        plain = strip_markdown(stripped)
        plain = re.sub(r"^#+\s*", "", plain)
        plain = re.sub(r"^>\s*", "", plain)
        plain = re.sub(r"^[-*+]\s+", "", plain)
        plain = re.sub(r"^\d+\.\s+", "", plain)
        plain = clean_whitespace(plain)

        if not plain:
            lines.append("")
            continue

        lowered = plain.lower()
        if lowered in {"license", "contributing", "credits", "faq", "todo", "usage", "installation"}:
            lines.append("")
            continue
        if plain.startswith(":"):
            continue
        if len(plain) <= 4:
            continue
        if plain.isupper() and len(plain.split()) <= 6:
            continue
        if plain.startswith("Project Path:") or plain.startswith("Source Tree:"):
            continue
        lines.append(plain)

    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(clean_whitespace(" ".join(current)))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(clean_whitespace(" ".join(current)))
    return paragraphs


def sentence_candidates(readme_text: str, repo: str) -> list[str]:
    candidates: list[str] = []
    repo_name = normalized_compare(repo)

    for paragraph in paragraph_candidates(readme_text):
        if len(paragraph) < 25:
            continue
        for sentence in SENTENCE_SPLIT_RE.split(paragraph):
            sentence = clean_whitespace(sentence)
            if not sentence:
                continue
            lowered = sentence.lower().strip(". ")
            if lowered == repo_name:
                continue
            if normalized_compare(sentence) == repo_name:
                continue
            if lowered.startswith(("license", "copyright", "install", "usage", "contributing")):
                continue
            if any(token in lowered for token in ("sponsored by", "discord", "patreon", "telegram", "donate", "buy me a coffee", "follow me")):
                continue
            if len(sentence) < 25:
                continue
            if sentence[0].islower():
                continue
            if not mostly_ascii_letters(sentence):
                continue
            if sentence.count(":") > 2:
                continue
            if sum(sentence.count(symbol) for symbol in "*_|") > 2:
                continue
            if not is_descriptive_sentence(sentence):
                continue
            candidates.append(ensure_period(sentence))
        if len(candidates) >= 4:
            break

    return candidates[:4]


def top_languages(source_tree: str) -> list[str]:
    counts: Counter[str] = Counter()
    for raw_line in source_tree.splitlines():
        line = raw_line.strip()
        if not line or line.endswith("/"):
            continue
        _, ext = Path(line).suffix.lower(), Path(line).suffix.lower()
        if not ext:
            continue
        language = EXTENSION_LANGUAGES.get(ext)
        if not language:
            continue
        counts[language] += 1

    ordered = [name for name, _ in counts.most_common() if name not in {"Shell", "CMake"}]
    return ordered[:3]


def top_features(text: str) -> list[str]:
    lowered = text.lower()
    features: list[str] = []
    for token, label in FEATURE_PATTERNS:
        if token in lowered and label not in features:
            features.append(label)
    return features[:4]


def join_natural(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def fallback_summary(entry: RepoEntry) -> str:
    repo_name = pretty_repo_name(entry.repo).lower()
    if any(token in repo_name for token in ("guide", "notes", "tutorial", "book", "cheat sheet", "reference", "awesome", "list", "tips")):
        return ensure_period(f"This project provides {repo_name}")
    if any(token in repo_name for token in ("engine", "framework", "plugin", "tool", "tools", "sdk", "server", "emulator", "renderer", "library")):
        return ensure_period(f"This project provides {repo_name}")

    focus = context_focus(entry.category, entry.subcategory).lower()
    return ensure_period(
        f"This project is a repository listed under {focus} and centers on {repo_name}"
    )


def resource_sentence(entry: RepoEntry, languages: list[str], features: list[str], archive_exists: bool) -> str:
    annotation = entry.annotation
    lowered = annotation.lower()
    if any(token in lowered for token in ("list", "guide", "awesome", "tutorial", "cheat sheet", "notes", "book", "reference", "tips")):
        focus = context_focus(entry.category, entry.subcategory).lower()
        return ensure_period(
            f"It is organized as documentation and reference material for the {focus} area rather than as a single standalone runtime codebase"
        )

    parts: list[str] = []
    if languages:
        parts.append(f"It is primarily written in {join_natural(languages[:2])}")
    if features:
        verb = "centers on" if parts else "It centers on"
        parts.append(f"{verb} {join_natural(features[:3])}")
    if parts:
        return ensure_period(" and ".join(parts))
    if archive_exists:
        return "The archive includes source code and project documentation that outline the repository structure and main implementation areas."
    return "The README entry provides the main context for the project even though no local archive snapshot is available."


def audience_sentence(entry: RepoEntry, features: list[str]) -> str:
    audience = AUDIENCE_BY_CATEGORY.get(entry.category, "game security and tooling researchers")
    focus = context_focus(entry.category, entry.subcategory)
    return ensure_period(
        f"It is mainly useful for {audience} working in the {focus.lower()} area"
    )


def build_description(entry: RepoEntry, archive_text: str) -> str:
    archive_readme = extract_archive_readme(archive_text)
    source_tree = extract_source_tree(archive_text)
    readme_sentences = sentence_candidates(archive_readme, entry.repo)
    languages = top_languages(source_tree)
    features = top_features(" ".join([entry.annotation, entry.line_text, archive_readme, source_tree]))
    archive_exists = bool(archive_text)

    sentences: list[str] = []

    if entry.annotation and not is_generic_annotation(entry.annotation):
        sentences.append(fragment_to_sentence(entry.annotation, entry.repo))
    elif readme_sentences:
        sentences.append(fragment_to_sentence(readme_sentences[0], entry.repo))
    else:
        sentences.append(fallback_summary(entry))

    if readme_sentences:
        for candidate in readme_sentences[1:]:
            candidate = ensure_period(candidate)
            lowered = candidate.lower()
            if lowered not in {sentence.lower() for sentence in sentences}:
                sentences.append(candidate)
            if len(sentences) >= 2:
                break

    if len(sentences) < 2:
        sentences.append(resource_sentence(entry, languages, features, archive_exists))

    if len(sentences) < 3:
        sentences.append(audience_sentence(entry, features))

    deduped: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        normalized = clean_whitespace(sentence).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(ensure_period(sentence))

    if len(deduped) < 3:
        deduped.append(audience_sentence(entry, features))

    return "\n".join(deduped[:4])


def collect_entries() -> list[RepoEntry]:
    return parse_readme_entries(README_PATH.read_text(encoding="utf-8"))


def missing_entries(entries: list[RepoEntry], overwrite: bool) -> list[RepoEntry]:
    result: list[RepoEntry] = []
    for entry in entries:
        if overwrite or not description_path(entry.owner, entry.repo).exists():
            result.append(entry)
    return result


def write_description(entry: RepoEntry, description: str, dry_run: bool) -> None:
    path = description_path(entry.owner, entry.repo)
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(description + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill missing repo descriptions from README and local archives")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N matching repositories")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild descriptions even if they already exist")
    parser.add_argument("--dry-run", action="store_true", help="Preview output without writing files")
    parser.add_argument("--show", type=int, default=0, help="Print the first N generated descriptions")
    args = parser.parse_args()

    entries = collect_entries()
    targets = missing_entries(entries, args.overwrite)
    if args.limit:
        targets = targets[: args.limit]

    written = 0
    for index, entry in enumerate(targets, start=1):
        archive_text = read_archive_text(entry.owner, entry.repo)
        description = build_description(entry, archive_text)
        if args.show and index <= args.show:
            print(f"[{entry.owner}/{entry.repo}]")
            print(description)
            print()
        write_description(entry, description, args.dry_run)
        written += 1

    print(f"processed={len(targets)}")
    print(f"written={0 if args.dry_run else written}")


if __name__ == "__main__":
    main()