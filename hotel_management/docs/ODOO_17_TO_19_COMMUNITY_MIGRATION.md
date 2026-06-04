# Odoo 17 Community to Odoo 19 Community Migration

## Goal

Migrate this `hotel_management` custom module from Odoo 17 Community to Odoo 19 Community while preserving:

- the current backend GUI and menu structure as closely as Odoo 19 allows
- the current staff login and portal login flow
- guest magic-link and pre-arrival flows
- reservation, folio, housekeeping, maintenance, reporting, dashboard, floor-plan, tape-chart, POS room-charge, and portal behavior
- existing business data during the database upgrade

The goal is a compatibility migration, not a redesign. Odoo 19 framework changes may require technical XML, JavaScript, Python, and data-migration changes, but those changes should not intentionally alter hotel workflows or user-visible behavior.

## Current Project Shape

The module currently includes:

- a single application manifest in `__manifest__.py`
- backend models in `models/`, including a large reservation and accounting integration in `models/hotel_reservation.py`
- portal and guest routes in `controllers/main.py`
- backend XML views, inherited standard views, menus, reports, and QWeb templates in `views/`, `report/`, and `wizard/`
- OWL/backend JavaScript actions and widgets in `static/src/js/`
- POS integration in `models/pos_hotel.py`, `static/src/js/pos_hotel.js`, and `static/src/xml/pos_hotel.xml`

The migration should keep those boundaries. Do not split or redesign the module merely because the Odoo version changes.

## Migration Strategy

1. Freeze a known-good Odoo 17 baseline.
2. Back up the Odoo 17 database and filestore together.
3. Port the custom module until it installs on an empty Odoo 19 Community database.
4. Run the Odoo database upgrade path for a test copy of the Odoo 17 database.
5. Install/update the Odoo 19 custom module against the upgraded test database.
6. Add upgrade scripts only when model names, field names, XML IDs, stored values, or data structures must change.
7. Run workflow regression tests until the Odoo 19 result matches the Odoo 17 behavior.
8. Repeat on a fresh production backup before go-live.

## Required Code Changes

### 1. Manifest and Dependency Pass

Update `__manifest__.py` for the Odoo 19 port.

Recommended version format:

```python
'version': '19.0.1.0.0',
```

Keep the dependency intent unless Odoo 19 module names prove otherwise:

```python
'depends': [
    'base',
    'mail',
    'sale_management',
    'maintenance',
    'portal',
    'website',
    'account',
    'point_of_sale',
],
```

Verify every dependency exists in Odoo 19 Community before removing or replacing it. A missing dependency should be fixed deliberately, not hidden by deleting it.

Verify asset bundle names against the target Odoo 19 source before finalizing:

- `web.assets_backend`
- `point_of_sale._assets_pos`

Audit the remote `jsQR` CDN entry in the backend asset list. For repeatable production builds, prefer a locally vendored static asset if Odoo 19 asset compilation or deployment policy does not accept the remote URL.

### 2. Convert Old List-View Naming

This project still uses the Odoo 17-era `tree` view name broadly. Odoo 19 documentation describes list views with:

- XML root element `<list>`
- action view type `list`
- default window action `view_mode` such as `list,form`

Make a full migration pass:

```xml
<!-- Odoo 17 style -->
<tree string="Rooms">
    <field name="name"/>
</tree>

<!-- Odoo 19 style -->
<list string="Rooms">
    <field name="name"/>
</list>
```

```xml
<!-- Odoo 17 style -->
<field name="view_mode">tree,form</field>

<!-- Odoo 19 style -->
<field name="view_mode">list,form</field>
```

```javascript
// Odoo 17 style
view_mode: "tree,form",
views: [[false, "tree"], [false, "form"]],

// Odoo 19 style
view_mode: "list,form",
views: [[false, "list"], [false, "form"]],
```

Update inherited XPath expressions too:

```xml
<!-- Existing project example -->
<xpath expr="//field[@name='order_line']/tree/field[@name='name']" position="before">

<!-- Odoo 19 port candidate -->
<xpath expr="//field[@name='order_line']/list/field[@name='name']" position="before">
```

Files that already show this hotspot include:

