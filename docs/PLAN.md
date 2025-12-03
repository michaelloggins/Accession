# Facility Matching & Data Enrichment Feature Plan

## Overview
This plan implements intelligent facility matching, patient lookup, and ordering physician tracking to improve data quality and reduce manual entry in the document review workflow.

---

## Phase 1: Database Schema Changes

### 1.1 New Table: `facility_physicians`
Track ordering physicians/veterinarians tied to facilities.

```sql
CREATE TABLE facility_physicians (
    id INTEGER PRIMARY KEY,
    facility_id INTEGER NOT NULL REFERENCES facilities(id),
    name VARCHAR(150) NOT NULL,              -- "Dr. John Smith, DVM"
    npi VARCHAR(20),                         -- National Provider Identifier (optional)
    specialty VARCHAR(100),                  -- "Internal Medicine", "Oncology", etc.
    phone VARCHAR(20),
    email VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(facility_id, name)                -- Prevent duplicates per facility
);
CREATE INDEX idx_facility_physicians_facility ON facility_physicians(facility_id);
CREATE INDEX idx_facility_physicians_name ON facility_physicians(name);
```

### 1.2 New Table: `facility_match_log`
Track facility matching attempts for auditing and improvement.

```sql
CREATE TABLE facility_match_log (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    extracted_name VARCHAR(255),
    extracted_address VARCHAR(255),
    extracted_fax VARCHAR(20),
    matched_facility_id INTEGER REFERENCES facilities(id),
    match_confidence DECIMAL(5,4),           -- 0.0000 to 1.0000
    match_method VARCHAR(50),                -- "exact", "fuzzy", "ai_assisted"
    alternatives_json TEXT,                  -- JSON array of other candidates
    user_confirmed BOOLEAN DEFAULT FALSE,
    confirmed_by VARCHAR(100),
    confirmed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_match_log_document ON facility_match_log(document_id);
```

### 1.3 Add Column to `documents` Table
```sql
ALTER TABLE documents ADD COLUMN matched_facility_id INTEGER REFERENCES facilities(id);
ALTER TABLE documents ADD COLUMN epr_status VARCHAR(50);  -- NULL, "pending", "created", "sent"
```

---

## Phase 2: Facility Matching Service

### 2.1 New File: `app/services/facility_matching_service.py`

**Matching Algorithm (Multi-tier approach):**

1. **Tier 1 - Exact Match (Confidence: 1.0)**
   - Match on `facility_id` if provided
   - Match on exact `facility_name` (case-insensitive)

2. **Tier 2 - Fuzzy Name Match (Confidence: 0.7-0.95)**
   - Use Levenshtein distance or similar algorithm
   - Normalize names (remove "Inc.", "LLC", "Clinic", "Hospital", etc.)
   - Match threshold: 85% similarity

3. **Tier 3 - Address + Fax Match (Confidence: 0.6-0.9)**
   - Match on fax number (exact, normalized)
   - Match on address components (street, city, state, zip)
   - Combine scores for multiple matches

4. **Tier 4 - AI-Assisted Match (Future Enhancement)**
   - Use Azure OpenAI to compare extracted text with facility records
   - Consider for cases where fuzzy matching fails

**Service Methods:**
```python
class FacilityMatchingService:
    def match_facility(
        self,
        facility_name: str,
        address: str = None,
        city: str = None,
        state: str = None,
        zipcode: str = None,
        fax: str = None,
        phone: str = None
    ) -> List[FacilityMatchResult]:
        """
        Returns list of potential matches with confidence scores.
        Sorted by confidence descending.
        """

    def get_best_match(self, ...) -> Optional[FacilityMatchResult]:
        """Returns single best match if confidence > threshold."""

    def confirm_match(
        self,
        document_id: int,
        facility_id: int,
        user: str
    ) -> None:
        """User confirms the correct facility match."""
```

**Return Type:**
```python
@dataclass
class FacilityMatchResult:
    facility: Facility
    confidence: float           # 0.0 to 1.0
    match_method: str           # "exact", "fuzzy_name", "fax", "address"
    match_details: str          # Human-readable explanation
    discrepancies: Dict[str, Tuple[str, str]]  # {field: (extracted, database)}
```

---

## Phase 3: Patient Lookup Service

### 3.1 New File: `app/services/patient_lookup_service.py`

**Matching Logic:**
1. Require `matched_facility_id` first (must know facility before patient lookup)
2. Match on `owner_last_name` (fuzzy, 90% threshold)
3. For veterinary: also match on `pet_name`
4. For human: match on `owner_first_name` + `owner_last_name`
5. If multiple matches, return all candidates

**Service Methods:**
```python
class PatientLookupService:
    def find_patients(
        self,
        facility_id: int,
        owner_last_name: str,
        pet_name: str = None,        # For veterinary
        owner_first_name: str = None  # For human
    ) -> List[PatientMatchResult]:
        """Find matching patients at the given facility."""

    def enrich_from_patient(
        self,
        patient: Patient
    ) -> Dict:
        """Returns species and date_of_birth from matched patient."""
```

