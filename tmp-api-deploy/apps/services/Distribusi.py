from flask import jsonify, request, current_app
from sqlalchemy.exc import IntegrityError
from apps import native_db as DB
from sqlalchemy import bindparam, text
import time
import random
import re
from apps.lib.helper import datetime_now, date_now, time_now, format_angka, format_rupiah, status_order, date_now_obj
from apps.models import (
    Plafon as Plafon,
    proses_picking as prosesPicking,
    faktur as Faktur,
    sales_order,
    sales_order_detail,
    Stok, draft_voucher, Customer, Plafon, setoran, Cabang, Principal, Perusahaan, faktur, faktur_detail,
    order_batch
)

from apps.models.faktur import faktur as Faktur
from apps.models.faktur import faktur

from apps.models.Plafon import Plafon
from apps.models.Plafon import Plafon as plafon

from apps.models.SalesOrder import sales_order
from apps.models.SalesOrderDetail import sales_order_detail
from apps.models.Stok import Stok
from apps.models.Stok import Stok as stok
from apps.models.Customer import Customer as customer
from apps.models.setoran import setoran as SetoranModel

from apps.models.draft_voucher import draft_voucher
from apps.models.order_batch import OrderBatchModel
from apps.models.UserHelper import UserHelper


from apps.handler import handle_error, handle_error_rollback, nonServerErrorException
from datetime import timedelta, time, datetime, date
from . import BaseServices
from apps.services.InventoryLedger import InventoryLedgerService
import bcrypt

from ..lib.paginateV2 import PaginateV2
from ..models.faktur_detail import FakturDetailModel


# from .. import redis_cache


