#!/usr/bin/env python3
"""Convert Quarto (.qmd) handbook chapters to SSML for Azure Text-To-Speech.

Usage (run from repo root):

    python3 scripts/qmd_to_ssml.py          # generate all SSML files
    python3 scripts/ssml_to_mp3.py           # then synthesise MP3 audio

Pipeline: handbook/*.qmd  ->  ssml/*.ssml  ->  mp3/*.mp3

Discovers all .qmd files in INPUT_DIR plus EXTRA_TEXT_FILES, parses Markdown
and YAML frontmatter, and writes one .ssml file per chapter to OUTPUT_DIR.

Constants (edit at the top of this file):

    VOICE_NAME       Azure Neural voice (default: "en-AU-WilliamNeural")
    SSML_LANG        BCP-47 language tag (default: "en-AU")
    INPUT_DIR        Source directory (default: "handbook")
    OUTPUT_DIR       Output directory, created if missing (default: "ssml")
    EXTRA_TEXT_FILES  Extra sources outside INPUT_DIR (default: ["index.qmd"])
    BREAK_TIMINGS    Pause durations (ms) around headings, tables, lists, etc.
"""

import re
import sys
import html
from pathlib import Path

VOICE_NAME = "en-AU-WilliamNeural"
SSML_LANG = "en-AU"
INPUT_DIR = "handbook"
INPUT_FILE_EXT = ".qmd"
OUTPUT_DIR = "ssml"
BREAK_TIMINGS = {
    "hr": "800ms",
    "h1_before": "1000ms",
    "h1_after": "700ms",
    "h2_before": "900ms",
    "h2_after": "600ms",
    "h3_before": "700ms",
    "h3_after": "500ms",
    "h4_before": "500ms",
    "h4_after": "400ms",
    "table_before": "500ms",
    "table_after": "500ms",
    "list_item_after": "300ms",
    "chapter_title_after": "1000ms",
}
EXTRA_TEXT_FILES = ["index.qmd"]

def discover_chapters(repo_root: Path) -> list[str]:
    """Build chapter list from INPUT_DIR/*{INPUT_FILE_EXT} (alphanumeric order)."""
    ext = INPUT_FILE_EXT if INPUT_FILE_EXT.startswith(".") else f".{INPUT_FILE_EXT}"
    handbook_qmds = sorted((repo_root / INPUT_DIR).glob(f"*{ext}"), key=lambda p: p.name)
    discovered = [p.relative_to(repo_root).as_posix() for p in handbook_qmds]

    # Merge declarative extras while preserving alphanumeric order and uniqueness.
    all_files = sorted(set(discovered + EXTRA_TEXT_FILES))
    return all_files


