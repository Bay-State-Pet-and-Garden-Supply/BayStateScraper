"""
Scraper caching and incremental update system.

Provides intelligent caching for scraper results with TTL-based invalidation,
incremental scraping support, and cache statistics.
"""

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CacheStatus(Enum):
    """Status of a cache entry."""

    VALID = "valid"
    EXPIRED = "expired"
    STALE = "stale"  # Beyond soft TTL but before hard TTL
    MISSING = "missing"


@dataclass
class CacheEntry:
    """Represents a cached scraper result."""

    key: str
    value: dict[str, Any]
    created_at: float
    updated_at: float
    expires_at: float
    access_count: int = 0
    last_accessed: float = 0.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if entry is expired."""
        return time.time() > self.expires_at

    def is_stale(self, stale_threshold_seconds: float = 3600) -> bool:
        """Check if entry is stale (old but not expired)."""
        age = time.time() - self.created_at
        return age > stale_threshold_seconds and not self.is_expired()

    def get_status(self, stale_threshold: float = 3600) -> CacheStatus:
        """Get the current status of the entry."""
        if self.is_expired():
            return CacheStatus.EXPIRED
        if self.is_stale(stale_threshold):
            return CacheStatus.STALE
        return CacheStatus.VALID

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheEntry":
        """Create from dictionary."""
        return cls(
            key=data["key"],
            value=data["value"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            expires_at=data["expires_at"],
            access_count=data.get("access_count", 0),
            last_accessed=data.get("last_accessed", 0.0),
            source=data.get("source", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CacheStats:
    """Statistics for cache operations."""

    hits: int = 0
    misses: int = 0
    expired_hits: int = 0
    stale_hits: int = 0
    evictions: int = 0
    size: int = 0
    total_entries: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "expired_hits": self.expired_hits,
            "stale_hits": self.stale_hits,
            "evictions": self.evictions,
            "size": self.size,
            "total_entries": self.total_entries,
            "hit_rate": round(self.hit_rate, 4),
        }


class ScraperCache:
    """
    Intelligent cache for scraper results.

    Features:
    - TTL-based expiration
    - LRU eviction when size limit reached
    - Persistent storage
    - Thread-safe operations
    - Cache statistics
    """

    DEFAULT_TTL_SECONDS = 86400  # 24 hours
    DEFAULT_STALE_THRESHOLD = 3600  # 1 hour
    DEFAULT_MAX_SIZE = 10000

    def __init__(
        self,
        cache_dir: str | Path,
        cache_id: str = "scraper_cache",
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        stale_threshold: float = DEFAULT_STALE_THRESHOLD,
        max_size: int = DEFAULT_MAX_SIZE,
        persist: bool = True,
    ) -> None:
        """
        Initialize the scraper cache.

        Args:
            cache_dir: Directory for cache storage
            cache_id: Unique identifier for this cache
            ttl_seconds: Time-to-live for cache entries
            stale_threshold: Time after which entries are considered stale
            max_size: Maximum number of entries
            persist: Whether to persist cache to disk
        """
        self.cache_dir = Path(cache_dir)
        self.cache_id = cache_id
        self.ttl_seconds = ttl_seconds
        self.stale_threshold = stale_threshold
        self.max_size = max_size
        self.persist = persist

        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = CacheStats()
        self._lock = threading.RLock()

        self._cache_file = self.cache_dir / f"{cache_id}.json"

        if persist:
            self._load_cache()

    def _generate_key(self, scraper_name: str, sku: str) -> str:
        """Generate a cache key from scraper name and SKU."""
        raw_key = f"{scraper_name}:{sku}"
        return hashlib.md5(raw_key.encode()).hexdigest()

    def get(
        self,
        scraper_name: str,
        sku: str,
        allow_stale: bool = False,
        allow_expired: bool = False,
    ) -> tuple[dict[str, Any] | None, CacheStatus]:
        """
        Get a cached result.

        Args:
            scraper_name: Name of the scraper
            sku: SKU to look up
            allow_stale: Whether to return stale entries
            allow_expired: Whether to return expired entries

        Returns:
            Tuple of (cached value or None, cache status)
        """
        key = self._generate_key(scraper_name, sku)

        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats.misses += 1
                return None, CacheStatus.MISSING

            status = entry.get_status(self.stale_threshold)

            if status == CacheStatus.EXPIRED:
                self._stats.expired_hits += 1
                if not allow_expired:
                    self._stats.misses += 1
                    return None, status
            elif status == CacheStatus.STALE:
                self._stats.stale_hits += 1
                if not allow_stale:
                    self._stats.misses += 1
                    return None, status

            # Update access tracking
            entry.access_count += 1
            entry.last_accessed = time.time()

            # Move to end for LRU
            self._cache.move_to_end(key)

            self._stats.hits += 1
            return entry.value, status

    def set(
        self,
        scraper_name: str,
        sku: str,
        value: dict[str, Any],
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CacheEntry:
        """
        Cache a scraper result.

        Args:
            scraper_name: Name of the scraper
            sku: SKU being cached
            value: Result to cache
            ttl_seconds: Custom TTL (uses default if None)
            metadata: Additional metadata to store

        Returns:
            The created cache entry
        """
        key = self._generate_key(scraper_name, sku)
        ttl = ttl_seconds or self.ttl_seconds
        now = time.time()

        entry = CacheEntry(
            key=key,
            value=value,
            created_at=now,
            updated_at=now,
            expires_at=now + ttl,
            access_count=0,
            last_accessed=now,
            source=scraper_name,
            metadata=metadata or {},
        )

        with self._lock:
            # Check if we need to evict
            while len(self._cache) >= self.max_size:
                self._evict_oldest()

            self._cache[key] = entry
            self._cache.move_to_end(key)
            self._stats.total_entries = len(self._cache)

            if self.persist:
                self._save_cache()

        return entry

    def delete(self, scraper_name: str, sku: str) -> bool:
        """
        Delete a cached entry.

        Args:
            scraper_name: Name of the scraper
            sku: SKU to delete

        Returns:
            True if entry was deleted, False if not found
        """
        key = self._generate_key(scraper_name, sku)

        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats.total_entries = len(self._cache)

                if self.persist:
                    self._save_cache()

                return True
            return False

    def invalidate(
        self,
        scraper_name: str | None = None,
        sku: str | None = None,
        older_than: float | None = None,
    ) -> int:
        """
        Invalidate cache entries matching criteria.

        Args:
            scraper_name: Invalidate entries for this scraper
            sku: Invalidate entries for this SKU
            older_than: Invalidate entries older than this timestamp

        Returns:
            Number of entries invalidated
        """
        with self._lock:
            keys_to_delete = []

            for key, entry in self._cache.items():
                should_delete = False

                if scraper_name and entry.source == scraper_name:
                    should_delete = True
                if sku and sku in entry.key:
                    should_delete = True
                if older_than and entry.created_at < older_than:
                    should_delete = True

                if should_delete:
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                del self._cache[key]
                self._stats.evictions += 1

            self._stats.total_entries = len(self._cache)

            if self.persist and keys_to_delete:
                self._save_cache()

            return len(keys_to_delete)

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            keys_to_delete = [key for key, entry in self._cache.items() if entry.is_expired()]

            for key in keys_to_delete:
                del self._cache[key]
                self._stats.evictions += 1

            self._stats.total_entries = len(self._cache)

            if self.persist and keys_to_delete:
                self._save_cache()

            return len(keys_to_delete)

    def _evict_oldest(self) -> None:
        """Evict the oldest (LRU) entry."""
        if self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._stats.evictions += 1

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            self._stats.size = len(self._cache)
            self._stats.total_entries = len(self._cache)
            return self._stats

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats = CacheStats()

            if self.persist and self._cache_file.exists():
                self._cache_file.unlink()

            return count

    def _load_cache(self) -> None:
        """Load cache from disk."""
        if not self._cache_file.exists():
            return

        try:
            with open(self._cache_file, encoding="utf-8") as f:
                data = json.load(f)

            for entry_data in data.get("entries", []):
                entry = CacheEntry.from_dict(entry_data)
                if not entry.is_expired():
                    self._cache[entry.key] = entry

            self._stats.total_entries = len(self._cache)
            logger.info(f"Loaded {len(self._cache)} cache entries from {self._cache_file}")

        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load cache: {e}")

    def _save_cache(self) -> None:
        """Save cache to disk."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "cache_id": self.cache_id,
            "saved_at": time.time(),
            "entries": [entry.to_dict() for entry in self._cache.values()],
        }

        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError as e:
            logger.warning(f"Failed to save cache: {e}")

    def get_cached_skus(self, scraper_name: str | None = None) -> list[str]:
        """
        Get list of SKUs in cache.

        Args:
            scraper_name: Filter by scraper name

        Returns:
            List of cached SKUs
        """
        with self._lock:
            skus = []
            for entry in self._cache.values():
                if scraper_name is None or entry.source == scraper_name:
                    # Extract SKU from metadata if available
                    sku = entry.metadata.get("sku", entry.key)
                    skus.append(sku)
            return skus