---

## Phase 4: API Endpoints

### 4.1 New Facility Matching Endpoints

**File: `app/routers/facilities.py` (extend existing)**

```python
POST /api/facilities/match
Request:
{
    "facility_name": "Happy Paws Veterinary",
    "address": "123 Main St",
    "city": "Columbus",
    "state": "OH",
    "zipcode": "43215",
    "fax": "(614) 555-1234",
    "phone": "(614) 555-0000"
}
Response:
{
    "matches": [
        {
            "facility": { id, facility_id, facility_name, ... },
            "confidence": 0.92,
            "match_method": "fuzzy_name",
            "match_details": "Name 92% similar, same city/state",
            "discrepancies": {
                "address": ["123 Main St", "123 Main Street"],
                "phone": ["(614) 555-0000", "(614) 555-1111"]
            }
        },
        ...
    ],
    "best_match": { ... } or null,
    "has_high_confidence_match": true/false
}

POST /api/facilities/{facility_id}/confirm-match
Request:
{
    "document_id": 123
}
Response:
{
    "success": true,
    "message": "Facility match confirmed"
}

GET /api/facilities/{facility_id}/physicians
Response:
{
    "physicians": [
        { "id": 1, "name": "Dr. John Smith, DVM", "specialty": "Internal Medicine" },
        { "id": 2, "name": "Dr. Jane Doe, DVM", "specialty": "Oncology" }
    ]
}

POST /api/facilities/{facility_id}/physicians
Request:
{
    "name": "Dr. New Doctor, DVM",
    "specialty": "Surgery"
}
Response:
{
    "id": 3,
    "name": "Dr. New Doctor, DVM",
    ...
}
```

### 4.2 Patient Lookup Endpoints

**File: `app/routers/patients.py` (new or extend)**

```python
POST /api/patients/lookup
Request:
{
    "facility_id": 42,
    "owner_last_name": "Smith",
    "pet_name": "Buddy",           # Optional, for veterinary
    "owner_first_name": "John"     # Optional, for human
}
Response:
{
    "matches": [
        {
            "patient": { id, owner_last_name, pet_name, species, date_of_birth, ... },
            "confidence": 0.95,
            "match_details": "Exact match on owner + pet name"
        }
    ]
}
```

### 4.3 Document Re-process Endpoint

```python
POST /api/documents/{id}/reprocess-facility
Response:
{
    "matches": [...],
    "best_match": {...}
}
```

---

## Phase 5: UI Changes (review.html)

### 5.1 Facility Section Enhancements

**Layout Changes:**
```
┌─────────────────────────────────────────────────────────────────────┐
│ Ordering Facility                                    [🔄 Reprocess] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ Facility ID: [________] ← Auto-filled when matched                 │
│              (Small reprocess button here too)                      │
│                                                                     │
│ Facility Name: [Happy Paws Veterinary Clinic___________]           │
│                                                                     │
│ ┌─── MATCH FOUND (92% confidence) ─────────────────────────────┐   │
│ │ ○ Happy Paws Veterinary (ID: FAC-001)                        │   │
│ │   123 Main Street, Columbus, OH 43215                        │   │
│ │   Fax: (614) 555-1234                                        │   │
│ │                                                               │   │
│ │ ○ Happy Paws Animal Hospital (ID: FAC-042)                   │   │
│ │   456 Oak Ave, Columbus, OH 43210                            │   │
│ │   Fax: (614) 555-9999                                        │   │
│ │                                                               │   │
│ │ ○ None of these / Create New                                 │   │
│ │                                                               │   │
│ │ [Confirm Selection]                                          │   │
│ └───────────────────────────────────────────────────────────────┘   │
│                                                                     │
│ Address: [123 Main St_______] (123 Main Street)  ← RED if mismatch │
│ City: [Columbus___________]                                         │
│ State: [OH_] Zip: [43215___]                                       │
│ Phone: [(614) 555-0000____] ((614) 555-1111)     ← RED if mismatch │
│ Fax: [(614) 555-1234______]                                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Field Discrepancy Display:**
- If extracted value differs from database value:
  - Field border: RED
  - Database value shown in RED BOLD in parentheses to the right
  - Tooltip: "Extracted: X | Database: Y"

### 5.2 Ordering Physician Dropdown

**Location:** Order Information section

```
┌─────────────────────────────────────────────────────────────────────┐
│ Order Information                                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ Ordering Veterinarian: [Dr. John Smith, DVM        ▼]              │
│                        ┌────────────────────────────┐              │
│                        │ Dr. John Smith, DVM        │              │
│                        │ Dr. Jane Doe, DVM          │              │
│                        │ Dr. Bob Wilson, DVM        │              │
│                        │ ─────────────────────────  │              │
│                        │ + Add New Physician        │              │
│                        └────────────────────────────┘              │
│                                                                     │
│ Specimen Collection Date: [2024-01-15]                             │
│ ...                                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Dropdown populated from `GET /api/facilities/{id}/physicians`
- If extracted physician not in list, show at top with "(New)" badge
- "Add New Physician" option creates new record when form submitted
- Dropdown only enabled after facility is matched/confirmed

