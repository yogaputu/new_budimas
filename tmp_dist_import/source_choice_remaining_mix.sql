create temp table src_stok_18 (kode text,nama text,active text,principle text,jenis text,brand text,kodeprinciple text,namaprinciple text);
\copy src_stok_18 from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/all_stok_brand_from_192_168_1_8.csv' with csv header;
create temp table src_stok_16 (kode text,nama text,active text,principle_kode text,food text,jenis text,satuan text,perunit text,nama_unit text,harga_beli text,harga_jual text,brand_kode text,brand_nama text,subbrand_kode text,subbrand_nama text,kategori_lama text,kode_ean text,master_kode text);
\copy src_stok_16 from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/dist_stok_active.csv' with csv header;
with current_mix as (
  select p.id, p.kode_sku, pr.kode as mix_kode
  from produk p join principal pr on pr.id=p.id_principal
  where pr.kode in ('M1','M3','MFT')
), source_choice as (
  select c.mix_kode,
         c.kode_sku,
         coalesce(nullif(trim(s18.kodeprinciple),''), nullif(trim(s16.brand_kode),'')) as source_kode,
         coalesce(nullif(trim(s18.namaprinciple),''), nullif(trim(s16.brand_nama),'')) as source_nama,
         case when nullif(trim(s18.kodeprinciple),'') is not null then 'sql_1_8'
              when nullif(trim(s16.brand_kode),'') is not null then 'sql_1_16'
              else 'kosong' end as sumber
  from current_mix c
  left join src_stok_18 s18 on upper(trim(s18.kode))=upper(trim(c.kode_sku))
  left join src_stok_16 s16 on upper(trim(s16.kode))=upper(trim(c.kode_sku))
)
select mix_kode, sumber, count(*) jumlah_produk
from source_choice
group by mix_kode, sumber
order by mix_kode, sumber;

select mix_kode, source_kode, source_nama, sumber, count(*) jumlah_produk, min(kode_sku) contoh_kode
from source_choice
where source_kode is not null or source_nama is not null
group by mix_kode, source_kode, source_nama, sumber
order by mix_kode, jumlah_produk desc
limit 80;
