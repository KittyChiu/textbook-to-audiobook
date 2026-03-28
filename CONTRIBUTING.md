# Contributing to QMD-to-Audiobook Pipeline

Thanks for your interest in contributing! Here's how to get started.

## Getting started

1. Fork the repository and clone your fork locally.
2. Create a branch for your change: `git checkout -b my-feature`.
3. Make your changes and test them locally.
4. Commit with a clear message and push to your fork.
5. Open a pull request against `main`.

## Development setup

- Python 3.10+
- No additional dependencies are required (stdlib only).
- On macOS with framework Python, `pip install certifi` may be needed for SSL.

## Running the pipeline

```bash
# Step 1: Generate SSML from QMD
python3 scripts/qmd_to_ssml.py

# Step 2: Synthesise MP3 (requires Azure TTS credentials)
export AZURE_TTS_KEY='your-key'
export AZURE_TTS_REGION='your-region'
python3 scripts/ssml_to_mp3.py --dry-run   # preview first
python3 scripts/ssml_to_mp3.py             # run for real
```

## Guidelines

- Keep changes focused — one issue or feature per pull request.
- Follow the existing code style (no linter is enforced yet, but consistency is appreciated).
- Update `README.md` if your change affects usage or configuration.
- Do not commit generated files (`mp3/`, `ssml/` outputs).

## Reporting issues

Open a [GitHub issue](https://github.com/KittyChiu/textbook-to-audiobook/issues) with:

- A clear description of the problem or suggestion.
- Steps to reproduce (if applicable).
- Your Python version and OS.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
