# Odoo 19 Migration Prompt

Use this prompt with a coding agent after giving it access to this repository and to an Odoo 19 Community source tree or running Odoo 19 test environment.

```text
You are migrating the custom Odoo addon `hotel_management` from Odoo 17 Community to Odoo 19 Community.

Primary goal:
Make the addon install, update, and run on Odoo 19 Community while preserving the Odoo 17 user experience, login flow, portal flow, guest magic-link flow, pre-arrival flow, and hotel functionality. This is a compatibility migration, not a redesign.

Repository context:
- Manifest: `__manifest__.py`
- Portal/controllers: `controllers/main.py`
- Core hotel logic: `models/`
- Large reservation/accounting/PMS integration: `models/hotel_reservation.py`
- POS backend integration: `models/pos_hotel.py`
- Backend and inherited views: `views/`
- Wizards: `wizard/`
- Reports: `report/`
- OWL/backend JS: `static/src/js/`
- POS JS/XML: `static/src/js/pos_hotel.js`, `static/src/xml/pos_hotel.xml`

Non-negotiable behavior to preserve:
1. Staff can log in through the Odoo web login and use the hotel menus and backend screens.
2. Portal users can open `/my`, `/my/reservations`, and their own reservation details.
3. Tokenized guest magic links continue to work through `/hotel/reservation/...`.
4. Tokenized pre-arrival links continue to work through `/pre-arrival/...`.
5. Reservation, check-in, check-out, folio, deposits, invoices, payments, housekeeping, maintenance, lost-found, service requests, reporting, dashboard, floor plan, tape chart, availability grid, night audit, and POS room-charge workflows remain functionally equivalent unless an Odoo 19 compatibility change requires a documented deviation.

Implementation rules:
- Read the Odoo 19 Community parent code before changing inherited views, overridden Python methods, POS patches, or JS imports.
- Keep technical model names, field names, XML IDs, routes, and menu intent stable unless a real Odoo 19 conflict requires a change.
- Do not redesign the GUI. Use Odoo 19-compatible syntax while keeping the existing view layout and workflow placement as close to the Odoo 17 baseline as practical.
- Do not remove dependencies merely to make installation proceed. Confirm target module names first.
- Add upgrade scripts only when stored data needs migration because a model, field, XML ID, relation, or value changed.
- Preserve security boundaries. Do not weaken token validation or portal record ownership checks.

Required first-pass code changes:
1. Update the manifest version to an Odoo 19 version such as `19.0.1.0.0`.
2. Verify all manifest dependencies and asset bundle names against Odoo 19 Community.
3. Convert old list-view naming throughout the addon:
   - XML `<tree>` roots to `<list>`
   - XML `</tree>` to `</list>`
   - `view_mode` values using `tree` to `list`
   - JS action `views` entries using `"tree"` to `"list"`
   - inherited XPath fragments such as `/tree/` to the Odoo 19 parent architecture, usually `/list/`
4. Revalidate inherited view parents and XPaths in:
   - `views/hotel_reservation_views.xml`
   - `views/hotel_payment_views.xml`
   - `views/pos_payment_method_views.xml`
   - `views/res_config_settings_views.xml`
   - `views/hotel_maintenance_views.xml`
5. Compare Python overrides with Odoo 19 source, especially:
   - `models/pos_hotel.py`: `pos.order._process_order`
   - `models/pos_hotel.py`: `pos.session._loader_params_pos_payment_method`
   - standard model extensions inside `models/hotel_reservation.py`
6. Compare JS imports and patch targets with Odoo 19 source, especially:
   - `static/src/js/pos_hotel.js`
   - `static/src/js/hotel_quick_toolbar.js`
   - `static/src/js/hotel_billing_target_field.js`
   - `static/src/js/hotel_tape_chart.js`
7. Review the external `jsQR` asset in `__manifest__.py`; vendor it locally if target asset compilation or production policy requires it.

Important project hotspots already identified:
- Many XML files still use `tree` list-view syntax.
- `views/hotel_reservation_views.xml` contains an inherited XPath into `sale.order` order lines using `/tree/`.
- `static/src/js/hotel_dashboard.js` emits action `view_mode` and `views` entries using `tree`.
- POS logic patches frontend POS components and overrides backend POS order/session behavior, so it must be checked against Odoo 19 internals instead of guessed.
- `controllers/main.py` owns portal and tokenized guest/pre-arrival flow; preserve routes and authorization intent while checking Odoo 19 imports and CSRF behavior.

Required workflow:
1. Inspect current addon files and target Odoo 19 parent source.
2. Produce a short migration plan based on actual incompatibilities found.
3. Make tightly scoped code changes.
4. Install the addon on an empty Odoo 19 Community database.
5. Fix install/update errors until the addon loads.
6. Open critical backend menus/actions and fix view or asset runtime errors.
7. Test portal, guest-link, pre-arrival, reservation, folio/accounting, dashboard/custom actions, and POS room-charge flows.
8. On an upgraded copy of the Odoo 17 database, update the module and add versioned upgrade scripts only for proven data conversion needs.

Verification searches:
`rg -n "<tree|</tree>|/tree/|view_mode.*tree|\[false, ['\"]tree['\"]\]" views wizard report static/src/js`
`rg -n "@point_of_sale|@web|@odoo|patch\(|registry\.category|useService" static/src/js`

Expected output:
- Working Odoo 19-compatible code changes
- Versioned upgrade scripts if data migration requires them
- A list of files changed
- Install/update/test commands run and their results
- Remaining risks or behaviors that need manual user acceptance testing
```

## Related Guide

Read `docs/ODOO_17_TO_19_COMMUNITY_MIGRATION.md` before executing the prompt.
