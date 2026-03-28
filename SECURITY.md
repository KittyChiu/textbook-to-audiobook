# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main`  | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public issue.
2. Email the maintainer via the contact information on their [GitHub profile](https://github.com/KittyChiu), or use [GitHub private vulnerability reporting](https://github.com/KittyChiu/textbook-to-audiobook/security/advisories/new).
3. Include a description of the vulnerability, steps to reproduce, and any potential impact.

You should receive a response within 7 days. We will work with you to understand and address the issue before any public disclosure.

## Scope

This project calls the Azure TTS REST API using credentials provided via environment variables. The scripts themselves do not run a server or accept untrusted network input. Security concerns most likely relate to:

- Credential handling (`AZURE_TTS_KEY`)
- Dependency supply-chain risks
- Input file parsing (SSML/QMD)