def extract_frontmatter_and_body(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return metadata + body."""
    meta = {}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip().strip('"')] = val.strip().strip('"')
        body = text[m.end():]
    return meta, body


def strip_quarto_divs(text: str) -> str:
    """Remove Quarto div fences (::: {.*}) and closing (:::).
    Keep the inner content, but skip content-visible/content-hidden blocks entirely."""
    lines = text.splitlines()
    result = []
    skip_depth = 0
    div_depth = 0

    for line in lines:
        stripped = line.strip()

        # Detect opening div
        if stripped.startswith("::: {"):
            div_depth += 1
            # Skip content-visible/content-hidden blocks and tbl-colwidths
            if any(kw in stripped for kw in ["content-visible", "content-hidden", "tbl-colwidths"]):
                skip_depth = div_depth
            continue
        elif stripped == ":::":
            if div_depth > 0:
                if skip_depth == div_depth:
                    skip_depth = 0
                div_depth -= 1
            continue

        if skip_depth > 0:
            continue

        result.append(line)

    return "\n".join(result)


def remove_code_blocks(text: str) -> str:
    """Remove fenced code blocks (``` ... ```) and mermaid blocks."""
    # Remove mermaid blocks first (```{mermaid} ... ```)
    text = re.sub(
        r"```\{mermaid\}.*?```",
        "\n(A diagram is shown here in the book.)\n",
        text,
        flags=re.DOTALL,
    )
    # Remove other fenced code blocks with a spoken note
    text = re.sub(
        r"```\w*\n.*?```",
        "\n(A code example is shown here in the book.)\n",
        text,
        flags=re.DOTALL,
    )
    return text


def remove_footnote_definitions(text: str) -> str:
    """Remove footnote definition lines like [^ch1-ref]: ..."""
    return re.sub(r"^\[\^[^\]]+\]:.*$", "", text, flags=re.MULTILINE)


def clean_inline_markdown(text: str) -> str:
    """Convert inline markdown to speakable plain text."""
    # Remove footnote references [^ch1-ref]
    text = re.sub(r"\[\^[^\]]+\]", "", text)

    # Convert links [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remove images ![alt](url)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)

    # Bold **text** or __text__ → text (with emphasis in SSML handled separately)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)

    # Italic *text* or _text_ → text
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"\1", text)

    # Inline code `text` → text
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Remove Quarto variables {{< var ... >}}
    text = re.sub(r"\{\{<\s*var\s+[^>]+\s*>\}\}", "", text)

    # Remove any leftover {{ }} or {{}}
    text = re.sub(r"\{\{\s*\}\}", "", text)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Clean up multiple spaces
    text = re.sub(r"  +", " ", text)

    return text.strip()


def table_to_speech(table_text: str) -> list[str]:
    """Convert a markdown table to speakable sentences."""
    lines = [l.strip() for l in table_text.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return []

    # Parse header
    headers = [h.strip() for h in lines[0].split("|") if h.strip()]

    # Skip separator line (line with ---)
    data_lines = [l for l in lines[2:] if not re.match(r"^[\s|:-]+$", l)]

    spoken = []
    for row_line in data_lines:
        cells = [c.strip() for c in row_line.split("|") if c.strip()]
        if not cells:
            continue
        parts = []
        for i, cell in enumerate(cells):
            if i < len(headers) and cell:
                cell_clean = clean_inline_markdown(cell)
                header_clean = clean_inline_markdown(headers[i])
                if cell_clean:
                    parts.append(f"{header_clean}: {cell_clean}")
        if parts:
            spoken.append(". ".join(parts) + ".")

    return spoken


def process_body(body: str) -> list[str]:
    """Process markdown body into a list of SSML paragraphs/breaks."""
    elements = []

    # Pre-process: strip quarto divs
    body = strip_quarto_divs(body)

    # Remove code blocks (replace with spoken note)
    body = remove_code_blocks(body)

    # Remove footnote definitions
    body = remove_footnote_definitions(body)

    # Remove lines that are just punctuation/whitespace after variable stripping
    body = re.sub(r"^\s*[·\-–—]+\s*$", "", body, flags=re.MULTILINE)

    # Remove callout markers but keep their content
    body = re.sub(r"^\*\*(.+?)\*\*\s*$", r"\1", body, flags=re.MULTILINE)

    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # Horizontal rule → pause
        if re.match(r"^---+$", line):
            elements.append(("break", BREAK_TIMINGS["hr"]))
            i += 1
            continue

        # Headings
        m = re.match(r"^(#{1,4})\s+(.+?)(?:\s*\{[^}]*\})?$", line)
        if m:
            level = len(m.group(1))
            heading_text = clean_inline_markdown(m.group(2))
            if level == 1:
                elements.append(("break", BREAK_TIMINGS["h1_before"]))
                elements.append(("paragraph", heading_text))
                elements.append(("break", BREAK_TIMINGS["h1_after"]))
            elif level == 2:
                elements.append(("break", BREAK_TIMINGS["h2_before"]))
                elements.append(("paragraph", heading_text))
                elements.append(("break", BREAK_TIMINGS["h2_after"]))
            elif level == 3:
                elements.append(("break", BREAK_TIMINGS["h3_before"]))
                elements.append(("paragraph", heading_text))
                elements.append(("break", BREAK_TIMINGS["h3_after"]))
            else:
                elements.append(("break", BREAK_TIMINGS["h4_before"]))
                elements.append(("paragraph", heading_text))
                elements.append(("break", BREAK_TIMINGS["h4_after"]))
            i += 1
            continue

        # Table detection (line starts with |)
        if line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            table_text = "\n".join(table_lines)
            spoken_rows = table_to_speech(table_text)
            if spoken_rows:
                elements.append(("break", BREAK_TIMINGS["table_before"]))
                for row in spoken_rows:
                    elements.append(("paragraph", clean_inline_markdown(row)))
                elements.append(("break", BREAK_TIMINGS["table_after"]))
            continue

        # List items (- or * or numbered)
        if re.match(r"^[-*]\s+", line) or re.match(r"^\d+\.\s+", line):
            # Collect multi-line list item
            item_text = re.sub(r"^[-*\d.]+\s+", "", line)
            i += 1
            # Continuation lines (indented or not empty, not a new list item or heading)
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                if not next_stripped:
                    break
                if re.match(r"^[-*]\s+", next_stripped) or re.match(r"^\d+\.\s+", next_stripped):
                    break
                if re.match(r"^#{1,4}\s+", next_stripped):
                    break
                if next_stripped.startswith("|"):
                    break
                if re.match(r"^---+$", next_stripped):
                    break
                item_text += " " + next_stripped
                i += 1

            cleaned = clean_inline_markdown(item_text)
            if cleaned:
                elements.append(("paragraph", cleaned))
                elements.append(("break", BREAK_TIMINGS["list_item_after"]))
            continue

        # Regular paragraph — collect consecutive non-empty lines
        para_lines = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i].strip()
            if not next_line:
                break
            if re.match(r"^#{1,4}\s+", next_line):
                break
            if next_line.startswith("|"):
                break
            if re.match(r"^[-*]\s+", next_line):
                break
            if re.match(r"^\d+\.\s+", next_line):
                break
            if re.match(r"^---+$", next_line):
                break
            if next_line.startswith(":::"):
                break
            para_lines.append(next_line)
            i += 1

        para_text = " ".join(para_lines)
        cleaned = clean_inline_markdown(para_text)
        if cleaned:
            elements.append(("paragraph", cleaned))

    return elements


def elements_to_ssml(elements: list[tuple], chapter_title: str | None = None) -> str:
    """Convert elements list to SSML XML string."""
    parts = [f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{SSML_LANG}">',
             f'  <voice name="{VOICE_NAME}">']

    if chapter_title:
        parts.append(f"    <p>{html.escape(chapter_title)}</p>")
        parts.append(f'    <break time="{BREAK_TIMINGS["chapter_title_after"]}"/>')

    last_was_break = False
    for elem_type, value in elements:
        if elem_type == "break":
            if last_was_break:
                # Skip consecutive breaks, keep the longer one
                # Replace previous break if this one is longer
                prev = parts[-1]
                prev_time = int(re.search(r'(\d+)', prev).group(1))
                curr_time = int(re.search(r'(\d+)', value).group(1))
                if curr_time > prev_time:
                    parts[-1] = f'    <break time="{value}"/>'
                continue
            parts.append(f'    <break time="{value}"/>')
            last_was_break = True
        elif elem_type == "paragraph":
            escaped = html.escape(value)
            # Skip empty or whitespace-only paragraphs
            if not escaped.strip():
                continue
            parts.append(f"    <p>{escaped}</p>")
            last_was_break = False

    parts.append("  </voice>")
    parts.append("</speak>")
    return "\n".join(parts)


def convert_chapter(repo_root: Path, qmd_path: str) -> tuple[str, str]:
    """Convert a single QMD file to SSML. Returns (output_filename, ssml_content)."""
    full_path = repo_root / qmd_path
    text = full_path.read_text(encoding="utf-8")

    meta, body = extract_frontmatter_and_body(text)
    title = meta.get("title", "Untitled")

    # Keep output filename aligned with source filename
    output_name = f"{Path(qmd_path).stem}.ssml"

    # Determine chapter number from filename
    ch_match = re.search(r"ch(\d+)", qmd_path)
    if ch_match:
        ch_num = int(ch_match.group(1))
        chapter_title = f"Chapter {ch_num}. {title}"
    else:
        chapter_title = title

    elements = process_body(body)
    ssml = elements_to_ssml(elements, chapter_title)

    return output_name, ssml


def main():
    repo_root = Path(__file__).resolve().parent.parent
    output_dir = repo_root / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    chapters = discover_chapters(repo_root)

    for qmd_path in chapters:
        full_path = repo_root / qmd_path
        if not full_path.exists():
            print(f"  SKIP {qmd_path} (not found)")
            continue

        output_name, ssml_content = convert_chapter(repo_root, qmd_path)
        out_file = output_dir / output_name
        out_file.write_text(ssml_content, encoding="utf-8")
        print(f"  OK   {qmd_path} -> ssml/{output_name}")

    print(f"\nDone. {len(chapters)} files written to ssml/")


if __name__ == "__main__":
    main()
