"""
Database Module for Fire Safety Equipment Register
Schema Design:
- locations: Physical locations in the building
- equipment_types: Types of safety equipment
- equipment: Individual equipment units
- inspections: History of all inspections (never overwritten)
- equipment_audit_log: History of changes to equipment records
"""

import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
import os

_default_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire_safety.db')
# Vercel's project root is read-only; use the writable /tmp directory instead.
DATABASE = _default_db if os.access(os.path.dirname(os.path.abspath(__file__)), os.W_OK) else '/tmp/fire_safety.db'


@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_db():
    """Initialize database with all tables"""
    with get_db() as conn:
        # Locations entity
        conn.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                location_id INTEGER PRIMARY KEY AUTOINCREMENT,
                building TEXT NOT NULL,
                floor TEXT NOT NULL,
                room TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(building, floor, room)
            )
        """)

        # Equipment Types entity
        conn.execute("""
            CREATE TABLE IF NOT EXISTS equipment_types (
                type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_name TEXT NOT NULL UNIQUE,
                default_interval_months INTEGER NOT NULL DEFAULT 12,
                description TEXT
            )
        """)

        # Equipment entity - main register
        # CHANGE 1: serial_number has a UNIQUE constraint — the database will
        # refuse any INSERT that tries to use a serial number already in use.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS equipment (
                equipment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id INTEGER NOT NULL,
                location_id INTEGER NOT NULL,
                serial_number TEXT NOT NULL UNIQUE,
                manufacturer TEXT NOT NULL,
                installation_date DATE NOT NULL,
                current_status TEXT DEFAULT 'active' CHECK(current_status IN ('active', 'inactive', 'decommissioned')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (type_id) REFERENCES equipment_types(type_id),
                FOREIGN KEY (location_id) REFERENCES locations(location_id)
            )
        """)

        # Inspections history - never overwritten, each inspection is a new record
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inspections (
                inspection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                inspection_date DATE NOT NULL,
                inspector_name TEXT NOT NULL,
                result TEXT DEFAULT 'pass' CHECK(result IN ('pass', 'fail', 'needs_repair')),
                notes TEXT,
                next_due_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id) ON DELETE CASCADE
            )
        """)

        # Equipment audit log - history of changes to equipment records
        conn.execute("""
            CREATE TABLE IF NOT EXISTS equipment_audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                changed_field TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_by TEXT,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id) ON DELETE CASCADE
            )
        """)

        # Users table for Google Email & standard login authentication
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                picture TEXT,
                auth_provider TEXT DEFAULT 'google',
                role TEXT DEFAULT 'Safety Inspector',
                status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'Active'")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE users ADD COLUMN password TEXT")
        except Exception:
            pass


        # Hazards & Incident Reporting table for Safety Inspector
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hazards (
                hazard_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                equipment_id INTEGER,
                severity TEXT DEFAULT 'Medium' CHECK(severity IN ('Low', 'Medium', 'High', 'Critical')),
                status TEXT DEFAULT 'Open' CHECK(status IN ('Open', 'In Progress', 'Resolved', 'Verified')),
                suggested_action TEXT,
                corrective_action TEXT,
                reported_by TEXT NOT NULL,
                verified_by TEXT,
                reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                FOREIGN KEY (location_id) REFERENCES locations(location_id),
                FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id) ON DELETE SET NULL
            )
        """)

        # Compliance Audits table for Compliance Auditor
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audits (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_title TEXT NOT NULL,
                audit_type TEXT DEFAULT 'Internal' CHECK(audit_type IN ('Internal', 'External', 'Regulatory')),
                auditor_id INTEGER NOT NULL,
                auditor_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                compliance_score REAL DEFAULT 100.0,
                status TEXT DEFAULT 'Completed' CHECK(status IN ('Scheduled', 'In Progress', 'Completed', 'Passed', 'Failed')),
                findings TEXT,
                recommendations TEXT,
                audit_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (auditor_id) REFERENCES users(user_id)
            )
        """)

        # System Logs table for System Administrator security & performance audit
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT,
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inspections_equipment ON inspections(equipment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inspections_date ON inspections(inspection_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_equipment_location ON equipment(location_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_equipment_type ON equipment(type_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hazards_status ON hazards(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audits_date ON audits(audit_date)")

        print("Database initialized successfully.")


def get_equipment_with_status():
    """Get all equipment with current inspection status and next due date"""
    with get_db() as conn:
        query = """
            SELECT 
                e.equipment_id,
                e.serial_number,
                e.manufacturer,
                e.installation_date,
                e.current_status,
                et.type_name,
                et.default_interval_months,
                l.building,
                l.floor,
                l.room,
                i.inspection_date as last_inspection_date,
                i.next_due_date,
                i.inspector_name as last_inspector,
                i.result as last_result,
                CASE 
                    WHEN i.next_due_date < DATE('now') THEN 'overdue'
                    WHEN i.next_due_date <= DATE('now', '+30 days') THEN 'approaching'
                    ELSE 'good'
                END as urgency_status,
                CASE 
                    WHEN i.next_due_date < DATE('now') THEN 0
                    WHEN i.next_due_date <= DATE('now', '+30 days') THEN 1
                    ELSE 2
                END as urgency_order
            FROM equipment e
            JOIN equipment_types et ON e.type_id = et.type_id
            JOIN locations l ON e.location_id = l.location_id
            LEFT JOIN inspections i ON i.equipment_id = e.equipment_id
            AND i.inspection_id = (
                SELECT inspection_id FROM inspections 
                WHERE equipment_id = e.equipment_id 
                ORDER BY inspection_date DESC LIMIT 1
            )
            WHERE e.current_status = 'active'
            ORDER BY urgency_order ASC, i.next_due_date ASC
        """
        return conn.execute(query).fetchall()

def get_equipment_by_id(equipment_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT e.*, et.type_name, et.default_interval_months,
                   l.building, l.floor, l.room
            FROM equipment e
            JOIN equipment_types et ON e.type_id = et.type_id
            JOIN locations l ON e.location_id = l.location_id
            WHERE e.equipment_id = ?
        """, (equipment_id,)).fetchone()

