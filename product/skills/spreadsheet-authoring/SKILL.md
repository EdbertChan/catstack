---
name: spreadsheet-authoring
description: >-
  Design scalable spreadsheet models with category-level raw data, formula-
  driven aggregation tables, provenance, and charts. Use when creating or
  restructuring Excel or Google Sheets workbooks that must grow by adding rows.
---

# Spreadsheet authoring

Build the workbook as a data pipeline, not as a decorated report:

`raw observations → selector-driven aggregation table → chart`

## Raw observation contract

- Keep one raw sheet per category.
- Keep one numeric observation per row.
- Put dates in typed `Period Start` and `Period End` columns.
- Put `Average`, `Start`, `Peak`, `End`, `Low`, `High`, or similar qualifiers
  in a separate categorical `Observation Point` column.
- Preserve the source wording in `Original Period Label` for audit, but never
  use that display label as the aggregation key.
- When a source publishes a bounded start/end range but omits an average, a
  midpoint may be added only as a derived estimate: retain the source URL,
  label `Observation Type` as `derived estimate`, and record the formula in
  `Notes`. Never derive a start or end value from a peak, low, or other
  non-endpoint observation.
- Keep geography, scope, segment, entity, metric, value, unit, source, source
  URL, source location, derivation method, and derived-from lineage as
  separate fields.
- Geography bucketing is deterministic only when keyed by `(taxonomy_id, taxonomy_version, source_label)`. Preserve the source label, never fuzzy-match across taxonomies, and represent unknown, source-defined, or overlapping memberships with explicit mapping statuses rather than guessed membership.
- Synthetic observations may be added to the category raw sheet only when
  they are explicitly marked `Observation Type = derived estimate`. They must
  include `Derivation Method`, `Derived From`, a source URL for the underlying
  observations, and a formula/method note. The aggregate must support a
  published-only view and a published-plus-derived view; charts must make the
  selected mode visible.
- The default permitted synthetic methods are `midpoint` from matching Start
  and End observations and `linear interpolation` between bracketing periods.
  Never synthesize a competitor's missing observation from another entity, or
  infer Start/End/Peak/Low from an unrelated observation point.

When parsing a range such as `Nov 2024–Sep 2025`, write the first and last
dates as typed values. When parsing `Q4 2023 end`, write the quarter dates and
`End` separately. Derive human-readable titles after the typed fields exist.

## Aggregation and chart contract

- Before aggregation or chart generation, declare a measurement contract:
  metric name and definition, unit, numerator/denominator or population,
  geography, period basis and cadence, expected entity/competitor inventory,
  comparison basis, missing-data policy, and whether values are observed,
  estimated, or synthetic. Do not proceed when the contract is incomplete or
  differs across plotted entities.
- The aggregation table must reference raw fields, not copied values.
- Include every dimension that distinguishes observations in its key, including
  the observation point and cohort/segment.
- Let selectors choose the metric and the relevant subset of raw data.
- Reserve expandable formula ranges so adding a valid raw row updates the table.
- Charts must reference the aggregation table only, never the raw sheet.
- Derive the chart title or subtitle from the measurement contract so the
  graph states what is being measured. Use the native legend to identify the
  comparable entities and series roles. Do not compare entities whose metric,
  unit, denominator, geography, or period basis differs.
- Every user-facing chart must explain its visual encodings inside the graph:
  use the native legend, set `headerCount` to include semantic source headers,
  and label every plotted series (for example `Average / median`, `Lower
  bound`, and `Upper bound`). A sheet-side color key is not a substitute for
  the in-graph legend and should not be generated.
- Declare the expected entity inventory for each category and measurement slice.
  A table/chart is not complete until every expected entity has a valid,
  source-backed observation for each aggregation key, or the raw data carries
  an explicit `No observation published` status. Never convert an absent value
  into zero or silently treat it as complete. Derived estimates do not satisfy
  source-backed entity coverage.

## Preflight and verification

Before editing the live workbook, validate representative period labels,
source URLs, expected-entity coverage, and the migration result. Reject any
schema where a time column contains a qualifier token, where two distinct
observation points collapse to one key, or where an expected entity is absent
from a source-backed aggregation key. For CSV exports or fixtures, run
`scripts/validate_schema.py <file> --expected-entities A,B,C`.

If coverage fails, do not proceed to table or chart generation. Run a bounded
source-collection retry loop up to three times; each attempt must either add
new source-backed raw observations or record an explicit unresolved status.
After the third attempt, stop with `SPREADSHEET_COVERAGE: FAIL` and list the
missing entity/period keys. Never resolve the failure by copying, averaging,
zero-filling, or estimating an unreported competitor value.

After writing, reread raw headers, typed dates, observation points, derivation
fields, table formulas, selector behavior, chart source ranges, native legend
position, and semantic series headers. Test both a new source-backed row and a
derived row, plus invalid, duplicate, and unprovenanceable rows when the
workbook is intended to scale. Run `scripts/validate_chart_spec.py <spec.json>`
for chart fixtures.
