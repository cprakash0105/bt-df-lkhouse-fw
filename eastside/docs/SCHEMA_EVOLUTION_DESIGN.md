# Schema Evolution — Layer-Aware Governance Framework

**Owner:** Chandra Prakash

**Platform:** CDH 2.0 (GCP — bt-df-lkhouse)

**Table Format:** Apache Iceberg (BigLake Metastore)

**Compute:** Dataproc Serverless (PySpark)

**Orchestration:** Dagster

**Last Updated:** Jul 2025

---

## Executive Summary

This design implements a governed, layer-aware schema evolution framework for Apache Iceberg tables managed through BigLake Metastore (BLMS). The framework allows source systems to evolve independently while protecting downstream curated datasets and published data products from ungoverned structural changes.

The design adopts different schema evolution policies across Bronze, Silver, and Gold layers. Bronze prioritises data preservation, Silver enforces backward compatibility, and Gold enforces data product contracts.

In addition to the core schema evolution capability, this design introduces:

- Alias-based rename handling
- Formal type compatibility matrix
- Contract version management
- Schema audit repository
- Operational alerting
- Schema quarantine workflow
- Schema ownership metadata
- Schema fingerprint optimisation
- Clear PII protection strategy

---

## 1. Schema Evolution Governance Model

### Bronze Layer

**Purpose:** Preserve exactly what source systems send and act as the immutable audit layer.

**Policy:**
- Accept new columns
- Accept dropped columns
- Accept widening changes
- Accept narrowing changes with controlled casting
- Generate alerts for suspicious changes
- Never reject incoming source data

**Guiding Principle:** Data loss is unacceptable. Governance should never prevent raw data capture.

### Silver Layer

**Purpose:** Provide curated and governed datasets suitable for downstream consumption.

**Policy:**
- Allow additive changes
- Allow widening changes
- Block destructive changes
- Maintain SCD2 integrity
- Preserve backward compatibility

**Guiding Principle:** Governance is enforced here because downstream models, joins, and historical records depend on schema stability.

### Gold Layer

**Purpose:** Publish governed data products.

**Policy:**
- Contract driven
- Version controlled
- Consumer approved
- Breaking changes require contract version upgrades

**Guiding Principle:** Consumers consume contracts, not source schemas.

---

## 2. Enhanced Schema Evolution Rules

### Change Treatment Matrix

| Change | Bronze | Silver | Gold |
|--------|--------|--------|------|
| Add Column | Auto Accept | Accept Nullable | Contract Change |
| Drop Column | Accept with Null Fill | Block | Block |
| Type Widen | Accept | Accept | Contract Change |
| Type Narrow | Accept with Alert | Block | Block |
| Rename | Alias Resolution | Alias Resolution | Contract Change |

---

## 3. Alias-Based Rename Handling

### Problem

A source column rename appears to Iceberg as:
- Column drop
- New column addition

Without additional logic, Silver pipelines fail.

### Solution

Support alias mappings within table configuration.

```yaml
schema_evolution:
  aliases:
    cust_name: customer_name
    cust_id: customer_id
```

Before schema comparison, incoming columns are mapped to their canonical names.

### Benefits

- Eliminates unnecessary failures
- Reduces operational support effort
- Preserves consumer-facing schemas

---

## 4. Formal Type Compatibility Matrix

Instead of hard-coded logic, all type promotions are centrally maintained.

```yaml
type_rules:
  widen:
    - "short -> int"
    - "int -> bigint"
    - "int -> decimal"
    - "int -> double"
    - "bigint -> decimal"
    - "bigint -> double"
    - "float -> double"
    - "decimal(10,2) -> decimal(20,2)"

  narrow:
    - "bigint -> int"
    - "double -> float"
    - "decimal -> int"
```

### Benefits

- Easier maintenance
- Business-controlled behaviour
- Consistent implementation across data products

---

## 5. Contract Versioning Framework

Gold schemas become managed contracts.

### Contract Structure

```
contracts/
 └── customer/
      ├── v1.0.0.yaml
      ├── v1.1.0.yaml
      └── v2.0.0.yaml
```