def get_inspection_history(equipment_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT * FROM inspections 
            WHERE equipment_id = ? 
            ORDER BY inspection_date DESC
        """, (equipment_id,)).fetchall()

def add_equipment(type_id, location_id, serial_number, manufacturer, installation_date):
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO equipment (type_id, location_id, serial_number, manufacturer, installation_date)
            VALUES (?, ?, ?, ?, ?)
        """, (type_id, location_id, serial_number, manufacturer, installation_date))
        return cursor.lastrowid

def record_inspection(equipment_id, inspection_date, inspector_name, result, notes, next_due_date):
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO inspections (equipment_id, inspection_date, inspector_name, result, notes, next_due_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (equipment_id, inspection_date, inspector_name, result, notes, next_due_date))
        return cursor.lastrowid

def calculate_next_due_date(last_inspection_date, interval_months):
    """Calculate next due date based on inspection interval"""
    from dateutil.relativedelta import relativedelta
    inspection_date = datetime.strptime(last_inspection_date, '%Y-%m-%d')
    next_due = inspection_date + relativedelta(months=interval_months)
    return next_due.strftime('%Y-%m-%d')

def get_all_locations():
    with get_db() as conn:
        return conn.execute("SELECT * FROM locations ORDER BY building, floor, room").fetchall()

def get_all_equipment_types():
    with get_db() as conn:
        return conn.execute("SELECT * FROM equipment_types ORDER BY type_name").fetchall()

def search_equipment(search_term=None, status_filter=None, type_filter=None):
    """Search and filter equipment"""
    with get_db() as conn:
        query = """
            SELECT 
                e.equipment_id, e.serial_number, e.manufacturer, e.installation_date,
                et.type_name, et.default_interval_months,
                l.building, l.floor, l.room,
                i.inspection_date as last_inspection_date,
                i.next_due_date,
                CASE 
                    WHEN i.next_due_date < DATE('now') THEN 'overdue'
                    WHEN i.next_due_date <= DATE('now', '+30 days') THEN 'approaching'
                    ELSE 'good'
                END as urgency_status,
                CASE 
                    WHEN i.next_due_date < DATE('now') THEN 0
                    WHEN i.next_due_date <= DATE('now', '+30 days') THEN 1
                    ELSE 2
                END as urgency_order
            FROM equipment e
            JOIN equipment_types et ON e.type_id = et.type_id
            JOIN locations l ON e.location_id = l.location_id
            LEFT JOIN inspections i ON i.equipment_id = e.equipment_id
            AND i.inspection_id = (
                SELECT inspection_id FROM inspections 
                WHERE equipment_id = e.equipment_id 
                ORDER BY inspection_date DESC LIMIT 1
            )
            WHERE e.current_status = 'active'
        """
        params = []

        if search_term:
            query += " AND (e.serial_number LIKE ? OR l.building LIKE ? OR l.room LIKE ?)"
            term = f"%{search_term}%"
            params.extend([term, term, term])

        if type_filter:
            query += " AND et.type_id = ?"
            params.append(type_filter)

        if status_filter:
            query += " AND CASE WHEN i.next_due_date < DATE('now') THEN 'overdue' WHEN i.next_due_date <= DATE('now', '+30 days') THEN 'approaching' ELSE 'good' END = ?"
            params.append(status_filter)

        query += " ORDER BY urgency_order ASC, i.next_due_date ASC"

        return conn.execute(query, params).fetchall()

