-- tiny_shop.orders: one row per order; amount is the order total
select * from {{ ref('raw_orders') }}
