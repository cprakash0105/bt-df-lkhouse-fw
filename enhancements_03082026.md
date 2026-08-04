# Enhancement Plan — 03/08/2026
## Catalog Detail Modal: BA/BDE Click → Tabbed Detail Popup

---

## Problem

When you click a Business Application (BA) or Business Data Element (BDE) in the
catalog tree (HomePage) or the Glossary view, a thin right-side panel opens that
is essentially empty — just a few static text fields. There is no sample data,
no lineage, no DQ scores, and no attribute-level detail.

---

## What Should Happen

Clicking any BA or BDE anywhere in the app opens a **full-screen modal popup**
(same style as `DiscoveryModal`) with **four tabs**:

| Tab | Content |
|-----|---------|
| **Details** | All metadata: domain, type, PII flag, synonyms, DQ rules, linked tables, description, owner |
| **Sample Data** | Live sample rows from the dataset via the Profiler Service — column stats, null%, distinct count, sample values |
| **Lineage** | End-to-end attribute-level lineage graph: Landing → Bronze → Silver → Gold → Data Product. Shows which source column maps to which output column at every layer |
| **Data Quality** | DQ score per column: rules inherited from BDE, pass/fail counts, flagged records, quarantine stats |

---

## Files to Change

### 1. `discovery/web/src/components/CatalogDetailModal.jsx` — NEW FILE

The main modal component. Accepts `node` (the clicked BA or BDE object) and `onClose`.

**Structure:**
```
CatalogDetailModal
  ├── Header: node name, type badge, PII badge, close button
  ├── Tab bar: Details | Sample Data | Lineage | Data Quality
  └── Tab body (lazy-loaded per tab):
       ├── DetailsTab
       ├── SampleDataTab
       ├── LineageTab  (reuses LineageGraph SVG from LineageModal)
       └── DQTab
```

**DetailsTab** — renders from the `node` object already in memory:
- Domain, information type, data type, PII classification
- Synonyms list
- DQ rules inherited from this BDE (not_null, unique, accepted_values, positive)
- Linked tables (which datasets use this BDE) — from `api.glossary()` cross-reference
- Description if present

**SampleDataTab** — calls `api.profileDataset(node.id)` on mount:
- Shows column-level stats table: null%, distinct count, cardinality ratio, sample values
- Reuses the same table layout already in `ProfilerPanel.jsx`
- Shows a loading spinner while fetching
- Shows "Profiler service not available" gracefully if it fails

**LineageTab** — calls `api.lineage(node.id)` on mount:
- Reuses `LineageGraph` SVG component from `LineageModal.jsx` (extract it to a shared
  location or import directly)
- **Attribute-level lineage**: the `/lineage/{dataset}` API endpoint already stores
  `columnLineage` facets in the OpenLineage events. The tab reads these and renders
  a second sub-graph below the table-level graph showing:
  - Source column → bronze column → silver column → gold column
  - Each attribute node shows: column name, type, transformation type
    (IDENTITY / HASH / DERIVED / MASKED)
  - Highlighted path when you hover a column name in the Details tab
- Toggle between "Table lineage" and "Attribute lineage" views
- Falls back to static landing→bronze→silver→gold graph if no OpenLineage events exist

**DQTab** — calls `api.profileDataset(node.id)` (same call as SampleData, cached):
- Per-column DQ score bar (0–100%)
- DQ rules applied: shows each rule (not_null, unique, accepted_values) with
  pass/fail indicator
- Flagged record count from bronze `_dq_flags` column stats
- Quarantine count if available from lineage event `rowStats.quarantinedRows`
- Overall dataset DQ score = average of per-column scores
- Color coding: green ≥80%, amber 50–79%, red <50%

---

### 2. `discovery/web/src/components/HomePage.jsx` — MODIFY

**Change:** Replace the `DetailPanel` right-side panel with `CatalogDetailModal`.

Current code (lines ~180–230):
```jsx
{selectedNode && (
  <div className="w-[340px] border-l border-gray-200 p-5 overflow-auto bg-white shadow-elevated">
    <DetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />
  </div>
)}
```

New code:
```jsx
{selectedNode && (
  <CatalogDetailModal node={selectedNode} onClose={() => setSelectedNode(null)} />
)}
```

- Import `CatalogDetailModal` at the top
- Remove the `DetailPanel` function entirely (it becomes dead code)
- `setSelectedNode` already exists — no state changes needed

---

### 3. `discovery/web/src/components/GlossaryView.jsx` — MODIFY

**Change:** Replace the right-side detail panel with `CatalogDetailModal`.

Current code:
```jsx
{!showCreate && selected && (
  <div className="w-[320px] border-l border-gray-200 p-5 overflow-auto bg-white shadow-elevated">
    ... static fields ...
  </div>
)}
```

New code:
```jsx
{!showCreate && selected && (
  <CatalogDetailModal node={selected} onClose={() => setSelected(null)} />
)}
```

