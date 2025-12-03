"""
Clear incorrect tests and reseed with MVD veterinary tests.
"""

import sys
from app.database import SessionLocal, init_db
from app.models.test import Test, TestSpecimenType

def clear_tests():
    """Clear all existing tests and specimen types."""
    print("Clearing Test Catalog...")
    print("=" * 60)

    session = SessionLocal()
    try:
        # Get counts before deletion
        test_count = session.query(Test).count()
        specimen_count = session.query(TestSpecimenType).count()

        print(f"Found {test_count} tests and {specimen_count} specimen types")

        if test_count == 0:
            print("No tests to delete")
            return True

        # Delete all test specimen types (cascade should handle this, but being explicit)
        deleted_specimens = session.query(TestSpecimenType).delete()
        print(f"Deleted {deleted_specimens} specimen type entries")

        # Delete all tests
        deleted_tests = session.query(Test).delete()
        print(f"Deleted {deleted_tests} tests")

        session.commit()

        # Verify deletion
        final_test_count = session.query(Test).count()
        final_specimen_count = session.query(TestSpecimenType).count()

        print(f"\nVerification:")
        print(f"  Tests remaining: {final_test_count}")
        print(f"  Specimen types remaining: {final_specimen_count}")

        if final_test_count == 0 and final_specimen_count == 0:
            print("\n[SUCCESS] Database cleared successfully!")
            return True
        else:
            print("\n[WARNING] Some records may not have been deleted")
            return False

    except Exception as e:
        print(f"\n[ERROR] {e}")
        session.rollback()
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()


if __name__ == "__main__":
    print("This will DELETE ALL TESTS from the database and reseed with MVD tests\n")

    response = input("Are you sure you want to continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Operation cancelled.")
        sys.exit(0)

    # Initialize database
    print("\nInitializing database...")
    init_db()

    # Clear existing tests
    if clear_tests():
        print("\n" + "=" * 60)
        print("Database cleared. Now run: python seed_test_catalog.py")
        print("=" * 60)
    else:
        print("\n[FAILED] Could not clear database")
        sys.exit(1)