class IncrementalScraper:
    """
    Manages incremental scraping with intelligent cache checking.

    Determines which SKUs need to be scraped vs which can use cached data.
    """

    def __init__(
        self,
        cache: ScraperCache,
        max_age_seconds: float = 86400,  # 24 hours
        force_refresh_ratio: float = 0.1,  # 10% random refresh
    ) -> None:
        """
        Initialize the incremental scraper.

        Args:
            cache: ScraperCache instance
            max_age_seconds: Maximum age before requiring refresh
            force_refresh_ratio: Ratio of entries to force refresh
        """
        self.cache = cache
        self.max_age_seconds = max_age_seconds
        self.force_refresh_ratio = force_refresh_ratio

    def partition_skus(
        self,
        scraper_name: str,
        skus: list[str],
    ) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        """
        Partition SKUs into those needing scraping vs cached.

        Args:
            scraper_name: Name of the scraper
            skus: List of SKUs to check

        Returns:
            Tuple of (skus_to_scrape, skus_from_cache, cached_results)
        """
        import random

        skus_to_scrape = []
        skus_from_cache = []
        cached_results = []

        for sku in skus:
            # Check if should force refresh (random sampling)
            force_refresh = random.random() < self.force_refresh_ratio

            if force_refresh:
                skus_to_scrape.append(sku)
                continue

            # Check cache
            cached, status = self.cache.get(
                scraper_name,
                sku,
                allow_stale=True,
                allow_expired=False,
            )

            if cached and status == CacheStatus.VALID:
                skus_from_cache.append(sku)
                cached_results.append(cached)
            else:
                skus_to_scrape.append(sku)

        logger.info(
            f"Incremental partition: {len(skus_to_scrape)} to scrape, "
            f"{len(skus_from_cache)} from cache"
        )

        return skus_to_scrape, skus_from_cache, cached_results

    def scrape_incremental(
        self,
        scraper_name: str,
        skus: list[str],
        scrape_func,
    ) -> Iterator[dict[str, Any]]:
        """
        Perform incremental scraping.

        Args:
            scraper_name: Name of the scraper
            skus: SKUs to process
            scrape_func: Function to scrape a single SKU

        Yields:
            Results (from cache or fresh scrape)
        """
        to_scrape, _from_cache, cached_results = self.partition_skus(scraper_name, skus)

        # Yield cached results first
        for result in cached_results:
            yield result

        # Scrape remaining SKUs
        for sku in to_scrape:
            try:
                result = scrape_func(sku)
                if result:
                    # Cache the new result
                    self.cache.set(
                        scraper_name,
                        sku,
                        result,
                        metadata={"sku": sku},
                    )
                    yield result
            except Exception as e:
                logger.error(f"Error scraping {sku}: {e}")

    def get_freshness_report(
        self,
        scraper_name: str,
        skus: list[str],
    ) -> dict[str, Any]:
        """
        Generate a report on cache freshness for given SKUs.

        Args:
            scraper_name: Name of the scraper
            skus: SKUs to check

        Returns:
            Report with freshness statistics
        """
        valid_count = 0
        stale_count = 0
        expired_count = 0
        missing_count = 0

        for sku in skus:
            _, status = self.cache.get(
                scraper_name,
                sku,
                allow_stale=True,
                allow_expired=True,
            )

            if status == CacheStatus.VALID:
                valid_count += 1
            elif status == CacheStatus.STALE:
                stale_count += 1
            elif status == CacheStatus.EXPIRED:
                expired_count += 1
            else:
                missing_count += 1

        return {
            "total_skus": len(skus),
            "valid": valid_count,
            "stale": stale_count,
            "expired": expired_count,
            "missing": missing_count,
            "cache_coverage": (valid_count + stale_count) / len(skus) if skus else 0,
            "freshness_ratio": valid_count / len(skus) if skus else 0,
        }


