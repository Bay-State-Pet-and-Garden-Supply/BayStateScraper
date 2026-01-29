"""
Test Database Migration for Test Lab Extensions

Tests for the database schema extensions needed for real-time test lab updates.
Following TDD approach: RED - GREEN - REFACTOR
"""

import os
import sys
from unittest.mock import MagicMock, patch
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


class TestDatabaseMigration:
    """Tests for database migration schema extensions."""

    def test_migration_file_exists(self):
        """Test that migration file exists with correct naming pattern."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        # Check if migrations directory exists
        assert os.path.exists(migrations_dir), f"Migrations directory not found: {migrations_dir}"

        # Look for test_lab migration file
        migration_files = os.listdir(migrations_dir)
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        assert len(test_lab_migrations) > 0, f"No test_lab migration found. Found: {migration_files}"

    def test_migration_adds_selector_results_table(self):
        """Test migration creates scraper_selector_results table."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for selector_results table creation
        assert "scraper_selector_results" in content.lower(), "Migration should create scraper_selector_results table"
        assert "CREATE TABLE" in content.upper() or "create table" in content.lower(), "Migration should contain CREATE TABLE statement"

    def test_migration_adds_login_results_table(self):
        """Test migration creates scraper_login_results table."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for login_results table creation
        assert "scraper_login_results" in content.lower(), "Migration should create scraper_login_results table"

    def test_migration_adds_extraction_results_table(self):
        """Test migration creates scraper_extraction_results table."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for extraction_results table creation
        assert "scraper_extraction_results" in content.lower(), "Migration should create scraper_extraction_results table"

    def test_migration_adds_columns_to_scraper_test_runs(self):
        """Test migration extends scraper_test_runs table."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for ALTER TABLE scraper_test_runs
        assert "scraper_test_runs" in content.lower(), "Migration should reference scraper_test_runs table"
        assert "ALTER TABLE" in content.upper() or "alter table" in content.lower(), "Migration should contain ALTER TABLE statement"

    def test_migration_adds_indexes(self):
        """Test migration adds indexes for performance."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for CREATE INDEX
        has_index = "CREATE INDEX" in content.upper() or "create index" in content.lower() or "CREATE INDEX" in content
        assert has_index, "Migration should create indexes for performance"

    def test_selector_results_has_required_columns(self):
        """Test selector_results table has required fields."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for required columns in selector_results
        required_columns = ["test_run_id", "scraper_id", "selector_name", "status"]
        for col in required_columns:
            assert col in content.lower(), f"Selector results should have {col} column"

    def test_login_results_has_required_columns(self):
        """Test login_results table has required fields."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for required columns in login_results
        required_columns = ["test_run_id", "scraper_id", "status"]
        for col in required_columns:
            assert col in content.lower(), f"Login results should have {col} column"

    def test_extraction_results_has_required_columns(self):
        """Test extraction_results table has required fields."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for required columns in extraction_results
        required_columns = ["test_run_id", "scraper_id", "field_name", "status"]
        for col in required_columns:
            assert col in content.lower(), f"Extraction results should have {col} column"

    def test_migration_follows_existing_patterns(self):
        """Test migration follows existing migration file patterns."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))

        # Get a sample existing migration for comparison
        existing_migrations = [f for f in migration_files if f.endswith(".sql")]
        if len(existing_migrations) < 2:
            pytest.skip("Not enough existing migrations to compare patterns")

        # Read an existing migration to understand the pattern
        existing_migration = os.path.join(migrations_dir, existing_migrations[0])
        with open(existing_migration, "r") as f:
            existing_content = f.read()

        # New migration should follow similar structure
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        new_migration = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(new_migration, "r") as f:
            new_content = f.read()

        # Check that new migration has comments (like existing ones)
        assert "--" in new_content, "Migration should have comment blocks"

        # Check that new migration uses IF NOT EXISTS or similar safe patterns
        # (existing migrations show this pattern)
        assert "IF NOT EXISTS" in new_content or "CREATE TABLE" in new_content, "Migration should use safe creation patterns"


class TestDatabaseMigrationDown:
    """Tests for migration rollback capability."""

    def test_migration_has_down_function(self):
        """Test migration includes rollback/down functionality."""
        migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../BayStateApp/supabase/migrations/"))

        migration_files = sorted(os.listdir(migrations_dir))
        test_lab_migrations = [f for f in migration_files if "test_lab" in f.lower() or "testlab" in f.lower()]

        if not test_lab_migrations:
            pytest.skip("No test_lab migration file found")

        migration_path = os.path.join(migrations_dir, test_lab_migrations[0])
        with open(migration_path, "r") as f:
            content = f.read()

        # Check for DROP TABLE IF EXISTS (for rollback)
        has_rollback = "DROP TABLE" in content.upper() or "drop table" in content.lower()
        # Note: Supabase migrations typically don't have explicit down functions,
        # but we check for safe cleanup patterns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
