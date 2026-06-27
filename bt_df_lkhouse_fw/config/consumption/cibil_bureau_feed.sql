-- cibil_bureau_feed.sql
-- Data Product: CIBIL Bureau Feed materialised from CCN
CREATE OR REPLACE TABLE `${PROJECT_ID}.lakehouse_dataproduct.cibil_bureau_feed` AS
SELECT
    customer_id,
    pan_number,
    cibil_score,
    score_date,
    enquiry_date,
    loan_amount_requested,
    number_of_accounts,
    overdue_amount,
    credit_utilization_pct,
    account_type,
    dpd_30_plus_count,
    bureau_reference_id,
    mobile_number,
    email_address,
    date_of_birth
FROM `${PROJECT_ID}.lakehouse_ccn.cibil_bureau_feed`
