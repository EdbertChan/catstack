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
- Keep geography, scope, segment, entity, metric, value, unit, source, source
  URL, and source location as separate fields.

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

## Preflight and verification

Before editing the live workbook, validate representative period labels and
the migration result. Reject any schema where a time column contains a
qualifier token or where two distinct observation points collapse to one key.
For CSV exports or fixtures, run `scripts/validate_schema.py <file>`.

After writing, reread raw headers, typed dates, observation points, table
formulas, selector behavior, and chart source ranges. Test both a new row and
an invalid or duplicate row when the workbook is intended to scale.
