from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SalesInventorySale(models.Model):
    _name = "sales.inventory.sale"
    _description = "Venta"
    _order = "date desc, id desc"

    name = fields.Char(string="Folio", default="Nuevo", readonly=True, copy=False)
    date = fields.Date(string="Fecha", default=fields.Date.context_today, required=True)
    line_ids = fields.One2many("sales.inventory.sale.line", "sale_id", string="Productos", copy=True)
    total = fields.Monetary(string="Total cobrado", compute="_compute_totals", store=True)
    recovered_total = fields.Monetary(string="Capital recuperado", compute="_compute_totals", store=True)
    profit_total = fields.Monetary(string="Ganancia", compute="_compute_totals", store=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id, required=True)
    notes = fields.Text(string="Notas")
    state = fields.Selection([("draft", "Borrador"), ("confirmed", "Confirmada"), ("cancel", "Cancelada")], default="draft", required=True)

    @api.depends("line_ids.sale_total", "line_ids.recovered_total", "line_ids.profit_total")
    def _compute_totals(self):
        for sale in self:
            sale.total = sum(sale.line_ids.mapped("sale_total"))
            sale.recovered_total = sum(sale.line_ids.mapped("recovered_total"))
            sale.profit_total = sum(sale.line_ids.mapped("profit_total"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code("sales.inventory.sale") or "Nuevo"
        return super().create(vals_list)

    def action_confirm(self):
        for sale in self:
            if sale.state != "draft" or not sale.line_ids:
                raise UserError(_("Agrega productos a una venta en borrador."))
            for line in sale.line_ids:
                if line.quantity <= 0 or line.sale_total < 0:
                    raise ValidationError(_("La cantidad debe ser positiva y el total vendido no puede ser negativo."))
                line.product_id._change_stock(-line.quantity)
            sale.state = "confirmed"

    def action_cancel(self):
        for sale in self.filtered(lambda r: r.state == "confirmed"):
            for line in sale.line_ids:
                line.product_id._change_stock(line.quantity)
            sale.state = "cancel"

    def action_draft(self):
        self.filtered(lambda r: r.state == "cancel").state = "draft"

    def unlink(self):
        if any(record.state == "confirmed" for record in self):
            raise UserError(_("No puedes eliminar una venta confirmada; cancélala primero."))
        return super().unlink()


class SalesInventorySaleLine(models.Model):
    _name = "sales.inventory.sale.line"
    _description = "Producto vendido"

    sale_id = fields.Many2one("sales.inventory.sale", required=True, ondelete="cascade")
    product_id = fields.Many2one("sales.inventory.product", string="Producto", required=True)
    quantity = fields.Float(string="Cantidad", default=1, required=True, digits="Product Unit of Measure")
    available_qty = fields.Float(string="Disponible", related="product_id.stock_qty")
    suggested_price = fields.Monetary(string="Precio sugerido", related="product_id.suggested_price")
    sale_total = fields.Monetary(string="Total vendido", required=True)
    effective_unit_price = fields.Monetary(string="Precio unitario real", compute="_compute_amounts")
    unit_cost = fields.Monetary(string="Costo unitario", readonly=True)
    recovered_total = fields.Monetary(string="Recuperado", compute="_compute_amounts", store=True)
    profit_total = fields.Monetary(string="Ganancia", compute="_compute_amounts", store=True)
    currency_id = fields.Many2one(related="sale_id.currency_id")

    @api.depends("quantity", "sale_total", "unit_cost")
    def _compute_amounts(self):
        for line in self:
            line.effective_unit_price = line.sale_total / line.quantity if line.quantity else 0
            line.recovered_total = line.quantity * line.unit_cost
            line.profit_total = line.sale_total - line.recovered_total

    @api.onchange("product_id", "quantity")
    def _onchange_suggested_total(self):
        if self.product_id and self.quantity:
            self.unit_cost = self.product_id.purchase_price
            self.sale_total = self.product_id.suggested_price * self.quantity

    @api.model_create_multi
    def create(self, vals_list):
        products = self.env["sales.inventory.product"].browse(
            [vals.get("product_id") for vals in vals_list if vals.get("product_id")]
        )
        costs = {product.id: product.purchase_price for product in products}
        for vals in vals_list:
            if vals.get("product_id"):
                vals["unit_cost"] = costs[vals["product_id"]]
        return super().create(vals_list)
