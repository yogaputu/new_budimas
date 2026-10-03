import json
from flask import jsonify, request, current_app
from sqlalchemy import bindparam, text
from apps.lib.helper import date_now_stamp, time_now_stamp, date_now, to_array_string, status_order, status_faktur
from datetime import datetime, timedelta
from apps.models import (
    sales_order,
    draft_sales,
    draft_voucher,
    sales_order_detail,
    faktur,
    Produk as produk_model,
    Plafon,
    Stok,
    proses_picking, Customer, Cabang, Perusahaan, Principal, ReturRequest, ReturRequestDetail, OrderBatchModel
)
from apps.models.faktur import faktur as Faktur
from apps.models.faktur import faktur

from apps.models.Plafon import Plafon
from apps.models.Plafon import Plafon as plafon

from apps.models.SalesOrder import sales_order
from apps.models.SalesOrderDetail import sales_order_detail
from apps.models.Stok import Stok
from apps.models.Stok import Stok as stok
from apps.models.Principal import Principal as principal
from apps.models.Perusahaan import Perusahaan as perusahaan
from apps.models.Produk import Produk as produk_model

from apps.models.draft_sales import draft_sales
from apps.models.draft_voucher import draft_voucher
from apps.models.proses_picking import proses_picking
from apps.models.order_batch import OrderBatchModel
from . import BaseServices
from apps.handler import handle_error, handle_error_rollback, nonServerErrorException
from apps.services.SalesSupervisorScope import SalesSupervisorScope
from ..lib.utils import calculate_konversi
from ..models.faktur_detail import FakturDetailModel


