# Extended rules — gap analysis

Reviewed four Power BI semantic-model best-practice articles against the existing rule sets
(`BPARules-PowerBI.json`, `BPARules-standard.json`) and added the **checkable** gaps to
[`BPARules-custom-extended.json`](BPARules-custom-extended.json) (11 new rules).

Sources reviewed:
- powerbiconsulting.com/blog/semantic-model-practices
- linkedin.com/pulse/10-tips-optimize-semantic-model-power-bi-christopher-wagner
- solvingmicrosoft365.com/guides/power-bi-semantic-model-design
- datacrafters.io/best-practices-for-building-scalable-power-bi-semantic-models-in-the-age-of-ai

---

## 1. New rules added (checkable, were missing)

| ID | Rule | Category | Sev | Why it was missing |
|---|---|---|---|---|
| `PROVIDE_DESCRIPTION_MEASURES` | Descriptions on visible measures | Metadata | 2 | Existing `TRANSLATE_DESCRIPTIONS` only translates *existing* descriptions across cultures; nothing required descriptions to exist. Key for AI/Copilot. |
| `PROVIDE_DESCRIPTION_COLUMNS` | Descriptions on visible columns | Metadata | 1 | Same gap. |
| `PROVIDE_DESCRIPTION_TABLES` | Descriptions on visible tables (grain/purpose) | Metadata | 1 | Same gap. |
| `AVOID_CALCULATED_COLUMNS` | Minimize calculated columns | Performance | 2 | Existing set flags *unused* columns only, not calc-column overuse. |
| `AVOID_BIDIRECTIONAL_RELATIONSHIPS` | No bi-directional cross-filter | Performance | 3 | No relationship cross-filter rule existed. |
| `AVOID_MANYTOMANY_RELATIONSHIPS` | No many-to-many relationships | Performance | 3 | No relationship-cardinality rule existed. |
| `RELATIONSHIP_COLUMNS_INTEGER_KEY` | Integer keys in relationships | Performance | 2 | Existing `RELATIONSHIP_COLUMN_NAMES` checks *names*, not key *data types*. |
| `MARK_DATE_TABLE` | Mark calendar tables as Date table | Metadata | 2 | Only `DIABLE_AUTO_DATE/TIME` existed; nothing checked a real date table is marked. |
| `SET_GEO_DATA_CATEGORY` | Data category on geographic columns | Metadata | 1 | No data-category rule existed. |
| `AVOID_DATETIME_COLUMNS` | Split DateTime (reduce cardinality) | Performance | 2 | Cardinality reduction not covered. |
| `SINGULAR_TABLE_NAMES` | Singular table names (heuristic) | Naming | 1 | No singular/plural naming rule existed. Heuristic — may have false positives. |

---

## 2. Already covered by existing rules (no new rule needed)

| Article recommendation | Covered by |
|---|---|
| Star schema / avoid single-attribute dims | `AVOID_SINGLE_ATTRIBUTE_DIMENSIONS` |
| Format strings on numeric columns/measures | `APPLY_FORMAT_STRING_COLUMNS/MEASURES` |
| Avoid floating-point types | `META_AVOID_FLOAT` |
| Explicit measures / don't summarize columns | `META_SUMMARIZE_NONE` |
| Organize measures/columns in display folders | `LAYOUT_MEASURES_DF`, `LAYOUT_COLUMNS_HIERARCHIES_DF` |
| Hide internal/foreign-key columns | `LAYOUT_HIDE_FK_COLUMNS` |
| Remove unused columns/measures | `PERF_UNUSED_COLUMNS`, `PERF_UNUSED_MEASURES` |
| Disable auto date/time | `DIABLE_AUTO_DATE/TIME` |
| Disable attribute hierarchies | `DISABLE_ATTRIBUTE_HIERACHIES` (standard set) |
| Consistent relationship column names | `RELATIONSHIP_COLUMN_NAMES` |
| Proper-case / no CamelCase naming | `UPPERCASE_FIRST_LETTER_*`, `NO_CAMELCASE_*` |
| Use DIVIDE instead of `/` | `DAX_DIVISION_COLUMNS` |

---

## 3. Intentionally NOT added (not statically checkable from model metadata)

These are process / governance / data-quality practices that need runtime data, a tenant, or
human judgement — a static BPA pass can't validate them, so they are **out of scope** (track them
in review checklists instead):

- Test RLS with "View as Role"; validate dynamic RLS mapping.
- Certify / promote the model; add workspace documentation.
- Configure refresh-failure alerts; configure incremental refresh partitions (needs policy + row counts).
- Validate measure values against source; validate Copilot/AI answers.
- Direct Lake / composite storage-mode and aggregation-table design choices.
- Slowly-changing-dimension (Type 1 vs 2) strategy.
- Model size within capacity limits; query-performance testing (DAX Studio / VertiPaq).
- Referential-integrity / date-completeness / value-range data checks (require querying data,
  not metadata — could be added later as DAX-query-based checks).
- Synonyms for Q&A (live in the linguistic schema; add manually for AI readiness).

---

## 4. How to use the extended rules

Select a rule set that includes them (the agent merges the extended file on top of a base set):

- `PowerBI+extended` → `BPARules-PowerBI.json` + `BPARules-custom-extended.json` (26 + 11 = 37)
- `standard+extended` → `BPARules-standard.json` + `BPARules-custom-extended.json` (29 + 11 = 40)
- `extended` → the 11 extended rules only

The file is standard Tabular Editor BPA JSON, so it also loads directly in Tabular Editor's
Best Practice Analyzer if you prefer to run it there.
