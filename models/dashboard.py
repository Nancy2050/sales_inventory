from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class SalesInventoryDashboard(models.Model):
    _name = "sales.inventory.dashboard"
    _description = "Dashboard de ventas e inventario"

    name = fields.Char(default="Resumen", readonly=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    recovered_gross = fields.Monetary(string="Recuperado por ventas", compute="_compute_balances")
    recovered_balance = fields.Monetary(string="Capital recuperado disponible", compute="_compute_balances")
    profit_gross = fields.Monetary(string="Ganancia de ventas", compute="_compute_balances")
    profit_balance = fields.Monetary(string="Ganancia disponible", compute="_compute_balances")
    cash_total = fields.Monetary(string="Total en caja", compute="_compute_balances")
    inventory_units = fields.Float(string="Unidades en inventario", compute="_compute_balances")
    inventory_value = fields.Monetary(string="Valor del inventario", compute="_compute_balances")

    def _compute_balances(self):
        balances = self._get_balances()
        for dashboard in self:
            dashboard.recovered_gross = balances["recovered_gross"]
            dashboard.recovered_balance = balances["recovered_balance"]
            dashboard.profit_gross = balances["profit_gross"]
            dashboard.profit_balance = balances["profit_balance"]
            dashboard.cash_total = balances["cash_total"]
            dashboard.inventory_units = balances["inventory_units"]
            dashboard.inventory_value = balances["inventory_value"]

    @api.model
    def _get_balances(self):
        """Obtiene los saldos globales a partir de movimientos confirmados."""
        Sale = self.env["sales.inventory.sale"]
        Expense = self.env["sales.inventory.expense"]
        Recovery = self.env["sales.inventory.recovery"]
        Product = self.env["sales.inventory.product"]
        recovered_gross = sum(Sale.search([("state", "=", "confirmed")]).mapped("recovered_total"))
        profit_gross = sum(Sale.search([("state", "=", "confirmed")]).mapped("profit_total"))
        expenses = Expense.search([("state", "=", "confirmed")])
        releases = Recovery.search([("state", "=", "released")])
        capital_used = sum(expenses.mapped("recovered_used")) + sum(releases.mapped("recovered_used"))
        profit_used = sum(expenses.mapped("profit_used")) + sum(releases.mapped("profit_used"))
        # Compatibility with movements confirmed before source-allocation fields existed.
        for movement in expenses:
            if not movement.recovered_used and not movement.profit_used and movement.amount:
                if movement.expense_type == "fixed":
                    profit_used += movement.amount
                else:
                    capital_used += movement.amount
        capital_used += sum(
            movement.amount
            for movement in releases
            if not movement.recovered_used and not movement.profit_used and movement.amount
        )
        products = Product.search([])
        recovered_balance = recovered_gross - capital_used
        profit_balance = profit_gross - profit_used
        return {
            "recovered_gross": recovered_gross,
            "recovered_balance": recovered_balance,
            "profit_gross": profit_gross,
            "profit_balance": profit_balance,
            "cash_total": recovered_balance + profit_balance,
            "inventory_units": sum(products.mapped("stock_qty")),
            "inventory_value": sum(products.mapped("investment_total")),
        }

    @api.model
    def get_dashboard_data(self):
        """Genera las métricas y series gráficas del dashboard principal."""
        balances = self._get_balances()
        today = fields.Date.context_today(self)
        first_month = today.replace(day=1) - relativedelta(months=11)
        months = [first_month + relativedelta(months=index) for index in range(12)]
        month_keys = [month.strftime("%Y-%m") for month in months]
        month_names = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
        month_labels = [f"{month_names[month.month - 1]} {str(month.year)[-2:]}" for month in months]

        confirmed_lines = self.env["sales.inventory.sale.line"].search([
            ("sale_id.state", "=", "confirmed"),
        ])
        monthly_sales = defaultdict(float)
        monthly_profit = defaultdict(float)
        product_units = defaultdict(float)
        category_month_units = defaultdict(lambda: defaultdict(float))
        for line in confirmed_lines:
            product_units[line.product_id.display_name] += line.quantity
            sale_date = fields.Date.to_date(line.sale_id.date)
            if not sale_date or sale_date < first_month:
                continue
            month_key = sale_date.strftime("%Y-%m")
            monthly_sales[month_key] += line.sale_total
            monthly_profit[month_key] += line.profit_total
            category_name = line.product_id.category_id.display_name or "Sin categoría"
            category_month_units[category_name][month_key] += line.quantity

        palette = ["#1769ff", "#23aa53", "#f4aa3d", "#7654d6", "#e4546b", "#20a4b8", "#8a6d3b", "#68778c"]
        categories = sorted(
            category_month_units,
            key=lambda name: sum(category_month_units[name].values()),
            reverse=True,
        )
        category_legend = [
            {"name": name, "color": palette[index % len(palette)]}
            for index, name in enumerate(categories)
        ]
        category_months = []
        for month_key, label in zip(month_keys[-6:], month_labels[-6:]):
            values = [category_month_units[name][month_key] for name in categories]
            total = sum(values)
            category_months.append({
                "label": label,
                "total": total,
                "segments": [
                    {
                        "name": category["name"],
                        "color": category["color"],
                        "value": value,
                        "percent": (value / total * 100) if total else 0,
                    }
                    for category, value in zip(category_legend, values)
                    if value
                ],
            })

        sorted_products = sorted(product_units.items(), key=lambda item: (-item[1], item[0]))
        products_ranking = [
            {"name": name, "quantity": quantity}
            for name, quantity in sorted_products[:10]
        ]
        inventory_by_category = defaultdict(float)
        for product in self.env["sales.inventory.product"].search([("active", "=", True), ("stock_qty", ">", 0)]):
            inventory_by_category[product.category_id.display_name or "Sin categoría"] += product.stock_qty

        return {
            "currency_id": self.env.company.currency_id.id,
            "balances": balances,
            "monthly": [
                {
                    "label": label,
                    "sales": monthly_sales[key],
                    "profit": monthly_profit[key],
                }
                for key, label in zip(month_keys, month_labels)
            ],
            "products_ranking": products_ranking,
            "most_sold": (
                {"name": sorted_products[0][0], "quantity": sorted_products[0][1]}
                if sorted_products else False
            ),
            "least_sold": (
                {"name": sorted_products[-1][0], "quantity": sorted_products[-1][1]}
                if sorted_products else False
            ),
            "category_legend": category_legend,
            "category_months": category_months,
            "inventory_by_category": [
                {"name": name, "quantity": quantity}
                for name, quantity in sorted(
                    inventory_by_category.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        }
