CREATE TABLE IF NOT EXISTS gym_plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    sessions_per_month INT NOT NULL,
    price NUMERIC(10, 2) NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
);

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
);

CREATE TABLE IF NOT EXISTS gym_admins (
    id SERIAL PRIMARY KEY,
    username VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_subscriptions_updated_at ON gym_subscriptions;
CREATE TRIGGER trg_subscriptions_updated_at
BEFORE UPDATE ON gym_subscriptions
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_admins_updated_at ON gym_admins;
CREATE TRIGGER trg_admins_updated_at
BEFORE UPDATE ON gym_admins
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

INSERT INTO gym_plans (name, sessions_per_month, price, is_active)
SELECT 'Plan Básico', 8, 80.00, TRUE
WHERE NOT EXISTS (SELECT 1 FROM gym_plans WHERE name = 'Plan Básico');

INSERT INTO gym_plans (name, sessions_per_month, price, is_active)
SELECT 'Plan Intermedio', 12, 120.00, TRUE
WHERE NOT EXISTS (SELECT 1 FROM gym_plans WHERE name = 'Plan Intermedio');

INSERT INTO gym_plans (name, sessions_per_month, price, is_active)
SELECT 'Plan Full', 20, 180.00, TRUE
WHERE NOT EXISTS (SELECT 1 FROM gym_plans WHERE name = 'Plan Full');
