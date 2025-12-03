"""
Seed the species reference table with common species for both human and veterinary testing.
Run this after creating a fresh database.
"""

import sys
from app.database import SessionLocal, init_db
from app.models.species import Species


SPECIES_DATA = [
    # Human
    {
        "name": "Human",
        "common_name": "Humans",
        "description": "Human patients - uses human test menu with different specimen requirements",
        "test_category": "human"
    },

    # Veterinary - Companion Animals
    {
        "name": "Canine",
        "common_name": "Dog",
        "description": "Domestic dogs - most common veterinary patient",
        "test_category": "veterinary"
    },
    {
        "name": "Feline",
        "common_name": "Cat",
        "description": "Domestic cats",
        "test_category": "veterinary"
    },

    # Veterinary - Large Animals
    {
        "name": "Equine",
        "common_name": "Horse",
        "description": "Horses, ponies, donkeys, mules",
        "test_category": "veterinary"
    },
    {
        "name": "Bovine",
        "common_name": "Cattle",
        "description": "Cows, bulls, calves",
        "test_category": "veterinary"
    },
    {
        "name": "Ovine",
        "common_name": "Sheep",
        "description": "Domestic sheep",
        "test_category": "veterinary"
    },
    {
        "name": "Caprine",
        "common_name": "Goat",
        "description": "Domestic goats",
        "test_category": "veterinary"
    },
    {
        "name": "Porcine",
        "common_name": "Pig",
        "description": "Pigs, hogs, swine",
        "test_category": "veterinary"
    },

    # Veterinary - Exotic/Other
    {
        "name": "Avian",
        "common_name": "Bird",
        "description": "Birds (parrots, chickens, ducks, etc.)",
        "test_category": "veterinary"
    },
    {
        "name": "Reptilian",
        "common_name": "Reptile",
        "description": "Reptiles (snakes, lizards, turtles)",
        "test_category": "veterinary"
    },
    {
        "name": "Rodent",
        "common_name": "Small Mammal",
        "description": "Rodents and small mammals (rabbits, guinea pigs, hamsters)",
        "test_category": "veterinary"
    },
    {
        "name": "Aquatic",
        "common_name": "Fish/Aquatic",
        "description": "Fish and aquatic animals",
        "test_category": "veterinary"
    },
]


def seed_species():
    """Seed the species reference table."""

    print("Species Reference Table Seeder")
    print("=" * 60)

    session = SessionLocal()
    try:
        # Check if species already exist
        existing_count = session.query(Species).count()
        if existing_count > 0:
            print(f"\nWarning: Database already has {existing_count} species")
            response = input("Do you want to continue and add more? (y/n): ")
            if response.lower() != 'y':
                print("Operation cancelled.")
                return False

        added_count = 0

        for species_data in SPECIES_DATA:
            # Check if species already exists
            existing = session.query(Species).filter(
                Species.name == species_data["name"]
            ).first()

            if existing:
                print(f"  ⊘ Skipping {species_data['name']} (already exists)")
                continue

            species = Species(
                name=species_data["name"],
                common_name=species_data["common_name"],
                description=species_data["description"],
                test_category=species_data["test_category"],
                is_active=1
            )

            session.add(species)
            added_count += 1

            category_badge = "[HUMAN]" if species_data["test_category"] == "human" else "[VET]"
            print(f"  ✓ Added {category_badge} {species_data['name']} ({species_data['common_name']})")

        # Commit all changes
        session.commit()

        print("\n" + "=" * 60)
        print(f"✓ Successfully added {added_count} species")
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
        total_count = session.query(Species).count()
        human_count = session.query(Species).filter(Species.test_category == "human").count()
        vet_count = session.query(Species).filter(Species.test_category == "veterinary").count()

        print("\nDatabase Statistics:")
        print(f"  Total Species: {total_count}")
        print(f"  Human: {human_count}")
        print(f"  Veterinary: {vet_count}")

        # Show all species
        print("\nAll Species:")
        print("-" * 60)
        print(f"{'ID':<5} {'Name':<15} {'Common Name':<20} {'Category':<12}")
        print("-" * 60)

        all_species = session.query(Species).order_by(Species.test_category, Species.name).all()
        for species in all_species:
            print(f"{species.id:<5} {species.name:<15} {species.common_name:<20} {species.test_category:<12}")

    finally:
        session.close()


if __name__ == "__main__":
    print("This will seed the species reference table\n")

    # Initialize database if needed
    print("Initializing database...")
    init_db()

    # Seed species
    success = seed_species()

    if success:
        print("\n" + "=" * 60)
        verify_data()
        print("\n✓ Species seeding complete!")
    else:
        print("\n✗ Species seeding failed")
        sys.exit(1)
