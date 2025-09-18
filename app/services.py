from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from . import db
from .models import Service
from .forms import ServiceForm, parse_money_to_float

services_bp = Blueprint("services", __name__, template_folder="templates")


@services_bp.route("/")
@login_required
def list_services():
    services = Service.query.order_by(Service.id.desc()).all()
    return render_template("services/list.html", services=services)


@services_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_service():
    form = ServiceForm()
    if form.validate_on_submit():
        price_float = parse_money_to_float(form.price.data)
        if price_float is None:
            flash("Preço inválido. Utilize formato como 29,90.", "warning")
        else:
            service = Service(
                name=form.name.data,
                price=price_float,
                unit=form.unit.data or "peca",
            )
            db.session.add(service)
            db.session.commit()
            flash("Serviço criado com sucesso", "success")
            return redirect(url_for("services.list_services"))
    return render_template("services/form.html", form=form, action="Criar")


@services_bp.route("/<int:service_id>/edit", methods=["GET", "POST"])
@login_required
def edit_service(service_id):
    service = Service.query.get_or_404(service_id)
    form = ServiceForm(obj=service)
    # WTForms com obj usa getattr; formata preço manualmente em GET
    if request.method == "GET":
        form.price.data = f"{service.price:.2f}".replace('.', ',')
    if form.validate_on_submit():
        price_float = parse_money_to_float(form.price.data)
        if price_float is None:
            flash("Preço inválido. Utilize formato como 29,90.", "warning")
        else:
            service.name = form.name.data
            service.price = price_float
            service.unit = form.unit.data or "peca"
            db.session.commit()
            flash("Serviço atualizado", "success")
            return redirect(url_for("services.list_services"))
    return render_template("services/form.html", form=form, action="Editar")


@services_bp.route("/<int:service_id>/delete", methods=["POST"])
@login_required
def delete_service(service_id):
    service = Service.query.get_or_404(service_id)
    db.session.delete(service)
    db.session.commit()
    flash("Serviço excluído", "info")
    return redirect(url_for("services.list_services"))
