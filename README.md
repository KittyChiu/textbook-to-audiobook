# QMD-to-Audiobook Pipeline

Convert Quarto (`.qmd`) chapters into an audiobook via Azure Text-To-Speech.

## Pipeline

```
qmd/*.qmd  ──►  ssml/*.ssml  ──►  mp3/*.mp3
                 qmd_to_ssml.py    ssml_to_mp3.py
```

## Folder structure

```
project-root/
├── README.md              # README
├── index.qmd              # Extra source file (e.g. preface)
├── qmd/                   # Quarto source chapters (*.qmd)
│   ├── ch01-*.qmd
│   ├── ch02-*.qmd
│   └── ...
├── ssml/                  # Generated SSML (one per chapter)
├── mp3/                   # Generated MP3 audiobook files
└── scripts/
    ├── qmd_to_ssml.py     # Step 1: Markdown → SSML
    └── ssml_to_mp3.py     # Step 2: SSML → MP3 via Azure TTS
```

## Prerequisites

- Python 3.10+
- An [Azure Speech Services](https://azure.microsoft.com/products/ai-services/text-to-speech) subscription key and region

Optional (for macOS with framework Python):

```bash
pip install certifi
```

## Step 1 — Generate SSML from QMD

```bash
python3 scripts/qmd_to_ssml.py
```

Discovers all `.qmd` files in `qmd/` (plus any extras like `index.qmd`),
strips code blocks, tables, and Quarto directives, and writes one `.ssml` file
per chapter to `ssml/`.

### Configuration

Edit constants at the top of `qmd_to_ssml.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `VOICE_NAME` | `en-AU-WilliamNeural` | Azure Neural voice written into SSML |
| `SSML_LANG` | `en-AU` | BCP-47 language tag |
| `INPUT_DIR` | `qmd` | Directory containing `.qmd` source files |
| `INPUT_FILE_EXT` | `.qmd` | File extension to glob |
| `OUTPUT_DIR` | `ssml` | Output directory (created if missing) |
| `EXTRA_TEXT_FILES` | `["index.qmd"]` | Additional files outside `INPUT_DIR` |
| `BREAK_TIMINGS` | *(see source)* | Pause durations around headings, tables, lists |

### Adapting for a new project

1. Set `INPUT_DIR` to your content directory.
2. Set `EXTRA_TEXT_FILES` to any files outside that directory (e.g. a preface).
3. Choose a [voice](https://learn.microsoft.com/azure/ai-services/speech-service/language-support) and set `VOICE_NAME` / `SSML_LANG`.
4. Tune `BREAK_TIMINGS` for your content style.

## Step 2 — Synthesise MP3 from SSML

```bash
export AZURE_TTS_KEY='your-subscription-key'
export AZURE_TTS_REGION='australiaeast'

python3 scripts/ssml_to_mp3.py              # all files
python3 scripts/ssml_to_mp3.py --dry-run    # preview only (no API calls)
python3 scripts/ssml_to_mp3.py ssml/ch01.ssml  # one file
python3 scripts/ssml_to_mp3.py -o output/   # custom output directory
```

Reads `.ssml` files, splits large documents into API-safe chunks (≤ 5 KB),
calls Azure TTS, concatenates audio, and writes ID3-tagged MP3 files to `mp3/`.

### Configuration

Edit constants at the top of `ssml_to_mp3.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `ALBUM` | `Awesome Book` | ID3 album tag |
| `ARTIST` | `Joe Bob` | ID3 artist tag |
| `INPUT_DIR` | `ssml` | Directory containing `.ssml` files |
| `OUTPUT_DIR` | `mp3` | Output directory (created if missing) |
| `OUTPUT_FORMAT` | `audio-48khz-192kbitrate-mono-mp3` | Azure TTS audio format |
| `USER_AGENT` | `some-user-tts` | HTTP User-Agent header |
| `MAX_CHUNK_CHARS` | `5000` | Max UTF-8 bytes per API request |
| `SSML_LANG` | `en-AU` | Fallback language tag (if not in SSML) |
| `VOICE_NAME` | `en-AU-WilliamNeural` | Fallback voice (if not in SSML) |
| `TITLE_ACRONYMS` | `{"Sdlc": "SDLC", ...}` | Words to keep uppercase in track titles |

### Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `AZURE_TTS_KEY` | Yes | Azure Speech Services subscription key |
| `AZURE_TTS_REGION` | Yes | Azure region (e.g. `australiaeast`) |

### Adapting for a new project

1. Set `ALBUM` and `ARTIST` to your book metadata.
2. Set `USER_AGENT` to your project name.
3. Set `TITLE_ACRONYMS` to domain-specific terms that should stay uppercase.
4. Adjust `OUTPUT_FORMAT` if you need a different bitrate or codec.

## Naming conventions

The pipeline assumes chapter files follow this pattern:

```
ch01-slug-name.qmd  →  ch01-slug-name.ssml  →  ch01-slug-name.mp3
```

- Files starting with `ch{NN}` get a "Chapter N. Title" spoken header and ID3 title.
- Files starting with `00-` are treated as a preface.
- All other files use their filename as the title.
- Track numbers are assigned by sorted file order (1-based).

## Quick start for a new project

```bash
# 1. Copy the scripts
mkdir -p my-book/scripts
cp scripts/qmd_to_ssml.py scripts/ssml_to_mp3.py my-book/scripts/

# 2. Add your content
mkdir my-book/chapters
# ... add your .qmd files ...

# 3. Edit constants in both scripts
#    - qmd_to_ssml.py: INPUT_DIR, VOICE_NAME, EXTRA_TEXT_FILES
#    - ssml_to_mp3.py: ALBUM, ARTIST, USER_AGENT, TITLE_ACRONYMS

# 4. Run the pipeline
cd my-book
python3 scripts/qmd_to_ssml.py
export AZURE_TTS_KEY='...' AZURE_TTS_REGION='...'
python3 scripts/ssml_to_mp3.py
```
