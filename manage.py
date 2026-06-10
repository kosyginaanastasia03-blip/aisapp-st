#!/usr/bin/env python
from __future__ import annotations

import os
import sys
import ctypes.util
from pathlib import Path

from config.env import load_project_env


BASE_DIR = Path(__file__).resolve().parent
VENV_SITE_PACKAGES = BASE_DIR / ".venv" / "Lib" / "site-packages"
load_project_env(BASE_DIR / ".env")


def _add_project_site_packages() -> None:
    if VENV_SITE_PACKAGES.exists():
        site_packages = str(VENV_SITE_PACKAGES)
        if site_packages not in sys.path:
            sys.path.insert(0, site_packages)


def _postgres_bin_candidates() -> list[Path]:
    candidates: list[Path] = []

    env_bin = os.environ.get("POSTGRES_BIN", "").strip()
    if env_bin:
        candidates.append(Path(env_bin))

    env_home = os.environ.get("POSTGRES_HOME", "").strip()
    if env_home:
        candidates.append(Path(env_home) / "bin")

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    postgres_root = program_files / "PostgreSQL"
    if postgres_root.exists():
        for child in sorted(postgres_root.iterdir(), reverse=True):
            candidate = child / "bin"
            if candidate.exists():
                candidates.append(candidate)

    return candidates


def _patch_windows_libpq_lookup() -> None:
    if os.name != "nt":
        return

    libpq_path = None
    for candidate in _postgres_bin_candidates():
        maybe_libpq = candidate / "libpq.dll"
        if maybe_libpq.exists():
            libpq_path = maybe_libpq.resolve()
            try:
                os.add_dll_directory(str(libpq_path.parent))
            except (AttributeError, FileNotFoundError):
                pass
            break

    if not libpq_path:
        return

    original_find_library = ctypes.util.find_library

    def patched_find_library(name: str):
        if name in {"libpq.dll", "libpq", "pq"}:
            return str(libpq_path)
        return original_find_library(name)

    ctypes.util.find_library = patched_find_library


_add_project_site_packages()
_patch_windows_libpq_lookup()


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()