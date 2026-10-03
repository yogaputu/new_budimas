select 'PT_COL:' || column_name from information_schema.columns where table_schema='public' and table_name='purchase_transaksi' order by ordinal_position;
select 'TG_COL:' || column_name from information_schema.columns where table_schema='public' and table_name='purchase_tagihan' order by ordinal_position;
