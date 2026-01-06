"""
Local key-value store implementation using JSON file storage.
"""
from __future__ import annotations


import json
from pathlib import Path
from typing import Any


class LocalKeyValueStore:
    """
    Local file-based key-value store.

    Stores key-value pairs in a JSON file.
    """

    def __init__(self, store_id: str, base_dir: str):
        """
        Initialize the key-value store.

        Args:
            store_id: Unique identifier for the store
            base_dir: Base directory for storage
        """
        self.store_id = store_id
        self.base_dir = Path(base_dir)
        self.storage_file = self.base_dir / f"{store_id}.json"
        self._data: dict[str, Any] = {}
        self._load_data()

    def _load_data(self):
        """Load existing data from storage file."""
        if self.storage_file.exists():
            try:
                with open(self.storage_file, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (OSError, json.JSONDecodeError):
                self._data = {}
        else:
            self._data = {}

    def _save_data(self):
        """Save data to storage file."""
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def set_value(self, key: str, value: Any):
        """
        Set a value for a key.

        Args:
            key: The key to set
            value: The value to store
        """
        self._data[key] = value
        self._save_data()

    def get_value(self, key: str, default: Any = None) -> Any:
        """
        Get a value for a key.

        Args:
            key: The key to retrieve
            default: Default value if key doesn't exist

        Returns:
            The value or default
        """
        return self._data.get(key, default)

    def delete_value(self, key: str) -> bool:
        """
        Delete a value for a key.

        Args:
            key: The key to delete

        Returns:
            True if key existed and was deleted, False otherwise
        """
        if key in self._data:
            del self._data[key]
            self._save_data()
            return True
        return False

    def list_keys(self) -> list[str]:
        """
        List all keys in the store.

        Returns:
            List of keys
        """
        return list(self._data.keys())

    def get_info(self) -> dict[str, Any]:
        """
        Get store information.

        Returns:
            Dictionary with store info
        """
        return {
            "id": self.store_id,
            "keyCount": len(self._data),
            "storageDir": str(self.storage_file),
        }

    def drop(self):
        """Drop the store and delete all data."""
        if self.storage_file.exists():
            self.storage_file.unlink()
        self._data = {}
