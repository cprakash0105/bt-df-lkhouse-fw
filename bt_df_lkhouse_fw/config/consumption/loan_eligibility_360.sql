-- loan_eligibility_360.sql
-- Data Product: Loan Eligibility 360 view
-- Sources: customers, cibil_bureau_feed
-- Business Use Case: Mobile app loan eligibility check
CREATE OR REPLACE TABLE `${PROJECT_ID}.lakehouse_dataproduct.loan_eligibility_360` AS
SELECT
    c.customer_id,
    c.name,
    c.region,
    b.cibil_score,
    b.enquiry_date,
    b.loan_amount_requested,
    b.number_of_accounts,
    b.overdue_amount,
    CASE
        WHEN b.cibil_score >= 750 THEN 'pre_approved'
        WHEN b.cibil_score >= 650 THEN 'eligible'
        ELSE 'not_eligible'
    END AS loan_eligibility_status
FROM `${PROJECT_ID}.lakehouse_ccn.customers` c
INNER JOIN `${PROJECT_ID}.lakehouse_ccn.cibil_bureau_feed` b
    ON c.customer_id = b.customer_id
