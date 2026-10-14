import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings


class Storage(ABC):
    @abstractmethod
    def put(self, source_path: Path | str, dest_relative_path: str) -> str:
        """Stores a file at dest_relative_path and returns the relative storage path."""
        pass

    @abstractmethod
    def get_path(self, dest_relative_path: str) -> Path:
        """Returns the full Path to the stored file."""
        pass

    @abstractmethod
    def exists(self, dest_relative_path: str) -> bool:
        """Checks if a stored file exists."""
        pass


class LocalStorage(Storage):
    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir or settings.STORAGE_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def put(self, source_path: Path | str, dest_relative_path: str) -> str:
        source = Path(source_path).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        dest = (self.base_dir / dest_relative_path).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return dest_relative_path.replace("\\", "/")

    def get_path(self, dest_relative_path: str) -> Path:
        return (self.base_dir / dest_relative_path).resolve()

    def exists(self, dest_relative_path: str) -> bool:
        return (self.base_dir / dest_relative_path).exists()


storage: Storage = LocalStorage()
