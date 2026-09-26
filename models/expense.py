from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SalesInventoryExpense(models.Model):
    _name = "sales.inventory.expense"
    _description = "Solicitud de gasto"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(string="Folio", default="Nuevo", readonly=True, copy=False)
    date = fields.Date(string="Fecha", default=fields.Date.context_today, required=True)
    expense_type = fields.Selection(
        [
            ("fixed", "Gasto operativo"),
            ("reinvestment", "Reinversión con productos"),
            ("capital_adjustment", "Compra de inventario ya registrada"),
        ],
        string="Tipo",
        default="fixed",
        required=True,
    )
    concept = fields.Char(string="Concepto", required=True)
    fund_source = fields.Selection(
        [
            ("capital", "Capital recuperado"),
            ("profit", "Ganancias"),
        ],
        string="Descontar primero de",
        default="profit",
        required=True,
        tracking=True,
        help=(
            "Fondo del que se intentará descontar el gasto primero. Si no alcanza, "
            "la diferencia se tomará del otro fondo y quedará registrada en el historial."
        ),
    )
    fixed_amount = fields.Monetary(string="Importe del gasto")
    amount = fields.Monetary(string="Importe total", compute="_compute_amount", store=True)
    recovered_used = fields.Monetary(string="Tomado de capital recuperado", readonly=True, copy=False)
    profit_used = fields.Monetary(string="Tomado de ganancias", readonly=True, copy=False)
    line_ids = fields.One2many("sales.inventory.expense.line", "expense_id", string="Productos")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id, required=True)
    state = fields.Selection(
        [("draft", "Borrador"), ("confirmed", "Aprobada"), ("cancel", "Cancelada")],
        default="draft",
        required=True,
        tracking=True,
    )
    notes = fields.Text(string="Notas")

    @api.depends("expense_type", "fixed_amount", "line_ids.subtotal")
    def _compute_amount(self):
        for expense in self:
            expense.amount = (
                sum(expense.line_ids.mapped("subtotal"))
                if expense.expense_type == "reinvestment"
                else expense.fixed_amount
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code("sales.inventory.expense") or "Nuevo"
            if not vals.get("fund_source"):
                vals["fund_source"] = "profit" if vals.get("expense_type", "fixed") == "fixed" else "capital"
        return super().create(vals_list)

    @api.onchange("expense_type")
    def _onchange_expense_type_fund_source(self):
        for expense in self:
            expense.fund_source = "profit" if expense.expense_type == "fixed" else "capital"

    def _money_label(self, amount):
        self.ensure_one()
        currency_label = self.currency_id.symbol or self.currency_id.name
        return "%s %s" % (currency_label, f"{amount:,.2f}")

    def action_confirm(self):
        dashboard = self.env.ref("sales_inventory.dashboard_main")
        fallback_warnings = []
        for expense in self:
            if expense.state != "draft" or expense.amount <= 0:
                raise ValidationError(_("El gasto debe estar en borrador y tener un importe positivo."))
            dashboard.invalidate_recordset()
            capital_available = max(dashboard.recovered_balance, 0)
            profit_available = max(dashboard.profit_balance, 0)
            available = capital_available + profit_available
            if expense.amount > available:
                raise ValidationError(_("El importe excede el saldo disponible (%s).") % available)
            if expense.expense_type == "reinvestment":
                if not expense.line_ids:
                    raise ValidationError(_("Agrega al menos un producto para la reinversión."))
                for line in expense.line_ids:
                    if not line.use_initial_stock:
                        line.product_id._change_stock(line.quantity)
                    line.product_id.purchase_price = line.unit_cost
            if expense.fund_source == "capital":
                recovered_used = min(expense.amount, capital_available)
                profit_used = expense.amount - recovered_used
                requested_available = capital_available
                fallback_used = profit_used
                requested_label = _("capital recuperado")
                fallback_label = _("ganancias")
            else:
                profit_used = min(expense.amount, profit_available)
                recovered_used = expense.amount - profit_used
                requested_available = profit_available
                fallback_used = recovered_used
                requested_label = _("ganancias")
                fallback_label = _("capital recuperado")

            expense.write({
                "recovered_used": recovered_used,
                "profit_used": profit_used,
                "state": "confirmed",
            })

            if not expense.currency_id.is_zero(fallback_used):
                message = _(
                    "Se solicitó descontar este gasto de %(requested)s, pero el saldo disponible "
                    "(%(available)s) no fue suficiente. Se tomaron %(fallback_amount)s de "
                    "%(fallback)s para cubrir la diferencia. Desglose final: %(capital)s de "
                    "capital recuperado y %(profit)s de ganancias."
                ) % {
                    "requested": requested_label,
                    "available": expense._money_label(requested_available),
                    "fallback_amount": expense._money_label(fallback_used),
                    "fallback": fallback_label,
                    "capital": expense._money_label(recovered_used),
                    "profit": expense._money_label(profit_used),
                }
                expense.message_post(body=message, message_type="comment", subtype_xmlid="mail.mt_note")
                fallback_warnings.append(_("%(expense)s: %(message)s") % {
                    "expense": expense.name,
                    "message": message,
                })
            else:
                expense.message_post(
                    body=_(
                        "Gasto aprobado con cargo a %(source)s. Desglose final: %(capital)s de "
                        "capital recuperado y %(profit)s de ganancias."
                    ) % {
                        "source": requested_label,
                        "capital": expense._money_label(recovered_used),
                        "profit": expense._money_label(profit_used),
                    },
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )

        if fallback_warnings:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Se utilizó el fondo alterno"),
                    "message": "\n".join(fallback_warnings),
                    "type": "warning",
                    "sticky": True,
                    "next": {"type": "ir.actions.client", "tag": "soft_reload"},
                },
            }
        return True

    def action_cancel(self):
        for expense in self.filtered(lambda r: r.state == "confirmed"):
            if expense.expense_type == "reinvestment":
                for line in expense.line_ids:
                    if not line.use_initial_stock:
                        line.product_id._change_stock(-line.quantity)
            expense.state = "cancel"

    def action_draft(self):
        records = self.filtered(lambda record: record.state == "cancel")
        records.write({"state": "draft", "recovered_used": 0, "profit_used": 0})

    def unlink(self):
        if any(record.state == "confirmed" for record in self):
            raise UserError(_("No puedes eliminar un gasto aprobado; cancélalo primero."))
        return super().unlink()


