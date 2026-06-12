-- tiny_shop.customers: one row per customer
select * from {{ ref('raw_customers') }}
