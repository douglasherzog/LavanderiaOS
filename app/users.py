from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from werkzeug.security import generate_password_hash
from . import db
from .models import User
from .forms import UserCreateForm, UserEditForm

users_bp = Blueprint("users", __name__, template_folder="templates")


@users_bp.route("/")
@login_required
def list_users():
    users = User.query.order_by(User.id.desc()).all()
    return render_template("users/list.html", users=users)


@users_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_user():
    form = UserCreateForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("Usuário já existe", "warning")
        else:
            user = User(
                username=form.username.data,
                full_name=form.full_name.data,
                role=form.role.data,
                password_hash=generate_password_hash(form.password.data),
            )
            db.session.add(user)
            db.session.commit()
            flash("Usuário criado com sucesso", "success")
            return redirect(url_for("users.list_users"))
    return render_template("users/form.html", form=form, action="Criar")


@users_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = UserEditForm(obj=user)
    if form.validate_on_submit():
        user.username = form.username.data
        user.full_name = form.full_name.data
        user.role = form.role.data
        if form.password.data:
            user.password_hash = generate_password_hash(form.password.data)
        db.session.commit()
        flash("Usuário atualizado", "success")
        return redirect(url_for("users.list_users"))
    return render_template("users/form.html", form=form, action="Editar")


@users_bp.route("/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash("Usuário excluído", "info")
    return redirect(url_for("users.list_users"))
