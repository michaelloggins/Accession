"""
Seed the test catalog with data from test_specimen_volumes.json
Run this after creating a fresh database to populate the tests table.
"""

import json
import sys
from pathlib import Path

from app.database import SessionLocal, init_db
from app.models.test import Test, TestSpecimenType


def load_test_data():
    """Load test data from JSON file."""
    json_path = Path("prompts/mvd_veterinary_tests.json")

    if not json_path.exists():
        print(f"Error: {json_path} not found")
        print(f"Looking in: {json_path.absolute()}")
        return None

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return data.get('tests', {})


def seed_tests():
    """Seed the test catalog with test and specimen type data."""

    print("Test Catalog Seeder")
    print("=" * 60)

    # Load test data
    test_data = load_test_data()
    if not test_data:
        print("No test data found!")
        return False

    session = SessionLocal()
    try:
        # Check if tests already exist
        existing_count = session.query(Test).count()
        if existing_count > 0:
            print(f"\nWarning: Database already has {existing_count} tests")
            response = input("Do you want to continue and add more? (y/n): ")
            if response.lower() != 'y':
                print("Operation cancelled.")
                return False

        added_tests = 0
        added_specimens = 0

        for test_name, test_info in test_data.items():
            print(f"\nProcessing: {test_name}")

            # Get test type from JSON or determine from name
            test_type = test_info.get("test_type", "Antigen Test")

            # Get test_code (required in MVD catalog)
            test_code = test_info.get("test_code")
            if not test_code:
                print(f"  [ERROR] Test {test_name} missing test_code, skipping...")
                continue

            # Get species information
            species = test_info.get("species", "Any")

            # Check if test already exists
            existing_test = session.query(Test).filter(Test.test_number == test_code).first()
            if existing_test:
                print(f"  [SKIP] Test {test_code} already exists, skipping...")
                test = existing_test
            else:
                # Create test record
                test = Test(
                    test_number=test_code,
                    test_name=test_name,
                    full_name=test_info.get("full_name", test_name),
                    test_type=test_type,
                    species=species,
                    cpt_code=test_info.get("cpt_code", ""),
                    description=test_info.get("notes", "")
                )

                session.add(test)
                session.flush()  # Get the test.id
                added_tests += 1

                print(f"  [OK] Added test {test_code}: {test_name} (Species: {species})")

            # Add specimen types for this test
            specimens = test_info.get("specimens", {})
            for specimen_name, specimen_info in specimens.items():
                # Check if this specimen type already exists for this test
                existing_specimen = session.query(TestSpecimenType).filter(
                    TestSpecimenType.test_id == test.id,
                    TestSpecimenType.specimen_type == specimen_name
                ).first()

                if existing_specimen:
                    min_vol = specimen_info.get("minimum_volume_ml", "N/A")
                    print(f"    [SKIP] {specimen_name}: {min_vol} mL (already exists)")
                else:
                    specimen_type = TestSpecimenType(
                        test_id=test.id,
                        specimen_type=specimen_name,
                        minimum_volume_ml=specimen_info.get("minimum_volume_ml"),
                        preferred_container=specimen_info.get("preferred_tube") or specimen_info.get("preferred_container"),
                        notes=specimen_info.get("notes")
                    )

                    session.add(specimen_type)
                    added_specimens += 1

                    min_vol = specimen_info.get("minimum_volume_ml", "N/A")
                    print(f"    + {specimen_name}: {min_vol} mL")

        # Commit all changes
        session.commit()

        print("\n" + "=" * 60)
        print(f"[SUCCESS] Added {added_tests} tests")
        print(f"[SUCCESS] Added {added_specimens} specimen type entries")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\nError: {e}")
        session.rollback()
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()


def verify_data():
    """Verify the seeded data."""
    session = SessionLocal()
    try:
        test_count = session.query(Test).count()
        specimen_count = session.query(TestSpecimenType).count()

        print("\nDatabase Statistics:")
        print(f"  Tests: {test_count}")
        print(f"  Specimen Types: {specimen_count}")

        # Show sample data
        print("\nSample Tests:")
        sample_tests = session.query(Test).limit(5).all()
        for test in sample_tests:
            print(f"  * {test.test_name} ({test.test_type})")
            specimens = session.query(TestSpecimenType).filter(
                TestSpecimenType.test_id == test.id
            ).all()
            for spec in specimens:
                print(f"      - {spec.specimen_type}: {spec.minimum_volume_ml} mL")

    finally:
        session.close()


if __name__ == "__main__":
    print("This will seed the test catalog from test_specimen_volumes.json\n")

    # Initialize database if needed
    print("Initializing database...")
    init_db()

    # Seed tests
    success = seed_tests()

    if success:
        print("\n" + "=" * 60)
        verify_data()
        print("\n[SUCCESS] Test catalog seeding complete!")
    else:
        print("\n[FAILED] Test catalog seeding failed")
        sys.exit(1)
