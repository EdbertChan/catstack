# spreadsheet-completeness-guard

Stop hook for spreadsheet completion claims. A completion claim must carry a
source-backed `SPREADSHEET_COVERAGE: PASS` receipt from the expected-entity
validator. Missing observations must be explicitly classified; estimates and
zeros are not substitutes for absent competitor data.

Tests: `python3 -m unittest discover -s engine/hooks/spreadsheet-completeness-guard/tests -v`