def get_equipment_for_prediction():
    """Get equipment data formatted for ML prediction"""
    with get_db() as conn:
        return conn.execute("""
            SELECT 
                e.equipment_id,
                e.serial_number,
                et.type_name,
                et.default_interval_months,
                l.building,
                l.floor,
                l.room,
                e.installation_date,
                julianday('now') - julianday(e.installation_date) as age_days,
                i.inspection_date as last_inspection_date,
                i.next_due_date,
                julianday('now') - julianday(i.inspection_date) as days_since_inspection,
                julianday(i.next_due_date) - julianday('now') as days_until_due,
                (SELECT COUNT(*) FROM inspections WHERE equipment_id = e.equipment_id) as inspection_count,
                (SELECT COUNT(*) FROM inspections 
                 WHERE equipment_id = e.equipment_id 
                 AND result = 'fail') as fail_count
            FROM equipment e
            JOIN equipment_types et ON e.type_id = et.type_id
            JOIN locations l ON e.location_id = l.location_id
            LEFT JOIN inspections i ON i.equipment_id = e.equipment_id
            AND i.inspection_id = (
                SELECT inspection_id FROM inspections 
                WHERE equipment_id = e.equipment_id 
                ORDER BY inspection_date DESC LIMIT 1
            )
            WHERE e.current_status = 'active'
        """).fetchall()

def get_user_by_email(email):
    """Retrieve user by email address"""
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()

def get_or_create_user(email, name=None, picture=None, auth_provider='google', role='Safety Inspector'):
    """Find or insert user into database"""
    email_clean = email.strip().lower()
    if not name:
        name = email_clean.split('@')[0].replace('.', ' ').replace('_', ' ').title()
    
    admin_emails = ['gowtham20050831@gmail.com', 'admin@firesafety.com', 'admin@firesafety.org', 'gowtham@safety.org']
    inspector_emails = ['gowtham.s.27.it@psvpec.in', 'inspector@firesafety.com', 'officer@firesafety.org']
    auditor_emails = ['motogsaravanan@gmail.com', 'auditor@firesafety.com', 'client@safety.org']

    if email_clean in admin_emails:
        target_role = 'System Administrator'
    elif email_clean in inspector_emails:
        target_role = 'Safety Inspector'
    elif email_clean in auditor_emails:
        target_role = 'Compliance Auditor'
    else:
        role_map = {'Inspector': 'Safety Inspector', 'Admin': 'System Administrator', 'Auditor': 'Compliance Auditor'}
        target_role = role_map.get(role, role)
    
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email_clean,)).fetchone()
        if user:
            if user['role'] != target_role and (email_clean in admin_emails or email_clean in inspector_emails or email_clean in auditor_emails or user['role'] in ['Inspector', 'Admin', 'Auditor']):
                conn.execute("UPDATE users SET role = ? WHERE email = ?", (target_role, email_clean))
            conn.execute("""
                UPDATE users 
                SET name = COALESCE(?, name), 
                    picture = COALESCE(?, picture),
                    last_login = CURRENT_TIMESTAMP
                WHERE email = ?
            """, (name, picture, email_clean))
            return conn.execute("SELECT * FROM users WHERE email = ?", (email_clean,)).fetchone()
        else:
            cursor = conn.execute("""
                INSERT INTO users (email, name, picture, auth_provider, role, status)
                VALUES (?, ?, ?, ?, ?, 'Active')
            """, (email_clean, name, picture, auth_provider, target_role))
            user_id = cursor.lastrowid
            return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

# ==========================================
# SYSTEM ADMINISTRATOR FUNCTIONS
# ==========================================

def get_all_users():
    """Retrieve all registered users"""
    with get_db() as conn:
        return conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()

