"""
Seed Data Module
Generates realistic sample data for the Fire Safety Register
and trains the prediction model.
"""

from database import get_db, init_db, add_equipment, record_inspection
from model import train_model
from datetime import datetime, timedelta
import random

random.seed(42)

def seed_locations():
    """Create sample building locations"""
    buildings = ['Main Building', 'Annex', 'Old Wing', 'Science Block']
    floors = ['1', '2', '3', '4', '5']
    rooms = []

    for building in buildings:
        for floor in floors:
            for room_num in range(101, 106):
                room = f"{floor}{room_num-100:02d}"
                rooms.append((building, floor, room))

    with get_db() as conn:
        for building, floor, room in rooms:
            try:
                conn.execute("""
                    INSERT INTO locations (building, floor, room)
                    VALUES (?, ?, ?)
                """, (building, floor, room))
            except Exception:
                pass  # Duplicate

    print(f"Seeded {len(rooms)} locations")

def seed_equipment_types():
    """Create equipment types with inspection intervals"""
    types = [
        ('Fire Extinguisher - CO2',    12, 'Carbon dioxide fire extinguisher'),
        ('Fire Extinguisher - Powder', 12, 'Dry powder fire extinguisher'),
        ('Fire Extinguisher - Foam',   12, 'Foam fire extinguisher'),
        ('Smoke Detector',              6, 'Smoke detection unit'),
        ('Fire Alarm Panel',            3, 'Main fire alarm control panel'),
        ('Emergency Light',             6, 'Emergency exit lighting'),
        ('Fire Hose Reel',             12, 'Fire hose reel unit'),
        ('Sprinkler Head',             12, 'Automatic sprinkler head'),
    ]

    with get_db() as conn:
        for type_name, interval, desc in types:
            try:
                conn.execute("""
                    INSERT INTO equipment_types (type_name, default_interval_months, description)
                    VALUES (?, ?, ?)
                """, (type_name, interval, desc))
            except Exception:
                pass

    print(f"Seeded {len(types)} equipment types")

def seed_equipment():
    """Create equipment records"""
    with get_db() as conn:
        locations = conn.execute("SELECT location_id, building, floor FROM locations").fetchall()
        types = conn.execute("SELECT type_id, type_name, default_interval_months FROM equipment_types").fetchall()

    manufacturers = ['Safeguard', 'FireShield', 'Protecta', 'AgniSafe', 'BlazeGuard']

    equipment_ids = []
    run_id = random.randint(100, 999)
    for i in range(80):
        loc = random.choice(locations)
        eq_type = random.choice(types)

        serial = f"{eq_type['type_name'][:3].upper()}-{loc['building'][:3].upper()}-{loc['floor']}-{run_id}-{i+1001}"
        manufacturer = random.choice(manufacturers)

        # Installation date between 2-5 years ago
        days_ago = random.randint(730, 1825)
        install_date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')

        try:
            eq_id = add_equipment(
                type_id=eq_type['type_id'],
                location_id=loc['location_id'],
                serial_number=serial,
                manufacturer=manufacturer,
                installation_date=install_date
            )
            equipment_ids.append((eq_id, eq_type['default_interval_months'], install_date, loc['building']))
        except Exception:
            continue

    print(f"Seeded {len(equipment_ids)} equipment units")
    return equipment_ids

def seed_inspections(equipment_data):
    """Create inspection history with realistic patterns"""
    inspectors = ['Rajesh K.', 'Priya S.', 'Arun M.', 'Divya R.', 'Karthik N.', 'Sneha P.']

    count = 0
    for eq_id, interval_months, install_date, building in equipment_data:
        install_dt = datetime.strptime(install_date, '%Y-%m-%d')
        current = install_dt
        end = datetime.now()

        # Older / neglected buildings have more delays and failures
        delay_prob = 0.15 if building in ['Annex', 'Old Wing'] else 0.05
        fail_prob  = 0.08 if building in ['Annex', 'Old Wing'] else 0.03

        inspection_dates = []
        while current < end:
            current = current + timedelta(days=interval_months * 30)
            if current > end:
                break
            if random.random() < delay_prob:
                current = current + timedelta(days=random.randint(10, 45))
            inspection_dates.append(current)

        for insp_date in inspection_dates:
            inspector = random.choice(inspectors)
            result = 'fail' if random.random() < fail_prob else 'pass'
            notes = '' if result == 'pass' else 'Minor issue found, needs follow-up'
            next_due = insp_date + timedelta(days=interval_months * 30)

            record_inspection(
                equipment_id=eq_id,
                inspection_date=insp_date.strftime('%Y-%m-%d'),
                inspector_name=inspector,
                result=result,
                notes=notes,
                next_due_date=next_due.strftime('%Y-%m-%d')
            )
            count += 1

    print(f"Seeded {count} inspection records")
    return count

