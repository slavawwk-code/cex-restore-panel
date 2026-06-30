# Руководство по тестированию

Документ описывает ручную проверку интерфейса в Telegram. Старые подробные
сценарии ниже могут сохранять прежние английские подписи, но фактический
интерфейс полностью русифицирован.

## Setup

1. **Install dependencies**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   python -m pip install -r requirements.txt
   python -m pip check
   python -m unittest discover -v
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   - Set `BOT_TOKEN` to your Telegram bot token
   - Set `OWNER_TELEGRAM_ID` to your Telegram ID
   - Keep `DRY_RUN=True` for testing

3. **Initialize database**
   ```bash
   python -c "from app.database.models import init_db; init_db()"
   ```

4. **Run the bot**
   ```bash
   python main.py
   ```
   A successful startup initializes the database, starts the scheduler, and
   logs `Starting polling...`. Stop it with `Ctrl+C` after the smoke test.

## Первичная проверка в Telegram

1. Отправить `/start` и убедиться, что меню состоит из четырёх симметричных
   рядов по две кнопки.
2. Открыть каждый раздел и проверить, что операторские тексты и кнопки на
   русском языке.
3. Открыть аккаунт → **Прокси** и сохранить тестовый SOCKS5/SOCKS4/HTTP proxy.
   Основной сценарий: **Настроить прокси → Вставить строкой → вставить →
   Сохранить → Проверить**. Отдельно проверить ручной режим.
   Для строки без схемы интерфейс должен показать «Определить автоматически» и
   проверить SOCKS5 → HTTP → SOCKS4. Для явной схемы проверяется только её тип;
   `https://` использует HTTP CONNECT.
4. Убедиться, что пароль не показывается в подтверждении, карточке и логах.
5. Нажать **🟢 Быстрая проверка**, затем **🔍 Полная диагностика**. Для рабочего
   proxy ожидается карточка с задержкой; для нерабочего — понятные ошибки по
   проверенным типам.
6. Нажать **Подключить Telegram** → **Запросить код**. Проверить, что бот
   показывает выбранный Telegram канал доставки кода.
7. Ввести код, при необходимости облачный пароль 2FA, затем проверить статус
   сессии в карточке аккаунта.
8. Сохранить `DRY_RUN=True` и пройти симулятор/валидатор без реальной отправки.

Код Telegram обычно приходит служебным сообщением в официальное приложение,
а не по SMS. Повторные запросы подряд могут вызвать FloodWait, поэтому между
попытками нужно выдерживать указанную Telegram паузу.

## Testing Accounts Management Flow

### 1. Main Menu Navigation
- Open Telegram and find your bot
- Send `/start`
- You should see the main menu with options including "📊 Accounts"
- Click "📊 Accounts"

**Expected**: You should see the accounts menu with:
- ➕ Add Account
- 📋 View Accounts
- ⬅️ Back

### 2. View Empty Accounts List
- Click "📋 View Accounts"

**Expected**: You should see:
- "📊 Accounts"
- "No accounts yet."
- Message: "Create one to get started."
- Option to add a new account

### 3. Create New Account (Basic Flow)
- Click "➕ Add Account"
- You should be prompted: "What is the display name for this account?"

**Step 3a: Display Name**
- Enter: `Test Account 1`

**Expected**:
- ✅ Display name: Test Account 1
- Next prompt: "What is the phone number for this account?"

**Step 3b: Phone Number**
- Enter: `+1234567890`

**Expected**:
- ✅ Phone: +1234567890
- Next prompt: "What should be the session name?"

**Step 3c: Session Name**
- Enter: `test_session_1`

**Expected**:
- Confirmation screen showing:
  - Display Name: Test Account 1
  - Phone Number: +1234567890
  - Session Name: test_session_1
- Buttons: ✅ Confirm, ❌ Cancel

**Step 3d: Confirmation**
- Click ✅ Confirm

**Expected**:
- ✅ Account Created!
- Display: "Test Account 1"
- Phone: +1234567890
- Status: Warming
- Message: "The account is ready for setup..."

### 4. View Accounts List
- Click "📋 View Accounts"

**Expected**:
- Should see your account with:
  - 🔥 Test Account 1
  - 📱 +1234567890
  - 💬 0 chats

### 5. Account Detail View
- Click on "Test Account 1" account

**Expected**:
- Account Details screen showing:
  - 🔥 Test Account 1
  - 📱 Phone: +1234567890
  - 💬 Assigned Chats: 0
  - 📅 Created: [current date/time]
