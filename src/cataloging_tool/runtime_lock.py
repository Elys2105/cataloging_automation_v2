from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from threading import Lock
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from cataloging_tool.domain.errors import ProfileInUseError, WorkItemInUseError


_HELD_PATHS: set[Path] = set()
_HELD_PATHS_GUARD = Lock()


def _canonical(value: str | Path) -> str:
    text = str(value)
    try:
        text = str(Path(text).expanduser().resolve(strict=False))
    except Exception:
        pass
    return os.path.normcase(os.path.normpath(text)).casefold()


def _normalize_profile_query(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"\s*([./-])\s*", r"\1", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass(slots=True)
class HeldFileLock:
    path: Path
    handle: BinaryIO

    def release(self) -> None:
        if self.handle.closed:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            with _HELD_PATHS_GUARD:
                _HELD_PATHS.discard(self.path)

    def __enter__(self) -> "HeldFileLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class SlotLockService:
    """Cross-process locks shared by both slots on the same Windows user profile."""

    def __init__(self, lock_dir: Path, slot_id: int) -> None:
        self.lock_dir = lock_dir
        self.slot_id = slot_id

    def acquire_browser_profile(self, profile_dir: Path) -> HeldFileLock:
        key = f"browser-profile::{_canonical(profile_dir)}"
        try:
            return self._acquire("profile", key, resource=str(profile_dir))
        except BlockingIOError as exc:
            owner = self._read_owner("profile", key)
            owner_slot = owner.get("slot") if owner else None
            suffix = f" ở Slot {owner_slot}" if owner_slot else " ở tiến trình khác"
            raise ProfileInUseError(
                f"Chrome profile đang được sử dụng{suffix}: {profile_dir}",
                step="profile_lock",
                retryable=False,
            ) from exc

    def acquire_job(self, profile_query: str) -> HeldFileLock:
        normalized = _normalize_profile_query(profile_query)
        key = f"job-profile::{normalized}"
        try:
            return self._acquire("job", key, resource=profile_query)
        except BlockingIOError as exc:
            owner = self._read_owner("job", key)
            owner_slot = owner.get("slot") if owner else None
            suffix = f" ở Slot {owner_slot}" if owner_slot else " ở tiến trình khác"
            raise WorkItemInUseError(
                f"Hồ sơ đang được xử lý{suffix}: {profile_query}",
                step="job_lock",
                retryable=False,
            ) from exc

    def _lock_path(self, prefix: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return self.lock_dir / f"{prefix}-{digest}.lock"

    def _acquire(self, prefix: str, key: str, *, resource: str) -> HeldFileLock:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        path = self._lock_path(prefix, key)
        with _HELD_PATHS_GUARD:
            if path in _HELD_PATHS:
                raise BlockingIOError(f"Lock already held in this process: {path}")
        handle = path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise BlockingIOError(str(exc)) from exc

            payload = json.dumps(
                {
                    "slot": self.slot_id,
                    "pid": os.getpid(),
                    "resource": resource,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            handle.seek(1)
            handle.write(payload)
            handle.truncate()
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                # Some filesystems may not support fsync; flush is still enough
                # for correctness, while fsync improves immediate owner visibility.
                pass
            with _HELD_PATHS_GUARD:
                _HELD_PATHS.add(path)
            return HeldFileLock(path=path, handle=handle)
        except Exception:
            handle.close()
            raise

    def _read_owner(self, prefix: str, key: str) -> dict[str, object]:
        path = self._lock_path(prefix, key)
        try:
            # Byte 0 is the cross-process lock byte. On Windows an active
            # msvcrt byte-range lock can make a second handle fail if it tries
            # to read that byte. Read owner metadata starting at byte 1 so the
            # diagnostic path never touches the locked range.
            with path.open("rb") as handle:
                handle.seek(1)
                data = handle.read()
            if not data:
                return {}
            value = json.loads(data.decode("utf-8", errors="replace"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
