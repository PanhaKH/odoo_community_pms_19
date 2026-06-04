# PMS QA Corrections and Suggestions

Date: 2026-05-22
Environment: Odoo 19 Community, local database `odoo`
Addon: `hotel_management`

## Executive Summary

This pass corrected issues found while validating reservation, front desk,
availability grid, night audit, partial payment, housekeeping, and POS room
charge workflows. The changes are scoped to Odoo 19 compatibility and workflow
continuity. They do not redesign the PMS.

## Corrections Made

1. Same-day early checkout no longer rewrites a reservation into an invalid
   zero-night date range before checkout.
2. The Hotel Dashboard now exposes `Walk-In Check-In`. It opens the existing
   reservation form with the hotel business date, a one-night default stay, and
   the existing Walk-In booking source prefilled.
3. Availability Grid booking creation now defaults checkout to the next date
   instead of the same date as check-in.
4. POS room-charge sale lines use the Odoo 19 `product_uom_id` field through
   the hotel sale line compatibility path.
5. Bill To Room Charge payment methods are linked to POS configurations by the
   hotel POS data hook.
6. Visible broken encoded symbols were removed from reservation chatter,
   transfer messages, group checkout warnings, and night audit text.
7. Night audit backups no longer use a hardcoded Odoo 17 installation path.
   They are written below the active Odoo data directory in
   `hotel_night_audit_backups`.
8. The local Odoo config now selects the `odoo` database and narrows
   `dbfilter` to `^odoo$`. Odoo 19 must know the database before it can load
   custom public guest and pre-arrival routes from a fresh browser session.

## Validation Performed

- Updated `hotel_management` successfully on the Odoo 19 database.
- Verified reservation overlap blocks duplicate room occupancy.
- Verified dirty or unreleased rooms are blocked at check-in.
- Verified check-in creates a folio and does not create an accounting move by
  itself.
- Verified checkout moves the room to dirty housekeeping state.
- Verified cleaning plus inspection releases a room when inspection policy is
  active.
- Verified Walk-In Check-In action context supplies valid stay dates and Walk-In
  source defaults.
- Verified a partial payment scenario with a 500.00 folio invoice and a 200.00
  payment. Odoo reported `partial` and a 300.00 residual.
- Scanned posted accounting moves in the current database sample and found no
  unbalanced posted moves.
- Verified staff authentication can open `/my`, `/my/reservations`, dashboard,
  housekeeping, and reservation web entry URLs.
- Verified a non-owner portal detail request without token redirects to `/my`,
  while a valid reservation token opens the detail page.
- Verified direct guest magic-link and pre-arrival entry URLs return public
  pages after local database selection is configured.
- Verified invalid guest and pre-arrival tokens are rejected.
- Verified the POS UI page serves the POS debug asset bundle and that the bundle
  includes `pos_hotel.js`.
- Verified the backend debug asset bundle includes `hotel_quick_toolbar.js`.

## Remaining Manual Acceptance Checks

- Complete the POS browser click flow for Bill To Room Charge in an open POS
  session. The POS page, POS bundle, payment-method configuration, and backend
  folio posting path were validated locally.
- Confirm the Walk-In Check-In button placement visually on the dashboard.
- Confirm invoice settlement and checkout with the intended hotel journals,
  taxes, and payment methods on a staging copy of production configuration.
- Confirm dashboard, grid, tape chart, form chatter, and mobile housekeeping
  views visually on desktop and narrow browser widths.
- Confirm production host database routing. A public hotel URL needs a
  single-database host, matching `dbfilter`, or an equivalent deployment
  database selection policy.

## Suggestions

1. Add Odoo automated tests for overlap validation, same-day checkout, dirty
   room check-in, availability-grid defaults, walk-in action defaults, POS room
   charge folio posting, and partial payment reconciliation.
2. Decide whether staff need a separate visible `Reserved` booking indicator.
   Current code correctly separates date availability from physical room state,
   but QA scripts should describe that distinction.
3. Confirm POS tax policy for room-posted restaurant charges. The current hotel
   integration intentionally creates tax-free Restaurant Charge folio lines to
   avoid double tax.
4. Move backup retention, backup folder policy, and night-audit backup failures
   into deployment settings if operations need explicit retention controls.
5. Keep UI labels icon-safe. Prefer Font Awesome or clean text labels over
   pasted emoji in XML, Python chatter text, and mail templates.
6. Run the final production gate on an upgraded copy of the Odoo 17 database,
   not only on an empty or local Odoo 19 database.
7. Keep a staging database filter aligned with the production host before
   testing guest email links from private browser sessions.

## Production Readiness

Status: Not yet signed off for production.

The core reservation, duplicate-booking, check-in, checkout, housekeeping, POS
page/assets and backend charge, portal authorization, guest links, pre-arrival
links, partial payment, and posted-move balance checks now pass in focused local
validation. Production sign-off still requires the manual visual checks, live
POS click-through, and upgraded database test listed above.
