"""Fix blob_name column to be nullable in documents table."""
import sqlite3
import shutil
import os
from datetime import datetime

# Backup the database first
db_path = "test.db"
if os.path.exists(db_path):
    backup_path = f"test.db.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"Creating backup: {backup_path}")
    shutil.copy2(db_path, backup_path)

# Connect to database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # SQLite doesn't support ALTER COLUMN directly, so we need to:
    # 1. Create a new table with the correct schema
    # 2. Copy data from old table
    # 3. Drop old table
    # 4. Rename new table

    print("Creating new documents table with nullable blob_name...")
    cursor.execute("""
        CREATE TABLE documents_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            filename VARCHAR(255) NOT NULL,
            blob_name VARCHAR(500),
            upload_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            uploaded_by VARCHAR(100) NOT NULL,
            extracted_data TEXT,
            confidence_score NUMERIC(5, 4),
            status VARCHAR(50) DEFAULT 'pending',
            reviewed_by VARCHAR(100),
            reviewed_at DATETIME,
            corrected_data TEXT,
            submitted_to_lab BOOLEAN DEFAULT 0,
            lab_submission_date DATETIME,
            lab_confirmation_id VARCHAR(100),
            reviewer_notes TEXT,
            document_type VARCHAR(50),
            source VARCHAR(50),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    print("Copying data from old table...")
    cursor.execute("""
        INSERT INTO documents_new
        SELECT * FROM documents
    """)

    print("Dropping old table...")
    cursor.execute("DROP TABLE documents")

    print("Renaming new table...")
    cursor.execute("ALTER TABLE documents_new RENAME TO documents")

    print("Creating indexes...")
    cursor.execute("CREATE INDEX idx_status ON documents(status)")
    cursor.execute("CREATE INDEX idx_upload_date ON documents(upload_date)")
    cursor.execute("CREATE INDEX idx_reviewed_at ON documents(reviewed_at)")
    cursor.execute("CREATE INDEX idx_order_id ON documents(order_id)")

    conn.commit()
    print("✅ Database schema updated successfully!")
    print("blob_name is now nullable for manual orders")

except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()
finally:
    conn.close()
