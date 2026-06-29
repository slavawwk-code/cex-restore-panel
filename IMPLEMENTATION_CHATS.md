# Chats Management Implementation

## Overview

This document describes the implementation of Chats Management for Cex Restore Panel - the critical module that connects Accounts and Templates together.

## What Is Implemented

Complete Chats Management system enabling operators to:
- Create chats with 6-step wizard
- Assign accounts and templates to chats
- Configure per-chat cooldown times
- Manage chat status (active/paused/error)
- Change account, template, or cooldown per chat
- Soft disable chats when no longer needed

## Files Created/Modified

### New Files

1. **[app/services/chats.py](app/services/chats.py)**
   - Core business logic for chat management
   - 12 functions:
     - `create_chat()` - Create new chat configuration
     - `list_chats()` - Get chats (optionally filtered by account)
     - `get_chat()` - Get chat by ID
     - `get_chat_info()` - Get detailed chat information
     - `update_chat_account()` - Change assigned account
     - `update_chat_template()` - Change assigned template
     - `update_chat_cooldown()` - Change cooldown minutes
     - `update_chat_status()` - Change status (active/paused/error)
     - `disable_chat()` - Soft disable
     - `count_account_chats()` - Count chats per account
     - `count_template_chats()` - Count chats per template
     - `get_status_emoji()` - Get status emoji

2. **[app/handlers/chats.py](app/handlers/chats.py)**
   - All callback handlers and message handlers for chat management
   - Complex 6-step creation wizard using FSM
   - Handlers for:
     - Chat listing (`chats_view`)
     - Chat details (`chat_detail_*`)
     - 6-step creation wizard with validation at each step
     - Pause/resume chats
     - Change account/template/cooldown flows
     - Disable chats
     - View errors

3. **[IMPLEMENTATION_CHATS.md](IMPLEMENTATION_CHATS.md)**
   - This file, documenting the implementation

### Modified Files

1. **[app/database/models.py](app/database/models.py)**
   - Added `is_active: bool = True` field to Chat model
   - Supports soft disabling

2. **[app/states.py](app/states.py)**
   - Added `ChatCreation` FSM state group with 6 states
   - Added `ChatEdit` FSM state group with 4 states

3. **[app/keyboards/chats.py](app/keyboards/chats.py)**
   - Added 11 keyboard layouts for comprehensive chat management

4. **[app/handlers/__init__.py](app/handlers/__init__.py)**
   - Export chats_router

5. **[app/services/__init__.py](app/services/__init__.py)**
   - Export 12 chat service functions

6. **[app/keyboards/__init__.py](app/keyboards/__init__.py)**
   - Export 11 chat keyboard functions

7. **[main.py](main.py)**
   - Include chats_router in dispatcher

## Feature Breakdown

### 1. Chat Creation Wizard (6-Step FSM)

The most comprehensive feature - guides operators through complete chat setup:

**Step 1: Select Account**
- Shows all active accounts
- Validates account is active
- User selects account for this chat

**Step 2: Select Template**
- Shows all active templates
- Validates template exists
- User selects template to use

**Step 3: Enter Chat Username or ID**
- Accepts either format:
  - `@username` (validated with regex)
  - Negative chat ID (e.g., `-100123456789`)
- Length validation (3-50 chars)
- Basic format validation

**Step 4: Enter Display Name**
- User-friendly name for this chat
- Validation: 2-100 characters
- Whitespace trimmed

**Step 5: Enter Cooldown**
- Minutes between messages
- Validation: 1-1440 (24 hours max)
- Numeric validation with error handling

**Step 6: Confirmation**
- Show summary of:
  - Selected account
  - Selected template
  - Chat info (title, ID)
  - Cooldown setting
  - Status: Active
- Buttons: Confirm / Cancel

**Files**: 
- States: `app/states.py::ChatCreation`
- Handlers: `handlers/chats.py` (7 step handlers)
- Keyboards: 3 keyboard layouts

### 2. Chat Listing

View all active chats with relevant information:

**Display for each chat:**
- Status emoji (🟢 active, ⏸️ paused, ⚠️ error)
- Chat display name
- Account name
- Template name
- Cooldown in minutes
- Last send timestamp (or "Never sent")

**Clickable**: Each chat links to detail view

**Files**: `handlers/chats.py::callback_view_chats`, `keyboards/chats.py::get_chats_list_keyboard`

### 3. Chat Detail Screen

Full information view with action buttons:

