create temp table src_principle(kode text);
\copy src_principle from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/source_principle_codes.csv' with csv header;
create temp table src_stok_active(kode text);
\copy src_stok_active from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/source_stok_codes_active.csv' with csv header;
with sp as (select distinct trim(kode) kode from src_principle where nullif(trim(kode),'') is not null),
     ss as (select distinct trim(kode) kode from src_stok_active where nullif(trim(kode),'') is not null),
     tp as (select distinct trim(kode) kode from principal where nullif(trim(kode),'') is not null),
     ts as (select distinct trim(kode_sku) kode from produk where nullif(trim(kode_sku),'') is not null)
select 'principal_distinct' metric, count(*) total, count(tp.kode) already_exists, count(*) - count(tp.kode) missing from sp left join tp using(kode)
union all
select 'produk_active_distinct', count(*), count(ts.kode), count(*) - count(ts.kode) from ss left join ts using(kode);
select 'source_principle_duplicate_codes' metric, count(*) from (select kode from src_principle group by kode having count(*) > 1) d
union all
select 'source_stok_active_duplicate_codes', count(*) from (select kode from src_stok_active group by kode having count(*) > 1) d
union all
select 'target_principal_duplicate_codes', count(*) from (select trim(kode) from principal where nullif(trim(kode),'') is not null group by trim(kode) having count(*) > 1) d
union all
select 'target_produk_duplicate_codes', count(*) from (select trim(kode_sku) from produk where nullif(trim(kode_sku),'') is not null group by trim(kode_sku) having count(*) > 1) d;
