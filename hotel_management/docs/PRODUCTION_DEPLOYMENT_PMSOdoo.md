# Production Deployment Guide for `PMSOdoo`

This guide is the recommended production setup for a customer server.

## Goal

Run the hotel system in a single-database production layout:

- Database name: `PMSOdoo`
- No database selector for users or guests
- Guest portal links work directly
- Email links use the real public server URL, not `localhost`

## Recommended Production Model

Use one Odoo instance for one hotel customer:

- one Odoo service
- one PostgreSQL database
- one public URL or domain
- one fixed database: `PMSOdoo`

This avoids the multi-database portal problem seen on the local test server.

## Sample Odoo Config

Use the sample file:

- [odoo.PMSOdoo.conf.example](/c:/Program%20Files/Odoo%2017.0.20260307/server/addons/hotel_management/docs/odoo.PMSOdoo.conf.example)

The key production settings are:

- `db_name = PMSOdoo`
- `dbfilter = ^PMSOdoo$`
- `list_db = False`

With that layout, guests do not need to select a database first.

## Two Deployment Paths

### Option A: Preferred

Restore a prepared hotel database as `PMSOdoo`.

Use this when your local test database already contains:

- room types
- rooms
- rates
- taxes
- email templates
- users
- settings
- hotel operational data you want to keep

Steps:

1. Back up the final tested database and matching filestore.
2. Restore it on the customer server as `PMSOdoo`.
3. Point the production Odoo config to `db_name = PMSOdoo`.
4. Start Odoo with the single-database config.

This is the safest go-live path.

### Option B: Fresh Build

Create a brand-new `PMSOdoo` database automatically on first start, then install the hotel module.

Odoo 17 can auto-create the database named in `db_name` if it does not exist.

Recommended first-run command:

```powershell
python odoo-bin -c odoo.PMSOdoo.conf -d PMSOdoo -i hotel_management --without-demo=all --stop-after-init
```

Then start the normal service:

```powershell
python odoo-bin -c odoo.PMSOdoo.conf
```

This path is fine for a clean new hotel rollout, but it still needs hotel setup afterward.

## Base URL: Required for Guest Links

Your guest portal and pre-arrival emails now build absolute URLs from Odoo's base URL.

Before sending real emails, set:

- `web.base.url` to the real public server URL
- `web.base.url.freeze` to `True`

Example:

- `https://pms.customerhotel.com`
- or `http://10.10.10.20:8069` if using IP only

You can set these in Odoo shell:

```python
params = env['ir.config_parameter'].sudo()
params.set_param('web.base.url', 'https://pms.customerhotel.com')
params.set_param('web.base.url.freeze', 'True')
```

Why this matters:

- if `web.base.url` is wrong, emails may still generate `localhost` or an internal address
- if `web.base.url.freeze` is not set, Odoo can overwrite the base URL from later requests

## Go-Live Order

1. Prepare the final production config with `db_name = PMSOdoo`.
2. Restore the final database as `PMSOdoo`, or create it fresh.
3. Install or update `hotel_management`.
4. Set `web.base.url` and `web.base.url.freeze`.
5. Restart Odoo.
6. Test guest portal from an external browser using the real server URL.
7. Re-send booking confirmation emails after go-live.

## Why Re-Send Emails

Old chatter messages and previously sent emails already contain stored HTML.

That means:

- old portal buttons can still point to old URLs
- new confirmations sent after go-live will use the corrected absolute production URL

## Validation Checklist

Before go-live, verify:

1. Opening `/web/database/selector` is not part of the normal user flow.
2. Guest portal opens directly from a fresh browser.
3. Pre-arrival link opens directly from a fresh browser.
4. Booking confirmation email uses the real public URL.
5. Guest request form submits successfully.
6. Reservation ownership protections still work.
7. Housekeeping, night audit, and folio flows still work after restore.

## Recommendation for This Project

For this hotel system, the best production path is:

1. keep using the local multi-database server for development and testing
2. prepare one clean final customer database
3. deploy that customer environment as single-database `PMSOdoo`

That gives the cleanest guest portal behavior with the least operational risk.
