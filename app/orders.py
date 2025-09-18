from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from sqlalchemy import or_, func
from sqlalchemy.orm import subqueryload
from flask_login import login_required
from flask_wtf.csrf import generate_csrf
from . import db
from .models import Order, OrderItem, Client, Service, Payment
from . import printing
from .forms import OrderForm, OrderItemForm, PaymentForm, parse_money_to_float

orders_bp = Blueprint("orders", __name__, template_folder="templates")


@orders_bp.route("/")
@login_required
def list_orders():
    from datetime import datetime, timedelta
    q = (request.args.get('q') or '').strip()
    start = (request.args.get('start') or '').strip()
    end = (request.args.get('end') or '').strip()
    date_field = (request.args.get('date_field') or 'created').lower()
    if date_field not in ('created', 'delivery'):
        date_field = 'created'
    pay_filter = (request.args.get('pay') or 'all').lower()
    if pay_filter not in ('all', 'quitado', 'em_aberto'):
        pay_filter = 'all'
    # Base query with eager loads to ensure accurate totals
    qry = Order.query.options(subqueryload(Order.items), subqueryload(Order.payments))
    if q:
        # If q is numeric, allow match by ID; otherwise by client name (case-insensitive)
        try:
            q_id = int(q)
        except Exception:
            q_id = None
        qry = qry.join(Client)
        if q_id is not None:
            qry = qry.filter(or_(Order.id == q_id, func.lower(Client.name).like(f"%{q.lower()}%")))
        else:
            qry = qry.filter(func.lower(Client.name).like(f"%{q.lower()}%"))
    # Date interval filter
    if start or end:
        try:
            if date_field == 'delivery':
                # delivery_date is stored as naive local datetime (date-only semantics). Compare by DATE only.
                if start:
                    qry = qry.filter(func.date(Order.delivery_date) >= start)
                if end:
                    qry = qry.filter(func.date(Order.delivery_date) <= end)
            else:
                # created_at stored in UTC-naive; build UTC boundaries from Sao_Paulo local dates
                from datetime import timezone
                try:
                    from zoneinfo import ZoneInfo
                    tz_sp = ZoneInfo("America/Sao_Paulo")
                except Exception:
                    tz_sp = None
                def to_utc(dt_local_naive):
                    # Treat naive as Sao_Paulo local
                    if tz_sp is not None:
                        dt_local = dt_local_naive.replace(tzinfo=tz_sp)
                    else:
                        from datetime import timedelta as _td
                        dt_local = dt_local_naive.replace(tzinfo=timezone(_td(hours=-3)))
                    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)
                if start:
                    sd_local = datetime.strptime(start, "%Y-%m-%d")  # 00:00 local
                    sd_utc = to_utc(sd_local)
                    qry = qry.filter(Order.created_at >= sd_utc)
                if end:
                    ed_local = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)  # next day 00:00 local
                    ed_utc = to_utc(ed_local)
                    qry = qry.filter(Order.created_at < ed_utc)
        except Exception:
            pass
    orders = qry.order_by(Order.id.desc()).all()
    # Precompute paid, computed grand total and remaining for display
    data = []
    changed_any = False
    for o in orders:
        # Ensure persisted total matches model rules
        try:
            _recalc_total(o)
        except Exception:
            pass
        try:
            paid = sum(p.amount for p in getattr(o, 'payments', []) or [])
        except Exception:
            paid = 0.0
        grand_total = float(getattr(o, 'total', 0.0) or 0.0)
        remaining = max(0.0, grand_total - float(paid or 0))
        # Always derive display status from remaining to avoid stale stored values
        pay_status = 'quitado' if remaining <= 1e-6 else 'em_aberto'
        # Opportunistically sync stored field if differs
        if getattr(o, 'payment_status', None) != pay_status:
            try:
                o.payment_status = pay_status
                changed_any = True
            except Exception:
                pass
        # Build breakdown for tooltip
        try:
            items_total = sum(i.subtotal for i in getattr(o, 'items', []) or [])
        except Exception:
            items_total = grand_total
        d_percent = (getattr(o, 'discount_percent', 0.0) or 0.0)
        s_percent = (getattr(o, 'surcharge_percent', 0.0) or 0.0)
        percent_discount = (items_total * (d_percent / 100.0)) if d_percent > 0 else 0.0
        percent_surcharge = (items_total * (s_percent / 100.0)) if s_percent > 0 else 0.0
        fixed_discount = (getattr(o, 'discount', 0.0) or 0.0)
        fixed_surcharge = (getattr(o, 'surcharge', 0.0) or 0.0)
        data.append({
            'order': o,
            'paid': paid,
            'remaining': remaining,
            'grand_total': grand_total,
            'items_total': items_total,
            'fixed_discount': fixed_discount,
            'percent_discount': percent_discount,
            'fixed_surcharge': fixed_surcharge,
            'percent_surcharge': percent_surcharge,
            'pay_status': pay_status,
        })
    if changed_any:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    # Apply filter on computed data
    if pay_filter != 'all':
        data = [d for d in data if d['pay_status'] == pay_filter]
        orders = [d['order'] for d in data]
    # List available printers (Windows) for quick print on list page
    try:
        printers = printing.list_printers()
    except Exception:
        printers = []
    return render_template(
        "orders/list.html",
        orders=orders,
        orders_extra=data,
        pay_filter=pay_filter,
        q=q,
        start=start,
        end=end,
        csrf_token_list=generate_csrf(),
        printers=printers,
        date_field=date_field,
    )


