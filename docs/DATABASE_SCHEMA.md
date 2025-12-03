# Database Schema Documentation

## Overview
This database schema is designed for a veterinary laboratory document intelligence system. It normalizes data from lab requisition forms into a relational structure.

## Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│   Facilities    │◄──────│    Patients     │◄──────│     Orders      │
│                 │ 1   * │                 │ 1   * │                 │
│ PK: id          │       │ PK: id          │       │ PK: id          │
│    facility_id  │       │ FK: facility_id │       │ FK: facility_id │
│    name         │       │    owner_name   │       │ FK: patient_id  │
│    address      │       │    pet_name     │       │    vet_name     │
│    city         │       │    pet_dob      │       │    coll_date    │
│    state        │       │    species      │       │    status       │
│    zipcode      │       └─────────────────┘       └────────┬────────┘
│    contact      │                                          │
│    phone        │                                          │ 1
│    fax          │                                          │
│    email        │                                          │
└─────────────────┘                                          │ *
                                                    ┌────────▼────────┐
┌─────────────────┐                                │   Order_Tests   │
│   Documents     │                                │                 │
│                 │                                │ PK: id          │
│ PK: id (1001+)  │                                │ FK: order_id    │
│ FK: order_id    │                                │ FK: test_id     │
│    filename     │                                │    specimen     │
│    blob_name    │                                │    volume       │
│    extracted    │                                └────────┬────────┘
│    confidence   │                                         │
│    status       │                                         │ *
└─────────────────┘                                         │ 1
                                                    ┌────────▼────────┐
┌─────────────────┐                                │     Tests       │
│   Users         │                                │                 │
│                 │                                │ PK: id          │
│ PK: id          │                                │    test_number  │
│    email        │                                │    test_name    │
│    role         │                                │    test_type    │
│    mfa_enabled  │                                │    cpt_code     │
└─────────────────┘                                └────────┬────────┘
                                                            │ 1
┌─────────────────┐                                        │
│   Audit_Logs    │                                        │ *
│                 │                                ┌───────▼──────────────┐
│ PK: id          │                                │ Test_Specimen_Types  │
│    user_id      │                                │                      │
│    action       │                                │ PK: id               │
│    resource     │                                │ FK: test_id          │
│    timestamp    │                                │    specimen_type     │
│    success      │                                │    min_volume_ml     │
└─────────────────┘                                │    preferred_tube    │
                                                   └──────────────────────┘
