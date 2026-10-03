create temp table src_mfb_18 (
  kode text,
  nama text,
  active text,
  principle text,
  jenis text,
  kodeprinciple text,
  namaprinciple text
);
\copy src_mfb_18 from 'D:/laragon/www/budimas/new_budimas/tmp_dist_import/mfb_principle_from_192_168_1_8.csv' with csv header;
create temp table mfb_principal_match as
with current_mfb as (
  select p.id, p.kode_sku, p.nama, pr.kode as current_principal_kode
  from produk p
  join principal pr on pr.id = p.id_principal
  where pr.kode = 'MFB'
), mapped as (
  select c.id, c.kode_sku, c.nama,
         nullif(trim(s.kodeprinciple), '') as source_principal_kode,
         nullif(trim(s.namaprinciple), '') as source_principal_nama
  from current_mfb c
  left join src_mfb_18 s on upper(trim(s.kode)) = upper(trim(c.kode_sku))
)
select m.*, p.id as target_principal_id, p.kode as target_principal_kode, p.nama as target_principal_nama
from mapped m
left join lateral (
  select p.*
  from principal p
  where p.kode not in ('MFB','MFT','M1','M2','M3')
    and (
      upper(trim(p.kode)) = upper(trim(m.source_principal_kode))
      or regexp_replace(upper(p.nama), '[^A-Z0-9]+', '', 'g') = regexp_replace(upper(m.source_principal_nama), '[^A-Z0-9]+', '', 'g')
    )
  order by case when upper(trim(p.kode)) = upper(trim(m.source_principal_kode)) then 0 else 1 end, p.id
  limit 1
) p on true;

select source_principal_kode, source_principal_nama, target_principal_kode, target_principal_nama, count(*) as jumlah_produk, min(kode_sku) as contoh_kode, min(nama) as contoh_produk
from mfb_principal_match
where source_principal_kode is not null
group by source_principal_kode, source_principal_nama, target_principal_kode, target_principal_nama
order by jumlah_produk desc
limit 50;
