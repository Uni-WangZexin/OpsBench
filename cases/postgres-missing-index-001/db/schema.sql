CREATE TABLE customers (
    id integer PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE orders (
    id bigserial PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers(id),
    status text NOT NULL,
    total_cents integer NOT NULL,
    created_at timestamptz NOT NULL
);
