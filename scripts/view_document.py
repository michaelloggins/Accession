"""View document data with decryption."""

from app.database import SessionLocal
from app.services.document_service import DocumentService
import json
import sys

doc_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1

db = SessionLocal()
doc_service = DocumentService(db)
doc = doc_service.get_document(doc_id)

if not doc:
    print(f"Document {doc_id} not found")
    sys.exit(1)

print("=" * 60)
print(f"Document ID: {doc.id}")
print(f"Filename: {doc.filename}")
print(f"Status: {doc.status}")
print(f"Confidence: {doc.confidence_score}")
print(f"Uploaded: {doc.upload_date}")
print(f"Uploaded By: {doc.uploaded_by}")
print("=" * 60)
print("\nExtracted Data (Decrypted):")
print(json.dumps(doc.extracted_data, indent=2))
print("\n" + "=" * 60)

db.close()
