from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestSalesInventory(TransactionCase):
    def setUp(self):
        super().setUp()
        self.product = self.env["sales.inventory.product"].create({
            "name": "Bolsa de prueba",
            "code": "TEST-001",
            "initial_qty": 3,
            "purchase_price": 50,
            "suggested_price": 90,
        })
        self.dashboard = self.env.ref("sales_inventory.dashboard_main")

    def _refresh_dashboard(self):
        self.dashboard.invalidate_recordset()
        return self.dashboard

    def test_complete_money_and_stock_flow(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 2, "sale_total": 160})],
        })
        sale.action_confirm()
        self.assertEqual(self.product.stock_qty, 1)
        self.assertEqual(sale.recovered_total, 100)
        self.assertEqual(sale.profit_total, 60)

        fixed = self.env["sales.inventory.expense"].create({
            "expense_type": "fixed", "concept": "Transporte", "fixed_amount": 10,
        })
        fixed.action_confirm()
        reinvestment = self.env["sales.inventory.expense"].create({
            "expense_type": "reinvestment", "concept": "Reposición",
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 1, "unit_cost": 50})],
        })
        reinvestment.action_confirm()
        self.assertEqual(self.product.stock_qty, 2)

        release = self.env["sales.inventory.recovery"].create({"amount": 25, "reason": "Pago de inversión"})
        release.action_release()
        dashboard = self._refresh_dashboard()
        self.assertEqual(dashboard.recovered_balance, 25)
        self.assertEqual(dashboard.profit_balance, 50)
        self.assertEqual(dashboard.cash_total, 75)

    def test_sale_cannot_exceed_stock(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 4, "sale_total": 300})],
        })
        with self.assertRaises(ValidationError):
            sale.action_confirm()

    def test_release_cannot_exceed_recovered_balance(self):
        release = self.env["sales.inventory.recovery"].create({"amount": 1, "reason": "Sin ventas"})
        with self.assertRaises(ValidationError):
            release.action_release()

    def test_release_uses_profit_when_capital_is_insufficient(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 1, "sale_total": 90})],
        })
        sale.action_confirm()
        release = self.env["sales.inventory.recovery"].create({"amount": 70, "reason": "Retiro combinado"})
        release.action_release()
        self.assertEqual(release.recovered_used, 50)
        self.assertEqual(release.profit_used, 20)
        dashboard = self._refresh_dashboard()
        self.assertEqual(dashboard.recovered_balance, 0)
        self.assertEqual(dashboard.profit_balance, 20)

    def test_new_product_uses_initial_stock_without_duplicating_it(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 2, "sale_total": 200})],
        })
        sale.action_confirm()
        new_product = self.env["sales.inventory.product"].create({
            "name": "Producto nuevo",
            "code": "TEST-NEW",
            "initial_qty": 2,
            "purchase_price": 40,
            "suggested_price": 80,
        })
        expense = self.env["sales.inventory.expense"].create({
            "expense_type": "reinvestment",
            "concept": "Compra inicial",
            "line_ids": [(0, 0, {
                "product_id": new_product.id,
                "quantity": 1,
                "use_initial_stock": True,
                "unit_cost": 40,
            })],
        })
        self.assertEqual(expense.amount, 80)
        expense.action_confirm()
        self.assertEqual(new_product.stock_qty, 2)
        expense.action_cancel()
        self.assertEqual(new_product.stock_qty, 2)
        expense.action_draft()
        self.assertEqual(expense.state, "draft")
        expense.action_confirm()
        self.assertEqual(new_product.stock_qty, 2)

    def test_reinvestment_uses_profit_when_recovered_capital_is_insufficient(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 1, "sale_total": 90})],
        })
        sale.action_confirm()
        expense = self.env["sales.inventory.expense"].create({
            "expense_type": "reinvestment",
            "concept": "Compra con capital y ganancia",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1,
                "unit_cost": 70,
            })],
        })
        expense.action_confirm()
        self.assertEqual(expense.recovered_used, 50)
        self.assertEqual(expense.profit_used, 20)
        dashboard = self._refresh_dashboard()
        self.assertEqual(dashboard.recovered_balance, 0)
        self.assertEqual(dashboard.profit_balance, 20)
        self.assertEqual(dashboard.cash_total, 20)

    def test_registered_inventory_purchase_uses_capital_without_changing_stock(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 2, "sale_total": 180})],
        })
        sale.action_confirm()
        stock_before = self.product.stock_qty
        expense = self.env["sales.inventory.expense"].create({
            "expense_type": "capital_adjustment",
            "concept": "Mercancía capturada previamente",
            "fixed_amount": 80,
        })
        expense.action_confirm()
        self.assertEqual(expense.recovered_used, 80)
        self.assertEqual(expense.profit_used, 0)
        self.assertEqual(self.product.stock_qty, stock_before)
        dashboard = self._refresh_dashboard()
        self.assertEqual(dashboard.recovered_balance, 20)
        self.assertEqual(dashboard.profit_balance, 80)

    def test_operating_expense_can_use_capital_first(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 1, "sale_total": 90})],
        })
        sale.action_confirm()
        expense = self.env["sales.inventory.expense"].create({
            "expense_type": "fixed",
            "concept": "Gasto elegido desde capital",
            "fixed_amount": 30,
            "fund_source": "capital",
        })
        expense.action_confirm()
        self.assertEqual(expense.recovered_used, 30)
        self.assertEqual(expense.profit_used, 0)
        dashboard = self._refresh_dashboard()
        self.assertEqual(dashboard.recovered_balance, 20)
        self.assertEqual(dashboard.profit_balance, 40)

    def test_expense_falls_back_to_other_fund_and_logs_warning(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 1, "sale_total": 90})],
        })
        sale.action_confirm()
        expense = self.env["sales.inventory.expense"].create({
            "expense_type": "fixed",
            "concept": "Gasto mayor que la ganancia",
            "fixed_amount": 70,
            "fund_source": "profit",
        })

        result = expense.action_confirm()

        self.assertEqual(expense.profit_used, 40)
        self.assertEqual(expense.recovered_used, 30)
        self.assertEqual(result["params"]["type"], "warning")
        dashboard = self._refresh_dashboard()
        self.assertEqual(dashboard.recovered_balance, 20)
        self.assertEqual(dashboard.profit_balance, 0)
        self.assertTrue(any(
            "no fue suficiente" in (message.body or "")
            and "capital recuperado" in (message.body or "")
            for message in expense.message_ids
        ))

    def test_inventory_verification_can_be_marked_and_cleared(self):
        self.product.action_mark_inventory_verified()
        self.assertTrue(self.product.inventory_verified)
        self.assertEqual(self.product.inventory_review_status, "present")
        self.assertTrue(self.product.inventory_verified_date)
        self.assertEqual(self.product.inventory_verified_by, self.env.user)
        self.product.action_clear_inventory_verified()
        self.assertFalse(self.product.inventory_verified)
        self.assertEqual(self.product.inventory_review_status, "pending")
        self.assertFalse(self.product.inventory_verified_date)

    def test_inventory_review_stores_history_and_resets_next_round(self):
        second_product = self.env["sales.inventory.product"].create({
            "name": "Producto ausente",
            "code": "TEST-MISSING",
            "initial_qty": 2,
            "purchase_price": 25,
            "suggested_price": 45,
        })
        self.product.action_mark_inventory_verified()
        second_product.action_mark_inventory_missing()

        result = self.env["sales.inventory.product"].action_finish_inventory_review()

        review = self.env["sales.inventory.review"].browse(result["id"])
        self.assertEqual(review.total_products, 2)
        self.assertEqual(review.present_count, 1)
        self.assertEqual(review.missing_count, 1)
        self.assertIn(self.product.code, review.present_summary)
        self.assertIn(second_product.code, review.missing_summary)
        self.assertEqual(len(review.line_ids), 2)
        self.assertEqual(self.product.inventory_review_status, "pending")
        self.assertEqual(second_product.inventory_review_status, "pending")

    def test_inventory_review_cannot_finish_with_pending_products(self):
        with self.assertRaises(ValidationError):
            self.env["sales.inventory.product"].action_finish_inventory_review()

    def test_dashboard_returns_sales_and_inventory_series(self):
        sale = self.env["sales.inventory.sale"].create({
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1,
                "sale_total": 90,
            })],
        })
        sale.action_confirm()

        data = self.env["sales.inventory.dashboard"].get_dashboard_data()

        self.assertEqual(len(data["monthly"]), 12)
        self.assertEqual(data["most_sold"]["name"], self.product.display_name)
        self.assertEqual(data["most_sold"]["quantity"], 1)
        self.assertEqual(data["balances"]["inventory_units"], 2)
        self.assertTrue(data["inventory_by_category"])

    def test_inventory_review_reset_clears_active_verified_products_with_stock(self):
        second_product = self.env["sales.inventory.product"].create({
            "name": "Segundo producto",
            "code": "TEST-002",
            "initial_qty": 1,
            "purchase_price": 30,
            "suggested_price": 60,
        })
        archived_product = self.env["sales.inventory.product"].create({
            "name": "Producto archivado",
            "code": "TEST-ARCHIVED",
            "initial_qty": 1,
            "purchase_price": 10,
            "suggested_price": 20,
        })
        zero_stock_product = self.env["sales.inventory.product"].create({
            "name": "Producto sin existencia",
            "code": "TEST-ZERO",
            "purchase_price": 15,
            "suggested_price": 25,
        })
        (
            self.product | second_product | archived_product | zero_stock_product
        ).action_mark_inventory_verified()
        archived_product.active = False

        reset_count = self.env["sales.inventory.product"].action_reset_inventory_review()

        self.assertEqual(reset_count, 2)
        self.assertFalse(self.product.inventory_verified)
        self.assertFalse(second_product.inventory_verified)
        self.assertFalse(self.product.inventory_verified_date)
        self.assertFalse(second_product.inventory_verified_by)
        self.assertTrue(archived_product.inventory_verified)
        self.assertTrue(zero_stock_product.inventory_verified)
