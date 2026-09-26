def migrate(cr, version):
    """Conserva como presentes las verificaciones activas de la versión anterior."""
    cr.execute(
        """
        UPDATE sales_inventory_product
           SET inventory_review_status = 'present'
         WHERE inventory_verified = TRUE
           AND inventory_review_status = 'pending'
        """
    )
