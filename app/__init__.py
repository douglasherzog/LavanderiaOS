from flask import Flask, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from werkzeug.security import generate_password_hash
import os

# Global extensions

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"


def create_app():
    app = Flask(__name__)

    # Basic config
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance")
    os.makedirs(db_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        os.environ.get("DATABASE_URL")
        or f"sqlite:///{os.path.join(db_path, 'lavanderia.db')}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)

    from .models import User

    # Blueprints
    from .auth import auth_bp
    from .users import users_bp
    from .clients import clients_bp
    from .services import services_bp
    from .orders import orders_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(clients_bp, url_prefix="/clients")
    app.register_blueprint(services_bp, url_prefix="/services")
    app.register_blueprint(orders_bp, url_prefix="/orders")

    @app.route("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        # Build dashboard context
        try:
            from sqlalchemy import func
            from .models import Order, Payment, Client
            # Timezone helpers
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            try:
                from zoneinfo import ZoneInfo
                tz_sp = ZoneInfo("America/Sao_Paulo")
            except Exception:
                tz_sp = None
            def to_utc_naive(dt_local_naive: _dt) -> _dt:
                if tz_sp is not None:
                    dt_local = dt_local_naive.replace(tzinfo=tz_sp)
                else:
                    dt_local = dt_local_naive.replace(tzinfo=_tz(_td(hours=-3)))
                return dt_local.astimezone(_tz.utc).replace(tzinfo=None)
            # Today boundaries in local Sao_Paulo
            now_local = _dt.now()
            today_local = _dt(year=now_local.year, month=now_local.month, day=now_local.day)
            today_utc_start = to_utc_naive(today_local)
            today_utc_end = to_utc_naive(today_local + _td(days=1))
            # Orders created today (created_at in UTC-naive range)
            today_orders = (
                db.session.query(func.count(Order.id))
                .filter(Order.created_at >= today_utc_start, Order.created_at < today_utc_end)
                .scalar()
            ) or 0
            # Open orders by payment_status
            open_orders = (db.session.query(func.count(Order.id)).filter(Order.payment_status == 'em_aberto').scalar()) or 0
            # Deliveries today: compare by DATE only on delivery_date
            sd = today_local.strftime("%Y-%m-%d")
            deliveries_today = (
                db.session.query(func.count(Order.id))
                .filter(func.date(Order.delivery_date) == sd)
                .scalar()
            ) or 0
            # Revenue last 7 days based on payments created_at within local range
            start7_local = today_local - _td(days=6)  # include today and previous 6 days
            start7_utc = to_utc_naive(start7_local)
            end7_utc = today_utc_end
            revenue_7d = (
                db.session.query(func.coalesce(func.sum(Payment.amount), 0.0))
                .filter(Payment.created_at >= start7_utc, Payment.created_at < end7_utc)
                .scalar()
            ) or 0.0
            # Recent orders with client, latest 8
            recent_orders = (
                Order.query.join(Client).add_columns(Client.name)
                .order_by(Order.id.desc()).limit(8).with_entities(Order).all()
            )
            # Paid today: distinct orders that are quitado and had any payment today
            paid_today = (
                db.session.query(func.count(func.distinct(Payment.order_id)))
                .join(Order, Order.id == Payment.order_id)
                .filter(Payment.created_at >= today_utc_start, Payment.created_at < today_utc_end)
                .filter(Order.payment_status == 'quitado')
                .scalar()
            ) or 0
            # New clients in last 7 days (local)
            new_clients_7d = (
                db.session.query(func.count(Client.id))
                .filter(Client.created_at >= start7_utc, Client.created_at < end7_utc)
                .scalar()
            ) or 0
            # Build 7-day trends for Orders created and Revenue by payment date
            labels, orders_series, revenue_series = [], [], []
            for i in range(6, -1, -1):
                d_local = today_local - _td(days=i)
                d_start_utc = to_utc_naive(_dt(d_local.year, d_local.month, d_local.day))
                d_end_utc = to_utc_naive(_dt(d_local.year, d_local.month, d_local.day) + _td(days=1))
                cnt = (
                    db.session.query(func.count(Order.id))
                    .filter(Order.created_at >= d_start_utc, Order.created_at < d_end_utc)
                    .scalar()
                ) or 0
                rev = (
                    db.session.query(func.coalesce(func.sum(Payment.amount), 0.0))
                    .filter(Payment.created_at >= d_start_utc, Payment.created_at < d_end_utc)
                    .scalar()
                ) or 0.0
                labels.append(d_local.strftime('%d/%m'))
                orders_series.append(int(cnt))
                revenue_series.append(float(rev))
            metrics = {
                'today_orders': int(today_orders),
                'open_orders': int(open_orders),
                'today_deliveries': int(deliveries_today),
                'revenue_7d': float(revenue_7d),
                'paid_today': int(paid_today),
                'new_clients_7d': int(new_clients_7d),
            }
            trends = {
                'labels': labels,
                'orders': orders_series,
                'revenue': revenue_series,
            }
        except Exception:
            metrics = {'today_orders': 0, 'open_orders': 0, 'today_deliveries': 0, 'revenue_7d': 0.0, 'paid_today': 0, 'new_clients_7d': 0}
            recent_orders = []
            trends = {'labels': [], 'orders': [], 'revenue': []}
        return render_template("dashboard.html", metrics=metrics, recent_orders=recent_orders, trends=trends)

    @app.template_filter('phone_br')
    def phone_br(value):
        try:
            s = ''.join(ch for ch in (value or '') if ch.isdigit())
            if len(s) == 11:
                # (##) #####-####
                return f"({s[0:2]}) {s[2:7]}-{s[7:11]}"
            if len(s) == 10:
                # (##) ####-####
                return f"({s[0:2]}) {s[2:6]}-{s[6:10]}"
            if len(s) > 2:
                return f"({s[0:2]}) {s[2:]}"
            return s
        except Exception:
            return value

    @app.template_filter('money_br')
    def money_br(value):
        try:
            v = float(value or 0)
            # Format like 1.234,56
            s = f"{v:,.2f}"
            return s.replace(',', 'X').replace('.', ',').replace('X', '.')
        except Exception:
            return "0,00"

    @app.template_filter('date_br')
    def date_br(value):
        """Format a date or datetime as DD/MM/YYYY without timezone conversion.
        Useful for delivery dates that are date-like to avoid TZ shifts.
        """
        try:
            if value is None:
                return ""
            d = getattr(value, 'date', None)
            if callable(d):
                value = value.date()
            return value.strftime("%d/%m/%Y")
        except Exception:
            try:
                return str(value)
            except Exception:
                return ""

    @app.template_filter('datetime_br')
    def datetime_br(value, fmt: str = "%d/%m/%Y %H:%M"):
        try:
            from datetime import timezone
            try:
                from zoneinfo import ZoneInfo  # Python 3.9+
                tz_sp = ZoneInfo("America/Sao_Paulo")
            except Exception:
                tz_sp = None
            dt = value
            if not dt:
                return ""
            # Assume stored in UTC if naive
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if tz_sp is not None:
                dt = dt.astimezone(tz_sp)
            else:
                # Fallback: manual offset -03:00 (no DST handling)
                from datetime import timedelta
                dt = dt.astimezone(timezone(timedelta(hours=-3)))
            return dt.strftime(fmt)
        except Exception:
            try:
                return value.strftime(fmt)
            except Exception:
                return ""

    # Create DB and default admin
    with app.app_context():
        db.create_all()
        # Light migration: ensure new columns exist in SQLite
        try:
            from sqlalchemy import text
            # Check columns in 'order' table
            cols = db.session.execute(text("PRAGMA table_info('order');")).fetchall()
            col_names = {c[1] for c in cols}
            if 'discount' not in col_names:
                db.session.execute(text("ALTER TABLE 'order' ADD COLUMN discount FLOAT DEFAULT 0.0"))
            if 'surcharge' not in col_names:
                db.session.execute(text("ALTER TABLE 'order' ADD COLUMN surcharge FLOAT DEFAULT 0.0"))
            if 'discount_percent' not in col_names:
                db.session.execute(text("ALTER TABLE 'order' ADD COLUMN discount_percent FLOAT DEFAULT 0.0"))
            if 'surcharge_percent' not in col_names:
                db.session.execute(text("ALTER TABLE 'order' ADD COLUMN surcharge_percent FLOAT DEFAULT 0.0"))
            if 'delivery_date' not in col_names:
                db.session.execute(text("ALTER TABLE 'order' ADD COLUMN delivery_date DATETIME"))
            if 'payment_status' not in col_names:
                db.session.execute(text("ALTER TABLE 'order' ADD COLUMN payment_status VARCHAR(20) DEFAULT 'em_aberto'"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        if not User.query.filter_by(username="admin").first():
            admin = User(
                username="admin",
                full_name="Administrador",
                role="admin",
                password_hash=generate_password_hash("admin"),
            )
            db.session.add(admin)
            db.session.commit()

    return app