class SalesInventoryExpenseLine(models.Model):
    _name = "sales.inventory.expense.line"
    _description = "Producto de reinversión"

    expense_id = fields.Many2one("sales.inventory.expense", required=True, ondelete="cascade")
    product_id = fields.Many2one("sales.inventory.product", string="Producto", required=True)
    quantity = fields.Float(string="Cantidad a agregar", default=1, required=True, digits="Product Unit of Measure")
    use_initial_stock = fields.Boolean(
        string="Usar existencia inicial",
        help=(
            "Actívalo únicamente cuando el producto se creó desde esta solicitud y su existencia inicial "
            "ya representa toda la compra. El inventario no se volverá a incrementar."
        ),
    )
    initial_qty = fields.Float(
        string="Existencia inicial",
        related="product_id.initial_qty",
        digits="Product Unit of Measure",
    )
    effective_quantity = fields.Float(
        string="Cantidad considerada",
        compute="_compute_subtotal",
        store=True,
        digits="Product Unit of Measure",
    )
    unit_cost = fields.Monetary(string="Costo unitario", required=True)
    subtotal = fields.Monetary(compute="_compute_subtotal", store=True)
    currency_id = fields.Many2one(related="expense_id.currency_id")

    @api.depends("quantity", "unit_cost", "use_initial_stock", "product_id.initial_qty")
    def _compute_subtotal(self):
        for line in self:
            line.effective_quantity = line.initial_qty if line.use_initial_stock else line.quantity
            line.subtotal = line.effective_quantity * line.unit_cost

    @api.onchange("product_id")
    def _onchange_product(self):
        self.unit_cost = self.product_id.purchase_price

    @api.constrains("quantity", "unit_cost", "use_initial_stock", "product_id")
    def _check_values(self):
        if any(line.quantity <= 0 or line.unit_cost < 0 for line in self):
            raise ValidationError(_("La cantidad debe ser positiva y el costo no puede ser negativo."))
        if any(line.use_initial_stock and line.initial_qty <= 0 for line in self):
            raise ValidationError(_("El producto debe tener una existencia inicial positiva para usar esa opción."))
