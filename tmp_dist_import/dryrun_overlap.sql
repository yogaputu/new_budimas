create temp table src_principle(kode text);
\copy src_principle from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/source_principle_codes.csv' with csv header;
create temp table src_stok_all(kode text);
\copy src_stok_all from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/source_stok_codes_all.csv' with csv header;
create temp table src_stok_active(kode text);
\copy src_stok_active from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/source_stok_codes_active.csv' with csv header;
select 'principal_source' metric, count(*) total, count(p.id) already_exists, count(*) - count(p.id) missing
from src_principle s left join principal p on trim(p.kode)=trim(s.kode)
union all
select 'produk_source_all', count(*), count(p.id), count(*) - count(p.id)
from src_stok_all s left join produk p on trim(p.kode_sku)=trim(s.kode)
union all
select 'produk_source_active', count(*), count(p.id), count(*) - count(p.id)
from src_stok_active s left join produk p on trim(p.kode_sku)=trim(s.kode);