class CacheWarmer:
    """
    Pre-warms cache with frequently accessed data.
    """

    def __init__(self, cache: ScraperCache) -> None:
        """
        Initialize the cache warmer.

        Args:
            cache: ScraperCache instance
        """
        self.cache = cache

    def warm_from_history(
        self,
        scraper_name: str,
        historical_results: list[dict[str, Any]],
        sku_field: str = "sku",
    ) -> int:
        """
        Warm cache from historical results.

        Args:
            scraper_name: Name of the scraper
            historical_results: List of historical results
            sku_field: Field name containing SKU

        Returns:
            Number of entries added to cache
        """
        count = 0
        for result in historical_results:
            sku = result.get(sku_field)
            if sku:
                self.cache.set(
                    scraper_name,
                    sku,
                    result,
                    metadata={"sku": sku, "source": "history_warm"},
                )
                count += 1

        logger.info(f"Warmed cache with {count} historical results")
        return count

    def warm_from_file(
        self,
        file_path: str | Path,
        scraper_name: str,
        sku_field: str = "sku",
    ) -> int:
        """
        Warm cache from a JSON file.

        Args:
            file_path: Path to JSON file
            scraper_name: Name of the scraper
            sku_field: Field name containing SKU

        Returns:
            Number of entries added
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                results = data
            elif isinstance(data, dict) and "results" in data:
                results = data["results"]
            else:
                results = []

            return self.warm_from_history(scraper_name, results, sku_field)

        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to warm cache from file: {e}")
            return 0


def create_scraper_cache(
    cache_dir: str | Path | None = None,
    cache_id: str = "default",
    ttl_hours: float = 24.0,
) -> ScraperCache:
    """
    Factory function to create a scraper cache.

    Args:
        cache_dir: Directory for cache storage (defaults to data/cache)
        cache_id: Unique identifier for the cache
        ttl_hours: Time-to-live in hours

    Returns:
        Configured ScraperCache instance
    """
    if cache_dir is None:
        from scraper_backend.core.settings_manager import PROJECT_ROOT

        cache_dir = Path(PROJECT_ROOT) / "data" / "cache"

    return ScraperCache(
        cache_dir=cache_dir,
        cache_id=cache_id,
        ttl_seconds=ttl_hours * 3600,
    )
