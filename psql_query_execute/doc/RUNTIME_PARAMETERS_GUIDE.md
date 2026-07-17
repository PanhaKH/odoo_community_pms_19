# SQL Report Parameters Guide

This guide explains how to configure and test RoomMaster-style parameters in
the existing **PSQL Query Execute** module.

## User workflow

1. Open a saved SQL report.
2. Add definitions under **Report Parameters**.
3. Click **Run Report**.
4. Enter values in the **Report Parameters** popup.
5. Click **Generate Report**.

Reports with visible parameters open the popup. Reports without parameters run
directly. Required values and ranges are validated before SQL execution. Applied
parameter labels and values appear in the PDF header; empty optional values are
hidden.

## Placeholder rules

- Use psycopg named placeholders such as `%(date_from)s` (recommended).
- The shorter `:date_from` form is also accepted and normalized safely.
- Never quote a placeholder: use `state = %(status)s`, not
  `state = '%(status)s'`.
- Optional scalar filters should use a NULL-aware condition:

  ```sql
  AND (%(status)s IS NULL OR state = %(status)s)
  ```

- A Date Range named `period` binds `%(period_from)s` and `%(period_to)s`.
- A Number Range named `amount` binds `%(amount_from)s` and `%(amount_to)s`.
- Multiple Selection binds a PostgreSQL list. A typical condition is:

  ```sql
  AND (%(statuses)s IS NULL OR state = ANY(%(statuses)s))
  ```

- Every SQL placeholder must have one active parameter definition, and every
  active definition must be used by the SQL. A mismatch produces a clear error.
- Values are passed to `cursor.execute(sql, values)`; they are never inserted by
  string concatenation.

PostgreSQL literal percent signs continue to work. For example, modulo can be
written as `sequence % 2 = 0` even when the query also has parameters.

## Parameter fields

| Field | Purpose |
|---|---|
| Parameter Label | User-facing label in the popup and PDF |
| Technical Name | Safe identifier used by the SQL placeholder |
| Parameter Type | Determines the popup widget and value conversion |
| SQL Placeholder | Computed preview of the placeholder(s) |
| Required | Prevents generation when no value is supplied |
| Default Value | Initial value for the popup or a hidden parameter |
| Sequence | Display order |
| Visible | Whether users enter the value in the popup |
| Help Text | Guidance shown beside the input |
| Field / Column Reference | Optional link to a configured report column |
| Selection Values | Separate user label and stored SQL value |

Supported types are Date, Datetime, Text, Integer, Decimal, Boolean, Selection,
Many2one, Multiple Selection, Date Range, and Number Range.

For Many2one, select the allowed Odoo model. The popup uses a searchable record
field and passes the selected record ID. For Selection and Multiple Selection,
add option rows containing a display label and stored value.

## Date presets

A Date Range parameter supports Today, Yesterday, This Week, Last Week, This
Month, Last Month, This Year, and Custom Date Range. Custom mode displays Date
From and Date To. The popup rejects an empty required range or a From value
later than To. Number Range uses equivalent minimum/maximum validation.

## Requested test reports

### Test 1: Date Range

SQL:

```sql
SELECT *
FROM sale_order
WHERE date_order::date BETWEEN %(date_from)s AND %(date_to)s;
```

Create these definitions:

| Sequence | Label | Technical Name | Type | Required |
|---:|---|---|---|---|
| 10 | Date From | date_from | Date | Yes |
| 20 | Date To | date_to | Date | Yes |

Expected: **Run Report** opens the popup. Missing dates are rejected. Valid
dates generate the PDF.

### Test 2: Optional Status

SQL:

```sql
SELECT *
FROM sale_order
WHERE (%(status)s IS NULL OR state = %(status)s);
```

Create one optional Selection definition named `status`. Add options such as:

| Label | Stored Value |
|---|---|
| Draft | draft |
| Confirmed | sale |
| Cancelled | cancel |

Expected: leaving Status unused binds NULL and returns all rows. Selecting an
option filters by its stored value while the PDF displays its label.

### Test 3: Date and Room

SQL:

```sql
SELECT *
FROM hotel_room_service_order
WHERE order_date::date BETWEEN %(date_from)s AND %(date_to)s
  AND (%(room_number)s IS NULL OR room_number = %(room_number)s);
```

Create Date parameters as in Test 1, then add:

| Sequence | Label | Technical Name | Type | Required |
|---:|---|---|---|---|
| 30 | Room Number | room_number | Text | No |

Expected: dates are required and Room Number is optional.

### Test 4: No Parameters

SQL:

```sql
SELECT current_database(), current_user, NOW();
```

Do not add parameter definitions. Expected: **Run Report** executes directly
without an empty popup.

## Common errors

- **Missing required parameter**: enter a value in the popup.
- **Invalid date/number range**: make the From/Minimum value no greater than the
  To/Maximum value.
- **Invalid selection value**: use a configured active option.
- **Unknown SQL parameter**: create a matching definition or correct the SQL
  placeholder spelling.
- **Missing SQL placeholder**: remove the unused definition or add its
  placeholder to the SQL.
- **No records found**: the report ran successfully but the filters matched no
  rows.
- **Query timeout / PDF failure**: review the user-facing message and the Odoo
  server log; the module does not expose only a raw traceback for parameter
  validation failures.

## JavaScript asset troubleshooting

The SQL editor mode is explicitly mapped to
`/psql_query_execute/static/src/js/mode_sql.js`. This prevents Ace from deriving
`mode-sql.js` beneath Odoo's hashed `/web/assets/` route, which previously caused
the server error `not enough values to unpack` and a browser module-loading
banner.

After deploying an updated module:

1. Upgrade **PSQL Query Execute**.
2. Restart the Odoo service.
3. Hard-refresh the browser (`Ctrl+F5`) or clear site cache.
4. Confirm the form and SQL editor load without a JavaScript console error.