- `views/hotel_reservation_views.xml`
- `views/hotel_room_views.xml`
- `views/hotel_payment_views.xml`
- `views/hotel_housekeeping_views.xml`
- `views/hotel_lost_found_views.xml`
- `views/hotel_service_request_views.xml`
- `views/hotel_rate_plan_views.xml`
- `views/hotel_change_log_views.xml`
- `views/hotel_daily_stats_views.xml`
- `views/hotel_dashboard_views.xml`
- `views/hotel_floor_plan_views.xml`
- `views/hotel_maintenance_views.xml`
- `wizard/hotel_split_line_wizard_views.xml`
- `static/src/js/hotel_dashboard.js`

Search the whole module after edits. The required pass includes `<tree>`, `</tree>`, `/tree/` XPath fragments, `view_mode` strings, and JavaScript `views` arrays.

### 3. Revalidate Standard View Inheritance

Inherited standard views are version-sensitive. Re-check each `inherit_id` and XPath against the actual Odoo 19 Community source.

High-risk examples in this project:

- `views/hotel_reservation_views.xml` inherits `sale.view_order_form`
- `views/hotel_payment_views.xml` extends accounting/payment views
- `views/pos_payment_method_views.xml` extends POS payment method configuration
- `views/res_config_settings_views.xml` extends settings UI
- `views/hotel_maintenance_views.xml` extends maintenance views

Do not "fix" a broken XPath by inserting the UI block in an unrelated location. Find the Odoo 19 parent architecture and preserve the Odoo 17 placement where practical.

### 4. Python Override Signature Pass

Install the module on Odoo 19 and check every override of a standard Odoo model or method against the Odoo 19 source signature and return contract.

Priority files and methods:

- `models/pos_hotel.py`
  - `pos.order._process_order`
  - `pos.session._loader_params_pos_payment_method`
- `models/hotel_reservation.py`
  - inherited `sale.order`, `sale.order.line`, `account.move`, `account.move.line`, `account.payment`, `res.partner`, `res.company`, `res.config.settings`, `pos.session`, and `sale.advance.payment.inv` code
- any controller helper imported from standard addons in `controllers/main.py`

Required rule:

```python
# Keep only after verifying the Odoo 19 parent method accepts the same signature
def _process_order(self, order, options, draft=False):
    result = super()._process_order(order, options, draft)
    ...
    return result
```

If Odoo 19 changes an argument, return type, loader mechanism, or payment/order data path, update the override to Odoo 19 while preserving the room-charge business behavior.

### 5. JavaScript and OWL Pass

The backend assets already use native Odoo JavaScript modules and OWL imports, which is the right direction for Odoo 19:

- `@web/...`
- `@odoo/owl`
- registry actions and fields
- service hooks such as `orm`, `action`, `dialog`, `notification`

Revalidate imports and patch targets against Odoo 19, especially:

- `static/src/js/hotel_quick_toolbar.js` patching `ControlPanel`
- `static/src/js/hotel_billing_target_field.js` extending selection field behavior
- `static/src/js/hotel_tape_chart.js` dialog imports
- `static/src/js/pos_hotel.js` POS screen, popup, and popup-service imports

POS frontend internals are the highest-risk frontend area because `pos_hotel.js` imports and patches POS components directly.

### 6. Portal, Login, and Guest Link Preservation

Keep the existing route intent in `controllers/main.py`:

- logged-in portal reservations remain under `/my/reservations`
- the logged-in reservation detail route remains under `/my/reservation/<id>`
- guest magic-link entry remains tokenized
- pre-arrival entry remains tokenized

Regression-test these route families:

| Flow | Route Family | Expected Behavior |
| --- | --- | --- |
| Portal login | `/web/login`, `/my` | user signs in and sees portal home |
| Portal reservation list | `/my/reservations` | only that partner's reservations are listed |
| Portal reservation detail | `/my/reservation/<id>` | other partners' records are rejected |
| Guest magic link | `/hotel/reservation/<id>?access_token=...` | link resolves to token-protected guest page |
| Guest service request | `/hotel/reservation/<id>/request` | valid token creates request and chatter alert |
| Pre-arrival form | `/pre-arrival/<id>?access_token=...` | valid token opens form |
| Pre-arrival submit | `/pre-arrival/submit` | saves preferences and optional passport upload |

Review `csrf=False` on `pre_arrival_submit` during the security pass. Keep it only if the Odoo 19 form flow needs it and the token validation remains enforced.