def seed_users():
    """Create default demo accounts for all 3 system roles"""
    from database import get_or_create_user, log_system_event
    users_data = [
        ('admin@firesafety.com', 'Alex Morgan (Admin)', 'https://ui-avatars.com/api/?name=Alex+Morgan&background=6366f1&color=fff', 'email', 'System Administrator'),
        ('inspector@firesafety.com', 'Sarah Connor (Inspector)', 'https://ui-avatars.com/api/?name=Sarah+Connor&background=10b981&color=fff', 'email', 'Safety Inspector'),
        ('auditor@firesafety.com', 'David Vance (Auditor)', 'https://ui-avatars.com/api/?name=David+Vance&background=f59e0b&color=fff', 'email', 'Compliance Auditor')
    ]
    for email, name, picture, provider, role in users_data:
        get_or_create_user(email, name, picture, provider, role)
        log_system_event(email, 'SYSTEM_SEED', f'Seeded account with role {role}')
    print("Seeded 3 demo role accounts: Admin, Inspector, Auditor")

def seed_hazards():
    """Create sample hazard reports and corrective action records"""
    from database import add_hazard, update_hazard_status, get_all_locations
    locations = get_all_locations()
    if not locations:
        return
    
    sample_hazards = [
        ("Blocked Fire Exit Corridor", "Items stacked in fire exit route on Floor 2", locations[0]['location_id'], "High", "Clear hallway debris and post warning sign", "Open"),
        ("Expired Pressure Gauge", "Extinguisher pressure reading below green zone", locations[1]['location_id'] if len(locations)>1 else locations[0]['location_id'], "Medium", "Replace pressure gauge valve", "In Progress"),
        ("Damaged Emergency Light Battery", "Backup lighting failed 90-min test run", locations[2]['location_id'] if len(locations)>2 else locations[0]['location_id'], "Critical", "Replace emergency unit battery pack", "Resolved"),
        ("Missing Hose Reel Nozzle", "Fire hose reel nozzle missing from cabinet", locations[3]['location_id'] if len(locations)>3 else locations[0]['location_id'], "Medium", "Install replacement brass spray nozzle", "Verified")
    ]

    for title, desc, loc_id, severity, action, status in sample_hazards:
        h_id = add_hazard(title, desc, loc_id, severity=severity, suggested_action=action, reported_by='Sarah Connor (Inspector)')
        if status in ['Resolved', 'Verified']:
            update_hazard_status(h_id, status, corrective_action="Corrective work executed and inspected on-site.", verified_by='Sarah Connor (Inspector)')

    print(f"Seeded {len(sample_hazards)} sample hazards and corrective actions")

def seed_audits():
    """Create sample compliance audit reports"""
    from database import create_audit
    sample_audits = [
        ("Q2 Annual Workplace Fire Safety Audit", "Internal", 3, "David Vance (Auditor)", "Main Building & Annex Facilities", 94.5, "Completed", 
         "All primary fire extinguishers fully functional. 2 emergency light batteries required replacement.",
         "Implement bi-monthly emergency lighting testing schedule and update location tags.", (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')),
        ("ISO 45001 Regulatory Safety Compliance Check", "Regulatory", 3, "David Vance (Auditor)", "Old Wing & Science Block", 88.0, "Passed",
         "Good adherence to inspection schedules. Clear documentation maintained across logs.",
         "Automate overdue inspection alerts for high-risk equipment types.", (datetime.now() - timedelta(days=45)).strftime('%Y-%m-%d'))
    ]

    for title, a_type, u_id, name, scope, score, status, findings, recs, a_date in sample_audits:
        create_audit(title, a_type, u_id, name, scope, score, status, findings, recs, a_date)

    print(f"Seeded {len(sample_audits)} sample compliance audits")

def main():
    print("=" * 50)
    print("FIRE SAFETY REGISTER - DATA SEEDING")
    print("=" * 50)

    init_db()
    seed_locations()
    seed_equipment_types()
    equipment_data = seed_equipment()
    total_inspections = seed_inspections(equipment_data)
    seed_users()
    seed_hazards()
    seed_audits()

    # Train prediction model
    print("\n" + "=" * 50)
    print("TRAINING PREDICTION MODEL")
    print("=" * 50)

    from database import get_equipment_for_prediction
    equipment_rows = get_equipment_for_prediction()

    with get_db() as conn:
        inspection_history = conn.execute("SELECT * FROM inspections").fetchall()

    model = train_model(equipment_rows, inspection_history)

    print("\n" + "=" * 50)
    print("SEEDING COMPLETE")
    print("=" * 50)
    print(f"Total equipment:   {len(equipment_data)}")
    print(f"Total inspections: {total_inspections}")
    if model:
        print("Prediction model: trained and saved")
    else:
        print("Prediction model: using heuristic fallback")

if __name__ == '__main__':
    main()