### Example

```yaml
contract:
  name: customer
  version: "2.0.0"
  status: active
  owner:
    team: retail_data
    data_steward: Chandra Prakash
  schema:
    primary_key: customer_id
    required_columns:
      - name: customer_id
        type: string
        nullable: false
      - name: email
        type: string
        nullable: true
  consumers:
    - name: retail_dashboard
      team: bi_team
  changelog:
    - version: "2.0.0"
      date: "2025-07-13"
      change: "Added loyalty_tier column (breaking — new required field)"
```

### Contract Change Process

1. Producer proposes schema change
2. Consumers review impact
3. Contract version incremented
4. Change approved
5. Gold deployment executed

### Versioning Rules

- **Patch** (1.0.1): Metadata change only (description, owner)
- **Minor** (1.1.0): Non-breaking change (new optional column)
- **Major** (2.0.0): Breaking change (column drop, type change, rename)

### Benefits

- Full auditability
- Consumer awareness
- Controlled breaking changes

---

## 6. Schema Audit Repository

Every schema event is stored in a dedicated audit table.

### Table

```
{catalog}.{namespace}.schema_change_audit
```

### Columns

| Column | Type | Description |
|--------|------|-------------|
| event_id | string | Unique event identifier |
| run_id | string | Pipeline run identifier |
| table_name | string | Affected table |
| layer | string | bronze / silver / gold |
| change_type | string | add_column / drop_column / type_widen / type_narrow / rename_mapped / contract_violation |
| column_name | string | Affected column |
| old_type | string | Previous type (empty for adds) |
| new_type | string | New type (empty for drops) |
| status | string | applied / blocked / graceful_null_fill / graceful_cast |
| event_timestamp | timestamp | When the change was detected |

### Supported Events

- `ADD_COLUMN`
- `DROP_COLUMN`
- `TYPE_WIDEN`
- `TYPE_NARROW`
- `CONTRACT_VIOLATION`
- `RENAME_MAPPED`

### Benefits

- Historical reporting
- Governance dashboards
- Audit support

---

## 7. Alerting Framework

Schema violations generate proactive notifications.

### Alert Scenarios

- Drop column detected
- Type narrowing detected
- Contract validation failure
- Unexpected rename
- Repeated schema drift

### Notification Targets

- Microsoft Teams
- Email
- ServiceNow
- PagerDuty

### Severity Levels

| Severity | Trigger |
|----------|---------|
| INFO | New column added, alias resolved |
| WARNING | Column dropped in bronze, type narrowing in bronze |
| CRITICAL | Silver blocked, contract violation, repeated drift |

---

## 8. Schema Quarantine Zone

### Purpose

Capture problematic schema changes without losing diagnostic information.

### Location

```
gs://{bucket}/schema_quarantine/{table}/{run_id}/
```

### Captured Artifacts

| Artifact | Description |
|----------|-------------|
| Source file | The raw data that triggered the violation |
| Schema diff | JSON of detected vs expected schema |
| Table name | Affected table |
| Run ID | Pipeline run identifier |
| Failure reason | Human-readable explanation |
| Event timestamp | When the violation occurred |

### Example Triggers

- Type narrowing in silver
- Contract violation in gold
- Unsupported schema mutation

### Benefits

- Faster troubleshooting
- Easier root cause analysis
- No loss of evidence
- Data available for replay once resolved

---

## 9. Metadata Ownership Model

Every table must declare ownership.

```yaml
metadata:
  business_owner: CRM Team
  technical_owner: Data Engineering Team
  steward: Data Governance Team
  support_email: crm-support@company.com
```

Schema alerts automatically route to the declared owners.

### Benefits

- Clear accountability
- Automated alert routing
- Audit trail of responsibility

---

## 10. Schema Fingerprint Optimisation

Large platforms can contain hundreds of tables. Repeated schema comparisons add catalog overhead.

### Solution

Store a schema hash after each successful run.

```json
{
  "fingerprint": "a3f2b8c1e9d04f7a",
  "columns": ["transaction_id", "store_id", "product_sku"],
  "updated_at": "2025-07-13T07:34:00Z"
}
```

