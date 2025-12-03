# Database Migration Guide
## Version 2.0 - Multi-Species Support with StarLIMS Integration

## Overview
This guide covers migrating from the single-purpose veterinary schema to the new multi-species schema that supports both human and veterinary patients with StarLIMS integration.

## What's New in V2.0

### 1. **Species Reference Table**
- Centralizes species management
- Supports both human and veterinary patients
- Enables species-specific test menus and specimen requirements

### 2. **Enhanced Patient Model**
- Flexible fields for both human and animal patients
- For **Human**: Patient name in `owner_first_name/last_name`, `pet_name` = NULL
- For **Veterinary**: Owner name + pet name populated
- Added contact fields (phone, email, address) for human patients

### 3. **StarLIMS Integration Fields** (in Orders table)
- `starlims_accession` - StarLIMS accession number
- `starlims_status` - Current status from StarLIMS
- `starlims_error` - Error messages from StarLIMS
- `lab_support_ticket` - Support ticket reference number

### 4. **Enhanced Order Tracking**
- `source_document_id` - Links to the original scanned document
- `extracted_json` - Full JSON from AI extraction for audit trail

### 5. **Species-Specific Test Requirements**
- Test specimen types can now have species-specific minimum volumes
- Different requirements for human vs. veterinary patients
- Shown on back of requisition forms

---

## Migration Steps

### Step 1: Backup Current Database (if you have data)

```bash
# For SQLite
cp test.db test.db.backup.$(date +%Y%m%d)

# For PostgreSQL
pg_dump -U username database_name > backup_$(date +%Y%m%d).sql
```

### Step 2: Delete Old Database (Fresh Start)

```bash
# WARNING: This deletes all data!
rm test.db
```

### Step 3: Initialize New Schema

```bash
python -c "from app.database import init_db; init_db()"
```

This will:
- Create all tables with new schema
- Set document and order IDs to start from 1001

### Step 4: Seed Reference Data

```bash
# Seed species (Human, Canine, Feline, Equine, etc.)
python seed_species.py

# Seed test catalog (MVista tests + common lab tests)
python seed_test_catalog.py
```

### Step 5: Verify Database

```bash
python verify_database.py  # (create this script or use SQL)
```

Expected counts:
- Species: 12 (1 human + 11 veterinary)
- Tests: ~20+ (MiraVista + common tests)
- Test Specimen Types: ~40+ (test-specimen combinations)

---

## New Database Schema

```
species (12 rows)
├── Human
├── Canine (Dog)
├── Feline (Cat)
├── Equine (Horse)
├── Bovine (Cattle)
├── Ovine (Sheep)
├── Caprine (Goat)
├── Porcine (Pig)
├── Avian (Bird)
├── Reptilian
├── Rodent
└── Aquatic

facilities
├── id (PK)
├── facility_id (external code)
├── facility_name
├── address, city, state, zipcode
├── laboratory_contact
└── phone, fax, email

patients
├── id (PK)
├── facility_id (FK)
├── species_id (FK) ← NEW
├── owner_first_name
├── owner_middle_name ← NEW
├── owner_last_name
├── pet_name (nullable for humans)
├── date_of_birth
├── medical_record_number ← NEW
├── patient_id ← NEW
├── phone, email ← NEW
├── address, city, state, zipcode ← NEW
└── gender ← NEW

orders (starts at ID 1001)
├── id (PK)
├── facility_id (FK)
├── patient_id (FK)
├── ordering_veterinarian
├── specimen_collection_date
├── specimen_collection_time
├── specimen_storage_temperature
├── order_date
├── status
├── reviewed_by, reviewed_at
├── reviewer_notes
├── submitted_to_lab
├── lab_submission_date
├── lab_confirmation_id
├── starlims_accession ← NEW
├── starlims_status ← NEW
├── starlims_error ← NEW
├── lab_support_ticket ← NEW
├── source_document_id (FK) ← NEW
├── extracted_json ← NEW
├── created_at
└── updated_at

tests
├── id (PK)
├── test_number (unique)
├── test_name
├── full_name
├── test_type
├── cpt_code
└── description

test_specimen_types
├── id (PK)
├── test_id (FK)
├── species_id (FK, nullable) ← NEW (NULL = all species)
├── specimen_type
├── minimum_volume_ml
├── preferred_container
└── notes

order_tests (junction table)
├── id (PK)
├── order_id (FK)
├── test_id (FK)
├── specimen_type (actual specimen used)
├── specimen_volume_ml (actual volume)
└── specimen_notes

documents (starts at ID 1001)
├── id (PK)
├── order_id (FK, nullable)
├── filename
├── blob_name
├── upload_date
├── uploaded_by
├── extracted_data
├── confidence_score
├── status
├── reviewed_by, reviewed_at
├── corrected_data
├── submitted_to_lab
├── lab_submission_date
├── lab_confirmation_id
├── reviewer_notes
├── document_type
├── source
├── created_at
└── updated_at
```