class SalesOrder(BaseServices):
    def _normalize_order_date(self):
        requested_date = self.req("tanggal_order")
        minimum_date = datetime.strptime(date_now(), "%Y-%m-%d") + timedelta(days=1)
        if requested_date in (None, "", "None"):
            return minimum_date.strftime("%Y-%m-%d")

        requested_date = str(requested_date).strip()
        try:
            normalized_date = datetime.strptime(requested_date[:10], "%Y-%m-%d")
        except (TypeError, ValueError):
            return minimum_date.strftime("%Y-%m-%d")

        if normalized_date < minimum_date:
            raise nonServerErrorException(
                f"Tanggal order minimal {minimum_date.strftime('%Y-%m-%d')}",
                400
            )

        return normalized_date.strftime("%Y-%m-%d")

    def _normalize_retur_date(self, requested_date):
        if requested_date in (None, "", "None"):
            return None

        requested_date = str(requested_date).strip()
        try:
            return datetime.strptime(requested_date[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return None

    def _to_int(self, value, default=0):
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return default

    def _to_float(self, value, default=0.0):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return default

    def _resolve_sales_access_scope(self, current_user, raw_user_id=None, raw_id_cabang=None):
        current_user = current_user or {}
        current_jabatan_id = str(current_user.get("id_jabatan") or "")
        is_super_user = current_jabatan_id in ("1", "2")
        has_raw_user = raw_user_id not in (None, "", "None")
        has_raw_branch = raw_id_cabang not in (None, "", "None")

        if is_super_user:
            return {
                "is_super_user": True,
                "user_id": int(raw_user_id) if has_raw_user else None,
                "id_cabang": int(raw_id_cabang) if has_raw_branch else None,
                "allowed_user_ids": [],
                "force_empty": False,
            }

        supervised_sales = SalesSupervisorScope().get_supervised_sales(current_user.get("id"))
        allowed_user_ids = [
            int(row.get("id_user"))
            for row in supervised_sales
            if row.get("id_user") is not None
        ]

        if allowed_user_ids:
            if has_raw_user:
                selected_user_id = int(raw_user_id)
                return {
                    "is_super_user": False,
                    "user_id": selected_user_id,
                    "id_cabang": int(raw_id_cabang) if has_raw_branch else None,
                    "allowed_user_ids": [],
                    "force_empty": selected_user_id not in allowed_user_ids,
                }

            return {
                "is_super_user": False,
                "user_id": None,
                "id_cabang": int(raw_id_cabang) if has_raw_branch else None,
                "allowed_user_ids": allowed_user_ids,
                "force_empty": False,
            }

        return {
            "is_super_user": False,
            "user_id": int(raw_user_id) if has_raw_user else current_user.get("id"),
            "id_cabang": int(raw_id_cabang) if has_raw_branch else current_user.get("id_cabang"),
            "allowed_user_ids": [],
            "force_empty": False,
        }

    def _query_with_expanding(self, query_sql, params):
        query = text(query_sql)
        for key, value in (params or {}).items():
            if isinstance(value, (list, tuple)):
                query = query.bindparams(bindparam(key, expanding=True))
        return query

    def _get_product_ppn_rate(self, produk):
        explicit_rate = produk.get("ppn_rate")
        if explicit_rate not in (None, "", "None"):
            return self._to_float(explicit_rate)

        product_id = produk.get("id_produk") or produk.get("id")
        if not product_id:
            return 0.0

        if not hasattr(self, "_product_ppn_rate_cache"):
            self._product_ppn_rate_cache = {}

        cache_key = str(product_id)
        if cache_key not in self._product_ppn_rate_cache:
            row = self.query().setRawQuery(
                """
                    SELECT COALESCE(mp.persentase, p.ppn, 0) AS ppn_rate
                    FROM produk p
                    LEFT JOIN master_ppn mp ON mp.id = p.id_ppn
                    WHERE p.id = :id_produk
                    LIMIT 1
                """
            ).bindparams({"id_produk": int(float(product_id))}).execute().fetchone().get()
            self._product_ppn_rate_cache[cache_key] = self._to_float((row or {}).get("ppn_rate"))

        return self._product_ppn_rate_cache[cache_key]

    def _summarize_products_after_discount(self, products, total_discount=0):
        subtotal_before_discount = sum(self._to_float(produk.get("subtotalorder")) for produk in (products or []))
        tax_before_discount = sum(
            self._to_float(produk.get("subtotalorder")) * self._get_product_ppn_rate(produk) / 100
            for produk in (products or [])
        )
        total_discount = min(max(self._to_float(total_discount), 0), subtotal_before_discount)
        taxable_base = max(subtotal_before_discount - total_discount, 0)
        tax_total = 0.0

        for produk in (products or []):
            row_subtotal = self._to_float(produk.get("subtotalorder"))
            row_ratio = (row_subtotal / subtotal_before_discount) if subtotal_before_discount else 0
            row_discount = total_discount * row_ratio
            row_taxable_base = max(row_subtotal - row_discount, 0)
            tax_total += row_taxable_base * self._get_product_ppn_rate(produk) / 100

        return {
            "subtotal_before_discount": round(subtotal_before_discount, 2),
            "tax_before_discount": round(tax_before_discount, 2),
            "gross_before_discount": round(subtotal_before_discount, 2),
            "total_discount": round(total_discount, 2),
            "taxable_base": round(taxable_base, 2),
            "tax_total": round(tax_total, 2),
            "grand_total": round(taxable_base + tax_total, 2),
        }

    def _ensure_order_discount_schema(self):
        schema_map = {
            "sales_order": {
                "total_order_before_discount": "DOUBLE PRECISION DEFAULT 0",
                "unified_promo_nominal": "DOUBLE PRECISION DEFAULT 0",
                "manual_discount_type": "VARCHAR(20)",
                "manual_discount_value": "DOUBLE PRECISION DEFAULT 0",
                "manual_discount_percent_equivalent": "DOUBLE PRECISION DEFAULT 0",
                "manual_discount_nominal": "DOUBLE PRECISION DEFAULT 0",
                "order_discount_total": "DOUBLE PRECISION DEFAULT 0",
                "order_discount_note": "TEXT",
                "unified_promo_snapshot": "TEXT",
            },
            "faktur": {
                "total_penjualan_before_discount": "DOUBLE PRECISION DEFAULT 0",
                "unified_promo_nominal": "DOUBLE PRECISION DEFAULT 0",
                "manual_discount_type": "VARCHAR(20)",
                "manual_discount_value": "DOUBLE PRECISION DEFAULT 0",
                "manual_discount_percent_equivalent": "DOUBLE PRECISION DEFAULT 0",
                "manual_discount_nominal": "DOUBLE PRECISION DEFAULT 0",
                "order_discount_total": "DOUBLE PRECISION DEFAULT 0",
                "order_discount_note": "TEXT",
                "unified_promo_snapshot": "TEXT",
            },
            "customer": {
                "status_pajak": "VARCHAR(30)",
                "jenis_identitas_pajak": "VARCHAR(30)",
            },
        }

        for table_name, columns in schema_map.items():
            try:
                self.db.session.execute(
                    text(f"SELECT {', '.join(columns.keys())} FROM {table_name} LIMIT 0")
                )
            except Exception as exc:
                raise nonServerErrorException(
                    f"Schema promo/discount/customer tax belum lengkap pada tabel {table_name}. "
                    f"Jalankan tools/migrations/20260519_runtime_schema_manual.sql atau tools/migrations/20260617_customer_tax_identity.sql "
                    f"sebagai owner database terlebih dahulu. Detail: {exc}",
                    500
                )

    def _calculate_order_discount(self, products):
        self._ensure_order_discount_schema()

        base_summary = self._summarize_products_after_discount(products, 0)
        subtotal_before_discount = base_summary["subtotal_before_discount"]
        promo_payload = self.req("promo_application") or {}
        if not isinstance(promo_payload, dict):
            promo_payload = {}

        use_unified_promo = bool(promo_payload.get("use_unified_promo"))
        promo_preview = {"total_estimated_benefit": 0, "groups": []}
        promo_nominal = 0.0

        if use_unified_promo:
            try:
                from apps.services.UnifiedPromo import UnifiedPromo

                promo_service = UnifiedPromo()
                promo_preview = promo_service._calculate_preview(products or [], {
                    "order_date": self.req("tanggal_order"),
                    "id_cabang": self.req("id_cabang"),
                    "id_perusahaan": promo_payload.get("id_perusahaan") or self.req("id_perusahaan"),
                    "id_principal": promo_payload.get("id_principal") or self.req("id_principal"),
                    "id_customer": promo_payload.get("id_customer") or self.req("id_customer"),
                })
                promo_nominal = self._to_float(promo_preview.get("total_estimated_benefit"))
            except Exception as exc:
                print(f"Unified promo order preview skipped: {exc}")
                promo_preview = {"total_estimated_benefit": 0, "groups": []}
                promo_nominal = 0.0

        promo_nominal = min(max(promo_nominal, 0), subtotal_before_discount)
        manual_type = (promo_payload.get("manual_discount_type") or self.req("manual_discount_type") or "").strip().lower()
        manual_value = self._to_float(promo_payload.get("manual_discount_value") or self.req("manual_discount_value"))
        discount_base = max(subtotal_before_discount - promo_nominal, 0)

        if manual_type in ("percent", "persen", "%"):
            manual_type = "percent"
            manual_nominal = discount_base * min(max(manual_value, 0), 100) / 100
        elif manual_type in ("nominal", "amount", "rupiah", "rp"):
            manual_type = "nominal"
            manual_nominal = manual_value
        else:
            manual_type = None
            manual_value = 0
            manual_nominal = 0

        manual_nominal = min(max(manual_nominal, 0), discount_base)
        manual_percent_equivalent = (manual_nominal / discount_base * 100) if discount_base else 0
        total_discount = min(promo_nominal + manual_nominal, subtotal_before_discount)
        final_summary = self._summarize_products_after_discount(products, total_discount)

        return {
            "gross_total": final_summary["gross_before_discount"],
            "subtotal_before_discount": final_summary["subtotal_before_discount"],
            "tax_before_discount": final_summary["tax_before_discount"],
            "promo_nominal": round(promo_nominal, 2),
            "manual_type": manual_type,
            "manual_value": round(manual_value, 4),
            "manual_percent_equivalent": round(manual_percent_equivalent, 4),
            "manual_nominal": round(manual_nominal, 2),
            "total_discount": final_summary["total_discount"],
            "taxable_base": final_summary["taxable_base"],
            "tax_total": final_summary["tax_total"],
            "net_total": final_summary["grand_total"],
            "note": promo_payload.get("manual_discount_note") or promo_payload.get("note") or self.req("order_discount_note"),
            "snapshot": promo_preview,
        }

    def _apply_order_discount_columns(self, sales_order_id, discount_context, ratio=1):
        allocated_promo = round(self._to_float(discount_context.get("promo_nominal")) * ratio, 2)
        allocated_manual = round(self._to_float(discount_context.get("manual_nominal")) * ratio, 2)
        allocated_discount = round(self._to_float(discount_context.get("total_discount")) * ratio, 2)
        allocated_gross = round(self._to_float(discount_context.get("gross_total")) * ratio, 2)

        self.db.session.execute(
            text("""
            UPDATE sales_order
            SET total_order_before_discount = :gross_total,
                unified_promo_nominal = :promo_nominal,
                manual_discount_type = :manual_type,
                manual_discount_value = :manual_value,
                manual_discount_percent_equivalent = :manual_percent_equivalent,
                manual_discount_nominal = :manual_nominal,
                order_discount_total = :total_discount,
                order_discount_note = :note,
                unified_promo_snapshot = :snapshot
            WHERE id = :sales_order_id
            """),
            {
            "sales_order_id": sales_order_id,
            "gross_total": allocated_gross,
            "promo_nominal": allocated_promo,
            "manual_type": discount_context.get("manual_type"),
            "manual_value": discount_context.get("manual_value"),
            "manual_percent_equivalent": discount_context.get("manual_percent_equivalent"),
            "manual_nominal": allocated_manual,
            "total_discount": allocated_discount,
            "note": discount_context.get("note"),
            "snapshot": json.dumps(discount_context.get("snapshot") or {}, default=str),
            },
        )

    def _apply_faktur_discount_columns(self, faktur_id, discount_context):
        self.db.session.execute(
            text("""
            UPDATE faktur
            SET total_penjualan_before_discount = :gross_total,
                unified_promo_nominal = :promo_nominal,
                manual_discount_type = :manual_type,
                manual_discount_value = :manual_value,
                manual_discount_percent_equivalent = :manual_percent_equivalent,
                manual_discount_nominal = :manual_nominal,
                order_discount_total = :total_discount,
                order_discount_note = :note,
                unified_promo_snapshot = :snapshot
            WHERE id = :faktur_id
            """),
            {
            "faktur_id": faktur_id,
            "gross_total": discount_context.get("gross_total"),
            "promo_nominal": discount_context.get("promo_nominal"),
            "manual_type": discount_context.get("manual_type"),
            "manual_value": discount_context.get("manual_value"),
            "manual_percent_equivalent": discount_context.get("manual_percent_equivalent"),
            "manual_nominal": discount_context.get("manual_nominal"),
            "total_discount": discount_context.get("total_discount"),
            "note": discount_context.get("note"),
            "snapshot": json.dumps(discount_context.get("snapshot") or {}, default=str),
            },
        )

    def _record_unified_promo_usage(self, sales_order_id, faktur_id, id_plafon, discount_context, ratio=1):
        snapshot = discount_context.get("snapshot") or {}
        groups = snapshot.get("groups") or []
        qualified_groups = [item for item in groups if item.get("qualified") and self._to_float(item.get("estimated_benefit") or item.get("estimated_cashback")) > 0]
        if not qualified_groups:
            return

        plafon_row = self.db.session.execute(
            text("""
            SELECT p.id_customer, p.id_principal
            FROM plafon p
            WHERE p.id = :id_plafon
            LIMIT 1
            """),
            {"id_plafon": id_plafon},
        ).mappings().first()
        plafon_data = dict(plafon_row) if plafon_row else {}

        self.db.session.execute(
            text("""
            DELETE FROM unified_promo_usage
            WHERE id_sales_order = :sales_order_id
              AND source = 'sales_order'
            """),
            {"sales_order_id": sales_order_id},
        )

        for item in qualified_groups:
            nominal = round(self._to_float(item.get("estimated_benefit") or item.get("estimated_cashback")) * ratio, 2)
            if nominal <= 0:
                continue

            self.db.session.execute(
                text("""
                INSERT INTO unified_promo_usage (
                    promo_id, rule_id, id_sales_order, id_faktur,
                    id_customer, id_principal, nominal, status, source, catatan, used_at
                )
                VALUES (
                    :promo_id, :rule_id, :sales_order_id, :faktur_id,
                    :id_customer, :id_principal, :nominal, 'used', 'sales_order', :catatan, CURRENT_TIMESTAMP
                )
                """),
                {
                "promo_id": item.get("program_id"),
                "rule_id": item.get("rule_id"),
                "sales_order_id": sales_order_id,
                "faktur_id": faktur_id,
                "id_customer": plafon_data.get("id_customer"),
                "id_principal": plafon_data.get("id_principal"),
                "nominal": nominal,
                "catatan": item.get("nama_promo") or item.get("nama_program") or "Promo all-in order",
                },
            )

    def _publish_sales_discount_journal(self, sales_order_id, id_plafon, amount, reference=None, replace_existing=False):
        try:
            amount = float(amount or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return

        profile_row = self.db.session.execute(
            text("""
            SELECT
                c.id_cabang,
                p.id_principal,
                pr.id_perusahaan
            FROM plafon p
            LEFT JOIN customer c ON c.id = p.id_customer
            LEFT JOIN principal pr ON pr.id = p.id_principal
            WHERE p.id = :id_plafon
            LIMIT 1
            """),
            {"id_plafon": id_plafon},
        ).mappings().first()
        profile = dict(profile_row) if profile_row else {}
        if not profile.get("id_perusahaan"):
            return

        pubsub = getattr(current_app, "pubsub", None)
        if not pubsub:
            from apps.lib.pubsub import dispatch_create_jurnal
            dispatch_create_jurnal({
                "id_fitur_mal": 33,
                "id_perusahaan": int(profile["id_perusahaan"]),
                "id_cabang": int(profile["id_cabang"]) if profile.get("id_cabang") else None,
                "id_principal": int(profile["id_principal"]) if profile.get("id_principal") else None,
                "id_sales_order": int(sales_order_id) if sales_order_id else None,
                "amount": amount,
                "reference": reference or f"Diskon Penjualan SO ID: {sales_order_id}",
                "keterangan": reference or f"Diskon Penjualan SO ID: {sales_order_id}",
                "replace_existing": bool(replace_existing),
            })
            return

        pubsub.publish(data={
            "id_fitur_mal": 33,
            "id_perusahaan": int(profile["id_perusahaan"]),
            "id_cabang": int(profile["id_cabang"]) if profile.get("id_cabang") else None,
            "id_principal": int(profile["id_principal"]) if profile.get("id_principal") else None,
            "id_sales_order": int(sales_order_id) if sales_order_id else None,
            "amount": amount,
            "reference": reference or f"Diskon Penjualan SO ID: {sales_order_id}",
            "keterangan": reference or f"Diskon Penjualan SO ID: {sales_order_id}",
            "replace_existing": bool(replace_existing),
        }, topic="create_jurnal")

    def _safe_query_rows(self, query, params=None):
        response = (
            self.query()
            .setRawQuery(query)
            .bindparams(params or {})
            .execute()
            .fetchall()
        )

        raw_rows = None
        if hasattr(response, 'result'):
            raw_rows = response.result
        elif hasattr(response, 'get'):
            try:
                raw_rows = response.get()
            except TypeError:
                raw_rows = response
        else:
            raw_rows = response

        if isinstance(raw_rows, dict):
            raw_rows = raw_rows.get('result', [])

        if not isinstance(raw_rows, list):
            return []

        normalized = []
        for row in raw_rows:
            if isinstance(row, dict):
                normalized.append(row)
            elif hasattr(row, '_mapping'):
                normalized.append(dict(row._mapping))

        return normalized

    def _normalize_uom_list(self, value):
        if value in (None, '', 'None'):
            return []

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []

        if isinstance(value, dict):
            value = [value]

        if not isinstance(value, list):
            return []

        normalized = []
        for item in value:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except json.JSONDecodeError:
                    continue

            if not isinstance(item, dict):
                continue

            normalized.append({
                'id': item.get('id'),
                'level': int(item.get('level') or 0),
                'nama': item.get('nama'),
                'kode': item.get('kode'),
                'faktor_konversi': float(item.get('faktor_konversi') or 0)
            })

        return normalized

    def _retur_uom_name(self, uom_list, level):
        for item in uom_list or []:
            if int(item.get("level") or 0) == int(level):
                return item.get("nama") or item.get("kode") or None

        fallback = {1: "pcs", 2: "box", 3: "karton"}
        return fallback.get(int(level), f"uom {level}")

    def _format_retur_qty_parts(self, pieces=0, box=0, karton=0, uom_list=None, include_zero=False):
        rows = [
            (1, float(pieces or 0)),
            (2, float(box or 0)),
            (3, float(karton or 0)),
        ]
        parts = []

        for level, value in rows:
            uom_name = self._retur_uom_name(uom_list, level)
            if not uom_name:
                continue
            if not include_zero and value == 0:
                continue
            parts.append(f"{value:g} {uom_name}")

        return parts or [f"0 {self._retur_uom_name(uom_list, 1)}"]

    def _build_retur_qty_labels(self, request_ids):
        if not request_ids:
            return {}

        safe_ids = []
        for request_id in request_ids:
            try:
                safe_ids.append(str(int(request_id)))
            except (TypeError, ValueError):
                continue

        if not safe_ids:
            return {}

        details = self.db.session.execute(
            text(
                f"""
                    SELECT
                        rrd.id_request,
                        rrd.id_request_detail,
                        rrd.id_produk,
                        p.kode_sku,
                        p.nama AS nama_produk,
                        COALESCE(rrd.pieces_retur, 0) AS pieces_retur,
                        COALESCE(rrd.box_retur, 0) AS box_retur,
                        COALESCE(rrd.karton_retur, 0) AS karton_retur,
                        json_agg(
                            DISTINCT jsonb_build_object(
                                'id', pu.id,
                                'level', pu.level,
                                'nama', pu.nama,
                                'kode', pu.kode,
                                'faktor_konversi', pu.faktor_konversi
                            )
                        ) AS uom_list
                    FROM retur_request_detail rrd
                    JOIN produk p ON p.id = rrd.id_produk
                    LEFT JOIN produk_uom pu ON pu.id_produk = p.id
                    WHERE rrd.id_request IN ({",".join(safe_ids)})
                    GROUP BY rrd.id_request_detail, p.id
                    ORDER BY rrd.id_request, rrd.id_request_detail
                """
            )
        ).mappings().all()

        grouped = {}
        for row in details:
            item = dict(row)
            item["uom_list"] = self._normalize_uom_list(item.get("uom_list"))
            grouped.setdefault(item.get("id_request"), []).append(item)

        labels = {}
        for request_id, rows in grouped.items():
            uom_signatures = {
                tuple(self._retur_uom_name(row.get("uom_list"), level) for level in (1, 2, 3))
                for row in rows
            }

            if len(uom_signatures) == 1:
                first_uom = rows[0].get("uom_list") if rows else []
                labels[request_id] = " | ".join(
                    self._format_retur_qty_parts(
                        sum(float(row.get("pieces_retur") or 0) for row in rows),
                        sum(float(row.get("box_retur") or 0) for row in rows),
                        sum(float(row.get("karton_retur") or 0) for row in rows),
                        first_uom,
                        include_zero=False,
                    )
                )
                continue

            per_product_labels = []
            for row in rows:
                qty_label = " | ".join(
                    self._format_retur_qty_parts(
                        row.get("pieces_retur"),
                        row.get("box_retur"),
                        row.get("karton_retur"),
                        row.get("uom_list"),
                        include_zero=False,
                    )
                )
                product_label = row.get("kode_sku") or row.get("nama_produk") or "Produk"
                per_product_labels.append(f"{product_label}: {qty_label}")

            labels[request_id] = "; ".join(per_product_labels)

        return labels

    def _resolve_user_from_token(self):
        token = request.headers.get('Authorization')
        if not token:
            return None

        token = token.replace('Bearer ', '').strip()
        if not token:
            return None

        user = (
            self.query()
            .setRawQuery(
                """
                    SELECT id, id_cabang, id_jabatan
                    FROM users
                    WHERE tokens = :token
                """
            )
            .bindparams({'token': token})
            .execute()
            .fetchone()
        )

        return user.result if user else None

    def _retur_status_label(self, status):
        status_key = str(status) if status is not None else ''
        status_map = {
            '0': 'Pengajuan',
            '1': 'KPR Dicetak',
            '2': 'Retur Stock',
            '3': 'Credit Note',
            '9': 'Batal'
        }
        return status_map.get(status_key, f'Status {status_key or "-"}')

    def _resolve_payment_status(self, total_tagihan, total_setoran, no_faktur):
        total_tagihan = float(total_tagihan or 0)
        total_setoran = float(total_setoran or 0)

        if not no_faktur:
            return 'Belum Faktur'

        if total_setoran <= 0:
            return 'Belum Bayar'

        if total_setoran + 0.5 >= total_tagihan:
            return 'Lunas'

        return 'Sebagian'

    def _resolve_setoran_stage(self, item):
        tanggal_setoran_diterima = item.get("tanggal_setoran_diterima")
        status_setoran = item.get("status_setoran")
        id_setoran = item.get("id_setoran")
        is_rekap = item.get("is_rekap")
        total_setoran = float(item.get("total_setoran") or 0)

        if tanggal_setoran_diterima:
            return 'Diterima Kasir'

        if id_setoran is not None or status_setoran is not None:
            return 'Masuk Rekap'

        if int(is_rekap or 0) == 1:
            return 'Draft Rekap'

        if total_setoran > 0:
            return 'Pembayaran Customer'

        return 'Belum Ada Setoran'

    @handle_error
    def getSalesOrderList(self):
        raw_user_id = self.req("user_id")
        raw_status = self.req("status")
        raw_status_group = self.req("status_group")
        status_group = (
            str(raw_status_group).strip().lower()
            if raw_status_group not in (None, '', 'None')
            else ''
        )
        raw_id_cabang = self.req("id_cabang")
        raw_id_perusahaan = self.req("id_perusahaan")
        raw_status_pajak = self.req("status_pajak")
        search = (self.req("search") or "").strip()
        date_from = self.req("date_from")
        date_to = self.req("date_to")

        current_user = self._resolve_user_from_token() or {}
        access_scope = self._resolve_sales_access_scope(current_user, raw_user_id, raw_id_cabang)
        user_id = access_scope.get("user_id")
        id_cabang = access_scope.get("id_cabang")

        where_clauses = []
        params = {}

        if access_scope.get("force_empty"):
            where_clauses.append("1 = 0")

        if access_scope.get("allowed_user_ids"):
            params["allowed_user_ids"] = access_scope["allowed_user_ids"]
            where_clauses.append("pl.id_user IN :allowed_user_ids")

        if user_id not in (None, '', 'None'):
            params["user_id"] = int(user_id)
            where_clauses.append("pl.id_user = :user_id")

        if id_cabang not in (None, '', 'None'):
            params["id_cabang"] = int(id_cabang)
            where_clauses.append("so.id_cabang = :id_cabang")

        if raw_id_perusahaan not in (None, '', 'None'):
            params["id_perusahaan"] = int(raw_id_perusahaan)
            where_clauses.append("pr.id_perusahaan = :id_perusahaan")

        if raw_status_pajak not in (None, '', 'None'):
            params["status_pajak"] = str(raw_status_pajak).strip().lower()
            where_clauses.append("LOWER(COALESCE(c.status_pajak, '')) = :status_pajak")

        if status_group:
            if status_group in ("pending", "draft"):
                params["status_order"] = 0
                where_clauses.append("so.status_order = :status_order")
            elif status_group == "on_process":
                params["status_order_values"] = [1, 2, 3, 4, 10, 11]
                where_clauses.append("so.status_order IN :status_order_values")
            elif status_group in ("completed", "done", "delivered", "selesai"):
                params["status_order"] = 6
                where_clauses.append("so.status_order = :status_order")
            elif status_group in ("return", "retur"):
                params["status_order"] = 8
                where_clauses.append("so.status_order = :status_order")
            elif status_group in ("batal", "cancel", "canceled", "cancelled"):
                params["status_order"] = 7
                where_clauses.append("so.status_order = :status_order")
        elif raw_status not in (None, '', 'None'):
            params["status_order"] = int(raw_status)
            where_clauses.append("so.status_order = :status_order")

        if date_from not in (None, '', 'None'):
            params["date_from"] = date_from
            where_clauses.append("so.tanggal_order >= :date_from")

        if date_to not in (None, '', 'None'):
            params["date_to"] = date_to
            where_clauses.append("so.tanggal_order <= :date_to")

        if search:
            params["search"] = f"%{search.lower()}%"
            where_clauses.append(
                """
                    (
                        LOWER(COALESCE(so.no_order, '')) LIKE :search
                        OR LOWER(COALESCE(c.kode, '')) LIKE :search
                        OR LOWER(COALESCE(c.nama, '')) LIKE :search
                        OR LOWER(COALESCE(u.nama, '')) LIKE :search
                        OR LOWER(COALESCE(pr.nama, '')) LIKE :search
                        OR LOWER(COALESCE(pr.kode, '')) LIKE :search
                        OR EXISTS (
                            SELECT 1
                            FROM faktur f_search
                            WHERE (
                                f_search.id_sales_order = so.id
                                OR f_search.id_order_batch = so.id_order_batch
                            )
                            AND LOWER(COALESCE(f_search.no_faktur, '')) LIKE :search
                        )
                    )
                """
            )

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = self._query_with_expanding(
            f"""
                WITH retur_order_summary AS (
                    SELECT
                        rr.id_sales_order,
                        COUNT(rrd.id_request_detail) AS total_produk,
                        COALESCE(SUM(COALESCE(rrd.pieces_diajukan, rrd.pieces_retur, 0)), 0) AS total_pieces_order,
                        COALESCE(SUM(COALESCE(rrd.box_diajukan, rrd.box_retur, 0)), 0) AS total_box_order,
                        COALESCE(SUM(COALESCE(rrd.karton_diajukan, rrd.karton_retur, 0)), 0) AS total_karton_order,
                        COALESCE(SUM(COALESCE(rrd.total_retur, rrd.subtotal_retur, 0)), 0) AS total_retur
                    FROM retur_request rr
                    JOIN retur_request_detail rrd
                        ON rrd.id_request = rr.id_request
                    GROUP BY rr.id_sales_order
                )
                SELECT
                    so.id,
                    so.id_plafon,
                    so.id_order_batch,
                    so.id_cabang,
                    so.no_order,
                    so.tanggal_order,
                    so.status_order,
                    CASE
                        WHEN COALESCE(so.total_order, 0) = 0
                         AND COALESCE(MAX(ros.total_retur), 0) > 0
                        THEN COALESCE(MAX(ros.total_retur), 0)
                        ELSE so.total_order
                    END AS total_order,
                    CASE
                        WHEN COALESCE(so.total_order_before_discount, 0) = 0
                         AND COALESCE(MAX(ros.total_retur), 0) > 0
                        THEN COALESCE(MAX(ros.total_retur), 0)
                        ELSE so.total_order_before_discount
                    END AS total_order_before_discount,
                    so.unified_promo_nominal,
                    so.manual_discount_type,
                    so.manual_discount_value,
                    so.manual_discount_percent_equivalent,
                    so.manual_discount_nominal,
                    so.order_discount_total,
                    so.order_discount_note,
                    c.id AS id_customer,
                    c.kode AS kode_customer,
                    c.nama AS nama_customer,
                    c.npwp AS customer_npwp,
                    c.status_pajak AS customer_status_pajak,
                    c.jenis_identitas_pajak AS customer_jenis_identitas_pajak,
                    u.id AS id_user,
                    u.nama AS nama_sales,
                    pl.id_sales,
                    pl.id_principal,
                    MAX(pr.id_perusahaan) AS id_perusahaan,
                    COALESCE(string_agg(DISTINCT pr.kode, ', '), '-') AS kode_principal,
                    COALESCE(string_agg(DISTINCT pr.nama, ', '), '-') AS nama_principal,
                    CASE
                        WHEN COUNT(DISTINCT sod.id) = 0
                         AND COALESCE(MAX(ros.total_produk), 0) > 0
                        THEN COALESCE(MAX(ros.total_produk), 0)
                        ELSE COUNT(DISTINCT sod.id)
                    END AS total_produk,
                    CASE
                        WHEN COALESCE(SUM(COALESCE(sod.pieces_order, 0)), 0) = 0
                         AND COALESCE(MAX(ros.total_pieces_order), 0) > 0
                        THEN COALESCE(MAX(ros.total_pieces_order), 0)
                        ELSE COALESCE(SUM(COALESCE(sod.pieces_order, 0)), 0)
                    END AS total_pieces_order,
                    MAX(f.id) AS id_faktur,
                    MAX(f.no_faktur) AS no_faktur,
                    MAX(f.status_faktur) AS status_faktur,
                    CASE
                        WHEN COALESCE(MAX(f.total_penjualan), 0) = 0
                         AND COALESCE(MAX(ros.total_retur), 0) > 0
                        THEN COALESCE(MAX(ros.total_retur), 0)
                        ELSE MAX(f.total_penjualan)
                    END AS total_penjualan,
                    CASE
                        WHEN COALESCE(MAX(f.pajak), 0) = 0
                         AND COALESCE(MAX(ros.total_retur), 0) > 0
                        THEN 0
                        ELSE MAX(f.pajak)
                    END AS pajak,
                    CASE
                        WHEN COALESCE(MAX(f.dpp), 0) = 0
                         AND COALESCE(MAX(ros.total_retur), 0) > 0
                        THEN COALESCE(MAX(ros.total_retur), 0)
                        ELSE MAX(f.dpp)
                    END AS dpp,
                    MAX(f.total_penjualan_before_discount) AS faktur_total_before_discount,
                    MAX(f.unified_promo_nominal) AS faktur_unified_promo_nominal,
                    MAX(f.manual_discount_type) AS faktur_manual_discount_type,
                    MAX(f.manual_discount_value) AS faktur_manual_discount_value,
                    MAX(f.manual_discount_percent_equivalent) AS faktur_manual_discount_percent_equivalent,
                    MAX(f.manual_discount_nominal) AS faktur_manual_discount_nominal,
                    MAX(f.order_discount_total) AS faktur_order_discount_total,
                    MAX(f.order_discount_note) AS faktur_order_discount_note,
                    MAX(pp.id_armada) AS id_armada,
                    MAX(pp.id_driver) AS id_driver,
                    MAX(pp.delivering_date) AS delivering_date
                FROM sales_order so
                JOIN plafon pl ON pl.id = so.id_plafon
                JOIN customer c ON c.id = pl.id_customer
                LEFT JOIN users u ON u.id = pl.id_user
                LEFT JOIN sales_order_detail sod ON sod.id_sales_order = so.id
                LEFT JOIN retur_order_summary ros ON ros.id_sales_order = so.id
                LEFT JOIN principal pr ON pr.id = pl.id_principal
                LEFT JOIN faktur f ON f.id_sales_order = so.id OR f.id_order_batch = so.id_order_batch
                LEFT JOIN proses_picking pp ON pp.id_order_detail = sod.id
                {where_sql}
                GROUP BY
                    so.id,
                    so.id_plafon,
                    so.id_order_batch,
                    so.id_cabang,
                    so.no_order,
                    so.tanggal_order,
                    so.status_order,
                    so.total_order,
                    so.total_order_before_discount,
                    so.unified_promo_nominal,
                    so.manual_discount_type,
                    so.manual_discount_value,
                    so.manual_discount_percent_equivalent,
                    so.manual_discount_nominal,
                    so.order_discount_total,
                    so.order_discount_note,
                    c.id,
                    c.kode,
                    c.nama,
                    c.npwp,
                    c.status_pajak,
                    c.jenis_identitas_pajak,
                    u.id,
                    u.nama,
                    pl.id_sales,
                    pl.id_principal
                ORDER BY so.id DESC
            """
            ,
            params,
        )

        rows = self.db.session.execute(query, params).mappings().all()
        items = []

        for row in rows:
            item = dict(row)
            item["total_order_before_discount"] = float(item.get("faktur_total_before_discount") or item.get("total_order_before_discount") or 0)
            item["unified_promo_nominal"] = float(item.get("faktur_unified_promo_nominal") or item.get("unified_promo_nominal") or 0)
            item["manual_discount_type"] = item.get("faktur_manual_discount_type") or item.get("manual_discount_type") or ""
            item["manual_discount_value"] = float(item.get("faktur_manual_discount_value") or item.get("manual_discount_value") or 0)
            item["manual_discount_percent_equivalent"] = float(item.get("faktur_manual_discount_percent_equivalent") or item.get("manual_discount_percent_equivalent") or 0)
            item["manual_discount_nominal"] = float(item.get("faktur_manual_discount_nominal") or item.get("manual_discount_nominal") or 0)
            item["order_discount_total"] = float(item.get("faktur_order_discount_total") or item.get("order_discount_total") or 0)
            item["order_discount_note"] = item.get("faktur_order_discount_note") or item.get("order_discount_note") or ""
            item["npwp"] = item.get("customer_npwp") or item.get("npwp") or ""
            item["status_pajak"] = item.get("customer_status_pajak") or item.get("status_pajak") or ""
            item["jenis_identitas_pajak"] = item.get("customer_jenis_identitas_pajak") or item.get("jenis_identitas_pajak") or ""
            item["pajak"] = float(item.get("pajak") or 0)
            item["dpp"] = float(item.get("dpp") or 0)
            item["status_order_label"] = status_order(item.get("status_order"))
            item["status_faktur_label"] = status_faktur(item.get("status_faktur")) if item.get("status_faktur") is not None else "-"
            items.append(item)

        summary = {
            "total_orders": len(items),
            "draft_orders": len([item for item in items if item.get("status_order") == 0]),
            "active_orders": len([item for item in items if item.get("status_order") in (1, 2, 3, 4, 10, 11)]),
            "completed_orders": len([item for item in items if item.get("status_order") == 6]),
            "total_amount": float(sum(float(item.get("total_penjualan") or item.get("total_order") or 0) for item in items))
        }

        return {
            "items": items,
            "summary": summary
        }

    @handle_error
    def getSalesReturList(self):
        raw_user_id = self.req("user_id")
        raw_status = self.req("status")
        raw_status_group = self.req("status_group")
        raw_id_cabang = self.req("id_cabang")
        raw_id_perusahaan = self.req("id_perusahaan")
        search = (self.req("search") or "").strip()
        date_from = self.req("date_from")
        date_to = self.req("date_to")

        current_user = self._resolve_user_from_token() or {}
        access_scope = self._resolve_sales_access_scope(current_user, raw_user_id, raw_id_cabang)
        user_id = access_scope.get("user_id")
        id_cabang = access_scope.get("id_cabang")

        where_clauses = []
        params = {}

        if access_scope.get("force_empty"):
            where_clauses.append("1 = 0")

        if access_scope.get("allowed_user_ids"):
            params["allowed_user_ids"] = access_scope["allowed_user_ids"]
            where_clauses.append("pl.id_user IN :allowed_user_ids")

        if user_id not in (None, '', 'None'):
            params["user_id"] = int(user_id)
            where_clauses.append(
                """
                    (
                        rr.id_sales = :user_id
                        OR s.id_user = :user_id
                        OR pl.id_user = :user_id
                        OR pl.id_sales = :user_id
                    )
                """
            )

        if id_cabang not in (None, '', 'None'):
            params["id_cabang"] = int(id_cabang)
            where_clauses.append("so.id_cabang = :id_cabang")

        if raw_id_perusahaan not in (None, '', 'None'):
            params["id_perusahaan"] = int(raw_id_perusahaan)
            where_clauses.append("pr.id_perusahaan = :id_perusahaan")

        if raw_status_group not in (None, '', 'None'):
            status_group = str(raw_status_group).strip().lower()
            if status_group == "pending":
                params["status_request"] = "0"
                where_clauses.append("CAST(rr.status_request AS TEXT) = :status_request")
            elif status_group == "on_process":
                params["status_request_values"] = ["1", "2", "3"]
                where_clauses.append("CAST(rr.status_request AS TEXT) IN :status_request_values")
            elif status_group in ("batal", "cancel", "canceled", "cancelled"):
                params["status_request"] = "9"
                where_clauses.append("CAST(rr.status_request AS TEXT) = :status_request")
        elif raw_status not in (None, '', 'None'):
            params["status_request"] = str(raw_status)
            where_clauses.append("CAST(rr.status_request AS TEXT) = :status_request")
        else:
            where_clauses.append("COALESCE(NULLIF(CAST(rr.status_request AS TEXT), ''), '0') <> '9'")

        if date_from not in (None, '', 'None'):
            params["date_from"] = date_from
            where_clauses.append("rr.tanggal_request >= :date_from")

        if date_to not in (None, '', 'None'):
            params["date_to"] = date_to
            where_clauses.append("rr.tanggal_request <= :date_to")

        if search:
            params["search"] = f"%{search.lower()}%"
            where_clauses.append(
                """
                    (
                        LOWER(COALESCE(rr.kode_request, '')) LIKE :search
                        OR LOWER(COALESCE(rr.kode_kpr, '')) LIKE :search
                        OR LOWER(COALESCE(rr.no_cn, '')) LIKE :search
                        OR LOWER(COALESCE(so.no_order, '')) LIKE :search
                        OR EXISTS (
                            SELECT 1
                            FROM faktur f_search
                            WHERE (
                                f_search.id_sales_order = so.id
                                OR f_search.id_order_batch = so.id_order_batch
                            )
                            AND LOWER(COALESCE(f_search.no_faktur, '')) LIKE :search
                        )
                        OR LOWER(COALESCE(c.nama, '')) LIKE :search
                        OR LOWER(COALESCE(pr.nama, '')) LIKE :search
                    )
                """
            )

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        rows = self.db.session.execute(
            self._query_with_expanding(
                f"""
                    WITH base_retur AS (
                        SELECT
                            rr.id_request,
                            rr.id_sales,
                            rr.kode_request,
                            rr.kode_kpr,
                            rr.no_cn,
                            rr.tanggal_request,
                            rr.tanggal_retur,
                            rr.status_request,
                            rr.total_retur,
                            so.id AS id_sales_order,
                            so.id_plafon,
                            so.no_order,
                            so.status_order,
                            so.id_cabang,
                            so.id_order_batch,
                            c.nama AS nama_customer,
                            pr.nama AS nama_principal
                        FROM retur_request rr
                        JOIN sales_order so ON so.id = rr.id_sales_order
                        LEFT JOIN sales s ON s.id = rr.id_sales
                        LEFT JOIN plafon pl ON pl.id = so.id_plafon
                        LEFT JOIN customer c ON c.id = rr.id_customer
                        LEFT JOIN principal pr ON pr.id = rr.id_principal
                        {where_sql}
                    )
                    SELECT
                        br.id_request,
                        br.id_sales,
                        br.kode_request,
                        br.kode_kpr,
                        COALESCE(br.no_cn, cns.kode_cn) AS no_cn,
                        br.tanggal_request,
                        br.tanggal_retur,
                        br.status_request,
                        COALESCE(br.total_retur, cns.total_cn, 0) AS total_retur,
                        br.id_sales_order,
                        br.id_plafon,
                        br.no_order,
                        br.status_order,
                        br.id_cabang,
                        br.nama_customer,
                        br.nama_principal,
                        fs.no_faktur,
                        COALESCE(ds.total_produk, 0) AS total_produk,
                        COALESCE(ds.total_pieces_retur, 0) AS total_pieces_retur,
                        COALESCE(ds.total_box_retur, 0) AS total_box_retur,
                        COALESCE(ds.total_karton_retur, 0) AS total_karton_retur,
                        COALESCE(ds.total_qty_retur, 0) AS total_qty_retur
                    FROM base_retur br
                    LEFT JOIN LATERAL (
                        SELECT
                            COUNT(rrd.id_request_detail) AS total_produk,
                            COALESCE(SUM(COALESCE(rrd.pieces_retur, 0)), 0) AS total_pieces_retur,
                            COALESCE(SUM(COALESCE(rrd.box_retur, 0)), 0) AS total_box_retur,
                            COALESCE(SUM(COALESCE(rrd.karton_retur, 0)), 0) AS total_karton_retur,
                            COALESCE(
                                SUM(
                                    COALESCE(rrd.pieces_retur, 0)
                                    + COALESCE(rrd.box_retur, 0)
                                    + COALESCE(rrd.karton_retur, 0)
                                ),
                                0
                            ) AS total_qty_retur
                        FROM retur_request_detail rrd
                        WHERE rrd.id_request = br.id_request
                    ) ds ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT MAX(f_inner.no_faktur) AS no_faktur
                        FROM faktur f_inner
                        WHERE f_inner.id_sales_order = br.id_sales_order
                           OR f_inner.id_order_batch = br.id_order_batch
                    ) fs ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT
                            MAX(cn.kode_cn) AS kode_cn,
                            MAX(cn.total_cn) AS total_cn
                        FROM credit_note cn
                        WHERE cn.id_retur_request = br.id_request
                    ) cns ON TRUE
                    ORDER BY br.id_request DESC
                """
                ,
                params,
            ),
            params
        ).mappings().all()

        qty_labels = self._build_retur_qty_labels([row.get("id_request") for row in rows])

        items = []
        for row in rows:
            item = dict(row)
            item["status_request_label"] = self._retur_status_label(item.get("status_request"))
            item["status_order_label"] = status_order(item.get("status_order"))
            item["total_retur"] = float(item.get("total_retur") or 0)
            item["total_qty_retur"] = float(item.get("total_qty_retur") or 0)
            item["total_pieces_retur"] = float(item.get("total_pieces_retur") or 0)
            item["total_box_retur"] = float(item.get("total_box_retur") or 0)
            item["total_karton_retur"] = float(item.get("total_karton_retur") or 0)
            item["qty_retur_label"] = qty_labels.get(item.get("id_request")) or " | ".join(
                self._format_retur_qty_parts(
                    item["total_pieces_retur"],
                    item["total_box_retur"],
                    item["total_karton_retur"],
                    include_zero=False,
                )
            )
            items.append(item)

        summary = {
            "total_requests": len(items),
            "pending_requests": len([item for item in items if str(item.get("status_request")) == '0']),
            "kpr_requests": len([item for item in items if str(item.get("status_request")) == '1']),
            "processed_requests": len([item for item in items if str(item.get("status_request")) in ('2', '3')]),
            "on_process_requests": len([item for item in items if str(item.get("status_request")) in ('1', '2', '3')]),
            "canceled_requests": len([item for item in items if str(item.get("status_request")) == '9']),
            "total_amount": float(sum(float(item.get("total_retur") or 0) for item in items))
        }

        return {
            "items": items,
            "summary": summary
        }

    @handle_error
    def getSalesInvoiceDashboard(self):
        self._ensure_order_discount_schema()
        raw_user_id = self.req("user_id")
        raw_id_sales = self.req("id_sales")
        raw_faktur_status = self.req("faktur_status")
        raw_payment_status = self.req("payment_status")
        raw_id_cabang = self.req("id_cabang")
        raw_id_perusahaan = self.req("id_perusahaan")
        raw_status_pajak = self.req("status_pajak")
        search = (self.req("search") or "").strip()
        date_from = self.req("date_from")
        date_to = self.req("date_to")

        current_user = self._resolve_user_from_token() or {}
        access_scope = self._resolve_sales_access_scope(current_user, raw_user_id, raw_id_cabang)
        user_id = access_scope.get("user_id")
        id_cabang = access_scope.get("id_cabang")

        where_clauses = []
        params = {}

        if access_scope.get("force_empty"):
            where_clauses.append("1 = 0")

        if access_scope.get("allowed_user_ids"):
            params["allowed_user_ids"] = access_scope["allowed_user_ids"]
            where_clauses.append("pl.id_user IN :allowed_user_ids")

        if raw_id_sales not in (None, '', 'None'):
            params["id_sales"] = int(raw_id_sales)
            where_clauses.append("pl.id_sales = :id_sales")
        elif user_id not in (None, '', 'None'):
            params["user_id"] = int(user_id)
            where_clauses.append("pl.id_user = :user_id")

        if id_cabang not in (None, '', 'None'):
            params["id_cabang"] = int(id_cabang)
            where_clauses.append("so.id_cabang = :id_cabang")

        if raw_id_perusahaan not in (None, '', 'None'):
            params["id_perusahaan"] = int(raw_id_perusahaan)
            where_clauses.append("pr.id_perusahaan = :id_perusahaan")

        if raw_status_pajak not in (None, '', 'None'):
            params["status_pajak"] = str(raw_status_pajak).strip().lower()
            where_clauses.append("LOWER(COALESCE(c.status_pajak, '')) = :status_pajak")

        if raw_faktur_status not in (None, '', 'None'):
            params["status_faktur"] = int(raw_faktur_status)
            where_clauses.append("COALESCE(f.status_faktur, -999) = :status_faktur")

        if date_from not in (None, '', 'None'):
            params["date_from"] = date_from
            where_clauses.append("so.tanggal_order >= :date_from")

        if date_to not in (None, '', 'None'):
            params["date_to"] = date_to
            where_clauses.append("so.tanggal_order <= :date_to")

        if search:
            params["search"] = f"%{search.lower()}%"
            where_clauses.append(
                """
                    (
                        LOWER(COALESCE(so.no_order, '')) LIKE :search
                        OR LOWER(COALESCE(f.no_faktur, '')) LIKE :search
                        OR LOWER(COALESCE(c.nama, '')) LIKE :search
                        OR LOWER(COALESCE(pr.nama, '')) LIKE :search
                        OR LOWER(COALESCE(u.nama, '')) LIKE :search
                    )
                """
            )

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        rows = self.db.session.execute(
            self._query_with_expanding(
                f"""
                    WITH payment_totals AS (
                        SELECT
                            id_sales_order,
                            COALESCE(SUM(jumlah_setoran), 0) AS total_setoran,
                            MAX(tanggal_input) AS tanggal_setoran_terakhir,
                            MAX(is_rekap) AS is_rekap
                        FROM setoran_customer
                        GROUP BY id_sales_order
                    ),
                    voucher_totals AS (
                        SELECT
                            id_sales_order,
                            COALESCE(SUM(nominal), 0) AS total_voucher_used
                        FROM payment_voucher_usage
                        WHERE status = 1
                        GROUP BY id_sales_order
                    ),
                    setoran_meta AS (
                        SELECT
                            id_sales_order,
                            MAX(id) AS id_setoran,
                            MAX(status_setoran) AS status_setoran,
                            MAX(tanggal_setoran_diterima) AS tanggal_setoran_diterima
                        FROM setoran
                        GROUP BY id_sales_order
                    ),
                    picking_dates AS (
                        SELECT
                            sod.id_sales_order,
                            MAX(pp.delivering_date) AS delivering_date
                        FROM sales_order_detail sod
                        LEFT JOIN proses_picking pp ON pp.id_order_detail = sod.id
                        GROUP BY sod.id_sales_order
                    )
                    SELECT
                        so.id,
                        so.id_plafon,
                        pl.id_sales,
                        so.id_order_batch,
                        so.id_cabang,
                        so.no_order,
                        so.tanggal_order,
                        so.tanggal_jatuh_tempo,
                        so.status_order,
                        c.nama AS nama_customer,
                        c.npwp AS customer_npwp,
                        c.status_pajak AS customer_status_pajak,
                        c.jenis_identitas_pajak AS customer_jenis_identitas_pajak,
                        pr.nama AS nama_principal,
                        u.nama AS nama_sales,
                        MAX(f.id) AS id_faktur,
                        MAX(f.no_faktur) AS no_faktur,
                        MAX(f.status_faktur) AS status_faktur,
                        COALESCE(MAX(f.total_penjualan), MAX(so.total_order), 0) AS total_penjualan,
                        COALESCE(MAX(f.nominal_retur), 0) AS nominal_retur,
                        COALESCE(MAX(pay.total_setoran), 0) AS total_setoran_cash,
                        COALESCE(MAX(vu.total_voucher_used), 0) + COALESCE(MAX(f.order_discount_total), MAX(so.order_discount_total), 0) AS total_voucher_used,
                        COALESCE(MAX(f.order_discount_total), MAX(so.order_discount_total), 0) AS order_discount_total,
                        COALESCE(MAX(f.unified_promo_nominal), MAX(so.unified_promo_nominal), 0) AS unified_promo_nominal,
                        COALESCE(MAX(f.manual_discount_nominal), MAX(so.manual_discount_nominal), 0) AS manual_discount_nominal,
                        COALESCE(MAX(f.manual_discount_percent_equivalent), MAX(so.manual_discount_percent_equivalent), 0) AS manual_discount_percent_equivalent,
                        COALESCE(MAX(f.manual_discount_type), MAX(so.manual_discount_type), '') AS manual_discount_type,
                        COALESCE(MAX(f.order_discount_note), MAX(so.order_discount_note), '') AS order_discount_note,
                        COALESCE(MAX(pay.total_setoran), 0) + COALESCE(MAX(vu.total_voucher_used), 0) AS total_setoran,
                        MAX(pay.tanggal_setoran_terakhir) AS tanggal_setoran_terakhir,
                        MAX(pay.is_rekap) AS is_rekap,
                        MAX(sm.id_setoran) AS id_setoran,
                        MAX(sm.status_setoran) AS status_setoran,
                        MAX(sm.tanggal_setoran_diterima) AS tanggal_setoran_diterima,
                        MAX(pd.delivering_date) AS delivering_date
                    FROM sales_order so
                    JOIN plafon pl ON pl.id = so.id_plafon
                    LEFT JOIN customer c ON c.id = pl.id_customer
                    LEFT JOIN principal pr ON pr.id = pl.id_principal
                    LEFT JOIN users u ON u.id = pl.id_user
                    LEFT JOIN faktur f ON f.id_sales_order = so.id OR f.id_order_batch = so.id_order_batch
                    LEFT JOIN payment_totals pay ON pay.id_sales_order = so.id
                    LEFT JOIN voucher_totals vu ON vu.id_sales_order = so.id
                    LEFT JOIN setoran_meta sm ON sm.id_sales_order = so.id
                    LEFT JOIN picking_dates pd ON pd.id_sales_order = so.id
                    {where_sql}
                    GROUP BY
                        so.id,
                        so.id_plafon,
                        pl.id_sales,
                        so.id_order_batch,
                        so.id_cabang,
                        so.no_order,
                        so.tanggal_order,
                        so.tanggal_jatuh_tempo,
                        so.status_order,
                        c.nama,
                        c.npwp,
                        c.status_pajak,
                        c.jenis_identitas_pajak,
                        pr.nama,
                        u.nama
                    ORDER BY so.id DESC
                """
                ,
                params,
            ),
            params
        ).mappings().all()

        items = []
        for row in rows:
            item = dict(row)
            total_penjualan = float(item.get("total_penjualan") or 0)
            nominal_retur = float(item.get("nominal_retur") or 0)
            total_setoran = float(item.get("total_setoran") or 0)
            total_tagihan = max(total_penjualan - nominal_retur, 0)
            sisa_tagihan = max(total_tagihan - total_setoran, 0)
            payment_status_label = self._resolve_payment_status(total_tagihan, total_setoran, item.get("no_faktur"))
            effective_status_faktur = item.get("status_faktur")

            if payment_status_label == 'Lunas':
                effective_status_faktur = 3
            elif payment_status_label in ('Belum Bayar', 'Sebagian') and effective_status_faktur in (None, 0, 1):
                effective_status_faktur = 2

            item["status_order_label"] = status_order(item.get("status_order"))
            item["status_faktur"] = effective_status_faktur
            item["status_faktur_label"] = status_faktur(effective_status_faktur) if effective_status_faktur is not None else "-"
            item["total_penjualan"] = total_penjualan
            item["nominal_retur"] = nominal_retur
            item["total_setoran_cash"] = float(item.get("total_setoran_cash") or 0)
            item["total_voucher_used"] = float(item.get("total_voucher_used") or 0)
            item["order_discount_total"] = float(item.get("order_discount_total") or 0)
            item["unified_promo_nominal"] = float(item.get("unified_promo_nominal") or 0)
            item["manual_discount_nominal"] = float(item.get("manual_discount_nominal") or 0)
            item["manual_discount_percent_equivalent"] = float(item.get("manual_discount_percent_equivalent") or 0)
            item["npwp"] = item.get("customer_npwp") or item.get("npwp") or ""
            item["status_pajak"] = item.get("customer_status_pajak") or item.get("status_pajak") or ""
            item["jenis_identitas_pajak"] = item.get("customer_jenis_identitas_pajak") or item.get("jenis_identitas_pajak") or ""
            item["total_setoran"] = total_setoran
            item["total_tagihan"] = total_tagihan
            item["sisa_tagihan"] = sisa_tagihan
            item["payment_status_label"] = payment_status_label
            item["setoran_stage_label"] = self._resolve_setoran_stage(item)

            if raw_payment_status not in (None, '', 'None') and payment_status_label != raw_payment_status:
                continue

            items.append(item)

        summary = {
            "total_invoices": len(items),
            "belum_faktur": len([item for item in items if item.get("payment_status_label") == 'Belum Faktur']),
            "belum_bayar": len([item for item in items if item.get("payment_status_label") == 'Belum Bayar']),
            "sebagian": len([item for item in items if item.get("payment_status_label") == 'Sebagian']),
            "lunas": len([item for item in items if item.get("payment_status_label") == 'Lunas']),
            "total_tagihan": float(sum(float(item.get("total_tagihan") or 0) for item in items)),
            "total_setoran_cash": float(sum(float(item.get("total_setoran_cash") or 0) for item in items)),
            "total_voucher_used": float(sum(float(item.get("total_voucher_used") or 0) for item in items)),
            "total_setoran": float(sum(float(item.get("total_setoran") or 0) for item in items)),
            "total_sisa_tagihan": float(sum(float(item.get("sisa_tagihan") or 0) for item in items))
        }

        return {
            "items": items,
            "summary": summary
        }

    def updateSisaPlafon(self, id_plafon, total_penjualan):
        get_plafon = plafon.query.filter(plafon.id == id_plafon).first()
        limit_plafon = get_plafon.limit_bon
        sisa_plafon = get_plafon.sisa_bon
        sisa_bon = None

        if sisa_plafon != None:
            sisa_bon = sisa_plafon - total_penjualan
            # if sisa_bon < 0: sisa_bon = 0
        else:
            sisa_bon = limit_plafon - total_penjualan

        get_plafon.sisa_bon = sisa_bon

    def searchIdPlafon(self, id_plafon):
        plafons = []
        sorted_ids = sorted([self._to_int(id) for id in id_plafon if self._to_int(id)], reverse=True)

        for id in sorted_ids:
            plafon = (
                self
                .query()
                .setRawQuery(
                    f"""
                        select * from plafon
                        where id = {id} 
                    """
                )
                .execute()
                .fetchone()
                .result
            )

            if not plafon:
                raise nonServerErrorException(f"Plafon dengan ID {id} tidak ditemukan")
            plafons.append(plafon)


        return plafons

    def searchIdPlafonByIdPrincipal(self, id_plafon, id_principal):
        plafon = {}
        sorted_ids = sorted([self._to_int(id) for id in id_plafon if self._to_int(id)], reverse=True)

        for id in sorted_ids:
            plafon = (
                self
                .query()
                .setRawQuery(
                    f"""
                        select * from plafon
                        where id = {id}
                        and id_principal = {id_principal}
                    """
                )
                .execute()
                .fetchone()
                .result
            )

            if len(plafon): return plafon

        return plafon

    @handle_error_rollback
    def SalesRequestWithDBT(self):
        """
         Generate sales request
         @return dict
        """
        products = self.req("products")
        id_cabang = self._to_int(self.req("id_cabang"), None)
        if id_cabang is None:
            raise nonServerErrorException("Cabang wajib dipilih sebelum membuat order")

        allow_overstock_order = str(self.req("allow_overstock_order") or "").lower() in ("1", "true", "yes", "y")
        overstock_warnings = []

        # validate products
        for produk in products:
            data_produk = produk_model.query.get(produk["id_produk"])
            if not data_produk:
                raise nonServerErrorException(f"Produk dengan ID {produk['id_produk']} tidak ditemukan")

            data_stok = stok.query.filter(
                stok.produk_id == produk["id_produk"],
                stok.cabang_id == id_cabang
            ).first()

            if not data_stok:
                message = f"Data stok untuk produk {data_produk.nama} di cabang ini tidak ditemukan"
                if allow_overstock_order:
                    overstock_warnings.append({
                        "id_produk": produk["id_produk"],
                        "nama_produk": data_produk.nama,
                        "dipesan": produk.get("total_pieces", 0),
                        "tersedia": 0,
                        "message": message,
                    })
                    continue
                raise nonServerErrorException(message)

            total_pieces_dipesan = produk.get("total_pieces", 0)

            jumlah_ready = data_stok.jumlah_ready or 0
            if total_pieces_dipesan > jumlah_ready:
                message = (
                    f"Stok tidak mencukupi untuk produk {data_produk.nama}. "
                    f"Dipesan: {total_pieces_dipesan}, Tersedia: {jumlah_ready}"
                )
                if allow_overstock_order:
                    overstock_warnings.append({
                        "id_produk": produk["id_produk"],
                        "nama_produk": data_produk.nama,
                        "dipesan": total_pieces_dipesan,
                        "tersedia": jumlah_ready,
                        "message": message,
                    })
                    continue
                raise nonServerErrorException(message)

        if overstock_warnings:
            request.mobile_overstock_warnings = overstock_warnings
            print("WARN MOBILE OVERSTOCK ORDER:", overstock_warnings)

        data_product_by_principal = self.__filtered_by_id_principal(self.req("products"))

        if len(data_product_by_principal) > 1:
            plafon_arr = self.searchIdPlafon(self.req("id_plafon"))
            return self.__for_multiple_principal(plafon_arr, products)
        else:
            id_principal =products[0]["id_principal"]
            plafon_obj = self.searchIdPlafonByIdPrincipal(self.req("id_plafon"), id_principal)
            id_plafon = int(plafon_obj["id"])
            return self.__for_one_principal(id_plafon=id_plafon, products=products)

    def __for_multiple_principal(self, plafon_arr, products):
        discount_context = self._calculate_order_discount(products)
        total_order = discount_context["subtotal_before_discount"]
        net_total_order = discount_context["net_total"]
        total_discount = discount_context["total_discount"]

        new_order_batch = OrderBatchModel(
            id_sales=plafon_arr[0]["id_sales"],
            id_customer=plafon_arr[0]["id_customer"],
            status=0
        )

        data_product_by_principal = self.__filtered_by_id_principal(self.req("products"))

        self.add(new_order_batch).flush()

        # Faktur dibuat dengan no_faktur NULL
        faktur_sales = faktur(
            no_faktur=None,  # Set NULL dulu
            status_faktur=0,
            jenis_faktur='penjualan',
            subtotal_penjualan=total_order,
            subtotal_diskon=total_discount,
            total_penjualan=net_total_order,
            total_dana_diterima=self.req("total_dana_diterima") or 0,
            pajak=discount_context["tax_total"],
            dpp=discount_context["taxable_base"],
            id_order_batch=new_order_batch.id
        )

        self.add(faktur_sales).flush()
        self._apply_faktur_discount_columns(faktur_sales.id, discount_context)
        for plafon in plafon_arr:
            id_plafon = plafon["id"]
            if plafon["id_principal"] not in data_product_by_principal:
                continue
            draftSales = draft_sales(
                id_plafon=id_plafon,
                no_order=self.req("no_sales_order"),
                tanggal_order=self.req("tanggal_order"),
                # tanggal_jatuh_tempo=self.req(
                #     "tanggal_jatuh_tempo") or tanggal_jatuh_tempo,
                nama_sales=self.req("nama_sales"),
                status_order="0"
            )

            self.add(draftSales).flush()

            sales_order_id = draftSales.id

            tanggal_order = self._normalize_order_date()

            total_order_by_principal = sum(
                self._to_float(produk.get("subtotalorder")) for produk in data_product_by_principal[plafon["id_principal"]])
            ratio = (total_order_by_principal / total_order) if total_order else 0
            principal_discount = total_discount * ratio
            principal_summary = self._summarize_products_after_discount(
                data_product_by_principal[plafon["id_principal"]],
                principal_discount
            )
            net_order_by_principal = principal_summary["grand_total"]

            salesOrder = sales_order()
            salesOrder.id = sales_order_id
            salesOrder.id_plafon = id_plafon
            salesOrder.id_cabang = self.req("id_cabang")
            salesOrder.no_order = self.req("no_sales_order")
            salesOrder.tanggal_order = tanggal_order
            salesOrder.nama_sales = self.req("nama_sales")
            salesOrder.status_order = 0
            salesOrder.total_order = net_order_by_principal
            salesOrder.id_order_batch = new_order_batch.id

            self.add(salesOrder)
            self.flush()
            self._apply_order_discount_columns(sales_order_id, discount_context, ratio)
            self._record_unified_promo_usage(sales_order_id, faktur_sales.id, id_plafon, discount_context, ratio)
            self._publish_sales_discount_journal(
                sales_order_id,
                id_plafon,
                total_discount * ratio,
                f"Diskon Penjualan SO {self.req('no_sales_order') or sales_order_id}",
            )

            subtotal_diskon = sum(produk["totalDiskon"] for produk in data_product_by_principal[plafon["id_principal"]])
            pajak = principal_summary["tax_total"]

            # Faktur dibuat dengan no_faktur NULL
            faktur_detail = FakturDetailModel(
                id_faktur=faktur_sales.id,
                id_sales_order=sales_order_id,
                id_principal=plafon["id_principal"],
                subtotal_diskon=subtotal_diskon + (total_discount * ratio),
                subtotal=total_order_by_principal,
                draft_total=net_order_by_principal,
                pajak=pajak
            )

            self.add(faktur_detail)

            self.flush()

            total_kubikasi = 0
            # Add products to the list of produks
            for produk in data_product_by_principal[plafon["id_principal"]]:
                pieces_order = self._to_int(produk.get("pieces_order"))
                box_order = self._to_int(produk.get("box_order"))
                karton_order = self._to_int(produk.get("karton_order"))
                harga_jual = self._to_float(produk.get("harga_jual"))
                subtotal_order = self._to_float(produk.get("subtotalorder"))
                total_diskon = self._to_float(produk.get("totalDiskon"))

                # calculate total kubikasi
                curr_produk = produk_model.query.get(produk["id_produk"])
                kubikasi_per_pieces = curr_produk.kubikasiperpieces or 0
                kubikasi_per_box = curr_produk.kubikasiperbox or 0
                kubikasi_per_karton = curr_produk.kubikasiperkarton or 0

                kubikasi_pieces = kubikasi_per_pieces * \
                                  pieces_order
                kubikasi_box = kubikasi_per_box * box_order
                kubikasi_karton = kubikasi_per_karton * \
                                  karton_order

                curr_total = kubikasi_pieces + kubikasi_box + kubikasi_karton
                total_kubikasi += curr_total

                salesOrderDetail = sales_order_detail(
                    id_sales_order=sales_order_id,
                    id_produk=produk["id_produk"],
                    pieces_order=pieces_order,
                    box_order=box_order,
                    karton_order=karton_order,
                    hargaorder=harga_jual,
                    subtotalorder=subtotal_order,
                    vouchers=produk.get("vouchers") or [],
                    estimasi_kubikasi=curr_total,
                    total_nilai_discount=total_diskon
                )

                self.add(salesOrderDetail).flush()

                # add proses picking
                picking = proses_picking(
                    id_order_detail=salesOrderDetail.id,
                    id_produk=produk["id_produk"]
                )

                self.add(picking)

                if 'voucherSelections' in produk:
                    # Voucher 1 Regular
                    if 'voucher1Regular' in produk['voucherSelections'] and produk['voucherSelections'][
                        'voucher1Regular']:
                        voucher1Regular = produk['voucherSelections']['voucher1Regular']
                        diskon1Regular = produk['discountDetails'][
                            'diskon1Regular'] if 'discountDetails' in produk and 'diskon1Regular' in \
                                                 produk['discountDetails'] else 0

                        draftVoucher1Regular = draft_voucher(
                            id_sales_order=sales_order_id,
                            id_sales_order_detail=salesOrderDetail.id,
                            id_voucher=voucher1Regular['id'],
                            tipe_voucher=1,
                            status_promo=0,
                            status_klaim=0,
                            jumlah_diskon=diskon1Regular,
                            kode_voucher=voucher1Regular['kode_voucher']
                        )

                        self.add(draftVoucher1Regular)

                    # Voucher 2 Regular
                    if 'voucher2Regular' in produk['voucherSelections'] and produk['voucherSelections'][
                        'voucher2Regular']:
                        voucher2Regular = produk['voucherSelections']['voucher2Regular']
                        diskon2Regular = produk['discountDetails'][
                            'diskon2Regular'] if 'discountDetails' in produk and 'diskon2Regular' in \
                                                 produk['discountDetails'] else 0

                        draftVoucher2Regular = draft_voucher(
                            id_sales_order=sales_order_id,
                            id_sales_order_detail=salesOrderDetail.id,
                            id_voucher=voucher2Regular['id'],
                            tipe_voucher=2,
                            status_promo=0,
                            status_klaim=0,
                            jumlah_diskon=diskon2Regular,
                            kode_voucher=voucher2Regular['kode_voucher']
                        )

                        self.add(draftVoucher2Regular)

                    # Voucher 3 Regular
                    if 'voucher3Regular' in produk['voucherSelections'] and produk['voucherSelections'][
                        'voucher3Regular']:
                        voucher3Regular = produk['voucherSelections']['voucher3Regular']
                        diskon3Regular = produk['discountDetails'][
                            'diskon3Regular'] if 'discountDetails' in produk and 'diskon3Regular' in \
                                                 produk['discountDetails'] else 0

                        draftVoucher3Regular = draft_voucher(
                            id_sales_order=sales_order_id,
                            id_sales_order_detail=salesOrderDetail.id,
                            id_voucher=voucher3Regular['id'],
                            tipe_voucher=3,
                            status_promo=0,
                            status_klaim=0,
                            jumlah_diskon=diskon3Regular,
                            kode_voucher=voucher3Regular['kode_voucher']
                        )

                        self.add(draftVoucher3Regular)

                    # Voucher 2 Product
                    if 'voucher2Product' in produk['voucherSelections'] and produk['voucherSelections'][
                        'voucher2Product']:
                        voucher2Product = produk['voucherSelections']['voucher2Product']
                        diskon2Product = produk['discountDetails'][
                            'diskon2Product'] if 'discountDetails' in produk and 'diskon2Product' in \
                                                 produk['discountDetails'] else 0

                        draftVoucher2Product = draft_voucher(
                            id_sales_order=sales_order_id,
                            id_sales_order_detail=salesOrderDetail.id,
                            id_voucher=voucher2Product['id'],
                            tipe_voucher=2,  # Tetap menggunakan tipe_voucher=2 karena ini adalah voucher level 2
                            status_promo=0,
                            status_klaim=0,
                            jumlah_diskon=diskon2Product,
                            kode_voucher=voucher2Product['kode_voucher']
                        )

                        self.add(draftVoucher2Product)

                    # Voucher 3 Product
                    if 'voucher3Product' in produk['voucherSelections'] and produk['voucherSelections'][
                        'voucher3Product']:
                        voucher3Product = produk['voucherSelections']['voucher3Product']
                        diskon3Product = produk['discountDetails'][
                            'diskon3Product'] if 'discountDetails' in produk and 'diskon3Product' in \
                                                 produk['discountDetails'] else 0

                        draftVoucher3Product = draft_voucher(
                            id_sales_order=sales_order_id,
                            id_sales_order_detail=salesOrderDetail.id,
                            id_voucher=voucher3Product['id'],
                            tipe_voucher=3,  # Tetap menggunakan tipe_voucher=3 karena ini adalah voucher level 3
                            status_promo=0,
                            status_klaim=0,
                            jumlah_diskon=diskon3Product,
                            kode_voucher=voucher3Product['kode_voucher']
                        )

                        self.add(draftVoucher3Product)

            get_sales_order = sales_order.query.get(sales_order_id)
            get_sales_order.total_kubikasi = total_kubikasi

            self.add(get_sales_order)
            self.flush()

        self.flush().commit()

        faktur_just_inserted = {
            "no_faktur": None,
            "id_sales_order": faktur_sales.id_sales_order,
            "status_faktur": faktur_sales.status_faktur,
            "jenis_faktur": faktur_sales.jenis_faktur,
            "subtotal_penjualan": faktur_sales.subtotal_penjualan,
            "subtotal_diskon": faktur_sales.subtotal_diskon,
            "total_penjualan": faktur_sales.total_penjualan,
            "total_dana_diterima": faktur_sales.total_dana_diterima,
            "pajak": faktur_sales.pajak
        }

        return jsonify(faktur_just_inserted)

    def __for_one_principal(self, id_plafon, products):
        discount_context = self._calculate_order_discount(products)
        total_order = discount_context["subtotal_before_discount"]
        net_total_order = discount_context["net_total"]
        total_discount = discount_context["total_discount"]

        draftSales = draft_sales(
            id_plafon=id_plafon,
            no_order=self.req("no_sales_order"),
            tanggal_order=self.req("tanggal_order"),
            # tanggal_jatuh_tempo=self.req(
            #     "tanggal_jatuh_tempo") or tanggal_jatuh_tempo,
            nama_sales=self.req("nama_sales"),
            status_order="0"
        )

        self.add(draftSales).flush()

        sales_order_id = draftSales.id

        tanggal_order = self._normalize_order_date()

        salesOrder = sales_order()
        salesOrder.id = sales_order_id
        salesOrder.id_plafon = id_plafon
        salesOrder.id_cabang = self.req("id_cabang")
        salesOrder.no_order = self.req("no_sales_order")
        salesOrder.tanggal_order = tanggal_order
        salesOrder.nama_sales = self.req("nama_sales")
        salesOrder.status_order = 0
        salesOrder.total_order = net_total_order

        self.add(salesOrder)

        # Faktur dibuat dengan no_faktur NULL
        faktur_sales = faktur(
            no_faktur=None,  # Set NULL dulu
            id_sales_order=sales_order_id,
            status_faktur=0,
            jenis_faktur='penjualan',
            subtotal_penjualan=total_order,
            subtotal_diskon=total_discount,
            total_penjualan=net_total_order,
            total_dana_diterima=self.req("total_dana_diterima") or 0,
            pajak=discount_context["tax_total"],
            dpp=discount_context["taxable_base"]
        )

        self.add(faktur_sales).flush()
        self._apply_order_discount_columns(sales_order_id, discount_context)
        self._apply_faktur_discount_columns(faktur_sales.id, discount_context)
        self._record_unified_promo_usage(sales_order_id, faktur_sales.id, id_plafon, discount_context)
        self._publish_sales_discount_journal(
            sales_order_id,
            id_plafon,
            total_discount,
            f"Diskon Penjualan SO {self.req('no_sales_order') or sales_order_id}",
        )

        total_kubikasi = 0
        # Add products to the list of produks
        for produk in self.req("products"):
            pieces_order = self._to_int(produk.get("pieces_order"))
            box_order = self._to_int(produk.get("box_order"))
            karton_order = self._to_int(produk.get("karton_order"))
            harga_jual = self._to_float(produk.get("harga_jual"))
            subtotal_order = self._to_float(produk.get("subtotalorder"))
            total_diskon = self._to_float(produk.get("totalDiskon"))

            # calculate total kubikasi
            curr_produk = produk_model.query.get(produk["id_produk"])
            kubikasi_per_pieces = curr_produk.kubikasiperpieces or 0
            kubikasi_per_box = curr_produk.kubikasiperbox or 0
            kubikasi_per_karton = curr_produk.kubikasiperkarton or 0

            kubikasi_pieces = kubikasi_per_pieces * \
                              pieces_order
            kubikasi_box = kubikasi_per_box * box_order
            kubikasi_karton = kubikasi_per_karton * \
                              karton_order

            curr_total = kubikasi_pieces + kubikasi_box + kubikasi_karton
            total_kubikasi += curr_total

            salesOrderDetail = sales_order_detail(
                id_sales_order=sales_order_id,
                id_produk=produk["id_produk"],
                pieces_order=pieces_order,
                box_order=box_order,
                karton_order=karton_order,
                hargaorder=harga_jual,
                subtotalorder=subtotal_order,
                vouchers=produk.get("vouchers") or [],
                estimasi_kubikasi=curr_total,
                total_nilai_discount=total_diskon
            )

            self.add(salesOrderDetail).flush()

            # add proses picking
            picking = proses_picking(
                id_order_detail=salesOrderDetail.id,
                id_produk=produk["id_produk"]
            )

            self.add(picking)

            if 'voucherSelections' in produk:
                # Voucher 1 Regular
                if 'voucher1Regular' in produk['voucherSelections'] and produk['voucherSelections'][
                    'voucher1Regular']:
                    voucher1Regular = produk['voucherSelections']['voucher1Regular']
                    diskon1Regular = produk['discountDetails'][
                        'diskon1Regular'] if 'discountDetails' in produk and 'diskon1Regular' in \
                                             produk['discountDetails'] else 0

                    draftVoucher1Regular = draft_voucher(
                        id_sales_order=sales_order_id,
                        id_sales_order_detail=salesOrderDetail.id,
                        id_voucher=voucher1Regular['id'],
                        tipe_voucher=1,
                        status_promo=0,
                        status_klaim=0,
                        jumlah_diskon=diskon1Regular,
                        kode_voucher=voucher1Regular['kode_voucher']
                    )

                    self.add(draftVoucher1Regular)

                # Voucher 2 Regular
                if 'voucher2Regular' in produk['voucherSelections'] and produk['voucherSelections'][
                    'voucher2Regular']:
                    voucher2Regular = produk['voucherSelections']['voucher2Regular']
                    diskon2Regular = produk['discountDetails'][
                        'diskon2Regular'] if 'discountDetails' in produk and 'diskon2Regular' in \
                                             produk['discountDetails'] else 0

                    draftVoucher2Regular = draft_voucher(
                        id_sales_order=sales_order_id,
                        id_sales_order_detail=salesOrderDetail.id,
                        id_voucher=voucher2Regular['id'],
                        tipe_voucher=2,
                        status_promo=0,
                        status_klaim=0,
                        jumlah_diskon=diskon2Regular,
                        kode_voucher=voucher2Regular['kode_voucher']
                    )

                    self.add(draftVoucher2Regular)

                # Voucher 3 Regular
                if 'voucher3Regular' in produk['voucherSelections'] and produk['voucherSelections'][
                    'voucher3Regular']:
                    voucher3Regular = produk['voucherSelections']['voucher3Regular']
                    diskon3Regular = produk['discountDetails'][
                        'diskon3Regular'] if 'discountDetails' in produk and 'diskon3Regular' in \
                                             produk['discountDetails'] else 0

                    draftVoucher3Regular = draft_voucher(
                        id_sales_order=sales_order_id,
                        id_sales_order_detail=salesOrderDetail.id,
                        id_voucher=voucher3Regular['id'],
                        tipe_voucher=3,
                        status_promo=0,
                        status_klaim=0,
                        jumlah_diskon=diskon3Regular,
                        kode_voucher=voucher3Regular['kode_voucher']
                    )

                    self.add(draftVoucher3Regular)

                # Voucher 2 Product
                if 'voucher2Product' in produk['voucherSelections'] and produk['voucherSelections'][
                    'voucher2Product']:
                    voucher2Product = produk['voucherSelections']['voucher2Product']
                    diskon2Product = produk['discountDetails'][
                        'diskon2Product'] if 'discountDetails' in produk and 'diskon2Product' in \
                                             produk['discountDetails'] else 0

                    draftVoucher2Product = draft_voucher(
                        id_sales_order=sales_order_id,
                        id_sales_order_detail=salesOrderDetail.id,
                        id_voucher=voucher2Product['id'],
                        tipe_voucher=2,  # Tetap menggunakan tipe_voucher=2 karena ini adalah voucher level 2
                        status_promo=0,
                        status_klaim=0,
                        jumlah_diskon=diskon2Product,
                        kode_voucher=voucher2Product['kode_voucher']
                    )

                    self.add(draftVoucher2Product)

                # Voucher 3 Product
                if 'voucher3Product' in produk['voucherSelections'] and produk['voucherSelections'][
                    'voucher3Product']:
                    voucher3Product = produk['voucherSelections']['voucher3Product']
                    diskon3Product = produk['discountDetails'][
                        'diskon3Product'] if 'discountDetails' in produk and 'diskon3Product' in \
                                             produk['discountDetails'] else 0

                    draftVoucher3Product = draft_voucher(
                        id_sales_order=sales_order_id,
                        id_sales_order_detail=salesOrderDetail.id,
                        id_voucher=voucher3Product['id'],
                        tipe_voucher=3,  # Tetap menggunakan tipe_voucher=3 karena ini adalah voucher level 3
                        status_promo=0,
                        status_klaim=0,
                        jumlah_diskon=diskon3Product,
                        kode_voucher=voucher3Product['kode_voucher']
                    )

                    self.add(draftVoucher3Product)

        get_sales_order = sales_order.query.get(sales_order_id)
        get_sales_order.total_kubikasi = total_kubikasi

        self.flush().commit()

        faktur_just_inserted = {
            "no_faktur": None,
            "id_sales_order": faktur_sales.id_sales_order,
            "status_faktur": faktur_sales.status_faktur,
            "jenis_faktur": faktur_sales.jenis_faktur,
            "subtotal_penjualan": faktur_sales.subtotal_penjualan,
            "subtotal_diskon": faktur_sales.subtotal_diskon,
            "total_penjualan": faktur_sales.total_penjualan,
            "total_dana_diterima": faktur_sales.total_dana_diterima,
            "pajak": faktur_sales.pajak
        }

        return jsonify(faktur_just_inserted)

    def __filtered_by_id_principal(self, data_products):
        data_filtered = {}
        for data_product in data_products:
            id_principal = data_product['id_principal']
            if id_principal not in data_filtered:
                data_filtered[id_principal] = []
            data_filtered[id_principal].append(data_product)
        return data_filtered

    @handle_error
    def getEditableSalesOrder(self, id_sales_order):
        self._ensure_order_discount_schema()

        header = self.db.session.execute(text("""
            SELECT
                so.id,
                so.no_order,
                so.tanggal_order,
                so.status_order,
                so.id_plafon,
                so.id_cabang AS id_cabang_order,
                so.total_order,
                so.total_order_before_discount,
                so.unified_promo_nominal,
                so.manual_discount_type,
                so.manual_discount_value,
                so.manual_discount_percent_equivalent,
                so.manual_discount_nominal,
                so.order_discount_total,
                so.order_discount_note,
                so.unified_promo_snapshot,
                pl.id_customer,
                pl.id_principal,
                pl.id_sales,
                pl.id_user AS id_user_plafon,
                c.id_cabang,
                pr.id_perusahaan,
                s.id_user AS id_user_sales,
                COALESCE(us.nama, so.nama_sales, '') AS nama_sales
            FROM sales_order so
            JOIN plafon pl ON pl.id = so.id_plafon
            LEFT JOIN customer c ON c.id = pl.id_customer
            LEFT JOIN principal pr ON pr.id = pl.id_principal
            LEFT JOIN sales s ON s.id = pl.id_sales
            LEFT JOIN users us ON us.id = COALESCE(s.id_user, pl.id_user)
            WHERE so.id = :id_sales_order
            LIMIT 1
        """), {"id_sales_order": id_sales_order}).mappings().first()

        if not header:
            raise nonServerErrorException("Sales order tidak ditemukan", 404)

        details = self.db.session.execute(text("""
            SELECT
                sod.id,
                sod.id_produk,
                p.nama,
                p.kode_sku,
                sod.pieces_order,
                sod.box_order,
                sod.karton_order,
                sod.hargaorder,
                sod.subtotalorder,
                sod.total_nilai_discount,
                p.ppn,
                p.id_ppn
            FROM sales_order_detail sod
            JOIN produk p ON p.id = sod.id_produk
            WHERE sod.id_sales_order = :id_sales_order
            ORDER BY sod.id ASC
        """), {"id_sales_order": id_sales_order}).mappings().all()

        return jsonify({
            "header": dict(header),
            "details": [dict(row) for row in details],
        })

    @handle_error_rollback
    def updateEditableSalesOrder(self, id_sales_order):
        self.db.session.execute(text("SET LOCAL lock_timeout = '5s'"))
        self.db.session.execute(text("SET LOCAL statement_timeout = '110s'"))

        header = self.db.session.execute(text("""
            SELECT
                so.id,
                so.status_order,
                so.id_plafon,
                so.id_order_batch,
                so.order_discount_total,
                f.id AS id_faktur
            FROM sales_order so
            LEFT JOIN faktur f ON f.id_sales_order = so.id
            WHERE so.id = :id_sales_order
            LIMIT 1
        """), {"id_sales_order": id_sales_order}).mappings().first()

        if not header:
            raise nonServerErrorException("Sales order tidak ditemukan", 404)

        if self._to_int(header.get("status_order"), -999) != 0:
            raise nonServerErrorException("Order hanya bisa diedit saat masih draft / menunggu verifikasi", 400)

        products = self.req("products") or []
        if not products:
            raise nonServerErrorException("Minimal satu produk wajib diisi", 400)

        product_ids = []
        for produk in products:
            product_id = self._to_int(produk.get("id_produk"), None)
            if product_id is None:
                raise nonServerErrorException("Produk order tidak valid", 400)
            product_ids.append(product_id)

        product_query = text("""
            SELECT id, kubikasiperpieces, kubikasiperbox, kubikasiperkarton
            FROM produk
            WHERE id IN :product_ids
        """).bindparams(bindparam("product_ids", expanding=True))
        product_lookup = {
            int(row["id"]): dict(row)
            for row in self.db.session.execute(product_query, {"product_ids": product_ids}).mappings().all()
        }

        id_cabang = self._to_int(self.req("id_cabang"), None)
        if id_cabang is None:
            raise nonServerErrorException("Cabang wajib dipilih", 400)

        discount_context = self._calculate_order_discount(products)
        net_total_order = discount_context["net_total"]
        total_order = discount_context["subtotal_before_discount"]
        total_discount = discount_context["total_discount"]
        tanggal_order = self._normalize_order_date()
        no_order = self.req("no_sales_order") or header.get("no_order")
        nama_sales = self.req("nama_sales")

        total_kubikasi = 0
        old_details = self.db.session.execute(text("""
            SELECT id
            FROM sales_order_detail
            WHERE id_sales_order = :id_sales_order
        """), {"id_sales_order": id_sales_order}).mappings().all()
        old_detail_ids = [row["id"] for row in old_details]

        if old_detail_ids:
            self.db.session.execute(
                text("DELETE FROM draft_voucher WHERE id_sales_order = :id_sales_order"),
                {"id_sales_order": id_sales_order}
            )
            proses_picking.query.filter(proses_picking.id_order_detail.in_(old_detail_ids)).delete(synchronize_session=False)
            sales_order_detail.query.filter(sales_order_detail.id_sales_order == id_sales_order).delete(synchronize_session=False)

        for produk in products:
            product_id = self._to_int(produk.get("id_produk"), None)
            pieces_order = self._to_int(produk.get("pieces_order"))
            box_order = self._to_int(produk.get("box_order"))
            karton_order = self._to_int(produk.get("karton_order"))
            harga_jual = self._to_float(produk.get("harga_jual"))
            subtotal_order = self._to_float(produk.get("subtotalorder"))
            total_diskon = self._to_float(produk.get("totalDiskon"))

            curr_produk = product_lookup.get(product_id)
            if not curr_produk:
                raise nonServerErrorException(f"Produk dengan ID {product_id} tidak ditemukan", 400)

            curr_total = (
                (curr_produk.get("kubikasiperpieces") or 0) * pieces_order
                + (curr_produk.get("kubikasiperbox") or 0) * box_order
                + (curr_produk.get("kubikasiperkarton") or 0) * karton_order
            )
            total_kubikasi += curr_total

            detail = sales_order_detail(
                id_sales_order=id_sales_order,
                id_produk=product_id,
                pieces_order=pieces_order,
                box_order=box_order,
                karton_order=karton_order,
                hargaorder=harga_jual,
                subtotalorder=subtotal_order,
                vouchers=produk.get("vouchers") or [],
                estimasi_kubikasi=curr_total,
                total_nilai_discount=total_diskon,
            )
            self.add(detail).flush()
            self.add(proses_picking(id_order_detail=detail.id, id_produk=product_id))

        self.db.session.execute(text("""
            UPDATE sales_order
            SET no_order = :no_order,
                tanggal_order = :tanggal_order,
                nama_sales = :nama_sales,
                id_cabang = :id_cabang,
                total_order = :total_order,
                total_kubikasi = :total_kubikasi
            WHERE id = :id_sales_order
        """), {
            "id_sales_order": id_sales_order,
            "no_order": no_order,
            "tanggal_order": tanggal_order,
            "nama_sales": nama_sales,
            "id_cabang": id_cabang,
            "total_order": net_total_order,
            "total_kubikasi": total_kubikasi,
        })

        self.db.session.execute(text("""
            UPDATE draft_sales
            SET no_order = :no_order,
                tanggal_order = :tanggal_order,
                nama_sales = :nama_sales
            WHERE id = :id_sales_order
        """), {
            "id_sales_order": id_sales_order,
            "no_order": no_order,
            "tanggal_order": tanggal_order,
            "nama_sales": nama_sales,
        })

        if header.get("id_faktur"):
            self.db.session.execute(text("""
                UPDATE faktur
                SET subtotal_penjualan = :subtotal_penjualan,
                    subtotal_diskon = :subtotal_diskon,
                    total_penjualan = :total_penjualan,
                    pajak = :pajak,
                    dpp = :dpp
                WHERE id = :id_faktur
            """), {
                "id_faktur": header["id_faktur"],
                "subtotal_penjualan": total_order,
                "subtotal_diskon": total_discount,
                "total_penjualan": net_total_order,
                "pajak": discount_context["tax_total"],
                "dpp": discount_context["taxable_base"],
            })
            self._apply_faktur_discount_columns(header["id_faktur"], discount_context)

        self._apply_order_discount_columns(id_sales_order, discount_context)
        self._record_unified_promo_usage(id_sales_order, header.get("id_faktur"), header.get("id_plafon"), discount_context)
        self._publish_sales_discount_journal(
            id_sales_order,
            header.get("id_plafon"),
            total_discount,
            f"Diskon Penjualan SO {no_order or id_sales_order}",
            replace_existing=True,
        )

        self.flush().commit()

        return jsonify({
            "status": 200,
            "message": "Sales order berhasil diperbarui",
            "id_sales_order": id_sales_order,
            "total_order": net_total_order,
            "order_discount_total": total_discount,
        })


    @handle_error
    def SalesStockOpname(self):
        log_stockOpname = [
            {
                "id_sales": self.req("id_sales"),
                "id_principal": self.req("id_principal"),
                "id_customer": self.req("id_customer"),
                "id_produk": product["id_produk"],
                "pieces": product["pieces"],
                "box": product["box"],
                "karton": product["karton"],
            }
            for product in self.req("products")
        ]

        return (
            self.query()
            .setRawQuery(
                """
                    INSERT INTO log_stockopname_sales
                    (id_produk, id_sales, id_principal, id_customer, pieces, box, karton)
                    VALUES
                    (:id_produk, :id_sales, :id_principal, :id_customer, :pieces, :box, :karton)
                """
            )
            .bulkQuery(log_stockOpname)
            .result
        )

    @handle_error_rollback
    def salesSkipRequest(self):
        id_plafons = self.req("id_plafon")
        keterangan = self.req("keterangan")

        for id in id_plafons:
            add_sales_order = sales_order(id_plafon=id, status_order=-2, keterangan=keterangan)
            self.add(add_sales_order).flush()

        self.commit()

        return 'skip sales order', 200

    @handle_error
    def searchFaktur(self):
        def normalize_query_rows(value):
            if not value:
                return []
            if isinstance(value, dict) and isinstance(value.get("result"), list):
                value = value["result"]
            elif isinstance(value, dict):
                value = [value]

            rows = []
            for row in value:
                if isinstance(row, dict):
                    rows.append(row)
                elif hasattr(row, "_mapping"):
                    rows.append(dict(row._mapping))
                elif hasattr(row, "_asdict"):
                    rows.append(row._asdict())
            return rows

        id_plafon = self.req("id_plafon")
        search = (self.req("search") or "").strip()
        status_faktur_filter = self.req("status-faktur")

        if not search:
            return []

        where_clauses = [
            "faktur.jenis_faktur = 'penjualan'",
            """
            (
                faktur.no_faktur ILIKE :search
                OR sales_order.no_order ILIKE :search
                OR customer.nama ILIKE :search
                OR customer.kode ILIKE :search
                OR principal.nama ILIKE :search
            )
            """
        ]
        bindparams = {"search": f"%{search}%"}

        normalized_plafon_ids = []
        if isinstance(id_plafon, list):
            normalized_plafon_ids = [self._to_int(value) for value in id_plafon if self._to_int(value)]
        elif id_plafon not in (None, "", "None"):
            normalized_plafon_ids = [self._to_int(id_plafon)]

        if normalized_plafon_ids:
            where_clauses.append("sales_order.id_plafon = ANY(:id_plafon)")
            bindparams["id_plafon"] = normalized_plafon_ids

        if status_faktur_filter not in (None, "", "None"):
            where_clauses.append("(CAST(faktur.status_faktur AS TEXT) = :status_faktur OR CAST(sales_order.status_order AS TEXT) = :status_faktur)")
            bindparams["status_faktur"] = str(status_faktur_filter)

        where_sql = " AND ".join(where_clauses)

        fakturs = (
            self.db.session.execute(
                text(
                    f"""
                    SELECT
                        sales_order.id AS id_sales_order,
                        sales_order.id_plafon,
                        sales_order.id_cabang,
                        sales_order.no_order,
                        sales_order.tanggal_order,
                        sales_order.status_order,
                        plafon.id_sales,
                        plafon.id_user AS sales_user_id,
                        customer.id AS id_customer,
                        customer.kode AS kode_customer,
                        customer.nama AS nama_customer,
                        principal.id AS id_principal,
                        principal.nama AS nama_principal,
                        faktur.id AS id_faktur,
                        faktur.no_faktur,
                        faktur.no_faktur AS nomor_faktur,
                        faktur.status_faktur,
                        faktur.total_penjualan,
                        faktur.nominal_retur,
                        latest_retur.id_request AS id_retur_request,
                        latest_retur.kode_request,
                        latest_retur.kode_kpr,
                        latest_retur.no_cn,
                        latest_retur.status_request AS status_request_retur
                    FROM sales_order
                    JOIN faktur ON sales_order.id = faktur.id_sales_order
                    JOIN plafon ON plafon.id = sales_order.id_plafon
                    LEFT JOIN customer ON customer.id = plafon.id_customer
                    LEFT JOIN principal ON principal.id = plafon.id_principal
                    LEFT JOIN LATERAL (
                        SELECT rr.id_request, rr.kode_request, rr.kode_kpr, rr.no_cn, rr.status_request
                        FROM retur_request rr
                        WHERE rr.id_sales_order = sales_order.id
                        ORDER BY rr.id_request DESC
                        LIMIT 1
                    ) latest_retur ON TRUE
                    WHERE {where_sql}
                    ORDER BY faktur.id DESC
                    LIMIT 30
                    """
                ),
                bindparams
            )
            .mappings()
            .all()
        )

        if not len(fakturs):
            retur_where_clauses = [
                """
                (
                    retur_request.kode_request ILIKE :search
                    OR retur_request.kode_kpr ILIKE :search
                    OR retur_request.no_cn ILIKE :search
                    OR sales_order.no_order ILIKE :search
                    OR customer.nama ILIKE :search
                    OR customer.kode ILIKE :search
                    OR principal.nama ILIKE :search
                )
                """
            ]

            if normalized_plafon_ids:
                retur_where_clauses.append("sales_order.id_plafon = ANY(:id_plafon)")

            if status_faktur_filter not in (None, "", "None"):
                retur_where_clauses.append(
                    "(CAST(retur_request.status_request AS TEXT) = :status_faktur OR CAST(sales_order.status_order AS TEXT) = :status_faktur)"
                )

            retur_where_sql = " AND ".join(retur_where_clauses)
            fakturs = (
                self.db.session.execute(
                    text(
                        f"""
                        SELECT
                            sales_order.id AS id_sales_order,
                            sales_order.id_plafon,
                            sales_order.id_cabang,
                            sales_order.no_order,
                            sales_order.tanggal_order,
                            sales_order.status_order,
                            plafon.id_sales,
                            plafon.id_user AS sales_user_id,
                            customer.id AS id_customer,
                            customer.kode AS kode_customer,
                            customer.nama AS nama_customer,
                            principal.id AS id_principal,
                            principal.nama AS nama_principal,
                            faktur.id AS id_faktur,
                            faktur.no_faktur,
                            COALESCE(faktur.no_faktur, retur_request.no_cn, retur_request.kode_request, sales_order.no_order) AS nomor_faktur,
                            faktur.status_faktur,
                            COALESCE(faktur.total_penjualan, retur_request.total_retur, 0) AS total_penjualan,
                            COALESCE(faktur.nominal_retur, retur_request.total_retur, 0) AS nominal_retur,
                            retur_request.id_request AS id_retur_request,
                            retur_request.kode_request,
                            retur_request.kode_kpr,
                            retur_request.no_cn,
                            retur_request.status_request AS status_request_retur
                        FROM retur_request
                        JOIN sales_order ON sales_order.id = retur_request.id_sales_order
                        JOIN plafon ON plafon.id = sales_order.id_plafon
                        LEFT JOIN customer ON customer.id = plafon.id_customer
                        LEFT JOIN principal ON principal.id = plafon.id_principal
                        LEFT JOIN LATERAL (
                            SELECT f.id, f.no_faktur, f.status_faktur, f.total_penjualan, f.nominal_retur
                            FROM faktur f
                            WHERE f.id_sales_order = sales_order.id
                              AND f.jenis_faktur = 'penjualan'
                            ORDER BY f.id DESC
                            LIMIT 1
                        ) faktur ON TRUE
                        WHERE {retur_where_sql}
                        ORDER BY retur_request.id_request DESC
                        LIMIT 30
                        """
                    ),
                    bindparams
                )
                .mappings()
                .all()
            )

            if not len(fakturs):
                return []

        fakturs = [dict(row) for row in fakturs]

        for faktur in fakturs:
            products_result = (
                self.query()
                .setRawQuery(
                    """
                        SELECT * 
                        FROM sales_order_detail 
                        WHERE id_sales_order = :id_sales_order
                    """
                )
                .bindparams({"id_sales_order": faktur["id_sales_order"]})
                .execute()
                .fetchall()
                .get()
            )
            faktur["products"] = normalize_query_rows(products_result)

            for fakturProduct in faktur["products"]:
                produk_result = (
                    self.query()
                    .setRawQuery(
                        """
                            SELECT * 
                            FROM produk 
                            WHERE
                            id = :id_produk 
                        """
                    )
                    .bindparams({"id_produk": fakturProduct["id_produk"]})
                    .execute()
                    .fetchone()
                    .result
                )
                if hasattr(produk_result, "_mapping"):
                    produk_result = dict(produk_result._mapping)
                fakturProduct["produk"] = produk_result or {}

                konversi_result = (
                    self.query()
                    .setRawQuery(
                        """
                            SELECT * 
                            FROM produk_uom 
                            WHERE
                            id_produk = :id_produk 
                        """
                    )
                    .bindparams({"id_produk": fakturProduct["id_produk"]})
                    .execute()
                    .fetchall()
                    .get()
                )
                fakturProduct['konversi'] = normalize_query_rows(konversi_result)


        return fakturs

    @handle_error_rollback
    def createReturRequest(self):
        id_sales_order = self.req('id_sales_order')
        id_sales = self.req('id_sales')
        id_plafon = self.req('id_plafon')
        raw_tanggal_retur_pengajuan = self.req('tanggal_retur_pengajuan')
        tanggal_retur_pengajuan = self._normalize_retur_date(raw_tanggal_retur_pengajuan)
        products = self.req('products')

        def safe_float(value, default=0):
            try:
                if value in (None, '', 'None'):
                    return default
                return float(value)
            except (TypeError, ValueError):
                return default

        if not tanggal_retur_pengajuan:
            tanggal_retur_pengajuan = date_now()

        is_periode_closed, next_date = self.check_is_periode_closed()
        if is_periode_closed and not raw_tanggal_retur_pengajuan:
            tanggal_retur_pengajuan = next_date.strftime("%Y-%m-%d")

        if not id_sales_order or not id_sales or not id_plafon or not products:
            raise nonServerErrorException("ID Sales Order, ID Sales, ID Plafon, dan Products harus diisi")

        data_plafon = (
            self.db.session.query(plafon,
                                             principal,
                                             perusahaan.kode.label('kode_perusahan'))
                        .join(principal, plafon.id_principal == principal.id)
                          .join(perusahaan, principal.id_perusahaan == perusahaan.id)
                        .filter(plafon.id == id_plafon)
                        .first()
                       )
        if not data_plafon:
            raise nonServerErrorException(f"Plafon dengan ID {id_plafon} tidak ditemukan")
        plafon_data = data_plafon[0]  # instance model plafon
        principal_data = data_plafon[1]  # instance model principal
        kode_perusahaan = data_plafon[2]  # string kode dari perusahaan
        id_customer = plafon_data.id_customer
        id_principal = plafon_data.id_principal
        kode_perusahaan = kode_perusahaan

        prefix_kode_request = f"RT{kode_perusahaan}-"

        self.db.session.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('retur_request', 'id_request'),
                    GREATEST(COALESCE((SELECT MAX(id_request) FROM retur_request), 0), 1),
                    CASE WHEN EXISTS (SELECT 1 FROM retur_request) THEN true ELSE false END
                )
                """
            )
        )

        last_kode_request = (
            ReturRequest.query.filter(
                ReturRequest.kode_request.like(f"{prefix_kode_request}%")
            ).with_for_update().order_by(ReturRequest.kode_request.desc()).first()
        )

        if last_kode_request:
            last_kode = last_kode_request.kode_request
            last_number = int(last_kode.split('-')[-1])
            next_number = last_number + 1
        else:
            next_number = 1

        counter_str = f"{next_number:04d}"  # Format dengan 4 digit

        kode_request = f"{prefix_kode_request}{counter_str}"

        add_retur_request = ReturRequest(
            id_sales_order=id_sales_order,
            kode_request=kode_request,
            id_sales=id_sales,
            id_customer=id_customer,
            id_principal=id_principal,
            tanggal_request=tanggal_retur_pengajuan ,
            status_request=0,
            subtotal_retur=safe_float(self.req('subtotal')),
            total_dpp_retur=safe_float(self.req('subtotal')),
            total_ppn_retur=safe_float(self.req('ppn')),
            total_retur=safe_float(self.req('total_retur') or self.req('grand_total')),
        )

        self.add(add_retur_request).flush()

        self.db.session.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('retur_request_detail', 'id_request_detail'),
                    GREATEST(COALESCE((SELECT MAX(id_request_detail) FROM retur_request_detail), 0), 1),
                    CASE WHEN EXISTS (SELECT 1 FROM retur_request_detail) THEN true ELSE false END
                )
                """
            )
        )

        datas_sales_order_detail = self._safe_query_rows(
            """
            SELECT
                   COALESCE(sod.pieces_delivered, sod.pieces_picked, sod.pieces_order, 0) AS pieces_delivered,
                   COALESCE(sod.box_delivered, sod.box_picked, sod.box_order, 0) AS box_delivered,
                   COALESCE(sod.karton_delivered, sod.karton_picked, sod.karton_order, 0) AS karton_delivered,
                   COALESCE(sod.pieces_order, 0) AS pieces_order,
                   COALESCE(sod.box_order, 0) AS box_order,
                   COALESCE(sod.karton_order, 0) AS karton_order,
                   COALESCE(sod.hargaorder, 0) AS hargaorder,
                   sod.id_produk,
                   sod.id,
                   json_agg(
                           DISTINCT jsonb_build_object(
                           'id', produk_uom.id,
                           'level', produk_uom.level,
                           'faktor_konversi', produk_uom.faktor_konversi
                                    )
                   ) AS uom_list
            FROM sales_order_detail sod
                     JOIN produk_uom
                          ON sod.id_produk = produk_uom.id_produk
            WHERE id_sales_order = :id_sales_order
            GROUP BY
                COALESCE(sod.pieces_delivered, sod.pieces_picked, sod.pieces_order, 0),
                COALESCE(sod.box_delivered, sod.box_picked, sod.box_order, 0),
                COALESCE(sod.karton_delivered, sod.karton_picked, sod.karton_order, 0),
                COALESCE(sod.pieces_order, 0),
                COALESCE(sod.box_order, 0),
                COALESCE(sod.karton_order, 0),
                COALESCE(sod.hargaorder, 0),
                sod.id_produk,
                sod.id
            """,
            {"id_sales_order": id_sales_order}
        )

        if not datas_sales_order_detail:
            raise nonServerErrorException(f"Sales Order dengan ID {id_sales_order} tidak ditemukan atau tidak memiliki detail produk")

        subtotal_retur_request = 0
        total_dpp_retur_request = 0
        total_ppn_retur_request = 0
        total_retur_request = 0

        for product in products:

            data_sales_order_detail = next((
                detail for detail in datas_sales_order_detail
                if detail['id_produk'] == product['id_produk']
            ), None)

            if not data_sales_order_detail:
                raise nonServerErrorException(f"Produk dengan ID {product['id_produk']} tidak ditemukan dalam Sales Order ini")

            uom_list = self._normalize_uom_list(data_sales_order_detail.get('uom_list'))
            if not uom_list:
                raise nonServerErrorException(
                    f"Konversi UOM untuk produk {product['id_produk']} tidak ditemukan atau tidak valid"
                )

            data_retur = calculate_konversi(
                {
                    "pieces": product['pieces_retur_good'] + product['pieces_retur_bad'],
                    "box": product['box_retur_good'] + product['box_retur_bad'],
                    "karton": product['karton_retur_good'] + product['karton_retur_bad']
                },
                uom_list
            )

            data_order = calculate_konversi(
                {
                    "pieces": data_sales_order_detail['pieces_delivered'],
                    "box": data_sales_order_detail['box_delivered'],
                    "karton": data_sales_order_detail['karton_delivered']
                },
                uom_list
            )
            data_original_order = calculate_konversi(
                {
                    "pieces": data_sales_order_detail.get('pieces_order', 0),
                    "box": data_sales_order_detail.get('box_order', 0),
                    "karton": data_sales_order_detail.get('karton_order', 0)
                },
                uom_list
            )

            if data_order['pieces'] <= 0 or (
                data_original_order['pieces'] > 0 and data_order['pieces'] > data_original_order['pieces']
            ):
                data_order = data_original_order

            if data_retur['pieces'] > data_order['pieces']:
                raise nonServerErrorException(
                    f"Jumlah retur untuk produk {product['id_produk']} melebihi jumlah yang dipesan. "
                    f"Jumlah dipesan: {data_order['pieces']}, Jumlah retur: {data_retur['pieces']}"
                )

            harga_satuan = product.get('harga_satuan') or data_sales_order_detail.get('hargaorder') or 0
            subtotal_retur = safe_float(product.get('subtotal_retur'), data_retur['pieces'] * safe_float(harga_satuan))
            total_retur = safe_float(product.get('total_retur'), subtotal_retur)
            ppn_retur = max(total_retur - subtotal_retur, 0)

            add_retur_request_detail = ReturRequestDetail(
                id_request=add_retur_request.id_request,
                id_sales_order_detail=data_sales_order_detail['id'],
                id_produk=product['id_produk'],
                pieces_diajukan=product['pieces_retur_bad'],
                box_diajukan=product['box_retur_bad'],
                karton_diajukan=product['karton_retur_bad'],
                alasan_retur=product['keterangan_retur'],
                harga_satuan=harga_satuan,
                subtotal_retur=subtotal_retur,
                dpp_retur=subtotal_retur,
                ppn_retur=ppn_retur,
                total_retur=total_retur,
                pieces_retur=product['pieces_retur_bad'] + product['pieces_retur_good'],
                box_retur=product['box_retur_bad'] + product['box_retur_good'],
                karton_retur=product['karton_retur_bad'] + product['karton_retur_good'],
                pieces_good_diajukan=product['pieces_retur_good'],
                box_good_diajukan=product['box_retur_good'],
                karton_good_diajukan=product['karton_retur_good'],
            )

            self.add(add_retur_request_detail).flush()

            subtotal_retur_request += subtotal_retur
            total_dpp_retur_request += subtotal_retur
            total_ppn_retur_request += ppn_retur
            total_retur_request += total_retur

        if safe_float(add_retur_request.total_retur) <= 0 and total_retur_request > 0:
            add_retur_request.subtotal_retur = subtotal_retur_request
            add_retur_request.total_dpp_retur = total_dpp_retur_request
            add_retur_request.total_ppn_retur = total_ppn_retur_request
            add_retur_request.total_retur = total_retur_request
            self.add(add_retur_request).flush()

        self.commit()

        return {"status": "success","message": "Request retur berhasil dibuat"}, 200

    @handle_error
    def checkReturRequest(self):
        id_sales_order = self.req('id_sales_order')

        if not id_sales_order:
            raise nonServerErrorException("ID Sales Order harus diisi")

        retur_request = self._safe_query_rows(
            """
            SELECT
                retur_request.id_request,
                retur_request.id_sales_order,
                retur_request.kode_request,
                retur_request.kode_kpr,
                retur_request.no_cn,
                retur_request.tanggal_request,
                retur_request.status_request,
                retur_request_detail.id_request_detail,
                retur_request_detail.id_produk,
                retur_request_detail.alasan_retur,
                retur_request_detail.pieces_retur,
                retur_request_detail.box_retur,
                retur_request_detail.karton_retur,
                retur_request_detail.pieces_good_diajukan,
                retur_request_detail.box_good_diajukan,
                retur_request_detail.karton_good_diajukan
            FROM retur_request
            JOIN retur_request_detail
                 ON retur_request.id_request = retur_request_detail.id_request
            WHERE id_sales_order = :id_sales_order
            ORDER BY retur_request.id_request DESC, retur_request_detail.id_request_detail DESC
            """,
            {"id_sales_order": id_sales_order}
        )

        if not retur_request:
            return {"status": "not_found", "message": "Tidak ada request retur untuk sales order ini"}, 404

        for item in retur_request:
            item["status_request_label"] = self._retur_status_label(item.get("status_request"))

        return retur_request


    def __createNotaRetur(self):
        self.query().setRawQuery(
            """
                    UPDATE 
                    faktur 
                    SET 
                    perubahan_ke = :perubahan_ke 
                    WHERE id = :id
                """
        ).bindparams(
            {
                "id": self.req("id"),
                "perubahan_ke": 1,
            }
        ).execute()

        self.query().setRawQuery(
            """
                    UPDATE sales_order
                    SET status_order = 8
                    WHERE id = :id_sales_order
                """
        ).bindparams({
            "id_sales_order": self.req("id_sales_order")
        }).execute()

        (
            self.query()
            .setRawQuery(
                """
                    INSERT INTO 
                    faktur
                    (no_faktur, id_sales_order, status_faktur, jenis_faktur, total_penjualan, 
                    total_dana_diterima, tanggal_retur_pengajuan)
                    VALUES
                    (:no_faktur, :id_sales_order, :status_faktur, 'retur', :total_penjualan, 
                    :total_dana_diterima, :tanggal_retur_pengajuan)
                """
            )
            .bindparams(
                {
                    "no_faktur": self.req("no_faktur"),
                    "id_sales_order": self.req("id_sales_order"),
                    "total_penjualan": self.req("total_penjualan"),
                    "status_faktur": 0,
                    "total_dana_diterima": self.req("total_dana_diterima") or 0,
                    "tanggal_retur_pengajuan": date_now()
                }
            )
            .execute()
        )

        for product in self.req("products"):
            self.query().setRawQuery(
                """
                        UPDATE sales_order_detail 
                        SET 
                        pieces_retur = :pieces_retur,
                        box_retur = :box_retur,
                        karton_retur = :karton_retur,
                        keterangan_retur = :keterangan_retur
                        WHERE id = :id_sales_order_detail
                    """
            ).bindparams(
                {
                    "id_sales_order_detail": product["id_sales_order_detail"],
                    "pieces_retur": product["pieces_retur"],
                    "box_retur": product["box_retur"],
                    "karton_retur": product["karton_retur"],
                    "keterangan_retur": product["keterangan_retur"],
                }
            ).execute()

        return "success"

    @handle_error
    def lewatiSalesOrder(self):
        return (
            self.query().setRawQuery(
                """
                    INSERT INTO draft_sales 
                    (id_plafon, keterangan) 
                    VALUES
                    (:id_plafon, :keterangan)
                    RETURNING id
                """
            ).bindparams({
                "id_plafon": self.req("id_plafon"),
                "keterangan": self.req("keterangan")
            }).execute().getReturning()
        )
