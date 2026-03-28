#!/usr/bin/env python3
"""Synthesise MP3 audiobook files from SSML via Azure Text-To-Speech.

Usage (run from repo root):

    export AZURE_TTS_KEY='your-subscription-key'
    export AZURE_TTS_REGION='australiaeast'

    # To create the Speech resource and find the key/region in Azure Portal:
    # https://learn.microsoft.com/azure/ai-services/speech-service/get-started-text-to-speech?pivots=programming-language-rest

    python scripts/ssml_to_mp3.py                                # all files
    python scripts/ssml_to_mp3.py ssml/ch01.ssml  # one file
    python scripts/ssml_to_mp3.py --dry-run                      # preview only

Pipeline: handbook/*.qmd  ->  ssml/*.ssml  ->  mp3/*.mp3
                              (qmd_to_ssml.py)   (this script)

Reads SSML files from ssml/, splits large documents into API-safe chunks,
calls Azure TTS, concatenates the audio, and writes ID3-tagged MP3s to mp3/.

Constants (edit at the top of this file):

    ALBUM            ID3 album tag (default: "Awesome Book")
    ARTIST           ID3 artist tag (default: "Mystery Author")
    INPUT_DIR        Directory containing .ssml source files (default: "ssml")
    OUTPUT_DIR       Directory for generated .mp3 files (default: "mp3")
    OUTPUT_FORMAT    Azure TTS audio format (default: "audio-48khz-192kbitrate-mono-mp3")
    USER_AGENT       HTTP User-Agent sent to Azure TTS API
    MAX_CHUNK_CHARS  Max UTF-8 bytes per TTS request (default: 5000)
    SSML_LANG        Fallback BCP-47 language tag (default: "en-AU")
    VOICE_NAME       Fallback Azure Neural voice (default: "en-AU-WilliamNeural")
    TITLE_ACRONYMS   Words to keep uppercase in generated track titles
"""

import os
import re
import ssl
import struct
import sys
import time
import http.client
import argparse
import urllib.request
import urllib.error
from pathlib import Path

ALBUM = "Awesome Book"
ARTIST = "Mystery Author"
INPUT_DIR = "ssml"
OUTPUT_DIR = "mp3"
OUTPUT_FORMAT = "audio-48khz-192kbitrate-mono-mp3"
USER_AGENT = "some-user-tts"
SSML_LANG = "en-AU"
VOICE_NAME = "en-AU-WilliamNeural"
TITLE_ACRONYMS = {"Sdlc": "SDLC", "Ai": "AI", "Apm": "APM", "Prose": "PROSE"}

# Azure TTS limits: 60,000 UTF-8 bytes per request, 10 min audio output.
# Observed rate: ~1,000 SSML chars/min of speech (tags + entities inflate
# char count well above spoken word count). 5,000 chars ≈ 5 min audio,
# giving safe headroom below the 10-min audio ceiling.
MAX_CHUNK_CHARS = 5_000


def _build_ssl_context() -> ssl.SSLContext:
    """Build an SSL context that works across macOS Python installs.

    macOS framework Python (e.g. 3.11 from python.org) ships without
    root CA certificates. Try certifi first, then fall back to the
    default context which works on Homebrew Python.
    """
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    return ctx


SSL_CONTEXT = _build_ssl_context()


def get_config() -> tuple[str, str]:
    """Read Azure TTS credentials from environment."""
    key = os.environ.get("AZURE_TTS_KEY", "")
    region = os.environ.get("AZURE_TTS_REGION", "")
    if not key:
        print("ERROR: Set AZURE_TTS_KEY environment variable.")
        print("  export AZURE_TTS_KEY='your-subscription-key'")
        sys.exit(1)
    if not region:
        print("ERROR: Set AZURE_TTS_REGION environment variable.")
        print("  export AZURE_TTS_REGION='australiaeast'")
        sys.exit(1)
    return key, region


def fetch_access_token(key: str, region: str) -> str:
    """Exchange subscription key for a short-lived access token."""
    url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    req = urllib.request.Request(url, data=b"", method="POST")
    req.add_header("Ocp-Apim-Subscription-Key", key)
    req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
        return resp.read().decode("utf-8")