---

## Data Examples

### Example 1: Human Patient

```sql
-- Species
INSERT INTO species VALUES (1, 'Human', 'Humans', 'Human patients', 'human', 1);

-- Facility
INSERT INTO facilities VALUES (1, 'FAC001', 'City Hospital Lab',
    '123 Main St', 'Indianapolis', 'IN', '46201',
    'Dr. Smith', '317-555-0100', '317-555-0101', 'lab@cityhospital.com');

-- Patient (Human)
INSERT INTO patients VALUES (1, 1, 1,  -- facility_id=1, species_id=1
    'Doe', 'John', 'A',  -- owner names (patient's name)
    NULL,  -- pet_name is NULL for humans
    '1980-05-15',  -- date_of_birth
    'MRN12345', 'PAT001',  -- medical record, patient ID
    '317-555-1234', 'john.doe@email.com',  -- phone, email
    '456 Oak St', 'Indianapolis', 'IN', '46201',  -- address
    'M');  -- gender

-- Order
INSERT INTO orders VALUES (1001, 1, 1,  -- facility_id=1, patient_id=1
    'Dr. Jane Smith',  -- ordering_veterinarian (actually MD for humans)
    '2025-01-18', '09:30',  -- collection date/time
    'Stored Refrigerated',
    CURRENT_TIMESTAMP, 'pending', ...);
```

### Example 2: Veterinary Patient

```sql
-- Species
INSERT INTO species VALUES (2, 'Canine', 'Dog', 'Domestic dogs', 'veterinary', 1);

-- Facility
INSERT INTO facilities VALUES (2, 'VET001', 'Happy Paws Veterinary',
    '789 Vet Rd', 'Indianapolis', 'IN', '46240',
    'Dr. Williams', '317-555-0200', '317-555-0201', 'info@happypaws.com');

-- Patient (Dog)
INSERT INTO patients VALUES (2, 2, 2,  -- facility_id=2, species_id=2
    'Smith', 'Sarah', NULL,  -- owner name
    'Fluffy',  -- pet_name
    '2020-03-10',  -- pet's DOB
    NULL, NULL,  -- MRN, patient_id (optional for vet)
    NULL, NULL,  -- phone, email (optional)
    NULL, NULL, NULL, NULL,  -- address (optional)
    'F');  -- gender (Female)

-- Order
INSERT INTO orders VALUES (1002, 2, 2,
    'Dr. Williams, DVM',
    '2025-01-18', '10:00',
    'Stored Ambient',
    CURRENT_TIMESTAMP, 'pending', ...);
```

### Example 3: Species-Specific Test Requirements

```sql
-- Test
INSERT INTO tests VALUES (1, '310', 'MVista Histoplasma Ag',
    'MVista® Histoplasma Ag Quantitative EIA', 'Antigen Test', '87385', '...');

-- Specimen Type - Applies to ALL species (species_id = NULL)
INSERT INTO test_specimen_types VALUES (1, 1, NULL, 'Urine', 0.5,
    'Sterile container', 'Standard requirement for all species');

-- Specimen Type - HUMAN SPECIFIC (species_id = 1)
INSERT INTO test_specimen_types VALUES (2, 1, 1, 'Serum', 2.0,
    'Gold top (SST)', 'Human patients require 2.0mL');

-- Specimen Type - CANINE SPECIFIC (species_id = 2)
INSERT INTO test_specimen_types VALUES (3, 1, 2, 'Serum', 1.2,
    'Gold top (SST)', 'Dogs require only 1.2mL');
```

---

## API/Application Changes Required

### 1. Update Extraction Logic

When processing a document, determine if it's human or veterinary:

```python
# In extraction service
if "veterinarian" in extracted_data or "pet_name" in extracted_data:
    species_name = extracted_data.get("species", "Canine")
else:
    species_name = "Human"

# Find or create species
species = session.query(Species).filter(Species.name == species_name).first()

# Create patient
patient = Patient(
    facility_id=facility.id,
    species_id=species.id,
    owner_first_name=extracted_data.get("patient_first_name") or extracted_data.get("owner_first_name"),
    owner_last_name=extracted_data.get("patient_last_name") or extracted_data.get("owner_last_name"),
    pet_name=extracted_data.get("pet_name"),  # NULL for humans
    ...
)

# Create order with source document link
order = Order(
    facility_id=facility.id,
    patient_id=patient.id,
    source_document_id=document.id,  # Link to original document
    extracted_json=json.dumps(extracted_data),  # Store full JSON
    ...
)
```