@orders_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_order():
    form = OrderForm()
    clients = Client.query.order_by(Client.name).all()
    form.client_id.choices = [(0, "Selecione um cliente")] + [(c.id, c.name) for c in clients]
    if form.validate_on_submit():
        # Impede criar sem cliente válido
        if not form.client_id.data or int(form.client_id.data) <= 0:
            flash("Selecione um cliente.", "warning")
            return render_template("orders/form.html", form=form, action="Criar", order=None)
        order = Order(client_id=form.client_id.data, status=form.status.data, notes=form.notes.data)
        # parse campos de desconto/acréscimo unificados (moeda ou %)
        disc_raw = (form.discount.data or "").strip() if hasattr(form, 'discount') else ""
        if disc_raw.endswith('%'):
            try:
                dp = float(disc_raw[:-1].replace(',', '.'))
            except Exception:
                dp = 0.0
            dp = max(0.0, min(100.0, dp))
            order.discount_percent = dp
            order.discount = 0.0
        else:
            order.discount = parse_money_to_float(disc_raw) or 0.0
            order.discount_percent = 0.0

        sur_raw = (form.surcharge.data or "").strip() if hasattr(form, 'surcharge') else ""
        if sur_raw.endswith('%'):
            try:
                sp = float(sur_raw[:-1].replace(',', '.'))
            except Exception:
                sp = 0.0
            sp = max(0.0, min(100.0, sp))
            order.surcharge_percent = sp
            order.surcharge = 0.0
        else:
            order.surcharge = parse_money_to_float(sur_raw) or 0.0
            order.surcharge_percent = 0.0
        db.session.add(order)
        db.session.commit()
        _sync_payment_status(order)
        # Em vez de redirecionar, já renderizamos a página de edição com a área de itens
        item_form = OrderItemForm()
        services_list = Service.query.order_by(Service.name).all()
        item_form.service_id.choices = [(0, "Selecione um serviço")] + [
            (s.id, s.name) for s in services_list
        ]
        # Preencher campos monetários do cabeçalho no formato brasileiro
        form = OrderForm(obj=order)
        form.client_id.choices = [(c.id, c.name) for c in Client.query.order_by(Client.name).all()]
        if (order.discount_percent or 0) > 0:
            form.discount.data = f"{int(order.discount_percent)}%"
        else:
            form.discount.data = f"{(order.discount or 0):.2f}".replace('.', ',')
        if (order.surcharge_percent or 0) > 0:
            form.surcharge.data = f"{int(order.surcharge_percent)}%"
        else:
            form.surcharge.data = f"{(order.surcharge or 0):.2f}".replace('.', ',')
        # Payments context for a freshly created order
        pay_form = PaymentForm()
        payments = []
        paid_total = 0.0
        remaining_total = float(order.total or 0.0)
        has_entry_payment = False
        flash("Ordem criada. Agora adicione itens.", "success")
        # List available printers (Windows)
        try:
            printers = printing.list_printers()
        except Exception:
            printers = []
        return render_template(
            "orders/form.html",
            form=form,
            item_form=item_form,
            pay_form=pay_form,
            order=order,
            action="Editar",
            services_available=len(services_list) > 0,
            focus_services=True,
            service_prices={s.id: float(s.price) for s in services_list},
            services_list=services_list,
            csrf_token_inline=item_form.csrf_token.current_token if hasattr(item_form, 'csrf_token') else None,
            payments=payments,
            paid_total=paid_total,
            remaining_total=remaining_total,
            has_entry_payment=has_entry_payment,
            printers=printers,
        )
    return render_template("orders/form.html", form=form, action="Criar", order=None, services_list=[])


