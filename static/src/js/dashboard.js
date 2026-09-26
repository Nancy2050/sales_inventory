/** @odoo-module **/

import { registry } from "@web/core/registry";
import { formatCurrency } from "@web/core/currency";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class SalesInventoryDashboard extends Component {
    static template = "sales_inventory.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.state = useState({ loading: true, data: null });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "sales.inventory.dashboard",
            "get_dashboard_data",
            []
        );
        this.state.loading = false;
    }

    formatMoney(amount) {
        return formatCurrency(amount || 0, this.state.data.currency_id);
    }

    formatQuantity(amount) {
        return new Intl.NumberFormat("es-MX", { maximumFractionDigits: 2 }).format(amount || 0);
    }

    formatCompact(amount) {
        return new Intl.NumberFormat("es-MX", {
            notation: "compact",
            maximumFractionDigits: 1,
        }).format(amount || 0);
    }

    get lineMax() {
        if (!this.state.data) {
            return 1;
        }
        return Math.max(
            1,
            ...this.state.data.monthly.flatMap((month) => [month.sales, month.profit])
        );
    }

    chartX(index) {
        const count = this.state.data.monthly.length;
        return count > 1 ? 58 + (index * 642) / (count - 1) : 379;
    }

    chartY(value) {
        return 220 - ((value || 0) / this.lineMax) * 188;
    }

    chartPoints(fieldName) {
        return this.state.data.monthly
            .map((month, index) => `${this.chartX(index)},${this.chartY(month[fieldName])}`)
            .join(" ");
    }

    get axisTicks() {
        return [4, 3, 2, 1, 0].map((step) => ({
            value: (this.lineMax * step) / 4,
            y: 220 - (188 * step) / 4,
        }));
    }

    get rankingMax() {
        return Math.max(1, ...this.state.data.products_ranking.map((product) => product.quantity));
    }

    rankingWidth(quantity) {
        return `${(quantity / this.rankingMax) * 100}%`;
    }

    get inventoryMax() {
        return Math.max(1, ...this.state.data.inventory_by_category.map((category) => category.quantity));
    }

    inventoryWidth(quantity) {
        return `${(quantity / this.inventoryMax) * 100}%`;
    }
}

registry.category("actions").add("sales_inventory.dashboard", SalesInventoryDashboard);