### 2. Update Test Menu Display

Filter tests by species category:

```python
# For veterinary requisitions
vet_species = session.query(Species).filter(Species.id == patient.species_id).first()
if vet_species.test_category == "veterinary":
    # Show veterinary tests
    tests = session.query(Test).filter(Test.test_type.in_([
        "Antigen Test", "Antibody Test", "Panel - Syndrome"
    ])).all()
else:
    # Show human tests
    tests = session.query(Test).filter(Test.test_type.in_([
        "Panel - General/Geographic", "Drug Monitoring"
    ])).all()
```

### 3. Display Species-Specific Requirements

When showing test details:

```python
def get_specimen_requirements(test_id, species_id):
    """Get specimen requirements for a test, considering species."""
    # Try species-specific first
    requirements = session.query(TestSpecimenType).filter(
        TestSpecimenType.test_id == test_id,
        TestSpecimenType.species_id == species_id
    ).all()

    # Fall back to generic (species_id = NULL)
    if not requirements:
        requirements = session.query(TestSpecimenType).filter(
            TestSpecimenType.test_id == test_id,
            TestSpecimenType.species_id == None
        ).all()

    return requirements
```

### 4. StarLIMS Integration Hooks

```python
def submit_to_starlims(order_id):
    """Submit order to StarLIMS."""
    order = session.query(Order).filter(Order.id == order_id).first()

    try:
        response = starlims_api.submit_order(order.to_dict())

        # Update order with StarLIMS info
        order.starlims_accession = response.get("accession_number")
        order.starlims_status = "SUBMITTED"
        order.submitted_to_lab = 1
        order.lab_submission_date = datetime.utcnow()

        session.commit()
        return True

    except StarLIMSError as e:
        # Log error
        order.starlims_error = str(e)
        order.starlims_status = "ERROR"

        # Create support ticket
        ticket = create_support_ticket(order_id, str(e))
        order.lab_support_ticket = ticket.ticket_number

        session.commit()
        return False
```

---

## Testing the Migration

### 1. Test Human Patient Creation

```bash
# Create human patient order manually
# Verify: species_id = 1 (Human)
# Verify: pet_name = NULL
# Verify: Contact info populated
```

### 2. Test Veterinary Patient Creation

```bash
# Create dog patient order
# Verify: species_id = 2 (Canine)
# Verify: pet_name populated
# Verify: Owner name separate from pet name
```

### 3. Test Species-Specific Requirements

```bash
# Query test requirements for human patient
# Verify: Returns human-specific minimum volumes

# Query same test for dog patient
# Verify: Returns dog-specific minimum volumes
```

### 4. Test StarLIMS Integration

```bash
# Submit order to StarLIMS (mock)
# Verify: starlims_accession populated
# Verify: starlims_status = "SUBMITTED"

# Simulate error
# Verify: starlims_error populated
# Verify: lab_support_ticket created
```

---

## Rollback Plan

If migration fails:

```bash
# Restore backup
cp test.db.backup.20250118 test.db

# Restart application
python main.py
```

---

## Complete Migration Script

```bash
#!/bin/bash
# complete_migration.sh

echo "Starting database migration to V2.0..."

# Backup
echo "1. Backing up current database..."
cp test.db test.db.backup.$(date +%Y%m%d)

# Delete old database
echo "2. Deleting old database..."
rm test.db

# Initialize new schema
echo "3. Initializing new schema..."
python -c "from app.database import init_db; init_db()"

# Seed reference data
echo "4. Seeding species..."
python seed_species.py

echo "5. Seeding test catalog..."
python seed_test_catalog.py

# Verify
echo "6. Verifying database..."
python -c "from app.models import Species, Test; from app.database import SessionLocal; s = SessionLocal(); print(f'Species: {s.query(Species).count()}'); print(f'Tests: {s.query(Test).count()}'); s.close()"

echo "Migration complete!"
```

---

## Support

If you encounter issues:

1. Check backup exists: `ls -la test.db.backup.*`
2. Review migration logs
3. Test with small dataset first
4. Verify all relationships with SQL queries
5. Use `reset_document_id.py` if ID sequence is wrong

## Next Steps After Migration

1. Update extraction prompts to detect human vs. veterinary
2. Update UI to show species selector
3. Implement StarLIMS API integration
4. Add species-specific validation rules
5. Create reports filtered by species
