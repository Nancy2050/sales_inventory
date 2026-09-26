def migrate(cr, version):
    """Assign the historical default source without changing existing allocations."""
    cr.execute(
        """
        UPDATE sales_inventory_expense
           SET fund_source = CASE
               WHEN expense_type = 'fixed' THEN 'profit'
               ELSE 'capital'
           END
        """
    )
