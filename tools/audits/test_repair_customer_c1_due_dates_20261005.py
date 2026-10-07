import unittest
from datetime import date

from repair_customer_c1_due_dates_20261005 import plan_missing_dates


class MissingDueDatePlanTest(unittest.TestCase):
    def setUp(self):
        self.master = [{'id':192927, 'id_customer':89330, 'tempo':24}]
        self.order = {'id':79162142, 'no_order':'SO-20261005-092434',
                      'id_plafon':192927, 'id_cabang':5, 'status_order':6,
                      'tanggal_faktur':None, 'tanggal_order':'2026-10-05',
                      'tanggal_jatuh_tempo':None}

    def test_missing_due_uses_order_date(self):
        plan = plan_missing_dates([self.order], self.master)
        self.assertEqual(plan[0]['after'], '2026-10-29')
        self.assertIsNone(self.order['tanggal_jatuh_tempo'])

    def test_invoice_date_precedes_order_fallback(self):
        self.order['tanggal_faktur'] = '2026-10-06'
        self.assertEqual(plan_missing_dates([self.order],self.master)[0]['after'],'2026-10-30')

    def test_existing_dates_and_repeat_runs_are_not_changed(self):
        self.order['tanggal_jatuh_tempo'] = '2026-10-29'
        self.assertEqual(plan_missing_dates([self.order],self.master), [])

    def test_draft_denied_cancelled_return_are_not_changed(self):
        for status in (-1,0,7,8):
            with self.subTest(status=status):
                self.order['status_order'] = status
                self.assertEqual(plan_missing_dates([self.order],self.master), [])

    def test_customer_and_branch_must_match(self):
        self.master[0]['id_customer'] = 999
        with self.assertRaises(ValueError):
            plan_missing_dates([self.order],self.master)
        self.master[0]['id_customer'] = 89330
        self.order['id_cabang'] = 9
        with self.assertRaises(ValueError):
            plan_missing_dates([self.order],self.master)

    def test_changed_terms_fail_closed(self):
        self.master[0]['tempo'] = 30
        with self.assertRaises(ValueError):
            plan_missing_dates([self.order],self.master)

    def test_date_object_and_missing_date(self):
        self.order['tanggal_order'] = date(2026,10,5)
        self.assertEqual(plan_missing_dates([self.order],self.master)[0]['after'],'2026-10-29')
        self.order['tanggal_order'] = None
        with self.assertRaises(ValueError):
            plan_missing_dates([self.order],self.master)


if __name__ == '__main__':
    unittest.main()
