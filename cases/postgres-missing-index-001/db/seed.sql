INSERT INTO customers (id, name)
SELECT id, 'customer-' || id
FROM generate_series(1, 10000) AS id;

INSERT INTO orders (customer_id, status, total_cents, created_at)
SELECT
    ((g % 10000) + 1)::integer AS customer_id,
    CASE WHEN g % 7 = 0 THEN 'refunded' ELSE 'paid' END AS status,
    ((g % 50000) + 100)::integer AS total_cents,
    now() - ((g % 365) || ' days')::interval AS created_at
FROM generate_series(1, 800000) AS g;

CREATE INDEX idx_orders_customer_id ON orders(customer_id);
ANALYZE orders;
