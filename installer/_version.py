"""Single source of truth for the application version.

This value is bumped automatically by the release pipeline (git-cliff computes
the next semver from Conventional Commit messages on each valid change). Do not
edit by hand — see .github/workflows/release.yml and cliff.toml.
"""

__version__ = "0.1.0"
