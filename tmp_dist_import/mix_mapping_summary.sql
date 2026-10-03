with mix_products as (
  select p.id, p.kode_sku, p.nama as produk_nama, pr.kode as mix_kode, pr.nama as mix_nama,
         pb.id as brand_id, pb.nama as brand_nama
  from produk p
  join principal pr on pr.id = p.id_principal
  left join produk_brand pb on pb.id = p.id_brand
  where pr.kode in ('MFB','MFT','M1','M2','M3')
), principal_norm as (
  select distinct on (regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g'))
    id, kode, nama, regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g') as nama_key,
    regexp_replace(upper(coalesce(kode,'')), '[^A-Z0-9]+', '', 'g') as kode_key
  from principal
  where kode not in ('MFB','MFT','M1','M2','M3') and nullif(trim(coalesce(nama,'')), '') is not null
  order by regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g'), id
), brand_summary as (
  select mix_kode, coalesce(brand_nama, '(tanpa brand)') as brand_nama, count(*) as jumlah_produk,
         regexp_replace(upper(coalesce(brand_nama,'')), '[^A-Z0-9]+', '', 'g') as brand_key
  from mix_products
  group by mix_kode, brand_nama
), mapped as (
  select b.*, coalesce(pe.id, pn.id) as kandidat_id,
         case when pe.id is not null then 'exact'
              when pn.id is not null then 'mirip'
              else 'manual' end as status
  from brand_summary b
  left join principal_norm pe on pe.nama_key = b.brand_key and b.brand_key <> ''
  left join lateral (
    select p.* from principal_norm p
    where b.brand_key <> '' and p.nama_key <> '' and length(p.nama_key) >= 6
      and (position(p.nama_key in b.brand_key) > 0 or position(b.brand_key in p.nama_key) > 0)
    order by length(p.nama_key) desc, p.id limit 1
  ) pn on true
)
select status, count(*) as grup_brand, sum(jumlah_produk) as jumlah_produk
from mapped group by status order by status;

with mix_products as (
  select p.id, p.kode_sku, p.nama as produk_nama, pr.kode as mix_kode, pr.nama as mix_nama,
         pb.id as brand_id, pb.nama as brand_nama
  from produk p
  join principal pr on pr.id = p.id_principal
  left join produk_brand pb on pb.id = p.id_brand
  where pr.kode in ('MFB','MFT','M1','M2','M3')
), principal_norm as (
  select distinct on (regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g'))
    id, kode, nama, regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g') as nama_key
  from principal
  where kode not in ('MFB','MFT','M1','M2','M3') and nullif(trim(coalesce(nama,'')), '') is not null
  order by regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g'), id
), brand_summary as (
  select mix_kode, coalesce(brand_nama, '(tanpa brand)') as brand_nama, count(*) as jumlah_produk,
         min(kode_sku) as contoh_kode, min(produk_nama) as contoh_produk,
         regexp_replace(upper(coalesce(brand_nama,'')), '[^A-Z0-9]+', '', 'g') as brand_key
  from mix_products group by mix_kode, brand_nama
), mapped as (
  select b.*, coalesce(pe.kode, pn.kode) as kandidat_kode, coalesce(pe.nama, pn.nama) as kandidat_principal,
         case when pe.id is not null then 'exact'
              when pn.id is not null then 'mirip'
              else 'manual' end as status
  from brand_summary b
  left join principal_norm pe on pe.nama_key = b.brand_key and b.brand_key <> ''
  left join lateral (
    select p.* from principal_norm p
    where b.brand_key <> '' and p.nama_key <> '' and length(p.nama_key) >= 6
      and (position(p.nama_key in b.brand_key) > 0 or position(b.brand_key in p.nama_key) > 0)
    order by length(p.nama_key) desc, p.id limit 1
  ) pn on true
)
select mix_kode, brand_nama, jumlah_produk, kandidat_kode, kandidat_principal, status, contoh_kode, contoh_produk
from mapped order by jumlah_produk desc limit 20;
