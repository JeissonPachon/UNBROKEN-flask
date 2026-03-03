import os
from datetime import date, timedelta
from functools import wraps
from urllib.parse import parse_qs, unquote, urlparse

import pymysql
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


def load_env_file(env_path):
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
load_env_file(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'unbroken-secret-key')

app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', 'admin')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'unbroken')
app.config['MYSQL_PORT'] = int(os.getenv('MYSQL_PORT', '3306'))
app.config['MYSQL_URL'] = os.getenv('MYSQL_URL', '').strip()
app.config['MYSQL_SSL_DISABLED'] = os.getenv('MYSQL_SSL_DISABLED', '0') == '1'
app.config['DATABASE_URL'] = os.getenv('DATABASE_URL', os.getenv('SUPABASE_DB_URL', '')).strip()
app.config['DB_ENGINE'] = 'postgres' if app.config['DATABASE_URL'].lower().startswith(('postgres://', 'postgresql://')) else 'mysql'
app.config['AUTO_SCHEMA_INIT'] = os.getenv('AUTO_SCHEMA_INIT', '0' if os.getenv('VERCEL') else '1') == '1'

ADMIN_USER = os.getenv('ADMIN_USER', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')


def format_cop(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0

    rounded = int(round(amount))
    formatted = f"{rounded:,}".replace(",", ".")
    return f"$ {formatted} COP"


app.jinja_env.filters['cop'] = format_cop


def is_postgres():
    return app.config.get('DB_ENGINE') == 'postgres'


def sql_today():
    return 'CURRENT_DATE' if is_postgres() else 'CURDATE()'


def sql_true():
    return 'TRUE' if is_postgres() else '1'


def active_value():
    return True if is_postgres() else 1


def scalar_from_row(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def get_db_connection():
    if is_postgres():
        if not app.config['DATABASE_URL']:
            raise RuntimeError('DATABASE_URL no configurada para PostgreSQL/Supabase.')
        if psycopg is None:
            raise RuntimeError('Falta instalar psycopg para conectar con Supabase.')
        return psycopg.connect(app.config['DATABASE_URL'], row_factory=dict_row, connect_timeout=10)

    if app.config['MYSQL_URL']:
        parsed = urlparse(app.config['MYSQL_URL'])
        query = parse_qs(parsed.query)
        ssl_disabled_by_url = (query.get('ssl', [''])[0].lower() == 'false')
        ssl_disabled = app.config['MYSQL_SSL_DISABLED'] or ssl_disabled_by_url

        connect_kwargs = {
            'host': parsed.hostname or app.config['MYSQL_HOST'],
            'user': unquote(parsed.username) if parsed.username else app.config['MYSQL_USER'],
            'password': unquote(parsed.password) if parsed.password else app.config['MYSQL_PASSWORD'],
            'database': parsed.path.lstrip('/') or app.config['MYSQL_DB'],
            'port': int(parsed.port or app.config['MYSQL_PORT']),
            'charset': 'utf8mb4',
            'autocommit': False,
            'connect_timeout': 10,
        }
        if not ssl_disabled:
            connect_kwargs['ssl'] = {}
        return pymysql.connect(**connect_kwargs)

    return pymysql.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB'],
        port=app.config['MYSQL_PORT'],
        charset='utf8mb4',
        autocommit=False,
        connect_timeout=10,
    )


def query_all(sql, params=()):
    conn = get_db_connection()
    cursor = conn.cursor() if is_postgres() else conn.cursor(pymysql.cursors.DictCursor)
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def query_one(sql, params=()):
    conn = get_db_connection()
    cursor = conn.cursor() if is_postgres() else conn.cursor(pymysql.cursors.DictCursor)
    cursor.execute(sql, params)
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def execute(sql, params=()):
    conn = get_db_connection()
    cursor = conn.cursor()
    normalized_sql = sql.strip().lower()
    needs_returning_id = is_postgres() and normalized_sql.startswith('insert into') and 'returning' not in normalized_sql
    sql_to_run = f"{sql.rstrip().rstrip(';')} RETURNING id" if needs_returning_id else sql
    cursor.execute(sql_to_run, params)

    last_id = None
    if needs_returning_id:
        inserted = cursor.fetchone()
        if isinstance(inserted, dict):
            last_id = inserted.get('id')
        elif inserted:
            last_id = inserted[0]

    conn.commit()
    if last_id is None:
        last_id = getattr(cursor, 'lastrowid', None)
    row_count = cursor.rowcount if cursor.rowcount is not None else 0
    cursor.close()
    conn.close()
    return last_id, row_count


def current_role():
    return session.get('user_role', '')


def ensure_schema():
    if app.config.get('SCHEMA_READY'):
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    if is_postgres():
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_plans (
                id SERIAL PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                sessions_per_month INT NOT NULL,
                price NUMERIC(10, 2) NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_members (
                id SERIAL PRIMARY KEY,
                full_name VARCHAR(180) NOT NULL,
                document VARCHAR(50) NOT NULL UNIQUE,
                phone VARCHAR(50),
                email VARCHAR(120),
                injuries TEXT,
                conditions_text TEXT,
                emergency_contact_name VARCHAR(180),
                emergency_contact_phone VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_subscriptions (
                id SERIAL PRIMARY KEY,
                member_id INT NOT NULL,
                plan_id INT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                remaining_sessions INT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_sub_member FOREIGN KEY (member_id) REFERENCES gym_members(id),
                CONSTRAINT fk_sub_plan FOREIGN KEY (plan_id) REFERENCES gym_plans(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_admins (
                id SERIAL PRIMARY KEY,
                username VARCHAR(120) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_session_logs (
                id SERIAL PRIMARY KEY,
                member_id INT NULL,
                member_document VARCHAR(50),
                member_name VARCHAR(180),
                subscription_id INT NULL,
                action VARCHAR(40) NOT NULL,
                remaining_before INT NULL,
                remaining_after INT NULL,
                performed_by VARCHAR(120) NOT NULL,
                performed_role VARCHAR(20) NOT NULL,
                notes VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute("ALTER TABLE gym_admins ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'admin'")
    else:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_plans (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                sessions_per_month INT NOT NULL,
                price DECIMAL(10, 2) NOT NULL DEFAULT 0,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_members (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(180) NOT NULL,
                document VARCHAR(50) NOT NULL UNIQUE,
                phone VARCHAR(50),
                email VARCHAR(120),
                injuries TEXT,
                conditions_text TEXT,
                emergency_contact_name VARCHAR(180),
                emergency_contact_phone VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_subscriptions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                member_id INT NOT NULL,
                plan_id INT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                remaining_sessions INT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_sub_member FOREIGN KEY (member_id) REFERENCES gym_members(id),
                CONSTRAINT fk_sub_plan FOREIGN KEY (plan_id) REFERENCES gym_plans(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_admins (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(120) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gym_session_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                member_id INT NULL,
                member_document VARCHAR(50),
                member_name VARCHAR(180),
                subscription_id INT NULL,
                action VARCHAR(40) NOT NULL,
                remaining_before INT NULL,
                remaining_after INT NULL,
                performed_by VARCHAR(120) NOT NULL,
                performed_role VARCHAR(20) NOT NULL,
                notes VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'gym_admins'
              AND COLUMN_NAME = 'role'
            """,
            (app.config['MYSQL_DB'],),
        )
        role_column_exists = scalar_from_row(cursor.fetchone()) > 0
        if not role_column_exists:
            cursor.execute("ALTER TABLE gym_admins ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'admin' AFTER password_hash")

    cursor.execute("UPDATE gym_admins SET role = 'admin' WHERE role IS NULL OR role = ''")
    cursor.execute('SELECT COUNT(*) FROM gym_plans')
    plans_count = scalar_from_row(cursor.fetchone())
    if plans_count == 0:
        cursor.execute(
            """
            INSERT INTO gym_plans (name, sessions_per_month, price)
            VALUES
                ('Plan Básico', 8, 80.00),
                ('Plan Intermedio', 12, 120.00),
                ('Plan Full', 20, 180.00)
            """
        )

    cursor.execute('SELECT COUNT(*) FROM gym_admins')
    admins_count = scalar_from_row(cursor.fetchone())
    if admins_count == 0:
        cursor.execute(
            'INSERT INTO gym_admins (username, password_hash, role, is_active) VALUES (%s, %s, %s, %s)',
            (ADMIN_USER, generate_password_hash(ADMIN_PASSWORD), 'admin', active_value()),
        )
    else:
        cursor.execute('SELECT id FROM gym_admins WHERE username = %s', (ADMIN_USER,))
        env_admin = cursor.fetchone()
        if not env_admin:
            cursor.execute(
                'INSERT INTO gym_admins (username, password_hash, role, is_active) VALUES (%s, %s, %s, %s)',
                (ADMIN_USER, generate_password_hash(ADMIN_PASSWORD), 'admin', active_value()),
            )

    conn.commit()
    cursor.close()
    conn.close()
    app.config['SCHEMA_READY'] = True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('is_authenticated'):
            flash('Debes iniciar sesión.', 'danger')
            return redirect(url_for('index'))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('is_authenticated'):
            flash('Debes iniciar sesión.', 'danger')
            return redirect(url_for('index'))
        if current_role() != 'admin':
            flash('No tienes permisos para esta acción.', 'danger')
            return redirect(url_for('dashboard'))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def before_request():
    if app.config.get('AUTO_SCHEMA_INIT'):
        ensure_schema()

@app.route('/')
def index ():
    active_plans = []
    try:
        active_plans = query_all(
            f'SELECT id, name, sessions_per_month, price FROM gym_plans WHERE is_active = {sql_true()} ORDER BY id ASC'
        )
    except Exception:
        active_plans = []
    data = {
        'titulo': 'UNBROKEN',
        'bienvenida': 'Bienvenido a UNBROKEN',
        'planes': active_plans,
        'admin_logged': bool(session.get('is_authenticated')),
    }
    return render_template('index.html', data=data)


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        session['is_authenticated'] = True
        session['is_admin'] = True
        session['user_role'] = 'admin'
        session['admin_user'] = username
        flash('Sesión iniciada.', 'success')
        return redirect(url_for('dashboard'))

    try:
        admin = query_one(
            f'SELECT id, username, password_hash, role FROM gym_admins WHERE username = %s AND is_active = {sql_true()}',
            (username,),
        )
    except Exception:
        flash('No se pudo validar el usuario en este momento. Verifica la conexión de base de datos.', 'danger')
        return redirect(url_for('index'))

    is_valid = False
    user_role = 'admin'
    if admin and check_password_hash(admin['password_hash'], password):
        is_valid = True
        user_role = admin.get('role', 'admin')

    if is_valid:
        session['is_authenticated'] = True
        session['is_admin'] = user_role == 'admin'
        session['user_role'] = user_role
        session['admin_user'] = username
        flash('Sesión iniciada correctamente.', 'success')
    else:
        flash('Credenciales inválidas.', 'danger')

    return redirect(url_for('index'))


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Sesión cerrada.', 'info')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    user_role = current_role()
    can_manage = user_role == 'admin'
    members_count = 0
    active_count = 0
    plans = []
    recent_members = []
    recent_session_logs = []
    monthly_members_raw = []
    monthly_sessions_raw = []

    months = []
    month_cursor = date.today().replace(day=1)
    for _ in range(11, -1, -1):
        months.insert(0, month_cursor)
        if month_cursor.month == 1:
            month_cursor = month_cursor.replace(year=month_cursor.year - 1, month=12)
        else:
            month_cursor = month_cursor.replace(month=month_cursor.month - 1)
    months = months[-12:]

    month_labels = [f"{m.month:02d}/{m.year}" for m in months]
    month_keys = [f"{m.year}-{m.month:02d}" for m in months]
    month_members = [0 for _ in month_keys]
    month_sessions = [0 for _ in month_keys]
    trailing_avg = [0 for _ in month_keys]
    drop_alert = None

    try:
        members_count_row = query_one('SELECT COUNT(*) AS total FROM gym_members')
        members_count = members_count_row['total'] if members_count_row else 0

        active_count_row = query_one(
            f"""
            SELECT COUNT(*) AS total
            FROM gym_subscriptions
            WHERE status = 'active' AND remaining_sessions > 0 AND end_date >= {sql_today()}
            """
        )
        active_count = active_count_row['total'] if active_count_row else 0

        plans = query_all(f'SELECT id, name FROM gym_plans WHERE is_active = {sql_true()} ORDER BY name')
        recent_members = query_all(
            """
            SELECT m.id, m.full_name, m.document, s.remaining_sessions, s.status, p.name AS plan_name
            FROM gym_members m
            LEFT JOIN gym_subscriptions s ON s.id = (
                SELECT gs.id
                FROM gym_subscriptions gs
                WHERE gs.member_id = m.id
                ORDER BY gs.id DESC
                LIMIT 1
            )
            LEFT JOIN gym_plans p ON p.id = s.plan_id
            ORDER BY m.id DESC
            LIMIT 10
            """
        )
        recent_session_logs = query_all(
            """
            SELECT id, member_document, member_name, action,
                   remaining_before, remaining_after,
                   performed_by, performed_role, created_at
            FROM gym_session_logs
            ORDER BY id DESC
            LIMIT 15
            """
        )
        if is_postgres():
            monthly_members_raw = query_all(
                """
                SELECT to_char(created_at, 'YYYY-MM') AS ym, COUNT(*) AS total
                FROM gym_members
                WHERE created_at >= (CURRENT_DATE - INTERVAL '12 months')
                GROUP BY to_char(created_at, 'YYYY-MM')
                ORDER BY ym ASC
                """
            )
            monthly_sessions_raw = query_all(
                """
                SELECT to_char(created_at, 'YYYY-MM') AS ym, COUNT(*) AS total
                FROM gym_session_logs
                WHERE action = 'session_discount'
                  AND created_at >= (CURRENT_DATE - INTERVAL '12 months')
                GROUP BY to_char(created_at, 'YYYY-MM')
                ORDER BY ym ASC
                """
            )
        else:
            monthly_members_raw = query_all(
                """
                SELECT DATE_FORMAT(created_at, '%%Y-%%m') AS ym, COUNT(*) AS total
                FROM gym_members
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
                GROUP BY DATE_FORMAT(created_at, '%%Y-%%m')
                ORDER BY ym ASC
                """
            )
            monthly_sessions_raw = query_all(
                """
                SELECT DATE_FORMAT(created_at, '%%Y-%%m') AS ym, COUNT(*) AS total
                FROM gym_session_logs
                WHERE action = 'session_discount'
                  AND created_at >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
                GROUP BY DATE_FORMAT(created_at, '%%Y-%%m')
                ORDER BY ym ASC
                """
            )

        members_map = {row['ym']: int(row['total']) for row in monthly_members_raw}
        sessions_map = {row['ym']: int(row['total']) for row in monthly_sessions_raw}

        month_members = [members_map.get(key, 0) for key in month_keys]
        month_sessions = [sessions_map.get(key, 0) for key in month_keys]

        trailing_avg = []
        for idx in range(len(month_sessions)):
            start = max(0, idx - 2)
            window = month_sessions[start:idx + 1]
            trailing_avg.append(round(sum(window) / len(window), 2) if window else 0)

        current_month_sessions = month_sessions[-1] if month_sessions else 0
        previous_three = month_sessions[-4:-1] if len(month_sessions) >= 4 else month_sessions[:-1]
        previous_three_avg = round(sum(previous_three) / len(previous_three), 2) if previous_three else 0
        if previous_three_avg > 0:
            drop_pct = round(((previous_three_avg - current_month_sessions) / previous_three_avg) * 100, 1)
            if drop_pct >= 20:
                drop_alert = {
                    'drop_pct': drop_pct,
                    'current': current_month_sessions,
                    'avg': previous_three_avg,
                }
    except Exception:
        flash('No hay conexión con la base de datos. El panel se muestra en modo limitado.', 'warning')

    lookup_document = request.args.get('document', '').strip()
    member_lookup = None
    if lookup_document:
        try:
            member_lookup = query_one(
                """
                SELECT m.full_name,
                       m.document,
                       s.remaining_sessions,
                       s.status,
                       s.end_date,
                       p.name AS plan_name
                FROM gym_members m
                LEFT JOIN gym_subscriptions s ON s.id = (
                    SELECT gs.id
                    FROM gym_subscriptions gs
                    WHERE gs.member_id = m.id
                    ORDER BY gs.id DESC
                    LIMIT 1
                )
                LEFT JOIN gym_plans p ON p.id = s.plan_id
                WHERE m.document = %s
                """,
                (lookup_document,),
            )
        except Exception:
            member_lookup = None

    return render_template(
        'dashboard.html',
        members_count=members_count,
        active_count=active_count,
        plans=plans,
        recent_members=recent_members,
        recent_session_logs=recent_session_logs,
        month_labels=month_labels,
        month_members=month_members,
        month_sessions=month_sessions,
        trailing_avg=trailing_avg,
        drop_alert=drop_alert,
        lookup_document=lookup_document,
        member_lookup=member_lookup,
        user_role=user_role,
        can_manage=can_manage,
    )


@app.route('/members')
@admin_required
def members_list():
    members = []
    try:
        members = query_all(
            """
            SELECT m.id, m.full_name, m.document, m.phone, m.email,
                   m.injuries, m.conditions_text,
                   m.emergency_contact_name, m.emergency_contact_phone,
                   s.remaining_sessions, s.status, s.end_date, p.name AS plan_name
            FROM gym_members m
            LEFT JOIN gym_subscriptions s ON s.id = (
                SELECT gs.id
                FROM gym_subscriptions gs
                WHERE gs.member_id = m.id
                ORDER BY gs.id DESC
                LIMIT 1
            )
            LEFT JOIN gym_plans p ON p.id = s.plan_id
            ORDER BY m.id DESC
            """
        )
    except Exception:
        flash('No hay conexión con la base de datos. La vista de miembros está en modo limitado.', 'warning')
    return render_template('members_list.html', members=members)


@app.route('/members/new', methods=['GET', 'POST'])
@admin_required
def members_new():
    plans = []
    try:
        plans = query_all(f'SELECT id, name, sessions_per_month FROM gym_plans WHERE is_active = {sql_true()} ORDER BY name')
    except Exception:
        flash('No hay conexión con la base de datos. No es posible cargar planes en este momento.', 'warning')

    if request.method == 'POST':
        if not plans:
            flash('No se pudo registrar el miembro porque no hay conexión a base de datos.', 'danger')
            return redirect(url_for('members_list'))

        full_name = request.form.get('full_name', '').strip()
        document = request.form.get('document', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        injuries = request.form.get('injuries', '').strip()
        conditions_text = request.form.get('conditions_text', '').strip()
        emergency_name = request.form.get('emergency_contact_name', '').strip()
        emergency_phone = request.form.get('emergency_contact_phone', '').strip()
        plan_id = request.form.get('plan_id', '').strip()

        if not full_name or not document or not plan_id:
            flash('Nombre, documento y plan son obligatorios.', 'danger')
            return render_template('members_form.html', plans=plans)

        plan = query_one(f'SELECT id, sessions_per_month FROM gym_plans WHERE id = %s AND is_active = {sql_true()}', (plan_id,))
        if not plan:
            flash('Plan inválido.', 'danger')
            return render_template('members_form.html', plans=plans)

        member = query_one('SELECT id FROM gym_members WHERE document = %s', (document,))
        if member:
            member_id = member['id']
            execute(
                """
                UPDATE gym_members
                SET full_name = %s,
                    phone = %s,
                    email = %s,
                    injuries = %s,
                    conditions_text = %s,
                    emergency_contact_name = %s,
                    emergency_contact_phone = %s
                WHERE id = %s
                """,
                (full_name, phone, email, injuries, conditions_text, emergency_name, emergency_phone, member_id),
            )
        else:
            member_id, _ = execute(
                """
                INSERT INTO gym_members
                (full_name, document, phone, email, injuries, conditions_text, emergency_contact_name, emergency_contact_phone)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (full_name, document, phone, email, injuries, conditions_text, emergency_name, emergency_phone),
            )

        execute(
            "UPDATE gym_subscriptions SET status = 'cancelled' WHERE member_id = %s AND status = 'active'",
            (member_id,),
        )

        start_date = date.today()
        end_date = start_date + timedelta(days=30)
        execute(
            """
            INSERT INTO gym_subscriptions (member_id, plan_id, start_date, end_date, remaining_sessions, status)
            VALUES (%s, %s, %s, %s, %s, 'active')
            """,
            (member_id, plan['id'], start_date, end_date, plan['sessions_per_month']),
        )
        flash('Miembro registrado y plan asignado correctamente.', 'success')
        return redirect(url_for('members_list'))

    return render_template('members_form.html', plans=plans)


@app.route('/members/<int:member_id>/delete', methods=['POST'])
@admin_required
def members_delete(member_id):
    member = query_one('SELECT id, full_name FROM gym_members WHERE id = %s', (member_id,))
    if not member:
        flash('Miembro no encontrado.', 'danger')
        return redirect(url_for('members_list'))

    execute('DELETE FROM gym_subscriptions WHERE member_id = %s', (member_id,))
    execute('DELETE FROM gym_members WHERE id = %s', (member_id,))
    flash(f"Miembro {member['full_name']} eliminado correctamente.", 'success')
    return redirect(url_for('members_list'))


@app.route('/subscriptions/use-session', methods=['POST'])
@login_required
def use_session():
    document = request.form.get('document', '').strip()
    if not document:
        flash('Debes enviar el documento.', 'danger')
        return redirect(url_for('dashboard'))

    member = query_one('SELECT id, full_name, document FROM gym_members WHERE document = %s', (document,))
    if not member:
        flash('No existe un miembro con ese documento.', 'danger')
        return redirect(url_for('dashboard'))

    subscription = query_one(
                f"""
        SELECT id, remaining_sessions
        FROM gym_subscriptions
        WHERE member_id = %s
          AND status = 'active'
                    AND end_date >= {sql_today()}
        ORDER BY id DESC
        LIMIT 1
        """,
        (member['id'],),
    )
    if not subscription:
        flash('El miembro no tiene suscripción activa.', 'danger')
        return redirect(url_for('dashboard'))

    if subscription['remaining_sessions'] <= 0:
        flash('El miembro ya no tiene sesiones disponibles.', 'warning')
        return redirect(url_for('dashboard'))

    new_remaining = subscription['remaining_sessions'] - 1
    new_status = 'active' if new_remaining > 0 else 'expired'
    execute(
        'UPDATE gym_subscriptions SET remaining_sessions = %s, status = %s WHERE id = %s',
        (new_remaining, new_status, subscription['id']),
    )
    execute(
        """
        INSERT INTO gym_session_logs
        (member_id, member_document, member_name, subscription_id, action,
         remaining_before, remaining_after, performed_by, performed_role, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            member['id'],
            member['document'],
            member['full_name'],
            subscription['id'],
            'session_discount',
            subscription['remaining_sessions'],
            new_remaining,
            session.get('admin_user', 'desconocido'),
            current_role() or 'admin',
            'Descuento de sesión por ingreso',
        ),
    )
    flash(f'Sesión registrada. Sesiones restantes: {new_remaining}.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/subscriptions/renew', methods=['POST'])
@admin_required
def renew_subscription():
    document = request.form.get('document', '').strip()
    plan_id = request.form.get('plan_id', '').strip()

    member = query_one('SELECT id FROM gym_members WHERE document = %s', (document,))
    if not member:
        flash('No existe un miembro con ese documento.', 'danger')
        return redirect(url_for('dashboard'))

    if not plan_id:
        latest = query_one(
            'SELECT plan_id FROM gym_subscriptions WHERE member_id = %s ORDER BY id DESC LIMIT 1',
            (member['id'],),
        )
        plan_id = latest['plan_id'] if latest else None

    plan = query_one(f'SELECT id, sessions_per_month FROM gym_plans WHERE id = %s AND is_active = {sql_true()}', (plan_id,))
    if not plan:
        flash('Plan inválido para renovación.', 'danger')
        return redirect(url_for('dashboard'))

    execute(
        "UPDATE gym_subscriptions SET status = 'cancelled' WHERE member_id = %s AND status = 'active'",
        (member['id'],),
    )

    start_date = date.today()
    end_date = start_date + timedelta(days=30)
    execute(
        """
        INSERT INTO gym_subscriptions (member_id, plan_id, start_date, end_date, remaining_sessions, status)
        VALUES (%s, %s, %s, %s, %s, 'active')
        """,
        (member['id'], plan['id'], start_date, end_date, plan['sessions_per_month']),
    )
    flash('Suscripción renovada correctamente.', 'success')
    return redirect(url_for('members_list'))


@app.route('/subscriptions/cancel', methods=['POST'])
@admin_required
def cancel_subscription():
    document = request.form.get('document', '').strip()
    member = query_one('SELECT id FROM gym_members WHERE document = %s', (document,))
    if not member:
        flash('No existe un miembro con ese documento.', 'danger')
        return redirect(url_for('dashboard'))

    _, affected = execute(
        "UPDATE gym_subscriptions SET status = 'cancelled' WHERE member_id = %s AND status = 'active'",
        (member['id'],),
    )
    if affected == 0:
        flash('No había licencia activa para cancelar.', 'warning')
    else:
        flash('Licencia cancelada correctamente.', 'success')
    return redirect(url_for('members_list'))


@app.route('/settings/plans')
@admin_required
def settings_plans():
    plans = []
    staff_users = []
    try:
        plans = query_all('SELECT * FROM gym_plans ORDER BY id DESC')
        staff_users = query_all(
            """
            SELECT id, username, is_active, created_at
            FROM gym_admins
            WHERE role = 'staff'
            ORDER BY id DESC
            """
        )
    except Exception:
        flash('No hay conexión con la base de datos. Configuración en modo limitado.', 'warning')
    return render_template('plans_settings.html', plans=plans, staff_users=staff_users)


@app.route('/settings/plans/create', methods=['POST'])
@admin_required
def settings_plans_create():
    name = request.form.get('name', '').strip()
    sessions_per_month = request.form.get('sessions_per_month', '0').strip()
    price = request.form.get('price', '0').strip()

    if not name:
        flash('El nombre del plan es obligatorio.', 'danger')
        return redirect(url_for('settings_plans'))

    execute(
        'INSERT INTO gym_plans (name, sessions_per_month, price, is_active) VALUES (%s, %s, %s, %s)',
        (name, int(sessions_per_month), float(price), active_value()),
    )
    flash('Plan creado correctamente.', 'success')
    return redirect(url_for('settings_plans'))


@app.route('/settings/plans/<int:plan_id>/edit', methods=['POST'])
@admin_required
def settings_plans_edit(plan_id):
    name = request.form.get('name', '').strip()
    sessions_per_month = request.form.get('sessions_per_month', '0').strip()
    price = request.form.get('price', '0').strip()

    if not name:
        flash('El nombre del plan es obligatorio.', 'danger')
        return redirect(url_for('settings_plans'))

    execute(
        'UPDATE gym_plans SET name = %s, sessions_per_month = %s, price = %s WHERE id = %s',
        (name, int(sessions_per_month), float(price), plan_id),
    )
    flash('Plan actualizado correctamente.', 'success')
    return redirect(url_for('settings_plans'))


@app.route('/settings/plans/<int:plan_id>/toggle', methods=['POST'])
@admin_required
def settings_plans_toggle(plan_id):
    plan = query_one('SELECT is_active FROM gym_plans WHERE id = %s', (plan_id,))
    if not plan:
        flash('Plan no encontrado.', 'danger')
        return redirect(url_for('settings_plans'))

    new_state = (not bool(plan['is_active'])) if is_postgres() else (0 if plan['is_active'] else 1)
    execute('UPDATE gym_plans SET is_active = %s WHERE id = %s', (new_state, plan_id))
    flash('Estado del plan actualizado.', 'success')
    return redirect(url_for('settings_plans'))


@app.route('/settings/plans/<int:plan_id>/delete', methods=['POST'])
@admin_required
def settings_plans_delete(plan_id):
    used = query_one('SELECT COUNT(*) AS total FROM gym_subscriptions WHERE plan_id = %s', (plan_id,))
    if used and used['total'] > 0:
        flash('No se puede eliminar un plan con historial de suscripciones.', 'warning')
        return redirect(url_for('settings_plans'))

    execute('DELETE FROM gym_plans WHERE id = %s', (plan_id,))
    flash('Plan eliminado.', 'success')
    return redirect(url_for('settings_plans'))


@app.route('/settings/admin/password', methods=['POST'])
@login_required
def settings_admin_password():
    current_password = request.form.get('current_password', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    if not current_password or not new_password or not confirm_password:
        flash('Todos los campos de contraseña son obligatorios.', 'danger')
        return redirect(url_for('settings_plans'))

    if len(new_password) < 6:
        flash('La nueva contraseña debe tener al menos 6 caracteres.', 'danger')
        return redirect(url_for('settings_plans'))

    if new_password != confirm_password:
        flash('La confirmación no coincide con la nueva contraseña.', 'danger')
        return redirect(url_for('settings_plans'))

    username = session.get('admin_user')
    admin = query_one(f'SELECT id, password_hash FROM gym_admins WHERE username = %s AND is_active = {sql_true()}', (username,))
    if not admin:
        flash('Usuario admin no encontrado.', 'danger')
        return redirect(url_for('settings_plans'))

    if not check_password_hash(admin['password_hash'], current_password):
        flash('La contraseña actual es incorrecta.', 'danger')
        return redirect(url_for('settings_plans'))

    execute(
        'UPDATE gym_admins SET password_hash = %s WHERE id = %s',
        (generate_password_hash(new_password), admin['id']),
    )
    flash('Contraseña actualizada correctamente.', 'success')
    return redirect(url_for('settings_plans'))


@app.route('/settings/staff/create', methods=['POST'])
@admin_required
def settings_staff_create():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        flash('Usuario y contraseña son obligatorios para el encargado.', 'danger')
        return redirect(url_for('settings_plans'))

    if len(password) < 6:
        flash('La contraseña del encargado debe tener al menos 6 caracteres.', 'danger')
        return redirect(url_for('settings_plans'))

    exists = query_one('SELECT id FROM gym_admins WHERE username = %s', (username,))
    if exists:
        flash('Ese usuario ya existe.', 'danger')
        return redirect(url_for('settings_plans'))

    execute(
        'INSERT INTO gym_admins (username, password_hash, role, is_active) VALUES (%s, %s, %s, %s)',
        (username, generate_password_hash(password), 'staff', active_value()),
    )
    flash('Encargado creado correctamente.', 'success')
    return redirect(url_for('settings_plans'))


@app.route('/settings/staff/<int:user_id>/toggle', methods=['POST'])
@admin_required
def settings_staff_toggle(user_id):
    user = query_one('SELECT id, role, is_active FROM gym_admins WHERE id = %s', (user_id,))
    if not user or user['role'] != 'staff':
        flash('Encargado no encontrado.', 'danger')
        return redirect(url_for('settings_plans'))

    new_state = (not bool(user['is_active'])) if is_postgres() else (0 if user['is_active'] else 1)
    execute('UPDATE gym_admins SET is_active = %s WHERE id = %s', (new_state, user_id))
    flash('Estado del encargado actualizado.', 'success')
    return redirect(url_for('settings_plans'))


@app.route('/settings/staff/<int:user_id>/delete', methods=['POST'])
@admin_required
def settings_staff_delete(user_id):
    user = query_one('SELECT id, role, username FROM gym_admins WHERE id = %s', (user_id,))
    if not user or user['role'] != 'staff':
        flash('Encargado no encontrado.', 'danger')
        return redirect(url_for('settings_plans'))

    execute('DELETE FROM gym_admins WHERE id = %s', (user_id,))
    flash(f"Encargado {user['username']} eliminado.", 'success')
    return redirect(url_for('settings_plans'))

@app.route('/contacto/<nombre>/<int:edad>')
def contacto(nombre, edad):
    data = {
        'titulo': 'Contacto',
        'nombre': nombre,
        'edad': edad
    }
    return render_template('contacto.html', data=data)


@app.route('/miembro-qr/<document>')
def member_qr(document):
    member = query_one('SELECT full_name, document FROM gym_members WHERE document = %s', (document,))
    if not member:
        return redirect(url_for('index'))

    return render_template('member_qr.html', member=member)


@app.route('/db-test')
def db_test():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if is_postgres():
            cursor.execute('SELECT current_database() AS db_name')
        else:
            cursor.execute('SELECT DATABASE() AS db_name')
        db_row = cursor.fetchone()

        if is_postgres():
            cursor.execute("SELECT to_regclass('public.gym_members') AS table_name")
            tabla_miembros = cursor.fetchone()
            cursor.execute("SELECT to_regclass('public.gym_plans') AS table_name")
            tabla_planes = cursor.fetchone()
            cursor.execute("SELECT to_regclass('public.gym_subscriptions') AS table_name")
            tabla_subs = cursor.fetchone()
        else:
            cursor.execute('SHOW TABLES LIKE %s', ('gym_members',))
            tabla_miembros = cursor.fetchone()
            cursor.execute('SHOW TABLES LIKE %s', ('gym_plans',))
            tabla_planes = cursor.fetchone()
            cursor.execute('SHOW TABLES LIKE %s', ('gym_subscriptions',))
            tabla_subs = cursor.fetchone()

        cursor.close()
        conn.close()

        return {
            'ok': True,
            'database': scalar_from_row(db_row),
            'tabla_miembros': bool(scalar_from_row(tabla_miembros)),
            'tabla_planes': bool(scalar_from_row(tabla_planes)),
            'tabla_suscripciones': bool(scalar_from_row(tabla_subs)),
        }
    except Exception as e:
        return {
            'ok': False,
            'error': str(e)
        }, 500

def pagina_no_encontrada(error):
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.register_error_handler(404, pagina_no_encontrada)
    app.run(debug=True) #esto nos sirve para poder ver los cambios sin tener que reiniciarlo