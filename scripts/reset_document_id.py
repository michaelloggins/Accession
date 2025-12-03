"""
Script to reset the document ID sequence to start from 1001.
Run this script to set the next document ID to 1001.
"""

import sys
from sqlalchemy import text
from app.database import engine, SessionLocal
from app.models.document import Document

def reset_document_id_sequence(start_id=1001):
    """Reset the document ID sequence to start from specified ID."""

    session = SessionLocal()
    try:
        # Check if there are any existing documents
        max_id = session.query(Document.id).order_by(Document.id.desc()).first()

        if max_id and max_id[0] >= start_id:
            print(f"Warning: Highest existing document ID is {max_id[0]}, which is >= {start_id}")
            response = input(f"Do you want to continue? This will set next ID to {max_id[0] + 1} (y/n): ")
            if response.lower() != 'y':
                print("Operation cancelled.")
                return False
            start_id = max_id[0] + 1

        # For SQLite, we need to update the sqlite_sequence table
        with engine.connect() as conn:
            # Check if the sequence exists
            result = conn.execute(text(
                "SELECT name FROM sqlite_sequence WHERE name = 'documents'"
            ))

            if result.fetchone():
                # Update existing sequence
                conn.execute(text(
                    f"UPDATE sqlite_sequence SET seq = {start_id - 1} WHERE name = 'documents'"
                ))
                conn.commit()
                print(f"✓ Updated sqlite_sequence. Next document ID will be: {start_id}")
            else:
                # Insert new sequence entry (will be used after first insert)
                conn.execute(text(
                    f"INSERT INTO sqlite_sequence (name, seq) VALUES ('documents', {start_id - 1})"
                ))
                conn.commit()
                print(f"✓ Created sqlite_sequence entry. Next document ID will be: {start_id}")

        return True

    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def verify_next_id():
    """Verify what the next document ID will be."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT seq FROM sqlite_sequence WHERE name = 'documents'"
        ))
        row = result.fetchone()
        if row:
            next_id = row[0] + 1
            print(f"Next document ID will be: {next_id}")
            return next_id
        else:
            print("No sequence found yet (will be created on first insert)")
            return None


if __name__ == "__main__":
    print("Document ID Sequence Reset Tool")
    print("=" * 50)

    # Show current state
    print("\nCurrent state:")
    verify_next_id()

    # Ask for confirmation
    print(f"\nThis will set the next document ID to 1001")
    response = input("Continue? (y/n): ")

    if response.lower() == 'y':
        success = reset_document_id_sequence(1001)
        if success:
            print("\n" + "=" * 50)
            print("Verification:")
            verify_next_id()
            print("\n✓ Document ID sequence has been reset successfully!")
        else:
            print("\n✗ Failed to reset document ID sequence")
            sys.exit(1)
    else:
        print("Operation cancelled.")
