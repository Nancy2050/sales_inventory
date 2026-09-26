/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatCurrency } from "@web/core/currency";
import { useService } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";

export class InventoryReview extends Component {
    static template = "sales_inventory.InventoryReview";

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            products: [], histories: [], index: 0, loading: true, refreshing: false,
            expandedReviewId: null,
        });
        this._loadSequence = 0;
        this._refreshOnFocus = () => {
            this.loadProducts({ preserveCurrent: true }).catch(() => undefined);
        };
        onWillStart(() => this.loadProducts());
        onMounted(() => {
            window.addEventListener("focus", this._refreshOnFocus);
            this._refreshInterval = window.setInterval(() => {
                if (document.visibilityState === "visible") {
                    this.loadProducts({ preserveCurrent: true }).catch(() => undefined);
                }
            }, 15000);
        });
        onWillUnmount(() => {
            this._loadSequence++;
            window.removeEventListener("focus", this._refreshOnFocus);
            window.clearInterval(this._refreshInterval);
        });
    }

    async loadProducts({ preserveCurrent = false, notify = false } = {}) {
        const sequence = ++this._loadSequence;
        const currentProductId = preserveCurrent ? this.product?.id : false;
        if (!this.state.loading) {
            this.state.refreshing = true;
        }
        let products;
        let histories;
        try {
            [products, histories] = await Promise.all([
                this.orm.searchRead(
                    "sales.inventory.product",
                    [["active", "=", true], ["stock_qty", ">", 0]],
                    [
                        "name", "code", "category_id", "stock_qty", "purchase_price",
                        "suggested_price", "currency_id", "inventory_verified",
                        "inventory_review_status", "inventory_verified_date", "write_date", "image_1024",
                    ],
                    { order: "name asc" }
                ),
                this.orm.searchRead(
                    "sales.inventory.review",
                    [],
                    [
                        "review_date", "reviewed_by", "total_products", "present_count",
                        "missing_count", "present_summary", "missing_summary",
                    ],
                    { order: "review_date desc, id desc", limit: 20 }
                ),
            ]);
        } catch (error) {
            if (sequence === this._loadSequence) {
                this.state.loading = false;
                this.state.refreshing = false;
            }
            throw error;
        }
        if (sequence !== this._loadSequence) {
            return;
        }
        this.state.products = products;
        this.state.histories = histories;
        const currentIndex = currentProductId
            ? products.findIndex((product) => product.id === currentProductId)
            : -1;
        if (currentIndex >= 0) {
            this.state.index = currentIndex;
        } else {
            const pendingIndex = products.findIndex(
                (product) => product.inventory_review_status === "pending"
            );
            this.state.index = pendingIndex >= 0 ? pendingIndex : 0;
        }
        this.state.loading = false;
        this.state.refreshing = false;
        if (notify) {
            this.notification.add(
                `${products.length} ${products.length === 1 ? "producto actualizado" : "productos actualizados"}`,
                { type: "info" }
            );
        }
    }

    refreshProducts() {
        return this.loadProducts({ preserveCurrent: true, notify: true });
    }

    get product() {
        return this.state.products[this.state.index];
    }

    get verifiedCount() {
        return this.state.products.filter(
            (product) => product.inventory_review_status === "present"
        ).length;
    }

    get missingCount() {
        return this.state.products.filter(
            (product) => product.inventory_review_status === "missing"
        ).length;
    }

    get reviewedCount() {
        return this.verifiedCount + this.missingCount;
    }

    get pendingCount() {
        return this.state.products.length - this.reviewedCount;
    }

    get progressPercent() {
        return this.state.products.length
            ? Math.round((this.reviewedCount / this.state.products.length) * 100)
            : 0;
    }

    get productImageUrl() {
        if (!this.product?.image_1024) {
            return "/web/static/img/placeholder.png";
        }
        return imageUrl("sales.inventory.product", this.product.id, "image_1024", {
            unique: this.product.write_date,
        });
    }

    formatPrice(amount) {
        return formatCurrency(amount, this.product.currency_id[0]);
    }

    previous() {
        if (this.state.index > 0) {
            this.state.index--;
        }
    }

    next() {
        if (this.state.index < this.state.products.length - 1) {
            this.state.index++;
        }
    }

    async setReviewStatus(status) {
        const product = this.product;
        const moveToNext = status !== "pending" && this.state.index < this.state.products.length - 1;
        await this.orm.call(
            "sales.inventory.product",
            "action_set_inventory_review_status",
            [],
            { product_id: product.id, status }
        );
        await this.loadProducts({ preserveCurrent: true });
        const messages = {
            present: ["Producto marcado como presente", "success"],
            missing: ["Producto marcado como ausente", "warning"],
            pending: ["Producto regresado a pendiente", "info"],
        };
        this.notification.add(messages[status][0], { type: messages[status][1] });
        if (moveToNext && this.state.index < this.state.products.length - 1) {
            this.state.index++;
        }
    }

    finishReview() {
        if (!this.state.products.length || this.pendingCount) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Finalizar revisión de inventario",
            body: `Se guardará un historial con ${this.verifiedCount} presentes y ${this.missingCount} ausentes. Después se preparará una nueva vuelta. Las existencias registradas no se modificarán.`,
            confirmLabel: "Finalizar revisión",
            confirmClass: "btn-primary",
            cancelLabel: "Cancelar",
            confirm: () => this.confirmFinishReview(),
        });
    }

    async confirmFinishReview() {
        const result = await this.orm.call(
            "sales.inventory.product",
            "action_finish_inventory_review",
            []
        );
        await this.loadProducts();
        this.state.index = 0;
        this.notification.add(
            `Revisión guardada: ${result.present_count} presentes y ${result.missing_count} ausentes`,
            { type: "success" }
        );
    }

    toggleHistory(reviewId) {
        this.state.expandedReviewId = this.state.expandedReviewId === reviewId ? null : reviewId;
    }

    historyItems(summary) {
        return (summary || "").split("\n").filter(Boolean);
    }

    formatReviewDate(value) {
        if (!value) {
            return "";
        }
        const date = new Date(`${value.replace(" ", "T")}Z`);
        return new Intl.DateTimeFormat("es-MX", {
            dateStyle: "medium",
            timeStyle: "short",
        }).format(date);
    }
}

registry.category("actions").add("sales_inventory.inventory_review", InventoryReview);
