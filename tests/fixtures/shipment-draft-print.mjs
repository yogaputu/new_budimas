export function schedule(id = 1, changes = {}) {
  return { id_proses_picking: String(id * 10 + 1), id_sales_order: String(id * 100 + 1),
    status_order: '2', id_cabang: 2, id_perusahaan: 3, nama_perusahaan: 'Perusahaan Uji',
    id_rute: id, nama_rute: `Rute ${id}`, kode_rute: `R${id}`, id_armada: id, id_driver: id,
    nama_armada: `Truk ${id}`, nama_driver: `Driver ${id}`, nama_helpers: 'Helper Uji',
    delivering_date: '2026-10-02', no_order: `SO-${id}`, nama_customer: `Toko ${id}`, sales_order_count: 1,
    dock_code: 'DOCK A', cargo_zone: 'FOOD', delivery_notes: 'Periksa jumlah barang', ...changes };
}
export function payload(row = schedule()) {
  const pickingId = Number(row.id_proses_picking), orderId = Number(row.id_sales_order);
  return { document: { branch: { id: row.id_cabang, name: 'Cabang Uji' }, route: { id: row.id_rute, name: row.nama_rute, code: row.kode_rute },
    fleet: { id: row.id_armada, name: row.nama_armada, plate: `B ${row.id_armada} UJI` }, driver: { id: row.id_driver, name: row.nama_driver },
    generated_at: '2026-10-01 17:00:00', delivering_date: '2026-10-02', source_picking_ids: [pickingId] },
    variants: [{ product_id: 9, sku: 'SKU-09', product_name: 'Produk Uji', principal_name: 'Principal Uji',
      uom: { pieces: { label: 'PCS' }, box: { label: 'BOX' }, karton: { label: 'CTN' } },
      allocations: [{ id_proses_picking: pickingId, id_order_detail: pickingId * 10, id_sales_order: orderId,
        no_order: row.no_order, customer_id: orderId, customer_code: `C-${orderId}`, customer_name: row.nama_customer,
        order_uom: { pieces: 2, box: 1, karton: 0 }, total_order_pcs: 14, draft_picked_pcs: 14 }] }] };
}
