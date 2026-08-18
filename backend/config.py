"""Runtime configuration for the BIM Cloud Pipeline.

All knobs are environment-variable driven with safe defaults.

``PUBLIC_DEMO_MODE`` hardens a deployment that is reachable by arbitrary
visitors on the internet **without disabling the real POC experience**:

  - uploads remain ENABLED (so visitors get a real POC), but are bounded by
    file-size, concurrency, and rate limits
  - job history is scoped to the requesting visitor (per-visitor cookie), so
    unrelated visitors cannot see each other's jobs, downloads, or comparisons
  - completed jobs/outputs are automatically expired (TTL cleanup)
  - the dashboard shows a visible "never upload confidential models" warning

To fully disable uploads (samples-only mode), set ``DISABLE_UPLOADS=1``.

Public demo mode is **on by default on hosted platforms** (Render, Hugging Face
Spaces, etc.) and **off by default locally**. Override explicitly with
``PUBLIC_DEMO_MODE=0`` / ``PUBLIC_DEMO_MODE=1``.
"""
from __future__ import annotations

import os


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:  # empty/whitespace env vars are treated as unset
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# -- public safety --------------------------------------------------------- #

def _is_hosted_platform() -> bool:
    """Detect public/hosted runtimes (Render, Hugging Face Spaces, etc.).

    On these platforms the app is reachable by arbitrary visitors, so public
    demo mode should be on unless explicitly disabled.
    """
    markers = (
        "RENDER", "SPACE_ID", "HF_SPACE", "REPL_ID",
        "CODESPACES", "GITPOD_WORKSPACE_ID", "FLY_APP_NAME", "RAILWAY_ENVIRONMENT",
    )
    return any(os.environ.get(k) for k in markers)


# When True, enable public-safety features (per-visitor history scoping +
# confidential-data warning). Uploads stay ENABLED for a real POC experience.
# Safe-by-default on hosted/public platforms; off locally unless enabled.
PUBLIC_DEMO_MODE = _bool("PUBLIC_DEMO_MODE", _is_hosted_platform())

# When True, fully disable arbitrary uploads (samples-only). Off by default so
# the public deployment remains a working POC.
DISABLE_UPLOADS = _bool("DISABLE_UPLOADS", False)

# When True, allow live `.rvt` uploads to use the Autodesk APS adapter.
# Off by default: APS Model Derivative has limited quota and must not be
# consumed by anonymous public visitors. BYOC for local/self-hosted use.
ALLOW_RVT_UPLOAD = _bool("ALLOW_RVT_UPLOAD", False)

# Hard limits (always enforced — they gate exposing public uploads safely).
# Concurrency is 1 for the POC to keep peak memory bounded on small hosts.
MAX_FILE_SIZE_MB = _int("MAX_FILE_SIZE_MB", 20)
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_CONCURRENT_JOBS = _int("MAX_CONCURRENT_JOBS", 1)
MAX_JOBS_PER_MINUTE = _int("MAX_JOBS_PER_MINUTE", 10)

# -- lifecycle / cleanup --------------------------------------------------- #

# Completed (and failed) jobs and their outputs are removed after this many
# seconds. Default 1 hour. 0 disables TTL cleanup.
JOB_TTL_SECONDS = _int("JOB_TTL_SECONDS", 3600)
CLEANUP_INTERVAL_SECONDS = _int("CLEANUP_INTERVAL_SECONDS", 300)
