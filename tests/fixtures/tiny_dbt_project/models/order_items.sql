-- tiny_shop.order_items: one row per line item (many per order)
select * from {{ ref('raw_order_items') }}
