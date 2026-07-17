## Module <psql_query_execute>

#### 01.01.2026
#### Version 19.0.1.0.0
#### ADD
- Initial commit for PSQL Query Execute

#### 09.06.2026
#### Version 19.0.1.0.1
#### UPDT
- Added test cases

#### 15.07.2026
#### Version 19.0.2.3.0
#### FIX
- Fixed Ace SQL mode loading from an invalid hashed asset URL.

#### ADD
- Added RoomMaster-style dynamic report parameters and a Run Report popup.
- Added safe named PostgreSQL parameter binding and friendly validation.
- Added Date/Datetime/Text/Integer/Decimal/Boolean/Selection/Many2one,
  Multiple Selection, Date Range, and Number Range parameter types.
- Added applied parameter summaries to existing PDF and XLSX report output.

#### 16.07.2026
#### Version 19.0.2.3.1
#### FIX
- Replaced the oversized report header stack with one compact, auto-height
  enterprise header.
- Added a sticky screen header and sticky column header without fixed
  positioning or hard-coded content offsets.
- Prevented wide report columns from pushing report branding and titles outside
  the printable page.
- Added responsive screen rules and static repeating print behavior for both
  portrait and landscape reports.

#### 16.07.2026
#### Version 19.0.2.4.0
#### IMPROVE
- Added sampled content-aware PDF column widths and horizontal column labels.
- Added automatic normal, compact, dense, and ultra-wide table styles.
- Improved portrait/landscape selection using estimated printable width.
- Added safe ellipsis handling for dense reports instead of vertical text.
- Batched relational display-name resolution to avoid per-cell database reads.
- Reduced expensive page-break layout work for large result sets.
