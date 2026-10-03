from  flask       import  Flask, request
from  apps.conn2  import  db
from apps.datatables import DataTables, DictMapper
from  apps.query  import  DB
from apps.widget import btn_actions
from  .  import  BaseModel

class Cabang(BaseModel) :
    
    __tablename__ = 'cabang'

    # id          = db.Column(db.Integer, primary_key=True)
    # nama        = db.Column(db.String(50))
    # alamat      = db.Column(db.String(100))
    # telepon     = db.Column(db.String(15))
    # npwp        = db.Column(db.String(25))
    # id_wilayah1 = db.Column(db.Integer)
    # id_wilayah2 = db.Column(db.Integer)
    # id_wilayah3 = db.Column(db.Integer)
    # id_wilayah4 = db.Column(db.Integer)
    # id_perusahaan = db.Column(db.Integer)
    
    nama = BaseModel.string(50)
    alamat = BaseModel.string(100)
    telepon = BaseModel.string(15)
    npwp = BaseModel.string(25)
    id_wilayah1 = BaseModel.integer()
    id_wilayah2 = BaseModel.integer()
    id_wilayah3 = BaseModel.bigInteger()
    id_wilayah4 = BaseModel.bigInteger()
    kode = BaseModel.string(100)
    id_perusahaan = BaseModel.foreign('perusahaan.id')

    def __repr__(self) :
        return f"data('{self.id}')"

    base_query = """
        SELECT
          cabang.id,
          cabang.kode,
          cabang.nama,
          cabang.alamat,
          cabang.telepon,
          cabang.npwp,
          cabang.id_perusahaan,
          perusahaan.nama AS nama_perusahaan,
          STRING_AGG(DISTINCT COALESCE(perusahaan_cabang.id_perusahaan, cabang.id_perusahaan)::text, ',')
            FILTER (WHERE COALESCE(perusahaan_cabang.id_perusahaan, cabang.id_perusahaan) IS NOT NULL)
            AS id_perusahaan_list,
          STRING_AGG(DISTINCT COALESCE(perusahaan_relasi.kode, perusahaan.kode), ', ')
            FILTER (WHERE COALESCE(perusahaan_relasi.kode, perusahaan.kode) IS NOT NULL)
            AS kode_perusahaan_list,
          STRING_AGG(DISTINCT COALESCE(perusahaan_relasi.nama, perusahaan.nama), ', ')
            FILTER (WHERE COALESCE(perusahaan_relasi.nama, perusahaan.nama) IS NOT NULL)
            AS nama_perusahaan_list,
          cabang.id_wilayah1,
          cabang.id_wilayah2,
          cabang.id_wilayah3,
          cabang.id_wilayah4
        FROM cabang
        LEFT JOIN perusahaan ON perusahaan.id = cabang.id_perusahaan
        LEFT JOIN perusahaan_cabang ON perusahaan_cabang.id_cabang = cabang.id
        LEFT JOIN perusahaan perusahaan_relasi ON perusahaan_relasi.id = perusahaan_cabang.id_perusahaan
        GROUP BY
          cabang.id,
          cabang.kode,
          cabang.nama,
          cabang.alamat,
          cabang.telepon,
          cabang.npwp,
          cabang.id_perusahaan,
          perusahaan.nama,
          cabang.id_wilayah1,
          cabang.id_wilayah2,
          cabang.id_wilayah3,
          cabang.id_wilayah4
    """

    @classmethod
    def ensure_company_relation_table(cls):
        from apps.models.Perusahaan import Perusahaan
        Perusahaan.ensure_branch_relation_table()

    @classmethod
    def all(cls):
        cls.ensure_company_relation_table()
        return DB(request).setRawQuery(cls.base_query).execute().fetchall().get()

    @classmethod
    def all_table(cls):
        cls.ensure_company_relation_table()
        return DataTables(db).handle(
            base_query=cls.base_query,
            transformer=lambda data: (
                DictMapper(data)
                .to_dict()
                .add_col(lambda i: "", "")
                .add_col(lambda i: btn_actions(i['id']), "actions")
                .get()
            )
        )
