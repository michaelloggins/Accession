"""Drop and recreate test tables with correct schema."""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import engine, Base
from app.models.test import Test, TestSpecimenType
from sqlalchemy import text

def reset_test_tables():
    """Drop and recreate test tables."""
    print("Resetting test tables...")

    with engine.begin() as conn:
        # Drop tables in correct order (foreign key dependencies)
        conn.execute(text('DROP TABLE IF EXISTS test_specimen_types'))
        conn.execute(text('DROP TABLE IF EXISTS tests'))
        print("Dropped old test tables")

    # Recreate with correct schema
    Base.metadata.create_all(bind=engine, tables=[Test.__table__, TestSpecimenType.__table__])
    print("Created new test tables with correct schema")

if __name__ == "__main__":
    reset_test_tables()
