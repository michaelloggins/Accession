"""Clear all documents, orders, audit logs, and uploaded files from the system."""

import sys
import os
import shutil
from sqlalchemy import text

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal, engine
from app.models.document import Document
from app.models.order import Order, OrderTest
from app.models.audit_log import AuditLog

def clear_all():
    """Clear all documents, orders, audit logs, and files."""
    db = SessionLocal()

    try:
        print("Clearing Lab Document Intelligence System...")
        print("=" * 50)

        # 1. Clear database records
        print("\n1. Clearing database records...")

        # Count before deletion
        doc_count = db.query(Document).count()
        order_test_count = db.query(OrderTest).count()
        order_count = db.query(Order).count()
        audit_count = db.query(AuditLog).count()

        print(f"   - Documents: {doc_count}")
        print(f"   - Orders: {order_count}")
        print(f"   - Order Tests: {order_test_count}")
        print(f"   - Audit Logs: {audit_count}")

        if doc_count == 0 and order_count == 0 and audit_count == 0:
            print("\n   No records to delete.")
        else:
            # Delete in correct order (respecting foreign keys)
            db.query(Document).delete()
            db.query(OrderTest).delete()
            db.query(Order).delete()
            db.query(AuditLog).delete()
            db.commit()
            print("   Database cleared successfully!")

        # 2. Reset auto-increment sequence for documents
        print("\n2. Resetting accession number sequence...")
        try:
            with engine.begin() as conn:
                # Reset the sqlite_sequence for documents table to 0
                # Next insert will be ID 1, which becomes A00000001
                result = conn.execute(text(
                    "SELECT name FROM sqlite_sequence WHERE name = 'documents'"
                ))
                if result.fetchone():
                    conn.execute(text(
                        "UPDATE sqlite_sequence SET seq = 0 WHERE name = 'documents'"
                    ))
                    print("   Accession number sequence reset to 0 (next will be A00000001)")
                else:
                    print("   No sequence to reset (will start at A00000001)")
        except Exception as e:
            print(f"   Warning: Could not reset sequence: {e}")

        # 3. Clear uploaded files
        print("\n3. Clearing uploaded files...")
        uploads_dir = "uploads"

        if os.path.exists(uploads_dir):
            # Count all files recursively
            file_count = sum([len(files) for r, d, files in os.walk(uploads_dir)])
            dir_count = sum([len(dirs) for r, dirs, f in os.walk(uploads_dir)])

            print(f"   - Files found: {file_count}")
            print(f"   - Directories found: {dir_count}")

            if file_count > 0 or dir_count > 0:
                # Remove entire uploads directory tree and recreate empty one
                for root, dirs, files in os.walk(uploads_dir, topdown=False):
                    for name in files:
                        file_path = os.path.join(root, name)
                        os.remove(file_path)
                    for name in dirs:
                        dir_path = os.path.join(root, name)
                        os.rmdir(dir_path)

                print("   Files and directories cleared successfully!")
            else:
                print("   No files or directories to delete.")
        else:
            print(f"   Uploads directory '{uploads_dir}' does not exist.")

        print("\n" + "=" * 50)
        print("System cleared successfully!")
        print("Next accession number will be: A00000001")
        print("=" * 50)

    except Exception as e:
        db.rollback()
        print(f"\nError clearing system: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("\nWARNING: This will delete ALL documents, orders, audit logs, and uploaded files!")
    print("The accession number sequence will be reset to start at A00000001")
    response = input("Are you sure you want to continue? (yes/no): ")

    if response.lower() == 'yes':
        clear_all()
    else:
        print("Operation cancelled.")
