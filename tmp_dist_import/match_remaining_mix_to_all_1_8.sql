create temp table src_stok_18 (
  kode text,
  nama text,
  active text,
  principle text,
  jenis text,
  brand text,
  kodeprinciple text,
  namaprinciple text
);
\copy src_stok_18 from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/all_stok_brand_from_192_168_1_8.csv' with csv header;
create temp table remaining_mix_match as
with current_mix as (
  select p.id, p.kode_sku, p.nama, pr.kode as mix_kode, pr.nama as mix_nama, p.id_principal as old_principal_id
  from produk p
  join principal pr on pr.id = p.id_principal
  where pr.kode in ('M1','M2','M3','MFT')
), mapped as (
  select distinct on (c.id)
    c.*, nullif(trim(s.kodeprinciple),'') as source_principal_kode,
    nullif(trim(s.namaprinciple),'') as source_principal_nama,
    nullif(trim(s.principle),'') as source_mix_principle
  from current_mix c
  left join src_stok_18 s on upper(trim(s.kode)) = upper(trim(c.kode_sku))
  order by c.id, case when nullif(trim(s.kodeprinciple),'') is null then 1 else 0 end
)
select m.*, p.id as target_principal_id, p.kode as target_principal_kode, p.nama as target_principal_nama
from mapped m
left join lateral (
  select p.*
  from principal p
  where p.kode not in ('MFB','MFT','M1','M2','M3')
    and (
      upper(trim(p.kode)) = upper(trim(m.source_principal_kode))
      or regexp_replace(upper(coalesce(p.nama,'')), '[^A-Z0-9]+', '', 'g') = regexp_replace(upper(coalesce(m.source_principal_nama,'')), '[^A-Z0-9]+', '', 'g')
    )
  order by case when upper(trim(p.kode)) = upper(trim(m.source_principal_kode)) then 0 else 1 end, p.id
  limit 1
) p on true;

select mix_kode,
  case
    when source_principal_kode is null then 'tidak ketemu kode di STOK 1.8'
    when target_principal_id is null then 'source ketemu, principal target belum ada'
    else 'siap mapping otomatis'
  end as status,
  count(*) as jumlah_produk
from remaining_mix_match
group by mix_kode, status
order by mix_kode, status;

select mix_kode, source_principal_kode, source_principal_nama, target_principal_kode, target_principal_nama, count(*) as jumlah_produk, min(kode_sku) contoh_kode, min(nama) contoh_produk
from remaining_mix_match
where source_principal_kode is not null
group by mix_kode, source_principal_kode, source_principal_nama, target_principal_kode, target_principal_nama
order by mix_kode, jumlah_produk desc
limit 80;
