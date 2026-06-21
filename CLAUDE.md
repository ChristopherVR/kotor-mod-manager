# Project rules

This is a KOTOR mod downloader and auto-installer aimed at regular players, not
developers. Keep that audience in mind for anything user-facing.

## Writing style

- Never use em-dashes (the long dash, Unicode U+2014) anywhere: not in code,
  comments, UI strings, docs, commit messages, or the changelog. Use a normal
  hyphen "-", a comma, or rewrite the sentence instead.

## Commit messages

- Write commit messages so a non-technical person can understand what changed
  and why it matters to them. This app ships to players, and the changelog is
  generated straight from commit subjects, so they double as release notes.
- Lead with the player-facing benefit in plain language. Avoid jargon, internal
  module names, and implementation detail in the subject line.
- Still keep the Conventional Commit prefix (feat:, fix:, etc.) so versioning
  and the changelog keep working, but phrase the rest for a human.
  - Good: `feat: show the real Nexus page for each mod`
  - Good: `fix: stop the installer asking the same question twice`
  - Avoid: `feat: wire NexusValidation into AccountSection useEffect`