### 7. Data Upgrade and Upgrade Scripts

Avoid model/field/XML-ID renames during the compatibility port unless they are necessary. Stable technical names reduce data-migration risk.

Create an upgrade script when a compatibility change renames or transforms stored data. Odoo upgrade scripts can live under a versioned path such as:

```text
hotel_management/upgrades/19.0.1.0.0/pre-*.py
hotel_management/upgrades/19.0.1.0.0/post-*.py
hotel_management/upgrades/19.0.1.0.0/end-*.py
```

Typical uses:

- rename a field, model, or XML ID without losing existing data
- initialize a new stored field from an old value
- normalize a selection value that changed during the port
- repair a relation after a standard model change

Do not use upgrade scripts to hide view or JavaScript compatibility errors.

## Recommended Work Order

### Phase A. Baseline

1. Record screenshots and short screen captures of the Odoo 17 GUI for critical hotel flows.
2. Export a list of installed modules and confirm this repository matches the running Odoo 17 code.
3. Back up database and filestore.
4. Record route behavior for portal login, guest magic links, and pre-arrival links.

### Phase B. Empty Odoo 19 Install

1. Set up Odoo 19 Community with the same custom addons path.
2. Update manifest version and dependency checks.
3. Fix XML parser and view errors first.
4. Fix Python import, method-signature, field, and model errors.
5. Fix frontend asset compilation and browser-console errors.
6. Confirm all menus and actions open.

### Phase C. Functional Port

Test these workflows in Odoo 19:

- create room types, rooms, rate plans, and booking sources
- create, confirm, check in, move, and check out a reservation
- create folio charges, deposits, invoices, receipts, split charges, and routing
- run housekeeping, maintenance, lost-found, and service request screens
- open dashboard, floor plan, tape chart, availability grid, and reporting views
- execute night audit and business-date flows on a test database
- create room charges from POS
- open portal and pre-arrival flows from real links

### Phase D. Upgraded Database

1. Upgrade a test copy of the Odoo 17 database.
2. Update `hotel_management` on the upgraded Odoo 19 database.
3. Add versioned upgrade scripts only for real data conversion needs.
4. compare totals, statuses, room availability, invoices, payments, folios, and dashboard figures between the Odoo 17 baseline and Odoo 19 result.

## Suggested Verification Commands

Adapt paths and database names to the Odoo 19 environment.

```powershell
python odoo-bin -d hotel19_empty -i hotel_management --stop-after-init
python odoo-bin -d hotel19_empty -u hotel_management --stop-after-init
```

Search for old list-view naming after the conversion:

```powershell
rg -n "<tree|</tree>|/tree/|view_mode.*tree|\[false, ['\"]tree['\"]\]" views wizard report static/src/js
```

Search for frontend and POS patch points before Odoo 19 source comparison:

```powershell
rg -n "@point_of_sale|@web|@odoo|patch\(|registry\.category|useService" static/src/js
```

## Acceptance Criteria

The migration is ready for user acceptance only when:

- `hotel_management` installs and updates on Odoo 19 Community without fatal errors
- old `tree` list-view declarations are removed or explicitly justified by target Odoo 19 behavior
- critical inherited views load on Odoo 19
- backend assets and POS assets load without import or runtime failures
- login, portal, guest magic-link, and pre-arrival flows behave like the Odoo 17 baseline
- reservation, folio, accounting, housekeeping, maintenance, reports, and POS room charges pass regression tests
- upgraded test database keeps required business records and totals
- any required upgrade scripts are versioned and reviewed

## Official Odoo 19 References

- Upgrade overview: `https://www.odoo.com/documentation/19.0/administration/upgrade.html`
- Customized database upgrade: `https://www.odoo.com/documentation/19.0/developer/howtos/upgrade_custom_db.html`
- Upgrade scripts: `https://www.odoo.com/documentation/19.0/developer/reference/upgrades/upgrade_scripts.html`
- Module manifests: `https://www.odoo.com/documentation/19.0/developer/reference/backend/module.html`
- Window actions: `https://www.odoo.com/documentation/19.0/developer/reference/backend/actions.html`
- View architectures: `https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_architectures.html`
- JavaScript modules: `https://www.odoo.com/documentation/19.0/developer/reference/frontend/javascript_modules.html`
