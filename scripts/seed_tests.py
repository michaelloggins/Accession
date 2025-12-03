"""
Seed the database with MiraVista test catalog.
Run this script to populate the tests table with all MiraVista tests.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models.test import Test, TestSpecimenType

def seed_tests():
    """Populate database with MiraVista test catalog."""
    db = SessionLocal()

    try:
        # Check if tests already exist
        existing_count = db.query(Test).count()
        if existing_count > 0:
            print(f"Database already contains {existing_count} tests.")
            response = input("Do you want to clear and re-seed? (yes/no): ")
            if response.lower() != 'yes':
                print("Aborted.")
                return

            # Clear existing tests
            db.query(TestSpecimenType).delete()
            db.query(Test).delete()
            db.commit()
            print("Cleared existing tests.")

        # Individual Tests
        tests_data = [
            # Antigen Tests
            {
                "test_number": "309",
                "test_name": "Aspergillus EIA",
                "test_type": "Antigen Test",
                "species": "Any",
                "specimens": ["SER", "PLS", "BAL"],
                "min_volume": 1.0
            },
            {
                "test_number": "310",
                "test_name": "Histoplasma EIA",
                "test_type": "Antigen Test",
                "species": "Any",
                "specimens": ["UR", "SER", "PLS", "CSF", "BAL"],
                "min_volume": 1.0
            },
            {
                "test_number": "315",
                "test_name": "Coccidioides EIA",
                "test_type": "Antigen Test",
                "species": "Any",
                "specimens": ["UR", "SER", "PLS", "CSF"],
                "min_volume": 1.0
            },
            {
                "test_number": "316",
                "test_name": "Blastomyces EIA",
                "test_type": "Antigen Test",
                "species": "Any",
                "specimens": ["UR", "SER", "PLS"],
                "min_volume": 1.0
            },
            {
                "test_number": "317",
                "test_name": "Beta-D-Glucan (BDG)",
                "test_type": "Antigen Test",
                "species": "Any",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "319",
                "test_name": "Cryptococcus LA",
                "test_type": "Antigen Test",
                "species": "Any",
                "specimens": ["SER", "CSF"],
                "min_volume": 0.5
            },

            # Antibody Tests
            {
                "test_number": "320",
                "test_name": "Coccidioides ID (Any)",
                "test_type": "Antibody Test",
                "species": "Any",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "321",
                "test_name": "Histoplasma ID (Any)",
                "test_type": "Antibody Test",
                "species": "Any",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "322",
                "test_name": "Blastomyces ID",
                "test_type": "Antibody Test",
                "species": "Any",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "324",
                "test_name": "Aspergillus ID (Any)",
                "test_type": "Antibody Test",
                "species": "Any",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "327",
                "test_name": "Histoplasma IgG EIA (K9)",
                "test_type": "Antibody Test",
                "species": "K9",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "328",
                "test_name": "Histoplasma IgG EIA (Fel)",
                "test_type": "Antibody Test",
                "species": "Feline",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "329",
                "test_name": "Coccidioides IgG EIA (K9)",
                "test_type": "Antibody Test",
                "species": "K9",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "330",
                "test_name": "Blastomyces IgG EIA (K9)",
                "test_type": "Antibody Test",
                "species": "K9",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },
            {
                "test_number": "332",
                "test_name": "Pythium IgG EIA (K9/Fel)",
                "test_type": "Antibody Test",
                "species": "K9 & Feline",
                "specimens": ["SER", "PLS"],
                "min_volume": 0.5
            },

            # Bioassay Test
            {
                "test_number": "312",
                "test_name": "Itraconazole",
                "test_type": "Bioassay",
                "species": "Any",
                "specimens": ["SER", "PLS"],
                "min_volume": 1.0
            },

            # Panel Tests - Feline
            {
                "test_number": "900",
                "test_name": "Fel Fungal, Ext",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "903",
                "test_name": "Fel Fungal West",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "907",
                "test_name": "Fel Fungal East",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "909",
                "test_name": "Fel Fungal, Comp",
                "test_type": "Panel - General",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "913",
                "test_name": "Fel Histoplasmosis",
                "test_type": "Panel - General",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "917",
                "test_name": "Fel Fungal GI",
                "test_type": "Panel - General",
                "specimens": ["UR"],
                "min_volume": 1.0
            },
            {
                "test_number": "920",
                "test_name": "Fel Fungal Bone West",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "921",
                "test_name": "Fel Fungal Bone East",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },

            # Panel Tests - Canine (K9)
            {
                "test_number": "901",
                "test_name": "K9 Fungal West, Ext",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "902",
                "test_name": "K9 Fungal East, Ext",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "904",
                "test_name": "K9 Fungal West",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "905",
                "test_name": "K9 Fungal East",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "908",
                "test_name": "K9 Fungal, Comp",
                "test_type": "Panel - General",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "910",
                "test_name": "K9 Blastomycosis",
                "test_type": "Panel - General",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "911",
                "test_name": "K9 Histoplasmosis",
                "test_type": "Panel - General",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "912",
                "test_name": "K9 Coccidioidomycosis",
                "test_type": "Panel - General",
                "specimens": ["SER", "UR"],
                "min_volume": 2.0
            },
            {
                "test_number": "916",
                "test_name": "K9 Fungal GI",
                "test_type": "Panel - General",
                "specimens": ["UR"],
                "min_volume": 1.0
            },
            {
                "test_number": "918",
                "test_name": "K9 Fungal Bone East",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },
            {
                "test_number": "919",
                "test_name": "K9 Fungal Bone West",
                "test_type": "Panel - Geographic",
                "specimens": ["UR", "SER"],
                "min_volume": 2.0
            },

            # Panel Tests - K9 & Feline
            {
                "test_number": "914",
                "test_name": "K9 & Fel Mold-Hyphae",
                "test_type": "Panel - General",
                "specimens": ["SER", "BAL"],
                "min_volume": 1.5
            },
            {
                "test_number": "915",
                "test_name": "K9 & Fel Fungal Nasal",
                "test_type": "Panel - General",
                "specimens": ["SER", "BAL"],
                "min_volume": 1.5
            },
        ]

        # Insert tests
        for test_data in tests_data:
            # Determine species if not specified
            species = test_data.get("species")
            if not species:
                # Auto-detect species from test name
                test_name = test_data["test_name"]
                if "K9 & Fel" in test_name or "K9/Fel" in test_name:
                    species = "K9 & Feline"
                elif "Fel" in test_name:
                    species = "Feline"
                elif "K9" in test_name:
                    species = "K9"
                else:
                    species = "Any"

            # Create test
            test = Test(
                test_number=test_data["test_number"],
                test_name=test_data["test_name"],
                test_type=test_data["test_type"],
                species=species
            )
            db.add(test)
            db.flush()  # Get the ID

            # Add specimen types
            for specimen in test_data["specimens"]:
                specimen_type = TestSpecimenType(
                    test_id=test.id,
                    specimen_type=specimen,
                    minimum_volume_ml=test_data.get("min_volume")
                )
                db.add(specimen_type)

            print(f"Added test: {test_data['test_number']} - {test_data['test_name']}")

        db.commit()
        print(f"\n✅ Successfully seeded {len(tests_data)} tests into the database!")

    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding tests: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("MiraVista Test Catalog Seeder")
    print("=" * 50)
    seed_tests()