```

## Tables

### 1. Facilities
**Purpose:** Stores veterinary clinics/hospitals that submit lab orders

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Primary key |
| facility_id | VARCHAR(50) | UNIQUE, INDEXED | External facility code |
| facility_name | VARCHAR(255) | NOT NULL, INDEXED | Clinic/hospital name |
| address | VARCHAR(255) | | Street address |
| city | VARCHAR(100) | | City |
| state | VARCHAR(2) | | State code (e.g., "IN") |
| zipcode | VARCHAR(10) | | ZIP code |
| laboratory_contact | VARCHAR(100) | | Contact person name |
| phone | VARCHAR(20) | | Phone number |
| fax | VARCHAR(20) | | Fax number |
| email | VARCHAR(255) | | Email address |

**Indexes:**
- `idx_facility_name` on `facility_name`
- `idx_facility_city_state` on `(city, state)`

**Relationships:**
- One-to-Many with `patients`
- One-to-Many with `orders`

---

### 2. Patients
**Purpose:** Stores pet/animal information

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Primary key |
| facility_id | INTEGER | FK, NOT NULL, INDEXED | Reference to facilities |
| owner_last_name | VARCHAR(100) | NOT NULL, INDEXED | Owner's last name |
| owner_first_name | VARCHAR(100) | NOT NULL | Owner's first name |
| pet_name | VARCHAR(100) | NOT NULL, INDEXED | Pet's name |
| pet_date_of_birth | DATE | | Pet's date of birth |
| species | VARCHAR(50) | INDEXED | Dog, Cat, Horse, etc. |

**Indexes:**
- `idx_owner_name` on `(owner_last_name, owner_first_name)`
- `idx_pet_name_species` on `(pet_name, species)`

**Relationships:**
- Many-to-One with `facilities`
- One-to-Many with `orders`

---

### 3. Orders
**Purpose:** Lab orders/requisitions

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT (starts at 1001) | Primary key |
| facility_id | INTEGER | FK, NOT NULL, INDEXED | Reference to facilities |
| patient_id | INTEGER | FK, NOT NULL, INDEXED | Reference to patients |
| ordering_veterinarian | VARCHAR(100) | NOT NULL | Vet who ordered tests |
| specimen_collection_date | DATE | NOT NULL, INDEXED | When specimen was collected |
| specimen_collection_time | VARCHAR(10) | | Collection time (HH:MM) |
| specimen_storage_temperature | VARCHAR(50) | | Stored Ambient/Frozen/Refrigerated |
| order_date | DATETIME | DEFAULT CURRENT_TIMESTAMP | When order was created |
| status | VARCHAR(50) | DEFAULT 'pending', INDEXED | pending/reviewed/approved/rejected/submitted |
| reviewed_by | VARCHAR(100) | | Who reviewed the order |
| reviewed_at | DATETIME | | When reviewed |
| reviewer_notes | TEXT | | Reviewer's notes |
| submitted_to_lab | INTEGER | DEFAULT 0 | 0=false, 1=true |
| lab_submission_date | DATETIME | | When submitted to lab |
| lab_confirmation_id | VARCHAR(100) | | Lab's confirmation ID |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | Record creation time |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | Last update time |

**Indexes:**
- `idx_order_status` on `status`
- `idx_order_collection_date` on `specimen_collection_date`
- `idx_order_facility_patient` on `(facility_id, patient_id)`

**Relationships:**
- Many-to-One with `facilities`
- Many-to-One with `patients`
- One-to-Many with `order_tests`
- One-to-Many with `documents`

---

### 4. Tests
**Purpose:** Catalog of available tests

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Primary key |
| test_number | VARCHAR(50) | UNIQUE, NOT NULL, INDEXED | Test code (e.g., "310") |
| test_name | VARCHAR(255) | NOT NULL, INDEXED | Test name |
| full_name | VARCHAR(500) | | Full test name |
| test_type | VARCHAR(100) | NOT NULL, INDEXED | Antigen/Antibody/Panel/Drug Monitoring |
| cpt_code | VARCHAR(20) | | CPT billing code |
| description | TEXT | | Test description |

**Test Types:**
- Antigen Test
- Antibody Test
- Panel - General/Geographic
- Panel - Syndrome
- Panel - Pathogen
- Drug Monitoring

**Indexes:**
- `idx_test_name` on `test_name`
- `idx_test_type` on `test_type`

**Relationships:**
- One-to-Many with `test_specimen_types`
- One-to-Many with `order_tests`

---

### 5. Test_Specimen_Types
**Purpose:** Valid specimen types for each test with minimum volumes

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Primary key |
| test_id | INTEGER | FK, NOT NULL, INDEXED | Reference to tests |
| specimen_type | VARCHAR(50) | NOT NULL | Blood/Urine/Serum/etc. |
| minimum_volume_ml | FLOAT | | Minimum volume in mL |
| preferred_container | VARCHAR(100) | | Preferred tube/container type |
| notes | TEXT | | Special handling notes |

**Valid Specimen Types:**
- Blood
- Urine
- Serum
- Plasma
- CSF (Cerebrospinal Fluid)
- BAL (Bronchoalveolar Lavage)
- Tissue
- Swab
- Other

**Indexes:**
- `idx_test_specimen` on `(test_id, specimen_type)`

**Relationships:**
- Many-to-One with `tests`

---

### 6. Order_Tests
**Purpose:** Junction table linking orders to tests (many-to-many)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Primary key |
| order_id | INTEGER | FK, NOT NULL, INDEXED | Reference to orders |
| test_id | INTEGER | FK, NOT NULL, INDEXED | Reference to tests |
| specimen_type | VARCHAR(50) | | Actual specimen type used |
| specimen_volume_ml | FLOAT | | Actual volume collected |
| specimen_notes | TEXT | | Notes about this specimen |

**Indexes:**
- `idx_order_test` on `(order_id, test_id)`

**Relationships:**
- Many-to-One with `orders`
- Many-to-One with `tests`

---

### 7. Documents
**Purpose:** Scanned/uploaded requisition forms

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT (starts at 1001) | Primary key |
| order_id | INTEGER | FK, INDEXED | Reference to orders (after extraction) |
| filename | VARCHAR(255) | NOT NULL | Original filename |
| blob_name | VARCHAR(500) | | Azure Blob Storage path |
| upload_date | DATETIME | DEFAULT CURRENT_TIMESTAMP | Upload timestamp |
| uploaded_by | VARCHAR(100) | NOT NULL | User who uploaded |
| extracted_data | TEXT | | Encrypted JSON of extracted data |
| confidence_score | DECIMAL(5,4) | | AI extraction confidence (0-1) |
| status | VARCHAR(50) | DEFAULT 'pending' | Document processing status |
| reviewed_by | VARCHAR(100) | | Who reviewed |
| reviewed_at | DATETIME | | When reviewed |
| corrected_data | TEXT | | Encrypted JSON of corrections |
| submitted_to_lab | BOOLEAN | DEFAULT 0 | Submitted flag |
| lab_submission_date | DATETIME | | Submission timestamp |
| lab_confirmation_id | VARCHAR(100) | | Lab confirmation ID |
| reviewer_notes | TEXT | | Reviewer notes |
| document_type | VARCHAR(50) | | Document category |
| source | VARCHAR(50) | | scanner/email/upload/fax |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | Record creation |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | Last update |

**Indexes:**
- `idx_status` on `status`
- `idx_upload_date` on `upload_date`
- `idx_reviewed_at` on `reviewed_at`
- `idx_order_id` on `order_id`

**Relationships:**
- Many-to-One with `orders`

---

## Data Flow

### 1. Document Upload
```
User uploads PDF → Document record created (status: pending)
    ↓
