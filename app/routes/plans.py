from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..auth_helpers import login_required, roles_required
from ..db import execute, query_all, query_one

plans_bp = Blueprint("plans", __name__, url_prefix="/plans")


@plans_bp.route("/")
@login_required
def list_plans():
    plans = query_all("SELECT * FROM plans ORDER BY id DESC")
    return render_template("plans/list.html", plans=plans)


@plans_bp.route("/new", methods=["GET", "POST"])
@login_required
@roles_required("Superadmin", "Admin")
def new_plan():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        days_per_month = request.form.get("days_per_month", "0").strip()
        price = request.form.get("price", "0").strip()

        if not name:
            flash("El nombre del plan es obligatorio.", "danger")
            return render_template("plans/form.html")

        execute(
            "INSERT INTO plans (name, days_per_month, price, is_active) VALUES (%s, %s, %s, 1)",
            (name, int(days_per_month), float(price)),
        )
        flash("Plan creado correctamente.", "success")
        return redirect(url_for("plans.list_plans"))

    return render_template("plans/form.html")


@plans_bp.route("/renew", methods=["GET", "POST"])
@login_required
@roles_required("Superadmin", "Admin")
def renew_subscription():
    if request.method == "POST":
        document = request.form.get("document", "").strip()
        member = query_one("SELECT id FROM members WHERE document = %s", (document,))
        if not member:
            flash("No existe miembro con ese documento.", "danger")
            return redirect(url_for("plans.renew_subscription"))

        subscription = query_one(
            """
            SELECT ms.id, ms.plan_id, p.days_per_month
            FROM member_subscriptions ms
            JOIN plans p ON p.id = ms.plan_id
            WHERE ms.member_id = %s
            ORDER BY ms.id DESC
            LIMIT 1
            """,
            (member["id"],),
        )
        if not subscription:
            flash("El miembro no tiene suscripción.", "danger")
            return redirect(url_for("plans.renew_subscription"))

        today = date.today()
        end_date = date(today.year, today.month, 28)
        execute(
            """
            UPDATE member_subscriptions
            SET start_date = %s,
                end_date = %s,
                remaining_days = %s,
                status = 'active',
                updated_at = NOW()
            WHERE id = %s
            """,
            (today, end_date, subscription["days_per_month"], subscription["id"]),
        )
        flash("Plan renovado exitosamente.", "success")
        return redirect(url_for("members.list_members"))

    return render_template("subscriptions/renew.html")
