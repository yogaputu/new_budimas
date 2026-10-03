with mix as (select id, kode, nama from principal where kode in ('MFB','MFT','M1','M2','M3'))
select m.kode, m.nama, 'produk' as sumber, count(p.id)::bigint as jumlah from mix m left join produk p on p.id_principal=m.id group by m.kode,m.nama
union all
select m.kode, m.nama, 'sales_principal_assignment', count(s.id)::bigint from mix m left join sales_principal_assignment s on s.id_principal=m.id group by m.kode,m.nama
union all
select m.kode, m.nama, 'stock_transfer_detail', count(s.id)::bigint from mix m left join stock_transfer_detail s on s.id_principal=m.id group by m.kode,m.nama
union all
select m.kode, m.nama, 'log_stockopname_sales', count(s.id)::bigint from mix m left join log_stockopname_sales s on s.id_principal=m.id group by m.kode,m.nama
union all
select m.kode, m.nama, 'principal_special_rule', count(s.id)::bigint from mix m left join principal_special_rule s on s.id_principal=m.id group by m.kode,m.nama
order by kode, sumber;
