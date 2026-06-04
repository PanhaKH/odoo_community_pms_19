# Default Hotel Accounting Setup

The `hotel_management` module includes an idempotent setup routine that creates or reuses the standard hotel accounting records needed for daily PMS operation.

## How It Runs

- Automatically after module installation through `post_init_hook`.
- Automatically on module upgrade through `data/hotel_default_accounts.xml`.
- Manually from `Hotel Management > Configuration > Setup Default Hotel Accounting`.

The setup is safe to rerun. It searches existing records first and only creates missing accounts, taxes, journals, and products. Existing hotel configuration fields are filled only when empty, so user-customized settings are not overwritten.

## Default Accounts

Liability:
- `210100` Guest Advance Deposit
- `210110` Group Advance Deposit
- `210120` Guest Security Deposit

Receivable:
- `101100` Hotel Cash
- `102100` Hotel Bank
- `110300` Guest Receivable
- `110310` City Ledger Receivable
- `110320` POS Room Charge Receivable

Tax Liability:
- `210300` VAT Payable

Revenue:
- `410100` Room Revenue / Accommodation Revenue
- `410200` F&B Revenue
- `410300` Laundry Revenue
- `410400` Minibar Revenue
- `410500` Other Hotel Revenue
- `410600` No Show / Cancellation Revenue
- `410700` Early Check-In / Late Check-Out Revenue
- `410800` Extra Person Revenue

Expense / COGS:
- `510100` Room Operating Expense
- `510200` Housekeeping Supplies Expense
- `510300` Laundry Expense
- `510400` Minibar Cost of Goods Sold
- `510500` Maintenance Expense
- `510600` Guest Amenities Expense

## Taxes

The setup reuses an existing 10% sales or purchase tax for the active company when found. If no matching tax exists, it creates:
- VAT 10% Sales Tax
- VAT 10% Purchase Tax

## Default Products

Service products:
- Accommodation / Room Charge
- Advance Deposit
- Group Advance Deposit
- Security Deposit
- Extra Person Charge
- Early Check-In / Late Check-Out
- No Show / Cancellation Charge
- Laundry Service
- Other Hotel Charge
- Restaurant Charge
- Breakfast

Inventory / consumable style products:
- Minibar Item
- Guest Amenity
- Housekeeping Supply
- Maintenance Spare Part

Deposit products point to liability accounts so they do not become revenue. Room and service charges point to the matching hotel revenue accounts.

## Default Journals

- Hotel Cash
- Hotel Bank
- Hotel Sales Journal
- Hotel Purchase Journal
- Hotel Deposit Journal
- City Ledger Journal

Hotel Cash and Hotel Bank journals are configured for front-office cashier use:
- journal default account is the matching Hotel Cash or Hotel Bank account
- inbound and outbound manual payment method lines use the same liquidity account
- customer invoice payments post directly to cash/bank instead of an Outstanding Receipts clearing account

## Editing Defaults

After setup, go to `Hotel Management > Configuration > Setting Options` to review the main accounting defaults. You may change accounts, products, journals, or taxes at any time. Rerunning the setup will not replace fields that already have values.

## Expected Accounting Flow

Advance deposit:
- Dr Cash/Bank
- Cr Guest Advance Deposit

Room invoice:
- Dr Guest Receivable or City Ledger Receivable
- Cr Room Revenue
- Cr VAT Payable

Example 10% VAT room invoice:
- Dr Accounts Receivable 44.00
- Cr Room Revenue 40.00
- Cr VAT Payable 4.00

Example Hotel Bank payment:
- Dr Hotel Bank 44.00
- Cr Accounts Receivable 44.00

Deposit application at checkout:
- Dr Guest Advance Deposit
- Cr Guest Receivable or City Ledger Receivable
