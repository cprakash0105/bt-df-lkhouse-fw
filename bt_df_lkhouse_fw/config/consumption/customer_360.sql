-- customer_360.sql
-- Customer 360: full customer view with order and payment aggregations
-- Reads from CCN (Iceberg via linked dataset), writes to Data Product (BQ native)
CREATE OR REPLACE TABLE `${PROJECT_ID}.lakehouse_dataproduct.customer_360` AS
SELECT
    c.customer_id,
    c.name,
    c.email,
    c.region,
    c.loyalty_tier,
    c.signup_date,
    c.is_active,
    COALESCE(o.total_orders, 0) AS total_orders,
    COALESCE(o.total_spend, 0.0) AS total_spend,
    COALESCE(o.avg_order_value, 0.0) AS avg_order_value,
    o.first_order_date,
    o.last_order_date,
    COALESCE(o.total_discounts, 0.0) AS total_discounts,
    COALESCE(p.total_payments, 0) AS total_payments,
    COALESCE(p.total_paid, 0.0) AS total_paid
FROM `${PROJECT_ID}.lakehouse_ccn.customers` c
LEFT JOIN (
    SELECT
        customer_id,
        COUNT(*) AS total_orders,
        SUM(total_amount) AS total_spend,
        AVG(total_amount) AS avg_order_value,
        MIN(order_date) AS first_order_date,
        MAX(order_date) AS last_order_date,
        SUM(discount_amount) AS total_discounts
    FROM `${PROJECT_ID}.lakehouse_ccn.orders`
    GROUP BY customer_id
) o ON c.customer_id = o.customer_id
LEFT JOIN (
    SELECT
        ord.customer_id,
        COUNT(*) AS total_payments,
        SUM(pay.amount) AS total_paid
    FROM `${PROJECT_ID}.lakehouse_ccn.payments` pay
    JOIN `${PROJECT_ID}.lakehouse_ccn.orders` ord ON pay.order_id = ord.order_id
    GROUP BY ord.customer_id
) p ON c.customer_id = p.customer_id
