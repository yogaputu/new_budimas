import copy
import unittest

from repair_customer_c1_invoice_20261006 import build_plan


def fixture():
    masters=[{'id':pid,'id_customer':89330,'id_principal':principal,'limit_bon':100000000,'sisa_bon':100000000}
             for pid,principal in ((173127,5),(173129,232),(192927,33),(192928,70))]
    masters[1]['sisa_bon']=111465705.53999999
    orders=[{'id':oid,'id_plafon':pid,'id_cabang':5,'status_order':6,'id_order_batch':4,'total_order':old}
            for oid,pid,old in ((66062181,192927,1158530.23),(66062182,173129,1100000))]
    orders.append({'id':10,'id_plafon':173129,'id_cabang':5,'status_order':2,'id_order_batch':None,'total_order':1000})
    invoice={'id':66059040,'no_faktur':'NPBMMSLO-2609000010','id_order_batch':4,'id_sales_order':None,
             'status_faktur':2,'jenis_faktur':'penjualan','nominal_retur':None,'total_dana_diterima':0,
             'total_penjualan':1100022,'dpp':1100000,'pajak':22,'subtotal_penjualan':1100000,'subtotal_diskon':0}
    other={'id':10,'id_order_batch':None,'id_sales_order':10,'status_faktur':2,'jenis_faktur':'penjualan',
           'total_penjualan':1000,'nominal_retur':0}
    details=[{'id':48046,'id_faktur':66059040,'id_sales_order':66062181,'id_principal':33,
              'total':1100022,'subtotal':1100000,'pajak':22,'subtotal_diskon':0},
             {'id':48047,'id_faktur':66059040,'id_sales_order':66062182,'id_principal':232,
              'total':1165500,'subtotal':1050000,'pajak':115500,'subtotal_diskon':0}]
    return {'plafon':masters,'sales_order':orders,'faktur':[invoice,other],'faktur_detail':details,
            'setoran':[{'id':100,'id_sales_order':10,'id_faktur':10,'status_setoran':3,'draft_jumlah_setor':100,'jumlah_setoran':100}],
            'setoran_customer':[{'id':50,'id_sales_order':10,'id_faktur':10,'jumlah_setoran':100}],
            'payment_voucher_usage':[],'finance_customer_advance_usage':[],
            'target_lph':[],'target_claims':[],'target_returns':[],'target_revisions':[],'target_cn':[]}


class CombinedInvoiceRepairTest(unittest.TestCase):
    def setUp(self):
        self.data=fixture()

    def test_two_principals_form_one_full_invoice(self):
        plan=build_plan(self.data)
        self.assertEqual(plan['invoice_total'],2265522)
        update=next(c for c in plan['changes'] if c['table']=='faktur')
        self.assertEqual(update['after'],{'total_penjualan':2265522,'dpp':2150000,'pajak':115522,'subtotal_penjualan':2150000})
        self.assertNotIn('status_faktur',update['after'])
        self.assertNotIn('draft_total_penjualan',update['after'])

    def test_reservations_and_final_payment_projections_not_double_counted(self):
        p1=next(p for p in build_plan(self.data)['credit_summary'] if p['principal_id']==232)
        self.assertEqual(p1['receivable'],1165500)
        self.assertEqual(p1['open_order_reservation'],900)
        self.assertEqual(p1['after'],98833600)
        self.assertEqual(p1['final_receipts'],100)

    def test_pending_receipt_does_not_release_credit(self):
        self.data['setoran'][0]['status_setoran']=2
        p1=next(p for p in build_plan(self.data)['credit_summary'] if p['principal_id']==232)
        self.assertEqual(p1['open_order_reservation'],1000)

    def test_no_side_effect_and_idempotence(self):
        saved=copy.deepcopy(self.data)
        plan=build_plan(self.data)
        self.assertEqual(saved,self.data)
        for c in plan['changes']:
            next(r for r in self.data[c['table']] if r['id']==c['id']).update(c['after'])
        self.assertEqual(build_plan(self.data)['changes'],[])

    def test_refuses_changed_details(self):
        self.data['faktur_detail'][1]['total']+=1
        with self.assertRaisesRegex(ValueError,'user-confirmed'):
            build_plan(self.data)

    def test_refuses_missing_principal(self):
        self.data['faktur_detail'].pop()
        with self.assertRaisesRegex(ValueError,'Both original'):
            build_plan(self.data)

    def test_refuses_payment_on_target_even_pending(self):
        self.data['setoran'].append({'id':101,'id_faktur':66059040,'id_sales_order':66062181,'status_setoran':0})
        with self.assertRaisesRegex(ValueError,'payment or adjustment'):
            build_plan(self.data)

    def test_refuses_new_lph_claim_return_revision_or_cn(self):
        for key in ('target_lph','target_claims','target_returns','target_revisions','target_cn'):
            with self.subTest(key=key):
                data=copy.deepcopy(self.data)
                data[key]=[{'id':1}]
                with self.assertRaisesRegex(ValueError,'review again'):
                    build_plan(data)

    def test_wrong_customer_is_rejected(self):
        self.data['plafon'][0]['id_customer']=9
        with self.assertRaisesRegex(ValueError,'Wrong customer'):
            build_plan(self.data)

    def test_missing_active_invoice_is_rejected(self):
        self.data['faktur'].pop()
        with self.assertRaisesRegex(ValueError,'missing invoice'):
            build_plan(self.data)

    def test_paid_more_than_invoice_requires_review(self):
        self.data['setoran'][0]['draft_jumlah_setor']=1100
        with self.assertRaisesRegex(ValueError,'Settlement exceeds'):
            build_plan(self.data)

    def test_denied_order_excluded_from_credit_exposure(self):
        self.data['sales_order'][-1]['status_order']=-1
        self.data['faktur'][-1]['status_faktur']=-1
        p1=next(p for p in build_plan(self.data)['credit_summary'] if p['principal_id']==232)
        self.assertEqual(p1['open_order_reservation'],0)


if __name__=='__main__':
    unittest.main()