@orders_bp.route("/<int:order_id>/edit", methods=["GET", "POST"])
@login_required
def edit_order(order_id):
    order = Order.query.get_or_404(order_id)
    form = OrderForm(obj=order)
    form.client_id.choices = [(c.id, c.name) for c in Client.query.order_by(Client.name).all()]

    item_form = OrderItemForm()
    services_list = Service.query.order_by(Service.name).all()
    item_form.service_id.choices = [(0, "Selecione um serviço")] + [
        (s.id, s.name) for s in services_list
    ]
    # Payments
    # Always recalc grand total so discounts/acrescimos and items are reflected
    _recalc_total(order)
    pay_form = PaymentForm()
    payments = Payment.query.filter_by(order_id=order.id).order_by(Payment.created_at.asc()).all()
    # Sort for display: entrada, retirada, apos
    order_map = {'entrada': 0, 'retirada': 1, 'apos': 2}
    payments = sorted(payments, key=lambda p: order_map.get(getattr(p, 'when_type', ''), 99))
    paid_total = sum(p.amount for p in payments)
    remaining_total = max(0.0, float(order.total or 0) - float(paid_total or 0))
    has_entry_payment = any(p.when_type == 'entrada' for p in payments)
    # Printers
    try:
        printers = printing.list_printers()
    except Exception:
        printers = []

    # Build breakdown for transparency
    items_total = sum(i.subtotal for i in order.items)
    d_percent = (order.discount_percent or 0.0)
    s_percent = (order.surcharge_percent or 0.0)
    percent_discount = (items_total * (d_percent / 100.0)) if d_percent > 0 else 0.0
    percent_surcharge = (items_total * (s_percent / 100.0)) if s_percent > 0 else 0.0
    fixed_discount = order.discount or 0.0
    fixed_surcharge = order.surcharge or 0.0
    grand_total = order.total or 0.0

    # Preencher campos de desconto/acréscimo na primeira carga
    if request.method == "GET":
        if (order.discount_percent or 0) > 0:
            form.discount.data = f"{int(order.discount_percent)}%"
        else:
            form.discount.data = f"{(order.discount or 0):.2f}".replace('.', ',')
        if (order.surcharge_percent or 0) > 0:
            form.surcharge.data = f"{int(order.surcharge_percent)}%"
        else:
            form.surcharge.data = f"{(order.surcharge or 0):.2f}".replace('.', ',')
        # Prefill delivery date (YYYY-MM-DD) if present
        try:
            if getattr(order, 'delivery_date', None):
                form.delivery_date.data = order.delivery_date.date().isoformat()
        except Exception:
            pass

    # Processa adicionar item de forma independente de WTForms, para evitar falhas por placeholder/CSRF
    if request.method == "POST" and request.form.get("_action") == "add_item":
        try:
            svc_id = int(request.form.get("service_id", "0"))
        except Exception:
            svc_id = 0
        if svc_id <= 0:
            flash("Selecione um serviço válido.", "warning")
            return render_template(
                "orders/form.html",
                form=form,
                item_form=item_form,
                pay_form=pay_form,
                order=order,
                action="Editar",
                services_available=len(services_list) > 0,
                service_prices={s.id: float(s.price) for s in services_list},
                services_list=services_list,
                csrf_token_inline=item_form.csrf_token.current_token if hasattr(item_form, 'csrf_token') else None,
                payments=payments,
                paid_total=paid_total,
                remaining_total=remaining_total,
                has_entry_payment=has_entry_payment,
                printers=printers,
            )
        service = Service.query.get(svc_id)
        qty_raw = request.form.get("quantity", "1")
        try:
            qty = int(qty_raw)
            if qty < 1:
                qty = 1
        except Exception:
            qty = 1
        parsed = parse_money_to_float(request.form.get("unit_price", ""))
        unit_price = parsed if (parsed is not None and parsed > 0) else (service.price if service else 0)
        subtotal = qty * float(unit_price)
        item = OrderItem(
            order_id=order.id,
            service_id=svc_id,
            description=request.form.get("description", ""),
            quantity=qty,
            unit_price=unit_price,
            subtotal=subtotal,
        )
        db.session.add(item)
        db.session.commit()
        _recalc_total(order)
        flash("Item adicionado", "success")
        anchor = request.form.get("_anchor") or "items"
        return redirect(url_for("orders.edit_order", order_id=order.id) + f"#{anchor}")

    # Processa salvar ordem de forma independente do WTForms, para garantir redirect
    if request.method == "POST" and request.form.get("_action") == "save_order":
        if len(order.items) == 0:
            flash("Adicione pelo menos um serviço (item) à ordem antes de salvar.", "warning")
            return render_template(
                "orders/form.html",
                form=form,
                item_form=item_form,
                pay_form=pay_form,
                order=order,
                action="Editar",
                services_available=len(services_list) > 0,
                payments=payments,
                paid_total=paid_total,
                remaining_total=remaining_total,
                has_entry_payment=has_entry_payment,
                printers=printers,
            )
        # Atualiza campos do cabeçalho (cliente permanece fixo)
        status_raw = request.form.get("status")
        notes_raw = request.form.get("notes")
        if status_raw:
            order.status = status_raw
        if notes_raw is not None:
            order.notes = notes_raw
        # Delivery date: persist only when status is 'entregue'.
        # - Accept both ISO (YYYY-MM-DD) and BR (DD/MM/YYYY) formats.
        # - When status is 'entregue' and the field is empty, keep the existing date (do not clear).
        # - When status is NOT 'entregue', always clear the date.
        try:
            del_str = (request.form.get("delivery_date", "") or "").strip()
            if order.status == 'entregue':
                if del_str:
                    from datetime import datetime
                    dt = None
                    # Try ISO first
                    try:
                        dt = datetime.strptime(del_str, "%Y-%m-%d")
                    except Exception:
                        # Try BR format
                        try:
                            dt = datetime.strptime(del_str, "%d/%m/%Y")
                        except Exception:
                            dt = None
                    order.delivery_date = dt
                # If no value provided, keep existing delivery_date as-is
            else:
                order.delivery_date = None
        except Exception:
            # On unexpected error, do not crash; keep existing date if status is 'entregue',
            # otherwise ensure it's cleared.
            if order.status != 'entregue':
                order.delivery_date = None
        # Parse desconto e acréscimo (aceita moeda ou %)
        # Desconto
        disc_raw = (request.form.get("discount", "") or "").strip()
        if disc_raw.endswith('%'):
            try:
                dp = float(disc_raw[:-1].replace(',', '.'))
            except Exception:
                dp = 0.0
            dp = max(0.0, min(100.0, dp))
            order.discount_percent = dp
            order.discount = 0.0
        else:
            order.discount = parse_money_to_float(disc_raw) or 0.0
            order.discount_percent = 0.0
        # Acréscimo
        sur_raw = (request.form.get("surcharge", "") or "").strip()
        if sur_raw.endswith('%'):
            try:
                sp = float(sur_raw[:-1].replace(',', '.'))
            except Exception:
                sp = 0.0
            sp = max(0.0, min(100.0, sp))
            order.surcharge_percent = sp
            order.surcharge = 0.0
        else:
            order.surcharge = parse_money_to_float(sur_raw) or 0.0
            order.surcharge_percent = 0.0
        # Calcular total proposto com base em itens, descontos e acréscimos
        items_total = sum(i.subtotal for i in order.items)
        fixed_discount = order.discount or 0.0
        fixed_surcharge = order.surcharge or 0.0
        d_percent = (order.discount_percent or 0.0)
        s_percent = (order.surcharge_percent or 0.0)
        percent_discount = (items_total * (d_percent / 100.0)) if d_percent > 0 else 0.0
        percent_surcharge = (items_total * (s_percent / 100.0)) if s_percent > 0 else 0.0
        proposed_total = max(0.0, items_total - percent_discount - fixed_discount + fixed_surcharge + percent_surcharge)

        # Soma dos pagamentos já lançados
        try:
            paid_total_now = sum(p.amount for p in payments)
        except Exception:
            paid_total_now = 0.0

        # Regra: total pago não pode exceder o total geral
        if paid_total_now > proposed_total + 1e-6:
            flash("Total pago não pode ser maior que o Total Geral da ordem.", "warning")
            return render_template(
                "orders/form.html",
                form=form,
                item_form=item_form,
                pay_form=pay_form,
                order=order,
                action="Editar",
                services_available=len(services_list) > 0,
                services_list=services_list,
                service_prices={s.id: float(s.price) for s in services_list},
                csrf_token_inline=item_form.csrf_token.current_token if hasattr(item_form, 'csrf_token') else None,
                payments=payments,
                paid_total=paid_total_now,
                remaining_total=max(0.0, proposed_total - float(paid_total_now or 0)),
                has_entry_payment=has_entry_payment,
                printers=printers,
            )

        # Persistir total calculado e salvar
        order.total = proposed_total
        db.session.commit()
        _sync_payment_status(order)
        flash("Ordem atualizada", "success")
        return redirect(url_for("orders.list_orders"))

    # Add payment
    if request.method == "POST" and request.form.get("_action") == "add_payment":
        if not pay_form.validate_on_submit():
            flash("Verifique os dados do pagamento.", "warning")
        else:
            amt = parse_money_to_float(pay_form.amount.data)
            if not amt or amt <= 0:
                flash("Valor de pagamento inválido.", "warning")
            else:
                when = pay_form.when_type.data
                if when == 'entrada' and has_entry_payment:
                    flash("Já existe um pagamento do tipo Entrada para esta ordem.", "warning")
                else:
                    # Apply any header changes (discount/surcharge) sent via hidden fields,
                    # then recalc grand total to reflect them before validating payment cap.
                    try:
                        disc_shadow = (request.form.get("discount_shadow", "") or "").strip()
                        if disc_shadow:
                            if disc_shadow.endswith('%'):
                                try:
                                    dp = float(disc_shadow[:-1].replace(',', '.'))
                                except Exception:
                                    dp = 0.0
                                dp = max(0.0, min(100.0, dp))
                                order.discount_percent = dp
                                order.discount = 0.0
                            else:
                                order.discount = parse_money_to_float(disc_shadow) or 0.0
                                order.discount_percent = 0.0
                        sur_shadow = (request.form.get("surcharge_shadow", "") or "").strip()
                        if sur_shadow:
                            if sur_shadow.endswith('%'):
                                try:
                                    sp = float(sur_shadow[:-1].replace(',', '.'))
                                except Exception:
                                    sp = 0.0
                                sp = max(0.0, min(100.0, sp))
                                order.surcharge_percent = sp
                                order.surcharge = 0.0
                            else:
                                order.surcharge = parse_money_to_float(sur_shadow) or 0.0
                                order.surcharge_percent = 0.0
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                    # Enforce cap: do not allow payments to exceed current grand total
                    # Recalculate order total just before validating cap
                    _recalc_total(order)
                    try:
                        current_paid = sum(p.amount for p in payments)
                        remaining = max(0.0, float(order.total or 0) - float(current_paid or 0))
                    except Exception:
                        remaining = max(0.0, float(order.total or 0))
                    if amt - remaining > 1e-6:  # amt > remaining with small epsilon
                        flash(f"Valor excede o restante da ordem (restante: R$ {remaining:,.2f}).", "warning")
                        anchor = request.form.get("_anchor") or "payments"
                        return redirect(url_for("orders.edit_order", order_id=order.id) + f"#{anchor}")
                    p = Payment(
                        order_id=order.id,
                        amount=float(amt),
                        method=pay_form.method.data,
                        when_type=when,
                        note=pay_form.note.data or None,
                    )
                    db.session.add(p)
                    db.session.commit()
                    _sync_payment_status(order)
                    flash("Pagamento adicionado.", "success")
                    anchor = request.form.get("_anchor") or "payments"
                    return redirect(url_for("orders.edit_order", order_id=order.id) + f"#{anchor}")

    # Delete payment
    if request.method == "POST" and request.form.get("_action") == "delete_payment":
        pid = request.form.get("payment_id")
        try:
            pid = int(pid)
        except Exception:
            pid = 0
        if pid > 0:
            pay = Payment.query.get(pid)
            if pay and pay.order_id == order.id:
                db.session.delete(pay)
                db.session.commit()
                _sync_payment_status(order)
                flash("Pagamento removido.", "info")
                return redirect(url_for("orders.edit_order", order_id=order.id))

    return render_template(
        "orders/form.html",
        form=form,
        item_form=item_form,
        pay_form=pay_form,
        order=order,
        action="Editar",
        services_available=len(services_list) > 0,
        services_list=services_list,
        service_prices={s.id: float(s.price) for s in services_list},
        csrf_token_inline=item_form.csrf_token.current_token if hasattr(item_form, 'csrf_token') else None,
        payments=payments,
        paid_total=paid_total,
        remaining_total=remaining_total,
        has_entry_payment=has_entry_payment,
        items_total=items_total,
        fixed_discount=fixed_discount,
        percent_discount=percent_discount,
        fixed_surcharge=fixed_surcharge,
        percent_surcharge=percent_surcharge,
        grand_total=grand_total,
        printers=printers,
    )