Azure OpenAI extracts data → extracted_data JSON populated
    ↓
System creates/finds:
    - Facility (by name/address)
    - Patient (by owner name + pet name)
    - Order (links facility + patient)
    - OrderTests (links order + tests)
    ↓
Document.order_id = Order.id
```

### 2. Manual Order Creation
```
User enters data manually → No Document created initially
    ↓
System creates:
    - Facility (or finds existing)
    - Patient (or finds existing)
    - Order
    - OrderTests
```

### 3. Order Review & Approval
```
Reviewer opens order → Sees facility, patient, tests
    ↓
Makes corrections → Updates Order + OrderTests
    ↓
Approves → Order.status = 'approved'
    ↓
Submits to lab → Order.submitted_to_lab = 1
```

## Primary/Foreign Key Summary

**Primary Keys:**
- All tables use auto-incrementing integer `id` as PK
- `orders.id` and `documents.id` start from 1001

**Foreign Keys:**
- `patients.facility_id` → `facilities.id`
- `orders.facility_id` → `facilities.id`
- `orders.patient_id` → `patients.id`
- `order_tests.order_id` → `orders.id`
- `order_tests.test_id` → `tests.id`
- `test_specimen_types.test_id` → `tests.id`
- `documents.order_id` → `orders.id` (nullable)

## Indexes Summary

**For Searching:**
- Facility name, city/state
- Owner name, pet name
- Test name, test type
- Order status, collection date

**For Joins (Foreign Keys):**
- All FK columns are indexed automatically

**For Performance:**
- Composite indexes on frequently queried combinations
- Date indexes for filtering by date ranges

## Sample Data Relationships

```
Facility: "Happy Paws Veterinary Clinic"
    ↓
Patient: "Fluffy" (Owner: John Smith)
    ↓
Order #1001:
    - Vet: Dr. Jane Doe
    - Collection: 2025-01-18
    - Tests:
        • MVista Histoplasma Ag (Urine, 1.0mL)
        • CBC (Blood, 3.0mL)
    ↓
Document #1001: "Lab_Req_123.pdf"
```

## Migration Strategy

To create fresh database:
```bash
# Delete existing database
rm test.db

# Run database initialization
python -c "from app.database import init_db; init_db()"

# Seed test data (optional)
python seed_test_data.py
```
