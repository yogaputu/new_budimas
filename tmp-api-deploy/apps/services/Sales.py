from datetime import datetime, timedelta
from apps.conn2 import native_db
from sqlalchemy import text

import holidays

from .User import User
from calendar import monthrange
from . import BaseServices
from apps.handler import handle_error, nonServerErrorException
from collections import defaultdict
import math
import threading
import bcrypt
from apps.lib.helper import GetWhereBindParams
from apps.services.BaseSales import BaseSales
from apps.services.User import UserService
from flask import request
from apps.lib.schema_guard import require_table_columns
from apps.services.SupervisorAudit import write_supervisor_audit

from ..lib.helper import get_day_number_for_date, get_week_number_for_date, is_holiday, get_current_day_number, \
    get_week_number_cycle, get_now_datetime


class Sales(BaseSales):
    _monthly_target_schema_ready = False
    _monthly_target_schema_lock = threading.Lock()

    def _ensure_monthly_target_table(self):
        if Sales._monthly_target_schema_ready:
            return

        with Sales._monthly_target_schema_lock:
            if Sales._monthly_target_schema_ready:
                return

            try:
                require_table_columns(
                    native_db.session,
                    "sales_target_monthly",
                    [
                        "id",
                        "id_sales",
                        "id_user",
                        "id_cabang",
                        "tahun",
                        "bulan",
                        "target_kunjungan",
                        "target_omset",
                        "notes",
                        "created_by",
                        "updated_by",
                        "created_at",
                        "updated_at",
                    ],
                    "tools/migrations/20260519_runtime_schema_manual.sql",
                )
                Sales._monthly_target_schema_ready = True
            except Exception:
                native_db.session.rollback()
                raise

    def _get_logged_user(self):
        authorization = request.headers.get("Authorization", "")
        token = authorization.split(" ", 1)[1].strip() if authorization.startswith("Bearer ") else None

        if not token:
            return None

        with native_db.session.begin():
            row = native_db.session.execute(
                text("""
                    SELECT id, nama, id_cabang, id_jabatan
                    FROM users
                    WHERE tokens = :token
                    LIMIT 1
                """),
                {"token": token},
            ).mappings().first()

        return dict(row) if row else None

    def _password_matches(self, plain_password, stored_password):
        if stored_password is None:
            return False

        plain_password = plain_password or ""
        stored_text = stored_password.decode('utf-8') if isinstance(stored_password, bytes) else str(stored_password)

        try:
            return bcrypt.checkpw(
                plain_password.encode('utf-8'),
                stored_text.encode('utf-8')
            )
        except ValueError:
            return plain_password == stored_text

    @handle_error
    def get_token_by_credential(self):
        email = self.req("email")
        password = self.req("password")

        getInfo = (
            self.query()
            .setRawQuery(
            """
                SELECT 
                users.tokens AS token, 
                users.id AS id_user,
                sales.id AS id_sales,
                sales.id_tipe AS id_tipe_sales,
                st.nama AS nama_tipe_sales,
                users.nama AS nama_user,
                users.email AS user_email,
                users.password
                FROM 
                users 
                JOIN sales ON users.id = sales.id_user 
                LEFT JOIN sales_tipe st ON st.id = sales.id_tipe
                WHERE users.email = :email
            """
            )
            .bindparams({"email": email})
            .execute()
            .fetchone()
            .result
        )

        if not getInfo:
            raise nonServerErrorException('Email salah atau tidak ada', 403)

        if not self._password_matches(password, getInfo.get("password")):
            raise nonServerErrorException('Password salah', 403)

        return getInfo

    @handle_error
    def salesInfo(self, userid, tahun=None, bulan=None):
        isRange = tahun and bulan
        now = get_now_datetime()
        current_date = now.strftime("%Y-%m-%d")
        last_update = now.strftime("%Y-%m-%d %H:%M:%S")

        # Fungsi pembantu untuk menangani response List atau Dict
        def safe_extract(response, key, default=0):
            if isinstance(response, list): 
                return response[0].get(key, default) if response else default
            if isinstance(response, dict): 
                res = response.get('result')
                if isinstance(res, list):
                    return res[0].get(key, default) if res else default
                if isinstance(res, dict):
                    return res.get(key, default)
            return default

        data_dict = {"userid": userid}
        
        if isRange:
            data_dict["from_date"] = f"{tahun}-{bulan}-01"
            last_day = monthrange(int(tahun), int(bulan))[1]
            data_dict["to_date"] = f"{tahun}-{bulan}-{last_day}"
        else:
            data_dict["tanggal_order"] = current_date

        # 1. Base query & Clauses
        baseQuery = " FROM plafon JOIN sales_order ON sales_order.id_plafon = plafon.id "
        clause = {"userid": "plafon.id_user = :userid"}
        tanggal_order_clause = "sales_order.tanggal_order BETWEEN :from_date AND :to_date" if isRange else "sales_order.tanggal_order = :tanggal_order"

        where, _ = GetWhereBindParams(data_dict, clause)
        where_clause = f" WHERE {tanggal_order_clause} AND {where}" if where else f" WHERE {tanggal_order_clause}"

        # 2. Eksekusi Query - Total Order
        queryTotalOrder = f"SELECT count(sales_order.id) as count {baseQuery} {where_clause}"
        resTotalOrder = self.query().setRawQuery(queryTotalOrder).bindparams(data_dict).execute().fetchall().get()
        totalOrderCount = safe_extract(resTotalOrder, 'count')

        # 3. Eksekusi Query - Total Customer Order
        queryCustomerOrder = f"SELECT COUNT(DISTINCT plafon.id_customer) as count {baseQuery} {where_clause}"
        resCustomerOrder = self.query().setRawQuery(queryCustomerOrder).bindparams(data_dict).execute().fetchall().get()
        totalCustomerOrderCount = safe_extract(resCustomerOrder, 'count')

        # 4. Kunjungan setup
        extra_clause = self.GetSchedule()
        tanggal_kunjungan_clause = "sales_kunjungan.tanggal BETWEEN :from_date AND :to_date" if isRange else "sales_kunjungan.tanggal = :tanggal_order"
        
        # 5. Belum Kunjungan
        where_belumKunjungan_clause = f" WHERE {tanggal_kunjungan_clause} AND {where} AND ({extra_clause})"
        queryKunjungan = f"""
                SELECT count(distinct plafon.id_customer) as count
                FROM plafon
                JOIN sales_kunjungan ON sales_kunjungan.id_plafon = plafon.id
                JOIN plafon_jadwal ON plafon_jadwal.id = sales_kunjungan.id_plafon_jadwal
                {where_belumKunjungan_clause}
        """
        resBelum = self.query().setRawQuery(queryKunjungan).bindparams(data_dict).execute().fetchone().get()
        belumKunjungan = safe_extract(resBelum, 'count')

        # 6. Sudah Kunjungan
        data_dict_sudah = {**data_dict, "status_1": 1, "status_2": 2}
        querySudahKunjungan = f"""
                SELECT count(distinct plafon.id_customer) as count
                FROM plafon
                JOIN sales_kunjungan ON sales_kunjungan.id_plafon = plafon.id 
                JOIN plafon_jadwal ON plafon_jadwal.id = sales_kunjungan.id_plafon_jadwal
                WHERE {tanggal_kunjungan_clause} AND {where} 
                AND sales_kunjungan.status IN (:status_1, :status_2)
                AND ({extra_clause})
        """
        resSudah = self.query().setRawQuery(querySudahKunjungan).bindparams(data_dict_sudah).execute().fetchone().get()
        sudahKunjungan = safe_extract(resSudah, 'count')

        # 7. Total Transaksi (Rupiah)
        queryTotalTransaksi = f"""
                SELECT SUM(sales_order_detail.subtotalorder) as sum
                {baseQuery}
                JOIN sales_order_detail ON sales_order_detail.id_sales_order = sales_order.id
                {where_clause}
        """
        resTransaksi = self.query().setRawQuery(queryTotalTransaksi).bindparams(data_dict).execute().fetchone().get()
        totalTransaksiVal = safe_extract(resTransaksi, 'sum')

        # 8. Total Pencapaian (Setoran)
        queryTotalPencapaian = f"""
                SELECT sum(setoran_customer.jumlah_setoran) as sum
                {baseQuery}
                JOIN setoran_customer ON setoran_customer.id_sales_order = sales_order.id
                {where_clause}
        """
        resPencapaian = self.query().setRawQuery(queryTotalPencapaian).bindparams(data_dict).execute().fetchone().get()
        totalPencapaianVal = safe_extract(resPencapaian, 'sum')

        # 9. Total Call Plan (Jika isRange)
        totalCallPlanVal = 0
        if isRange:
            where_kunj_clause = f" WHERE {tanggal_kunjungan_clause} AND {where}"
            queryTotalCallPlan = f"""
                        SELECT count(distinct plafon.id_customer) as count
                        FROM plafon
                        JOIN sales_kunjungan ON sales_kunjungan.id_plafon = plafon.id
                        JOIN plafon_jadwal ON plafon_jadwal.id = sales_kunjungan.id_plafon_jadwal
                        {where_kunj_clause}
            """
            resCP = self.query().setRawQuery(queryTotalCallPlan).bindparams(data_dict).execute().fetchone().get()
            totalCallPlanVal = safe_extract(resCP, 'count')

        return {
            "totalOrder": totalOrderCount,
            "totalCustomerOrder": totalCustomerOrderCount,
            "belumKunjungan": belumKunjungan,
            "sudahBerkunjung": sudahKunjungan,
            "updateTerakhir": last_update,
            "totalTransaksi": totalTransaksiVal,
            "totalCallPlan": totalCallPlanVal,
            "totalPencapaian": totalPencapaianVal,
        }

    def calculate_call_plan(self, userid, tahun, bulan):
        """
        Menghitung jadwal call plan untuk sales berdasarkan jadwal yang ada di plafon_jadwal
        """
        tahun = int(tahun)
        bulan = int(bulan)

        # Dapatkan semua jadwal dari plafon_jadwal untuk user tertentu
        jadwal_query = self.query().setRawQuery(
            """
            SELECT 
                pj.id, pj.id_plafon, pj.id_tipe_kunjungan, pj.id_hari, pj.id_minggu, p.id_customer,
                c.nama as customer_name
            FROM plafon_jadwal pj 
            LEFT JOIN plafon p ON pj.id_plafon = p.id
            LEFT JOIN customer c ON p.id_customer = c.id
            WHERE p.id_user = :userid
            """
        ).bindparams({"userid": userid}).execute().fetchall().get()

        if not jadwal_query:
            return 0

        # Kombinasi minggu
        week_combo = {
            5: [1, 2], 6: [1, 3], 7: [1, 4],
            8: [2, 3], 9: [2, 4], 10: [3, 4]
        }

        total_call_plan = 0
        last_day = monthrange(tahun, bulan)[1]

        # Simulasi untuk setiap hari dalam bulan
        for day in range(1, last_day + 1):
            current_date = datetime(tahun, bulan, day)

            # Skip hari libur
            # if is_holiday(current_date):
            #     continue

            # Dapatkan nomor hari dan minggu
            day_number = get_day_number_for_date(current_date)
            week_number = get_week_number_for_date(current_date)

            # Proses jadwal untuk hari ini
            for jadwal in jadwal_query:
                week = int(jadwal["id_minggu"])
                day = int(jadwal["id_hari"])

                if (week == week_number or week == 11) and day == day_number:
                    total_call_plan += 1
                elif week in week_combo:
                    if any(combo_week == week_number and day == day_number for combo_week in week_combo[week]):
                        total_call_plan += 1

        return total_call_plan

    @handle_error
    def getSaleses(self):
        saleses = (
            self.query()
            .setRawQuery(
            """
                SELECT * FROM sales JOIN users ON sales.id_user = users.id
            """
            )
            .execute()
            .fetchall()
            .get()
        )

        return saleses
    
    @handle_error
    def getSales(self, id_sales):
        # Ambil output dari DB
        response = (
            self.query()
            .setRawQuery("""
                SELECT sales.*, jabatan.nama AS nama_jabatan, cabang.nama AS nama_cabang
                FROM sales 
                JOIN users ON sales.id_user = users.id
                JOIN jabatan ON jabatan.id = users.id_jabatan 
                JOIN cabang ON cabang.id = users.id_cabang
                WHERE sales.id = :id_sales
            """)
            .bindparams({"id_sales": id_sales})
            .execute()
            .fetchall()
            .get()
        )

        # 1. Ambil list dari dalam key 'result'
        data_list = response.get('result', [])

        # 2. Cek apakah datanya ada sebelum akses indeks [0]
        if not data_list:
            return {"status": "error", "message": "Sales tidak ditemukan"}, 404

        sales_data = data_list[0]

        # 3. Panggil UserService (pastikan sudah di-import)
        # from apps.services.User import UserService
        return UserService().getUser(sales_data["id_user"], "sales", sales_data)
    
    @handle_error
    def history(self, id_plafon, jenis_faktur):
        return (
            self.query()
            .setRawQuery(
                """
                    SELECT * FROM sales_order 
                    JOIN faktur 
                    ON 
                    sales_order.id = faktur.id_sales_order 
                    WHERE 
                    id_plafon = :id_plafon
                    AND
                    jenis_faktur = :jenis_faktur
                """
            )
            .bindparams(
                {
                    "id_plafon": id_plafon, 
                    "jenis_faktur": jenis_faktur
                }
            )
            .execute()
            .fetchall()
            .get()
        )
    
    @handle_error
    def getOmset(self):
        # Input validation and parsing
        user_id = self.req('user_id')
        if not user_id:
            raise ValueError("user_id is required")

        tahun = self.req('tahun')
        bulan = self.req('bulan')
        if not (tahun and bulan):
            raise ValueError("tahun and bulan are required")
        
        tahun, bulan = int(tahun), int(bulan)
        tanggal = int(self.req('tanggal') or monthrange(tahun, bulan)[1])
        
        jenis_faktur = self.req('jenis_faktur') or 'penjualan'
        status_faktur = self.req('status_faktur')
        
        # Date formatting
        from_date = f"{tahun:04d}-{bulan:02d}-01"
        to_date = f"{tahun:04d}-{bulan:02d}-{tanggal:02d}"
        
        # Status condition
        status_condition = "faktur.status_faktur = :status_faktur" if status_faktur else "faktur.status_faktur in (0, 1, 2, 3, 4, 5)"
        
        # Query parameters
        params = {
            "user_id": user_id,
            "from_date": from_date,
            "to_date": to_date,
            "jenis_faktur": jenis_faktur,
        }
        if status_faktur:
            params["status_faktur"] = status_faktur
        
        # Query execution
        query = f"""
            SELECT faktur.total_penjualan AS omset, sales_order.tanggal_order AS tanggal_order
            FROM plafon
            JOIN users ON users.id = plafon.id_user
            JOIN sales_order ON sales_order.id_plafon = plafon.id
            JOIN faktur ON faktur.id_sales_order = sales_order.id
            WHERE plafon.id_user = :user_id
            AND faktur.jenis_faktur = :jenis_faktur
            AND {status_condition}
            AND sales_order.tanggal_order BETWEEN :from_date AND :to_date
        """
        
        # Query execution
        response = (
            self.query()
            .setRawQuery(query)
            .bindparams(params)
            .execute()
            .fetchall()
            .get()
        )
        
        # --- PERBAIKAN DI SINI ---
        # Ambil list data dari dalam key 'result'
        charts_data = response.get('result', [])
        
        # Process results
        result_dict = defaultdict(lambda: {"omset": 0})
        
        # Sekarang looping ini aman karena charts_data sudah berbentuk LIST
        for val in charts_data:
            tanggal = str(val["tanggal_order"]) # Pastikan jadi string untuk key dict
            omset = val["omset"] or 0 # Antisipasi jika omset None
            
            result_dict[tanggal]["tanggal"] = tanggal
            result_dict[tanggal]["omset"] += omset
            
        result = list(result_dict.values())
        return result

    @handle_error
    def getMonthlyTargets(self):
        self._ensure_monthly_target_table()

        now = get_now_datetime()
        tahun = int(self.req('tahun') or now.year)
        bulan = int(self.req('bulan') or now.month)
        id_principal = self.req('id_principal')
        branch_filter = self.req('id_cabang')
        logged_user = self._get_logged_user() or {}
        id_cabang = int(branch_filter) if str(branch_filter or '').isdigit() else logged_user.get('id_cabang')

        params = {
            "tahun": tahun,
            "bulan": bulan,
            "from_date": f"{tahun:04d}-{bulan:02d}-01",
            "to_date": f"{tahun:04d}-{bulan:02d}-{monthrange(tahun, bulan)[1]:02d}",
        }

        where_clauses = []
        if id_cabang:
            where_clauses.append("users.id_cabang = :id_cabang")
            params["id_cabang"] = int(id_cabang)

        if str(id_principal or '').isdigit():
            where_clauses.append("(sales.id_principal = :id_principal OR spa.id_principal = :id_principal)")
            params["id_principal"] = int(id_principal)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        rows = self.query().setRawQuery(f"""
            WITH sales_source AS (
                SELECT
                    sales.id AS id_sales,
                    sales.id_user,
                    users.nama AS nama_sales,
                    users.id_cabang,
                    cabang.nama AS nama_cabang,
                    COALESCE(sales_detail.kode_sales, '') AS kode_sales,
                    COALESCE(
                        STRING_AGG(DISTINCT principal.nama, ', ') FILTER (WHERE principal.nama IS NOT NULL),
                        '-'
                    ) AS nama_principals
                FROM sales
                INNER JOIN users ON users.id = sales.id_user
                LEFT JOIN cabang ON cabang.id = users.id_cabang
                LEFT JOIN sales_detail ON sales_detail.id_sales = sales.id
                LEFT JOIN sales_principal_assignment spa ON spa.id_sales = sales.id
                LEFT JOIN principal ON principal.id = spa.id_principal
                {where_sql}
                GROUP BY sales.id, sales.id_user, users.nama, users.id_cabang, cabang.nama, sales_detail.kode_sales
            ),
            actual_kunjungan AS (
                SELECT
                    p.id_user,
                    COUNT(sk.id) FILTER (WHERE sk.status IN (1, 2)) AS actual_kunjungan
                FROM sales_kunjungan sk
                INNER JOIN plafon p ON p.id = sk.id_plafon
                WHERE sk.tanggal BETWEEN :from_date AND :to_date
                GROUP BY p.id_user
            ),
            actual_omset AS (
                SELECT
                    plafon.id_user,
                    COALESCE(SUM(faktur.total_penjualan), 0) AS actual_omset
                FROM plafon
                INNER JOIN sales_order ON sales_order.id_plafon = plafon.id
                INNER JOIN faktur ON faktur.id_sales_order = sales_order.id
                WHERE faktur.jenis_faktur = 'penjualan'
                  AND faktur.status_faktur IN (0, 1, 2, 3, 4, 5)
                  AND sales_order.tanggal_order BETWEEN :from_date AND :to_date
                GROUP BY plafon.id_user
            )
            SELECT
                ss.id_sales,
                ss.id_user,
                ss.nama_sales,
                ss.id_cabang,
                ss.nama_cabang,
                ss.kode_sales,
                ss.nama_principals,
                COALESCE(stm.target_kunjungan, 0) AS target_kunjungan,
                COALESCE(stm.target_omset, 0) AS target_omset,
                COALESCE(stm.notes, '') AS notes,
                COALESCE(ak.actual_kunjungan, 0) AS actual_kunjungan,
                COALESCE(ao.actual_omset, 0) AS actual_omset
            FROM sales_source ss
            LEFT JOIN sales_target_monthly stm
                ON stm.id_sales = ss.id_sales
               AND stm.tahun = :tahun
               AND stm.bulan = :bulan
            LEFT JOIN actual_kunjungan ak
                ON ak.id_user = ss.id_user
            LEFT JOIN actual_omset ao
                ON ao.id_user = ss.id_user
            ORDER BY ss.nama_sales ASC
        """).bindparams(params).execute().fetchall().get()

        data = rows.get('result', []) if isinstance(rows, dict) else rows
        normalized = []
        for item in data or []:
            visit_achievement = 0
            omset_achievement = 0
            target_kunjungan = int(item.get('target_kunjungan') or 0)
            actual_kunjungan = int(item.get('actual_kunjungan') or 0)
            target = float(item.get('target_omset') or 0)
            actual = float(item.get('actual_omset') or 0)
            if target_kunjungan > 0:
                visit_achievement = round((actual_kunjungan / target_kunjungan) * 100, 2)
            if target > 0:
                omset_achievement = round((actual / target) * 100, 2)

            normalized.append({
                **item,
                "target_kunjungan": target_kunjungan,
                "actual_kunjungan": actual_kunjungan,
                "target_omset": target,
                "actual_omset": actual,
                "visit_achievement_percent": visit_achievement,
                "achievement_percent": omset_achievement,
            })

        return {
            "tahun": tahun,
            "bulan": bulan,
            "id_cabang": id_cabang,
            "rows": normalized,
            "summary": {
                "sales_count": len(normalized),
                "total_target_kunjungan": sum(item["target_kunjungan"] for item in normalized),
                "total_actual_kunjungan": sum(item["actual_kunjungan"] for item in normalized),
                "total_target": sum(item["target_omset"] for item in normalized),
                "total_actual": sum(item["actual_omset"] for item in normalized),
            }
        }

    @handle_error
    def saveMonthlyTargets(self):
        self._ensure_monthly_target_table()

        now = get_now_datetime()
        tahun = int(self.req('tahun') or now.year)
        bulan = int(self.req('bulan') or now.month)
        rows = self.req('rows') or []
        logged_user = self._get_logged_user() or {}

        if isinstance(rows, str):
            import json
            rows = json.loads(rows)

        if not isinstance(rows, list) or not rows:
            raise nonServerErrorException("Data target sales belum dikirim", 400)

        target_keys = [
            int(row.get('id_sales'))
            for row in rows
            if str(row.get('id_sales') or '').isdigit()
        ]
        before_rows = []
        if target_keys:
            target_params = {f"id_sales_{idx}": value for idx, value in enumerate(target_keys)}
            target_placeholders = ", ".join(f":id_sales_{idx}" for idx in range(len(target_keys)))
            with native_db.engine.connect() as conn:
                before_rows = conn.execute(text(f"""
                    SELECT
                        id_sales,
                        id_user,
                        id_cabang,
                        tahun,
                        bulan,
                        target_kunjungan,
                        target_omset,
                        notes
                    FROM sales_target_monthly
                    WHERE tahun = :tahun
                      AND bulan = :bulan
                      AND id_sales IN ({target_placeholders})
                """), {
                    "tahun": tahun,
                    "bulan": bulan,
                    **target_params,
                }).mappings().all()

        saved = 0
        with native_db.session.begin():
            for row in rows:
                id_sales = row.get('id_sales')
                id_user = row.get('id_user')
                id_cabang = row.get('id_cabang')
                target_kunjungan = int(row.get('target_kunjungan') or 0)
                target_omset = float(row.get('target_omset') or 0)
                notes = row.get('notes') or ''

                if not str(id_sales or '').isdigit():
                    continue

                native_db.session.execute(text("""
                    INSERT INTO sales_target_monthly (
                        id_sales, id_user, id_cabang, tahun, bulan, target_kunjungan, target_omset, notes, created_by, updated_by
                    ) VALUES (
                        :id_sales, :id_user, :id_cabang, :tahun, :bulan, :target_kunjungan, :target_omset, :notes, :created_by, :updated_by
                    )
                    ON CONFLICT (id_sales, tahun, bulan)
                    DO UPDATE SET
                        id_user = EXCLUDED.id_user,
                        id_cabang = EXCLUDED.id_cabang,
                        target_kunjungan = EXCLUDED.target_kunjungan,
                        target_omset = EXCLUDED.target_omset,
                        notes = EXCLUDED.notes,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                """), {
                    "id_sales": int(id_sales),
                    "id_user": int(id_user) if str(id_user or '').isdigit() else None,
                    "id_cabang": int(id_cabang) if str(id_cabang or '').isdigit() else None,
                    "tahun": tahun,
                    "bulan": bulan,
                    "target_kunjungan": target_kunjungan,
                    "target_omset": target_omset,
                    "notes": notes,
                    "created_by": logged_user.get('id'),
                    "updated_by": logged_user.get('id'),
                })
                saved += 1

        after_rows = []
        if target_keys:
            target_params = {f"id_sales_{idx}": value for idx, value in enumerate(target_keys)}
            target_placeholders = ", ".join(f":id_sales_{idx}" for idx in range(len(target_keys)))
            with native_db.engine.connect() as conn:
                after_rows = conn.execute(text(f"""
                    SELECT
                        id_sales,
                        id_user,
                        id_cabang,
                        tahun,
                        bulan,
                        target_kunjungan,
                        target_omset,
                        notes
                    FROM sales_target_monthly
                    WHERE tahun = :tahun
                      AND bulan = :bulan
                      AND id_sales IN ({target_placeholders})
                """), {
                    "tahun": tahun,
                    "bulan": bulan,
                    **target_params,
                }).mappings().all()

        id_cabang_audit = None
        for row in rows:
            if str(row.get('id_cabang') or '').isdigit():
                id_cabang_audit = int(row.get('id_cabang'))
                break
        write_supervisor_audit(
            action="update_sales_target",
            module="setting-target-sales",
            target={
                "target_type": "sales_target_monthly",
                "target_id": f"{tahun}-{bulan}",
                "target_code": f"{tahun}-{bulan}",
                "id_cabang": id_cabang_audit,
            },
            before=[dict(row) for row in before_rows],
            after=[dict(row) for row in after_rows],
            note=self.req("note") or self.req("catatan") or f"Update target sales {bulan}/{tahun}",
            id_user=logged_user.get('id'),
        )

        return {
            "status": "success",
            "saved_rows": saved,
            "tahun": tahun,
            "bulan": bulan,
        }, 200

    @handle_error
    def getDoiAnalysis(self):
        logged_user = self._get_logged_user() or {}
        today = get_now_datetime().date()

        default_from = today - timedelta(days=29)
        from_date = self.req('tanggal_awal') or default_from.strftime('%Y-%m-%d')
        to_date = self.req('tanggal_akhir') or today.strftime('%Y-%m-%d')
        branch_filter = self.req('id_cabang')
        company_filter = self.req('id_perusahaan')
        principal_filter = self.req('id_principal')
        search = str(self.req('search') or '').strip().lower()

        id_cabang = int(branch_filter) if str(branch_filter or '').isdigit() else logged_user.get('id_cabang')
        id_perusahaan = int(company_filter) if str(company_filter or '').isdigit() else None
        id_principal = int(principal_filter) if str(principal_filter or '').isdigit() else None

        start_date = datetime.strptime(from_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(to_date, '%Y-%m-%d').date()
        if start_date > end_date:
            raise nonServerErrorException("Tanggal awal tidak boleh lebih besar dari tanggal akhir", 400)

        total_days = max(1, (end_date - start_date).days + 1)

        stock_filters = []
        movement_filters = [
            "sales_order.tanggal_order BETWEEN :from_date AND :to_date"
        ]
        params = {
            "from_date": from_date,
            "to_date": to_date,
        }

        if id_cabang:
            stock_filters.append("stok.cabang_id = :id_cabang")
            movement_filters.append("sales_order.id_cabang = :id_cabang")
            params["id_cabang"] = int(id_cabang)

        if id_perusahaan:
            stock_filters.append("principal.id_perusahaan = :id_perusahaan")
            movement_filters.append("principal.id_perusahaan = :id_perusahaan")
            params["id_perusahaan"] = int(id_perusahaan)

        if id_principal:
            stock_filters.append("produk.id_principal = :id_principal")
            movement_filters.append("produk.id_principal = :id_principal")
            params["id_principal"] = int(id_principal)

        if search:
            stock_filters.append("""
                (
                    LOWER(produk.nama) LIKE :search
                    OR LOWER(COALESCE(produk.kode_sku, '')) LIKE :search
                    OR LOWER(COALESCE(principal.nama, '')) LIKE :search
                )
            """)
            params["search"] = f"%{search}%"

        stock_where = f"WHERE {' AND '.join(stock_filters)}" if stock_filters else ""
        movement_where = f"WHERE {' AND '.join(movement_filters)}"

        response = (
            self.query()
            .setRawQuery(f"""
                WITH stock_source AS (
                    SELECT
                        stok.id AS stok_id,
                        stok.cabang_id,
                        cabang.nama AS nama_cabang,
                        stok.produk_id,
                        produk.kode_sku,
                        produk.nama AS nama_produk,
                        produk.id_principal,
                        principal.id_perusahaan,
                        principal.nama AS nama_principal,
                        COALESCE(stok.jumlah_ready, 0) AS stok_ready,
                        COALESCE(stok.jumlah_good, 0) AS stok_good,
                        COALESCE(stok.jumlah_bad, 0) AS stok_bad,
                        GREATEST(COALESCE(NULLIF(produk.isiperbox, 0), 1), 1) AS isi_per_box,
                        GREATEST(COALESCE(NULLIF(produk.isiperkarton, 0), 1), 1) AS isi_per_karton
                    FROM stok
                    INNER JOIN produk ON produk.id = stok.produk_id
                    LEFT JOIN principal ON principal.id = produk.id_principal
                    LEFT JOIN cabang ON cabang.id = stok.cabang_id
                    {stock_where}
                ),
                movement_source AS (
                    SELECT
                        sales_order.id_cabang AS cabang_id,
                        sales_order_detail.id_produk AS produk_id,
                        SUM(
                            CASE
                                WHEN
                                    COALESCE(sales_order_detail.pieces_delivered, 0)
                                    + COALESCE(sales_order_detail.box_delivered, 0)
                                    + COALESCE(sales_order_detail.karton_delivered, 0) > 0
                                THEN
                                    COALESCE(sales_order_detail.pieces_delivered, 0)
                                    + (COALESCE(sales_order_detail.box_delivered, 0) * GREATEST(COALESCE(NULLIF(produk.isiperbox, 0), 1), 1))
                                    + (COALESCE(sales_order_detail.karton_delivered, 0) * GREATEST(COALESCE(NULLIF(produk.isiperkarton, 0), 1), 1))
                                ELSE
                                    COALESCE(sales_order_detail.pieces_order, 0)
                                    + (COALESCE(sales_order_detail.box_order, 0) * GREATEST(COALESCE(NULLIF(produk.isiperbox, 0), 1), 1))
                                    + (COALESCE(sales_order_detail.karton_order, 0) * GREATEST(COALESCE(NULLIF(produk.isiperkarton, 0), 1), 1))
                            END
                        ) AS total_keluar_pcs
                    FROM sales_order_detail
                    INNER JOIN sales_order ON sales_order.id = sales_order_detail.id_sales_order
                    INNER JOIN produk ON produk.id = sales_order_detail.id_produk
                    LEFT JOIN principal ON principal.id = produk.id_principal
                    {movement_where}
                    GROUP BY sales_order.id_cabang, sales_order_detail.id_produk
                )
                SELECT
                    stock_source.stok_id,
                    stock_source.cabang_id,
                    stock_source.nama_cabang,
                    stock_source.produk_id,
                    stock_source.kode_sku,
                    stock_source.nama_produk,
                    stock_source.id_principal,
                    stock_source.id_perusahaan,
                    stock_source.nama_principal,
                    stock_source.stok_ready,
                    stock_source.stok_good,
                    stock_source.stok_bad,
                    COALESCE(movement_source.total_keluar_pcs, 0) AS total_keluar_pcs
                FROM stock_source
                LEFT JOIN movement_source
                    ON movement_source.cabang_id = stock_source.cabang_id
                   AND movement_source.produk_id = stock_source.produk_id
                ORDER BY stock_source.nama_principal ASC, stock_source.nama_produk ASC
            """)
            .bindparams(params)
            .execute()
            .fetchall()
            .get()
        )

        rows = response.get('result', []) if isinstance(response, dict) else response

        rules = []
        try:
            rule_response = (
                self.query()
                .setRawQuery("""
                    SELECT
                        id,
                        id_cabang,
                        id_perusahaan,
                        id_principal,
                        principal_group,
                        target_doi_hari,
                        lead_time_hari,
                        moq_unit,
                        kelipatan_qty,
                        top_hari,
                        target_sell_in,
                        target_sell_out
                    FROM principal_special_rule
                    WHERE COALESCE(is_active, TRUE) = TRUE
                """)
                .execute()
                .fetchall()
                .get()
            )
            rules = rule_response.get('result', []) if isinstance(rule_response, dict) else rule_response
        except Exception:
            # Aturan principal adalah master tambahan. Kalau migration belum ada,
            # DOI tetap berjalan memakai threshold lama/default.
            rules = []

        def find_rule(row):
            row_branch = str(row.get("cabang_id") or "")
            row_company = str(row.get("id_perusahaan") or "")
            row_principal = str(row.get("id_principal") or "")
            row_principal_name = str(row.get("nama_principal") or "").lower()

            def score(rule):
                if rule.get("id_cabang") and str(rule.get("id_cabang")) != row_branch:
                    return -1
                if rule.get("id_perusahaan") and str(rule.get("id_perusahaan")) != row_company:
                    return -1
                if rule.get("id_principal") and str(rule.get("id_principal")) != row_principal:
                    return -1

                value = 0
                if rule.get("id_cabang"):
                    value += 4
                if rule.get("id_perusahaan"):
                    value += 4
                if rule.get("id_principal"):
                    value += 8

                group = str(rule.get("principal_group") or "").strip().lower()
                if group:
                    if group in row_principal_name:
                        value += 2
                    elif not rule.get("id_principal"):
                        return -1

                return value

            candidates = [(score(rule), rule) for rule in rules or []]
            candidates = [item for item in candidates if item[0] >= 0]
            if not candidates:
                return None
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]

        normalized = []
        doi_values = []
        summary = {
            "total_items": 0,
            "understock": 0,
            "healthy": 0,
            "overstock": 0,
            "no_movement": 0,
        }

        for row in rows or []:
            rule = find_rule(row) or {}
            target_doi = int(float(rule.get("target_doi_hari") or 30))
            target_doi = target_doi if target_doi > 0 else 30
            lower_target = max(7, round(target_doi * 0.5, 1))
            stok_ready = float(row.get('stok_ready') or 0)
            total_keluar = float(row.get('total_keluar_pcs') or 0)
            avg_daily_sales = round(total_keluar / total_days, 2) if total_keluar > 0 else 0.0
            lead_time_hari = int(float(rule.get("lead_time_hari") or 0))
            moq_unit = int(float(rule.get("moq_unit") or 0))
            kelipatan_qty = int(float(rule.get("kelipatan_qty") or 0))
            recommended_purchase_qty = 0

            if avg_daily_sales <= 0:
                doi_value = None
                status = 'No Movement'
                recommendation = 'Penjualan belum bergerak. Cek kebutuhan pasar, display, dan evaluasi stok lambat.'
                status_tone = 'slate'
            else:
                doi_value = round(stok_ready / avg_daily_sales, 1)
                doi_values.append(doi_value)

                if doi_value < lower_target:
                    status = 'Understock'
                    recommendation = f'Stok di bawah target minimal ({lower_target} hari). Prioritaskan replenishment sesuai MOQ/kelipatan principal.'
                    status_tone = 'rose'
                elif doi_value <= target_doi:
                    status = 'Healthy'
                    recommendation = f'Stok masih sehat terhadap target DOI principal {target_doi} hari.'
                    status_tone = 'emerald'
                else:
                    status = 'Overstock'
                    recommendation = f'Stok melewati target DOI principal {target_doi} hari. Dorong sell-out, promo, atau redistribusi.'
                    status_tone = 'amber'

                target_stock = avg_daily_sales * (target_doi + lead_time_hari)
                raw_replenishment = max(0, target_stock - stok_ready)
                if raw_replenishment > 0:
                    recommended_purchase_qty = int(math.ceil(raw_replenishment))
                    if moq_unit > 0:
                        recommended_purchase_qty = max(recommended_purchase_qty, moq_unit)
                    if kelipatan_qty > 0:
                        recommended_purchase_qty = int(math.ceil(recommended_purchase_qty / kelipatan_qty) * kelipatan_qty)

            normalized.append({
                **row,
                "stok_ready": int(stok_ready),
                "stok_good": int(float(row.get('stok_good') or 0)),
                "stok_bad": int(float(row.get('stok_bad') or 0)),
                "total_keluar_pcs": round(total_keluar, 2),
                "avg_daily_sales": avg_daily_sales,
                "doi": doi_value,
                "target_doi_hari": target_doi,
                "doi_gap_hari": round((doi_value or 0) - target_doi, 1) if doi_value is not None else None,
                "rule_id": rule.get("id"),
                "rule_source": "Aturan Principal" if rule else "Default",
                "lead_time_hari": lead_time_hari,
                "moq_unit": moq_unit,
                "kelipatan_qty": kelipatan_qty,
                "recommended_purchase_qty": recommended_purchase_qty,
                "top_hari": int(float(rule.get("top_hari") or 0)),
                "target_sell_in": float(rule.get("target_sell_in") or 0),
                "target_sell_out": float(rule.get("target_sell_out") or 0),
                "status_doi": status,
                "status_tone": status_tone,
                "recommendation": recommendation,
            })

            summary["total_items"] += 1
            if status == 'Understock':
                summary["understock"] += 1
            elif status == 'Healthy':
                summary["healthy"] += 1
            elif status == 'Overstock':
                summary["overstock"] += 1
            else:
                summary["no_movement"] += 1

        normalized.sort(
            key=lambda item: (
                {'Understock': 0, 'Overstock': 1, 'No Movement': 2, 'Healthy': 3}.get(item['status_doi'], 9),
                item['doi'] if item['doi'] is not None else 999999,
                item.get('nama_produk') or ''
            )
        )

        summary["average_doi"] = round(sum(doi_values) / len(doi_values), 1) if doi_values else 0

        return {
            "filters": {
                "tanggal_awal": from_date,
                "tanggal_akhir": to_date,
                "id_cabang": id_cabang,
                "id_perusahaan": id_perusahaan,
                "id_principal": id_principal,
                "search": search,
                "days_window": total_days,
            },
            "summary": summary,
            "rows": normalized,
        }
