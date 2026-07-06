# Knowledge Catalog — Design Update

## Current State (What Works)

| Relationship | Link Type | KC UI Rendering |
|---|---|---|
| BA → BDE | `definition` | ✅ Shows as "Glossary Terms" section on BA entry page |
| Domain → BA | `related` | ❌ Links exist in API but no UI rendering |
| CFU → Domain | `related` | ❌ Links exist in API but no UI rendering |

## Key Finding

Google Knowledge Catalog (Dataplex) renders `definition` link types as "Glossary Terms" on entry pages. But `related` link types have NO visual representation in the current UI (as of June 2026). They exist in the API but are invisible to users.

This means:
- ✅ Click BA → see BDEs (works via definition links)
- ❌ Click CFU → see Domains (related links not rendered)
- ❌ Click Domain → see BAs (related links not rendered)
- ❌ Tree/hierarchy view (doesn't exist in KC)

## Options

### Option A: Accept the Limitation
- BA→BDE navigation works (the most important link)
- Users manually navigate entries in the flat catalog list
- Use entry descriptions to indicate hierarchy ("Domain: Credit")
- **Pros:** No extra work. KC handles BDE linking.
- **Cons:** No tree navigation for CFU→Domain→BA

### Option B: Use Entry Groups as Hierarchy
- Create separate Entry Groups per CFU or per Domain
- e.g., `entryGroups/consumer-banking-credit` contains only Credit domain BAs
- KC UI shows entries grouped by Entry Group
- **Pros:** Visual grouping in KC
- **Cons:** Entries can only belong to one group, complex to manage

### Option C: Use Aspects for Hierarchy Metadata
- Attach custom Aspects to each entry: `parent_cfu`, `parent_domain`
- KC shows Aspects on entry pages
- Enables filtering/searching by aspect value
- **Pros:** Visible metadata on each entry, searchable
- **Cons:** Still not a tree view, but at least shows "belongs to"

### Option D: Build Tree View in SD UI
- Add `hierarchy` command to Chainlit
- Reads from enterprise_hierarchy.yaml config
- Renders ASCII tree or Markdown tree
- **Pros:** Instant, full tree, no KC dependency
- **Cons:** Separate from KC

### Option E: Wait for Google
- EntryLinks API exists, KC UI may add rendering in future
- Google is actively developing KC (formerly Dataplex Universal Catalog)
- Related links might get UI support in next quarter
- **Pros:** No work, native integration
- **Cons:** Unknown timeline

## Recommended Approach

**Short term:** Option A + Option D
- Accept KC shows BA→BDE only (that's the key business value)
- Add tree view in SD for the full hierarchy (quick win)
- Use entry descriptions for context

**Medium term:** Option C
- Add Aspects to entries with hierarchy metadata
- Enables KC search: "show all BAs in Credit domain"

**Long term:** Option E
- Monitor KC UI updates
- Related link rendering will likely come

## What This Means for the White Paper

The white paper claims "interactive navigation" — which is partially true:
- BA → BDE: ✅ Interactive (click-through in KC)
- Full hierarchy: ❌ Not interactive in KC yet

**Recommendation for white paper:** 
- Show the BA→BDE screenshot as proof
- Describe the full hierarchy as "API-level relationships" that enable programmatic traversal
- Note that KC's UI is evolving and will render these relationships natively in future releases
- The SD UI provides the tree view for human navigation today

## API Reference (for future implementation)

### List EntryLinks for an entry:
```bash
curl -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://dataplex.googleapis.com/v1/projects/978009776592/locations/europe-west2/entryGroups/enterprise-hierarchy/entryLinks/ba-credit-bureau-integration-to-bde-credit-score"
```

### EntryLink structure:
```json
{
  "entryLinkType": "projects/655216118709/locations/global/entryLinkTypes/definition",
  "entryReferences": [
    {"name": "...entries/credit_bureau_integration", "type": "SOURCE"},
    {"name": "...@dataplex/entries/.../terms/credit_score", "type": "TARGET"}
  ]
}
```

### Link types available:
- `definition` — renders as "Glossary Terms" on source entry ✅
- `related` — exists in API, no UI rendering ❌
- `origin` — for lineage (not tested)