def split_ssml_into_chunks(ssml: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split a large SSML document into smaller chunks at paragraph boundaries.

    Each chunk is a complete <speak><voice>...</voice></speak> document.
    """
    if len(ssml.encode("utf-8")) <= max_chars:
        return [ssml]

    def byte_len(text: str) -> int:
        return len(text.encode("utf-8"))

    def split_token_by_bytes(token: str, max_bytes: int) -> list[str]:
        """Split one token into byte-safe pieces (no content loss)."""
        parts: list[str] = []
        current = ""
        for ch in token:
            if current and byte_len(current + ch) > max_bytes:
                parts.append(current)
                current = ch
            else:
                current += ch
        if current:
            parts.append(current)
        return parts

    def split_text_by_bytes(text: str, max_bytes: int) -> list[str]:
        """Split text at token boundaries first, then char boundaries if needed."""
        if max_bytes <= 0:
            return [text]

        tokens = re.findall(r"\S+\s*", text)
        if not tokens:
            return [text]

        out: list[str] = []
        current = ""

        for token in tokens:
            if byte_len(token) > max_bytes:
                if current:
                    out.append(current)
                    current = ""
                out.extend(split_token_by_bytes(token, max_bytes))
                continue

            if not current:
                current = token
            elif byte_len(current + token) <= max_bytes:
                current += token
            else:
                out.append(current)
                current = token

        if current:
            out.append(current)

        return out

    def split_oversized_paragraph(elem: str, budget_bytes: int) -> list[str]:
        """Split a <p>...</p> element into multiple paragraphs within budget."""
        m = re.match(r"^<p(\b[^>]*)>(.*)</p>$", elem.strip(), flags=re.DOTALL)
        if not m:
            return [elem]

        attrs = m.group(1)
        inner = m.group(2)
        open_tag = f"<p{attrs}>"
        close_tag = "</p>"
        fixed_overhead = byte_len(f"    {open_tag}{close_tag}\n")
        inner_budget = budget_bytes - fixed_overhead

        if inner_budget <= 0:
            return [elem]

        parts = split_text_by_bytes(inner, inner_budget)
        return [f"{open_tag}{part}{close_tag}" for part in parts]

    # Extract the xmlns and lang attributes
    speak_match = re.search(r"<speak([^>]*)>", ssml)
    speak_attrs = speak_match.group(1) if speak_match else f' version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{SSML_LANG}"'

    # Preserve the full voice tag attributes
    voice_open_match = re.search(r"(<voice[^>]*>)", ssml)
    voice_open = voice_open_match.group(1) if voice_open_match else f'<voice name="{VOICE_NAME}">'

    # Extract inner content between <voice> tags
    inner_match = re.search(r"<voice[^>]*>(.*)</voice>", ssml, re.DOTALL)
    if not inner_match:
        return [ssml]

    inner = inner_match.group(1).strip()

    # Split on paragraph + break boundaries.
    # Supports <p>...</p> and self-closing <break .../>.
    elements = re.findall(r"<p\b[^>]*>.*?</p>|<break\b[^>]*/>", inner, flags=re.DOTALL)
    if not elements:
        return [ssml]

    wrapper_open = f"<speak{speak_attrs}>\n  {voice_open}\n"
    wrapper_close = "\n  </voice>\n</speak>"
    wrapper_size = byte_len(wrapper_open) + byte_len(wrapper_close)
    budget = max_chars - wrapper_size

    chunks = []
    current_elements: list[str] = []
    current_size = 0

    for elem in elements:
        element_candidates = [elem.strip()]

        # If a single paragraph is too large, split it safely.
        elem_preview = f"    {elem.strip()}\n"
        if byte_len(elem_preview) > budget and elem.strip().startswith("<p"):
            element_candidates = split_oversized_paragraph(elem.strip(), budget)

        for candidate in element_candidates:
            elem_with_indent = f"    {candidate}\n"
            elem_size = byte_len(elem_with_indent)

            if current_size + elem_size > budget and current_elements:
                # Flush current chunk
                chunk_body = "".join(current_elements)
                chunks.append(f"{wrapper_open}{chunk_body}{wrapper_close}")
                current_elements = []
                current_size = 0

            # If still too large (extreme edge case), force-split text-only fallback
            if elem_size > budget and candidate.startswith("<p"):
                forced = split_oversized_paragraph(candidate, budget)
                for forced_elem in forced:
                    forced_line = f"    {forced_elem}\n"
                    forced_size = byte_len(forced_line)
                    if current_size + forced_size > budget and current_elements:
                        chunk_body = "".join(current_elements)
                        chunks.append(f"{wrapper_open}{chunk_body}{wrapper_close}")
                        current_elements = []
                        current_size = 0
                    current_elements.append(forced_line)
                    current_size += forced_size
                continue

            current_elements.append(elem_with_indent)
            current_size += elem_size

    if current_elements:
        chunk_body = "".join(current_elements)
        chunks.append(f"{wrapper_open}{chunk_body}{wrapper_close}")

    return chunks


def synthesize_ssml(ssml: str, token: str, region: str) -> bytes:
    """Call Azure TTS REST API and return MP3 audio bytes."""
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    req = urllib.request.Request(url, data=ssml.encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/ssml+xml")
    req.add_header("X-Microsoft-OutputFormat", OUTPUT_FORMAT)
    req.add_header("User-Agent", USER_AGENT)

    try:
        with urllib.request.urlopen(req, timeout=300, context=SSL_CONTEXT) as resp:
            return resp.read()
    except http.client.IncompleteRead as e:
        # Azure TTS streams large audio via chunked transfer encoding.
        # Python's urllib can fail to read the final empty chunk.
        # The partial data is valid MP3 (streaming format).
        if e.partial and len(e.partial) > 0:
            return e.partial
        raise


def synthesize_with_retry(ssml: str, token: str, region: str, max_retries: int = 3) -> bytes:
    """Synthesize with exponential backoff on rate-limit or transient errors."""
    for attempt in range(max_retries):
        try:
            return synthesize_ssml(ssml, token, region)
        except http.client.IncompleteRead as e:
            if e.partial and len(e.partial) > 0:
                return e.partial
            wait = 2 ** attempt
            print(f"    Incomplete read (0 bytes). Retrying in {wait}s...")
            time.sleep(wait)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                print(f"    Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 401 and attempt == 0:
                raise  # Token expired, caller should refresh
            elif 500 <= e.code < 600:
                wait = 2 ** attempt
                print(f"    Server error ({e.code}). Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    # Final attempt — let it raise
    return synthesize_ssml(ssml, token, region)


def _id3v2_frame(frame_id: str, text: str) -> bytes:
    """Build a single ID3v2.3 text frame."""
    encoded = text.encode("utf-8")
    # Encoding byte: 0x03 = UTF-8
    data = b"\x03" + encoded
    return (
        frame_id.encode("ascii")
        + struct.pack(">I", len(data))  # frame size (big-endian 32-bit)
        + b"\x00\x00"  # frame flags
        + data
    )


def write_id3_tags(mp3_path: Path, title: str, track_number: int, total_tracks: int) -> None:
    """Prepend ID3v2.3 header with title, album, track, and artist tags."""
    frames = b"".join([
        _id3v2_frame("TIT2", title),
        _id3v2_frame("TALB", ALBUM),
        _id3v2_frame("TRCK", f"{track_number}/{total_tracks}"),
        _id3v2_frame("TPE1", ARTIST),
    ])

    # ID3v2.3 header: "ID3" + version 2.3 + no flags + size (synchsafe)
    def synchsafe(n: int) -> bytes:
        return struct.pack(">I",
            ((n & 0x0FE00000) << 3)
            | ((n & 0x001FC000) << 2)
            | ((n & 0x00003F80) << 1)
            | (n & 0x0000007F)
        )

    header = b"ID3" + b"\x03\x00" + b"\x00" + synchsafe(len(frames))

    original = mp3_path.read_bytes()
    # Strip any existing ID3v2 header (starts with "ID3")
    if original[:3] == b"ID3":
        if len(original) >= 10:
            s = original[6:10]
            old_size = (s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3]
            original = original[10 + old_size:]

    mp3_path.write_bytes(header + frames + original)


def _title_from_ssml(ssml_path: Path) -> str:
    """Extract a human-readable chapter title from the SSML filename."""
    stem = ssml_path.stem 
    def fix_title(s: str) -> str:
        t = s.replace("-", " ").title()
        for wrong, right in TITLE_ACRONYMS.items():
            t = t.replace(wrong, right)
        return t

    m = re.match(r"ch(\d+)-(.*)", stem)
    if m:
        num = int(m.group(1))
        slug = fix_title(m.group(2))
        return f"Chapter {num}. {slug}"
    if stem.startswith("00-"):
        return fix_title(stem[3:])
    return fix_title(stem)


def _track_number_from_ssml(ssml_path: Path) -> int:
    """Extract track number: preface=0, ch01=1, etc."""
    m = re.search(r"ch(\d+)", ssml_path.stem)
    return int(m.group(1)) if m else 0


def process_file(
    ssml_path: Path,
    output_dir: Path,
    token: str,
    region: str,
    key: str,
    dry_run: bool = False,
) -> Path | None:
    """Convert a single SSML file to MP3. Returns output path or None on error."""
    output_path = output_dir / ssml_path.with_suffix(".mp3").name

    if dry_run:
        print(f"  [dry-run] {ssml_path.name} -> mp3/{output_path.name}")
        return output_path

    ssml_text = ssml_path.read_text(encoding="utf-8")
    chunks = split_ssml_into_chunks(ssml_text)

    total_chunks = len(chunks)
    audio_parts: list[bytes] = []

    for i, chunk in enumerate(chunks, 1):
        label = f"chunk {i}/{total_chunks}" if total_chunks > 1 else "single request"
        print(f"    Synthesizing {label} ({len(chunk):,} chars)...", end=" ", flush=True)

        try:
            audio = synthesize_with_retry(chunk, token, region)
            audio_parts.append(audio)
            print(f"OK ({len(audio):,} bytes)")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                # Token may have expired (10 min lifetime), refresh
                print("token expired, refreshing...", end=" ", flush=True)
                token = fetch_access_token(key, region)
                audio = synthesize_with_retry(chunk, token, region)
                audio_parts.append(audio)
                print(f"OK ({len(audio):,} bytes)")
            else:
                body = e.read().decode("utf-8", errors="replace")
                print(f"FAILED (HTTP {e.code}: {body[:200]})")
                return None

        # Pause between chunks to avoid rate limiting
        if i < total_chunks:
            time.sleep(1)

    # Concatenate MP3 chunks (MP3 is a streaming format, raw concat works)
    mp3_data = b"".join(audio_parts)
    output_path.write_bytes(mp3_data)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate MP3 from SSML via Azure TTS")
    parser.add_argument("files", nargs="*", help="Specific SSML files to convert (default: all in ssml/)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated without calling API")
    parser.add_argument("--output", "-o", default=OUTPUT_DIR, help=f"Output directory (default: {OUTPUT_DIR})")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    ssml_dir = repo_root / INPUT_DIR
    output_dir = repo_root / args.output
    output_dir.mkdir(exist_ok=True)

    # Collect files
    if args.files:
        ssml_files = [Path(f) if Path(f).is_absolute() else repo_root / f for f in args.files]
    else:
        ssml_files = sorted(ssml_dir.glob("*.ssml"))

    if not ssml_files:
        print("No SSML files found.")
        sys.exit(1)

    print(f"Found {len(ssml_files)} SSML file(s) to convert.\n")

    if not args.dry_run:
        key, region = get_config()
        print(f"Region: {region}")
        print("Fetching access token...", end=" ", flush=True)
        token = fetch_access_token(key, region)
        print("OK\n")
    else:
        key, region, token = "", "", ""

    success = 0
    failed = 0

    total_tracks = len(ssml_files)

    for track, ssml_path in enumerate(ssml_files, 1):
        if not ssml_path.exists():
            print(f"  SKIP {ssml_path} (not found)")
            failed += 1
            continue

        print(f"  {ssml_path.name}")
        result = process_file(ssml_path, output_dir, token, region, key, args.dry_run)

        if result:
            if not args.dry_run:
                title = _title_from_ssml(ssml_path)
                write_id3_tags(result, title, track, total_tracks)
                size_kb = result.stat().st_size / 1024
                print(f"    -> {args.output}/{result.name} ({size_kb:.0f} KB) [Track {track}/{total_tracks}]\n")
            success += 1
        else:
            failed += 1
            print()

    print(f"Done. {success} succeeded, {failed} failed.")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
