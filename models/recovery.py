from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SalesInventoryRecovery(models.Model):
    _name = "sales.inventory.recovery"
    _description = "Liberación de capital recuperado"
    _order = "date desc, id desc"

    name = fields.Char(string="Folio", default="Nuevo", readonly=True, copy=False)
    date = fields.Date(string="Fecha", default=fields.Date.context_today, required=True)
    amount = fields.Monetary(string="Monto a liberar", required=True)
    recovered_used = fields.Monetary(string="Tomado de capital recuperado", readonly=True, copy=False)
    profit_used = fields.Monetary(string="Tomado de ganancias", readonly=True, copy=False)
    reason = fields.Char(string="Motivo", required=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id, required=True)
    state = fields.Selection([("draft", "Borrador"), ("released", "Liberado"), ("cancel", "Cancelado")], default="draft", required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code("sales.inventory.recovery") or "Nuevo"
        return super().create(vals_list)

    def action_release(self):
        dashboard = self.env.ref("sales_inventory.dashboard_main")
        for withdrawal in self:
            dashboard.invalidate_recordset()
            if withdrawal.state != "draft" or withdrawal.amount <= 0:
                raise ValidationError(_("El monto debe ser positivo."))
            available = max(dashboard.recovered_balance, 0) + max(dashboard.profit_balance, 0)
            if withdrawal.amount > available:
                raise ValidationError(
                    _("No puedes liberar más que el capital y la ganancia disponibles (%s).") % available
                )
            withdrawal.recovered_used = min(withdrawal.amount, max(dashboard.recovered_balance, 0))
            withdrawal.profit_used = withdrawal.amount - withdrawal.recovered_used
            withdrawal.state = "released"

    def action_cancel(self):
        self.filtered(lambda r: r.state == "released").state = "cancel"

    def action_draft(self):
        records = self.filtered(lambda record: record.state == "cancel")
        records.write({"state": "draft", "recovered_used": 0, "profit_used": 0})

    def unlink(self):
        if any(record.state == "released" for record in self):
            raise UserError(_("No puedes eliminar una liberación realizada; cancélala primero."))
        return super().unlink()