class Distribusi(BaseServices):
    def __init__(self):
        super().__init__()

        is_periode_close, next_date = self.check_is_periode_closed()

        if is_periode_close:
            self.current_date = next_date.strftime("%Y-%m-%d")
        else:
            self.current_date = date_now()

        self.before_this_date_query = (
            f"and sales_order.tanggal_order <= '{self.current_date}'"
            if self.is_production
            else ''
        )
        self.before_this_date_query_so = (
            f"and so.tanggal_order <= '{self.current_date}'"
            if self.is_production
            else ''
        )

    def _normalize_delivery_date(self, value):
        if value in (None, '', 'None'):
            return value
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d')
        if isinstance(value, date):
            return value.strftime('%Y-%m-%d')

        text_value = str(value).strip()
        if text_value in ('', 'None'):
            return text_value

        iso_match = re.search(r'\d{4}-\d{2}-\d{2}', text_value)
        if iso_match:
            return iso_match.group(0)

        month_map = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }
        browser_date = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', text_value)
        if browser_date:
            day = int(browser_date.group(1))
            month = month_map.get(browser_date.group(2).lower())
            year = int(browser_date.group(3))
            if month:
                return date(year, month, day).strftime('%Y-%m-%d')

        try:
            return datetime.strptime(text_value[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
        except (TypeError, ValueError):
            raise nonServerErrorException("Format tanggal pengiriman tidak valid", 400)

    def _resolve_id_cabang(self, fallback_param='id_cabang'):
        id_cabang = self.req(fallback_param)
        if id_cabang not in (None, '', 'None'):
            return int(id_cabang)

        token = request.headers.get('Authorization')
        if token:
            token = token.replace('Bearer ', '')
            user = (
                self.query()
                .setRawQuery("SELECT id_cabang FROM users WHERE tokens = :token")
                .bindparams({'token': token})
                .execute()
                .fetchone()
            )
            if user and user.result and user.result.get('id_cabang') is not None:
                return int(user.result['id_cabang'])

        return None

    def _safe_number(self, value, default=0):
        if value in (None, '', 'None'):
            return default

        try:
            return format_angka(value)
        except Exception:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

    def __product_ppn_rates(self, product_ids):
        ids = sorted({int(item) for item in product_ids if str(item or '').isdigit()})
        if not ids:
            return {}

        rows = DB.session.execute(
            text("""
                SELECT
                    p.id,
                    COALESCE(mp.persentase, p.ppn, 0) AS ppn_rate
                FROM produk p
                LEFT JOIN master_ppn mp ON mp.id = p.id_ppn
                WHERE p.id IN :ids
            """).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids}
        ).mappings().all()

        return {int(row.get("id")): self._safe_number(row.get("ppn_rate")) for row in rows}

    def __apply_product_ppn_to_revision_details(self, detail_produk_list):
        rates = self.__product_ppn_rates([item.get('id_produk') for item in detail_produk_list or []])

        for item in detail_produk_list or []:
            action = str(item.get('action') or item.get('_action') or 'update').lower()
            if action == 'delete':
                item['ppn'] = 0
                continue

            id_produk = item.get('id_produk')
            rate = rates.get(int(id_produk)) if str(id_produk or '').isdigit() else 0
            subtotal = self._safe_number(item.get('subtotal', 0))
            total_diskon = self._safe_number(item.get('total_diskon', 0))
            item['ppn_rate'] = rate
            item['ppn'] = max(subtotal - total_diskon, 0) * rate / 100

        return detail_produk_list or []

    def __revision_payment_totals_from_details(self, detail_produk_list):
        active = [
            item for item in (detail_produk_list or [])
            if str(item.get('action') or item.get('_action') or 'update').lower() != 'delete'
        ]
        subtotal = sum(self._safe_number(item.get('subtotal', 0)) for item in active)
        diskon = sum(self._safe_number(item.get('total_diskon', 0)) for item in active)
        pajak = sum(self._safe_number(item.get('ppn', 0)) for item in active)
        return {
            'subtotal': subtotal,
            'diskon_nota': diskon,
            'pajak': pajak,
            'total_penjualan': subtotal - diskon + pajak
        }

    def _normalize_uom_conversion(self, value, level=1):
        converted = int(self._safe_number(value, 0))
        if level == 1:
            return converted if converted > 0 else 1
        return converted if converted > 1 else 0

    def _default_picked_total_for_detail(self, detail):
        conversions = {1: 1}
        rows = DB.session.execute(
            text("""
                SELECT level, faktor_konversi
                FROM produk_uom
                WHERE id_produk = :id_produk
                ORDER BY level ASC
            """),
            {"id_produk": detail.id_produk}
        ).mappings().all()

        for row in rows:
            try:
                level = int(row.get("level") or 0)
                factor = int(row.get("faktor_konversi") or 1)
            except (TypeError, ValueError, AttributeError):
                continue

            if level:
                conversions[level] = factor

        pieces = (detail.pieces_booked or 0) * conversions.get(1, 1)
        box = (detail.box_booked or 0) * conversions.get(2, 1)
        karton = (detail.karton_booked or 0) * conversions.get(3, 1)

        return int(pieces + box + karton)

    def _upsert_schedule_pickings_for_detail(
        self,
        detail,
        id_driver,
        id_armada,
        id_helper,
        tanggal_pengiriman,
        default_picked=None,
        overwrite_picked=False
    ):
        pickings = prosesPicking.query.filter(
            prosesPicking.id_order_detail == detail.id
        ).all()

        if not pickings:
            picking = prosesPicking(
                id_order_detail=detail.id,
                id_produk=detail.id_produk
            )
            self.add(picking)
            pickings = [picking]

        for picking in pickings:
            picking.id_driver = id_driver
            picking.id_helper = id_helper
            picking.id_armada = id_armada
            picking.delivering_date = tanggal_pengiriman

            if default_picked is not None and (overwrite_picked or picking.jumlah_picked in (None, 0)):
                picking.jumlah_picked = default_picked

        self.flush()
        return pickings

    def _normalize_query_rows(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("result", "data", "items", "rows"):
                if isinstance(value.get(key), list):
                    return value.get(key)
            return []
        if hasattr(value, "_mapping"):
            return [dict(value._mapping)]
        return []

    def _split_total_to_uom(self, total_pieces, konversi1=1, konversi2=0, konversi3=0):
        remaining = int(self._safe_number(total_pieces, 0))
        konversi1 = self._normalize_uom_conversion(konversi1, 1)
        konversi2 = self._normalize_uom_conversion(konversi2, 2)
        konversi3 = self._normalize_uom_conversion(konversi3, 3)

        karton = 0
        if konversi3:
            karton = remaining // konversi3
            remaining %= konversi3

        box = 0
        if konversi2:
            box = remaining // konversi2
            remaining %= konversi2

        pieces = remaining // konversi1 if konversi1 else remaining

        return {
            "pieces": int(pieces),
            "box": int(box),
            "karton": int(karton),
        }

    def _uom_total_pieces(self, pieces=0, box=0, karton=0, konversi1=1, konversi2=0, konversi3=0):
        konversi1 = self._normalize_uom_conversion(konversi1, 1)
        konversi2 = self._normalize_uom_conversion(konversi2, 2)
        konversi3 = self._normalize_uom_conversion(konversi3, 3)

        return (
            int(self._safe_number(pieces, 0)) * konversi1 +
            int(self._safe_number(box, 0)) * (konversi2 or 0) +
            int(self._safe_number(karton, 0)) * (konversi3 or 0)
        )

    @handle_error
    # @redis_cache.multi_cached(['sales_order', 'faktur', 'customer', 'plafon', 'principal'], 'getListOrderKonfirmasi')
    def getListOrderKonfirmasi(self):
        id_cabang = self._resolve_id_cabang('id_cabang')
        if id_cabang in (None, '', 'None'):
            raise nonServerErrorException("ID cabang tidak ditemukan", 400)

        query_single_principal = """
            SELECT
                sales_order.id AS id_sales_order,
                faktur.no_faktur,
                sales_order.no_order,
                customer.id AS id_customer,
                customer.kode AS kode_customer,
                customer.nama AS nama_customer,
                customer.npwp AS npwp,
                customer.status_pajak AS status_pajak,
                customer.jenis_identitas_pajak AS jenis_identitas_pajak,
                principal.kode AS kode_principal,
                COALESCE(faktur.total_penjualan, sales_order.total_order, 0) AS total_bayar,
                faktur.status_faktur,
                sales_order.tanggal_order,
                COALESCE(users.nama, plafon_user.nama, sales_order.nama_sales) AS nama_sales
            FROM sales_order
            JOIN faktur ON sales_order.id = faktur.id_sales_order
            JOIN plafon ON plafon.id = sales_order.id_plafon
            JOIN customer ON plafon.id_customer = customer.id
            JOIN principal ON plafon.id_principal = principal.id
            LEFT JOIN sales ON plafon.id_sales = sales.id
            LEFT JOIN users ON sales.id_user = users.id
            LEFT JOIN users AS plafon_user ON plafon.id_user = plafon_user.id
            WHERE COALESCE(sales_order.id_cabang, customer.id_cabang) = :id_cabang
              AND sales_order.status_order = 0
              AND sales_order.id_order_batch IS NULL
            ORDER BY sales_order.tanggal_order DESC, sales_order.id DESC;
        """

        query_multiple_principal = """
            SELECT
                array_agg(sales_order.id) AS id_sales_order,
                array_agg(DISTINCT sales_order.no_order) AS no_order,
                faktur.no_faktur,
                customer.id AS id_customer,
                customer.kode AS kode_customer,
                customer.nama AS nama_customer,
                customer.npwp AS npwp,
                customer.status_pajak AS status_pajak,
                customer.jenis_identitas_pajak AS jenis_identitas_pajak,
                'MIX' AS kode_principal,
                faktur.total_penjualan AS total_bayar,
                faktur.status_faktur,
                order_batch.tanggal_submit AS tanggal_order,
                order_batch.id AS id_order_batch,
                COALESCE(users.nama, plafon_user.nama, sales_order.nama_sales) AS nama_sales
            FROM sales_order
            JOIN order_batch ON order_batch.id = sales_order.id_order_batch
            JOIN faktur_detail ON faktur_detail.id_sales_order = sales_order.id
            JOIN faktur ON faktur_detail.id_faktur = faktur.id
            JOIN plafon ON plafon.id = sales_order.id_plafon
            JOIN customer ON plafon.id_customer = customer.id
            JOIN principal ON plafon.id_principal = principal.id
            LEFT JOIN sales ON plafon.id_sales = sales.id
            LEFT JOIN users ON sales.id_user = users.id
            LEFT JOIN users AS plafon_user ON plafon.id_user = plafon_user.id
            WHERE COALESCE(sales_order.id_cabang, customer.id_cabang) = :id_cabang
            AND sales_order.status_order = 0
            GROUP BY faktur.no_faktur, customer.id, customer.kode, customer.nama,
                    customer.npwp, customer.status_pajak, customer.jenis_identitas_pajak,
                    faktur.total_penjualan, faktur.status_faktur,
                    COALESCE(users.nama, plafon_user.nama, sales_order.nama_sales),
                    order_batch.id, order_batch.tanggal_submit
        """

        data_order_single_principal = (
            self.query()
            .setRawQuery(query_single_principal)
            .bindparams({'id_cabang': id_cabang})
            .execute()
            .fetchall()
            .result or []
        )

        data_order_multiple_principal = (
            self.query()
            .setRawQuery(query_multiple_principal)
            .bindparams({'id_cabang': id_cabang})
            .execute()
            .fetchall()
            .result or []
        )

        data_all_orders = data_order_single_principal + data_order_multiple_principal

        def normalize_date(value):
            if isinstance(value, (list, tuple)) and value:
                value = value[0]

            if isinstance(value, date):
                return value

            if isinstance(value, str):
                try:
                    return datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    return date.min

            return date.min


        sorted_data_all_orders = sorted(
            data_all_orders,
            key=lambda data: normalize_date(data['tanggal_order']),
            reverse=True
        )

        # convert Row -> dict
        result = [dict(row._mapping) for row in sorted_data_all_orders]

        return result

    def __is_empty_tax_identity(self, value):
        normalized = str(value or '').strip().lower()
        return normalized in ('', '-', '0', 'null', 'none', 'n/a', 'na')

    def __tax_identity_label(self, row):
        identity_type = str((row or {}).get('jenis_identitas_pajak') or '').strip().lower()
        if identity_type == 'nik':
            return 'NIK'
        if identity_type == 'lain_lain':
            return 'NPWP/NIK'
        status_pajak = str((row or {}).get('status_pajak') or '').strip().lower()
        return 'NIK' if status_pajak == 'non_pkp' else 'NPWP'

    def __validate_customer_tax_identity_for_sales_orders(self, sales_order_ids):
        ids = [int(value) for value in (sales_order_ids or []) if value not in (None, '', 'None')]
        if not ids:
            raise nonServerErrorException("Sales order tidak ditemukan untuk validasi NPWP/NIK customer.", 400)

        missing = []
        for id_sales_order in ids:
            row = self.db.session.execute(text("""
                SELECT
                    so.id AS id_sales_order,
                    c.kode AS kode_customer,
                    c.nama AS nama_customer,
                    c.npwp,
                    c.status_pajak,
                    c.jenis_identitas_pajak
                FROM sales_order so
                JOIN plafon p ON p.id = so.id_plafon
                JOIN customer c ON c.id = p.id_customer
                WHERE so.id = :id_sales_order
                LIMIT 1
            """), {"id_sales_order": id_sales_order}).mappings().first()

            if not row:
                missing.append(f"SO {id_sales_order}")
                continue

            data = dict(row)
            if self.__is_empty_tax_identity(data.get('npwp')):
                label = self.__tax_identity_label(data)
                customer_name = " - ".join(
                    part for part in [data.get('kode_customer'), data.get('nama_customer')] if part
                ) or f"SO {id_sales_order}"
                missing.append(f"{customer_name} ({label})")

        if missing:
            raise nonServerErrorException(
                "NPWP/NIK customer masih kosong: " + ", ".join(missing) +
                ". Lengkapi dulu di Master Customer sebelum konfirmasi order.",
                400
            )


    @handle_error_rollback
    def konfirmasiOrder(self, status):
        # Ambil data mentah tanpa di-cast ke int dulu
        raw_id_batch = self.req('id_order_batch')
        
        # Jika id_order_batch ada isinya (bukan None atau string kosong)
        if raw_id_batch and str(raw_id_batch).strip() != "":
            try:
                id_order_batch = int(raw_id_batch)
                return self.__konfirmasi_order_multiple_principal(id_order_batch, status)
            except (ValueError, TypeError):
                return {"status": "error", "message": "Invalid batch ID format"}, 400
        else:
            return self.__konfirmasi_order_single_principal(status)

    def __products_by_id_sales_order(self, products):
        product_dict = {}
        for product in products:
            id_sales_order = product.get('id_sales_order')
            if id_sales_order not in product_dict:
                product_dict[id_sales_order] = []
            product_dict[id_sales_order].append(product)
        return product_dict

    def __konfirmasi_order_multiple_principal(self, id_order_batch, status):
        # Only get id_cabang if status is 1 (konfirmasi), not for status -1 (tolak)
        id_cabang = int(self.req('id_cabang')) if status == 1 else None
        vouchers = self.req('vouchers')
        update_faktur = db.session.query(Faktur).filter(Faktur.id_order_batch == int(id_order_batch)).first()
        products = self.req('products')
        products_by_sales_order = self.__products_by_id_sales_order(products)
        sales_orders = sales_order.query.with_entities(sales_order.id).filter(sales_order.id_order_batch == int(id_order_batch)).all()

        if status == 1:
            self.__validate_customer_tax_identity_for_sales_orders([so.id for so in sales_orders])

        for so in sales_orders:
            id_sales_order = so.id
            update_sales_order = sales_order.query.filter(sales_order.id == id_sales_order).first()
            update_sales_order.status_order = status
            self.add(update_sales_order)

        if status == 1:  # Booked
            total_penjualan = self._safe_number(self.req('total_penjualan'))
            subtotal_diskon = self._safe_number(self.req('subtotal_diskon'))
            dpp = self._safe_number(self.req('dpp'))
            pajak = self._safe_number(self.req('pajak'))

            update_faktur.total_penjualan = total_penjualan
            update_faktur.draft_total_penjualan = total_penjualan
            update_faktur.subtotal_diskon = subtotal_diskon
            update_faktur.dpp = dpp
            update_faktur.pajak = pajak

            self.add(update_faktur)

            for so in sales_orders:
                id_sales_order = so.id
                sales_order_products = products_by_sales_order.get(id_sales_order, [])

                pajak_by_sales_order = sum(
                    self._safe_number(product.get('subtotalorder')) * (self._safe_number(product.get('ppn')) / 100)
                    for product in sales_order_products
                )

                subtotal_penjualan_by_sales_order = sum(
                    self._safe_number(product.get('subtotalorder'))
                    for product in sales_order_products
                )

                subtotal_diskon_by_sales_order = sum(
                    sum(self._safe_number(product.get(field)) for field in
                        ['v1r_diskon', 'v2p_diskon', 'v2r_diskon', 'v3r_diskon', 'v3p_diskon'])
                    for product in sales_order_products
                )

                total_penjualan_by_sales_order = subtotal_penjualan_by_sales_order + pajak_by_sales_order

                plafon_data = plafon.query.filter(plafon.id == update_sales_order.id_plafon).first()
                if plafon_data and plafon_data.sisa_bon is not None:
                    # Validasi lock_order
                    if plafon_data.lock_order == '1':
                        # Jika lock_order = 1, sisa_bon harus sama dengan limit_bon
                        if float(plafon_data.sisa_bon) != float(plafon_data.limit_bon):
                            return {
                                "status": "error",
                                "message": f"Plafon dalam status lock. Sisa bon (Rp {format_rupiah(plafon_data.sisa_bon)}) harus sama dengan limit bon (Rp {format_rupiah(plafon_data.limit_bon)}) untuk melanjutkan transaksi."
                            }, 400

                    if float(total_penjualan_by_sales_order) > float(plafon_data.sisa_bon):
                        return {
                            "status": "error",
                            "message": f"Total penjualan (Rp {format_rupiah(total_penjualan_by_sales_order)}) melebihi sisa plafon (Rp {format_rupiah(plafon_data.sisa_bon)}). Transaksi tidak dapat dilanjutkan."
                        }, 400

                    # Potong sisa_bon dengan total_penjualan
                    plafon_data.sisa_bon = float(plafon_data.sisa_bon) - float(total_penjualan_by_sales_order)

                    update_faktur_detail = FakturDetailModel.query.filter(FakturDetailModel.id_sales_order == int(id_sales_order)).first()
                    if update_faktur_detail:
                        update_faktur_detail.subtotal = subtotal_penjualan_by_sales_order
                        update_faktur_detail.pajak = pajak_by_sales_order
                        update_faktur_detail.subtotal_diskon = subtotal_diskon_by_sales_order
                        update_faktur_detail.total = total_penjualan_by_sales_order
                        update_faktur_detail.draft_total = total_penjualan_by_sales_order
                        self.add(update_faktur_detail)

                    self.add(plafon_data)

            product_discounts = {}

            if vouchers and 'voucher_product' in vouchers:
                voucher_products = vouchers.get('voucher_product', [])

                for product_item in voucher_products:
                    id_sales_order_detail = product_item.get('id_sales_order_detail')
                    if id_sales_order_detail:
                        original_subtotal = format_angka(product_item.get('subtotalorder', 0))

                        total_diskon_produk = 0

                        vouchers_list = product_item.get('vouchers', [])

                        for voucher in vouchers_list:
                            is_active = voucher.get('active', False)
                            if is_active:
                                diskon = format_angka(voucher.get('diskon', 0))
                                total_diskon_produk += diskon

                        product_discounts[int(id_sales_order_detail)] = {
                            'total_diskon': total_diskon_produk,
                            'original_subtotal': original_subtotal
                        }

            for detail_id, values in product_discounts.items():
                detail = sales_order_detail.query.filter(sales_order_detail.id == detail_id).first()
                if detail:
                    detail.total_nilai_discount = format_angka(values['total_diskon'])
                    detail.subtotalorder = format_angka(values['original_subtotal'] - values['total_diskon'])

            voucher_product_data = {}
            if vouchers and 'voucher_product' in vouchers:
                for product in vouchers.get('voucher_product', []):
                    id_sales_order_detail = product.get('id_sales_order_detail')
                    if id_sales_order_detail:
                        voucher_product_data[int(id_sales_order_detail)] = {
                            'id_produk': product.get('id_produk'),
                            'konversi_level1': product.get('konversi_level1', 1),
                            'konversi_level2': product.get('konversi_level2', 1),
                            'konversi_level3': product.get('konversi_level3', 1),
                            'puom1_packing_panjang': product.get('puom1_packing_panjang', 0),
                            'puom1_packing_lebar': product.get('puom1_packing_lebar', 0),
                            'puom1_packing_tinggi': product.get('puom1_packing_tinggi', 0),
                            'puom2_packing_panjang': product.get('puom2_packing_panjang', 0),
                            'puom2_packing_lebar': product.get('puom2_packing_lebar', 0),
                            'puom2_packing_tinggi': product.get('puom2_packing_tinggi', 0),
                            'puom3_packing_panjang': product.get('puom3_packing_panjang', 0),
                            'puom3_packing_lebar': product.get('puom3_packing_lebar', 0),
                            'puom3_packing_tinggi': product.get('puom3_packing_tinggi', 0)
                        }
            for so in sales_orders:
                detail_orders = sales_order_detail.query.filter(
                    sales_order_detail.id_sales_order == so.id
                ).all()

                for detail in detail_orders:
                    detail.pieces_booked = self._safe_number(detail.pieces_order)
                    detail.box_booked = self._safe_number(detail.box_order)
                    detail.karton_booked = self._safe_number(detail.karton_order)
                    konversi_data = voucher_product_data.get(detail.id, {})

                    if konversi_data:
                        volume_pieces = (
                                                float(konversi_data.get('puom1_packing_panjang', 0) or 0) *
                                                float(konversi_data.get('puom1_packing_lebar', 0) or 0) *
                                                float(konversi_data.get('puom1_packing_tinggi', 0) or 0) *
                                                (detail.pieces_order or 0)
                                        ) or 0

                        volume_box = (
                                             float(konversi_data.get('puom2_packing_panjang', 0) or 0) *
                                             float(konversi_data.get('puom2_packing_lebar', 0) or 0) *
                                             float(konversi_data.get('puom2_packing_tinggi', 0) or 0) *
                                             (detail.box_order or 0)
                                     ) or 0

                        volume_karton = (
                                                float(konversi_data.get('puom3_packing_panjang', 0) or 0) *
                                                float(konversi_data.get('puom3_packing_lebar', 0) or 0) *
                                                float(konversi_data.get('puom3_packing_tinggi', 0) or 0) *
                                                (detail.karton_order or 0)
                                        ) or 0

                        produk_kubikasi = (volume_pieces + volume_box + volume_karton) or 0

                        detail.estimasi_kubikasi = produk_kubikasi

                    stok_item = stok.query.filter(
                        stok.produk_id == detail.id_produk,
                        stok.cabang_id == id_cabang
                    ).first()
                    if not stok_item:
                        return {
                            "status": "error",
                            "message": f"Stok tidak ditemukan untuk produk ID {detail.id_produk} di cabang {id_cabang}"
                        }, 404

                    if stok_item:
                        konversi_data = voucher_product_data.get(detail.id, {})

                        konversi_level1 = self._safe_number(konversi_data.get('konversi_level1'), 1)
                        konversi_level2 = self._safe_number(konversi_data.get('konversi_level2'), 1)
                        konversi_level3 = self._safe_number(konversi_data.get('konversi_level3'), 1)

                        total_item_booked = (
                                (self._safe_number(detail.pieces_booked) * konversi_level1) +
                                (self._safe_number(detail.box_booked) * konversi_level2) +
                                (self._safe_number(detail.karton_booked) * konversi_level3)
                        )

                        stok_item.jumlah_booked = self._safe_number(stok_item.jumlah_booked) + total_item_booked
                        stok_item.jumlah_ready = self._safe_number(stok_item.jumlah_ready) - total_item_booked

            if vouchers and 'voucher_product' in vouchers:
                voucher_products = vouchers.get('voucher_product', [])

                if voucher_products:
                    for product_item in voucher_products:
                        id_sales_order_detail = product_item.get('id_sales_order_detail')
                        vouchers_list = product_item.get('vouchers', [])

                        for voucher in vouchers_list:
                            id_dv = voucher.get('id_dv')
                            is_active = voucher.get('active', False)
                            jumlah_diskon = format_angka(voucher.get('diskon', 0))

                            if id_dv is not None:
                                status_promo = 1 if is_active else 3

                                draft_entry = draft_voucher.query.filter(
                                    draft_voucher.id == id_dv
                                ).first()

                                if draft_entry:
                                    draft_entry.status_promo = status_promo
                                    if is_active:
                                        draft_entry.jumlah_diskon = jumlah_diskon
                                    else:
                                        draft_entry.jumlah_diskon = 0

        elif status == -1:
            if update_faktur:
                update_faktur.status_faktur = status
                self.add(update_faktur)
            draft_entries = (
                draft_voucher.query
                .filter(draft_voucher.id_sales_order.in_([so.id for so in sales_orders]))
                .all()
            )

            if draft_entries:
                for entry in draft_entries:
                    entry.status_promo = 3
                    entry.jumlah_diskon = 0
                    self.add(entry)
            self.flush()

        update_order_batch = OrderBatchModel.query.filter(OrderBatchModel.id == int(id_order_batch)).first()
        if update_order_batch:
            update_order_batch.status_order = status
            self.add(update_order_batch).flush()

        self.commit()

        return {"status": "success"}, 200

    def __konfirmasi_order_single_principal(self,status):
        id_sales_order = int(self.req('id_sales_order'))
        # Only get id_cabang if status is 1 (konfirmasi), not for status -1 (tolak)
        id_cabang = int(self.req('id_cabang')) if status == 1 else None
        vouchers = self.req('vouchers')

        update_sales_order = sales_order.query.filter(sales_order.id == id_sales_order).first()
        update_faktur = Faktur.query.filter(Faktur.id_sales_order == int(id_sales_order)).first()
        plafon_data = plafon.query.filter(plafon.id == update_sales_order.id_plafon).first()

        if status == 1:
            self.__validate_customer_tax_identity_for_sales_orders([id_sales_order])

        update_sales_order.status_order = status

        if status == 1:  # Booked
            total_penjualan = self._safe_number(self.req('total_penjualan'))
            if plafon_data and plafon_data.sisa_bon is not None:
                # Validasi lock_order
                if plafon_data.lock_order == '1':
                    # Jika lock_order = 1, sisa_bon harus sama dengan limit_bon
                    if float(plafon_data.sisa_bon) != float(plafon_data.limit_bon):
                        return {
                            "status": "error",
                            "message": f"Plafon dalam status lock. Sisa bon (Rp {format_rupiah(plafon_data.sisa_bon)}) harus sama dengan limit bon (Rp {format_rupiah(plafon_data.limit_bon)}) untuk melanjutkan transaksi."
                        }, 400

                if float(total_penjualan) > float(plafon_data.sisa_bon):
                    return {
                        "status": "error",
                        "message": f"Total penjualan (Rp {format_rupiah(total_penjualan)}) melebihi sisa plafon (Rp {format_rupiah(plafon_data.sisa_bon)}). Transaksi tidak dapat dilanjutkan."
                    }, 400

                # Potong sisa_bon dengan total_penjualan
                plafon_data.sisa_bon = float(plafon_data.sisa_bon) - float(total_penjualan)
            subtotal_diskon = self._safe_number(self.req('subtotal_diskon'))
            dpp = self._safe_number(self.req('dpp'))
            pajak = self._safe_number(self.req('pajak'))

            update_faktur.total_penjualan = total_penjualan
            update_faktur.draft_total_penjualan = total_penjualan
            update_faktur.subtotal_diskon = subtotal_diskon
            update_faktur.dpp = dpp
            update_faktur.pajak = pajak

            product_discounts = {}

            if vouchers and 'voucher_product' in vouchers:
                voucher_products = vouchers.get('voucher_product', [])

                for product_item in voucher_products:
                    id_sales_order_detail = product_item.get('id_sales_order_detail')
                    if id_sales_order_detail:
                        original_subtotal = format_angka(product_item.get('subtotalorder', 0))

                        total_diskon_produk = 0

                        vouchers_list = product_item.get('vouchers', [])

                        for voucher in vouchers_list:
                            is_active = voucher.get('active', False)
                            if is_active:
                                diskon = format_angka(voucher.get('diskon', 0))
                                total_diskon_produk += diskon

                        product_discounts[int(id_sales_order_detail)] = {
                            'total_diskon': total_diskon_produk,
                            'original_subtotal': original_subtotal
                        }

            for detail_id, values in product_discounts.items():
                detail = sales_order_detail.query.filter(sales_order_detail.id == detail_id).first()
                if detail:
                    detail.total_nilai_discount = format_angka(values['total_diskon'])
                    detail.subtotalorder = format_angka(values['original_subtotal'] - values['total_diskon'])

            voucher_product_data = {}
            if vouchers and 'voucher_product' in vouchers:
                for product in vouchers.get('voucher_product', []):
                    id_sales_order_detail = product.get('id_sales_order_detail')
                    if id_sales_order_detail:
                        voucher_product_data[int(id_sales_order_detail)] = {
                            'id_produk': product.get('id_produk'),
                            'konversi_level1': product.get('konversi_level1', 1),
                            'konversi_level2': product.get('konversi_level2', 1),
                            'konversi_level3': product.get('konversi_level3', 1),
                            'puom1_packing_panjang': product.get('puom1_packing_panjang', 0),
                            'puom1_packing_lebar': product.get('puom1_packing_lebar', 0),
                            'puom1_packing_tinggi': product.get('puom1_packing_tinggi', 0),
                            'puom2_packing_panjang': product.get('puom2_packing_panjang', 0),
                            'puom2_packing_lebar': product.get('puom2_packing_lebar', 0),
                            'puom2_packing_tinggi': product.get('puom2_packing_tinggi', 0),
                            'puom3_packing_panjang': product.get('puom3_packing_panjang', 0),
                            'puom3_packing_lebar': product.get('puom3_packing_lebar', 0),
                            'puom3_packing_tinggi': product.get('puom3_packing_tinggi', 0)
                        }

            detail_orders = sales_order_detail.query.filter(
                sales_order_detail.id_sales_order == id_sales_order
            ).all()

            for detail in detail_orders:
                detail.pieces_booked = self._safe_number(detail.pieces_order)
                detail.box_booked = self._safe_number(detail.box_order)
                detail.karton_booked = self._safe_number(detail.karton_order)
                konversi_data = voucher_product_data.get(detail.id, {})

                if konversi_data:
                    volume_pieces = (
                                            float(konversi_data.get('puom1_packing_panjang', 0) or 0) *
                                            float(konversi_data.get('puom1_packing_lebar', 0) or 0) *
                                            float(konversi_data.get('puom1_packing_tinggi', 0) or 0) *
                                            (detail.pieces_order or 0)
                                    ) or 0

                    volume_box = (
                                         float(konversi_data.get('puom2_packing_panjang', 0) or 0) *
                                         float(konversi_data.get('puom2_packing_lebar', 0) or 0) *
                                         float(konversi_data.get('puom2_packing_tinggi', 0) or 0) *
                                         (detail.box_order or 0)
                                 ) or 0

                    volume_karton = (
                                            float(konversi_data.get('puom3_packing_panjang', 0) or 0) *
                                            float(konversi_data.get('puom3_packing_lebar', 0) or 0) *
                                            float(konversi_data.get('puom3_packing_tinggi', 0) or 0) *
                                            (detail.karton_order or 0)
                                    ) or 0

                    produk_kubikasi = (volume_pieces + volume_box + volume_karton) or 0

                    detail.estimasi_kubikasi = produk_kubikasi

                    self.add(detail)

                stok_item = (stok.query.filter(
                    stok.produk_id == detail.id_produk,
                    stok.cabang_id == id_cabang
                )
                . with_for_update()
                             .first())
                if not stok_item:
                    return {
                        "status": "error",
                        "message": f"Stok tidak ditemukan untuk produk ID {detail.id_produk} di cabang {id_cabang}"
                    }, 404

                if stok_item:
                    konversi_data = voucher_product_data.get(detail.id, {})

                    konversi_level1 = self._safe_number(konversi_data.get('konversi_level1'), 1)
                    konversi_level2 = self._safe_number(konversi_data.get('konversi_level2'), 1)
                    konversi_level3 = self._safe_number(konversi_data.get('konversi_level3'), 1)

                    total_item_booked = (
                            (self._safe_number(detail.pieces_booked) * konversi_level1) +
                            (self._safe_number(detail.box_booked) * konversi_level2) +
                            (self._safe_number(detail.karton_booked) * konversi_level3)
                    )

                    stok_item.jumlah_booked = self._safe_number(stok_item.jumlah_booked) + total_item_booked
                    stok_item.jumlah_ready = self._safe_number(stok_item.jumlah_ready) - total_item_booked

                    self.add(stok_item)

            if vouchers and 'voucher_product' in vouchers:
                voucher_products = vouchers.get('voucher_product', [])

                if voucher_products:
                    for product_item in voucher_products:
                        id_sales_order_detail = product_item.get('id_sales_order_detail')
                        vouchers_list = product_item.get('vouchers', [])

                        for voucher in vouchers_list:
                            id_dv = voucher.get('id_dv')
                            is_active = voucher.get('active', False)
                            jumlah_diskon = format_angka(voucher.get('diskon', 0))

                            if id_dv is not None:
                                status_promo = 1 if is_active else 3

                                draft_entry = draft_voucher.query.filter(
                                    draft_voucher.id == id_dv
                                ).first()

                                if draft_entry:
                                    draft_entry.status_promo = status_promo
                                    if is_active:
                                        draft_entry.jumlah_diskon = jumlah_diskon
                                    else:
                                        draft_entry.jumlah_diskon = 0
                                    self.add(draft_entry)

        elif status == -1:
            if update_faktur:
                update_faktur.status_faktur = status
                self.add(update_faktur)
            draft_entries = draft_voucher.query.filter(
                draft_voucher.id_sales_order == id_sales_order
            ).all()

            if draft_entries:
                for entry in draft_entries:
                    entry.status_promo = 3
                    entry.jumlah_diskon = 0

        self.commit()

        return {"status": "success"}, 200

    # @redis_cache.cached('produk_uom', 'getFactorKonversi')
    def getFactorKonversi(self, id_produk):
        return (
            self.query().setRawQuery(
                f"""
                    select faktor_konversi as fk, level
                    from produk_uom 
                    where id_produk = { id_produk }
                    order by level asc
                """
            )
            .execute()
            .fetchall()
            .get()
        )
        
    # def updateTenggatWaktuFaktur(self, id_sales_order):
    #     update_so = (
    #         self.db
    #         .session
    #         .query(sales_order)
    #         .filter(sales_order.id == id_sales_order)
    #         .first()
    #     )
            
    #     add_jatuh_tempo = (update_so.tanggal_jatuh_tempo + timedelta(days=10)).strftime("%Y-%m-%d")
    #     update_so.tanggal_jatuh_tempo = add_jatuh_tempo
    
    def getRoutes(self, id_cabang, status_order):
        if id_cabang is None:
            raise nonServerErrorException("ID cabang wajib diisi", 400)

        id_cabang = int(id_cabang)

        if not status_order:
            raise nonServerErrorException("Status order wajib diisi", 400)

        if isinstance(status_order, str):
            cleaned_status = status_order.strip().strip('()[]')
            status_tokens = [token.strip() for token in cleaned_status.split(',') if token.strip()]
        elif isinstance(status_order, (list, tuple, set)):
            status_tokens = list(status_order)
        else:
            status_tokens = [status_order]

        try:
            status_numbers = [int(x) for x in status_tokens]
            status_values = ",".join(str(x) for x in status_numbers)
        except (TypeError, ValueError):
            raise nonServerErrorException("Format status order tidak valid", 400)

        before_this_date_query_so = getattr(self, 'before_this_date_query_so', '') or ''
        require_schedule_query = (
            "AND pp.id IS NOT NULL AND pp.id_armada IS NOT NULL AND pp.id_driver IS NOT NULL AND pp.delivering_date IS NOT NULL"
            if set(status_numbers).issubset({2, 10})
            else ""
        )

        query_one_principal = text(f"""
            SELECT
                COUNT(DISTINCT c.nama) AS jumlah_toko,
                COUNT(DISTINCT f.id) AS jumlah_nota,
                COALESCE(SUM(sod.estimasi_kubikasi)::NUMERIC, 0) AS kubikal,
                r.id AS id_rute,
                r.nama_rute,
                r.kode,
                c.id AS id_customer,
                a.nama AS nama_armada,
                u.nama AS nama_driver,
                d.id AS id_driver,
                pp.delivering_date,
                a.id AS id_armada,
                string_agg(DISTINCT pp.id::text, ',') AS id_proses_picking,
                string_agg(DISTINCT pp.id_order_detail::text, ',') AS id_order_detail,
                string_agg(DISTINCT so.id::text, ',') AS id_sales_order,
                string_agg(DISTINCT so.no_order::text, ',') AS no_order,
                string_agg(DISTINCT f.id::text, ',') AS id_faktur
            FROM rute r
            JOIN customer c
                ON c.id_rute = r.id
            JOIN cabang cb
                ON c.id_cabang = cb.id
            JOIN plafon p
                ON p.id_customer = c.id
            JOIN sales_order so
                ON so.id_plafon = p.id
            AND so.status_order IN ({status_values})
            JOIN faktur f
                ON f.id_sales_order = so.id
            AND f.jenis_faktur = 'penjualan'
            LEFT JOIN sales_order_detail sod
                ON sod.id_sales_order = so.id
            LEFT JOIN proses_picking pp
                ON pp.id_order_detail = sod.id
            LEFT JOIN armada a
                ON a.id = pp.id_armada
            LEFT JOIN driver d
                ON d.id = pp.id_driver
            LEFT JOIN users u
                ON u.id = d.id_user
            WHERE cb.id = :id_cabang
            {before_this_date_query_so}
            {require_schedule_query}
            GROUP BY
                r.id, r.nama_rute, r.kode, a.nama, u.nama,
                pp.delivering_date, d.id, a.id, c.id
        """)

        query_multiple_principal = text(f"""
            SELECT
                COUNT(DISTINCT c.nama) AS jumlah_toko,
                COUNT(DISTINCT f.id) AS jumlah_nota,
                COALESCE(SUM(sod.estimasi_kubikasi)::NUMERIC, 0) AS kubikal,
                r.id AS id_rute,
                r.nama_rute,
                r.kode,
                c.id AS id_customer,
                a.nama AS nama_armada,
                u.nama AS nama_driver,
                d.id AS id_driver,
                pp.delivering_date,
                a.id AS id_armada,
                string_agg(DISTINCT pp.id::text, ',') AS id_proses_picking,
                string_agg(DISTINCT pp.id_order_detail::text, ',') AS id_order_detail,
                string_agg(DISTINCT so.id::text, ',') AS id_sales_order,
                string_agg(DISTINCT so.no_order::text, ',') AS no_order,
                string_agg(DISTINCT f.id::text, ',') AS id_faktur
            FROM rute r
            JOIN customer c
                ON c.id_rute = r.id
            JOIN cabang cb
                ON c.id_cabang = cb.id
            JOIN plafon p
                ON p.id_customer = c.id
            JOIN sales_order so
                ON so.id_plafon = p.id
            JOIN faktur_detail fd
                ON fd.id_sales_order = so.id
            JOIN faktur f
                ON f.id = fd.id_faktur
            LEFT JOIN sales_order_detail sod
                ON sod.id_sales_order = so.id
            LEFT JOIN proses_picking pp
                ON pp.id_order_detail = sod.id
            LEFT JOIN armada a
                ON a.id = pp.id_armada
            LEFT JOIN driver d
                ON d.id = pp.id_driver
            LEFT JOIN users u
                ON u.id = d.id_user
            WHERE cb.id = :id_cabang
            AND f.jenis_faktur = 'penjualan'
            AND so.status_order IN ({status_values})
            {before_this_date_query_so}
            {require_schedule_query}
            GROUP BY
                r.id, r.nama_rute, r.kode, a.nama, u.nama,
                pp.delivering_date, d.id, a.id, c.id
        """)

        rows_one = DB.session.execute(
            query_one_principal,
            {"id_cabang": id_cabang}
        ).mappings().all()

        rows_multiple = DB.session.execute(
            query_multiple_principal,
            {"id_cabang": id_cabang}
        ).mappings().all()

        order_one_principal = [dict(row) for row in rows_one]
        order_multiple_principal = [dict(row) for row in rows_multiple]

        merge_all_orders = [
            *order_one_principal,
            *order_multiple_principal
        ]

        grouped_data = []

        def merge_csv_values(old_value, new_value):
            old_set = {
                item.strip()
                for item in str(old_value or '').split(',')
                if item and item.strip()
            }
            new_set = {
                item.strip()
                for item in str(new_value or '').split(',')
                if item and item.strip()
            }
            merged = old_set | new_set

            if not merged:
                return None

            def sort_key(value):
                return int(value) if str(value).isdigit() else str(value)

            return ','.join(sorted(merged, key=sort_key))

        for entry in merge_all_orders:
            found = False

            for group in grouped_data:
                if (
                    group['id_rute'] == entry['id_rute']
                    and group['id_armada'] == entry['id_armada']
                    and group['id_driver'] == entry['id_driver']
                    and str(group['delivering_date']) == str(entry['delivering_date'])
                ):
                    if group['id_customer'] != entry['id_customer']:
                        group['jumlah_toko'] += 1

                    group['jumlah_nota'] += entry['jumlah_nota'] or 0
                    group['kubikal'] += float(entry['kubikal'] or 0)
                    group['id_proses_picking'] = merge_csv_values(
                        group.get('id_proses_picking'),
                        entry.get('id_proses_picking')
                    )
                    group['id_order_detail'] = merge_csv_values(
                        group.get('id_order_detail'),
                        entry.get('id_order_detail')
                    )
                    group['id_sales_order'] = merge_csv_values(
                        group.get('id_sales_order'),
                        entry.get('id_sales_order')
                    )
                    group['no_order'] = merge_csv_values(
                        group.get('no_order'),
                        entry.get('no_order')
                    )
                    group['id_faktur'] = merge_csv_values(
                        group.get('id_faktur'),
                        entry.get('id_faktur')
                    )
                    found = True
                    break

            if not found:
                grouped_data.append({
                    'jumlah_toko': int(entry.get('jumlah_toko') or 0),
                    'jumlah_nota': int(entry.get('jumlah_nota') or 0),
                    'kubikal': float(entry.get('kubikal') or 0),
                    'id_rute': entry.get('id_rute'),
                    'nama_rute': entry.get('nama_rute'),
                    'kode': entry.get('kode'),
                    'id_customer': entry.get('id_customer'),
                    'nama_armada': entry.get('nama_armada'),
                    'nama_driver': entry.get('nama_driver'),
                    'id_driver': entry.get('id_driver'),
                    'delivering_date': entry.get('delivering_date'),
                    'id_armada': entry.get('id_armada'),
                    'id_proses_picking': entry.get('id_proses_picking'),
                    'id_order_detail': entry.get('id_order_detail'),
                    'id_sales_order': entry.get('id_sales_order'),
                    'no_order': entry.get('no_order'),
                    'id_faktur': entry.get('id_faktur'),
                })

        return grouped_data





        
    @handle_error
    def getRuteArmada(self):
        id_cabang = self._resolve_id_cabang('id')
        status_order = (1, 9)
        
        return self.getRoutes(id_cabang, status_order)

    @handle_error
    def getInfoRuteArmada(self):
        id_cabang = self.req('id_cabang')
        id_rute = self.req('id_rute')
        order_one_principal = (
            self.query().setRawQuery(
                f"""
                            select
                                count (distinct c.nama) as jumlah_toko,
                                count (distinct f.id) as jumlah_nota,
                                coalesce(SUM(sod.estimasi_kubikasi)::NUMERIC, 0) as jumlah_kubikal,
                                r.id as id_rute,
                                r.nama_rute,
                                r.kode as kode_rute,
                                c.id as id_customer,
                                a.nama as nama_armada,
                                u.nama as nama_driver,
                                d.id as id_driver,
                                pp.delivering_date,
                                a.id as id_armada
                            from rute r
                            join customer c on c.id_rute = r.id
                            join cabang cb on c.id_cabang = cb.id
                            join plafon p on p.id_customer = c.id
                            join sales_order so on so.id_plafon = p.id and so.status_order in (1,9)
                            join faktur f on f.id_sales_order = so.id and f.jenis_faktur = 'penjualan'
                            left join sales_order_detail sod on sod.id_sales_order = so.id
                            left join proses_picking pp on pp.id_order_detail = sod.id
                            left join armada a on a.id = pp.id_armada
                            left join driver d on d.id = pp.id_driver
                            left join users u on u.id = d.id_user
                            where cb.id = :id_cabang 
                            AND
                            r.id = :id_rute
                            {self.before_this_date_query_so}
                            group by r.id, r.nama_rute, r.kode, a.nama, u.nama, pp.delivering_date , d.id, a.id, c.id
                        """
            )
            .bindparams({
                "id_cabang": id_cabang,
                "id_rute": id_rute
            })
            .execute()
            .fetchall()
            .get()
        )
        order_multiple_principal = (
            self.query().setRawQuery(
                f"""
                            select
                                count (distinct c.nama) as jumlah_toko,
                                count (distinct f.id) as jumlah_nota,
                                coalesce(SUM(sod.estimasi_kubikasi)::NUMERIC, 0) as jumlah_kubikal,
                                r.id as id_rute,
                                r.nama_rute,
                                r.kode as kode_rute,
                                c.id as id_customer,
                                a.nama as nama_armada,
                                u.nama as nama_driver,
                                d.id as id_driver,
                                pp.delivering_date,
                                a.id as id_armada
                            from rute r
                            join customer c on c.id_rute = r.id
                            join cabang cb on c.id_cabang = cb.id
                            join plafon p on p.id_customer = c.id
                            join sales_order so on so.id_plafon = p.id 
                            join faktur_detail fd on fd.id_sales_order = so.id
                            join faktur f on f.id = fd.id_faktur  
                            left join sales_order_detail sod on sod.id_sales_order = so.id
                            left join proses_picking pp on pp.id_order_detail = sod.id
                            left join armada a on a.id = pp.id_armada
                            left join driver d on d.id = pp.id_driver
                            left join users u on u.id = d.id_user
                            where cb.id = :id_cabang
                            AND 
                            f.jenis_faktur = 'penjualan'
                            AND 
                            r.id = :id_rute
                            AND                             
                            so.status_order in (1,9)
                            {self.before_this_date_query_so}
                            group by r.id, r.nama_rute, r.kode, a.nama, u.nama, pp.delivering_date , d.id, a.id, c.id
                        """
            )
            .bindparams({
                "id_cabang": id_cabang,
                "id_rute": id_rute
            })
            .execute()
            .fetchall()
            .get()
        )

        merge_all_orders = [
            *order_one_principal,
            *order_multiple_principal
        ]

        # Menggabungkan dan mengelompokkan data berdasarkan id_rute, id_armada, id_driver, dan delivering_date
        grouped_data = []
        for entry in merge_all_orders:
            found = False
            for group in grouped_data:
                if group['id_rute'] == entry['id_rute']:
                    if group['id_customer'] != entry['id_customer']:
                        group['jumlah_toko'] += 1
                    group['jumlah_nota'] += entry['jumlah_nota']
                    group['jumlah_kubikal'] += entry['jumlah_kubikal']
                    found = True
                    break
            if not found:
                grouped_data.append({
                    **entry,
                })
        return grouped_data

    @handle_error_rollback
    def updateJadwalRute(self):

        def normalize_db_rows(response):
            """
            Normalisasi response custom DB wrapper menjadi list of dict.
            Aman untuk hasil: DB object, list, RowMapping, tuple, None.
            """
            if response is None:
                return []

            if hasattr(response, "get"):
                try:
                    response = response.get()
                except TypeError:
                    pass

            if hasattr(response, "result"):
                response = response.result

            if response is None:
                return []

            if isinstance(response, dict):
                return [response]

            if not isinstance(response, list):
                return []

            rows = []
            for row in response:
                if isinstance(row, dict):
                    rows.append(row)
                elif hasattr(row, "_mapping"):
                    rows.append(dict(row._mapping))
            return rows

        def normalize_db_one(response):
            rows = normalize_db_rows(response)
            return rows[0] if rows else None

        raw_id_sales_orders = self.req("id_sales_orders")
        if raw_id_sales_orders in (None, '', 'None'):
            raise nonServerErrorException("ID sales order wajib diisi", 400)

        parsed_ids = []

        if isinstance(raw_id_sales_orders, list):
            for value in raw_id_sales_orders:
                if isinstance(value, dict):
                    candidate = value.get('id') or value.get('id_sales_order') or value.get('value')
                    if candidate not in (None, '', 'None'):
                        parsed_ids.append(candidate)
                else:
                    parsed_ids.append(value)

        elif isinstance(raw_id_sales_orders, str):
            parsed_ids.extend(
                item.strip()
                for item in raw_id_sales_orders.split(',')
                if item.strip()
            )
        else:
            parsed_ids.append(raw_id_sales_orders)

        try:
            id_sales_orders = [int(value) for value in parsed_ids]
        except (TypeError, ValueError, AttributeError):
            raise nonServerErrorException("Format ID sales order tidak valid", 400)

        if not id_sales_orders:
            raise nonServerErrorException("ID sales order wajib diisi", 400)

        try:
            id_driver = int(self.req("id_driver"))
            id_armada = int(self.req("id_armada"))
        except (TypeError, ValueError):
            raise nonServerErrorException("Driver dan armada wajib diisi", 400)

        raw_id_helper = self.req("id_helper")
        try:
            id_helper = int(raw_id_helper) if raw_id_helper not in (None, '', 'None') else None
        except (TypeError, ValueError):
            id_helper = None

        tanggal_pengiriman = self._normalize_delivery_date(self.req("tanggal_pengiriman"))
        if tanggal_pengiriman in (None, '', 'None'):
            raise nonServerErrorException("Tanggal pengiriman wajib diisi", 400)

        first_sales_order = sales_order.query.filter(
            sales_order.id == id_sales_orders[0]
        ).join(
            Plafon, sales_order.id_plafon == Plafon.id
        ).join(
            customer, Plafon.id_customer == customer.id
        ).first()

        if not first_sales_order:
            raise nonServerErrorException("Data sales order tidak ditemukan", 404)

        plafon_row = Plafon.query.filter(
            Plafon.id == first_sales_order.id_plafon
        ).first()

        customer_row = (
            customer.query.filter(customer.id == plafon_row.id_customer).first()
            if plafon_row else None
        )

        id_rute = customer_row.id_rute if customer_row else None

        if id_rute in (None, '', 'None'):
            raise nonServerErrorException(
                "Customer untuk sales order ini belum memiliki rute. Lengkapi rute customer terlebih dahulu sebelum membuat jadwal armada.",
                400
            )

        excluded_ids_sql = ','.join(str(id_value) for id_value in id_sales_orders)

        existing_response = (
            self.query()
            .setRawQuery(f"""
                SELECT COUNT(*) as count
                FROM proses_picking pp
                JOIN sales_order_detail sod ON sod.id = pp.id_order_detail
                JOIN sales_order so ON so.id = sod.id_sales_order
                JOIN plafon pl ON pl.id = so.id_plafon
                JOIN customer c ON c.id = pl.id_customer
                WHERE c.id_rute = :id_rute
                AND pp.id_armada = :id_armada
                AND pp.delivering_date = :delivering_date
                AND so.id NOT IN ({excluded_ids_sql})
            """)
            .bindparams({
                "id_rute": id_rute,
                "id_armada": id_armada,
                "delivering_date": tanggal_pengiriman
            })
            .execute()
            .fetchone()
        )

        existing_jadwal = normalize_db_one(existing_response)
        existing_count = int(existing_jadwal.get("count") or 0) if existing_jadwal else 0

        if existing_count > 0:
            raise nonServerErrorException(
                "Jadwal dengan armada dan tanggal pengiriman di rute tersebut sudah terdaftar, mohon pilih armada atau tanggal pengiriman yang lain. <br> Anda juga bisa menghapus jadwal yang sudah ada, lalu jadwalkan ulang rute tersebut.",
                400
            )

        for id_sales_order in id_sales_orders:
            update_sales_order = sales_order.query.filter(
                sales_order.id == id_sales_order
            ).first()

            if not update_sales_order:
                raise nonServerErrorException(
                    f"Sales order dengan ID {id_sales_order} tidak ditemukan",
                    404
                )

            order_details = sales_order_detail.query.filter(
                sales_order_detail.id_sales_order == id_sales_order
            ).all()

            for detail in order_details:
                self._upsert_schedule_pickings_for_detail(
                    detail,
                    id_driver,
                    id_armada,
                    id_helper,
                    tanggal_pengiriman,
                    default_picked=self._default_picked_total_for_detail(detail),
                    overwrite_picked=update_sales_order.status_order != 9
                )

            if update_sales_order.status_order == 1:
                update_sales_order.status_order = 2
            elif update_sales_order.status_order == 9:
                update_sales_order.status_order = 10

            self.flush()

        self.commit()

        return {"message": "Data updated successfully"}, 200

    @handle_error
    def getRuteListPicking(self):
        id_cabang = self._resolve_id_cabang('id')
        status_order = (2,)

        return self.getRoutes(id_cabang, status_order)

    @handle_error
    def getListRuteRevisiFaktur(self):
        id_cabang = self.req('id_cabang')
        status_order = '(5)'

        return self.getRoutes(id_cabang, status_order)

    @handle_error
    def getAddpicking(self):
        id = self.req('id')
        rute_id = self.req('rute_id')
        id_armada = self.req("id_armada")
        id_driver = self.req("id_driver")
        delivering_date = self._normalize_delivery_date(self.req("delivering_date"))
        id_proses_picking = self.req("id_proses_picking")
        id_order_detail = self.req("id_order_detail")

        def parse_id_csv(value):
            ids = []
            if value in (None, '', 'None'):
                return ids
            values = value if isinstance(value, (list, tuple, set)) else str(value).split(',')
            for raw_value in values:
                text_value = str(raw_value).strip()
                if not text_value:
                    continue
                try:
                    ids.append(int(text_value))
                except (TypeError, ValueError):
                    raise nonServerErrorException("Format ID proses picking tidak valid", 400)
            return sorted(set(ids))

        picking_ids = parse_id_csv(id_proses_picking)
        order_detail_ids = parse_id_csv(id_order_detail)

        if picking_ids:
            picking_filter_sql = f"pp.id IN ({','.join(str(value) for value in picking_ids)})"
            picking_params = {}
        elif order_detail_ids:
            picking_filter_sql = f"pp.id_order_detail IN ({','.join(str(value) for value in order_detail_ids)})"
            picking_params = {}
        else:
            if id_armada in (None, '', 'None') or id_driver in (None, '', 'None') or delivering_date in (None, '', 'None'):
                return []

            picking_filter_sql = "pp.id_armada = :id_armada AND pp.id_driver = :id_driver AND pp.delivering_date = :delivering_date"
            picking_params = {
                "id_armada": id_armada,
                "id_driver": id_driver,
                "delivering_date": delivering_date
            }

        # =========================
        # QUERY 1
        # =========================
        sql_one = text(f"""
            select
                    p.id as produk_id,
                    p.kode_sku,
                    p.nama as nama_produk,
                    string_agg(distinct c.id::text, ',') as id_customer,
                    string_agg(distinct c.nama, ',') as nama_customer,
                    coalesce(sum(pp.jumlah_picked), 0) as jumlah_picked,
                    COALESCE(MAX(CASE WHEN puom1.level = 1 THEN puom1.faktor_konversi END), 1) as konversi1,
                    COALESCE(MAX(CASE WHEN puom2.level = 2 THEN puom2.faktor_konversi END), 0) as konversi2,
                    COALESCE(MAX(CASE WHEN puom3.level = 3 THEN puom3.faktor_konversi END), 0) as konversi3,
                    COALESCE(
                    SUM(
                        (CASE WHEN puom1.level = 1 THEN puom1.faktor_konversi ELSE 1 END * sod.pieces_order) +
                        (CASE WHEN puom2.level = 2 THEN puom2.faktor_konversi ELSE 1 END * sod.box_order) +
                        (CASE WHEN puom3.level = 3 THEN puom3.faktor_konversi ELSE 1 END * sod.karton_order)
                    ), 0) as total_in_pieces,
                    string_agg(distinct pp.id_order_detail::text, ',') as id_order_detail,
                    string_agg(distinct pp.id::text, ',') as id_proses_picking,
                    string_agg(distinct f.id::text, ',') as id_faktur,
                    pp.delivering_date,
                    pp.id_driver,
                    pp.id_armada,
                    r.id as id_rute,
                    pr.nama as nama_principal,
                    coalesce(sum(sod.pieces_booked),0) as total_pieces,
                    coalesce(sum(sod.box_booked),0) as total_box,
                    coalesce(sum(sod.karton_booked),0) as total_karton,
                    coalesce(sum(pp.jumlah_picked), 0) as jumlah_picked,
                    stok.jumlah_good as stok,
                    MAX(CASE WHEN puom1.level = 1 THEN puom1.nama ELSE 'pieces' END) as pieces
                    from produk p
                    join proses_picking pp on p.id = pp.id_produk
                    join sales_order_detail sod on sod.id = pp.id_order_detail
                    join sales_order so on so.id = sod.id_sales_order and so.status_order in (2)
                    join plafon pl on pl.id = so.id_plafon
                    join customer c on c.id = pl.id_customer and c.id_cabang = :id
                    join principal pr on pr.id = p.id_principal
                    join rute r on r.id = c.id_rute and r.id = :rute_id
                    join faktur f on f.id_sales_order = so.id
                    left join produk_uom puom1 on puom1.id_produk = p.id and puom1.level = 1
                    left join produk_uom puom2 on puom2.id_produk = p.id and puom2.level = 2
                    left join produk_uom puom3 on puom3.id_produk = p.id and puom3.level = 3
                    join stok on stok.produk_id = p.id and stok.cabang_id = c.id_cabang
                    where {picking_filter_sql}
                    group by
                    p.id,
                    p.kode_sku,
                    p.nama,
                    pp.delivering_date,
                    pp.id_driver,
                    pp.id_armada,
                    r.id,
                    pr.nama,
                    stok.jumlah_good
        """)

        result_one = DB.session.execute(sql_one, {
            "id": id,
            "rute_id": rute_id,
            **picking_params
        }).mappings().all()

        add_picking_one_principal = [dict(row) for row in result_one]

        # =========================
        # QUERY 2
        # =========================
        sql_two = text(f"""
            select
                    p.id as produk_id,
                    p.kode_sku,
                    p.nama as nama_produk,
                    string_agg(distinct c.id::text, ',') as id_customer,
                    string_agg(distinct c.nama, ',') as nama_customer,
                    coalesce(sum(pp.jumlah_picked), 0) as jumlah_picked,
                    COALESCE(MAX(CASE WHEN puom1.level = 1 THEN puom1.faktor_konversi END), 1) as konversi1,
                    COALESCE(MAX(CASE WHEN puom2.level = 2 THEN puom2.faktor_konversi END), 0) as konversi2,
                    COALESCE(MAX(CASE WHEN puom3.level = 3 THEN puom3.faktor_konversi END), 0) as konversi3,
                    COALESCE(
                    SUM(
                        (CASE WHEN puom1.level = 1 THEN puom1.faktor_konversi ELSE 1 END * sod.pieces_order) +
                        (CASE WHEN puom2.level = 2 THEN puom2.faktor_konversi ELSE 1 END * sod.box_order) +
                        (CASE WHEN puom3.level = 3 THEN puom3.faktor_konversi ELSE 1 END * sod.karton_order)
                    ), 0) as total_in_pieces,
                    string_agg(distinct pp.id_order_detail::text, ',') as id_order_detail,
                    string_agg(distinct pp.id::text, ',') as id_proses_picking,
                    string_agg(distinct f.id::text, ',') as id_faktur,
                    pp.delivering_date,
                    pp.id_driver,
                    pp.id_armada,
                    r.id as id_rute,
                    pr.nama as nama_principal,
                    coalesce(sum(sod.pieces_booked),0) as total_pieces,
                    coalesce(sum(sod.box_booked),0) as total_box,
                    coalesce(sum(sod.karton_booked),0) as total_karton,
                    coalesce(sum(pp.jumlah_picked), 0) as jumlah_picked,
                    stok.jumlah_good as stok,
                    MAX(CASE WHEN puom1.level = 1 THEN puom1.nama ELSE 'pieces' END) as pieces
                    from produk p
                    join proses_picking pp on p.id = pp.id_produk
                    join sales_order_detail sod on sod.id = pp.id_order_detail
                    join sales_order so on so.id = sod.id_sales_order and so.status_order in (2)
                    join plafon pl on pl.id = so.id_plafon
                    join customer c on c.id = pl.id_customer and c.id_cabang = :id
                    join principal pr on pr.id = p.id_principal
                    join rute r on r.id = c.id_rute and r.id = :rute_id
					join faktur_detail fd on fd.id_sales_order =so.id 
                    join faktur f on f.id = fd.id_faktur
                    left join produk_uom puom1 on puom1.id_produk = p.id and puom1.level = 1
                    left join produk_uom puom2 on puom2.id_produk = p.id and puom2.level = 2
                    left join produk_uom puom3 on puom3.id_produk = p.id and puom3.level = 3
                    join stok on stok.produk_id = p.id and stok.cabang_id = c.id_cabang
                    where {picking_filter_sql}
                    group by
                    p.id,
                    p.kode_sku,
                    p.nama,
                    pp.delivering_date,
                    pp.id_driver,
                    pp.id_armada,
                    r.id,
                    pr.nama,
                    stok.jumlah_good
        """)

        result_two = DB.session.execute(sql_two, {
            "id": id,
            "rute_id": rute_id,
            **picking_params
        }).mappings().all()

        add_picking_multiple_principal = [dict(row) for row in result_two]

        # =========================
        # MERGE
        # =========================
        add_picking = [
            *add_picking_one_principal,
            *add_picking_multiple_principal
        ]

        merge_data_add_picking = []
        for entry in add_picking:
            found = False
            for group in merge_data_add_picking:
                if group['produk_id'] == entry['produk_id']:
                    if group['id_customer'] != entry['id_customer']:
                        group['nama_customer'] += f", {entry['nama_customer']}"
                        group['id_customer'] += f", {entry['id_customer']}"
                    group['jumlah_picked'] += entry['jumlah_picked']
                    group['total_in_pieces'] += entry['total_in_pieces']
                    group['total_pieces'] += entry['total_pieces']
                    group['total_box'] += entry['total_box']
                    group['total_karton'] += entry['total_karton']
                    group['id_order_detail'] += f", {entry['id_order_detail']}"
                    group['id_proses_picking'] += f", {entry['id_proses_picking']}"
                    group['id_faktur'] += f", {entry['id_faktur']}"

                    found = True
                    break
            if not found:
                merge_data_add_picking.append({
                    **entry,
                })

        return merge_data_add_picking

    @handle_error
    def getDaftarTokoPicking(self):
        id_cabang = self._resolve_id_cabang()
        id_rute = self.req("id_rute")
        id_produk = self.req("id_produk")
        id_order_detail = self.req("id_order_detail")

        if not all([id_cabang, id_rute, id_produk, id_order_detail]):
            return []

        # Buat string dari list id_order_detail untuk query
        id_order_detail_list = [
            str(int(id.strip()))
            for id in str(id_order_detail).split(',')
            if str(id).strip().isdigit()
        ]

        if not id_order_detail_list:
            return []

        id_order_detail_list_str = ','.join(id_order_detail_list)

        query_one_principal = text(
            f"""
                select
                customer.nama as nama_customer,
                customer.id as id_customer,
                produk.nama as nama_produk,
                produk.id as produk_id,
                proses_picking.id_armada,
                proses_picking.id_driver,
                proses_picking.delivering_date,
                coalesce(sum(sales_order_detail.pieces_order),0) as pieces_order,
                coalesce(sum(sales_order_detail.box_order),0) as box_order,
                coalesce(sum(sales_order_detail.karton_order),0) as karton_order,
                coalesce(proses_picking.jumlah_picked, 0) as jumlah_picked,
                COALESCE(SUM( (CASE WHEN puom1.level = 1 THEN puom1.faktor_konversi ELSE 1 END * sales_order_detail.pieces_order) + 
                (CASE WHEN puom2.level = 2 THEN puom2.faktor_konversi ELSE 1 END * sales_order_detail.box_order) + 
                (CASE WHEN puom3.level = 3 THEN puom3.faktor_konversi ELSE 1 END * sales_order_detail.karton_order) ), 0) as total_in_pieces,
                proses_picking.id_order_detail,
                faktur.no_faktur,
                sales_order.no_order
                from customer
                join rute on customer.id_rute = rute.id
                join cabang on customer.id_cabang = cabang.id
                join plafon on plafon.id_customer = customer.id
                join sales_order on sales_order.id_plafon = plafon.id
                left join faktur on faktur.id_sales_order = sales_order.id
                join sales_order_detail on sales_order_detail.id_sales_order = sales_order.id
                join proses_picking on proses_picking.id_order_detail = sales_order_detail.id
                join produk on sales_order_detail.id_produk = produk.id
                left join produk_uom puom1 on puom1.id_produk = produk.id and puom1.level = 1
                left join produk_uom puom2 on puom2.id_produk = produk.id and puom2.level = 2
                left join produk_uom puom3 on puom3.id_produk = produk.id and puom3.level = 3
                where customer.id_cabang = :id_cabang
                and rute.id = :id_rute
                and produk.id = :id_produk
                and (sales_order.status_order = 2 OR sales_order.status_order IS NULL)
                and proses_picking.id_order_detail IN ({id_order_detail_list_str})
                {self.before_this_date_query}
                group by nama_customer, nama_produk, produk_id, jumlah_picked, customer.id, proses_picking.id_order_detail, proses_picking.id_armada, proses_picking.id_driver, proses_picking.delivering_date, faktur.no_faktur, sales_order.no_order
            """
        )

        query_multiple_principal = text(
            f"""
                select
                customer.nama as nama_customer,
                customer.id as id_customer,
                produk.nama as nama_produk,
                produk.id as produk_id,
                proses_picking.id_armada,
                proses_picking.id_driver,
                proses_picking.delivering_date,
                coalesce(sum(sales_order_detail.pieces_order),0) as pieces_order,
                coalesce(sum(sales_order_detail.box_order),0) as box_order,
                coalesce(sum(sales_order_detail.karton_order),0) as karton_order,
                coalesce(proses_picking.jumlah_picked, 0) as jumlah_picked,
                COALESCE(SUM( (CASE WHEN puom1.level = 1 THEN puom1.faktor_konversi ELSE 1 END * sales_order_detail.pieces_order) + 
                (CASE WHEN puom2.level = 2 THEN puom2.faktor_konversi ELSE 1 END * sales_order_detail.box_order) + 
                (CASE WHEN puom3.level = 3 THEN puom3.faktor_konversi ELSE 1 END * sales_order_detail.karton_order) ), 0) as total_in_pieces,
                proses_picking.id_order_detail,
                faktur.no_faktur,
                sales_order.no_order
                from customer
                join rute on customer.id_rute = rute.id
                join cabang on customer.id_cabang = cabang.id
                join plafon on plafon.id_customer = customer.id
                join sales_order on sales_order.id_plafon = plafon.id
                join faktur_detail on sales_order.id = faktur_detail.id_sales_order
                left join faktur on faktur.id = faktur_detail.id_faktur
                join sales_order_detail on sales_order_detail.id_sales_order = sales_order.id
                join proses_picking on proses_picking.id_order_detail = sales_order_detail.id
                join produk on sales_order_detail.id_produk = produk.id
                left join produk_uom puom1 on puom1.id_produk = produk.id and puom1.level = 1
                left join produk_uom puom2 on puom2.id_produk = produk.id and puom2.level = 2
                left join produk_uom puom3 on puom3.id_produk = produk.id and puom3.level = 3
                where customer.id_cabang = :id_cabang
                and rute.id = :id_rute
                and produk.id = :id_produk
                and (sales_order.status_order = 2 OR sales_order.status_order IS NULL)
                and proses_picking.id_order_detail IN ({id_order_detail_list_str})
                {self.before_this_date_query}
                group by nama_customer, nama_produk, produk_id, jumlah_picked, customer.id, proses_picking.id_order_detail, proses_picking.id_armada, proses_picking.id_driver, proses_picking.delivering_date, faktur.no_faktur, sales_order.no_order
            """
        )

        params = {
            "id_cabang": int(id_cabang),
            "id_rute": int(id_rute),
            "id_produk": int(id_produk)
        }

        daftarToko_one_principal = [dict(row) for row in DB.session.execute(query_one_principal, params).mappings().all()]
        daftarToko_multiple_principal = [dict(row) for row in DB.session.execute(query_multiple_principal, params).mappings().all()]

        daftarToko = [
            *daftarToko_one_principal,
            *daftarToko_multiple_principal
        ]
        return daftarToko

    @handle_error_rollback
    def submitProdukPicking(self):
        list_picking = self.req("picking")

        if not list_picking or not isinstance(list_picking, list):
            raise nonServerErrorException("Data picking tidak valid atau kosong", 400)

        for pick in list_picking:
            picking_value = pick.get('picking')

            if picking_value is None or not isinstance(picking_value, int) or picking_value < 0:
                raise nonServerErrorException("Nilai picking tidak valid", 400)

            id_order_detail = pick.get("id_order_detail")

            if id_order_detail is None:
                raise nonServerErrorException("Invalid or missing 'id_order_detail'", 400)

            if not isinstance(id_order_detail, int):
                raise nonServerErrorException(f"Nilai id_order_detail tidak valid: {id_order_detail}", 400)

            proses_picking_picked = prosesPicking.query.filter(prosesPicking.id_order_detail == id_order_detail).first()

            if not proses_picking_picked:
                raise nonServerErrorException(
                    f"Data proses picking dengan ID detail order {id_order_detail} tidak ditemukan", 404)

            proses_picking_picked.jumlah_picked = picking_value

            self.flush()

        self.commit()

        return {'status': 'success'}, 200

    @handle_error_rollback
    def __submitProdukPicking(self):
        list_picking = self.req("picking") 
        id_produk = int(list_picking[0]["idProduk"])
        id_cabang = self.req('id_cabang')
    
        # loop produk yamh telah di pick dari frontend
        for picking in list_picking:
            pick = picking["picking"]
    
            # melakukan loop untuk id detail order
            for id_detail in picking["id_detail_sales"]:
                # mendapatkan proses picking yang sesuai dengan id order detail
                proses_picking_picked = prosesPicking.query.filter(prosesPicking.id_order_detail == id_detail).first()
                # mendapatkan jumlah picked dari hasil mendapatkan proses picking di atas
                proses_picking_picked.jumlah_picked = pick

            self.flush()

            # melakukan loop terhadap array id_faktur
            for id_faktur in picking["id_faktur"]:
                # melakuakan check terhadap jumlah picking yang mana disimpan di variabel pick
                # jika tidak null maka akan melakuakn perhitunga seperti dibawah
                if pick != None and pick != "" :
                    # mendapatkan hasil joinan proses picking, sales_order_detail, sales_order, dan faktur
                    # berdasarkan variabel id_faktur
                    get_picking_null = (
                        self.db.session
                        .query(
                            prosesPicking
                        )
                        .join(
                            sales_order_detail,
                            sales_order_detail.id == prosesPicking.id_order_detail
                        )
                        .join(
                            sales_order,
                            sales_order_detail.id_sales_order == sales_order.id
                        )
                        .join(
                            Faktur,
                            Faktur.id_sales_order == sales_order.id
                        )
                        .filter(Faktur.id == id_faktur)
                        .all()
                    )

                    get_picking_null_array, check_all_null = [], False

                    # melakukan loop terhadap variabel get_picking_null, dan mendapatkan jumlah_picked
                    for picking in get_picking_null:
                        jumlah_pick = picking.jumlah_picked

                        # jika jumlah_picked non atau 0 maka melakukan push True ke get_picking_null_array
                        if jumlah_pick is None or jumlah_pick == 0:
                            get_picking_null_array.append(True)
                        else:
                            get_picking_null_array.append(False)

                    # jika ada satu nilai di get_picking_null_array yang true maka check_all_null akan berisi True
                    check_all_null = any(get_picking_null_array)

                    faktur = Faktur.query.filter(Faktur.id == id_faktur).first()

                    # jika check_all_null False maka melakukan update status_faktur menjadi 3 (picked)
                    if not check_all_null:
                        faktur.status_faktur = 3
                    else:
                        faktur.status_faktur = 1

                    self.flush()

        stok_picked = stok.query.filter(stok.produk_id == id_produk, stok.cabang_id == id_cabang).first()
        total_produk_picked = (
            self.db.session.query(Plafon.id_customer, prosesPicking.jumlah_picked)
            .join(sales_order, sales_order.id_plafon == Plafon.id)
            .join(sales_order_detail, sales_order_detail.id_sales_order == sales_order.id)
            .join(prosesPicking, prosesPicking.id_order_detail == sales_order_detail.id)
            .filter(prosesPicking.id_produk == id_produk)
            .group_by(prosesPicking.jumlah_picked, Plafon.id_customer)
            .distinct()
            .all()
        )

        # mendapatkan hasil kalkulasi dari semua jumlah_picked yang telah didapatkan dari variabel total_produk_picked diatas
        total_picked = sum([result[1] for result in total_produk_picked if isinstance(result[1], int)])

        # mendapatkan jumlah_picked dari stok yang telah didapatkan berdasarkan id_produk saat ini
        stok_jumlah_picked = stok_picked.jumlah_picked if isinstance(stok_picked.jumlah_picked, int) else 0

        # mendapatkan hasil yang akan digunakan untuk melakukan pengurangan terhadap jumlah_ready di tabel stok
        subtract_value = total_picked - stok_jumlah_picked

        update_stok = stok.query.filter(stok.produk_id == id_produk, stok.cabang_id == id_cabang).first()
        stok_jumlah_ready = update_stok.jumlah_ready

        # jika kolom jumlah_ready tidak null maka akan melakuak update jumlah_ready dan jumlah_picked
        if isinstance(stok_jumlah_ready, int):
            update_stok.jumlah_ready = stok_jumlah_ready - subtract_value
            update_stok.jumlah_picked = total_picked

        self.commit()
        return {"status": "success"}, 200

    @handle_error
    def getShippingRuteList(self, id_cabang, isRealisasi=False):

        if isRealisasi:
            status_order = "(4,11)"
        else:
            status_order = "(3,10)"

        return self.getRoutes(id_cabang, status_order)

    @handle_error
    def getListFakturShipping(self, isRealisasi = 0):
        id_cabang = self.req("id_cabang")
        id_rute = self.req('id_rute')
        id_armada = self.req('id_armada')
        id_driver = self.req('id_driver')
        delivering_date = self._normalize_delivery_date(self.req('delivering_date'))

        status_map = {
            0: '(3,10)',  # get shipping
            1: '(4,11)',  # get realisasi
            2: '(5)'  # get revisi faktur
        }
        status = status_map.get(isRealisasi, '(3)')

        list_faktur_shipping_info = (
            self.query().setRawQuery(
                f"""
                    select
                    armada.id,
                    rute.kode as kode_rute,
                    armada.no_pelat,
                    users.nama,
                    coalesce(sum(DISTINCT faktur.total_penjualan)::numeric,0) as total_penjualan,
                    proses_picking.id_armada as id_armada,
                    proses_picking.id_driver as id_driver,
                    proses_picking.delivering_date,
                    rute.id as id_rute
                    from customer
                    join rute on customer.id_rute = rute.id 
                    join cabang on customer.id_cabang = cabang.id
                    join plafon on plafon.id_customer = customer.id
                    join sales_order on sales_order.id_plafon = plafon.id
                    join faktur on faktur.id_sales_order = sales_order.id
                    join sales_order_detail on sales_order_detail.id_sales_order = sales_order.id
                    join proses_picking on proses_picking.id_order_detail = sales_order_detail.id
                    join armada on proses_picking.id_armada = armada.id
                    join driver on driver.id = proses_picking.id_driver
                    join users on users.id = driver.id_user
                    where customer.id_cabang = :id_cabang
                    and rute.id = :id_rute
                    and faktur.jenis_faktur = 'penjualan'
                    and sales_order.status_order in {status}
                    and proses_picking.id_armada = :id_armada
                    and proses_picking.id_driver = :id_driver
                    and proses_picking.delivering_date = :delivering_date
                    
                    {self.before_this_date_query}
                    group by armada.id, rute.kode, armada.no_pelat, users.nama, proses_picking.id_armada, proses_picking.id_driver, proses_picking.delivering_date, rute.id
                """
            )
            .bindparams({
                "id_cabang": id_cabang,
                "id_rute": id_rute,
                "id_armada": id_armada,
                "id_driver": id_driver,
                "delivering_date": delivering_date
            })
            .execute()
            .fetchone()
            .result
        )
    
        list_faktur_shipping_one_principal = (
            self.query().setRawQuery(
                f"""
                    select
					customer.kode as kode_customer,
                    sales_order.id as id_sales_order,
					wilayah4.nama as area,
					sales_order.no_order,
                    faktur.no_faktur,
                    sales_order.tanggal_order as tanggal_order,
                    rute.nama_rute,
                    rute.id as id_rute,
                    rute.kode as kode_rute,
                    customer.nama as nama_customer,
                    coalesce(sum(sales_order_detail.estimasi_kubikasi)::NUMERIC,0) as kubikal,
                    plafon.tempo_label as terms,
                    faktur.total_penjualan,
                    sales_order.status_order,
                    string_agg(distinct sales_order_detail.id::text, ',') as id_sales_order_detail
                    from customer
                    join rute on customer.id_rute = rute.id
                    join cabang on customer.id_cabang = cabang.id
                    join plafon on plafon.id_customer = customer.id
                    join sales_order on sales_order.id_plafon = plafon.id
                    left join faktur on faktur.id_sales_order = sales_order.id
					left join wilayah4 on wilayah4.id = customer.id_wilayah4
                    join sales_order_detail on sales_order.id = sales_order_detail.id_sales_order
                    join proses_picking on sales_order_detail.id = proses_picking.id_order_detail
                    where customer.id_cabang = :id_cabang
                    and rute.id = :id_rute
                    and faktur.jenis_faktur = 'penjualan'
                    and sales_order.status_order in {status}
                    and proses_picking.id_armada = :id_armada
                    and proses_picking.id_driver = :id_driver
                    and proses_picking.delivering_date = :delivering_date
                    {self.before_this_date_query}
                    group by customer.kode, sales_order.id, wilayah4.nama, sales_order.no_order, faktur.no_faktur, sales_order.tanggal_order, rute.nama_rute, rute.id, rute.kode, customer.nama, plafon.tempo_label, faktur.total_penjualan, sales_order.status_order

                """
            )
            .bindparams({
                "id_cabang": id_cabang,
                "id_rute": id_rute,
                "id_armada": id_armada,
                "id_driver": id_driver,
                "delivering_date": delivering_date
            })
            .execute()
            .fetchall()
            .get()
        )

        list_faktur_shipping_multiple_principal = (
            self.query().setRawQuery(
                f"""
                 select
					customer.kode as kode_customer,
                    string_agg(sales_order.id::text, ',') as id_sales_order,
					wilayah4.nama as area,
					sales_order.no_order,
                    faktur.no_faktur,
                    sales_order.tanggal_order as tanggal_order,
                    rute.nama_rute,
                    rute.id as id_rute,
                    order_batch.id as id_order_batch,
                    rute.kode as kode_rute,
                    customer.nama as nama_customer,
                    coalesce(sum(sales_order_detail.estimasi_kubikasi)::NUMERIC,0) as kubikal,
                    plafon.tempo_label as terms,
                    faktur.total_penjualan,
                    sales_order.status_order,
                    string_agg(distinct sales_order_detail.id::text, ',') as id_sales_order_detail
                    from customer
                    join rute on customer.id_rute = rute.id
                    join cabang on customer.id_cabang = cabang.id
                    join plafon on plafon.id_customer = customer.id                    
                    join sales_order on sales_order.id_plafon = plafon.id
                    join faktur_detail on faktur_detail.id_sales_order = sales_order.id
                    join order_batch on order_batch.id = sales_order.id_order_batch
                    left join faktur on faktur.id = faktur_detail.id_faktur
					left join wilayah4 on wilayah4.id = customer.id_wilayah4
                    join sales_order_detail on sales_order.id = sales_order_detail.id_sales_order
                    join proses_picking on sales_order_detail.id = proses_picking.id_order_detail
                    where customer.id_cabang = :id_cabang
                    and rute.id = :id_rute
                    and faktur.jenis_faktur = 'penjualan'
                    and sales_order.status_order in {status}
                    and proses_picking.id_armada = :id_armada
                    and proses_picking.id_driver = :id_driver
                    and proses_picking.delivering_date = :delivering_date
                    {self.before_this_date_query}
                    group by customer.kode, wilayah4.nama, sales_order.no_order, faktur.no_faktur, sales_order.tanggal_order, rute.nama_rute, rute.id, rute.kode, customer.nama, plafon.tempo_label, faktur.total_penjualan, sales_order.status_order, order_batch.id
""")
            .bindparams({
                "id_cabang": id_cabang,
                "id_rute": id_rute,
                "id_armada": id_armada,
                "id_driver": id_driver,
                "delivering_date": delivering_date
            })
            .execute()
            .fetchall()
            .get()
        )

        # print(type(list_faktur_shipping_one_principal))
        # print(list_faktur_shipping_one_principal)

        list_faktur_shipping = [
            *list_faktur_shipping_one_principal.get("result", []),
            *list_faktur_shipping_multiple_principal.get("result", [])
        ]
        
        return {
            "list_faktur_shipping_info": list_faktur_shipping_info,
            "list_faktur_shipping": list_faktur_shipping
        }

    @handle_error
    def getDetailFakturShipping(self, id_sales_order, jenisFaktur=None ):
        id_order_batch = self.req('id_order_batch')
        if id_order_batch:
            id_sales_orders = self.req("id_sales_orders")
            if not id_sales_orders:
                raise nonServerErrorException("ID sales order tidak valid atau kosong", 400)
            id_sales_orders = [int(id) for id in id_sales_orders.split(",")]
            return self.__get_detail_faktur_by_id_sales_order_batch(id_order_batch=id_order_batch, id_sales_order=id_sales_orders, jenisFaktur=jenisFaktur)
        else:
            return self.__get_detail_faktur_by_id_sales_order(id_sales_order, jenisFaktur)

    def __get_retur_placeholder_detail_order(self, id_sales_order):
        return (
            self.query().setRawQuery(
                """
                SELECT
                    rrd.id_request_detail AS id_order_detail,
                    rr.id_sales_order,
                    p.nama AS nama_produk,
                    p.id AS id_produk,
                    p.kode_sku,
                    p.ppn,
                    COALESCE(rrd.pieces_diajukan, rrd.pieces_retur, 0) AS pieces_order,
                    COALESCE(rrd.box_diajukan, rrd.box_retur, 0) AS box_order,
                    COALESCE(rrd.karton_diajukan, rrd.karton_retur, 0) AS karton_order,
                    COALESCE(rrd.pieces_retur, rrd.pieces_diajukan, 0) AS pieces_retur,
                    COALESCE(rrd.box_retur, rrd.box_diajukan, 0) AS box_retur,
                    COALESCE(rrd.karton_retur, rrd.karton_diajukan, 0) AS karton_retur,
                    rrd.alasan_retur AS keterangan_retur,
                    0 AS pieces_picked,
                    0 AS box_picked,
                    0 AS karton_picked,
                    0 AS pieces_shipped,
                    0 AS box_shipped,
                    0 AS karton_shipped,
                    0 AS pieces_delivered,
                    0 AS box_delivered,
                    0 AS karton_delivered,
                    COALESCE(rrd.harga_satuan, 0) AS harga_jual,
                    COALESCE(rrd.total_retur, rrd.subtotal_retur, 0) AS subtotalorder,
                    puom1.nama AS puom1_nama,
                    puom1.kode AS puom1_kode,
                    puom2.nama AS puom2_nama,
                    puom3.nama AS puom3_nama,
                    puom1.faktor_konversi AS konversi_level1,
                    puom2.faktor_konversi AS konversi_level2,
                    puom3.faktor_konversi AS konversi_level3,
                    puom1.packing_lebar AS puom1_packing_lebar,
                    puom1.packing_panjang AS puom1_packing_panjang,
                    puom1.packing_tinggi AS puom1_packing_tinggi,
                    puom2.packing_lebar AS puom2_packing_lebar,
                    puom2.packing_panjang AS puom2_packing_panjang,
                    puom2.packing_tinggi AS puom2_packing_tinggi,
                    puom3.packing_lebar AS puom3_packing_lebar,
                    puom3.packing_panjang AS puom3_packing_panjang,
                    puom3.packing_tinggi AS puom3_packing_tinggi,
                    NULL AS v1r_id_dv,
                    NULL AS v1r_nama,
                    NULL AS v1r_diskon,
                    NULL AS v1r_kode,
                    NULL AS v1r_persen,
                    NULL AS v1r_minimal_subtotal_pembelian,
                    NULL AS v2r_id_dv,
                    NULL AS v2r_nama,
                    NULL AS v2r_diskon,
                    NULL AS v2r_kode,
                    NULL AS v2r_persen,
                    NULL AS v2r_minimal_subtotal_pembelian,
                    NULL AS v2p_id_dv,
                    NULL AS v2p_nama,
                    NULL AS v2p_diskon,
                    NULL AS v2p_kode,
                    NULL AS v2p_kategori_voucher,
                    NULL AS v2p_persen,
                    NULL AS v2p_nominal_diskon,
                    NULL AS v2p_minimal_subtotal_pembelian,
                    NULL AS v2p_minimal_jumlah_produk,
                    NULL AS v2p_level_uom,
                    NULL AS v2p_budget_diskon,
                    NULL AS v3r_id_dv,
                    NULL AS v3r_nama,
                    NULL AS v3r_diskon,
                    NULL AS v3r_kode,
                    NULL AS v3r_persen,
                    NULL AS v3r_minimal_subtotal_pembelian,
                    NULL AS v3p_id_dv,
                    NULL AS v3p_nama,
                    NULL AS v3p_diskon,
                    NULL AS v3p_kode,
                    NULL AS v3p_kategori_voucher,
                    NULL AS v3p_persen,
                    NULL AS v3p_nominal_diskon,
                    NULL AS v3p_budget_diskon
                FROM retur_request rr
                JOIN retur_request_detail rrd
                    ON rrd.id_request = rr.id_request
                JOIN produk p
                    ON p.id = rrd.id_produk
                LEFT JOIN produk_uom puom1
                    ON p.id = puom1.id_produk AND puom1.level = 1
                LEFT JOIN produk_uom puom2
                    ON p.id = puom2.id_produk AND puom2.level = 2
                LEFT JOIN produk_uom puom3
                    ON p.id = puom3.id_produk AND puom3.level = 3
                WHERE rr.id_sales_order = :id_sales_order
                ORDER BY rrd.id_request_detail
                """
            )
            .bindparams({"id_sales_order": id_sales_order})
            .execute()
            .fetchall()
            .get()
        )

    def __get_retur_placeholder_detail_header(self, id_sales_order):
        return (
            self.query().setRawQuery(
                """
                SELECT
                    customer.nama AS nama_customer,
                    customer.alamat AS alamat_customer,
                    customer.telepon AS telepon_customer,
                    customer.kode AS kode_customer,
                    sales_order.*,
                    rute.kode AS kode_rute,
                    principal.kode AS kode_principal,
                    principal.nama AS nama_principal,
                    NULL AS id_faktur,
                    rr.kode_request,
                    rr.kode_kpr,
                    rr.no_cn,
                    COALESCE(NULLIF(rr.no_cn, ''), NULLIF(rr.kode_request, ''), sales_order.no_order) AS nomor_faktur,
                    NULL AS nama_driver,
                    plafon.tempo_label
                FROM sales_order
                JOIN plafon
                    ON plafon.id = sales_order.id_plafon
                JOIN customer
                    ON customer.id = plafon.id_customer
                LEFT JOIN rute
                    ON rute.id = customer.id_rute
                LEFT JOIN principal
                    ON principal.id = plafon.id_principal
                LEFT JOIN retur_request rr
                    ON rr.id_sales_order = sales_order.id
                WHERE sales_order.id = :id_sales_order
                LIMIT 1
                """
            )
            .bindparams({"id_sales_order": id_sales_order})
            .execute()
            .fetchone()
            .result
        )

    def __get_detail_faktur_by_id_sales_order(self, id_sales_order, jenisFaktur=None):
        list_detail_order = (
            self.query().setRawQuery(
                f"""
                            -- CTE to get voucher information
                            WITH v_info AS (
                                SELECT 
                                    dv.id_sales_order_detail,
                                    -- Voucher 1 (Reguler)
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN dv.id ELSE NULL END) AS v1r_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN v1.nama_voucher ELSE NULL END) AS v1r_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN dv.jumlah_diskon ELSE NULL END) AS v1r_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN v1.kode_voucher ELSE NULL END) AS v1r_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN v1.persentase_diskon_1 ELSE NULL END) AS v1r_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN v1.minimal_subtotal_pembelian ELSE NULL END) AS v1r_minimal_subtotal_pembelian,

                                    -- Voucher 2 Reguler (tipe_voucher = 2 AND is_reguler = 1)
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN dv.id ELSE NULL END) AS v2r_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN v2.nama_voucher ELSE NULL END) AS v2r_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN dv.jumlah_diskon ELSE NULL END) AS v2r_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN v2.kode_voucher ELSE NULL END) AS v2r_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN v2.persentase_diskon_2 ELSE NULL END) AS v2r_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN v2.minimal_subtotal_pembelian ELSE NULL END) AS v2r_minimal_subtotal_pembelian,

                                    -- Voucher 2 Produk (tipe_voucher = 2 AND is_reguler = 0)
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN dv.id ELSE NULL END) AS v2p_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.nama_voucher ELSE NULL END) AS v2p_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN dv.jumlah_diskon ELSE NULL END) AS v2p_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.kode_voucher ELSE NULL END) AS v2p_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.kategori_voucher ELSE NULL END) AS v2p_kategori_voucher,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.persentase_diskon_2 ELSE NULL END) AS v2p_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.nominal_diskon ELSE NULL END) AS v2p_nominal_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.minimal_subtotal_pembelian ELSE NULL END) AS v2p_minimal_subtotal_pembelian,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.minimal_jumlah_produk ELSE NULL END) AS v2p_minimal_jumlah_produk,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.level_uom ELSE NULL END) AS v2p_level_uom,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.budget_diskon ELSE NULL END) AS v2p_budget_diskon,

                                    -- Voucher 3 Reguler (tipe_voucher = 3 AND is_reguler = 1)
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN dv.id ELSE NULL END) AS v3r_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN v3.nama_voucher ELSE NULL END) AS v3r_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN dv.jumlah_diskon ELSE NULL END) AS v3r_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN v3.kode_voucher ELSE NULL END) AS v3r_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN v3.persentase_diskon_3 ELSE NULL END) AS v3r_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN v3.minimal_subtotal_pembelian ELSE NULL END) AS v3r_minimal_subtotal_pembelian,

                                    -- Voucher 3 Produk (tipe_voucher = 3 AND is_reguler = 0)
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN dv.id ELSE NULL END) AS v3p_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.nama_voucher ELSE NULL END) AS v3p_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN dv.jumlah_diskon ELSE NULL END) AS v3p_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.kode_voucher ELSE NULL END) AS v3p_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.kategori_voucher ELSE NULL END) AS v3p_kategori_voucher,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.persentase_diskon_3 ELSE NULL END) AS v3p_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.nominal_diskon ELSE NULL END) AS v3p_nominal_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.budget_diskon ELSE NULL END) AS v3p_budget_diskon
                                FROM draft_voucher dv
                                LEFT JOIN voucher_1 v1 ON dv.id_voucher = v1.id AND dv.tipe_voucher = 1
                                LEFT JOIN voucher_2 v2 ON dv.id_voucher = v2.id AND dv.tipe_voucher = 2
                                LEFT JOIN voucher_3 v3 ON dv.id_voucher = v3.id AND dv.tipe_voucher = 3
                                WHERE dv.id_sales_order = :id_sales_order and dv.status_promo in (0,1)
                                GROUP BY dv.id_sales_order_detail
                            )

                            SELECT
                                sod.id as id_order_detail,
                                sod.id_sales_order,
                                p.nama as nama_produk,
                                p.id as id_produk,
                                p.kode_sku,
                                p.id_ppn,
                                mp.nama AS ppn_nama,
                                mp.kode AS ppn_kode,
                                COALESCE(mp.persentase, p.ppn, 0) AS ppn,
                                sod.pieces_order,
                                sod.box_order,
                                sod.karton_order,
                                sod.hargaorder,
                                sod.total_nilai_discount,
                                sod.pieces_retur,
                                sod.box_retur,
                                sod.karton_retur,
                                sod.keterangan_retur,
                                sod.pieces_picked,
                                sod.box_picked,
                                sod.karton_picked,
                                sod.pieces_shipped,
                                sod.box_shipped,
                                sod.karton_shipped,
                                sod.pieces_delivered,
                                sod.box_delivered,
                                sod.karton_delivered,
                                phj.harga as harga_jual,
                                sod.subtotalorder,
                                puom1.nama as puom1_nama,
                                puom1.kode as puom1_kode,
                                puom2.nama as puom2_nama,
                                puom3.nama as puom3_nama,
                                puom1.faktor_konversi as konversi_level1,
                                puom2.faktor_konversi as konversi_level2,
                                puom3.faktor_konversi as konversi_level3,
                                puom1.packing_lebar as puom1_packing_lebar,
                                puom1.packing_panjang as puom1_packing_panjang,
                                puom1.packing_tinggi as puom1_packing_tinggi,
                                puom2.packing_lebar as puom2_packing_lebar,
                                puom2.packing_panjang as puom2_packing_panjang,
                                puom2.packing_tinggi as puom2_packing_tinggi,
                                puom3.packing_lebar as puom3_packing_lebar,
                                puom3.packing_panjang as puom3_packing_panjang,
                                puom3.packing_tinggi as puom3_packing_tinggi,
                                -- Voucher 1 (Reguler)
                                v.v1r_id_dv,
                                v.v1r_nama,
                                v.v1r_diskon,
                                v.v1r_kode,
                                v.v1r_persen,
                                v.v1r_minimal_subtotal_pembelian,
                                -- Voucher 2 Reguler
                                v.v2r_id_dv,
                                v.v2r_nama,
                                v.v2r_diskon,
                                v.v2r_kode,
                                v.v2r_persen,
                                v.v2r_minimal_subtotal_pembelian,
                                -- Voucher 2 Produk
                                v.v2p_id_dv,
                                v.v2p_nama,
                                v.v2p_diskon,
                                v.v2p_kode,
                                v.v2p_kategori_voucher,
                                v.v2p_persen,
                                v.v2p_nominal_diskon,
                                v.v2p_minimal_subtotal_pembelian,
                                v.v2p_minimal_jumlah_produk,
                                v.v2p_level_uom,
                                v.v2p_budget_diskon,
                                -- Voucher 3 Reguler
                                v.v3r_id_dv,
                                v.v3r_nama,
                                v.v3r_diskon,
                                v.v3r_kode,
                                v.v3r_persen,
                                v.v3r_minimal_subtotal_pembelian,
                                -- Voucher 3 Produk
                                v.v3p_id_dv,
                                v.v3p_nama,
                                v.v3p_diskon,
                                v.v3p_kode,
                                v.v3p_kategori_voucher,
                                v.v3p_persen,
                                v.v3p_nominal_diskon,
                                v.v3p_budget_diskon
                            FROM sales_order so
                            LEFT JOIN faktur f ON f.id_sales_order = so.id
                            LEFT JOIN sales_order_detail sod ON sod.id_sales_order = so.id
                            LEFT JOIN plafon pl ON so.id_plafon = pl.id
                            LEFT JOIN produk p ON sod.id_produk = p.id
                            LEFT JOIN master_ppn mp ON mp.id = p.id_ppn
                            LEFT JOIN produk_harga_jual phj ON p.id = phj.id_produk AND phj.id_tipe_harga = pl.id_tipe_harga
                            LEFT JOIN produk_uom puom1 on p.id = puom1.id_produk and puom1.level = 1
                            LEFT JOIN produk_uom puom2 on p.id = puom2.id_produk and puom2.level = 2
                            LEFT JOIN produk_uom puom3 on p.id = puom3.id_produk and puom3.level = 3
                            LEFT JOIN v_info v ON v.id_sales_order_detail = sod.id
                            WHERE so.id = :id_sales_order
                            AND f.jenis_faktur = :jenis_faktur
                            {self.before_this_date_query_so}
                        """
            )
            .bindparams({
                "id_sales_order": id_sales_order,
                "jenis_faktur": jenisFaktur or 'penjualan'
            })
            .execute()
            .fetchall()
            .get()
        )

        list_detail_order = self._normalize_query_rows(list_detail_order)
        if not list_detail_order:
            list_detail_order = self._normalize_query_rows(
                self.__get_retur_placeholder_detail_order(id_sales_order)
            )

        detail_faktur = (
            self.query().setRawQuery(
                f"""
                            select
                            distinct customer.nama as nama_customer,
                            customer.alamat as alamat_customer,
                            customer.telepon as telepon_customer,
                            customer.kode as kode_customer,
                            sales_order.*,
                            faktur.*,
                            rute.kode as kode_rute,
                            principal.kode as kode_principal,
                            principal.nama as nama_principal,
                            faktur.id as id_faktur,
                            faktur.no_faktur as nomor_faktur,
                            users.nama as nama_driver,
                            plafon.tempo_label
                            from customer
                            left join rute
                            on rute.id = customer.id_rute
                            join plafon
                            on plafon.id_customer = customer.id
                            join principal
                            on principal.id = plafon.id_principal
                            join sales_order
                            on sales_order.id_plafon = plafon.id
                            join faktur
                            on sales_order.id = faktur.id_sales_order
                            join sales_order_detail
                            on sales_order_detail.id_sales_order = sales_order.id
                            join proses_picking
                            on proses_picking.id_order_detail = sales_order_detail.id
                            left join driver
                            on driver.id = proses_picking.id_driver
                            left join users
                            on users.id = driver.id_user
                            where faktur.id_sales_order = :id_sales_order 
                            and faktur.jenis_faktur = :jenis_faktur
                            {self.before_this_date_query}
                        """
            )
            .bindparams({
                "id_sales_order": id_sales_order,
                "jenis_faktur": jenisFaktur or 'penjualan'
            })
            .execute()
            .fetchone()
            .result
        )

        if not detail_faktur and list_detail_order:
            detail_faktur = self.__get_retur_placeholder_detail_header(id_sales_order)

        if not detail_faktur:
            return {
                "list_detail_order": list_detail_order or [],
                "detail_faktur": {}
            }

        if str(detail_faktur.get("no_order") or "").startswith("RETUR-"):
            detail_faktur["no_faktur"] = None
            detail_faktur["nomor_faktur"] = (
                detail_faktur.get("no_cn")
                or detail_faktur.get("kode_request")
                or detail_faktur.get("no_order")
            )

        if len(list(detail_faktur)):
            detail_faktur["status_order_str"] = status_order(detail_faktur["status_order"])

        detail_faktur_obj = {
            "list_detail_order": list_detail_order,
            "detail_faktur": detail_faktur
        }

        return detail_faktur_obj

    def __get_detail_faktur_by_id_sales_order_batch(self, id_order_batch,id_sales_order, jenisFaktur=None):
        list_detail_order = (
            self.query().setRawQuery(
                """
                WITH v_info AS (
                                SELECT 
                                    dv.id_sales_order_detail,
                                    -- Voucher 1 (Reguler)
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN dv.id ELSE NULL END) AS v1r_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN v1.nama_voucher ELSE NULL END) AS v1r_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN dv.jumlah_diskon ELSE NULL END) AS v1r_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN v1.kode_voucher ELSE NULL END) AS v1r_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN v1.persentase_diskon_1 ELSE NULL END) AS v1r_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 1 THEN v1.minimal_subtotal_pembelian ELSE NULL END) AS v1r_minimal_subtotal_pembelian,

                                    -- Voucher 2 Reguler (tipe_voucher = 2 AND is_reguler = 1)
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN dv.id ELSE NULL END) AS v2r_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN v2.nama_voucher ELSE NULL END) AS v2r_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN dv.jumlah_diskon ELSE NULL END) AS v2r_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN v2.kode_voucher ELSE NULL END) AS v2r_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN v2.persentase_diskon_2 ELSE NULL END) AS v2r_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 1 THEN v2.minimal_subtotal_pembelian ELSE NULL END) AS v2r_minimal_subtotal_pembelian,

                                    -- Voucher 2 Produk (tipe_voucher = 2 AND is_reguler = 0)
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN dv.id ELSE NULL END) AS v2p_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.nama_voucher ELSE NULL END) AS v2p_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN dv.jumlah_diskon ELSE NULL END) AS v2p_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.kode_voucher ELSE NULL END) AS v2p_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.kategori_voucher ELSE NULL END) AS v2p_kategori_voucher,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.persentase_diskon_2 ELSE NULL END) AS v2p_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.nominal_diskon ELSE NULL END) AS v2p_nominal_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.minimal_subtotal_pembelian ELSE NULL END) AS v2p_minimal_subtotal_pembelian,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.minimal_jumlah_produk ELSE NULL END) AS v2p_minimal_jumlah_produk,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.level_uom ELSE NULL END) AS v2p_level_uom,
                                    MAX(CASE WHEN dv.tipe_voucher = 2 AND v2.is_reguler = 0 THEN v2.budget_diskon ELSE NULL END) AS v2p_budget_diskon,

                                    -- Voucher 3 Reguler (tipe_voucher = 3 AND is_reguler = 1)
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN dv.id ELSE NULL END) AS v3r_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN v3.nama_voucher ELSE NULL END) AS v3r_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN dv.jumlah_diskon ELSE NULL END) AS v3r_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN v3.kode_voucher ELSE NULL END) AS v3r_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN v3.persentase_diskon_3 ELSE NULL END) AS v3r_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 1 THEN v3.minimal_subtotal_pembelian ELSE NULL END) AS v3r_minimal_subtotal_pembelian,

                                    -- Voucher 3 Produk (tipe_voucher = 3 AND is_reguler = 0)
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN dv.id ELSE NULL END) AS v3p_id_dv,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.nama_voucher ELSE NULL END) AS v3p_nama,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN dv.jumlah_diskon ELSE NULL END) AS v3p_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.kode_voucher ELSE NULL END) AS v3p_kode,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.kategori_voucher ELSE NULL END) AS v3p_kategori_voucher,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.persentase_diskon_3 ELSE NULL END) AS v3p_persen,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.nominal_diskon ELSE NULL END) AS v3p_nominal_diskon,
                                    MAX(CASE WHEN dv.tipe_voucher = 3 AND v3.is_reguler = 0 THEN v3.budget_diskon ELSE NULL END) AS v3p_budget_diskon
                                FROM draft_voucher dv
                                LEFT JOIN voucher_1 v1 ON dv.id_voucher = v1.id AND dv.tipe_voucher = 1
                                LEFT JOIN voucher_2 v2 ON dv.id_voucher = v2.id AND dv.tipe_voucher = 2
                                LEFT JOIN voucher_3 v3 ON dv.id_voucher = v3.id AND dv.tipe_voucher = 3
                                WHERE dv.id_sales_order IN :id_sales_order and dv.status_promo in (0,1)
                                GROUP BY dv.id_sales_order_detail
                            )

                            SELECT
                                sod.id as id_order_detail,
                                sod.id_sales_order,
                                p.nama as nama_produk,
                                p.id as id_produk,
                                p.kode_sku,
                                p.id_ppn,
                                mp.nama AS ppn_nama,
                                mp.kode AS ppn_kode,
                                COALESCE(mp.persentase, p.ppn, 0) AS ppn,
                                f.id as id_faktur,
                                sod.pieces_order,
                                sod.box_order,
                                sod.karton_order,
                                sod.hargaorder,
                                sod.total_nilai_discount,
                                sod.pieces_retur,
                                sod.box_retur,
                                sod.karton_retur,
                                sod.keterangan_retur,
                                sod.pieces_picked,
                                sod.box_picked,
                                sod.karton_picked,
                                sod.pieces_shipped,
                                sod.box_shipped,
                                sod.karton_shipped,
                                sod.pieces_delivered,
                                sod.box_delivered,
                                sod.karton_delivered,
                                phj.harga as harga_jual,
                                sod.subtotalorder,
                                puom1.nama as puom1_nama,
                                puom1.kode as puom1_kode,
                                puom2.nama as puom2_nama,
                                puom3.nama as puom3_nama,
                                puom1.faktor_konversi as konversi_level1,
                                puom2.faktor_konversi as konversi_level2,
                                puom3.faktor_konversi as konversi_level3,
                                puom1.packing_lebar as puom1_packing_lebar,
                                puom1.packing_panjang as puom1_packing_panjang,
                                puom1.packing_tinggi as puom1_packing_tinggi,
                                puom2.packing_lebar as puom2_packing_lebar,
                                puom2.packing_panjang as puom2_packing_panjang,
                                puom2.packing_tinggi as puom2_packing_tinggi,
                                puom3.packing_lebar as puom3_packing_lebar,
                                puom3.packing_panjang as puom3_packing_panjang,
                                puom3.packing_tinggi as puom3_packing_tinggi,
                                -- Voucher 1 (Reguler)
                                v.v1r_id_dv,
                                v.v1r_nama,
                                v.v1r_diskon,
                                v.v1r_kode,
                                v.v1r_persen,
                                v.v1r_minimal_subtotal_pembelian,
                                -- Voucher 2 Reguler
                                v.v2r_id_dv,
                                v.v2r_nama,
                                v.v2r_diskon,
                                v.v2r_kode,
                                v.v2r_persen,
                                v.v2r_minimal_subtotal_pembelian,
                                -- Voucher 2 Produk
                                v.v2p_id_dv,
                                v.v2p_nama,
                                v.v2p_diskon,
                                v.v2p_kode,
                                v.v2p_kategori_voucher,
                                v.v2p_persen,
                                v.v2p_nominal_diskon,
                                v.v2p_minimal_subtotal_pembelian,
                                v.v2p_minimal_jumlah_produk,
                                v.v2p_level_uom,
                                v.v2p_budget_diskon,
                                -- Voucher 3 Reguler
                                v.v3r_id_dv,
                                v.v3r_nama,
                                v.v3r_diskon,
                                v.v3r_kode,
                                v.v3r_persen,
                                v.v3r_minimal_subtotal_pembelian,
                                -- Voucher 3 Produk
                                v.v3p_id_dv,
                                v.v3p_nama,
                                v.v3p_diskon,
                                v.v3p_kode,
                                v.v3p_kategori_voucher,
                                v.v3p_persen,
                                v.v3p_nominal_diskon,
                                v.v3p_budget_diskon
                            FROM order_batch ob
							JOIN sales_order so ON so.id_order_batch = ob.id
							JOIN faktur_detail fd ON fd.id_sales_order = so.id
                            LEFT JOIN faktur f ON fd.id_faktur = f.id
                            LEFT JOIN sales_order_detail sod ON sod.id_sales_order = so.id
                            LEFT JOIN plafon pl ON so.id_plafon = pl.id
                            LEFT JOIN produk p ON sod.id_produk = p.id
                            LEFT JOIN master_ppn mp ON mp.id = p.id_ppn
                            LEFT JOIN produk_harga_jual phj ON p.id = phj.id_produk AND phj.id_tipe_harga = pl.id_tipe_harga
                            LEFT JOIN produk_uom puom1 on p.id = puom1.id_produk and puom1.level = 1
                            LEFT JOIN produk_uom puom2 on p.id = puom2.id_produk and puom2.level = 2
                            LEFT JOIN produk_uom puom3 on p.id = puom3.id_produk and puom3.level = 3
                            LEFT JOIN v_info v ON v.id_sales_order_detail = sod.id
                               WHERE ob.id = :id_order_batch
                            AND f.jenis_faktur = :jenis_faktur
                """
            )
            .bindparams_v2({
                "id_order_batch": id_order_batch,
                "jenis_faktur": jenisFaktur or 'penjualan',
                "id_sales_order": id_sales_order
            },
                expanding_keys=['id_sales_order']
        )
            .execute()
            .fetchall()
            .get()
        )
        list_detail_order = self._normalize_query_rows(list_detail_order)

        id_faktur = list_detail_order[0]['id_faktur'] if len(list_detail_order) else None

        detail_faktur = (
            self.query().setRawQuery(
                f"""
                                    select
                                    distinct customer.nama as nama_customer,
                                    customer.alamat as alamat_customer,
                                    customer.telepon as telepon_customer,
                                    customer.kode as kode_customer,
                                    sales_order.*,
                                    faktur.*,
                                    rute.kode as kode_rute,
                                    principal.kode as kode_principal,
                                    principal.nama as nama_principal,
                                    faktur.id as id_faktur,
                                    faktur.no_faktur as nomor_faktur,
                                    users.nama as nama_driver,
                                    plafon.tempo_label
                                    from customer
                                    left join rute
                                    on rute.id = customer.id_rute
                                    join plafon
                                    on plafon.id_customer = customer.id
                                    join principal
                                    on principal.id = plafon.id_principal
                                    join sales_order
                                    on sales_order.id_plafon = plafon.id
                                    join faktur_detail
                                    on faktur_detail.id_sales_order = sales_order.id
                                    join faktur
                                    on faktur.id = faktur_detail.id_faktur
                                    join sales_order_detail
                                    on sales_order_detail.id_sales_order = sales_order.id
                                    join proses_picking
                                    on proses_picking.id_order_detail = sales_order_detail.id
                                    left join driver
                                    on driver.id = proses_picking.id_driver
                                    left join users
                                    on users.id = driver.id_user
                                    where faktur.id = :id_faktur 
                                    and faktur.jenis_faktur = :jenis_faktur
                                    {self.before_this_date_query}
                                """
            )
            .bindparams({
                "id_faktur":id_faktur,
                "jenis_faktur": jenisFaktur or 'penjualan'
            })
            .execute()
            .fetchone()
            .result
        )

        if not detail_faktur:
            return {
                "list_detail_order": list_detail_order or [],
                "detail_faktur": {}
            }

        if len(list(detail_faktur)):
            detail_faktur["status_order_str"] = status_order(detail_faktur["status_order"])
        detail_faktur_obj = {
            "list_detail_order": list_detail_order,
            "detail_faktur": detail_faktur
        }
        return detail_faktur_obj

    def __mapping_produk_by_sales_order(self,detail_produk_list):
        mapping = {}
        for item in detail_produk_list:
            id_sales_order = item['id_sales_order']
            if id_sales_order not in mapping:
                mapping[id_sales_order] = [
                    item
                ]

            else:
                mapping[id_sales_order] = [
                    *mapping[id_sales_order], item
                ]

        return mapping

    @handle_error_rollback
    def submitShipping(self):
        token = request.headers.get('Authorization')
        if not token:
            raise nonServerErrorException("Token tidak ditemukan", 403)
        token = token.replace("Bearer ", "")
        if not token:
            raise nonServerErrorException("Token tidak ditemukan", 403)
        user = (
            self.query().setRawQuery(
                "SELECT id,id_cabang FROM users WHERE tokens = :token",
            ).bindparams({
                'token': token
            }).execute().fetchone().result
        )

        # Ambil parameter dari request

        id_rute = self.req('id_rute')
        raw_id_cabang = self.req('id_cabang')
        raw_id_armada = self.req('id_armada')
        raw_id_driver = self.req('id_driver')
        delivering_date = self._normalize_delivery_date(self.req('delivering_date'))
        faktur_ids = self.req('faktur_ids')
        faktur_data = self.req('faktur_data')
        nama_fakturist = self.req('nama_fakturist')

        if raw_id_cabang in (None, '', 'None') or raw_id_armada in (None, '', 'None') or raw_id_driver in (None, '', 'None'):
            raise nonServerErrorException("ID cabang, armada, dan driver wajib diisi sebelum submit faktur", 400)

        id_cabang = int(raw_id_cabang)
        id_armada = int(raw_id_armada)
        id_driver = int(raw_id_driver)

        is_periode_closed, next_date = self.check_is_periode_closed()

        # Validasi data
        if not faktur_ids or not faktur_data or not isinstance(faktur_data, list):
            raise nonServerErrorException("Data faktur tidak valid", 400)

        # Set tanggal saat ini
        tanggal_sekarang = date_now()
        if is_periode_closed:
            tanggal_sekarang = next_date.strftime('%Y-%m-%d')

        # Validasi kesesuaian data faktur
        faktur_ids_set = set(map(int, faktur_ids))
        faktur_data_ids = {
            int(x.strip())
            for faktur in faktur_data
            for x in (
                [str(faktur["id_sales_order"])] if isinstance(faktur["id_sales_order"], int)
                else str(faktur["id_sales_order"]).split(',')
            )
            if x.strip().isdigit()
        }

        if faktur_ids_set != faktur_data_ids:
            raise nonServerErrorException("Data faktur tidak sesuai dengan IDs yang diberikan", 400)

        data_mapping_by_faktur = {}

        # Proses setiap faktur
        for faktur_item in faktur_data:

            id_sales_orders = []

            if isinstance(faktur_item['id_sales_order']  ,str):
                ids = faktur_item['id_sales_order'].split(',')
                id_sales_orders = [int(id_.strip()) for id_ in ids if id_.strip().isdigit()]
            elif isinstance(faktur_item['id_sales_order'],int):
                id_sales_orders = [faktur_item['id_sales_order']]


            for id_sales_order in id_sales_orders:

                # Dapatkan sales_order
                so = sales_order.query.filter(sales_order.id == id_sales_order).first()
                if not so:
                    raise nonServerErrorException(f"Sales Order dengan ID {id_sales_order} tidak ditemukan", 404)

                # Update status sales_order
                so.status_order = 4
                so.tanggal_faktur = tanggal_sekarang
                self.flush()

            # Update faktur
            id_order_batch = faktur_item['faktur_info'].get('id_order_batch', None)
            faktur_terkait = None
            if id_order_batch:
                faktur_terkait = Faktur.query.filter(Faktur.id_order_batch == id_order_batch).first()
                data_mapping_by_faktur[faktur_terkait.id] = self.__get_data_profile_by_order_batch( id_order_batch )
            else:
                faktur_terkait = Faktur.query.filter(Faktur.id_sales_order == id_sales_order).first()
                data_mapping_by_faktur[faktur_terkait.id] = self.__get_data_profile_by_sales_order( id_sales_order )

            if faktur_terkait:
                faktur_terkait.status_faktur = 1
                faktur_terkait.nama_fakturist = nama_fakturist

                # Update nilai faktur dari rincian_pembayaran
                if 'rincian_pembayaran' in faktur_item:
                    rincian = faktur_item['rincian_pembayaran']

                    if 'subtotal' in rincian:
                        faktur_terkait.subtotal_penjualan = format_angka(rincian['subtotal'])

                        so.total_order = format_angka(rincian['subtotal'])

                    if 'total_penjualan' in rincian:
                        faktur_terkait.total_penjualan = format_angka(rincian['total_penjualan'])

                    if 'diskon_nota' in rincian:
                        faktur_terkait.subtotal_diskon = format_angka(rincian['diskon_nota'])

                    if 'pajak' in rincian:
                        faktur_terkait.pajak = format_angka(rincian['pajak'])

                    # Hitung DPP (subtotal - diskon_nota)
                    if 'subtotal' in rincian and 'diskon_nota' in rincian:
                        subtotal = format_angka(rincian['subtotal'])
                        diskon_nota = format_angka(rincian['diskon_nota'])
                        faktur_terkait.dpp = format_angka(subtotal - diskon_nota)



                self.flush()

            # Update data faktur detail for batch order
            if id_order_batch:
                new_detail_produk_list = []
                for detail_produk in faktur_item.get('detail_produk', []):
                    data_faktur = next( (fd for fd in faktur_item.get('detail_faktur', []) if fd['id_produk'] == detail_produk['id_produk']), None)
                    if data_faktur:
                        new_detail_produk_list.append(
                            {
                                'id_sales_order': data_faktur['id_sales_order'],
                                **detail_produk
                            }
                        )
                mapping_produk = self.__mapping_produk_by_sales_order(new_detail_produk_list)
                for id_so, detail_produk in mapping_produk.items():
                    update_faktur_detail = FakturDetailModel.query.filter(
                        FakturDetailModel.id_sales_order == id_so,
                    ).first()
                    subtotal_all_product = sum(
                        format_angka(dp.get('subtotal',0)) - format_angka(dp.get('total_diskon',0))
                        for dp in detail_produk
                    )
                    subtotal_diskon_all_product = sum(
                        format_angka(dp.get('total_diskon',0))
                        for dp in detail_produk
                    )
                    pajak_all_product = sum(
                        format_angka(dp.get('ppn',0))
                        for dp in detail_produk
                    )
                    update_faktur_detail.subtotal = subtotal_all_product
                    update_faktur_detail.pajak = pajak_all_product
                    update_faktur_detail.subtotal_diskon = subtotal_diskon_all_product
                    update_faktur_detail.total = format_angka(subtotal_all_product) + format_angka(pajak_all_product)

                    self.flush()


            # Buat mapping produk untuk mempermudah akses data
            produk_mapping = {item['id_produk']: item for item in faktur_item.get('detail_produk', [])}

            # Proses detail faktur
            for detail_faktur in faktur_item['detail_faktur']:
                id_order_detail = detail_faktur['id_order_detail']
                id_produk = detail_faktur['id_produk']

                # Dapatkan detail order
                detail = sales_order_detail.query.filter(sales_order_detail.id == id_order_detail).first()
                if not detail:
                    raise nonServerErrorException(f"Detail order dengan ID {id_order_detail} tidak ditemukan", 404)

                # Update nilai total_nilai_discount dan subtotalorder
                produk_detail = produk_mapping.get(id_produk)
                if produk_detail:
                    if 'total_diskon' in produk_detail:
                        detail.total_nilai_discount = format_angka(produk_detail['total_diskon'])

                    if 'subtotal' in produk_detail and 'total_diskon' in produk_detail:
                        subtotal = format_angka(produk_detail['subtotal'])
                        total_diskon = format_angka(produk_detail['total_diskon'])
                        detail.subtotalorder = format_angka(subtotal - total_diskon)

                # Salin nilai dari picked ke shipped
                detail.pieces_shipped = detail.pieces_picked
                detail.box_shipped = detail.box_picked
                detail.karton_shipped = detail.karton_picked
                self.flush()

                # Dapatkan proses_picking terkait
                picking = prosesPicking.query.filter(prosesPicking.id_order_detail == detail.id).first()
                if picking:
                    # Update date_on_delivery
                    picking.date_on_delivery = tanggal_sekarang
                    self.flush()

                    # Dapatkan produk_id
                    produk_id = picking.id_produk
                    jumlah_picked = picking.jumlah_picked

                    if jumlah_picked and produk_id:
                        # Update stok
                        stok_item = stok.query.filter(
                            stok.produk_id == produk_id,
                            stok.cabang_id == id_cabang
                        ).first()

                        if stok_item:
                            # Kurangi jumlah_picked
                            stok_item.jumlah_picked -= jumlah_picked

                            # Tambah jumlah_delivery
                            stok_item.jumlah_delivery = (stok_item.jumlah_delivery or 0) + jumlah_picked

                            # Update tanggal dan waktu
                            stok_item.tanggal_update = tanggal_sekarang
                            stok_item.waktu_update = time_now()
                            self.flush()

                if produk_detail and 'voucher_detail' in produk_detail:
                    voucher_info = produk_detail['voucher_detail']

                    voucher_fields = [
                        ('v1r_id_dv', 'v1r_diskon'),
                        ('v2r_id_dv', 'v2r_diskon'),
                        ('v3r_id_dv', 'v3r_diskon'),
                        ('v2p_id_dv', 'v2p_diskon'),
                        ('v3p_id_dv', 'v3p_diskon')
                    ]

                    for id_field, diskon_field in voucher_fields:
                        id_dv = detail_faktur.get(id_field)

                        if id_dv is not None:
                            # Ambil nilai diskon dari voucher_detail
                            diskon_value = voucher_info.get(diskon_field, 0)
                            formatted_diskon = format_angka(diskon_value) if diskon_value is not None else 0

                            # Dapatkan draft voucher
                            dv_entry = draft_voucher.query.filter(draft_voucher.id == id_dv).first()

                            if dv_entry:
                                # Update status jika diskon = 0
                                if formatted_diskon == 0:
                                    dv_entry.status_promo = 3

                                # Update jumlah diskon
                                dv_entry.jumlah_diskon = formatted_diskon
                                self.flush()

            # Update tenggat waktu faktur (delivering_date + plafon.top)
            # Get sales_order with related plafon data
            for id_sales_order in id_sales_orders:
                sales_order_data = (
                    self.db
                    .session
                    .query(sales_order, plafon)
                    .join(plafon, sales_order.id_plafon == plafon.id)
                    .filter(sales_order.id == id_sales_order)
                    .first()
                )

                if sales_order_data:
                    update_so, plafon_data = sales_order_data

                    # Get delivering_date from proses_picking
                    delivering_date_result = (
                        self.db
                        .session
                        .query(prosesPicking.delivering_date)
                        .join(sales_order_detail, prosesPicking.id_order_detail == sales_order_detail.id)
                        .filter(sales_order_detail.id_sales_order == id_sales_order)
                        .first()
                    )

                    if delivering_date_result and delivering_date_result.delivering_date:
                        delivering_date_from_db = delivering_date_result.delivering_date
                        top_days = plafon_data.top or 0
                        if is_periode_closed:
                            # Jika periode akuntansi ditutup, gunakan next_date sebagai delivering_date
                            top_days += 1

                        # Calculate tanggal_jatuh_tempo = delivering_date + top
                        tanggal_jatuh_tempo = (delivering_date_from_db + timedelta(days=top_days)).strftime("%Y-%m-%d")
                        update_so.tanggal_jatuh_tempo = tanggal_jatuh_tempo
                        update_so.tanggal_cetak_jatuh_tempo = tanggal_jatuh_tempo

                        self.flush()

        payload_pubsub = {
            "created_by": user['id'],
            "id_fitur_mal": 4,
            "data": data_mapping_by_faktur
        }

        pubsub = getattr(current_app, 'pubsub', None)
        if pubsub:
            success = pubsub.publish(data=payload_pubsub, topic='create_jurnal')
            if success:
                current_app.logger.info("Published to PubSub successfully")
            else:
                current_app.logger.error("Failed to publish to PubSub")
                raise nonServerErrorException(status_code=500, message='Gagal mengirim pesan ke sistem jurnal')
        else:
            current_app.logger.error("PubSub client not found")
            raise nonServerErrorException(status_code=500, message='Gagal mengirim pesan ke sistem jurnal')

        # Commit perubahan
        self.commit()

        return {
            "status": "success",
            "message": "Pengiriman berhasil diproses",
            "data": {
                "tanggal": datetime.strptime(tanggal_sekarang, "%Y-%m-%d").strftime('%d/%m/%Y'),
            }
        }, 200
            
    @handle_error
    def getListRuteHistory(self, id_cabang):
        return (
            self.query().setRawQuery(
                """
                    select 
                    count(distinct customer.nama) as jumlah_toko,
                    count(distinct faktur.id) as jumlah_nota,
                    coalesce(sum(sales_order_detail.estimasi_kubikasi), 0) as kubikal,
                    count(distinct case 
                        when faktur.status_faktur = 5  or faktur.status_faktur = 8
                        then faktur.id  
                    end) as nota_terkirim,
                    count(distinct case 
                        when faktur.status_faktur = 4
                        then faktur.id  
                    end) as nota_proses,
                    count(distinct case 
                        when faktur.status_faktur = 7 
                        then faktur.id  
                    end) as nota_gagal,
                    rute.id as id_rute,
                    rute.nama_rute,
                    rute.kode,
                    armada.nama as nama_armada,
                    users.nama as nama_driver
                    
                    from customer
                    join rute on customer.id_rute = rute.id 
                    join cabang on customer.id_cabang = cabang.id
                    join plafon on plafon.id_customer = customer.id
                    join sales_order on sales_order.id_plafon = plafon.id
                    join faktur on faktur.id_sales_order = sales_order.id
                    join sales_order_detail on sales_order_detail.id_sales_order = sales_order.id
                    join proses_picking on proses_picking.id_order_detail = sales_order_detail.id
                    join armada on armada.id = proses_picking.id_armada
                    join driver on driver.id = proses_picking.id_driver
                    join users on users.id = driver.id_user
                    where customer.id_cabang = :id_cabang
                    and
                    faktur.status_faktur in (4, 3, 7, 8)
                    group by
                    rute.kode,
                    rute.id, 
                    rute.nama_rute, 
                    armada.nama,
                    users.nama;

                """
            )
            .bindparams({
                "id_cabang": id_cabang
            })
            .execute()
            .fetchall()
            .get()
        )

    @handle_error
    def getListNota(self):
        id_cabang = self.req("id_cabang")
        id_rute = self.req("id_rute")
        status_faktur = self.req("status_faktur")
        
        return (
            self.query().setRawQuery(
                """
                    select
                    sales_order.id as id_sales_order,
                    faktur.no_faktur,
                    sales_order.tanggal_order as tanggal_order,
                    rute.nama_rute,
                    rute.id as id_rute,
                    customer.nama as nama_customer,                                  
                    sales_order.total_kubikasi as kubikal,
                    faktur.jenis_faktur
                    from customer
                    join rute on customer.id_rute = rute.id 
                    join cabang on customer.id_cabang = cabang.id
                    join plafon on plafon.id_customer = customer.id
                    join sales_order on sales_order.id_plafon = plafon.id
                    join faktur on faktur.id_sales_order = sales_order.id
                    where customer.id_cabang = :id_cabang
                    and rute.id = :id_rute
                    and faktur.status_faktur = :status_faktur
                """
            )
            .bindparams({
                "id_cabang": id_cabang,
                "id_rute": id_rute,
                "status_faktur": status_faktur 
            })
            .execute()
            .fetchall()
            .get()
        )

    @handle_error  
    def getListOrder(self, id_cabang):
        listOrder = (
            self.query().setRawQuery(
                f"""
                    select 
                    distinct faktur.id as id_faktur,
                    sales_order.no_order,
                    sales_order.tanggal_order,
                    faktur.status_faktur,
                    customer.nama as nama_customer,
                    principal.nama as nama_principal
                    from customer
                    join cabang on customer.id_cabang = cabang.id
                    join plafon on plafon.id_customer = customer.id
                    join principal on principal.id = plafon.id_principal
                    join sales_order on sales_order.id_plafon = plafon.id
                    join faktur on faktur.id_sales_order = sales_order.id
                    where 
                    customer.id_cabang = :id_cabang
                    and 
                    faktur.status_faktur in (1, 2, 3, 4, 5)
                    and 
                    faktur.jenis_faktur = 'penjualan'
                    {self.before_this_date_query}
                """
            )
            .bindparams({
                "id_cabang": id_cabang,
            })
            .execute()
            .fetchall()
            .get()
        )
        
        return {
            "listOrder": listOrder,
            "last_update": datetime_now()
        }

    @handle_error
    def getRealisasiDetail(self):
        id_cabang = self.req("id_cabang")
        id_rute = self.req("id_rute")
        id_sales_order = self.req("id_sales_order")
        id_armada = self.req("id_armada")
        id_driver = self.req("id_driver")
        delivering_date = self._normalize_delivery_date(self.req("delivering_date"))
        
        result = (
            self.query().setRawQuery(
                f"""
                    SELECT
                    DISTINCT produk.nama AS nama_produk,
                    rute.id AS id_rute,
                    faktur.id as id_faktur,
                    produk.id AS produk_id,
                    produk.kode_sku,
                    produk.isiperbox AS isi_per_box_produk,
                    produk.isiperkarton AS isi_per_karton_produk,
                    coalesce(SUM(sales_order_detail.pieces_picked),0) AS total_pieces,
                    coalesce(SUM(sales_order_detail.box_picked),0) AS total_box,
                    coalesce(SUM(sales_order_detail.karton_picked),0) AS total_karton,
                    coalesce(SUM(sales_order_detail.pieces_delivered),0) AS realisasi,
                    COALESCE(SUM(proses_picking.jumlah_picked), 0) AS jumlah_picked,
                    ARRAY_AGG(sales_order_detail.id) AS id_detail_sales_array,
                    COALESCE(MAX(CASE WHEN puom1.level = 1 THEN puom1.faktor_konversi END), 1) as konversi1,
                    COALESCE(MAX(CASE WHEN puom2.level = 2 THEN puom2.faktor_konversi END), 0) as konversi2,
                    COALESCE(MAX(CASE WHEN puom3.level = 3 THEN puom3.faktor_konversi END), 0) as konversi3
                    FROM customer
                    JOIN rute ON customer.id_rute = rute.id
                    JOIN cabang ON customer.id_cabang = cabang.id
                    JOIN plafon ON plafon.id_customer = customer.id
                    JOIN sales_order ON sales_order.id_plafon = plafon.id
                    JOIN faktur on faktur.id_sales_order = sales_order.id
                    JOIN sales_order_detail ON sales_order_detail.id_sales_order = sales_order.id
                    JOIN produk ON sales_order_detail.id_produk = produk.id
                    LEFT JOIN proses_picking ON proses_picking.id_order_detail = sales_order_detail.id
                    left join produk_uom puom1 on puom1.id_produk = produk.id and puom1.level = 1
                    left join produk_uom puom2 on puom2.id_produk = produk.id and puom2.level = 2
                    left join produk_uom puom3 on puom3.id_produk = produk.id and puom3.level = 3
                    WHERE customer.id_cabang = :id_cabang
                    AND rute.id = :id_rute
                    AND sales_order.id = :id_sales_order
                    and faktur.jenis_faktur = 'penjualan'
                    and proses_picking.id_armada = :id_armada
                    and proses_picking.id_driver = :id_driver
                    and proses_picking.delivering_date = :delivering_date
                    and sales_order.status_order in (4,11)
                    {self.before_this_date_query}
                    GROUP BY 
                    nama_produk, 
                    rute.id, 
                    produk_id, 
                    produk.kode_sku, 
                    isi_per_box_produk, 
                    isi_per_karton_produk, 
                    faktur.id
                """
            )
            .bindparams({
                "id_cabang": id_cabang,
                "id_rute": id_rute,
                "id_sales_order": id_sales_order,
                "id_armada": id_armada,
                "id_driver": id_driver,
                "delivering_date": delivering_date
            })
            .execute()
            .fetchall()
            .get()
        )
        
        return jsonify(result)

    @handle_error_rollback
    def submitRealisasiDetail(self):
        # Ambil data dari request

        token = request.headers.get('Authorization')
        if not token:
            raise nonServerErrorException("Token tidak ditemukan", 403)
        token = token.replace("Bearer ", "")
        if not token:
            raise nonServerErrorException("Token tidak ditemukan", 403)
        user = (
            self.query().setRawQuery(
                "SELECT id,id_cabang FROM users WHERE tokens = :token",
            ).bindparams({
                'token': token
            }).execute().fetchone().result
        )

        realisasi_list = self.req("realisasi")
        id_cabang = int(self.req("id_cabang"))
        id_fitur_mal = 5
        id_setoran = None
        id_sales_order = self.req("id_sales_order")
        id_order_batch = self.req("id_order_batch")
        nama_user = self.req("nama_user")
        pembayaran_via_dropper = self.req("pembayaran_via_dropper")
        no_faktur = self.req("no_faktur")

        # Validasi data
        if not realisasi_list or not isinstance(realisasi_list, list):
            raise nonServerErrorException("Data realisasi tidak valid atau kosong", 400)

        is_periode_closed, next_date = self.check_is_periode_closed()
        # Tanggal saat ini
        current_date = date_now()
        if is_periode_closed:
            current_date = next_date.strftime('%Y-%m-%d')
        current_time = time_now()

        # Kumpulkan semua ID faktur untuk diproses
        faktur_ids = set()
        need_revision = False

        def normalize_id_list(value):
            if isinstance(value, int):
                return [value]
            if isinstance(value, str):
                return [
                    int(x.strip())
                    for x in value.split(',')
                    if x.strip().isdigit()
                ]
            if isinstance(value, list):
                return [
                    int(x)
                    for x in value
                    if str(x).strip().isdigit()
                ]
            return []

        # Proses setiap item realisasi untuk validasi dan perbandingan
        for item in realisasi_list:
            realisasi_value = item.get("realisasi")
            id_produk = item.get("id_produk")
            id_faktur = item.get("id_faktur")
            id_detail_sales = item.get("id_detail_sales", [])

            # KONVERSI id_detail_sales ke list jika berupa integer
            id_detail_sales = normalize_id_list(id_detail_sales)
            realisasi_value = self._safe_number(realisasi_value, 0)

            # Nilai konversi
            konversi1 = self._normalize_uom_conversion(item.get("konversi1"), 1)
            konversi2 = self._normalize_uom_conversion(item.get("konversi2"), 2)
            konversi3 = self._normalize_uom_conversion(item.get("konversi3"), 3)

            # Validasi nilai realisasi
            if realisasi_value < 0:
                raise nonServerErrorException(f"Nilai realisasi tidak valid untuk produk {id_produk}", 400)

            faktur_ids.add(id_faktur)

            # Hitung total shipped dalam pieces untuk item ini
            total_shipped_pieces = 0
            for id_detail in id_detail_sales:
                detail = sales_order_detail.query.filter(sales_order_detail.id == id_detail).first()
                if detail:
                    shipped_pieces = self._uom_total_pieces(
                        detail.pieces_shipped,
                        detail.box_shipped,
                        detail.karton_shipped,
                        konversi1,
                        konversi2,
                        konversi3
                    )
                    total_shipped_pieces += shipped_pieces

            # Validasi: realisasi tidak boleh lebih besar dari shipped
            if realisasi_value > total_shipped_pieces:
                raise nonServerErrorException(
                    f"Realisasi ({realisasi_value}) tidak boleh lebih besar dari jumlah yang dikirim ({total_shipped_pieces}) untuk produk ID {id_produk}",
                    400
                )

            # Cek apakah ada perbedaan (perlu revisi)
            if realisasi_value != total_shipped_pieces:
                need_revision = True

        # Proses setiap item realisasi
        for item in realisasi_list:
            realisasi_value = item.get("realisasi")
            id_produk = item.get("id_produk")
            id_faktur = item.get("id_faktur")
            id_detail_sales = item.get("id_detail_sales", [])

            id_detail_sales = normalize_id_list(id_detail_sales)
            realisasi_value = self._safe_number(realisasi_value, 0)
            # Nilai konversi
            konversi1 = self._normalize_uom_conversion(item.get("konversi1"), 1)
            konversi2 = self._normalize_uom_conversion(item.get("konversi2"), 2)
            konversi3 = self._normalize_uom_conversion(item.get("konversi3"), 3)

            total_shipped_pieces = 0
            for id_detail in id_detail_sales:
                detail = sales_order_detail.query.filter(sales_order_detail.id == id_detail).first()
                if detail:
                    total_shipped_pieces += self._uom_total_pieces(
                        detail.pieces_shipped,
                        detail.box_shipped,
                        detail.karton_shipped,
                        konversi1,
                        konversi2,
                        konversi3
                    )

            remaining_realisasi = int(self._safe_number(realisasi_value, 0))
            is_full_realisasi = remaining_realisasi == total_shipped_pieces

            # Update sales_order_detail
            for id_detail in id_detail_sales:
                detail = sales_order_detail.query.filter(sales_order_detail.id == id_detail).first()

                if not detail:
                    continue

                detail_shipped_pieces = self._uom_total_pieces(
                    detail.pieces_shipped,
                    detail.box_shipped,
                    detail.karton_shipped,
                    konversi1,
                    konversi2,
                    konversi3
                )

                if is_full_realisasi:
                    pieces_delivered = detail.pieces_shipped or 0
                    box_delivered = detail.box_shipped or 0
                    karton_delivered = detail.karton_shipped or 0
                    delivered_for_detail = detail_shipped_pieces
                else:
                    delivered_for_detail = min(remaining_realisasi, detail_shipped_pieces)
                    delivered_qty = self._split_total_to_uom(delivered_for_detail, konversi1, konversi2, konversi3)
                    pieces_delivered = delivered_qty["pieces"]
                    box_delivered = delivered_qty["box"]
                    karton_delivered = delivered_qty["karton"]

                # Update jumlah delivered
                detail.pieces_delivered = pieces_delivered
                detail.box_delivered = box_delivered
                detail.karton_delivered = karton_delivered

                # Update subtotaldelivered (realisasi × harga order)
                detail.subtotaldelivered = int(delivered_for_detail * detail.hargaorder)

                # Update proses_picking
                picking = prosesPicking.query.filter(prosesPicking.id_order_detail == id_detail).first()
                if picking:
                    picking.date_delivered = current_date

                self.flush()
                remaining_realisasi = max(remaining_realisasi - delivered_for_detail, 0)

            # Update stok berdasarkan kondisi revisi
            stok_item = stok.query.filter(
                stok.produk_id == id_produk,
                stok.cabang_id == id_cabang
            ).first()
            if stok_item:
                if need_revision:
                    # Hitung total shipped dalam pieces untuk item ini
                    total_shipped_pieces = 0
                    for id_detail in id_detail_sales:
                        detail = sales_order_detail.query.filter(sales_order_detail.id == id_detail).first()
                        if detail:
                            shipped_pieces = self._uom_total_pieces(
                                detail.pieces_shipped,
                                detail.box_shipped,
                                detail.karton_shipped,
                                konversi1,
                                konversi2,
                                konversi3
                            )
                            total_shipped_pieces += shipped_pieces

                    # Kurangi jumlah_booked dan jumlah_delivery sesuai shipped_pieces
                    stok_item.jumlah_booked = self._safe_number(stok_item.jumlah_booked, 0) - total_shipped_pieces
                    stok_item.jumlah_delivery = self._safe_number(stok_item.jumlah_delivery, 0) - total_shipped_pieces

                    # Hitung selisih (barang yang dikembalikan ke gudang)
                    selisih = total_shipped_pieces - realisasi_value

                    # Tambah jumlah_good dan jumlah_ready dari selisih
                    stok_item.jumlah_good = (stok_item.jumlah_good or 0) + selisih
                    stok_item.jumlah_ready = (stok_item.jumlah_ready or 0) + selisih

                else:
                    # Tidak ada revisi, proses normal
                    stok_item.jumlah_booked = self._safe_number(stok_item.jumlah_booked, 0) - realisasi_value
                    stok_item.jumlah_delivery = self._safe_number(stok_item.jumlah_delivery, 0) - realisasi_value

                # Update tanggal dan waktu
                stok_item.tanggal_update = current_date
                stok_item.waktu_update = current_time
                self.flush()

        # Tambah setoran jika ada pembayaran_via_dropper (TIDAK peduli ada revisi atau tidak)
        if pembayaran_via_dropper:
            id_fitur_mal = 16
            new_setoran = None
            if id_order_batch:
                new_setoran = SetoranModel(
                    id_order_batch=id_order_batch,
                    draft_tanggal_input=current_date,
                    draft_jumlah_setor=pembayaran_via_dropper,
                    nama_pj=nama_user,
                    tipe_setoran=1,
                    status_setoran=0,
                    pj_setoran=2
                )
            else:
                new_setoran = SetoranModel(
                    id_sales_order=id_sales_order,
                    draft_tanggal_input=current_date,
                    draft_jumlah_setor=pembayaran_via_dropper,
                    nama_pj=nama_user,
                    tipe_setoran=1,
                    status_setoran=0,
                    pj_setoran=2
                )
            self.add(new_setoran).flush()

            id_setoran = new_setoran.id

        # Update status faktur dan sales order untuk semua faktur yang terlibat
        for id_faktur in faktur_ids:
            faktur_obj = Faktur.query.filter(Faktur.id == id_faktur).first()
            if faktur_obj:
                # Update plafon jika tidak ada revisi
                if not need_revision:
                    # Beberapa faktur hasil shipping lama bisa menyimpan draft total sedikit lebih kecil
                    # dari total penjualan karena pembulatan diskon/ppn. Untuk realisasi normal, sinkronkan
                    # dulu agar proses delivered tidak terblokir hanya karena mismatch kecil ini.
                    if faktur_obj.draft_total_penjualan in (None, '', 'None'):
                        faktur_obj.draft_total_penjualan = faktur_obj.total_penjualan
                    elif faktur_obj.draft_total_penjualan < faktur_obj.total_penjualan:
                        faktur_obj.draft_total_penjualan = faktur_obj.total_penjualan

                    # Hitung selisih
                    selisih = faktur_obj.draft_total_penjualan - faktur_obj.total_penjualan

                    # Dapatkan sales_order untuk mendapatkan id_plafon
                    sales_orders = []
                    if faktur_obj.id_order_batch:
                        sales_orders = sales_order.query.filter(sales_order.id_order_batch == faktur_obj.id_order_batch).all()
                    else:
                        sales_orders = sales_order.query.filter(sales_order.id == faktur_obj.id_sales_order).all()
                    for so in sales_orders:
                        if faktur_obj.id_order_batch:
                            data_detail_faktur = FakturDetailModel.query.filter(
                                FakturDetailModel.id_sales_order == so.id
                            ).first()
                            selisih_by_faktur_detail = data_detail_faktur.draft_total - data_detail_faktur.total
                            if so and so.id_plafon:
                                # Validasi plafon exists
                                plafon_obj = plafon.query.filter(plafon.id == so.id_plafon).first()
                                if plafon_obj:
                                    # Update sisa_bon plafon
                                    plafon_obj.sisa_bon = (plafon_obj.sisa_bon or 0) + selisih_by_faktur_detail
                                    self.flush()
                        else:
                            if so and so.id_plafon:
                                # Validasi plafon exists
                                plafon_obj = plafon.query.filter(plafon.id == so.id_plafon).first()
                                if plafon_obj:
                                    # Update sisa_bon plafon
                                    plafon_obj.sisa_bon = (plafon_obj.sisa_bon or 0) + selisih
                                    self.flush()

                    # Status faktur tidak berubah jika ada revisi
                    faktur_obj.status_faktur = 2  # Status faktur unpaid
                if faktur_obj.id_order_batch:
                    sales_orders = sales_order.query.filter(sales_order.id_order_batch == faktur_obj.id_order_batch).all()
                else:
                    sales_orders = sales_order.query.filter(sales_order.id == faktur_obj.id_sales_order).all()
                for so in sales_orders:
                    if so:
                        if need_revision:
                            so.status_order = 5  # Status need revision
                        else:
                            so.status_order = 6  # Status delivered
                        so.tanggal_terkirim = current_date

                        self.flush()
                        if not need_revision:
                            InventoryLedgerService(DB.session).record_sales_order_out(
                                so.id,
                                faktur_id=faktur_obj.id,
                                movement_date=current_date,
                                created_by=user.get('id')
                            )

        data_profile = {}

        if id_order_batch:
            data_profile = self.__get_data_profile_by_order_batch(id_order_batch)
        else:
            data_profile = self.__get_data_profile_by_sales_order(id_sales_order)

        if not need_revision:
            pubsub = getattr(current_app, 'pubsub', None)
            if pubsub:
                payload_pubsub = {
                    "created_by": user.get('id'),
                    "id_fitur_mal": id_fitur_mal,
                    "id_perusahaan": data_profile.get("id_perusahaan"),
                    "id_cabang": id_cabang,
                    "id_setoran": id_setoran,
                    "id_principal": data_profile.get("id_principal"),
                    "id_order_batch": id_order_batch,
                    "id_sales_order": id_sales_order,
                }

                success = pubsub.publish(data=payload_pubsub, topic='create_jurnal')
                if success:
                    current_app.logger.info("Published to PubSub successfully")
                else:
                    current_app.logger.error("Failed to publish to PubSub")
                    raise nonServerErrorException(status_code=500, message='Gagal mengirim pesan ke sistem jurnal')
            else:
                current_app.logger.error("PubSub client not found")
                raise nonServerErrorException(status_code=500, message='Gagal mengirim pesan ke sistem jurnal')

        # Commit semua perubahan
        self.commit()

        # Update pesan response untuk mencakup kasus setoran dengan revisi
        if pembayaran_via_dropper and need_revision:
            return {"status": "success",
                    "message": f"Proses realisasi belum selesai, Faktur dengan No Faktur: {no_faktur} ini lanjut ke proses revisi faktur. Setoran via dropper berhasil ditambahkan."}, 200
        elif pembayaran_via_dropper:
            return {"status": "success",
                    "message": f"Realisasi pengiriman dengan No Faktur: {no_faktur} berhasil dikonfirmasi. Setoran via dropper berhasil ditambahkan."}, 200
        else:
            if need_revision:
                return {"status": "success",
                        "message": f"Proses realisasi belum selesai, Faktur dengan No Faktur: {no_faktur} ini lanjut ke proses revisi faktur"}, 200
            return {"status": "success",
                    "message": f"Realisasi pengiriman dengan No Faktur: {no_faktur} berhasil dikonfirmasi"}, 200


    @handle_error
    def get_distribusi_info(self):
        email = self.req("email")
        password = self.req("password")

        print("LOGIN ROUTE Distribusi")

        row_obj = (
            self.query()
            .setRawQuery("""
                select 
                users.tokens AS token, 
                users.id AS id_user, 
                users.nama AS nama_user, 
                users.email AS user_email, 
                users.id_cabang AS id_cabang,
                users.password,
                cabang.nama as nama_cabang,
                cabang.alamat as alamat_cabang,
                cabang.telepon as telepon_cabang,
                cabang.npwp as npwp_cabang,
                jabatan.nama as nama_jabatan,
                wilayah1.nama as nama_wilayah1,
                wilayah2.nama as nama_wilayah2,
                wilayah3.nama as nama_wilayah3,
                wilayah4.nama as nama_wilayah4
                from users 
                join jabatan on jabatan.id = users.id_jabatan
                join cabang on cabang.id = users.id_cabang
                left join wilayah1 on wilayah1.id = cabang.id_wilayah1
                left join wilayah2 on wilayah2.id = cabang.id_wilayah2
                left join wilayah3 on wilayah3.id = cabang.id_wilayah3
                left join wilayah4 on wilayah4.id = cabang.id_wilayah4
                where email = :email 
                
            """)
            .bindparams({"email": email})
            .execute()
            .fetchone()
        )

        if not row_obj:
            raise nonServerErrorException("Email salah atau tidak ada")

        # Convert ke dict
        user_info = dict(row_obj.result)

        if not bcrypt.checkpw(
            password.encode("utf-8"),
            user_info["password"].encode("utf-8")
        ):
            raise nonServerErrorException("Password salah", 403)

        # Hapus password dari response
        user_info.pop("password", None)

        # ⚠ Kalau frontend lama tidak pakai wrapper:
        return jsonify(user_info)

    @handle_error
    def getUserInfo(self, id_user):
        user_info = (
            self.query().setRawQuery(
                """
                    select 
                    users.*,
                    cabang.nama as nama_cabang,
                    cabang.alamat as alamat_cabang,
                    cabang.telepon as telepon_cabang,
                    cabang.npwp as npwp_cabang,
                    jabatan.nama as nama_jabatan,
                    wilayah1.nama as nama_wilayah1,
                    wilayah2.nama as nama_wilayah2,
                    wilayah3.nama as nama_wilayah3,
                    wilayah4.nama as nama_wilayah4
                    from users 
                    join jabatan
                    on jabatan.id = users.id_jabatan
                    join cabang
                    on cabang.id = users.id_cabang
                    left join wilayah1
                    on wilayah1.id = cabang.id_wilayah1
                    left join wilayah2
                    on wilayah1.id = cabang.id_wilayah2
                    left join wilayah3
                    on wilayah3.id = cabang.id_wilayah3
                    left join wilayah4
                    on wilayah4.id = cabang.id_wilayah4
                    where
                    users.id = :id_user
                    and
                    users.id_jabatan in (1, 6, 8, 12, 13, 14)
                """
            )
            .bindparams({"id_user": id_user})
            .execute()
            .fetchone()
            .result
        )
        
        user_info['last_update'] = datetime_now()
        
        return user_info

    @handle_error_rollback
    def batalRealisasi(self):
        id_faktur = self.req("id_faktur")
        keterangan_batal = self.req("keterangan_batal")
        status_faktur = self.req("status_faktur")

        # array of object : [{id_produk: int, jumlah_kembali_ke_gudang: int}]
        produk = self.req("produk")

        update_faktur = Faktur.query.filter(Faktur.id == id_faktur).first()

        if update_faktur.id_order_batch:
            id_sales_order_detail_array = (
                self.query()
                .setRawQuery(
                    """
                    select sales_order_detail.id as id_detail_oder
                    from sales_order                             
                             join sales_order_detail
                                  on sales_order.id = sales_order_detail.id_sales_order
                    where sales_order.id_order_batch = :id_order_batch
                    """
                )
                .bindparams({
                    "id_order_batch": update_faktur.id_order_batch
                })
                .execute()
                .fetchall()
                .get()
            )

            for idd in id_sales_order_detail_array:
                id_detail = idd['id_detail_oder']
                update_sales_order = prosesPicking.query.filter(prosesPicking.id_order_detail == id_detail).first()
                update_sales_order.jumlah_picked = 0

                self.flush()
        else:
            id_sales_order_detail_array = (
                self.query()
                .setRawQuery(
                    """
                        select sales_order_detail.id as id_detail_oder from sales_order 
                        join faktur 
                        on faktur.id_sales_order = sales_order.id
                        join sales_order_detail 
                        on sales_order.id = sales_order_detail.id_sales_order
                        where faktur.id = :id_faktur
                    """
                )
                .bindparams({
                    "id_faktur": id_faktur
                })
                .execute()
                .fetchall()
                .get()
            )

            for idd in id_sales_order_detail_array:
                id_detail = idd['id_detail_oder']
                update_sales_order = prosesPicking.query.filter(prosesPicking.id_order_detail == id_detail).first()
                update_sales_order.jumlah_picked = 0

                self.flush()

        for retur in produk:
            id_produk = retur['id_produk']
            jumlah = retur['jumlah_kembali_ke_gudang']

            update_stok = stok.query.filter(stok.produk_id == id_produk).first()
            stok_jumlah_ready = update_stok.jumlah_ready if isinstance(update_stok.jumlah_ready, int) else 0

            update_stok.jumlah_ready = stok_jumlah_ready + jumlah

            self.flush()

        update_faktur.status_faktur = status_faktur
        update_faktur.keterangan_batal = keterangan_batal
        
        self.commit()
        
        return {"status": "success"}, 200


    @handle_error
    def getListFakturJadwal(self):
        id_cabang = self.req('id_cabang')
        id_rute = self.req('id_rute')
        query_one_principal = f"""
                select 
                    so.id as id_sales_order,
                    f.no_faktur,
                    f.id as id_faktur,
                    so.no_order,
                    c.kode as kode_customer,
                    c.nama as nama_customer,
                    c.id as id_customer,
                    pr.nama as nama_principal,
                    pr.id as id_principal,
                    f.total_penjualan as total_bayar,
                    so.status_order,
                    so.tanggal_order,
                    coalesce(sum(sod.estimasi_kubikasi),0) as estimasi_kubikasi,
                    r.id as id_rute
                from 
                    sales_order as so
                join faktur f on so.id = f.id_sales_order
                join plafon p on so.id_plafon = p.id
                join customer c on p.id_customer = c.id
                join principal pr on p.id_principal = pr.id
                join sales_order_detail sod on sod.id_sales_order = so.id
                join rute r on r.id = c.id_rute
                where c.id_cabang = :id_cabang
                and so.status_order in (1,9) and r.id = :id_rute
                GROUP BY 
                    so.id,
                    f.no_faktur,
                    f.id,
                    so.no_order,
                    c.kode,
                    c.nama,
                    c.id,
                    pr.nama,
                    pr.id,
                    f.total_penjualan,
                    so.status_order,
                    so.tanggal_order,
                    r.id
                order by so.tanggal_order ASC

               """

        query_multi_principal = f"""
                select 
                    array_agg(so.id) as id_sales_order,
                    f.no_faktur,
                    f.id as id_faktur,
                    so.no_order,
                    c.kode as kode_customer,
                    c.nama as nama_customer,    
                    c.id as id_customer,
                    'MIX' as nama_principal,                    
                    f.total_penjualan as total_bayar,
                    so.status_order,
                    so.tanggal_order,   
                    coalesce(sum(sod.estimasi_kubikasi),0) as estimasi_kubikasi,
                    r.id as id_rute
                from 
                    sales_order as so
					join faktur_detail  fd on fd.id_sales_order = so.id
                join faktur f on f.id = fd.id_faktur
                join plafon p on so.id_plafon = p.id
                join customer c on p.id_customer = c.id
                join sales_order_detail sod on sod.id_sales_order = so.id
                join rute r on r.id = c.id_rute
                where c.id_cabang = :id_cabang
                and so.id_order_batch is not null
                and so.status_order in (1,9) and r.id = :id_rute
                GROUP BY 
                    f.no_faktur,
                    f.id,
                    so.no_order,
                    c.kode,
                    c.nama,                    
                    c.id,
                    f.total_penjualan,
                    so.status_order,
                    so.tanggal_order,
                    r.id
                order by  so.tanggal_order ASC
               """


        data_order_one_principal = self.query().setRawQuery(query_one_principal).bindparams({'id_cabang': id_cabang,'id_rute':id_rute }).execute().fetchall().get()
        data_order_multi_principal = self.query().setRawQuery(query_multi_principal).bindparams({'id_cabang': id_cabang,'id_rute':id_rute }).execute().fetchall().get()
        data_order = [
            *data_order_one_principal,
            *data_order_multi_principal
        ]

        sorted_data_order = sorted(data_order, key=lambda x: (x['tanggal_order']))

        return sorted_data_order

    @handle_error
    def getJadwalArmada(self):
        
        id_cabang = self._resolve_id_cabang()
        if id_cabang is None:
            raise nonServerErrorException("ID cabang tidak ditemukan untuk memuat jadwal armada", 400)

        query = text("""
            SELECT
                string_agg(DISTINCT pp.id::text, ',') AS id_proses_picking,
                string_agg(DISTINCT pp.id_order_detail::text, ',') AS id_order_detail,
                string_agg(DISTINCT pp.id_produk::text, ',') AS id_produk,
                pp.id_armada,
                pp.id_driver,
                pp.id_helper,
                pp.delivering_date,
                a.nama AS nama_armada,
                u.nama AS nama_driver,
                uh.nama AS nama_helper,
                string_agg(DISTINCT so.status_order::text, ',') AS status_order,
                string_agg(DISTINCT f.id::text, ',') AS id_faktur,
                string_agg(DISTINCT so.id::text, ',') AS id_sales_order,
                string_agg(DISTINCT so.no_order::text, ',') AS no_order,
                MIN(so.id) AS primary_sales_order_id,
                COUNT(DISTINCT so.id) AS sales_order_count,
                r.id AS id_rute,
                r.nama_rute,
                r.kode AS kode_rute,
                COALESCE(SUM(sod.estimasi_kubikasi), 0) AS estimasi_kubikasi
            FROM proses_picking pp
            JOIN sales_order_detail sod
                ON sod.id = pp.id_order_detail
            JOIN sales_order so
                ON so.id = sod.id_sales_order
            JOIN plafon pl
                ON pl.id = so.id_plafon
            JOIN customer c
                ON c.id = pl.id_customer
            AND c.id_cabang = :id_cabang
            JOIN rute r
                ON r.id = c.id_rute
            LEFT JOIN armada a
                ON a.id = pp.id_armada
            LEFT JOIN driver d
                ON d.id = pp.id_driver
            LEFT JOIN users u
                ON u.id = d.id_user
            LEFT JOIN helper h
                ON h.id = pp.id_helper
            LEFT JOIN users uh
                ON uh.id = h.id_user
            LEFT JOIN faktur f
                ON f.id_sales_order = so.id
            GROUP BY
                r.id,
                pp.delivering_date,
                pp.id_armada,
                pp.id_driver,
                pp.id_helper,
                a.nama,
                u.nama,
                uh.nama,
                r.nama_rute,
                r.kode
            ORDER BY
                pp.delivering_date ASC,
                r.nama_rute ASC
        """)

        rows = DB.session.execute(query, {"id_cabang": int(id_cabang)}).mappings().all()
        data_order = [dict(row) for row in rows]

        merge_data_order = []

        def merge_csv_values(old_value, new_value):
            old_set = set(filter(None, str(old_value or '').split(',')))
            new_set = set(filter(None, str(new_value or '').split(',')))
            merged = old_set | new_set

            if not merged:
                return None

            def sort_key(x):
                return int(x) if str(x).isdigit() else str(x)

            return ','.join(sorted(merged, key=sort_key))

        for item in data_order:
            existing_item = next(
                (
                    x for x in merge_data_order
                    if x.get('id_rute') == item.get('id_rute')
                    and x.get('id_armada') == item.get('id_armada')
                    and x.get('id_driver') == item.get('id_driver')
                    and x.get('id_helper') == item.get('id_helper')
                    and str(x.get('delivering_date')) == str(item.get('delivering_date'))
                ),
                None
            )

            if existing_item:
                existing_item['id_proses_picking'] = merge_csv_values(
                    existing_item.get('id_proses_picking'),
                    item.get('id_proses_picking')
                )
                existing_item['id_order_detail'] = merge_csv_values(
                    existing_item.get('id_order_detail'),
                    item.get('id_order_detail')
                )
                existing_item['id_produk'] = merge_csv_values(
                    existing_item.get('id_produk'),
                    item.get('id_produk')
                )
                existing_item['status_order'] = merge_csv_values(
                    existing_item.get('status_order'),
                    item.get('status_order')
                )
                existing_item['id_faktur'] = merge_csv_values(
                    existing_item.get('id_faktur'),
                    item.get('id_faktur')
                )
                existing_item['id_sales_order'] = merge_csv_values(
                    existing_item.get('id_sales_order'),
                    item.get('id_sales_order')
                )
                existing_item['no_order'] = merge_csv_values(
                    existing_item.get('no_order'),
                    item.get('no_order')
                )
                existing_primary = existing_item.get('primary_sales_order_id')
                current_primary = item.get('primary_sales_order_id')
                if existing_primary in (None, ''):
                    existing_item['primary_sales_order_id'] = current_primary
                elif current_primary not in (None, ''):
                    existing_item['primary_sales_order_id'] = min(int(existing_primary), int(current_primary))
                existing_item['sales_order_count'] = int(existing_item.get('sales_order_count') or 0) + int(item.get('sales_order_count') or 0)
                existing_item['estimasi_kubikasi'] = float(existing_item.get('estimasi_kubikasi') or 0) + float(item.get('estimasi_kubikasi') or 0)
            else:
                merge_data_order.append({
                    'id_proses_picking': item.get('id_proses_picking'),
                    'id_order_detail': item.get('id_order_detail'),
                    'id_produk': item.get('id_produk'),
                    'id_armada': item.get('id_armada'),
                    'id_driver': item.get('id_driver'),
                    'id_helper': item.get('id_helper'),
                    'delivering_date': item.get('delivering_date'),
                    'nama_armada': item.get('nama_armada'),
                    'nama_driver': item.get('nama_driver'),
                    'nama_helper': item.get('nama_helper'),
                    'status_order': item.get('status_order'),
                    'id_faktur': item.get('id_faktur'),
                    'id_sales_order': item.get('id_sales_order'),
                    'no_order': item.get('no_order'),
                    'primary_sales_order_id': item.get('primary_sales_order_id'),
                    'sales_order_count': int(item.get('sales_order_count') or 0),
                    'id_rute': item.get('id_rute'),
                    'nama_rute': item.get('nama_rute'),
                    'kode_rute': item.get('kode_rute'),
                    'estimasi_kubikasi': float(item.get('estimasi_kubikasi') or 0)
                })

        return merge_data_order



    @handle_error_rollback
    def deleteJadwal(self):
        
        id_fakturs = self.req("id_faktur")
        id_proses_pickings = self.req("id_proses_picking")
        id_sales_orders = self.req("id_sales_order")

        # Convert comma-separated strings to lists if needed
        if isinstance(id_fakturs, str):
            id_fakturs = [int(id_faktur.strip()) for id_faktur in id_fakturs.split(',')]
        elif isinstance(id_fakturs, int):
            id_fakturs = [id_fakturs]

        if isinstance(id_proses_pickings, str):
            id_proses_pickings = [int(id_picking.strip()) for id_picking in id_proses_pickings.split(',')]
        elif isinstance(id_proses_pickings, int):
            id_proses_pickings = [id_proses_pickings]

        if isinstance(id_sales_orders, str):
            id_sales_orders = [int(id_so.strip()) for id_so in id_sales_orders.split(',')]
        elif isinstance(id_sales_orders, int):
            id_sales_orders = [id_sales_orders]

        # Cek status_order untuk setiap sales_order dan update sesuai kondisi
        for id_sales_order in id_sales_orders:
            sales_order_record = sales_order.query.filter(sales_order.id == id_sales_order).first()
            if not sales_order_record:
                raise nonServerErrorException(f"Sales Order dengan ID {id_sales_order} tidak ditemukan", 404)

            current_status = sales_order_record.status_order

            # Update status berdasarkan kondisi
            if current_status == 10:
                sales_order_record.status_order = 9
            elif current_status == 2:
                sales_order_record.status_order = 1

            self.flush()

        # Update proses_picking records berdasarkan status_order
        for id_picking in id_proses_pickings:
            picking_record = prosesPicking.query.filter(prosesPicking.id == id_picking).first()
            if picking_record:
                # Cari sales_order yang terkait dengan proses_picking ini
                detail_record = sales_order_detail.query.filter(
                    sales_order_detail.id == picking_record.id_order_detail
                ).first()

                if detail_record:
                    so_record = sales_order.query.filter(
                        sales_order.id == detail_record.id_sales_order
                    ).first()

                    if so_record:
                        # Reset delivery info untuk semua kasus
                        picking_record.delivering_date = None
                        picking_record.id_armada = None
                        picking_record.id_driver = None
                        picking_record.id_helper = None

                        # Update jumlah_picked berdasarkan status sebelumnya
                        # Jika status berubah dari 2 ke 1, reset jumlah_picked
                        # Jika status berubah dari 10 ke 9, tetap pertahankan jumlah_picked
                        if so_record.status_order == 1:  # Berarti sebelumnya status 2
                            picking_record.jumlah_picked = None
                        # Jika status_order == 9 (sebelumnya 10), jumlah_picked tetap tidak diubah

                        self.flush()

        self.commit()
        return {"message": "Jadwal berhasil dihapus."}, 200

    @handle_error_rollback
    def editJadwal(self):
        
        # Mengambil data dari request
        id_proses_picking = self.req("id_proses_picking")
        id_driver = self.req("id_driver")
        id_helper = self.req("id_helper")
        id_armada = self.req("id_armada")
        tanggal_pengiriman = self._normalize_delivery_date(self.req("tanggal_pengiriman"))

        def to_int(value, field):
            try:
                return int(value)
            except (TypeError, ValueError):
                raise nonServerErrorException(f"{field} harus berupa ID angka", 400)

        # Validasi data yang diterima
        if not id_proses_picking or not id_driver or not id_armada or not tanggal_pengiriman:
            raise nonServerErrorException("Data tidak lengkap", 400)

        # Mengonversi string id_proses_picking menjadi list jika dikirim dalam format "98,99"
        id_proses_picking_list = [
            value.strip()
            for value in (id_proses_picking.split(',') if isinstance(id_proses_picking, str) else [id_proses_picking])
            if str(value).strip()
        ]

        touched_order_ids = set()

        # Update setiap proses_picking berdasarkan ID
        for id_picking in id_proses_picking_list:
            # Cari record proses_picking berdasarkan ID
            picking_record = prosesPicking.query.filter(prosesPicking.id == to_int(id_picking, "ID picking")).first()

            if not picking_record:
                continue

            # Update data dengan nilai baru
            picking_record.id_driver = to_int(id_driver, "Driver")
            picking_record.id_helper = to_int(id_helper, "Helper") if id_helper not in (None, '', 'None') else None
            picking_record.id_armada = to_int(id_armada, "Armada")
            picking_record.delivering_date = tanggal_pengiriman

            order_detail = sales_order_detail.query.filter(sales_order_detail.id == picking_record.id_order_detail).first()
            if order_detail:
                touched_order_ids.add(order_detail.id_sales_order)
                order = sales_order.query.filter(sales_order.id == order_detail.id_sales_order).first()
                if order and order.status_order == 1:
                    order.status_order = 2
                elif order and order.status_order == 9:
                    order.status_order = 10

            self.flush()

        normalized_driver_id = to_int(id_driver, "Driver")
        normalized_armada_id = to_int(id_armada, "Armada")
        normalized_helper_id = to_int(id_helper, "Helper") if id_helper not in (None, '', 'None') else None

        for order_id in touched_order_ids:
            order = sales_order.query.filter(sales_order.id == order_id).first()
            order_details = sales_order_detail.query.filter(
                sales_order_detail.id_sales_order == order_id
            ).all()

            for detail in order_details:
                self._upsert_schedule_pickings_for_detail(
                    detail,
                    normalized_driver_id,
                    normalized_armada_id,
                    normalized_helper_id,
                    tanggal_pengiriman,
                    default_picked=self._default_picked_total_for_detail(detail),
                    overwrite_picked=False
                )

            if order and order.status_order == 1:
                order.status_order = 2
            elif order and order.status_order == 9:
                order.status_order = 10

            self.flush()

        self.commit()
        return {"status": "success", "message": "Jadwal pengiriman berhasil diubah"}, 200

    @handle_error_rollback
    def submitPicking(self):

        token = request.headers.get('Authorization')
        if not token:
            raise nonServerErrorException("Token tidak ditemukan", 403)
        token = token.replace("Bearer ", "")
        if not token:
            raise nonServerErrorException("Token tidak ditemukan", 403)
        user = (
            self.query().setRawQuery(
                "SELECT id,id_cabang FROM users WHERE tokens = :token",
            ).bindparams({
                'token': token
            }).execute().fetchone().result
        )

        nama_picked = self.req('nama_picked')
        list_picking = self.req('list_picking')
        raw_id_cabang = self.req('id_cabang')


        # Validasi data input
        if not nama_picked:
            raise nonServerErrorException("Nama picker tidak boleh kosong", 400)

        if not list_picking or not isinstance(list_picking, list) or len(list_picking) == 0:
            raise nonServerErrorException("Data picking tidak valid atau kosong", 400)

        if raw_id_cabang in (None, '', 'None'):
            raise nonServerErrorException("ID cabang tidak boleh kosong", 400)

        try:
            id_cabang = int(raw_id_cabang)
        except (TypeError, ValueError):
            raise nonServerErrorException("ID cabang tidak valid", 400)

        # Set tanggal picking saat ini
        tanggal_picking = date_now()
        waktu_picking = time_now()

        is_periode_closed, next_date = self.check_is_periode_closed()
        if is_periode_closed:
            tanggal_picking = next_date.strftime('%Y-%m-%d')

        data_mapping_by_faktur = {}

        # Set untuk menyimpan id_faktur yang unik
        unique_fakturs = set()
        # Iterasi untuk setiap item picking
        for item in list_picking:
            # Validasi item wajib
            if 'id_order_detail' not in item:
                raise nonServerErrorException("ID order detail tidak ditemukan", 400)
            if 'id_faktur' not in item:
                raise nonServerErrorException("ID faktur tidak ditemukan", 400)
            if 'produk_id' not in item:
                raise nonServerErrorException("ID produk tidak ditemukan", 400)

            # Parsing id_order_detail dan id_faktur yang mungkin berupa string dengan format '1,2,3'
            id_order_detail_list = str(item['id_order_detail']).split(',')
            id_faktur_list = str(item['id_faktur']).split(',')
            try:
                produk_id = int(item['produk_id'])
            except (ValueError, TypeError):
                raise nonServerErrorException(f"ID produk tidak valid: {item['produk_id']}", 400)

            # Validasi produk ada di database
            produk_exists = self.query().setRawQuery(
                "SELECT COUNT(*) as count FROM produk WHERE id = :id_produk"
            ).bindparams({"id_produk": produk_id}).execute().fetchone().result

            if not produk_exists or produk_exists["count"] == 0:
                raise nonServerErrorException(f"Produk dengan ID {produk_id} tidak ditemukan", 404)

            # Ambil nilai konversi dari frontend
            konversi1 = self._normalize_uom_conversion(item.get('konversi1'), 1)
            konversi2 = self._normalize_uom_conversion(item.get('konversi2'), 2)
            konversi3 = self._normalize_uom_conversion(item.get('konversi3'), 3)

            # Iterasi untuk setiap id_order_detail
            for i in range(len(id_order_detail_list)):
                try:
                    id_order_detail = int(id_order_detail_list[i].strip())
                except (ValueError, TypeError):
                    raise nonServerErrorException(f"ID order detail tidak valid: {id_order_detail_list[i]}", 400)

                # Mendapatkan sales_order_detail
                detail = sales_order_detail.query.filter(sales_order_detail.id == id_order_detail).first()
                if not detail:
                    raise nonServerErrorException(f"Detail sales order dengan ID {id_order_detail} tidak ditemukan",
                                                  404)

                # Mendapatkan proses_picking berdasarkan id_order_detail
                picking = prosesPicking.query.filter(prosesPicking.id_order_detail == id_order_detail).first()
                if not picking:
                    raise nonServerErrorException(
                        f"Proses picking untuk ID order detail {id_order_detail} tidak ditemukan", 404)

                # Dapatkan jumlah_picked dari database
                jumlah_picked = picking.jumlah_picked
                if not jumlah_picked or jumlah_picked <= 0:
                    raise nonServerErrorException(f"Jumlah picking untuk ID order detail {id_order_detail} tidak valid",
                                                  400)

                # Cek stok produk untuk validasi
                stok_item = stok.query.filter(
                    stok.produk_id == produk_id,
                    stok.cabang_id == id_cabang
                ).first()

                if not stok_item:
                    raise nonServerErrorException(f"Stok untuk produk ID {produk_id} tidak ditemukan di cabang ini",
                                                  404)

                # VALIDASI: Cek apakah stok mencukupi
                if stok_item.jumlah_good < jumlah_picked:
                    nama_produk = item.get('nama_produk')

                    raise nonServerErrorException(
                        f"Stok tidak mencukupi untuk produk '{nama_produk}'. "
                        f"Tersedia: {stok_item.jumlah_good}, Dibutuhkan: {jumlah_picked}",
                        400
                    )

                # Kalkulasi dari jumlah_picked dan nilai konversi UOM yang valid.
                calculated_qty = self._split_total_to_uom(jumlah_picked, konversi1, konversi2, konversi3)
                calculated_pieces = calculated_qty["pieces"]
                calculated_box = calculated_qty["box"]
                calculated_karton = calculated_qty["karton"]

                # Update sales_order_detail
                detail.pieces_picked = calculated_pieces
                detail.box_picked = calculated_box
                detail.karton_picked = calculated_karton
                self.flush()

                # Update proses_picking
                picking.date_picked = tanggal_picking
                picking.pickers = nama_picked
                self.flush()

                # Update stok
                stok_item = stok.query.filter(
                    stok.produk_id == produk_id,
                    stok.cabang_id == id_cabang
                ).first()

                if stok_item:
                    stok_item.jumlah_picked = self._safe_number(stok_item.jumlah_picked) + jumlah_picked
                    stok_item.jumlah_good = self._safe_number(stok_item.jumlah_good) - jumlah_picked
                    stok_item.tanggal_update = tanggal_picking
                    stok_item.waktu_update = waktu_picking
                    self.flush()

                # Tambahkan id_faktur ke set unik jika ada
                if i < len(id_faktur_list):
                    id_faktur = int(id_faktur_list[i].strip())
                    unique_fakturs.add(id_faktur)

        # GENERATE NO_FAKTUR untuk semua faktur yang terlibat
        for id_faktur in unique_fakturs:
            fak = Faktur.query.filter(Faktur.id == id_faktur).first()
            if fak and not fak.no_faktur:  # Hanya generate jika no_faktur masih NULL
                # Get customer data untuk PPN
                so = None
                if fak.id_order_batch:
                    so = sales_order.query.filter(sales_order.id_order_batch == fak.id_order_batch).first()
                else:
                    so = sales_order.query.filter(sales_order.id == fak.id_sales_order).first()
                if so:
                    # Get plafon dan customer
                    plafon_data = plafon.query.filter(plafon.id == so.id_plafon).first()
                    customer_data = customer.query.filter(customer.id == plafon_data.id_customer).first()

                    # Get cabang data
                    cabang_data = Cabang.query.filter(Cabang.id == so.id_cabang).first()

                    # Get perusahaan data through principal
                    principal_data = Principal.query.filter(Principal.id == plafon_data.id_principal).first()
                    perusahaan_data = Perusahaan.query.filter(Perusahaan.id == principal_data.id_perusahaan).first()

                    # Generate PPN prefix
                    ppn_prefix = "PJ" if customer_data.is_ppn == 1 else "NP"

                    # Get current date components
                    current_date_str = date_now()  # YYYY-MM-DD format
                    if is_periode_closed:
                        current_date_str = next_date.strftime("%Y-%m-%d")  # Gunakan next_date jika periode closed
                    year = current_date_str[2:4]  # Get last 2 digits of year (25 for 2025)
                    month = current_date_str[5:7]  # Get month (05 for May)

                    # Generate no_faktur dengan retry mechanism
                    max_retries = 5
                    no_faktur = None

                    for attempt in range(max_retries):
                        try:
                            # Generate prefix for counter search
                            faktur_prefix = f"{ppn_prefix}{perusahaan_data.kode}{cabang_data.kode}-{year}{month}"

                            # Get the last counter for this prefix with database lock
                            last_faktur = faktur.query.filter(
                                faktur.no_faktur.like(f"{faktur_prefix}%")
                            ).with_for_update().order_by(faktur.no_faktur.desc()).first()

                            # Generate new counter
                            if last_faktur:
                                # Extract counter from last faktur (last 6+ digits)
                                last_counter_str = last_faktur.no_faktur.split('-')[1][4:]  # Remove year+month part
                                last_counter = int(last_counter_str)
                                new_counter = last_counter + 1
                            else:
                                new_counter = 1

                            # Format counter with minimum 6 digits
                            counter_str = f"{new_counter:06d}"

                            # Generate new faktur format: PPN+kode_perusahaan+kode_cabang-tahun+bulan+counter
                            no_faktur = f"{ppn_prefix}{perusahaan_data.kode}{cabang_data.kode}-{year}{month}{counter_str}"

                            # Test if this no_faktur already exists
                            existing_faktur = faktur.query.filter(faktur.no_faktur == no_faktur).first()
                            if existing_faktur:
                                raise IntegrityError("Duplicate no_faktur", None, None)

                            # Update faktur dengan no_faktur yang baru di-generate
                            fak.no_faktur = no_faktur
                            self.flush()
                            break  # Success, exit retry loop

                        except IntegrityError:
                            if attempt == max_retries - 1:
                                raise nonServerErrorException("Failed to generate unique no_faktur after 5 attempts")

                            time.sleep(random.uniform(0.01, 0.05))

            # Update status sales order
            if fak:
                if fak.id_order_batch:

                    so = sales_order.query.filter(sales_order.id_order_batch == fak.id_order_batch).all()
                    if so:

                        data_mapping_by_faktur[fak.id] = self.__get_data_profile_by_order_batch(id_order_batch=fak.id_order_batch)

                        for s in so:
                            s.status_order = 3
                            self.flush()
                else:
                    so = sales_order.query.filter(sales_order.id == fak.id_sales_order).first()
                    if so:

                        data_mapping_by_faktur[fak.id] = self.__get_data_profile_by_sales_order(id_sales_order=fak.id_sales_order)

                        so.status_order = 3
                        self.flush()

        payload_pubsub = {
            "created_by": user['id'],
            "id_fitur_mal":3,
            "data": data_mapping_by_faktur
        }

        pubsub = getattr(current_app, 'pubsub', None)
        if pubsub:
            success = pubsub.publish(data=payload_pubsub, topic='create_jurnal')
            if success:
                current_app.logger.info("Published to PubSub successfully")
            else:
                current_app.logger.error("Failed to publish to PubSub")
                raise nonServerErrorException(500,"Failed to publish to PubSub")
        else:
            current_app.logger.error("PubSub client not found")
            raise nonServerErrorException(status_code=500, message='Gagal mengirim pesan ke sistem jurnal')

        # Commit perubahan
        self.commit()

        return {
            "status": "success",
            "message": "Pesanan ini berhasil disiapkan"
        }, 200

    def __get_data_profile_by_order_batch(self, id_order_batch:int):
        query_get_profile = """
                                    SELECT pc.id_perusahaan, so.id_cabang, p.id_principal 
                                    FROM sales_order so 
                                             JOIN plafon p ON so.id_plafon = p.id 
                                             JOIN public.principal pc on p.id_principal = pc.id
                                    WHERE so.id_order_batch = :id_order_batch 
                                    """

        profile = self.query().setRawQuery(query_get_profile).bindparams({
            "id_order_batch": id_order_batch
        }).execute().fetchone().result

        return {
            'id_order_batch': id_order_batch,
            'id_perusahaan': profile['id_perusahaan'],
            'id_principal': profile['id_principal'],
            'id_cabang': profile['id_cabang']
        }

    def __get_data_profile_by_sales_order(self, id_sales_order:int):
        query_get_profile = """
                                    SELECT pc.id_perusahaan, so.id_cabang, p.id_principal
                                    FROM sales_order so \
                                             JOIN plafon p ON so.id_plafon = p.id \
                                             JOIN public.principal pc on p.id_principal = pc.id
                                    WHERE so.id = :id_sales_order \
                                    """

        profile = self.query().setRawQuery(query_get_profile).bindparams({
            "id_sales_order": id_sales_order
        }).execute().fetchone().result

        return{
            'id_sales_order': id_sales_order,
            'id_perusahaan': profile['id_perusahaan'],
            'id_principal': profile['id_principal'],
            'id_cabang': profile['id_cabang']
        }

    @handle_error_rollback
    def submitRevisiFaktur(self):
        faktur_ids = self.req('faktur_ids')
        faktur_data = self.req('faktur_data')
        nama_fakturist = self.req('nama_fakturist')

        is_periode_closed, next_date = self.check_is_periode_closed()

        # Validasi data
        if not faktur_ids or not faktur_data or not isinstance(faktur_data, list):
            raise nonServerErrorException("Data faktur tidak valid", 400)

        # Set tanggal saat ini
        tanggal_sekarang = date_now()
        if is_periode_closed:
            tanggal_sekarang = next_date.strftime('%Y-%m-%d')

        # Validasi kesesuaian data faktur
        faktur_ids_set = set(map(int, faktur_ids))
        faktur_data_ids = {
            int(x.strip())
            for faktur in faktur_data
            for x in (
                [str(faktur["id_sales_order"])] if isinstance(faktur["id_sales_order"], int)
                else str(faktur["id_sales_order"]).split(',')
            )
            if x.strip().isdigit()
        }


        if faktur_ids_set != faktur_data_ids:
            raise nonServerErrorException("Data faktur tidak sesuai dengan IDs yang diberikan", 400)

        # Proses setiap faktur
        for faktur_item in faktur_data:

            id_sales_orders = []

            if isinstance(faktur_item['id_sales_order'], str):
                ids = faktur_item['id_sales_order'].split(',')
                id_sales_orders = [int(id_.strip()) for id_ in ids if id_.strip().isdigit()]
            elif isinstance(faktur_item['id_sales_order'], int):
                id_sales_orders = [faktur_item['id_sales_order']]

            sales_orders_for_item = []
            for id_sales_order in id_sales_orders:

                # Dapatkan sales_order
                so = sales_order.query.filter(sales_order.id == id_sales_order).first()
                if not so:
                    raise nonServerErrorException(f"Sales Order dengan ID {id_sales_order} tidak ditemukan", 404)
                sales_orders_for_item.append(so)

            detail_produk_list = self.__apply_product_ppn_to_revision_details(
                faktur_item.get('detail_produk', [])
            )
            faktur_item['detail_produk'] = detail_produk_list
            faktur_item['rincian_pembayaran'] = self.__revision_payment_totals_from_details(detail_produk_list)

            # Update status sales_order
            for order_item in sales_orders_for_item:
                order_item.status_order = 6
                order_item.tanggal_terkirim = tanggal_sekarang
                self.flush()

            # Update faktur
            id_order_batch = faktur_item['faktur_info'].get('id_order_batch', None)
            faktur_terkait = None
            if id_order_batch:
                faktur_terkait = Faktur.query.filter(Faktur.id_order_batch == id_order_batch).first()
            else:
                faktur_terkait = Faktur.query.filter(Faktur.id_sales_order == id_sales_order).first()

            if faktur_terkait:
                faktur_terkait.status_faktur = 2
                for order_item in sales_orders_for_item:
                    InventoryLedgerService(DB.session).record_sales_order_out(
                        order_item.id,
                        faktur_id=faktur_terkait.id,
                        movement_date=tanggal_sekarang
                    )

                # Update nilai faktur dari rincian_pembayaran
                if 'rincian_pembayaran' in faktur_item:
                    rincian = faktur_item['rincian_pembayaran']

                    if 'subtotal' in rincian:
                        faktur_terkait.subtotal_penjualan = format_angka(rincian['subtotal'])

                        so.total_order = format_angka(rincian['subtotal'])

                    if 'total_penjualan' in rincian:
                        faktur_terkait.total_penjualan = format_angka(rincian['total_penjualan'])

                    if 'diskon_nota' in rincian:
                        faktur_terkait.subtotal_diskon = format_angka(rincian['diskon_nota'])

                    if 'pajak' in rincian:
                        faktur_terkait.pajak = format_angka(rincian['pajak'])

                    # Hitung DPP (subtotal - diskon_nota)
                    if 'subtotal' in rincian and 'diskon_nota' in rincian:
                        subtotal = format_angka(rincian['subtotal'])
                        diskon_nota = format_angka(rincian['diskon_nota'])
                        faktur_terkait.dpp = format_angka(subtotal - diskon_nota)


                    # Update plafon - logika yang sama seperti submitRealisasiDetail
                    if 'total_penjualan' in rincian:
                        total_penjualan_baru = format_angka(rincian['total_penjualan'])
                        draft_total_penjualan = format_angka(
                            faktur_terkait.draft_total_penjualan
                            if faktur_terkait.draft_total_penjualan not in (None, '', 'None')
                            else faktur_terkait.total_penjualan
                        )

                        selisih = draft_total_penjualan - total_penjualan_baru

                        # Dapatkan sales_order untuk mendapatkan id_plafon
                        if faktur_terkait.id_order_batch:
                            new_detail_produk_list = []
                            for detail_produk in faktur_item.get('detail_produk', []):
                                data_faktur = next( (fd for fd in faktur_item.get('detail_faktur', []) if fd['id_produk'] == detail_produk['id_produk']), None)
                                if data_faktur:
                                    new_detail_produk_list.append(
                                        {
                                            'id_sales_order': data_faktur['id_sales_order'],
                                            **detail_produk
                                        }
                                    )

                            mapping_produk = self.__mapping_produk_by_sales_order(
                                [
                                    item for item in new_detail_produk_list
                                    if str(item.get('action') or item.get('_action') or 'update').lower() != 'delete'
                                ]
                            )
                            for id_so, detail_produk in mapping_produk.items():
                                update_faktur_detail = FakturDetailModel.query.filter(
                                    FakturDetailModel.id_sales_order == id_so,
                                ).first()
                                subtotal_all_product = sum(
                                    format_angka(dp.get('subtotal', 0)) - format_angka(dp.get('total_diskon', 0))
                                    for dp in detail_produk
                                )
                                subtotal_diskon_all_product = sum(
                                    format_angka(dp.get('total_diskon', 0))
                                    for dp in detail_produk
                                )
                                pajak_all_product = sum(
                                    format_angka(dp.get('ppn', 0))
                                    for dp in detail_produk
                                )
                                update_faktur_detail.subtotal = subtotal_all_product
                                update_faktur_detail.pajak = pajak_all_product
                                update_faktur_detail.subtotal_diskon = subtotal_diskon_all_product
                                update_faktur_detail.total = format_angka(subtotal_all_product) + format_angka(
                                    pajak_all_product)


                                self.flush()

                        else:
                            if so and so.id_plafon:
                                # Validasi plafon exists
                                plafon_obj = plafon.query.filter(plafon.id == so.id_plafon).first()
                                if plafon_obj:
                                    # Update sisa_bon plafon
                                    plafon_obj.sisa_bon = (plafon_obj.sisa_bon or 0) + selisih
                                    self.flush()

                self.flush()

            detail_produk_list = faktur_item.get('detail_produk', [])
            detail_faktur_by_id = {
                int(row.get('id_order_detail')): row
                for row in faktur_item.get('detail_faktur', [])
                if str(row.get('id_order_detail', '')).isdigit()
            }

            for produk_detail in detail_produk_list:
                action = str(produk_detail.get('action') or produk_detail.get('_action') or 'update').lower()
                id_order_detail = produk_detail.get('id_order_detail')
                id_produk = produk_detail.get('id_produk')
                target_sales_order_id = produk_detail.get('id_sales_order') or id_sales_orders[0]

                pieces_order = int(format_angka(produk_detail.get('pieces_order', 0)))
                box_order = int(format_angka(produk_detail.get('box_order', 0)))
                karton_order = int(format_angka(produk_detail.get('karton_order', 0)))
                harga_order = format_angka(produk_detail.get('hargaorder', produk_detail.get('harga_order', 0)))
                total_diskon = format_angka(produk_detail.get('total_diskon', 0))
                subtotal = format_angka(produk_detail.get('subtotal', 0))
                subtotal_after_discount = max(subtotal - total_diskon, 0)

                if action == 'delete':
                    if id_order_detail:
                        detail = sales_order_detail.query.filter(sales_order_detail.id == int(id_order_detail)).first()
                        if detail:
                            prosesPicking.query.filter(prosesPicking.id_order_detail == detail.id).delete(synchronize_session=False)
                            self.db.session.delete(detail)
                            self.flush()
                    continue

                if id_order_detail:
                    detail = sales_order_detail.query.filter(sales_order_detail.id == int(id_order_detail)).first()
                    if not detail:
                        raise nonServerErrorException(f"Detail order dengan ID {id_order_detail} tidak ditemukan", 404)
                else:
                    if not id_produk:
                        raise nonServerErrorException("Produk baru pada revisi faktur wajib dipilih", 400)
                    detail = sales_order_detail(
                        id_sales_order=int(target_sales_order_id),
                        id_produk=int(id_produk)
                    )
                    self.add(detail)

                detail.id_produk = int(id_produk or detail.id_produk)
                detail.pieces_order = pieces_order
                detail.box_order = box_order
                detail.karton_order = karton_order
                detail.pieces_booked = pieces_order
                detail.box_booked = box_order
                detail.karton_booked = karton_order
                detail.pieces_picked = pieces_order
                detail.box_picked = box_order
                detail.karton_picked = karton_order
                detail.pieces_shipped = pieces_order
                detail.box_shipped = box_order
                detail.karton_shipped = karton_order
                detail.pieces_delivered = pieces_order
                detail.box_delivered = box_order
                detail.karton_delivered = karton_order
                detail.hargaorder = harga_order
                detail.total_nilai_discount = total_diskon
                detail.subtotalorder = subtotal_after_discount
                detail.subtotaldelivered = subtotal_after_discount

                self.flush()

                detail_faktur = detail_faktur_by_id.get(detail.id)
                if detail_faktur and produk_detail.get('voucher_detail'):
                    voucher_info = produk_detail['voucher_detail']
                    voucher_fields = [
                        ('v1r_id_dv', 'v1r_diskon'),
                        ('v2r_id_dv', 'v2r_diskon'),
                        ('v3r_id_dv', 'v3r_diskon'),
                        ('v2p_id_dv', 'v2p_diskon'),
                        ('v3p_id_dv', 'v3p_diskon')
                    ]

                    for id_field, diskon_field in voucher_fields:
                        id_dv = detail_faktur.get(id_field)
                        if id_dv is not None:
                            diskon_value = voucher_info.get(diskon_field, 0)
                            formatted_diskon = format_angka(diskon_value) if diskon_value is not None else 0
                            dv_entry = draft_voucher.query.filter(draft_voucher.id == id_dv).first()
                            if dv_entry:
                                if formatted_diskon == 0:
                                    dv_entry.status_promo = 3
                                dv_entry.jumlah_diskon = formatted_diskon
                                self.flush()

            # Tambah setoran jika ada pembayaran_via_dropper
            # if pembayaran_via_dropper and 'rincian_pembayaran' in faktur_item:
            #     rincian = faktur_item['rincian_pembayaran']
            #     if 'total_penjualan' in rincian:
            #         new_setoran = setoran(
            #             id_sales_order=id_sales_order,
            #             draft_tanggal_input=current_date,
            #             draft_jumlah_setor=format_angka(rincian['total_penjualan']),
            #             nama_pj=nama_fakturist,
            #             tipe_setoran=1,
            #             status_setoran=0,
            #             pj_setoran=2
            #         )
            #         self.add(new_setoran).flush()

        # Commit perubahan
        self.commit()

        return {
            "status": "success",
            "message": "Revisi faktur berhasil diproses"
        }, 200

    @handle_error_rollback
    def jadwalkanUlangFaktur(self):
        id_sales_orders = self.req("id_sales_order")

        for id_sales_order in id_sales_orders:

            # Validasi sales order exists
            so = sales_order.query.filter(sales_order.id == id_sales_order).first()
            if not so:
                raise nonServerErrorException(f"Sales Order dengan ID {id_sales_order} tidak ditemukan", 404)

            # Update status sales order
            so.status_order = 9
            self.flush()

            # Hapus data delivery dari proses_picking yang terkait dengan sales_order
            proses_picking_records = (
                prosesPicking.query
                .join(sales_order_detail, prosesPicking.id_order_detail == sales_order_detail.id)
                .filter(sales_order_detail.id_sales_order == id_sales_order)
                .all()
            )

            for picking in proses_picking_records:
                picking.delivering_date = None
                picking.date_on_delivery = None
                picking.id_armada = None
                picking.id_driver = None
                self.flush()

        self.commit()

        return {
            "status": "success",
            "message": "Faktur siap dijadwalkan ulang"
        }, 200

    @handle_error_rollback
    def submitReshipping(self):
        reshipping_data = self.req("reshipping_data")  # Sesuai dengan body dari FE

        # Validasi data
        if not reshipping_data or not isinstance(reshipping_data, list):
            raise nonServerErrorException("Data reshipping tidak valid", 400)

        # Set tanggal saat ini
        current_date = date_now()
        is_periode_closed, next_date = self.check_is_periode_closed()
        if is_periode_closed:
            current_date = next_date.strftime('%Y-%m-%d')

        # Proses setiap item reshipping
        for item in reshipping_data:
            id_sales_orders = []
            if isinstance(item.get('id_sales_order'), str):
                ids = item.get('id_sales_order').split(',')
                id_sales_orders = [int(id_.strip()) for id_ in ids if id_.strip().isdigit()]
            elif isinstance(item.get('id_sales_order'), int):
                id_sales_orders = [item.get('id_sales_order')]

            for id_sales_order in id_sales_orders:
                # Validasi sales order exists

                id_sales_order_detail = item.get('id_sales_order_detail')

                # Validasi data
                if not id_sales_order:
                    raise nonServerErrorException("ID sales order tidak ditemukan", 400)
                if not id_sales_order_detail:
                    raise nonServerErrorException("ID sales order detail tidak ditemukan", 400)

                # Update status sales_order menjadi 11
                sales_order_data = (
                    self.db
                    .session
                    .query(sales_order, plafon)
                    .join(plafon, sales_order.id_plafon == plafon.id)
                    .filter(sales_order.id == id_sales_order)
                    .first()
                )
                if not sales_order_data:
                    raise nonServerErrorException(f"Sales Order dengan ID {id_sales_order} tidak ditemukan", 404)
                so, plafon_data  = sales_order_data
                if not so:
                    raise nonServerErrorException(f"Sales Order dengan ID {id_sales_order} tidak ditemukan", 404)

                so.status_order = 11
                self.flush()

                # Parse id_sales_order_detail yang berupa string dengan format "316,317,318"
                id_detail_list = [int(id_detail.strip()) for id_detail in str(id_sales_order_detail).split(',')]

                # Update proses_picking untuk setiap detail
                for id_detail in id_detail_list:
                    # Cari proses_picking berdasarkan id_order_detail
                    picking = prosesPicking.query.filter(prosesPicking.id_order_detail == id_detail).first()

                    if picking:
                        picking.date_on_delivery = current_date
                        self.flush()
                    else:
                        # Optional: log warning jika proses_picking tidak ditemukan
                        print(f"Warning: Proses picking untuk detail order {id_detail} tidak ditemukan")

                # Update jatuh tempo
                if plafon_data:
                    top_days = plafon_data.top or 0
                    if is_periode_closed:
                        top_days += 1
                    tanggal_jatuh_tempo = (date_now_obj() + timedelta(days=top_days)).strftime('%Y-%m-%d')
                    so.tanggal_jatuh_tempo = tanggal_jatuh_tempo
                    self.flush()

        # Commit perubahan
        self.commit()

        return {
            "status": "success",
            "message": "Reshipping berhasil diproses, dan draft berhasil dicetak"
        }, 200

    @handle_error
    def getListHistoryDistribusi(self):
        id_cabang = self.req('id_cabang')
        id_perusahaan = self.req('id_perusahaan')
        periode_awal = self.req('periode_awal')
        periode_akhir = self.req('periode_akhir')

        filters = ["so.status_order in (4, 9)"]
        bind_params = {}

        if id_cabang not in (None, "", "None"):
            filters.append("so.id_cabang = :id_cabang")
            bind_params["id_cabang"] = id_cabang

        if id_perusahaan not in (None, "", "None"):
            filters.append("pr.id_perusahaan = :id_perusahaan")
            bind_params["id_perusahaan"] = id_perusahaan

        if periode_awal not in (None, "", "None"):
            filters.append("fd.delivering_date >= :periode_awal")
            bind_params["periode_awal"] = periode_awal

        if periode_akhir not in (None, "", "None"):
            filters.append("fd.delivering_date <= :periode_akhir")
            bind_params["periode_akhir"] = periode_akhir

        where_clause = " AND ".join(filters)
        query = """
                WITH first_detail AS (
                    SELECT DISTINCT ON (sod.id_sales_order)
                        sod.id_sales_order,
                        pp.id_armada,
                        pp.delivering_date
                    FROM sales_order_detail sod
                             JOIN proses_picking pp ON pp.id_order_detail = sod.id
                    ORDER BY sod.id_sales_order, sod.id -- ambil 1 per id_sales_order (yang paling awal)
                )

                SELECT
                    so.id AS id,
                    so.id AS id_sales_order,
                    so.no_order,
                    so.id_cabang,
                    pr.id_perusahaan,
                    c.nama AS nama_customer,
                    f.no_faktur,                    
                    so.status_order,
                    fd.delivering_date 
                        AS
                     tanggal_terkirim,
                    r.kode as kode_rute,
                    a.nama as nama_armada
                FROM sales_order so
                         JOIN plafon p
                              ON p.id = so.id_plafon
                         LEFT JOIN principal pr
                              ON pr.id = p.id_principal
                         JOIN customer c
                              ON c.id = p.id_customer
                         JOIN rute r
                              ON r.id = c.id_rute
                         JOIN first_detail fd
                              ON fd.id_sales_order = so.id
                         JOIN armada a
                              ON a.id = fd.id_armada
                         JOIN faktur f
                              ON f.id_sales_order = so.id
                WHERE
                    """ + where_clause + """
                """


        return PaginateV2(request=request,query=query,bindParams=bind_params).paginate()