**Displayed Information:**
- Status emoji and title
- Chat ID / username
- Assigned account
- Assigned template
- Cooldown setting (minutes)
- Creation date
- Last send time
- Last error (if exists)

**Action Buttons:**
- Pause (if active) / Resume (if paused)
- Change Account
- Change Template
- Change Cooldown
- View Error (if error state)
- Disable Chat
- Back

**Files**: `handlers/chats.py::callback_chat_detail`, `keyboards/chats.py::get_chat_detail_keyboard`

### 4. Change Operations

Three separate change flows (each with simple validation):

**Change Account:**
- Shows list of active accounts
- User selects new account
- Single click to confirm

**Change Template:**
- Shows list of active templates
- User selects new template
- Single click to confirm

**Change Cooldown:**
- Prompts for new cooldown minutes
- Validates 1-1440 range
- Confirms on valid input

**Files**: Multiple handlers for each change type

### 5. Status Management

Three chat statuses with transitions:

- **🟢 Active** - Chat sends messages on schedule
- **⏸️ Paused** - Scheduler skips this chat
- **⚠️ Error** - Last send had an error

**Operations:**
- Pause active chat
- Resume paused chat
- View error details

**Files**: `handlers/chats.py` (pause/resume/error handlers)

### 6. Soft Disabling

Chats have `is_active` field:
- Disabled chats not shown in lists
- Data preserved for audit
- One-way operation (cannot re-enable via UI currently)
- Foundation for future features

**Files**: `services/chats.py::disable_chat`

### 7. Navigation Flow

```
Main Menu
  ↓
Chats Menu (chats_list)
  ├→ Add Chat (chat_create) → 6-Step Wizard
  └→ View Chats (chats_view)
      ↓
    Chats List (clickable)
      ↓
    Chat Detail (chat_detail_*)
      ├→ Pause/Resume
      ├→ Change Account (select_account → confirm)
      ├→ Change Template (select_template → confirm)
      ├→ Change Cooldown (enter → validate → update)
      ├→ View Error
      ├→ Disable Chat
      └→ Back to List
        ↓
      Back to Menu
        ↓
      Back to Main
```

## Database Integration

### Model Changes
- **Chat** model updated with:
  - All fields as specified in requirements
  - `is_active` field for soft delete
  - Relationships to AdvertisingAccount and Template

### Queries Implemented
- Create: `create_chat()`
- Read: `list_chats()`, `get_chat()`, `get_chat_info()`
- Update: `update_chat_account()`, `update_chat_template()`, `update_chat_cooldown()`, `update_chat_status()`
- Disable: `disable_chat()`
- Count: `count_account_chats()`, `count_template_chats()`

### Foreign Keys
- Chat.advertising_account_id → AdvertisingAccount.id
- Chat.assigned_template_id → Template.id

## Input Validation

### Chat Username/ID
- Format 1: `@username`
  - Must start with @
  - 3-32 chars
  - Letters, numbers, underscores only
  - Validated with regex: `^@[a-zA-Z0-9_]{3,32}$`
- Format 2: Numeric chat ID
  - Can be negative (e.g., -100123456789)
  - Digit-only validation
- Overall length: 3-50 characters

### Display Name
- Length: 2-100 characters
- Whitespace: Automatically trimmed
- Special characters: Allowed

### Cooldown
- Range: 1-1440 minutes (24 hours max)
- Integer validation
- Error message on non-numeric input
- Error message on out-of-range

### Account/Template Selection
- Validates existence in database
- Only shows active accounts/templates
- Blocks if none available

## Error Handling

### Input Validation
- Username format and length validation
- Display name length validation
- Cooldown range and type validation
- Database validation (account/template existence)

### Exception Handling
- Chat not found errors
- Invalid account/template errors
- Database operation errors (logged, user-friendly messages)

### Logging
- All chat operations logged (create, update, disable)
- Error messages stored in database
- Service functions use Python `logging` module

**Files**: `services/chats.py` (all functions include logging)

## Type Hints

All functions include proper type hints:
```python
def create_chat(
    session: Session,
    advertising_account_id: int,
    template_id: int,
    title: str,
    username_or_chat_id: str,
    cooldown_minutes: int,
) -> Chat:
```

## FSM States

### ChatCreation (6 states)
1. `selecting_account` - Choose account
2. `selecting_template` - Choose template
3. `entering_username` - Enter chat ID/username
4. `entering_title` - Enter display name
5. `entering_cooldown` - Enter cooldown minutes
6. `confirmation` - Review and confirm

