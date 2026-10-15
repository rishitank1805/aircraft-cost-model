"""Download the OurAirports ``airports.csv`` file and preserve it unmodified.

Each successful download is stored as a versioned snapshot::

    data/raw/airports/airports_<YYYYMMDDTHHMMSSZ>_<sha256[:12]>.csv
    data/raw/airports/airports_<YYYYMMDDTHHMMSSZ>_<sha256[:12]>.meta.json

The body is streamed to a temporary ``.part`` file and renamed only after the
transfer completed and the checksum was computed, so a failed download never
leaves a file that looks complete. If the newest existing snapshot has the same
checksum, the duplicate is discarded and the existing snapshot is reused.

Nothing here runs on import; call :func:`download_airports`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 256
_SNAPSHOT_GLOB = "airports_*.csv"


class DownloadError(RuntimeError):
    """Raised when a dataset could not be downloaded completely."""


@dataclass(frozen=True)
class RawSnapshot:
    """Metadata describing one preserved raw download."""

    path: Path
    source_url: str
    final_url: str
    retrieved_at: datetime
    sha256: str
    size_bytes: int
    http_status: int
    etag: str | None = None
    last_modified: str | None = None
    reused_existing: bool = False

    @property
    def meta_path(self) -> Path:
        """Location of the JSON sidecar describing this snapshot."""
        return self.path.with_suffix(".meta.json")

    def to_json_dict(self) -> dict[str, object]:
        """Serializable representation for the sidecar file."""
        data = asdict(self)
        data["path"] = self.path.name
        data["retrieved_at"] = self.retrieved_at.isoformat()
        data.pop("reused_existing")
        return data


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_snapshot_metadata(csv_path: Path) -> RawSnapshot:
    """Load the sidecar metadata for a raw snapshot CSV."""
    meta = json.loads(csv_path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    return RawSnapshot(
        path=csv_path,
        source_url=meta["source_url"],
        final_url=meta["final_url"],
        retrieved_at=datetime.fromisoformat(meta["retrieved_at"]),
        sha256=meta["sha256"],
        size_bytes=int(meta["size_bytes"]),
        http_status=int(meta["http_status"]),
        etag=meta.get("etag"),
        last_modified=meta.get("last_modified"),
        reused_existing=True,
    )


def latest_snapshot(raw_dir: Path) -> RawSnapshot | None:
    """Return the most recent snapshot (by timestamped filename) with metadata, if any."""
    candidates = sorted(
        p for p in raw_dir.glob(_SNAPSHOT_GLOB) if p.with_suffix(".meta.json").is_file()
    )
    return read_snapshot_metadata(candidates[-1]) if candidates else None


def download_airports(
    url: str,
    raw_dir: Path,
    timeout: tuple[float, float] = (10.0, 120.0),
    session: requests.Session | None = None,
) -> RawSnapshot:
    """Download the airport CSV into ``raw_dir`` as an immutable snapshot.

    Args:
        url: Dataset URL (redirects are followed and the final URL recorded).
        raw_dir: Directory for raw snapshots.
        timeout: ``(connect, read)`` timeouts in seconds.
        session: Optional :class:`requests.Session` (useful for tests).

    Returns:
        Metadata for the stored (or reused, if identical) snapshot.

    Raises:
        DownloadError: On network errors, non-200 responses, empty or truncated bodies.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    http = session or requests.Session()
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    tmp_path = raw_dir / f".airports_{stamp}.csv.part"

    logger.info("download_started", extra={"url": url})
    digest = hashlib.sha256()
    size = 0
    try:
        with http.get(url, stream=True, timeout=timeout, allow_redirects=True) as response:
            if response.status_code != 200:
                raise DownloadError(f"HTTP {response.status_code} while downloading {url}")
            expected = response.headers.get("Content-Length")
            with tmp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            encoding = response.headers.get("Content-Encoding")
            if expected is not None and not encoding and int(expected) != size:
                raise DownloadError(
                    f"Truncated download from {url}: expected {expected} bytes, got {size}"
                )
            if size == 0:
                raise DownloadError(f"Empty response body from {url}")
            final_url = response.url or url
            status = response.status_code
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
    except requests.RequestException as exc:
        tmp_path.unlink(missing_ok=True)
        logger.error("download_failed", extra={"url": url, "error": str(exc)})
        raise DownloadError(f"Network error while downloading {url}: {exc}") from exc
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        logger.error("download_failed", extra={"url": url})
        raise

    sha256 = digest.hexdigest()

    previous = latest_snapshot(raw_dir)
    if previous is not None and previous.sha256 == sha256:
        tmp_path.unlink(missing_ok=True)
        logger.info(
            "download_identical_to_existing_snapshot",
            extra={"url": url, "sha256": sha256, "existing": previous.path.name},
        )
        return previous

    final_path = raw_dir / f"airports_{stamp}_{sha256[:12]}.csv"
    os.replace(tmp_path, final_path)
    snapshot = RawSnapshot(
        path=final_path,
        source_url=url,
        final_url=final_url,
        retrieved_at=retrieved_at,
        sha256=sha256,
        size_bytes=size,
        http_status=status,
        etag=etag,
        last_modified=last_modified,
    )
    snapshot.meta_path.write_text(json.dumps(snapshot.to_json_dict(), indent=2), encoding="utf-8")
    logger.info(
        "download_complete",
        extra={
            "url": url,
            "final_url": final_url,
            "size_bytes": size,
            "sha256": sha256,
            "retrieved_at": retrieved_at.isoformat(),
            "path": final_path.name,
        },
    )
    return snapshot