- The `selected` object from `GlossaryView` has: `id`, `name`, `domain`,
  `is_pii`, `information_type`, `synonyms`, `dq_rules`
- `CatalogDetailModal` must handle both the glossary term shape AND the
  tree node shape (they differ slightly — `node.type` may be undefined for
  glossary terms, default to `'term'`)

---

### 4. `discovery/api/main.py` — MODIFY (lineage endpoint enhancement)

**Change:** Enrich the `/lineage/{dataset}` response to include attribute-level
column lineage extracted from the `columnLineage` facet in OpenLineage events.

Current response shape:
```json
{ "dataset": "...", "nodes": [...], "edges": [...], "source": "..." }
```

New response shape adds:
```json
{
  "dataset": "...",
  "nodes": [...],
  "edges": [...],
  "source": "...",
  "column_lineage": {
    "sensor_id":    [{"stage": "bronze", "col": "sensor_id", "transform": "IDENTITY"},
                     {"stage": "silver", "col": "sensor_id", "transform": "IDENTITY"},
                     {"stage": "gold",   "col": "sensor_id", "transform": "IDENTITY"}],
    "temperature":  [{"stage": "bronze", "col": "temperature", "transform": "IDENTITY"},
                     {"stage": "silver", "col": "temperature", "transform": "IDENTITY"},
                     {"stage": "gold",   "col": "temperature", "transform": "IDENTITY"}],
    "customer_id":  [{"stage": "bronze", "col": "customer_id", "transform": "IDENTITY"},
                     {"stage": "silver", "col": "customer_id", "transform": "HASH"},
                     {"stage": "gold",   "col": "customer_id", "transform": "HASH"}]
  },
  "row_stats": {
    "bronze": {"inputRows": 1000, "outputRows": 1000},
    "silver": {"inputRows": 1000, "outputRows": 987, "rejectedRows": 13},
    "gold":   {"inputRows": 987,  "outputRows": 987}
  }
}
```

The endpoint already reads all OpenLineage JSON blobs. It just needs to:
1. Extract `outputs[0].facets.columnLineage.fields` from each event
2. Build the `column_lineage` dict keyed by column name
3. Extract `outputs[0].facets.rowStats` from each event into `row_stats`

---

### 5. `discovery/web/src/components/LineageModal.jsx` — MINOR MODIFY

Extract `LineageGraph` and `assignRanks`/`layoutGraph` into a shared utility so
`CatalogDetailModal`'s LineageTab can import them without duplicating code.

Option A (simpler): just import `LineageGraph` directly from `LineageModal.jsx`
as a named export alongside the default export.

Option B: move to `discovery/web/src/components/LineageGraph.jsx` as its own file.

**Recommendation: Option A** — add `export { LineageGraph }` to `LineageModal.jsx`,
no file moves needed.

---

## API Calls Per Tab (summary)

| Tab | API Call | Already Exists? |
|-----|----------|----------------|
| Details | None (uses node object already in memory) | ✅ Yes |
| Sample Data | `api.profileDataset(node.id)` | ✅ Yes |
| Lineage (table) | `api.lineage(node.id)` | ✅ Yes |
| Lineage (attribute) | `api.lineage(node.id)` — reads `column_lineage` field | ⚠️ Needs backend addition |
| Data Quality | `api.profileDataset(node.id)` — same call, cached | ✅ Yes |

---

## Node Shape Normalisation

`CatalogDetailModal` receives nodes from two sources with slightly different shapes:

| Field | From `HomePage` tree | From `GlossaryView` |
|-------|---------------------|---------------------|
| `id` | ✅ | ✅ |
| `name` | ✅ | ✅ |
| `type` | `'term'` / `'application'` / `'domain'` | undefined (always a term) |
| `domain` | ✅ | ✅ |
| `is_pii` | ✅ | ✅ |
| `dq_rules` | ✅ | ✅ |
| `information_type` | via `data_type` field | ✅ |
| `synonyms` | not present | ✅ |
| `children` | ✅ (BDEs under BA) | not present |

The modal normalises on mount:
```js
const type = node.type || 'term'
const datasetId = node.id  // used for profileDataset + lineage calls
```

---

## Deploy Steps (after implementation)

Only the web service needs redeploying — no engine or Dagster changes:

```bash
# From Cloud Shell:
cd ~/bt-df-lkhouse-fw
git pull origin main
gcloud builds submit --config cloudbuild-web.yaml . --project=bt-df-lkhouse
```

---

## Implementation Order

1. Add `export { LineageGraph }` to `LineageModal.jsx`
2. Enhance `/lineage/{dataset}` in `main.py` to return `column_lineage` + `row_stats`
3. Build `CatalogDetailModal.jsx` with all 4 tabs
4. Swap `DetailPanel` in `HomePage.jsx` → `CatalogDetailModal`
5. Swap side panel in `GlossaryView.jsx` → `CatalogDetailModal`
6. Commit + push + Cloud Build deploy
