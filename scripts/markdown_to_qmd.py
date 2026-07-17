#!/usr/bin/env python3
"""Convert Markdown chapters to normalized Quarto (.qmd) files.

Usage (run from repo root):

    python3 scripts/markdown_to_qmd.py
    python3 scripts/markdown_to_qmd.py --overwrite
    python3 scripts/markdown_to_qmd.py --input-dir markdown --output-dir qmd

Pipeline: markdown/*.md  ->  qmd/*.qmd  ->  ssml/*.ssml  ->  mp3/*.mp3

Behavior:
- Discovers top-level .md files from INPUT_DIR in sorted order.
- Writes slugified .qmd filenames to OUTPUT_DIR.
- Uses source filename stem as frontmatter title.
- Keeps at most one H1 in body; demotes additional H1 headings to H2.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from config import ConfigError, load_markdown_to_qmd_settings

INPUT_EXT = ".md"
OUTPUT_EXT = ".qmd"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert markdown files to normalized qmd files.")
    parser.add_argument("--input-dir", help="Directory containing source markdown files")
    parser.add_argument("--output-dir", help="Directory for generated qmd files")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files instead of skipping",
    )
    return parser.parse_args()


def slugify(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "untitled"


def discover_markdown_files(repo_root: Path, input_dir: str) -> list[Path]:
    source_dir = repo_root / input_dir
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {source_dir}")
    return sorted(source_dir.glob(f"*{INPUT_EXT}"), key=lambda p: p.name)


def normalize_atx_spacing(line: str) -> str:
    return re.sub(r"^(\s{0,3}#{1,6})([^\s#])", r"\1 \2", line)


def normalize_list_marker_spacing(line: str) -> str:
    line = re.sub(r"^(\s*[-*+])([^\s])", r"\1 \2", line)
    line = re.sub(r"^(\s*\d+\.)([^\s])", r"\1 \2", line)
    return line


def demote_extra_h1(lines: list[str]) -> list[str]:
    output: list[str] = []
    in_fence = False
    fence_token = ""
    seen_h1 = False
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        fence_match = re.match(r"^\s*(```+|~~~+)", line)
        if fence_match:
            token = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_token = token[0]
            elif token[0] == fence_token:
                in_fence = False
                fence_token = ""
            output.append(line)
            i += 1
            continue

        if in_fence:
            output.append(line)
            i += 1
            continue

        atx_h1 = re.match(r"^(\s{0,3})#\s+(.+?)\s*$", line)
        if atx_h1:
            if seen_h1:
                output.append(f"{atx_h1.group(1)}## {atx_h1.group(2)}")
            else:
                output.append(line)
                seen_h1 = True
            i += 1
            continue

        if i + 1 < len(lines):
            next_line = lines[i + 1]
            if re.match(r"^\s*=+\s*$", next_line):
                if seen_h1:
                    output.append(f"## {line.strip()}")
                else:
                    output.append(line)
                    output.append(next_line)
                    seen_h1 = True
                i += 2
                continue

        output.append(line)
        i += 1

    return output


def collapse_blank_runs(lines: list[str], max_blank: int = 2) -> list[str]:
    output: list[str] = []
    blanks = 0
    for line in lines:
        if line.strip() == "":
            blanks += 1
            if blanks <= max_blank:
                output.append("")
        else:
            blanks = 0
            output.append(line)
    return output


def normalize_body(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    lines = demote_extra_h1(lines)
    lines = [normalize_atx_spacing(ln) for ln in lines]
    lines = [normalize_list_marker_spacing(ln) for ln in lines]
    lines = collapse_blank_runs(lines)
    normalized = "\n".join(lines).strip("\n")
    return normalized + "\n"


def build_frontmatter(title: str) -> str:
    escaped_title = title.replace('"', '\\"')
    return f"---\ntitle: \"{escaped_title}\"\n---\n\n"


def unique_output_path(base_slug: str, output_dir: Path, used: set[str]) -> Path:
    candidate = base_slug
    counter = 2
    while f"{candidate}{OUTPUT_EXT}" in used:
        candidate = f"{base_slug}-{counter}"
        counter += 1
    used.add(f"{candidate}{OUTPUT_EXT}")
    return output_dir / f"{candidate}{OUTPUT_EXT}"


def convert_file(input_path: Path, output_path: Path, overwrite: bool) -> str:
    if output_path.exists() and not overwrite:
        return "skip-exists"

    body = input_path.read_text(encoding="utf-8")
    title = input_path.stem
    frontmatter = build_frontmatter(title)
    normalized = normalize_body(body)
    output_path.write_text(frontmatter + normalized, encoding="utf-8")
    return "ok"


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent

    try:
        settings = load_markdown_to_qmd_settings()
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1

    input_dir = args.input_dir or settings.input_dir
    output_dir_name = args.output_dir or settings.output_dir

    output_dir = repo_root / output_dir_name
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        md_files = discover_markdown_files(repo_root, input_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    used_names: set[str] = set()
    converted = 0

    for md_file in md_files:
        slug = slugify(md_file.stem)
        out_path = unique_output_path(slug, output_dir, used_names)

        try:
            result = convert_file(md_file, out_path, args.overwrite)
        except UnicodeDecodeError:
            rel_in = md_file.relative_to(repo_root).as_posix()
            print(f"  SKIP {rel_in} (utf-8 decode failed)")
            continue
        except Exception as exc:
            rel_in = md_file.relative_to(repo_root).as_posix()
            print(f"  SKIP {rel_in} (error: {exc})")
            continue

        rel_in = md_file.relative_to(repo_root).as_posix()
        rel_out = out_path.relative_to(repo_root).as_posix()

        if result == "skip-exists":
            print(f"  SKIP {rel_in} ({rel_out} exists; use --overwrite)")
            continue

        print(f"  OK   {rel_in} -> {rel_out}")
        converted += 1

    print(f"\nDone. {converted} files written to {output_dir_name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