- Buttons:
  - ✅ Activate
  - 🔄 Set to Warming
  - 💬 View Chats
  - 🚫 Disable Account
  - ⬅️ Back

### 6. Account Status Changes
- Click "✅ Activate"

**Expected**:
- Notification: ✅ Account activated
- Status should change from 🔥 to 🟢
- Button should now be "⏸️ Pause" instead of "✅ Activate"

**Test pause:**
- Click "⏸️ Pause"

**Expected**:
- Notification: ✅ Account paused
- Status should change back to ⏸️
- Button should now be "▶️ Resume"

**Test resume:**
- Click "▶️ Resume"

**Expected**:
- Notification: ✅ Account resumed
- Status back to 🟢

**Test warming:**
- Click "🔄 Set to Warming"

**Expected**:
- Account status changes to 🔥
- Button changes back to "✅ Activate"

### 7. View Empty Chats
- While in account detail, click "💬 View Chats"

**Expected**:
- Shows: "💬 Chats for Test Account 1"
- "No chats assigned yet."

### 8. Disable Account
- From account detail, click "🚫 Disable Account"

**Expected**:
- Notification: ✅ Account disabled
- Status changes to 🚫
- The "🚫 Disable Account" button disappears (since it's already disabled)

### 9. Create Multiple Accounts
Repeat the creation flow with different phone numbers to test listing:
- `Test Account 2` with `+9876543210`
- `Test Account 3` with `+1111111111`

Then view the accounts list - should show all three with their statuses.

## Input Validation Tests

### Invalid Display Name
- Try to create an account with:
  - Empty name: Should reject with "must be at least 2 characters"
  - Name with 1 character: Should reject
  - Name with 51 characters: Should reject with "must be 50 characters or less"

### Invalid Phone Number
- Try phone numbers:
  - Empty: Should reject with "cannot be empty"
  - Too short (1 char): Should reject with "must be between 5 and 20 characters"
  - Too long (21+ chars): Should reject
  - Duplicate phone number: Should reject with "already exists"

### Invalid Session Name
- Try session names:
  - Name with spaces: Should be converted to underscores and lowercase
  - Name with special chars: Should reject with "can only contain letters, numbers, and underscores"
  - Name with 1 character: Should reject with "must be at least 2 characters"

## Database Verification

To verify accounts are properly saved:

```python
from app.database import get_session
from app.services import list_accounts

session = get_session()
accounts = list_accounts(session)
for account in accounts:
    print(f"ID: {account.id}, Name: {account.display_name}, Status: {account.status}")
session.close()
```

## Navigation Tests

Verify back buttons work correctly:
1. Main Menu → Accounts Menu → Accounts List → Account Detail → Back to List → Back to Menu → Back to Main
2. All back buttons should work without errors

## DRY_RUN Mode

With `DRY_RUN=True`, the scheduler logs actions without sending actual messages. This is already enabled for testing.

## Edge Cases to Test

1. **Rapid status changes**: Quickly pause/resume an account multiple times
2. **Long account names**: Try display names that are exactly 50 characters
3. **International phone numbers**: Test with various international formats (+44, +86, etc.)
4. **Session name edge cases**: `_test_session_`, numbers-only sessions, very long names

## Known Limitations (Not Implemented Yet)

- ❌ Telethon authentication (will be added later)
- ❌ Actual message sending (scheduler is in DRY_RUN mode)
- ❌ Account editing (only status can be changed)
- ❌ Account deletion (only soft disable is available)
- ❌ Last error viewing (infrastructure in place, no real errors yet)

## Troubleshooting

**Bot doesn't respond**:
- Check `BOT_TOKEN` is correct in `.env`
- Make sure you sent `/start` first
- Check console logs for errors

**Database errors**:
- Delete `data/cex_restore.db` and reinitialize: `python -c "from app.database.models import init_db; init_db()"`
- Check that `data/` directory exists

**FSM issues during account creation**:
- Make sure you're replying to bot messages, not sending separate messages in a different chat
- If stuck in an FSM state, send `/start` again to reset

---

# Testing Guide - Templates Management

This document explains how to test the Templates Management functionality.

## Prerequisites

Same as Accounts Management. Run `/start` and proceed.

## Testing Templates Management Flow

### 1. Main Menu Navigation
- From main menu, click "📝 Templates"

**Expected**: You should see the templates menu with:
- ➕ Create Template
- 📋 View Templates
- ⬅️ Back

### 2. View Empty Templates List
- Click "📋 View Templates"

**Expected**: You should see:
- "📝 Templates"
- "No templates yet."
- Message: "Create one to get started."

### 3. Create New Template (Basic Flow)
- Click "➕ Create Template"
- You should be prompted: "What should be the template name?"

**Step 3a: Template Name**
- Enter: `Welcome Template`

**Expected**:
- ✅ Template name: Welcome Template
- Next prompt: "What should be the template text?"

**Step 3b: Template Text**
- Enter: `Welcome to our service! We help recover your crypto exchange accounts. Contact us for assistance.`

**Expected**:
- Confirmation screen showing:
  - Name: Welcome Template
  - Text preview: Welcome to our service! We help recover...
- Buttons: ✅ Confirm, ❌ Cancel

**Step 3c: Confirmation**
- Click ✅ Confirm

**Expected**:
- ✅ Template Created!
- Display: "Welcome Template"
- Message: "Ready to use"

### 4. View Templates List
- Click "📋 View Templates"

**Expected**:
- Should see your template:
  - 📝 Welcome Template
  - Preview text (first 50 chars)
  - 📅 [current date]

### 5. Template Detail View
- Click on "Welcome Template"

**Expected**:
- Template Details screen showing:
  - 📝 Template Details
  - Name: Welcome Template
  - Text: [full text]
  - 📅 Created: [date/time]
  - 📝 Updated: [date/time]
- Buttons:
  - ✏️ Edit Name
  - ✏️ Edit Text
  - 🚫 Disable Template
  - ⬅️ Back

### 6. Edit Template Name
- From template detail, click "✏️ Edit Name"

**Expected**:
- Prompt: "What should be the new name?"
- Shows current name and length requirements

**Step 6a: Enter New Name**
- Enter: `Welcome Message`

**Expected**:
- Confirmation: "Old name: Welcome Template"
- "New name: Welcome Message"
- Buttons: ✅ Save Changes, ❌ Cancel

**Step 6b: Confirm**
- Click ✅ Save Changes

**Expected**:
- ✅ Success notification
- Template detail updates with new name
- Updated timestamp changes

### 7. Edit Template Text
- From template detail, click "✏️ Edit Text"

**Expected**:
- Prompt: "What should be the new text?"
- Shows current text and length requirements

**Step 7a: Enter New Text**
- Enter: `Welcome! We specialize in account recovery. DM us for help.`

**Expected**:
- Confirmation: "New text: Welcome! We specialize..."
- Buttons: ✅ Save Changes, ❌ Cancel

**Step 7b: Confirm**
- Click ✅ Save Changes

**Expected**:
- ✅ Success notification
- Template detail shows new text
- Updated timestamp changes

### 8. Create Multiple Templates
Create these additional templates to test listing:
- Name: `Recovery Guide` → Text: `Steps to recover your account: 1. Verify email 2. Check backup 3. Contact support`
- Name: `Contact Info` → Text: `Contact us at support@cexrestore.com or message on Telegram for 24/7 assistance`
- Name: `Promotion` → Text: `Have you lost access to your exchange account? We help you recover it safely and quickly!`

Then view the templates list - should show all three:
- 📝 Welcome Message
- 📝 Recovery Guide
- 📝 Contact Info
- 📝 Promotion

### 9. Disable Template
- Open any template (e.g., Contact Info)
- Click "🚫 Disable Template"

**Expected**:
- ✅ Template disabled notification
- Template detail now shows "⚠️ This template is disabled"
- Button changes to "✅ Enable Template"

### 10. Enable Disabled Template
- From the disabled template detail, click "✅ Enable Template"

**Expected**:
- ✅ Template enabled notification
- "⚠️ This template is disabled" message disappears
- Button changes back to "🚫 Disable Template"

## Input Validation Tests

### Invalid Template Name
- Try to create/edit templates with:
  - Empty name: Should reject with "must be at least 2 characters"
  - Name with 1 character: Should reject
  - Name with 65 characters: Should reject with "must be 64 characters or less"
  - Duplicate name (e.g., "Welcome Message" again): Should reject with "already exists"
  - Same name as current: Should reject when editing

### Invalid Template Text
- Try to create/edit templates with:
  - Empty text: Should reject with "must be at least 5 characters"
  - Text with 1-4 characters: Should reject
  - Text with 4097+ characters: Should reject with "must be 4096 characters or less"
  - Same text as current: Should reject when editing (e.g., "cannot be same as old text")

### Whitespace Handling
- Try creating template with:
  - Name: `  Welcome  ` → Should be trimmed to `Welcome`
  - Text: `  Some text  \n  more text  ` → Should be trimmed

## Database Verification

To verify templates are properly saved:

```python
from app.database import get_session
from app.services import list_templates

session = get_session()
templates = list_templates(session, include_inactive=False)
for template in templates:
    print(f"ID: {template.id}, Name: {template.name}, Active: {template.is_active}")
session.close()
```

To check disabled templates:

```python
from app.database import get_session
from app.services import list_templates

session = get_session()
all_templates = list_templates(session, include_inactive=True)
disabled = [t for t in all_templates if not t.is_active]
print(f"Disabled templates: {len(disabled)}")
session.close()
```

## Navigation Tests

Verify back buttons work correctly for templates:
1. Main Menu → Templates Menu → Templates List → Template Detail → Back to List → Back to Menu → Back to Main
2. Edit flows: Template Detail → Edit Name → Confirm → back to Detail
3. Edit flows: Template Detail → Edit Text → Confirm → back to Detail
4. All back buttons should work without errors

## Edge Cases to Test

1. **Long template names**: Try name with exactly 64 characters
2. **Long template text**: Try text with exactly 4096 characters
3. **Special characters**: Use emojis, unicode, special chars in text
4. **Multiple line breaks**: Text with `\n` characters
5. **Very short text**: Text with exactly 5 characters
6. **Rapid enable/disable**: Quickly toggle a template's active state
7. **Name collision attempts**: Try creating two templates with same name

## Integrated Tests

### Accounts + Templates (Future)
Once Chats Management is implemented:
- Create template
- Create account
- Create chat for account
- Assign template to chat
- Verify chat shows template name

### Combined Flow
1. Create account: "Test Account"
2. Create templates: "Template 1", "Template 2"
3. Add chats to account (future test)
4. Assign different templates to different chats (future test)
5. Verify scheduler respects assigned templates (future test)

## Known Limitations (Not Implemented Yet)

- ❌ Template variables (e.g., {name}, {email})
- ❌ Template categories/folders
- ❌ Template templates/duplication
- ❌ Template export/import
- ❌ HTML/markdown formatting
- ❌ Template scheduling (send only on specific days)

## Troubleshooting

**Template not appearing in list after creation**:
- Check it was created: Query database as shown above
- Verify `is_active=True`
- Try refreshing list by going back to menu and re-entering

**Cannot edit template name to an existing name**:
- This is expected validation - template names must be unique
- The system rejects duplicate names

**Edit confirmation stuck**:
- If you're in an edit FSM state and want out, send `/start`
- This resets all FSM states

**Text preview cuts off strangely**:
- This is normal - preview limited to 50-100 characters
- Full text shown in detail view

**Old timestamp not updating after edit**:
- Timestamp updates in detail view but may need refresh
- Try clicking back and reopening template

---

# Testing Guide - Chats Management

This document explains how to test the Chats Management functionality.

## Prerequisites

Same as Accounts and Templates. Create at least:
- 1 active Advertising Account
- 2 active Templates

## Testing Chats Management Flow

### 1. Main Menu Navigation
- From main menu, click "💬 Chats"

**Expected**: You should see the chats menu with:
- ➕ Add Chat
- 📋 View Chats
- ⬅️ Back

### 2. View Empty Chats List
- Click "📋 View Chats"

**Expected**: You should see:
- "💬 Chats"
- "No chats yet."
- Message: "Create one to get started."

### 3. Create Chat - Complete Wizard Flow

This is the main feature. Test the 6-step wizard.

**Step 1: Select Account**
- Click "➕ Add Chat"
- You should see list of active accounts
- Click on your account (e.g., "Test Account 1")

**Expected**:
- ✅ Account selected
- Prompt: "Step 2: Select Template"
- Shows list of available templates

**Step 2: Select Template**
- Click on a template (e.g., "Welcome Message")

**Expected**:
- ✅ Template selected
- Prompt: "Step 3: Chat Username or ID"
- Instructions for both formats

**Step 3: Enter Chat Username or ID**
- Try valid format 1: `@groupname`

**Expected**:
- ✅ Accepted
- Prompt: "Step 4: Chat Display Name"

**Step 4: Enter Display Name**
- Enter: `MEXC Recovery Group`

**Expected**:
- ✅ Display name: MEXC Recovery Group
- Prompt: "Step 5: Cooldown (minutes)"

**Step 5: Enter Cooldown**
- Enter: `30`

**Expected**:
- ✅ Cooldown: 30
- Confirmation screen with all settings
- Shows: Account, Template, Chat, Cooldown, Status

**Step 6: Confirmation**
- Click ✅ Confirm

**Expected**:
- ✅ Chat Created!
- Shows chat details
- Message: "The chat is ready and will receive messages on schedule"

### 4. View Chats List
- Click "📋 View Chats"

**Expected**:
- Should see your chat:
  - 🟢 MEXC Recovery Group
  - 📱 Test Account 1 • 📝 Welcome Message
  - ⏱️ 30m • 📅 [current date/time]

### 5. Chat Detail View
- Click on "MEXC Recovery Group"

**Expected**:
- Chat Details screen showing:
  - 🟢 MEXC Recovery Group
  - Chat ID: @groupname
  - 📱 Account: Test Account 1
  - 📝 Template: Welcome Message
  - ⏱️ Cooldown: 30 minutes
  - 📅 Created: [date/time]
  - 📤 Never sent
- Buttons:
  - ⏸️ Pause
  - 🔄 Change Account
  - 📝 Change Template
  - ⏱️ Change Cooldown
  - 🚫 Disable Chat
  - ⬅️ Back

### 6. Pause and Resume Chat
- From detail view, click "⏸️ Pause"

**Expected**:
- ✅ Chat paused notification
- Status changes from 🟢 to ⏸️
- Button changes to "▶️ Resume"

**Resume:**
- Click "▶️ Resume"

**Expected**:
- ✅ Chat resumed notification
- Status back to 🟢
- Button changes back to "⏸️ Pause"

### 7. Change Account
- From chat detail, click "🔄 Change Account"

**Expected**:
- Shows list of active accounts
- Each account listed with status

**Test:**
- If you have 2+ accounts, click a different one

**Expected**:
- Chat updates to use new account
- Back to detail view with updated account name

### 8. Change Template
- From chat detail, click "📝 Change Template"

**Expected**:
- Shows list of active templates

**Test:**
- If you have 2+ templates, click a different one

**Expected**:
- Chat updates to use new template
- Back to detail view with updated template name

### 9. Change Cooldown
- From chat detail, click "⏱️ Change Cooldown"

**Expected**:
- Prompt: "Enter the new cooldown (1–1440 minutes)"
- Shows current cooldown (30m)

**Test:**
- Enter: `60`

**Expected**:
- ✅ Cooldown updated successfully
- Back to detail view with new cooldown (60 minutes)

### 10. Create Multiple Chats
Create additional chats to test listing:
- Chat 2: Account1, Template1, `@test_group_2`, "Test Group 2", 45m
- Chat 3: Account1, Template2, `-100123456789`, "Private Chat", 120m

Then view chats list - should show all three with correct info

### 11. Disable Chat
- Open any chat
- Click "🚫 Disable Chat"

**Expected**:
- ✅ Chat disabled notification
- Chat no longer appears in regular list
- (Disabled chats would need admin view to re-enable)

## Input Validation Tests

### Valid Chat Username Tests
- `@groupname` → ✅ Accepted
- `@my_group_123` → ✅ Accepted
- `@a` → ❌ Rejected (too short)
- `@toolongusernameexceedsthirtytwocharacterlimit` → ❌ Rejected (too long)
- `@group-name` → ❌ Rejected (invalid chars)
- `@Group_Name` → ✅ Accepted (uppercase ok)

### Valid Chat ID Tests
- `-100123456789` → ✅ Accepted
- `-1001234` → ✅ Accepted
- `100123456789` → ❌ Rejected (must be negative)
- `-abc123` → ❌ Rejected (must be numeric)

### Display Name Validation
- 1 character → ❌ Rejected (too short)
- 2 characters → ✅ Accepted
- 100 characters → ✅ Accepted
- 101 characters → ❌ Rejected (too long)
- With spaces: `  My Group  ` → ✅ Accepted (trimmed)

### Cooldown Validation
- `0` → ❌ Rejected (too low)
- `1` → ✅ Accepted (minimum)
- `30` → ✅ Accepted (typical)
- `1440` → ✅ Accepted (maximum = 24 hours)
- `1441` → ❌ Rejected (too high)
- `abc` → ❌ Rejected (non-numeric)

## Database Verification

To verify chats are properly saved:

```python
from app.database import get_session
from app.services import list_chats

session = get_session()
chats = list_chats(session, include_inactive=False)
for chat in chats:
    info = {
        'title': chat.title,
        'account_id': chat.advertising_account_id,
        'template_id': chat.assigned_template_id,
        'cooldown': chat.cooldown_minutes,
        'status': chat.status,
    }
    print(f"Chat {chat.id}: {info}")
session.close()
```

## Navigation Tests

Verify all navigation flows:
1. Chats Menu → Chats List → Chat Detail → Back to List → Back to Menu
2. Creation wizard can be cancelled at any step
3. Change Account/Template/Cooldown flows return to detail view
4. All back buttons work
5. No getting stuck in FSM states

## Edge Cases to Test

1. **No Accounts**: Create chat when all accounts are paused/disabled
   - Should see: "No active accounts available"

2. **No Templates**: Create chat when all templates are disabled
   - Should see: "No active templates available"

3. **Special Characters**: Use emojis in display name
   - E.g., `📱 MEXC Group` → Should work

4. **Very Long Text**: Use max length values
   - 100-char display name
   - 1440-minute cooldown

5. **Boundary Values**:
   - Cooldown: 1 and 1440 minutes
   - Display name: 2 and 100 characters
   - Username: 3 and 50 characters

6. **Rapid Changes**: Quickly change account/template/cooldown multiple times
   - All changes should apply

7. **Status Transitions**: 
   - Active → Pause → Resume → Pause → Resume
   - Should work smoothly

## Integration Tests

### Accounts + Templates + Chats
1. Create account: "Main Account"
2. Create template: "Promo Message"
3. Create chat using both
4. Change account to different one
5. Change template to different one
6. Verify all changes persist

### Chats with Scheduler (Future)
Once scheduler is enhanced:
1. Create chat with 1-minute cooldown
2. Start scheduler
3. Watch logs to see messages sent
4. Pause chat
5. Verify scheduler skips it
6. Resume and verify sending resumes

## Known Limitations (Not Implemented Yet)

- ❌ Telethon authentication (phase 2)
- ❌ Actual message sending (phase 2)
- ❌ Re-enabling disabled chats via UI
- ❌ Bulk operations (pause multiple at once)
- ❌ Search/filter by name
- ❌ Export/import chat configs
- ❌ Scheduled sends (send only specific times)

## Troubleshooting

**Wizard stuck on step X**:
- Send `/start` to reset FSM state

**Cannot create chat - "No active accounts"**:
- Go to Accounts and activate at least one account

**Cannot create chat - "No active templates"**:
- Go to Templates and create at least one active template

**Chat not appearing in list**:
- Verify it was created: Query database as shown above
- Check `is_active=True`
- Refresh list by going back and re-entering

**Change operation returns to wrong screen**:
- This should not happen - report as bug
- All change operations return to chat detail

**Cooldown not updating**:
- Try again with valid number (1-1440)
- Check database to verify update

---

# Testing Guide - Dashboard & Logs

This document explains how to test the Dashboard & Logs functionality.

## Prerequisites

Same as other modules. For meaningful testing, have:
- 2+ active accounts
- 2+ active templates
- 3+ active chats
- Let scheduler run for a bit to generate some logs

## Testing Dashboard

### 1. Main Menu Navigation
- From main menu, click "💬 Chats" (or "📊 Campaigns")

**Expected**: You should see:
- "📊 Campaign Dashboard"
- 📊 View Dashboard
- 📋 Logs
- ⬅️ Back

### 2. View Dashboard
- Click "📊 View Dashboard"

**Expected**: You should see comprehensive dashboard with:
- 📱 Advertising Accounts section
  - Total count
  - 🟢 Active
  - ⏸️ Paused
  - 🔥 Warming
  - 🚫 Disabled

- 💬 Configured Chats section
  - Total count
  - 🟢 Active
  - ⏸️ Paused
  - ⚠️ Error
  - 🚫 Disabled

- 📝 Message Templates section
  - Total count
  - ✅ Active
  - 🚫 Disabled

- ⚙️ Scheduler Status section
  - ✅ RUNNING or ⏹️ STOPPED
  - DRY_RUN: ON (Simulated) or OFF (Real Sends)

- 📈 Activity Today section
  - ✅ Sends: [number]
  - ❌ Errors: [number]
  - Last success: [time or none]
  - Last error: [time or none]

- ⏰ Next Scheduled Sends section
  - Shows up to 10 upcoming sends
  - For each: emoji, chat name, account, template, time remaining

### 3. Dashboard Calculations

**Test Account Count:**
- Create account → Count increments
- Pause account → Count updates
- Disable account → Count updates

**Test Chat Count:**
- Create chat → Active count increments
- Pause chat → Paused count increments
- Edit chat status to error → Error count increments

**Test Next Scheduled Sends:**
- Create chat with 60m cooldown
- Check dashboard - should show "in 60m" or "NOW" if no last_sent_at
- Wait for scheduler to run
- Refresh dashboard - time should be approximately 60m from last send

### 4. Refresh Button
- Click "🔄 Refresh"

**Expected**: Dashboard reloads with current data

### 5. Navigate to Logs
- From dashboard, click "📋 Logs"

**Expected**: Logs menu appears

## Testing Logs

### 1. Logs Menu
- From dashboard (or main menu → Campaigns), click "📋 Logs"

**Expected**: Logs menu with options:
- 📋 Recent Logs
- ❌ Errors Only
- ✅ Success Only
- 📱 By Account
- 💬 By Chat
- ⬅️ Back

### 2. View Recent Logs
- Click "📋 Recent Logs"

**Expected**:
- "📋 Recent Logs (Last 20)"
- If no logs: "No logs found yet"
- If logs exist: Each log shows:
  - ✅/❌ emoji
  - Timestamp (YYYY-MM-DD HH:MM:SS)
  - 📱 Account Name • 💬 Chat Title • 📝 Template Name
  - ⚠️ Error: [message] (only if error)

### 3. View Error Logs
- From logs menu, click "❌ Errors Only"

**Expected**:
- "❌ Error Logs (Last 20)"
- Shows only logs with status = "error"
- Each shows error message
- If no errors yet: "No logs found yet"

### 4. View Success Logs
- From logs menu, click "✅ Success Only"

**Expected**:
- "✅ Success Logs (Last 20)"
- Shows only logs with status = "success"
- No error messages shown
- If no successes yet: "No logs found yet"

### 5. View Logs by Account

**Step 5a: Account Selection**
- From logs menu, click "📱 By Account"

**Expected**:
- "📱 Select Account"
- Shows list of all accounts
- Each account is clickable

**Step 5b: View Account Logs**
- Click on an account

**Expected**:
- "📱 Logs for [Account Name] (Last 20)"
- Shows last 20 logs for that account
- All logs have same account name
- Different chats and templates possible

**Test with Multiple Accounts:**
- View logs for Account 1
- Go back, view logs for Account 2
- Should show different chats/sends

### 6. View Logs by Chat

**Step 6a: Chat Selection**
- From logs menu, click "💬 By Chat"

**Expected**:
- "💬 Select Chat"
- Shows list of all active chats
- Each chat is clickable

**Step 6b: View Chat Logs**
- Click on a chat

**Expected**:
- "💬 Logs for [Chat Title] (Last 20)"
- Shows last 20 logs for that chat
- All logs have same chat title
- Same or different accounts possible

**Test with Multiple Chats:**
- View logs for Chat 1
- Go back, view logs for Chat 2
- Should show different accounts/sends

### 7. Log Formatting

**Test Status Emoji:**
- ✅ for successful sends
- ❌ for failed sends

**Test Error Message:**
- Successful logs: No error message
- Failed logs: Show error message (first 80 chars)

**Test Timestamp:**
- Should be in YYYY-MM-DD HH:MM:SS format
- Should match actual send time

**Test Account/Chat/Template Names:**
- Should match what's configured
- Should update if names are changed

## Integration Tests

### Dashboard + Chats
1. View dashboard
2. Note "Active Chats: X"
3. Pause a chat
4. Refresh dashboard
5. Active chats should decrement, paused should increment

### Dashboard + Accounts
1. View dashboard
2. Note "Active Accounts: X"
3. Disable an account
4. Refresh dashboard
5. Active should decrement, disabled should increment

### Dashboard + Templates
1. View dashboard
2. Note "Active Templates: X"
3. Disable a template
4. Refresh dashboard
5. Active should decrement, disabled should increment

### Logs + Scheduler
1. View dashboard - note activity counts
2. Let scheduler run (DRY_RUN mode) for a bit
3. View recent logs
4. Activity should increase
5. Next scheduled sends should show upcoming

## Edge Cases to Test

1. **Empty State:**
   - No logs yet → "No logs found yet"
   - No accounts → Account selection shows empty
   - No chats → Chat selection shows empty

2. **Large Numbers:**
   - 50+ accounts → Still displays properly
   - 100+ chats → Still displays properly
   - Very long error messages → Truncated at 80 chars

3. **Timestamp Accuracy:**
   - Log timestamp should match when it was created
   - Activity "today" resets at midnight UTC
   - Next send timing should be accurate

4. **Formatting:**
   - Long account names → Fit in display
   - Unicode in chat titles → Display correctly
   - Error messages with special chars → Display safely

## Database Verification

To verify logs are being created:

```python
from app.database import get_session
from app.services import list_recent_logs

session = get_session()
logs = list_recent_logs(session, limit=5)
for log in logs:
    print(f"{log.status} - {log.account.display_name} - {log.chat.title}")
session.close()
```

## Performance Testing

1. **Dashboard Load Time:**
   - Should load <1 second
   - With 50+ accounts/chats

2. **Next Scheduled Calculation:**
   - Should complete instantly
   - Even with 100+ chats

3. **Logs Query:**
   - Should return in <100ms
   - Even with 1000+ log entries

## Known Limitations (Not Implemented Yet)

- ❌ Log pagination (shows last 20, no "next page")
- ❌ Date range filtering
- ❌ Search by account/chat name
- ❌ Log export
- ❌ Real-time updates (needs refresh)
- ❌ Telethon auth status

## Troubleshooting

**Dashboard shows no data:**
- Verify accounts/chats/templates exist
- Check they're active (not paused/disabled)
- Try refresh button

**No logs appearing:**
- Scheduler might not be running
- No sends have happened yet
- Check scheduler status on dashboard

**Wrong account/chat selected for logs:**
- Go back and re-select
- Check the list carefully

**Activity counts don't update:**
- Click refresh button
- Wait for scheduler to run
- Check scheduler is actually running

**Next scheduled sends showing "NOW" for everything:**
- This is normal if scheduler just ran
- Times will update next refresh
- Check exact next send times

**Error messages truncated:**
- This is intentional (80 char limit)
- Full error in database if needed
- View in database for details

---

## All Tests Summary

| Feature | Status | Notes |
|---------|--------|-------|
| View templates list | ✅ | Create first |
| Create template | ✅ | FSM-based flow |
| Template details | ✅ | Shows full info |
| Edit name | ✅ | FSM with confirmation |
| Edit text | ✅ | FSM with preview |
| Disable template | ✅ | Soft delete |
| Enable template | ✅ | Restore disabled |
| Input validation | ✅ | Comprehensive |
| Navigation | ✅ | All back buttons work |
| Database persistence | ✅ | SQLite |
| Duplicate prevention | ✅ | Names and identity edits |
# Proxy Monitoring Checks

## Automated tests

Run:

```bash
python -m unittest discover -s tests -v
```

The proxy suite verifies single-type fast checks, ordered full diagnostics,
database health updates, password masking, transition-only background alerts,
and disabling monitoring with `PROXY_MONITOR_INTERVAL_SECONDS=0`.

## Manual Telegram check

1. Open **Аккаунты**, select an account, then open **🌐 Прокси**.
2. Press **🟢 Быстрая проверка**. Only the saved type should be checked and a
   status card with latency and check time should appear.
3. Press **🔍 Полная диагностика**. An auto-detected proxy should show attempts
   in the order SOCKS5, HTTP, SOCKS4 and stop after the first success. An
   explicit-scheme proxy should show one attempt.
4. Confirm that the proxy password is masked everywhere.
5. For monitor testing, temporarily set
   `PROXY_MONITOR_INTERVAL_SECONDS=30`, restart the bot, and make a known-good
   proxy unavailable. The owner should receive one failure notification, no
   repeated failure notification, and one recovery notification after the
   proxy becomes available again.

Set the interval back to `1800` after the test. A value of `0` disables the
monitor completely.

## Premium UI manual check

1. Open the main menu and confirm that action buttons have no decorative
   emoji and remain in the same four-by-two layout.
2. Open **Аккаунты → Список аккаунтов**. Every account should show a health
   status and percentage without exposing its phone number.
3. Open an account. Confirm the structured card contains masked phone,
   Telegram and proxy status, chat/template counts, last activity, and Health.
4. Open **Health** and verify every component shows its score and a reason when
   unhealthy.
5. Open **Прокси**. Confirm the host is masked and the password and login are
   absent. Run a fast check, then open **История** and verify the new record.
6. Open **Кампании → Открыть dashboard**. Confirm grouped Accounts, Campaigns,
   Proxy, Activity, System Health, and Accounts Health sections are visible.
7. Tap an account button below the dashboard and confirm its account card
   opens.
8. Confirm action order is primary, secondary, dangerous action, then Back.
