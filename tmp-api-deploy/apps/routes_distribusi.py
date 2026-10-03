from flask import Blueprint, jsonify, request, make_response
from apps.services.BaseServices import token_auth
from apps.services.Distribusi import Distribusi
from apps.services.Armada import Armada
from apps.services.Driver import Driver

distribusi = Blueprint('distribusi', __name__, url_prefix='/api/distribusi/')
distribusi.before_request(lambda: token_auth.login_required(lambda: None)())

# admin verifikasi routes
@distribusi.route('get-list-verifikasi')
def _get_list_verifikasi(): return Distribusi().getListOrderKonfirmasi()
# admin verifikasi routes

@distribusi.route('get-rute-armada')
def _1(): return Distribusi().getRuteArmada() 

@distribusi.route("get-all-armada")
def _2(): return Armada().getAllArmada()
    
@distribusi.route("get-all-driver")
def _3(): return Driver().getAllDriver()
    
@distribusi.route("get-rute-picking")
def _4(): return Distribusi().getRuteListPicking() 

@distribusi.route("get-info-rute-armada")
def _5(): return Distribusi().getInfoRuteArmada()

@distribusi.route("get-add-picking")
def _6(): return Distribusi().getAddpicking() 

@distribusi.route("update", methods=['POST'])
def _7(): return Distribusi().updateJadwalRute()

@distribusi.route("daftar-picking-toko")
def _8(): return Distribusi().getDaftarTokoPicking()

@distribusi.route("submit-produk-picking", methods=["POST"])
def _9(): return Distribusi().submitProdukPicking()

@distribusi.route("get-list-rute-shipping/<int:id_cabang>")
def _10(id_cabang): return Distribusi().getShippingRuteList(id_cabang)

@distribusi.route("get-list-rute-realisasi/<int:id_cabang>")
def _get_list_rute_realisasi(id_cabang): return Distribusi().getShippingRuteList(id_cabang, True)

@distribusi.route("get-list-faktur-shipping")
def _11(): return Distribusi().getListFakturShipping()

@distribusi.route("get-list-history-distribusi")
def _getListHistoryDistribusi(): return Distribusi().getListHistoryDistribusi()

# @distribusi.route("get-list-rute-realisasi/<int:id_cabang>")
# def __getListRuteRealisasi(id_cabang): return Distribusi().getShippingRuteList(id_cabang, True)

@distribusi.route("get-list-faktur-realisasi")
def _getListFakturRealisasi():    
    data = Distribusi().getListFakturShipping(1)
    # print(type(data))
    # print(data)
    return jsonify(data)

@distribusi.route("konfirmasi-order", methods=['PATCH', 'OPTIONS'])
def _konfirmasiOrder():
    if request.method == 'OPTIONS':
        # Berikan respon sukses untuk preflight check browser
        response = make_response()
        response.headers.add("Access-Control-Allow-Methods", "PATCH")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
        return response, 200
        
    # Hanya jalankan ini jika method-nya PATCH
    return Distribusi().konfirmasiOrder(1)

@distribusi.route('tolak-order', methods=["PATCH", "OPTIONS"])
def _tolakOrder():
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add("Access-Control-Allow-Methods", "PATCH")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
        return response, 200

    return Distribusi().konfirmasiOrder(-1)

@distribusi.route("get-detail-faktur/<int:id_sales_order>")
def _12(id_sales_order): return Distribusi().getDetailFakturShipping(id_sales_order)

@distribusi.route("get-detail-faktur-retur/<int:id_sales_order>")
def _13(id_sales_order): return Distribusi().getDetailFakturShipping(id_sales_order, 'retur')

@distribusi.route('get-list-rute-history/<int:id_cabang>')
def _14(id_cabang): return Distribusi().getListRuteHistory(id_cabang)

@distribusi.route('get-list-nota-history')
def _15(): return Distribusi().getListNota()

@distribusi.route('get-list-order/<int:id_cabang>')
def _16(id_cabang): return Distribusi().getListOrder(id_cabang)

@distribusi.route("get-realisasi-detail")
def _17(): return Distribusi().getRealisasiDetail()

@distribusi.route("submit-realisasi-detail", methods=["POST"])
def _18(): return Distribusi().submitRealisasiDetail()

@distribusi.route('get-user-info/<int:id_user>' )
def _19(id_user): return Distribusi().getUserInfo(id_user)

@distribusi.route("batal-realisasi", methods=["POST"])
def _20(): return Distribusi().batalRealisasi()

# @distribusi.route("submit-shipping", methods=["PUT"])
# def _21(): return Distribusi().submitShipping()

@distribusi.route("submit-faktur", methods=["POST"])
def _submitAllFaktur(): return Distribusi().submitShipping()

# pengeluaran driver
@distribusi.route("get-pengeluaran-driver-list")
def _22(): return Driver().getPengeluaranDriverList()

@distribusi.route("get-pengeluaran-driver-info-update/<int:id>")
def _23(id): return Driver().getPengeluaranDriverInfoUpdate(id)

@distribusi.route("get-pengeluaran-driver-info-fakturs-update/<int:id>")
def _24(id): return Driver().getPengeluaranDriverInfoFaktursUpdate(id)

@distribusi.route("get-pengeluaran-driver-info-fakturs-add/<int:id>")
def _25(id): return Driver().getPengeluaranDriverInfoFaktursAdd(id)

@distribusi.route("tambah-pengeluaran-driver", methods=['POST'])
def _26(): return Driver().addPengeluaranDriver()

@distribusi.route('update-pengeluaran-driver', methods=['POST'])
def _27(): return Driver().updatePengeluaranDriver()

@distribusi.route('search-driver')
def _28(): return Driver().searchDriver()

@distribusi.route('get-list-faktur-jadwal')
def _29(): return Distribusi().getListFakturJadwal()

@distribusi.route('get-jadwal-armada')
def _30(): return Distribusi().getJadwalArmada()

@distribusi.route('delete-jadwal', methods=['POST'])
def _31(): return Distribusi().deleteJadwal()

@distribusi.route('edit-jadwal', methods=['POST'])
def _32(): return Distribusi().editJadwal()

@distribusi.route('submit-picking', methods=['POST'])
def _33(): return Distribusi().submitPicking()

@distribusi.route('get-list-rute-revisi-faktur')
def _34(): return Distribusi().getListRuteRevisiFaktur()

@distribusi.route('get-list-faktur-revisi-faktur')
def _35(): return Distribusi().getListFakturShipping(2)

@distribusi.route('submit-revisi-faktur', methods=['POST'])
def _36(): return Distribusi().submitRevisiFaktur()

@distribusi.route('jadwalkan-ulang-faktur', methods=['POST'])
def _37(): return Distribusi().jadwalkanUlangFaktur()

@distribusi.route('submit-reshipping', methods=['POST'])
def _38(): return Distribusi().submitReshipping()
