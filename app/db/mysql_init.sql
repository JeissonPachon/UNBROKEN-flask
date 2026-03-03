CREATE TABLE IF NOT EXISTS gym_plans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    sessions_per_month INT NOT NULL,
    price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS gym_admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO gym_plans (name, sessions_per_month, price, is_active)
SELECT 'Plan Básico', 8, 80.00, 1
WHERE NOT EXISTS (SELECT 1 FROM gym_plans WHERE name = 'Plan Básico');

INSERT INTO gym_plans (name, sessions_per_month, price, is_active)
SELECT 'Plan Intermedio', 12, 120.00, 1
WHERE NOT EXISTS (SELECT 1 FROM gym_plans WHERE name = 'Plan Intermedio');

INSERT INTO gym_plans (name, sessions_per_month, price, is_active)
SELECT 'Plan Full', 20, 180.00, 1
WHERE NOT EXISTS (SELECT 1 FROM gym_plans WHERE name = 'Plan Full');
