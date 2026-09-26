# Ventas e Inventario

Módulo Odoo 19 para un pequeño negocio de reventa. Controla productos, existencias, ventas a precio real, capital recuperado, ganancias, gastos operativos, reinversión y liberaciones de capital.

## Flujo

1. Registra productos con existencia inicial, costo y precio sugerido.
2. Captura una venta con cantidad y **total realmente cobrado** por línea.
3. Al confirmar, baja el inventario y separa costo recuperado de ganancia.
4. En cada gasto eliges si se descuenta primero de capital recuperado o de ganancias.
5. Las liberaciones permiten retirar capital recuperado sin exceder el saldo.

Los borradores no modifican existencias ni saldos. Las cancelaciones revierten sus efectos.

Cuando el fondo elegido no alcanza, el sistema utiliza el otro fondo para cubrir únicamente la
diferencia, muestra una advertencia y registra el cambio de origen en el historial de la solicitud.
Cada gasto conserva el desglose **Tomado de capital recuperado** / **Tomado de ganancias**, por lo
que el origen del dinero es auditable.

Para registrar una compra cuya mercancía ya aparece en existencias, usa **Compra de inventario ya
registrada**. Este tipo descuenta el dinero según el fondo elegido, pero no vuelve a incrementar el
inventario.

### Productos nuevos en una reinversión

Si creas un producto desde la propia solicitud y capturas ahí su existencia inicial, activa
**Usar existencia inicial** en la línea del gasto. El subtotal utilizará esa existencia y la
aprobación no volverá a sumarla al inventario. Para productos que ya existían, deja la opción
desactivada y utiliza **Cantidad a agregar**.
