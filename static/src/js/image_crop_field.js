/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ImageField, imageField } from "@web/views/fields/image/image_field";
import { Component, onMounted, useRef, useState } from "@odoo/owl";

const VIEWPORT_SIZE = 380;
const OUTPUT_SIZE = 1024;

export class ProductImageCropDialog extends Component {
    static template = "sales_inventory.ProductImageCropDialog";
    static components = { Dialog };
    static props = ["close", "fileInfo", "onConfirm"];

    setup() {
        this.imageRef = useRef("cropImage");
        this.stageRef = useRef("cropStage");
        this.state = useState({
            ready: false,
            zoom: 1,
            offsetX: 0,
            offsetY: 0,
            naturalWidth: 0,
            naturalHeight: 0,
        });
        this.dragging = false;
        this.pointerX = 0;
        this.pointerY = 0;
        this.startOffsetX = 0;
        this.startOffsetY = 0;
        onMounted(() => {
            const image = this.imageRef.el;
            if (image.complete) {
                this.onImageLoad();
            }
        });
    }

    get imageSource() {
        return `data:${this.props.fileInfo.type};base64,${this.props.fileInfo.data}`;
    }

    get baseScale() {
        if (!this.state.naturalWidth || !this.state.naturalHeight) {
            return 1;
        }
        return Math.max(
            this.viewportSize / this.state.naturalWidth,
            this.viewportSize / this.state.naturalHeight
        );
    }

    get viewportSize() {
        return this.stageRef.el?.clientWidth || VIEWPORT_SIZE;
    }

    get scale() {
        return this.baseScale * Number(this.state.zoom);
    }

    get imageStyle() {
        return [
            "left: 50%",
            "top: 50%",
            `width: ${this.state.naturalWidth}px`,
            `height: ${this.state.naturalHeight}px`,
            `transform: translate(-50%, -50%) translate(${this.state.offsetX}px, ${this.state.offsetY}px) scale(${this.scale})`,
        ].join(";");
    }

    onImageLoad() {
        const image = this.imageRef.el;
        this.state.naturalWidth = image.naturalWidth;
        this.state.naturalHeight = image.naturalHeight;
        this.state.ready = true;
        this.centerImage();
    }

    getOffsetLimits() {
        return {
            x: Math.max(0, (this.state.naturalWidth * this.scale - this.viewportSize) / 2),
            y: Math.max(0, (this.state.naturalHeight * this.scale - this.viewportSize) / 2),
        };
    }

    clampOffsets() {
        const limits = this.getOffsetLimits();
        this.state.offsetX = Math.max(-limits.x, Math.min(limits.x, this.state.offsetX));
        this.state.offsetY = Math.max(-limits.y, Math.min(limits.y, this.state.offsetY));
    }

    centerImage() {
        this.state.offsetX = 0;
        this.state.offsetY = 0;
    }

    onZoomInput(event) {
        this.state.zoom = Number(event.target.value);
        this.clampOffsets();
    }

    onPointerDown(event) {
        if (!this.state.ready) {
            return;
        }
        this.dragging = true;
        this.pointerX = event.clientX;
        this.pointerY = event.clientY;
        this.startOffsetX = this.state.offsetX;
        this.startOffsetY = this.state.offsetY;
        event.currentTarget.setPointerCapture(event.pointerId);
    }

    onPointerMove(event) {
        if (!this.dragging) {
            return;
        }
        this.state.offsetX = this.startOffsetX + event.clientX - this.pointerX;
        this.state.offsetY = this.startOffsetY + event.clientY - this.pointerY;
        this.clampOffsets();
    }

    onPointerUp(event) {
        this.dragging = false;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
        }
    }

    confirmCrop() {
        const image = this.imageRef.el;
        const scale = this.scale;
        const renderedWidth = this.state.naturalWidth * scale;
        const renderedHeight = this.state.naturalHeight * scale;
        const viewportSize = this.viewportSize;
        const left = (viewportSize - renderedWidth) / 2 + this.state.offsetX;
        const top = (viewportSize - renderedHeight) / 2 + this.state.offsetY;
        const sourceSize = viewportSize / scale;
        const sourceX = Math.max(
            0,
            Math.min(this.state.naturalWidth - sourceSize, -left / scale)
        );
        const sourceY = Math.max(
            0,
            Math.min(this.state.naturalHeight - sourceSize, -top / scale)
        );

        const canvas = document.createElement("canvas");
        canvas.width = OUTPUT_SIZE;
        canvas.height = OUTPUT_SIZE;
        const context = canvas.getContext("2d");
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, OUTPUT_SIZE, OUTPUT_SIZE);
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = "high";
        context.drawImage(
            image,
            sourceX,
            sourceY,
            sourceSize,
            sourceSize,
            0,
            0,
            OUTPUT_SIZE,
            OUTPUT_SIZE
        );
        this.props.onConfirm(canvas.toDataURL("image/jpeg", 0.94).split(",")[1]);
        this.props.close();
    }
}

export class ImageCropField extends ImageField {
    static template = "sales_inventory.ImageCropField";

    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.state.rotating = false;
    }

    async onFileUploaded(info) {
        this.dialog.add(ProductImageCropDialog, {
            fileInfo: info,
            onConfirm: (data) => {
                this.state.isValid = true;
                this.lastURL = undefined;
                this.props.record.update({ [this.props.name]: data });
            },
        });
    }

    async rotateImage() {
        if (!this.props.record.data[this.props.name] || this.state.rotating) {
            return;
        }
        this.state.rotating = true;
        try {
            const image = document.createElement("img");
            image.src = this.getUrl(this.props.name);
            await new Promise((resolve, reject) => {
                image.addEventListener("load", resolve, { once: true });
                image.addEventListener("error", reject, { once: true });
            });
            const canvas = document.createElement("canvas");
            canvas.width = image.naturalHeight;
            canvas.height = image.naturalWidth;
            const context = canvas.getContext("2d");
            context.fillStyle = "#ffffff";
            context.fillRect(0, 0, canvas.width, canvas.height);
            context.translate(canvas.width / 2, canvas.height / 2);
            context.rotate(Math.PI / 2);
            context.imageSmoothingEnabled = true;
            context.imageSmoothingQuality = "high";
            context.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);
            this.lastURL = undefined;
            await this.props.record.update({
                [this.props.name]: canvas.toDataURL("image/jpeg", 0.94).split(",")[1],
            });
        } finally {
            this.state.rotating = false;
        }
    }
}

registry.category("fields").add("image_crop", {
    ...imageField,
    component: ImageCropField,
    displayName: _t("Image with crop editor"),
});
