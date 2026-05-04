-- Finance view 1: total revenue per store per day
CREATE OR REPLACE VIEW reports.daily_revenue_by_store AS
SELECT
    DATE(f.transaction_ts)          AS sale_date,
    s.store_id,
    s.store_name,
    s.region,
    COUNT(DISTINCT f.transaction_id) AS transaction_count,
    SUM(f.quantity)                  AS units_sold,
    SUM(f.revenue)                   AS total_revenue
FROM core.fact_sales f
JOIN core.dim_store s ON f.store_id = s.store_id
GROUP BY 1, 2, 3, 4;


-- Finance view 2: top products by revenue with daily rank
CREATE OR REPLACE VIEW reports.top_products AS
SELECT
    DATE(f.transaction_ts) AS sale_date,
    p.product_id,
    p.product_name,
    p.category,
    SUM(f.quantity)        AS units_sold,
    SUM(f.revenue)         AS total_revenue,
    RANK() OVER (
        PARTITION BY DATE(f.transaction_ts)
        ORDER BY SUM(f.revenue) DESC
    )                      AS revenue_rank
FROM core.fact_sales f
JOIN core.dim_product p ON f.product_id = p.product_id
GROUP BY 1, 2, 3, 4;


-- Finance view 3: day-over-day revenue change
CREATE OR REPLACE VIEW reports.day_over_day AS
WITH daily AS (
    SELECT
        DATE(transaction_ts) AS sale_date,
        SUM(revenue)         AS revenue
    FROM core.fact_sales
    GROUP BY 1
)
SELECT
    sale_date,
    revenue,
    LAG(revenue) OVER (ORDER BY sale_date)                              AS prior_day_revenue,
    revenue - LAG(revenue) OVER (ORDER BY sale_date)                    AS day_over_day_change,
    ROUND(
        100.0 * (revenue - LAG(revenue) OVER (ORDER BY sale_date))
        / NULLIF(LAG(revenue) OVER (ORDER BY sale_date), 0),
        2
    )                                                                    AS pct_change
FROM daily;
