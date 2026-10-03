\copy (
with mix_products as (
  select
    p.id,
    p.kode_sku,
    p.nama as produk_nama,
    pr.kode as mix_kode,
    pr.nama as mix_nama,
    pb.id as brand_id,
    pb.nama as brand_nama,
    ps.id as subbrand_id,
    ps.nama as subbrand_nama
  from produk p
  join principal pr on pr.id = p.id_principal
  left join produk_brand pb on pb.id = p.id_brand
  left join produk_subbrand ps on ps.id = p.id_subbrand
  where pr.kode in ('MFB','MFT','M1','M2','M3')
), principal_norm as (
  select distinct on (regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g'))
    id,
    kode,
    nama,
    regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g') as nama_key,
    regexp_replace(upper(coalesce(kode,'')), '[^A-Z0-9]+', '', 'g') as kode_key
  from principal
  where kode not in ('MFB','MFT','M1','M2','M3')
    and nullif(trim(coalesce(nama,'')), '') is not null
  order by regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g'), id
), principal_code_norm as (
  select distinct on (regexp_replace(upper(coalesce(kode,'')), '[^A-Z0-9]+', '', 'g'))
    id,
    kode,
    nama,
    regexp_replace(upper(coalesce(nama,'')), '[^A-Z0-9]+', '', 'g') as nama_key,
    regexp_replace(upper(coalesce(kode,'')), '[^A-Z0-9]+', '', 'g') as kode_key
  from principal
  where kode not in ('MFB','MFT','M1','M2','M3')
    and nullif(trim(coalesce(kode,'')), '') is not null
  order by regexp_replace(upper(coalesce(kode,'')), '[^A-Z0-9]+', '', 'g'), id
), brand_summary as (
  select
    mix_kode,
    mix_nama,
    brand_id,
    coalesce(brand_nama, '(tanpa brand)') as brand_nama,
    count(*) as jumlah_produk,
    min(kode_sku) as contoh_kode,
    min(produk_nama) as contoh_produk,
    regexp_replace(upper(coalesce(brand_nama,'')), '[^A-Z0-9]+', '', 'g') as brand_key
  from mix_products
  group by mix_kode, mix_nama, brand_id, brand_nama
), mapped as (
  select
    b.mix_kode,
    b.mix_nama,
    b.brand_nama,
    b.jumlah_produk,
    b.contoh_kode,
    b.contoh_produk,
    coalesce(pe.id, pc.id, pn.id) as kandidat_id_principal,
    coalesce(pe.kode, pc.kode, pn.kode) as kandidat_kode,
    coalesce(pe.nama, pc.nama, pn.nama) as kandidat_principal,
    case
      when pe.id is not null then 'TINGGI: exact nama principal'
      when pc.id is not null then 'TINGGI: exact kode principal'
      when pn.id is not null then 'SEDANG: nama mirip/mengandung brand'
      else 'KOSONG: perlu mapping manual'
    end as status_mapping
  from brand_summary b
  left join principal_norm pe on pe.nama_key = b.brand_key and b.brand_key <> ''
  left join principal_code_norm pc on pc.kode_key = b.brand_key and b.brand_key <> ''
  left join lateral (
    select p.*
    from principal_norm p
    where b.brand_key <> ''
      and p.nama_key <> ''
      and length(p.nama_key) >= 6
      and (position(p.nama_key in b.brand_key) > 0 or position(b.brand_key in p.nama_key) > 0)
    order by length(p.nama_key) desc, p.id
    limit 1
  ) pn on true
)
select * from mapped
order by jumlah_produk desc, mix_kode, brand_nama
) to 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/mix_principal_mapping_preview.csv' with csv header;

