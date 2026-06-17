-- customer_engagement.sql
-- Customer engagement metrics from clickstream data
CREATE OR REPLACE TABLE `${PROJECT_ID}.lakehouse_dataproduct.customer_engagement` AS
SELECT
    c.customer_id,
    c.name,
    c.loyalty_tier,
    c.region,
    COALESCE(cs.total_events, 0) AS total_events,
    COALESCE(cs.page_views, 0) AS page_views,
    COALESCE(cs.product_views, 0) AS product_views,
    COALESCE(cs.add_to_carts, 0) AS add_to_carts,
    COALESCE(cs.purchases, 0) AS purchases,
    COALESCE(cs.unique_sessions, 0) AS unique_sessions,
    cs.last_activity,
    CASE
        WHEN cs.purchases > 0 THEN ROUND(cs.purchases / cs.total_events * 100, 2)
        ELSE 0
    END AS conversion_rate
FROM `${PROJECT_ID}.lakehouse_ccn.customers` c
LEFT JOIN (
    SELECT
        customer_id,
        COUNT(*) AS total_events,
        COUNTIF(event_type = 'page_view') AS page_views,
        COUNTIF(event_type = 'product_view') AS product_views,
        COUNTIF(event_type = 'add_to_cart') AS add_to_carts,
        COUNTIF(event_type = 'purchase') AS purchases,
        COUNT(DISTINCT session_id) AS unique_sessions,
        MAX(event_timestamp) AS last_activity
    FROM `${PROJECT_ID}.lakehouse_ccn.clickstream`
    GROUP BY customer_id
) cs ON c.customer_id = cs.customer_id
