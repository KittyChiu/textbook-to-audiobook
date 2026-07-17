# QMD-to-Audiobook Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Convert Markdown (`.md`) chapters into an audiobook via Quarto (`.qmd`) and Azure Text-To-Speech.

## Pipeline

```text
markdown/*.md  ──►  qmd/*.qmd  ──►  ssml/*.ssml  ──►  mp3/*.mp3
                 markdown_to_qmd.py   qmd_to_ssml.py    ssml_to_mp3.py
```

## Folder structure

```text
project-root/
├── README.md              # This file
├── LICENSE                # MIT License
├── CODEOWNERS             # GitHub code-ownership rules
├── CODE_OF_CONDUCT.md     # Contributor Covenant
├── CONTRIBUTING.md        # How to contribute
├── SECURITY.md            # Vulnerability reporting policy
├── markdown/              # Source chapters (*.md)
│   ├── Chapter 1.md
│   ├── Chapter 2.md
│   └── ...
├── qmd/                   # Quarto source chapters (*.qmd)
│   ├── chapter-1.qmd
│   ├── chapter-2.qmd
│   └── ...
├── ssml/                  # Generated SSML (one per chapter)
├── mp3/                   # Generated MP3 audiobook files
└── scripts/
    ├── markdown_to_qmd.py # Step 1: Markdown → QMD
    ├── qmd_to_ssml.py     # Step 2: QMD → SSML
    └── ssml_to_mp3.py     # Step 3: SSML → MP3 via Azure TTS
```

## Prerequisites

- Python 3.10+
- An [Azure Speech Services](https://azure.microsoft.com/products/ai-services/text-to-speech) subscription key and region

Optional (for macOS with framework Python):

```bash
pip install certifi
```

## Configuration

1. Copy `.env.example` to `.env`.
2. Review the sectioned config keys in `.env`.
3. Set real Azure credentials in `.env` for non-dry runs.

All scripts load configuration from `.env` and support CLI directory overrides.
Config precedence is:

1. CLI flags
2. `.env` or process environment

## Step 1 — Generate QMD from Markdown

```bash
python3 scripts/markdown_to_qmd.py
```

Converts top-level `.md` files in `markdown/` to slugified `.qmd` files in `qmd/`,
adds frontmatter title from the source filename, and normalizes body formatting.

CLI options:

```bash
python3 scripts/markdown_to_qmd.py --overwrite
python3 scripts/markdown_to_qmd.py --input-dir markdown --output-dir qmd
```

## Step 2 — Generate SSML from QMD

```bash
python3 scripts/qmd_to_ssml.py
python3 scripts/qmd_to_ssml.py --input-dir qmd --output-dir ssml
```

Discovers all `.qmd` files in `qmd/` (plus any configured extras),
strips code blocks, tables, and Quarto directives, and writes one `.ssml` file
per chapter to `ssml/`.

QMD-to-SSML keys are configured in `.env` under:

- `QMD_TO_SSML_INPUT_DIR`
- `QMD_TO_SSML_OUTPUT_DIR`
- `QMD_TO_SSML_EXTRA_TEXT_FILES`
- `SHARED_SSML_LANG`
- `SHARED_VOICE_NAME`

## Step 3 — Synthesise MP3 from SSML

```bash
python3 scripts/ssml_to_mp3.py              # all files
python3 scripts/ssml_to_mp3.py --dry-run    # preview only (no API calls)
python3 scripts/ssml_to_mp3.py ssml/ch01.ssml  # one file
python3 scripts/ssml_to_mp3.py --output-dir output/   # custom output directory
```

If you do not already have `AZURE_TTS_KEY` and `AZURE_TTS_REGION`, create an
Azure Speech resource and then copy the key and region from the resource page in
Azure Portal:

- [Azure Text to Speech quickstart](https://learn.microsoft.com/azure/ai-services/speech-service/get-started-text-to-speech?pivots=programming-language-rest)

Reads `.ssml` files, splits large documents into API-safe chunks (≤ 5 KB),
calls Azure TTS, concatenates audio, and writes ID3-tagged MP3 files to `mp3/`.

SSML-to-MP3 keys are configured in `.env` under:

- `SSML_TO_MP3_INPUT_DIR`
- `SSML_TO_MP3_OUTPUT_DIR`
- `SSML_TO_MP3_ALBUM`
- `SSML_TO_MP3_ARTIST`
- `SSML_TO_MP3_USER_AGENT`
- `SSML_TO_MP3_MAX_CHUNK_CHARS`
- `SSML_TO_MP3_TITLE_ACRONYMS`
- `AZURE_TTS_KEY` (required for non-dry runs)
- `AZURE_TTS_REGION` (required for non-dry runs)

## Naming conventions

The pipeline assumes chapter files follow this pattern:

```text
my-chapter.qmd  →  my-chapter.ssml  →  my-chapter.mp3
```

- Titles are derived from the filename: hyphens become spaces and each word is title-cased (e.g. `01-intro-topic.qmd` → "01 Intro Topic").
- Acronyms listed in `TITLE_ACRONYMS` are preserved (e.g. "Sdlc" → "SDLC").
- Track numbers are assigned by sorted file order (1-based).

## Quick start for a new project

```bash
# 1. Copy the scripts
mkdir -p my-book/scripts
cp scripts/markdown_to_qmd.py scripts/qmd_to_ssml.py scripts/ssml_to_mp3.py my-book/scripts/

# 2. Add your content
mkdir my-book/chapters
# ... add your .md files ...

# 3. Configure .env values
cp .env.example .env
# edit .env as needed

# 4. Run the pipeline
cd my-book
python3 scripts/markdown_to_qmd.py
python3 scripts/qmd_to_ssml.py
python3 scripts/ssml_to_mp3.py
```
