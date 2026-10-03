select 'TABLE:' || table_name from information_schema.tables where table_schema='public' and table_name ilike '%user%' order by table_name;
select 'DETAIL_COL:' || column_name from information_schema.columns where table_schema='public' and table_name='purchase_order_detail' order by ordinal_position;
