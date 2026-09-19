"""Finite ordinary-failure undo, not a crash-atomic multi-file data journal."""
from __future__ import annotations

import filecmp
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path


class InputUndo:
    def __init__(self, project, *, data: bool = False):
        self.directory = Path(tempfile.mkdtemp(prefix="input-", dir=project.nodes.root))
        paths = {project.dir / "context.json", project.nodes.root / "investigation.json"}
        if data:
            paths.update(project.dir / name for name in
                         ("crystal.hkl", "start.res", "start.ins", "source.cif"))
            from .data_versions import is_protected
            for path in (project.hkl_path, project.start_model_path):
                if (path is not None and Path(path).resolve().is_relative_to(project.dir)
                        and not is_protected(project.dir, path)):
                    paths.add(Path(path).resolve())
        self.paths = sorted(paths)
        self.files = {}
        self.valid = False
        try:
            self.checkpoint()
        except BaseException:
            self.close()
            raise

    def checkpoint(self) -> None:
        """A committed child advances undo, without discarding that child's evidence."""
        self.valid = False
        files = {}
        token = uuid.uuid4().hex
        for index, path in enumerate(self.paths):
            backup = self.directory / f"{token}-{index}" if path.exists() else None
            if backup is not None:
                shutil.copy2(path, backup)
            files[path] = backup
        (self.directory / "manifest.json").write_text(json.dumps({
            "scope": "ordinary failure undo; manual inspection required after hard crash",
            "files": {str(path): backup.name if backup else None
                      for path, backup in files.items()},
        }, indent=2), encoding="utf-8")
        previous = self.files
        self.files = files
        self.valid = True
        for backup in previous.values():
            if backup is not None:
                try:
                    backup.unlink()
                except OSError:
                    pass

    def changed(self) -> bool:
        return any((path.exists() if backup is None else
                    not path.exists() or not filecmp.cmp(path, backup, shallow=False))
                   for path, backup in self.files.items())

    def restore(self) -> None:
        if not self.valid:
            raise OSError("Input undo baseline could not follow a committed child; manual recovery required")
        for path, backup in self.files.items():
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                staged = path.with_name(path.name + ".undo-" + uuid.uuid4().hex)
                try:
                    shutil.copy2(backup, staged)
                    os.replace(staged, path)
                finally:
                    staged.unlink(missing_ok=True)

    def close(self) -> None:
        shutil.rmtree(self.directory)
