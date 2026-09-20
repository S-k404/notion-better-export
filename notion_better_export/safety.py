"""Failsafes: atomic writes, output-directory checks, and a single-run lock.

Nothing here talks to Notion. It exists so an interrupted, mistargeted, or
concurrent run cannot damage the user's files.
"""

import contextlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import IO, Iterator, List, Optional

MARKER_NAME = ".nbe-export"
LOCK_NAME = ".nbe.lock"
MANIFEST_NAME = "notion_export_manifest.json"
MIN_FREE_MB = 200
STALE_LOCK_SECONDS = 6 * 3600  # only used on Windows, where a pid probe is unsafe

# Never write here (or anywhere beneath), even with --force.
_SYSTEM_TREES = (
    "/etc", "/usr", "/bin", "/sbin", "/System", "/Library", "/boot", "/dev", "/proc", "/sys",
    "/private/etc",  # macOS: /etc is a symlink to here
)
# Never write to exactly these (their children are fine).
_EXACT_PROTECTED = (
    "/", "/Users", "/home", "/var", "/private", "/private/var", "/opt", "/Applications", "/Volumes", "/mnt",
)


class ExportAborted(BaseException):
    """Stop the whole export now (revoked token, API meltdown).

    Deliberately a BaseException so the many per-page `except Exception`
    handlers, which record an error and carry on, cannot swallow it.
    """

    def __init__(self, reason: str, status: Optional[int] = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status


class UnsafeOutputDir(Exception):
    """The chosen output location must not be written to."""


# --------------------------------------------------------------------------- #
# Atomic writes
# --------------------------------------------------------------------------- #

def _default_file_mode() -> int:
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


@contextlib.contextmanager
def atomic_open(
    path: Path, mode: str = "w", encoding: str = "utf-8", newline: Optional[str] = None
) -> Iterator[IO]:
    """Open a temp file beside `path` and move it into place only on success.

    If the block raises (or the run is interrupted) the original file is left
    untouched and the temp file is removed, so users never see a half-written note.
    """
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    binary = "b" in mode
    try:
        with os.fdopen(
            fd,
            mode,
            encoding=None if binary else encoding,
            newline=None if binary else newline,
        ) as fh:
            yield fh
        with contextlib.suppress(OSError):
            os.chmod(tmp, _default_file_mode())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_text(
    path: Path, text: str, encoding: str = "utf-8", newline: Optional[str] = None
) -> None:
    with atomic_open(path, "w", encoding=encoding, newline=newline) as fh:
        fh.write(text)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    with atomic_open(path, "wb") as fh:
        fh.write(data)


# --------------------------------------------------------------------------- #
# Output directory checks
# --------------------------------------------------------------------------- #

def assert_safe_output_dir(out_dir: Path) -> None:
    """Hard refusals: raise UnsafeOutputDir for places we must never write into."""
    target = Path(out_dir).expanduser().resolve()

    if target.exists() and not target.is_dir():
        raise UnsafeOutputDir(f"{target} is a file, not a folder.")

    home = Path.home().resolve()
    if str(target) in _EXACT_PROTECTED or target == home or target == home.parent:
        raise UnsafeOutputDir(
            f"Refusing to export directly into {target}. "
            "Pick a dedicated folder, e.g. <your vault>/Notion Better Export."
        )
    if target.anchor and str(target) == target.anchor:
        raise UnsafeOutputDir("Refusing to export into the filesystem root.")
    # Check the path as typed too: resolving a symlink (e.g. /etc -> /private/etc) can hide it.
    typed = Path(out_dir).expanduser().absolute()
    for candidate in (typed, target):
        for tree in _SYSTEM_TREES:
            if candidate == Path(tree) or Path(tree) in candidate.parents:
                raise UnsafeOutputDir(f"Refusing to write inside system folder {tree}.")
    if (target / "pyproject.toml").exists() and (target / "notion_better_export").is_dir():
        raise UnsafeOutputDir(
            "That is this tool's own source folder; exporting here would mix notes into the code."
        )


def _nearest_existing(path: Path) -> Path:
    for candidate in [path, *path.parents]:
        if candidate.exists():
            return candidate
    return Path(".")


def output_dir_warnings(out_dir: Path, min_free_mb: int = MIN_FREE_MB) -> List[str]:
    """Soft problems the user may override (--force or an interactive yes)."""
    target = Path(out_dir).expanduser().resolve()
    warnings: List[str] = []

    if target.is_dir():
        ours = (target / MARKER_NAME).exists() or (target / MANIFEST_NAME).exists()
        existing = [
            p.name for p in target.iterdir() if p.name not in {".DS_Store", ".gitkeep", LOCK_NAME}
        ]
        if existing and not ours:
            hint = " It looks like an Obsidian vault root." if ".obsidian" in existing else ""
            warnings.append(
                f"{target} already has {len(existing)} item(s) that Notion Better Export did not "
                f"create and files with the same name will be overwritten.{hint}"
            )

    try:
        free_mb = shutil.disk_usage(_nearest_existing(target)).free // (1024 * 1024)
        if free_mb < min_free_mb:
            warnings.append(f"Only {free_mb} MB free on the destination disk (recommended: {min_free_mb}+ MB).")
    except OSError:
        pass
    return warnings


# --------------------------------------------------------------------------- #
# Single-run lock
# --------------------------------------------------------------------------- #

def _pid_alive(pid: int, lock_path: Path) -> bool:
    if pid == os.getpid():
        return False
    if os.name == "nt":
        # os.kill(pid, 0) would *terminate* the process on Windows; use lock age instead.
        try:
            return time.time() - lock_path.stat().st_mtime < STALE_LOCK_SECONDS
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def run_lock(out_dir: Path) -> Iterator[None]:
    """Refuse to start if another live export is writing to the same folder."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / LOCK_NAME

    for _ in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                pid = int(json.loads(lock_path.read_text(encoding="utf-8")).get("pid", 0))
            except (OSError, ValueError, AttributeError):
                pid = 0
            if pid and _pid_alive(pid, lock_path):
                raise UnsafeOutputDir(
                    f"Another export (pid {pid}) is already writing to {out_dir}. "
                    "Wait for it to finish, or delete .nbe.lock if it crashed."
                )
            with contextlib.suppress(OSError):
                lock_path.unlink()  # stale lock from a crashed run
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "started": time.time()}, fh)
        break
    else:
        raise UnsafeOutputDir(f"Could not acquire {lock_path}.")

    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock_path.unlink()