### Pipeline Execution

1. Read current fingerprint from storage
2. Compute incoming fingerprint (hash of column names + types)
3. Compare hashes
4. Skip evolution checks if unchanged

### Benefits

- Reduced BLMS traffic
- Faster execution
- Lower cost
- ~90% reduction in catalog lookups for stable tables

---

## 11. PII Protection Strategy

The implementation clearly separates two protection mechanisms.

### Irreversible Protection — SHA256

**Used for:**
- Analytics
- Joins
- Deduplication

The original value cannot be recovered. Suitable for fields where the business only needs to group or match records without revealing the actual value.

### Reversible Protection — Cloud KMS (AES-256)

**Used for:**
- Operational retrieval
- Regulatory requirements
- Controlled decryption workflows

Authorised users with key access can decrypt. Suitable for fields that must be revealed under specific circumstances (fraud investigation, compliance).

### Configuration

```yaml
masking:
  email: sha256
  phone: sha256

encryption:
  pan_number: aes256
  aadhaar: aes256
```

Both are applied in the Silver layer on write. Gold inherits the protected values.

---

## 12. Enhanced Configuration Example

Complete table configuration demonstrating all schema evolution features:

```yaml
table: pos_transactions
description: "Point-of-sale line items from 50+ physical stores"
source_format: json
source_system: pos
domain: sales
business_application: retail_pos
is_cdc: false

primary_key: transaction_id
hash_fields: [transaction_id, product_sku, transaction_datetime]

metadata:
  business_owner: Retail Team
  technical_owner: Data Engineering
  steward: Data Governance
  support_email: retail-data@company.com

contract_version: "2.0.0"

dq_rules:
  not_null: [transaction_id, store_id, product_sku, quantity, unit_price]
  positive: [quantity, unit_price]

masking:
  customer_email: sha256

encryption: {}

schema_evolution:
  aliases:
    cust_name: customer_name
    txn_id: transaction_id

  bronze:
    allowed:
      - add_column
      - type_widen
      - drop_column

  silver:
    allowed:
      - add_column
      - type_widen
    blocked:
      - drop_column
      - type_narrow
    on_drop: fail
    on_narrow: fail
```

---

## 13. Operational Behaviour

### Source Adds New Column

| Layer | Behaviour |
|-------|-----------|
| Bronze | Auto accept |
| Silver | Auto add as nullable |
| Gold | Not exposed until contract update |

### Source Drops Column

| Layer | Behaviour |
|-------|-----------|
| Bronze | Null-fill, alert |
| Silver | Block, alert, write quarantine record |
| Gold | Contract violation |

### Source Renames Column

| Layer | Behaviour |
|-------|-----------|
| Bronze | Alias mapping applied |
| Silver | Alias mapping applied |
| Gold | Contract approval required |

### Source Narrows Data Type

| Layer | Behaviour |
|-------|-----------|
| Bronze | Accept, alert |
| Silver | Fail, quarantine |
| Gold | Contract violation |

---

## 14. Enterprise Architecture Principles

1. No data loss in Bronze.
2. Backward compatibility in Silver.
3. Contract governance in Gold.
4. Every schema change is auditable.
5. Every schema violation is alertable.
6. Every schema contract is versioned.
7. Every table has defined ownership.
8. Every breaking event is recoverable and traceable.

---

## 15. Final Recommendation

The enhanced design transforms schema evolution from a technical capability into an enterprise governance service.

The platform continues to leverage Apache Iceberg and BigLake Metastore for native schema evolution while adding the operational controls required for large-scale production deployment. The result is a framework that:

- **Minimises data loss** — Bronze never rejects source data
- **Protects downstream consumers** — Silver blocks destructive changes
- **Improves operational observability** — Every change is audited, alerted, and traceable
- **Enables controlled evolution** — Gold contracts give consumers confidence and control

This design is production-ready and proven on CDH 2.0 with 8 datasets across 3 layers, orchestrated by Dagster and running on Dataproc Serverless with Apache Iceberg on BigLake Metastore.