### 5.3 Patient Auto-fill

**When Facility Matched + Owner Last Name + Pet Name entered:**
1. Auto-trigger patient lookup
2. If single match found with high confidence:
   - Auto-fill Species dropdown
   - Auto-fill Date of Birth
   - Show green "Patient found" indicator
3. If multiple matches:
   - Show patient selection modal (similar to facility)
4. If no match:
   - Fields remain editable (new patient)

### 5.4 EPR Button (Human Patients Only)

**Location:** Bottom of form, only visible when:
- Species = "Human"
- Facility is matched/confirmed

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│ [Back to Dashboard]                          [Reject] [Save Draft] │
│                                                                     │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ EPR Integration                                    Status: N/A  │ │
│ │ [Create EPR]                                                    │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│                                              [Approve & Submit ✓]  │
└─────────────────────────────────────────────────────────────────────┘
```

**EPR Status Values:**
- `null` - Not applicable or not started
- `pending` - EPR creation initiated
- `created` - EPR created successfully
- `sent` - EPR sent to external system

---

## Phase 6: JavaScript Implementation

### 6.1 New Functions in review.html

```javascript
// Facility Matching
async function matchFacility() { ... }
async function reprocessFacilityMatch() { ... }
function displayFacilityMatches(matches) { ... }
function confirmFacilitySelection(facilityId) { ... }
function showFacilityDiscrepancies(facility, extractedData) { ... }

// Physician Dropdown
async function loadFacilityPhysicians(facilityId) { ... }
function setupPhysicianDropdown() { ... }
async function addNewPhysician(name) { ... }

// Patient Lookup
async function lookupPatient() { ... }
function autoFillPatientData(patient) { ... }

// EPR
async function createEPR() { ... }
function updateEPRStatus(status) { ... }
```

### 6.2 Event Triggers

| Trigger | Action |
|---------|--------|
| Page load (after extraction) | Auto-run `matchFacility()` |
| Click "Reprocess" button | Run `reprocessFacilityMatch()` |
| Select facility radio button | Enable "Confirm Selection" |
| Click "Confirm Selection" | Run `confirmFacilitySelection()`, load physicians |
| Facility confirmed + blur on pet_name | Run `lookupPatient()` |
| Species = "Human" | Show EPR button |
| Click "Create EPR" | Run `createEPR()` |

---

## Implementation Order

### Step 1: Database Migration
- Create `facility_physicians` table
- Create `facility_match_log` table
- Add `matched_facility_id` and `epr_status` to documents

### Step 2: Facility Matching Service
- Implement `FacilityMatchingService`
- Add fuzzy matching logic (use `rapidfuzz` library)
- Unit tests

### Step 3: Facility API Endpoints
- `POST /api/facilities/match`
- `POST /api/facilities/{id}/confirm-match`
- `GET /api/facilities/{id}/physicians`
- `POST /api/facilities/{id}/physicians`

### Step 4: Patient Lookup Service & API
- Implement `PatientLookupService`
- `POST /api/patients/lookup`

### Step 5: UI - Facility Matching
- Add reprocess button
- Add facility match display (radio buttons)
- Add discrepancy highlighting (red fields)
- Add confirm selection functionality

### Step 6: UI - Physician Dropdown
- Convert text field to searchable dropdown
- Add "Add New" functionality
- Integrate with facility selection

### Step 7: UI - Patient Auto-fill
- Add patient lookup trigger
- Auto-fill species and DOB
- Handle multiple match scenario

### Step 8: UI - EPR Button
- Add EPR section (human only)
- Implement placeholder `createEPR()` function
- Track EPR status

---

## Dependencies

### Python Packages to Add:
```
rapidfuzz>=3.0.0    # For fuzzy string matching
```

### No New Frontend Dependencies
- Using existing Bootstrap/vanilla JS patterns

---

## Testing Checklist

- [ ] Facility exact match works
- [ ] Facility fuzzy match works (85%+ threshold)
- [ ] Facility fax match works
- [ ] Multiple facility candidates displayed correctly
- [ ] Field discrepancies highlighted in red
- [ ] Database values shown in parentheses
- [ ] Physician dropdown loads after facility confirmed
- [ ] New physician can be added
- [ ] Patient lookup finds matching patient
- [ ] Species and DOB auto-filled from patient
- [ ] EPR button appears only for humans
- [ ] EPR status tracked correctly
- [ ] Reprocess button triggers new match

---

## Future Enhancements (Not in This Phase)

1. **AI-Assisted Matching** - Use Azure OpenAI for complex matching cases
2. **Address Validation** - Integrate USPS/Google Maps API
3. **Facility Merge Tool** - Admin UI to merge duplicate facilities
4. **Physician NPI Lookup** - Validate NPI numbers
5. **EPR Integration** - Actual EPR system integration (currently placeholder)
