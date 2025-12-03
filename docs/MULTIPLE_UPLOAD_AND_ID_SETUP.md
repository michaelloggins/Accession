# Multiple File Upload & Custom Document ID Setup

## Feature 1: Multiple File Upload ✅

### What Changed

**Frontend (`app/templates/dashboard.html`):**
- File input now accepts `multiple` attribute
- User can select multiple files at once using Ctrl+Click or Shift+Click
- Updated help text to indicate multiple file support

**Upload Logic:**
- Files are uploaded sequentially (one after another) to avoid overwhelming the server
- Progress indicator shows "Processing X of Y..."
- Summary toast notification shows total success/fail count
- Individual error messages displayed for failed uploads
- All successful uploads are added to the queue immediately

### How to Use

1. **Select Multiple Files:**
   - Click the file input field
   - Hold `Ctrl` (Windows/Linux) or `Cmd` (Mac) and click multiple files
   - Or use `Shift` to select a range of files

2. **Upload:**
   - Click "Upload Document" button
   - Watch progress indicator show "Processing 1 of 3...", "Processing 2 of 3...", etc.
   - See summary notification: "Successfully uploaded 3 file(s)"

3. **Review Results:**
   - All successfully uploaded documents appear in the queue
   - Failed uploads show individual error messages
   - Queue auto-refreshes after all uploads complete

### Example Scenarios

**Scenario 1: All files succeed**
```
Upload 5 PDFs → All process successfully →
Toast: "Successfully uploaded 5 file(s)"
```

**Scenario 2: Some files fail**
```
Upload 3 files → 2 succeed, 1 fails →
Toast: "Successfully uploaded 2 file(s), 1 failed"
Toast: "Invalid_File.txt: Unsupported file type..."
```

**Scenario 3: All files fail**
```
Upload 2 files → Both fail →
Toast: "All 2 upload(s) failed"
Individual error toasts for each file
```

---

## Feature 2: Document ID Starting from 1001 ✅

### What Changed

**Automatic Setup (`app/database.py`):**
- Modified `init_db()` function to automatically set starting ID to 1001
- Only applies to **new/empty** databases
- Existing databases with data are not affected

**Manual Reset Tool (`reset_document_id.py`):**
- Standalone script to manually reset the ID sequence
- Includes safety checks for existing data
- Can be run anytime to adjust the sequence

### How It Works

#### For New Installations

When you run the application for the first time:
1. `init_db()` creates all tables
2. Checks if `documents` table is empty
3. If empty, sets sqlite_sequence to 1000
4. Next document inserted will have ID = 1001

**Example:**
```python
# Database initialized
python main.py  # Or however you start the app

# First document uploaded → ID = 1001
# Second document uploaded → ID = 1002
# Third document uploaded → ID = 1003
```

#### For Existing Databases

If you already have documents and want to reset the sequence:

**Option 1: Use the Reset Script**
```bash
python reset_document_id.py
```

**Interactive Prompts:**
```
Document ID Sequence Reset Tool
==================================================

Current state:
Next document ID will be: 15

This will set the next document ID to 1001
Continue? (y/n): y

Warning: Highest existing document ID is 14, which is >= 1001
Do you want to continue? This will set next ID to 15 (y/n): n
Operation cancelled.
```

**Option 2: Manual SQL (Advanced)**
```bash
# For SQLite
sqlite3 test.db
```

```sql
-- Check current sequence
SELECT * FROM sqlite_sequence WHERE name = 'documents';

-- Update to start from 1001
UPDATE sqlite_sequence SET seq = 1000 WHERE name = 'documents';

-- Verify
SELECT * FROM sqlite_sequence WHERE name = 'documents';
```

### Safety Features

1. **Existing Data Check:**
   - Script checks for existing documents
   - Warns if setting ID would conflict with existing IDs
   - Prevents data integrity issues

2. **Confirmation Prompts:**
   - User must confirm before making changes
   - Shows current state before modification
   - Allows cancellation at any point

3. **Automatic on New Databases:**
   - No manual intervention needed for fresh installs
   - Consistent ID numbering from the start

### When to Use Manual Reset

**Use the reset script when:**
- ✅ Starting fresh (deleted test data, want clean IDs)
- ✅ Migrating from another system (want to avoid ID conflicts)
- ✅ Testing/Development (want predictable IDs like 1001, 1002, etc.)

**DON'T use if:**
- ❌ Production system with active data
- ❌ IDs are referenced in other systems
- ❌ Unsure about current database state

### Database Type Support

**SQLite (Current):**
- Fully supported
- Uses `sqlite_sequence` table
- Automatic setup works out of the box

**Future Support (PostgreSQL, SQL Server):**
```python
# Will need different approach:
# PostgreSQL: ALTER SEQUENCE documents_id_seq RESTART WITH 1001;
# SQL Server: DBCC CHECKIDENT ('documents', RESEED, 1000);
```

---

## Files Modified/Created

### Modified Files:
1. `app/templates/dashboard.html` - Multiple file upload UI and logic
2. `app/database.py` - Automatic ID sequence initialization

### New Files:
1. `reset_document_id.py` - Manual ID reset utility
2. `MULTIPLE_UPLOAD_AND_ID_SETUP.md` - This documentation

---

## Testing the Features

### Test Multiple Upload:

1. **Test 1: Upload 3 valid PDFs**
   - Select 3 PDF files
   - Click Upload
   - Verify all 3 appear in queue with IDs 1001, 1002, 1003

2. **Test 2: Mix valid and invalid files**
   - Select 2 PDFs and 1 TXT file
   - Verify: 2 succeed, 1 fails with error message

3. **Test 3: Large batch**
   - Select 10+ files
   - Verify progress indicator updates correctly
   - Verify all successful files appear in queue

### Test Document ID:

**Fresh Database:**
```bash
# Delete existing database
rm test.db

# Start application
python main.py

# Upload first document
# Check: Document ID should be 1001
```

**Existing Database:**
```bash
# Run reset script
python reset_document_id.py

# Follow prompts
# Upload new document
# Verify ID starts from 1001 (or next available)
```

---

## Troubleshooting

### Multiple Upload Issues

**Problem:** "Upload error: Network error"
- **Solution:** Server might be overwhelmed. Files upload sequentially to prevent this, but very large files might timeout.

**Problem:** Some files succeed, some fail silently
- **Solution:** Check browser console (F12) for errors. File size might exceed 25MB limit.

### Document ID Issues

**Problem:** IDs still starting from 1 after running init_db()
- **Solution:** Database already has documents. Use `reset_document_id.py` instead.

**Problem:** Reset script shows "Error: no such table: sqlite_sequence"
- **Solution:** No documents have been inserted yet. Upload one document first to create the sequence.

**Problem:** "Next document ID will be: None"
- **Solution:** Normal for brand new database. Sequence will be created on first insert at 1001.

---

## Future Enhancements

### Multiple Upload:
- [ ] Parallel uploads (multiple files at once)
- [ ] Drag-and-drop support
- [ ] Upload progress per file (not just count)
- [ ] Pause/resume uploads
- [ ] Retry failed uploads

### Document ID:
- [ ] Support for PostgreSQL and SQL Server
- [ ] Configurable starting ID (environment variable)
- [ ] Auto-increment step size (1001, 2001, 3001, etc.)
- [ ] ID format customization (DOC-1001, ORD-1001, etc.)