### ChatEdit (4 states)
1. `choosing_field` - Choose what to edit (not yet used)
2. `changing_account` - Select new account
3. `changing_template` - Select new template
4. `changing_cooldown` - Enter new cooldown

## Code Statistics

- **Service functions**: 12
- **Handler functions**: 15+ callback/message handlers
- **Keyboard layouts**: 11
- **FSM states**: 10 (6 creation + 4 edit)
- **Validation rules**: 12+
- **Lines of code**: ~700 (handlers) + ~180 (services)

## Code Quality

- ✅ Type hints throughout
- ✅ Proper logging on all operations
- ✅ Input validation at every step
- ✅ Error handling with user-friendly messages
- ✅ Modular design (service layer separate)
- ✅ DRY principle (no code duplication)
- ✅ Same style as Accounts/Templates

## What's NOT Implemented (Intentional)

1. **Telethon Integration** - Not yet (phase 2)
2. **Actual Message Sending** - Not yet (phase 2)
3. **Scheduler Integration** - Not yet (phase 2)
4. **Enable Disabled Chats** - Can disable but not re-enable via UI
5. **Bulk Operations** - Cannot pause/enable multiple chats at once
6. **Chat Search/Filter** - Only filter by account
7. **Export/Import** - No chat configuration export

## Integration Points

### With Accounts
- Each chat references one AdvertisingAccount
- Only shows active accounts in creation/change
- Counts chats per account for account detail view

### With Templates
- Each chat references one Template
- Only shows active templates in creation/change
- Counts chats per template

### With Scheduler (Future)
- Scheduler will iterate chats
- Will fetch template text
- Will use account to send via Telethon
- Will respect chat status and cooldown
- Will update last_sent_at on success
- Will update last_error on failure

## Performance Considerations

- Database queries properly filtered by is_active
- Queries use ID lookup (indexed) for detail views
- List queries can filter by account_id
- No N+1 queries (relationships lazy-loaded appropriately)
- Emoji function for status display

## Security Considerations

- ✅ No SQL injection (using SQLAlchemy ORM)
- ✅ Input validation on all user inputs
- ✅ Chat IDs and usernames validated before storage
- ⚠️ No rate limiting (add if needed)

## Testing Coverage

See [TESTING.md](TESTING.md) for 50+ test cases covering:
- 6-step creation wizard validation
- Each step's input validation
- Account and template selection
- Status changes (pause/resume)
- Change operations (account, template, cooldown)
- Error viewing
- Chat disabling
- Navigation and back buttons
- Edge cases (boundary values, special characters)

## Next Steps - What Remains Before Sending

To connect Telethon and begin sending messages, you need:

1. **Telethon Authentication**
   - Handle phone login
   - Process verification codes
   - Store session files securely
   - Manage client lifecycle

2. **Scheduler Enhancement**
   - Iterate through active chats
   - Fetch template text
   - Connect Telethon client
   - Send actual message
   - Handle errors
   - Update last_sent_at
   - Create logs

3. **Logs Module**
   - Query send logs
   - Filter by account/chat/status
   - Display in Telegram UI

4. **Error Recovery**
   - Retry logic for failed sends
   - Exponential backoff
   - Error state management

The Chat Management module is **production-ready** for configuring chats.
All that's needed is connecting it to actual Telegram sending.

## Quick Reference

### Service Functions
```python
create_chat()              # Create new chat
list_chats()              # List active chats
get_chat()                # Get chat by ID
get_chat_info()           # Get detailed info
update_chat_account()     # Change account
update_chat_template()    # Change template
update_chat_cooldown()    # Change cooldown
update_chat_status()      # Change status
disable_chat()            # Soft delete
count_account_chats()     # Count per account
count_template_chats()    # Count per template
get_status_emoji()        # Get emoji for status
```

### Callback Data Prefixes
- `chats_list` - Chats menu
- `chats_view` - View chats list
- `chat_create` - Start creation wizard
- `chat_detail_*` - Chat detail view
- `chat_pause_*` - Pause chat
- `chat_resume_*` - Resume chat
- `chat_change_account_*` - Change account
- `chat_change_template_*` - Change template
- `chat_change_cooldown_*` - Change cooldown
- `chat_error_*` - View error
- `chat_disable_*` - Disable chat

### FSM States for Chats
```python
ChatCreation.selecting_account
ChatCreation.selecting_template
ChatCreation.entering_username
ChatCreation.entering_title
ChatCreation.entering_cooldown
ChatCreation.confirmation

ChatEdit.choosing_field
ChatEdit.changing_account
ChatEdit.changing_template
ChatEdit.changing_cooldown
```