def get_user_by_id(user_id):
    """Retrieve user details by ID"""
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def create_user_admin(email, name, role='Safety Inspector', status='Active', password=None):
    """Admin function to manually create a user with Google/Work email, password, and assigned role"""
    email_clean = email.strip().lower()
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO users (email, name, auth_provider, role, status, password)
            VALUES (?, ?, 'google', ?, ?, ?)
        """, (email_clean, name, role, status, password))
        return cursor.lastrowid

def update_user_admin(user_id, name, role, status, password=None):
    """Admin function to update user details, role, status, and optional password"""
    with get_db() as conn:
        if password:
            conn.execute("""
                UPDATE users 
                SET name = ?, role = ?, status = ?, password = ?
                WHERE user_id = ?
            """, (name, role, status, password, user_id))
        else:
            conn.execute("""
                UPDATE users 
                SET name = ?, role = ?, status = ?
                WHERE user_id = ?
            """, (name, role, status, user_id))

def delete_user_admin(user_id):
    """Admin function to delete a user account"""
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

def log_system_event(user_email, action, details=None, ip_address=None):
    """Log security and administrative actions"""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO system_logs (user_email, action, details, ip_address)
            VALUES (?, ?, ?, ?)
        """, (user_email, action, details, ip_address))

def get_system_logs(limit=50):
    """Retrieve recent system audit logs"""
    with get_db() as conn:
        return conn.execute("""
            SELECT * FROM system_logs ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()

def get_db_stats():
    """Retrieve statistical counters for administrative health monitoring"""
    with get_db() as conn:
        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        equipment_count = conn.execute("SELECT COUNT(*) FROM equipment WHERE current_status = 'active'").fetchone()[0]
        inspections_count = conn.execute("SELECT COUNT(*) FROM inspections").fetchone()[0]
        hazards_count = conn.execute("SELECT COUNT(*) FROM hazards").fetchone()[0]
        open_hazards = conn.execute("SELECT COUNT(*) FROM hazards WHERE status IN ('Open', 'In Progress')").fetchone()[0]
        audits_count = conn.execute("SELECT COUNT(*) FROM audits").fetchone()[0]
        return {
            'users_count': users_count,
            'equipment_count': equipment_count,
            'inspections_count': inspections_count,
            'hazards_count': hazards_count,
            'open_hazards': open_hazards,
            'audits_count': audits_count
        }

# ==========================================
# SAFETY INSPECTOR FUNCTIONS (HAZARDS)
# ==========================================

def add_hazard(title, description, location_id, equipment_id=None, severity='Medium', suggested_action=None, reported_by='Inspector'):
    """Record a new safety hazard or workplace incident"""
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO hazards (title, description, location_id, equipment_id, severity, suggested_action, reported_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (title, description, location_id, equipment_id, severity, suggested_action, reported_by))
        return cursor.lastrowid

def get_all_hazards(status_filter=None, severity_filter=None):
    """Retrieve all hazards with location & equipment details"""
    with get_db() as conn:
        query = """
            SELECT 
                h.*,
                l.building, l.floor, l.room,
                e.serial_number, et.type_name
            FROM hazards h
            JOIN locations l ON h.location_id = l.location_id
            LEFT JOIN equipment e ON h.equipment_id = e.equipment_id
            LEFT JOIN equipment_types et ON e.type_id = et.type_id
            WHERE 1=1
        """
        params = []
        if status_filter:
            query += " AND h.status = ?"
            params.append(status_filter)
        if severity_filter:
            query += " AND h.severity = ?"
            params.append(severity_filter)
        
        query += " ORDER BY h.reported_at DESC"
        return conn.execute(query, params).fetchall()

def get_hazard_by_id(hazard_id):
    """Retrieve specific hazard record"""
    with get_db() as conn:
        return conn.execute("""
            SELECT 
                h.*,
                l.building, l.floor, l.room,
                e.serial_number, et.type_name
            FROM hazards h
            JOIN locations l ON h.location_id = l.location_id
            LEFT JOIN equipment e ON h.equipment_id = e.equipment_id
            LEFT JOIN equipment_types et ON e.type_id = et.type_id
            WHERE h.hazard_id = ?
        """, (hazard_id,)).fetchone()

def update_hazard_status(hazard_id, status, corrective_action=None, verified_by=None):
    """Update corrective action status and verification"""
    with get_db() as conn:
        resolved_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if status in ['Resolved', 'Verified'] else None
        conn.execute("""
            UPDATE hazards
            SET status = ?,
                corrective_action = COALESCE(?, corrective_action),
                verified_by = COALESCE(?, verified_by),
                resolved_at = COALESCE(?, resolved_at)
            WHERE hazard_id = ?
        """, (status, corrective_action, verified_by, resolved_at, hazard_id))

# ==========================================
# COMPLIANCE AUDITOR FUNCTIONS (AUDITS)
# ==========================================

def create_audit(audit_title, audit_type, auditor_id, auditor_name, scope, compliance_score, status, findings, recommendations, audit_date):
    """Create a new compliance audit report entry"""
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO audits (audit_title, audit_type, auditor_id, auditor_name, scope, compliance_score, status, findings, recommendations, audit_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (audit_title, audit_type, auditor_id, auditor_name, scope, compliance_score, status, findings, recommendations, audit_date))
        return cursor.lastrowid

def get_all_audits():
    """Retrieve all compliance audits"""
    with get_db() as conn:
        return conn.execute("SELECT * FROM audits ORDER BY audit_date DESC").fetchall()

def get_audit_by_id(audit_id):
    """Retrieve detailed compliance audit by ID"""
    with get_db() as conn:
        return conn.execute("SELECT * FROM audits WHERE audit_id = ?", (audit_id,)).fetchone()


# ==========================================
# CHANGE 1 — UNIQUE Constraint Demo
# The equipment.serial_number column has a UNIQUE constraint.
# Calling demo_unique_constraint_violation() will try to insert a duplicate
# serial number and return the database error that proves the rule is enforced.
# ==========================================

def demo_unique_constraint_violation():
    """
    CHANGE 1 DEMO: Try to INSERT a row with a serial number that already exists.
    The database will refuse it because of the UNIQUE constraint on
    equipment.serial_number.
    Returns a dict describing the attempt and its outcome.
    """
    duplicate_serial = 'DEMO-DUPLICATE-001'

    with get_db() as conn:
        # Ensure a reference row for the demo exists
        conn.execute("""
            INSERT OR IGNORE INTO equipment_types (type_name, default_interval_months, description)
            VALUES ('Demo Type', 12, 'Used only for constraint demo')
        """)
        conn.execute("""
            INSERT OR IGNORE INTO locations (building, floor, room)
            VALUES ('Demo Building', 'G', 'Demo Room')
        """)
        type_id = conn.execute("SELECT type_id FROM equipment_types WHERE type_name = 'Demo Type'").fetchone()[0]
        loc_id  = conn.execute("SELECT location_id FROM locations WHERE building = 'Demo Building' AND floor = 'G' AND room = 'Demo Room'").fetchone()[0]

        # Insert the FIRST row — this should succeed
        conn.execute("""
            INSERT OR IGNORE INTO equipment (type_id, location_id, serial_number, manufacturer, installation_date)
            VALUES (?, ?, ?, 'DemoCo', DATE('now'))
        """, (type_id, loc_id, duplicate_serial))

    # Now attempt a SECOND insert with the same serial_number outside the
    # transaction so the error propagates cleanly
    result = {
        'rule': 'UNIQUE constraint on equipment.serial_number',
        'attempted_serial': duplicate_serial,
        'first_insert': 'SUCCESS — row inserted normally',
        'second_insert': None,
        'db_refused': False
    }

    try:
        conn2 = __import__('sqlite3').connect(DATABASE)
        conn2.execute("PRAGMA foreign_keys = ON")
        conn2.execute("""
            INSERT INTO equipment (type_id, location_id, serial_number, manufacturer, installation_date)
            VALUES (1, 1, ?, 'DupCo', DATE('now'))
        """, (duplicate_serial,))
        conn2.commit()
        conn2.close()
        result['second_insert'] = 'INSERT succeeded (unexpected)'
        result['db_refused'] = False
    except Exception as e:
        result['second_insert'] = f'REFUSED — {e}'
        result['db_refused'] = True

    return result


# ==========================================
# CHANGE 2 — Missing-Match Query (LEFT JOIN … IS NULL)
# Finds equipment that has NO inspection record in the inspections table.
# This is the canonical pattern for detecting rows in one table that are
# missing a related row in another table.
# ==========================================

def get_equipment_never_inspected():
    """
    CHANGE 2: LEFT JOIN ... IS NULL query.
    Returns equipment rows that have no matching row in the inspections table
    — i.e. equipment that has never been inspected.
    """
    with get_db() as conn:
        return conn.execute("""
            SELECT
                e.equipment_id,
                e.serial_number,
                e.manufacturer,
                e.installation_date,
                et.type_name,
                l.building,
                l.floor,
                l.room
            FROM   equipment e
            JOIN   equipment_types et ON e.type_id     = et.type_id
            JOIN   locations       l  ON e.location_id = l.location_id
            LEFT JOIN inspections  i  ON i.equipment_id = e.equipment_id
            WHERE  i.inspection_id IS NULL
            ORDER BY e.installation_date ASC
        """).fetchall()


if __name__ == '__main__':
    init_db()