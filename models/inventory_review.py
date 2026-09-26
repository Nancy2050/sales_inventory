from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SalesInventoryReview(models.Model):
    _name = "sales.inventory.review"
    _description = "Historial de revisión de inventario"
    _order = "review_date desc, id desc"

    name = fields.Char(string="Referencia", compute="_compute_name", store=True)
    review_date = fields.Datetime(string="Fecha", default=fields.Datetime.now, required=True, readonly=True)
    reviewed_by = fields.Many2one(
        "res.users", string="Finalizada por", default=lambda self: self.env.user, required=True, readonly=True
    )
    total_products = fields.Integer(string="Productos revisados", required=True, readonly=True)
    present_count = fields.Integer(string="Sí estaban", required=True, readonly=True)
    missing_count = fields.Integer(string="No estaban", required=True, readonly=True)
    present_summary = fields.Text(string="Productos presentes", readonly=True)
    missing_summary = fields.Text(string="Productos ausentes", readonly=True)
    line_ids = fields.One2many("sales.inventory.review.line", "review_id", string="Detalle", readonly=True)

    @api.depends("review_date")
    def _compute_name(self):
        """Genera una referencia legible con la fecha de cierre."""
        for review in self:
            review.name = _("Revisión %s") % (
                fields.Datetime.to_string(review.review_date) if review.review_date else ""
            )

    @api.constrains("total_products", "present_count", "missing_count")
    def _check_counts(self):
        """Valida que el resumen coincida con el total de productos revisados."""
        for review in self:
            if review.present_count + review.missing_count != review.total_products:
                raise ValidationError(_("El resumen de la revisión no coincide con el total."))


class SalesInventoryReviewLine(models.Model):
    _name = "sales.inventory.review.line"
    _description = "Detalle histórico de revisión de inventario"
    _order = "product_name, id"

    review_id = fields.Many2one("sales.inventory.review", required=True, ondelete="cascade", readonly=True)
    product_id = fields.Many2one("sales.inventory.product", string="Producto", ondelete="set null", readonly=True)
    product_name = fields.Char(string="Nombre registrado", required=True, readonly=True)
    product_code = fields.Char(string="Código registrado", required=True, readonly=True)
    stock_qty = fields.Float(string="Existencia registrada", readonly=True)
    was_present = fields.Boolean(string="Sí estaba", readonly=True)