@orders_bp.route("/<int:order_id>/delete", methods=["POST"])
@login_required
def delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()
    flash("Ordem excluída", "info")
    return redirect(url_for("orders.list_orders"))


@orders_bp.route("/<int:order_id>/print", methods=["POST"])
@login_required
def print_order(order_id):
    order = Order.query.get_or_404(order_id)
    try:
        printer_name = request.form.get("printer_name") or None
        printing.print_order_receipt(order, printer_name=printer_name)
        flash("Impressão enviada para a impressora.", "success")
    except Exception as e:
        flash(f"Falha ao imprimir: {e}", "danger")
    return redirect(url_for("orders.edit_order", order_id=order.id))


@orders_bp.route("/items/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    item = OrderItem.query.get_or_404(item_id)
    order_id = item.order_id
    db.session.delete(item)
    db.session.commit()
    order = Order.query.get(order_id)
    if order:
        _recalc_total(order)
    flash("Item removido", "info")
    anchor = request.form.get("_anchor") or "items"
    return redirect(url_for("orders.edit_order", order_id=order_id) + f"#{anchor}")



def _recalc_total(order: Order):
    items_total = sum(i.subtotal for i in order.items)
    fixed_discount = order.discount or 0.0
    fixed_surcharge = order.surcharge or 0.0
    d_percent = (order.discount_percent or 0.0)
    s_percent = (order.surcharge_percent or 0.0)
    percent_discount = (items_total * (d_percent / 100.0)) if d_percent > 0 else 0.0
    percent_surcharge = (items_total * (s_percent / 100.0)) if s_percent > 0 else 0.0
    order.total = max(0.0, items_total - percent_discount - fixed_discount + fixed_surcharge + percent_surcharge)
    db.session.commit()


def _sync_payment_status(order: Order):
    try:
        paid = sum(p.amount for p in order.payments)
    except Exception:
        paid = 0.0
    remaining = max(0.0, float(order.total or 0) - float(paid or 0))
    new_status = 'quitado' if remaining <= 1e-6 else 'em_aberto'
    if getattr(order, 'payment_status', None) != new_status:
        order.payment_status = new_status
        db.session.commit()


@orders_bp.route("/items/<int:item_id>/update", methods=["POST"])
@login_required
def update_item(item_id):
    item = OrderItem.query.get_or_404(item_id)
    order = Order.query.get_or_404(item.order_id)
    # Recuperar campos do formulário inline
    desc = request.form.get("description", "")
    qty = request.form.get("quantity", "1")
    price_str = request.form.get("unit_price", "")
    svc_id_str = request.form.get("service_id", "")
    try:
        quantity = int(qty)
        if quantity < 1:
            quantity = 1
    except Exception:
        quantity = 1
    # Atualiza serviço se enviado
    try:
        svc_id = int(svc_id_str)
        svc = Service.query.get(svc_id)
        if svc is not None:
            item.service_id = svc.id
    except Exception:
        pass
    parsed_price = parse_money_to_float(price_str)
    if parsed_price is None:
        flash("Preço unitário inválido no item.", "warning")
        return redirect(url_for("orders.edit_order", order_id=order.id))
    item.description = desc
    item.quantity = quantity
    item.unit_price = parsed_price
    item.subtotal = parsed_price * quantity
    # Calcular total proposto sem confirmar ainda
    items_total = sum(i.subtotal for i in order.items)
    fixed_discount = order.discount or 0.0
    fixed_surcharge = order.surcharge or 0.0
    d_percent = (order.discount_percent or 0.0)
    s_percent = (order.surcharge_percent or 0.0)
    percent_discount = (items_total * (d_percent / 100.0)) if d_percent > 0 else 0.0
    percent_surcharge = (items_total * (s_percent / 100.0)) if s_percent > 0 else 0.0
    proposed_total = max(0.0, items_total - percent_discount - fixed_discount + fixed_surcharge + percent_surcharge)

    # Soma dos pagamentos já lançados
    try:
        paid_total = sum((p.amount or 0.0) for p in getattr(order, 'payments', []) )
    except Exception:
        paid_total = 0.0

    # Validação: total pago não pode exceder total geral
    if paid_total > proposed_total + 1e-6:
        flash("Total pago não pode ser maior que o Total Geral da ordem.", "warning")
        return render_template(
            "orders/form.html",
            form=form,
            item_form=item_form,
            order=order,
            action="Editar",
            services_available=len(services_list) > 0,
            services_list=services_list,
            service_prices={s.id: float(s.price) for s in services_list},
            csrf_token_inline=item_form.csrf_token.current_token if hasattr(item_form, 'csrf_token') else None,
        )

    # Persistir total e salvar
    order.total = proposed_total
    db.session.commit()
    flash("Ordem atualizada", "success")
    return redirect(url_for("orders.list_orders"))
