from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from . import db
from .models import Client
from .forms import ClientForm
import re

clients_bp = Blueprint("clients", __name__, template_folder="templates")


@clients_bp.route("/")
@login_required
def list_clients():
    q = request.args.get("q", "").strip()
    query = Client.query
    if q:
        query = query.filter(Client.name.contains(q))
    clients = query.order_by(Client.id.desc()).all()
    return render_template("clients/list.html", clients=clients, q=q)


@clients_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_client():
    form = ClientForm()
    if form.validate_on_submit():
        phone_digits = re.sub(r"\D", "", form.phone.data or "")
        client = Client(
            name=form.name.data,
            phone=phone_digits,
            document=form.document.data,
            address=form.address.data,
        )
        db.session.add(client)
        db.session.commit()
        flash("Cliente criado com sucesso", "success")
        return redirect(url_for("clients.list_clients"))
    return render_template("clients/form.html", form=form, action="Criar")


@clients_bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def edit_client(client_id):
    client = Client.query.get_or_404(client_id)
    form = ClientForm(obj=client)
    if form.validate_on_submit():
        client.name = form.name.data
        client.phone = re.sub(r"\D", "", form.phone.data or "")
        client.document = form.document.data
        client.address = form.address.data
        db.session.commit()
        flash("Cliente atualizado", "success")
        return redirect(url_for("clients.list_clients"))
    return render_template("clients/form.html", form=form, action="Editar")


@clients_bp.route("/<int:client_id>/delete", methods=["POST"])
@login_required
def delete_client(client_id):
    client = Client.query.get_or_404(client_id)
    db.session.delete(client)
    db.session.commit()
    flash("Cliente excluído", "info")
    return redirect(url_for("clients.list_clients"))
