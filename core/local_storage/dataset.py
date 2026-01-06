"""
Local dataset implementation for storing data items as JSON files.
"""
from __future__ import annotations


import json
from pathlib import Path
from typing import Any


class LocalDataset:
    """
    Local file-based dataset storage.

    Stores data items as individual JSON files in a directory.
    """

    def __init__(self, dataset_id: str, base_dir: str):
        """
        Initialize the dataset.

        Args:
            dataset_id: Unique identifier for the dataset
            base_dir: Base directory for storage
        """
        self.dataset_id = dataset_id
        self.base_dir = Path(base_dir)
        self.storage_dir = self.base_dir / dataset_id
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._cache: list[dict[str, Any]] = []
        self._load_cache()

    def _load_cache(self):
        """Load existing data from storage directory into cache."""
        self._cache = []
        for json_file in sorted(self.storage_dir.glob("*.json")):
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self._cache.append(data)
            except (OSError, json.JSONDecodeError):
                continue

    def push_data(self, data: dict[str, Any] | list[dict[str, Any]]):
        """
        Push data to the dataset.

        Args:
            data: Single data item or list of data items
        """
        if not isinstance(data, list):
            data = [data]

        for item in data:
            # Generate unique filename
            import uuid

            filename = f"{uuid.uuid4()}.json"
            filepath = self.storage_dir / filename

            # Write to file
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=2)

            # Add to cache
            self._cache.append(item)

    def get_data(self, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        """
        Get data from the dataset.

        Args:
            limit: Maximum number of items to return
            offset: Number of items to skip

        Returns:
            List of data items
        """
        data = self._cache[offset:]
        if limit is not None:
            data = data[:limit]
        return data

    def get_info(self) -> dict[str, Any]:
        """
        Get dataset information.

        Returns:
            Dictionary with dataset info
        """
        return {
            "id": self.dataset_id,
            "itemCount": len(self._cache),
            "storageDir": str(self.storage_dir),
        }

    def drop(self):
        """Drop the dataset and delete all data."""
        # Remove all files
        for json_file in self.storage_dir.glob("*.json"):
            json_file.unlink()

        # Clear cache
        self._cache = []

    def __len__(self) -> int:
        """Return the number of items in the dataset."""
        return len(self._cache)
