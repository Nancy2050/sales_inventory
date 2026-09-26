import base64

from odoo import Command, api, fields, models, _
from odoo.exceptions import ValidationError


class SalesInventoryCategory(models.Model):
    _name = "sales.inventory.category"
    _description = "Categoría de producto"
    _order = "name"

    name = fields.Char(required=True)
    color = fields.Integer()
    active = fields.Boolean(default=True)

    _name_unique = models.UniqueIndex("(name)", "La categoría ya existe.")


class SalesInventoryProduct(models.Model):
    _name = "sales.inventory.product"
    _inherit = ["image.mixin"]
    _description = "Producto"
    _order = "name"

    name = fields.Char(string="Artículo", required=True)
    code = fields.Char(string="Código", required=True, index=True)
    category_id = fields.Many2one("sales.inventory.category", string="Categoría")
    stock_qty = fields.Float(string="Existencia actual", default=0, digits="Product Unit of Measure", readonly=True)
    initial_qty = fields.Float(string="Existencia inicial", default=0, digits="Product Unit of Measure")
    purchase_price = fields.Monetary(string="Precio de compra", required=True)
    suggested_price = fields.Monetary(string="Precio sugerido", required=True)
    investment_total = fields.Monetary(string="Inversión actual", compute="_compute_totals")
    suggested_total = fields.Monetary(string="Venta potencial", compute="_compute_totals")
    inventory_verified = fields.Boolean(string="Inventario verificado", copy=False)
    inventory_review_status = fields.Selection(
        [("pending", "Pendiente"), ("present", "Sí estaba"), ("missing", "No estaba")],
        string="Estado de revisión",
        default="pending",
        required=True,
        copy=False,
    )
    inventory_verified_date = fields.Datetime(string="Última verificación", readonly=True, copy=False)
    inventory_verified_by = fields.Many2one("res.users", string="Verificado por", readonly=True, copy=False)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id, required=True)
    active = fields.Boolean(default=True)

    _code_unique = models.UniqueIndex("(code)", "El código del producto debe ser único.")
    _prices_positive = models.Constraint(
        "CHECK (purchase_price >= 0 AND suggested_price >= 0 AND initial_qty >= 0 AND stock_qty >= 0)",
        "Las cantidades y precios no pueden ser negativos.",
    )

    @api.depends("stock_qty", "purchase_price", "suggested_price")
    def _compute_totals(self):
        for product in self:
            product.investment_total = product.stock_qty * product.purchase_price
            product.suggested_total = product.stock_qty * product.suggested_price

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["stock_qty"] = vals.get("initial_qty", 0)
        return super().create(vals_list)

    def write(self, vals):
        if "stock_qty" in vals and not self.env.context.get("allow_stock_change"):
            raise ValidationError(_("La existencia solo puede cambiar mediante ventas o reinversiones."))
        if "initial_qty" in vals and any(product.stock_qty != product.initial_qty for product in self):
            raise ValidationError(_("La existencia inicial no puede cambiar después de tener movimientos."))
        result = super().write(vals)
        if "initial_qty" in vals:
            super(SalesInventoryProduct, self.with_context(allow_stock_change=True)).write({"stock_qty": vals["initial_qty"]})
        return result

    def _change_stock(self, quantity):
        self.ensure_one()
        new_quantity = self.stock_qty + quantity
        if new_quantity < 0:
            raise ValidationError(_("No hay existencia suficiente de %s.") % self.display_name)
        self.with_context(allow_stock_change=True).stock_qty = new_quantity

    def action_mark_inventory_verified(self):
        self.write({
            "inventory_verified": True,
            "inventory_review_status": "present",
            "inventory_verified_date": fields.Datetime.now(),
            "inventory_verified_by": self.env.user.id,
        })

    def action_clear_inventory_verified(self):
        self.write({
            "inventory_verified": False,
            "inventory_review_status": "pending",
            "inventory_verified_date": False,
            "inventory_verified_by": False,
        })

    def action_mark_inventory_missing(self):
        """Marca los productos como ausentes durante la revisión actual."""
        self.write({
            "inventory_verified": False,
            "inventory_review_status": "missing",
            "inventory_verified_date": fields.Datetime.now(),
            "inventory_verified_by": self.env.user.id,
        })

    @api.model
    def action_set_inventory_review_status(self, product_id, status):
        """Actualiza el resultado físico de un producto en la revisión actual."""
        if status not in ("pending", "present", "missing"):
            raise ValidationError(_("El estado de revisión no es válido."))
        product = self.browse(product_id).exists()
        if not product:
            raise ValidationError(_("El producto ya no existe."))
        if status == "present":
            product.action_mark_inventory_verified()
        elif status == "missing":
            product.action_mark_inventory_missing()
        else:
            product.action_clear_inventory_verified()
        return True

    @api.model
    def action_finish_inventory_review(self):
        """Cierra la vuelta, conserva sus resultados y prepara la siguiente revisión."""
        products = self.search([
            ("active", "=", True),
            ("stock_qty", ">", 0),
        ], order="name")
        if not products:
            raise ValidationError(_("No hay productos con existencia para revisar."))
        pending = products.filtered(lambda product: product.inventory_review_status == "pending")
        if pending:
            raise ValidationError(_("Aún faltan %s productos por revisar.") % len(pending))

        present = products.filtered(lambda product: product.inventory_review_status == "present")
        missing = products.filtered(lambda product: product.inventory_review_status == "missing")
        review = self.env["sales.inventory.review"].create({
            "total_products": len(products),
            "present_count": len(present),
            "missing_count": len(missing),
            "present_summary": "\n".join(f"{product.code} — {product.name}" for product in present),
            "missing_summary": "\n".join(f"{product.code} — {product.name}" for product in missing),
            "line_ids": [
                Command.create({
                    "product_id": product.id,
                    "product_name": product.name,
                    "product_code": product.code,
                    "stock_qty": product.stock_qty,
                    "was_present": product.inventory_review_status == "present",
                })
                for product in products
            ],
        })
        products.action_clear_inventory_verified()
        return {
            "id": review.id,
            "present_count": review.present_count,
            "missing_count": review.missing_count,
        }

    @api.model
    def action_reset_inventory_review(self):
        products = self.search([
            ("active", "=", True),
            ("stock_qty", ">", 0),
            ("inventory_review_status", "!=", "pending"),
        ])
        products.action_clear_inventory_verified()
        return len(products)

    def action_export_catalog_pdf(self):
        products = self
        if not products:
            products = self.search([("active", "=", True)], order="name")
        return self.env.ref(
            "sales_inventory.action_report_product_catalog"
        ).report_action(products)

    @api.model
    def pdf_b64_text(self, value):
        """Keep Unicode out of the HTML byte stream consumed by wkhtmltopdf."""
        return base64.b64encode(str(value or "").encode("utf-8")).decode("ascii")
