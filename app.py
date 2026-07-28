"""
Fire Safety Equipment Inspection and Expiry Register
Main Flask Application
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g, send_file
from dotenv import load_dotenv
load_dotenv()
from database import (
    init_db, get_db, get_equipment_with_status, get_equipment_by_id,
    get_inspection_history, add_equipment, record_inspection,
    get_all_locations, get_all_equipment_types, search_equipment,
    get_equipment_for_prediction, calculate_next_due_date,
    get_or_create_user, get_user_by_email,
    # Admin
    get_all_users, get_user_by_id, create_user_admin, update_user_admin, delete_user_admin,
    log_system_event, get_system_logs, get_db_stats,
    # Inspector / Hazards
    add_hazard, get_all_hazards, get_hazard_by_id, update_hazard_status,
    # Auditor
    create_audit, get_all_audits, get_audit_by_id
)
from model import predict_risk, train_model
from datetime import datetime, timedelta
import os
import json
import base64
import io
import sqlite3
from functools import wraps

app = Flask(__name__, template_folder='template')

app.secret_key = os.environ.get('SECRET_KEY', 'your-flask-secret-key-here')

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

def parse_google_jwt(credential):
    """Parse payload from Google ID Token JWT"""
    try:
        parts = credential.split('.')
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        padded = payload_b64 + '=' * (4 - len(payload_b64) % 4)
        decoded_bytes = base64.urlsafe_b64decode(padded)
        return json.loads(decoded_bytes.decode('utf-8'))
    except Exception:
        return None

# Initialize database and session auth check
@app.before_request
def setup_and_authorize():
    from database import DATABASE
    if not os.path.exists(DATABASE):
        init_db()
        # Auto-seed demo data on first cold-start (required for Vercel serverless)
        try:
            from seed_data import main as seed_main
            seed_main()
        except Exception as e:
            print(f"Seed data warning: {e}")

    # Public endpoints that don't require login
    public_endpoints = {'login', 'google_auth', 'demo_login', 'static'}
    if request.endpoint and request.endpoint not in public_endpoints and not request.endpoint.startswith('static'):
        if 'user' not in session:
            return redirect(url_for('login', next=request.url))

def role_required(*allowed_roles):
    """Decorator to restrict access to specific user roles"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = session.get('user')
            if not user:
                flash('Please sign in to access this page.', 'error')
                return redirect(url_for('login'))
            user_role = user.get('role', '')
            # System Administrator has access to everything
            if user_role == 'System Administrator' or user_role in allowed_roles:
                return f(*args, **kwargs)
            # Redirect to user's own portal if they access the wrong one
            portal_map = {
                'Safety Inspector': 'portal_inspector',
                'Inspector': 'portal_inspector',
                'Compliance Auditor': 'portal_auditor',
                'Auditor': 'portal_auditor',
                'System Administrator': 'portal_admin',
                'Admin': 'portal_admin'
            }
            target = portal_map.get(user_role, 'index')
            flash(f'Access denied. You need one of these roles: {", ".join(allowed_roles)}.', 'error')
            return redirect(url_for(target))
        return wrapper
    return decorator

def get_role_portal_url(role):
    """Return the portal URL for a given role"""
    portal_map = {
        'Safety Inspector': 'portal_inspector',
        'Inspector': 'portal_inspector',
        'Compliance Auditor': 'portal_auditor',
        'Auditor': 'portal_auditor',
        'System Administrator': 'portal_admin',
        'Admin': 'portal_admin'
    }
    return url_for(portal_map.get(role, 'index'))

@app.context_processor
def inject_user():
    return dict(
        current_user=session.get('user'),
        google_client_id=GOOGLE_CLIENT_ID,
        get_role_portal_url=get_role_portal_url,
        now=datetime.now()
    )



@app.route('/')
def index():
    """Dashboard showing summary and urgent items"""
    equipment = get_equipment_with_status()

    # Summary counts
    total = len(equipment)
    overdue = sum(1 for e in equipment if e['urgency_status'] == 'overdue')
    approaching = sum(1 for e in equipment if e['urgency_status'] == 'approaching')
    good = sum(1 for e in equipment if e['urgency_status'] == 'good')

    # Get predictions
    prediction_data = get_equipment_for_prediction()
    predictions = predict_risk(prediction_data)

    # Merge predictions with equipment
    pred_map = {p['equipment_id']: p for p in predictions}
    equipment_with_pred = []
    for eq in equipment:
        eq_dict = dict(eq)
        pred = pred_map.get(eq_dict['equipment_id'], {})
        eq_dict['at_risk'] = pred.get('at_risk', False)
        eq_dict['confidence'] = pred.get('confidence', 0)
        eq_dict['risk_probability'] = pred.get('risk_probability', 0)
        equipment_with_pred.append(eq_dict)

    return render_template('index.html',
                           equipment=equipment_with_pred[:10],
                           total=total,
                           overdue=overdue,
                           approaching=approaching,
                           good=good)

@app.route('/equipment')
def equipment_list():
    """List view with search, filter, and ordering"""
    search_term = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '')
    type_filter = request.args.get('type', '')

    equipment = search_equipment(search_term, status_filter, type_filter)

    # Get predictions
    prediction_data = get_equipment_for_prediction()
    predictions = predict_risk(prediction_data)
    pred_map = {p['equipment_id']: p for p in predictions}

    equipment_with_pred = []
    for eq in equipment:
        eq_dict = dict(eq)
        pred = pred_map.get(eq_dict['equipment_id'], {})
        eq_dict['at_risk'] = pred.get('at_risk', False)
        eq_dict['confidence'] = pred.get('confidence', 0)
        eq_dict['risk_probability'] = pred.get('risk_probability', 0)
        equipment_with_pred.append(eq_dict)

    # Get filter options
    types = get_all_equipment_types()

    return render_template('equipment_list.html',
                           equipment=equipment_with_pred,
                           types=types,
                           search=search_term,
                           status=status_filter,
                           type_filter=type_filter,
                           count=len(equipment_with_pred))

@app.route('/equipment/add', methods=['GET', 'POST'])
def add_equipment_view():
    """Add new equipment with server-side validation"""
    if request.method == 'POST':
        errors = []

        type_id = request.form.get('type_id', '').strip()
        location_id = request.form.get('location_id', '').strip()
        serial_number = request.form.get('serial_number', '').strip()
        manufacturer = request.form.get('manufacturer', '').strip()
        installation_date = request.form.get('installation_date', '').strip()

        if not type_id or not type_id.isdigit():
            errors.append("Equipment type is required")
        if not location_id or not location_id.isdigit():
            errors.append("Location is required")
        if not serial_number or len(serial_number) < 3:
            errors.append("Serial number must be at least 3 characters")
        if not manufacturer:
            errors.append("Manufacturer is required")
        if not installation_date:
            errors.append("Installation date is required")
        else:
            try:
                install_dt = datetime.strptime(installation_date, '%Y-%m-%d')
                if install_dt > datetime.now():
                    errors.append("Installation date cannot be in the future")
            except ValueError:
                errors.append("Invalid date format. Use YYYY-MM-DD")

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('equipment_form.html',
                                   locations=get_all_locations(),
                                   types=get_all_equipment_types(),
                                   form_data=request.form)

        try:
            eq_id = add_equipment(int(type_id), int(location_id), serial_number,
                                  manufacturer, installation_date)

            eq_type = next((t for t in get_all_equipment_types()
                            if t['type_id'] == int(type_id)), None)
            interval = eq_type['default_interval_months'] if eq_type else 12
            next_due = calculate_next_due_date(installation_date, interval)

            record_inspection(eq_id, installation_date, 'System', 'pass',
                              'Initial installation inspection', next_due)

            flash(f'Equipment added successfully. Next inspection due: {next_due}', 'success')
            return redirect(url_for('equipment_list'))
        except Exception as e:
            flash(f'Error adding equipment: {str(e)}', 'error')

    return render_template('equipment_form.html',
                           locations=get_all_locations(),
                           types=get_all_equipment_types())

@app.route('/equipment/<int:equipment_id>')
def equipment_detail(equipment_id):
    """View equipment details and inspection history"""
    equipment = get_equipment_by_id(equipment_id)
    if not equipment:
        flash('Equipment not found', 'error')
        return redirect(url_for('equipment_list'))

    history = get_inspection_history(equipment_id)

    prediction_data = get_equipment_for_prediction()
    predictions = predict_risk(prediction_data)
    pred = next((p for p in predictions if p['equipment_id'] == equipment_id), {})

    return render_template('equipment_details.html',
                           equipment=equipment,
                           history=history,
                           prediction=pred)

@app.route('/inspection/add/<int:equipment_id>', methods=['GET', 'POST'])
def add_inspection(equipment_id):
    """Record new inspection with validation"""
    equipment = get_equipment_by_id(equipment_id)
    if not equipment:
        flash('Equipment not found', 'error')
        return redirect(url_for('equipment_list'))

    if request.method == 'POST':
        errors = []

        inspection_date = request.form.get('inspection_date', '').strip()
        inspector_name = request.form.get('inspector_name', '').strip()
        result = request.form.get('result', '').strip()
        notes = request.form.get('notes', '').strip()

        if not inspection_date:
            errors.append("Inspection date is required")
        else:
            try:
                insp_dt = datetime.strptime(inspection_date, '%Y-%m-%d')
                if insp_dt > datetime.now():
                    errors.append("Inspection date cannot be in the future")
            except ValueError:
                errors.append("Invalid date format")

        if not inspector_name or len(inspector_name) < 2:
            errors.append("Inspector name must be at least 2 characters")

        if result not in ['pass', 'fail', 'needs_repair']:
            errors.append("Invalid result selected")

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('inspection_form.html',
                                   equipment=equipment,
                                   form_data=request.form)

        try:
            interval = equipment['default_interval_months']
            next_due = calculate_next_due_date(inspection_date, interval)

            record_inspection(equipment_id, inspection_date, inspector_name,
                              result, notes, next_due)

            flash(f'Inspection recorded. Next due: {next_due}', 'success')
            return redirect(url_for('equipment_detail', equipment_id=equipment_id))
        except Exception as e:
            flash(f'Error recording inspection: {str(e)}', 'error')

    return render_template('inspection_form.html', equipment=equipment)

@app.route('/api/equipment')
def api_equipment():
    """API endpoint for equipment data"""
    equipment = get_equipment_with_status()
    return jsonify([dict(row) for row in equipment])

@app.route('/api/predictions')
def api_predictions():
    """API endpoint for risk predictions"""
    prediction_data = get_equipment_for_prediction()
    predictions = predict_risk(prediction_data)
    return jsonify(predictions)

@app.route('/retrain')
def retrain_model():
    """Retrain the prediction model"""
    try:
        prediction_data = get_equipment_for_prediction()
        with get_db() as conn:
            inspection_history = conn.execute("SELECT * FROM inspections").fetchall()

        model = train_model(prediction_data, inspection_history)
        if model:
            flash('Model retrained successfully', 'success')
        else:
            flash('Not enough data to train model', 'warning')
    except Exception as e:
        flash(f'Error training model: {str(e)}', 'error')

    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login view with Google Email login and email/password authentication"""
    if 'user' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or '@' not in email:
            flash('Please enter a valid email address.', 'error')
            return render_template('login.html')

        user = get_user_by_email(email)
        if not user:
            user = get_or_create_user(email=email, auth_provider='email')

        user_data = dict(user)
        if user_data.get('password') and user_data['password'] != password:
            flash('Invalid email address or password. Please try again.', 'error')
            return render_template('login.html')

        session['user'] = {
            'user_id': user_data['user_id'],
            'email': user_data['email'],
            'name': user_data['name'],
            'picture': user_data.get('picture'),
            'role': user_data['role'],
            'auth_provider': user_data.get('auth_provider', 'email')
        }
        log_system_event(user_data['email'], 'LOGIN', f'Signed in via email with role {user_data["role"]}', request.remote_addr)
        flash(f'Welcome back, {user["name"]}! Redirecting to your portal...', 'success')
        next_url = request.args.get('next')
        if next_url:
            return redirect(next_url)
        return redirect(get_role_portal_url(user['role']))

    return render_template('login.html')

@app.route('/api/auth/google', methods=['POST'])
def google_auth():
    """Google OAuth GIS callback endpoint"""
    data = request.get_json(silent=True) or request.form
    credential = data.get('credential')
    
    if credential:
        payload = parse_google_jwt(credential)
        if payload and payload.get('email'):
            email = payload.get('email')
            name = payload.get('name') or email.split('@')[0].title()
            picture = payload.get('picture')
            
            user = get_or_create_user(email=email, name=name, picture=picture, auth_provider='google', role='Safety Inspector')
            session['user'] = {
                'user_id': user['user_id'],
                'email': user['email'],
                'name': user['name'],
                'picture': user['picture'],
                'role': user['role'],
                'auth_provider': 'google'
            }
            log_system_event(email, 'GOOGLE_LOGIN', f'Google OAuth sign-in', request.remote_addr)
            return jsonify({'success': True, 'redirect': get_role_portal_url(user['role']), 'user': dict(user)})
    
    # Direct payload fallback
    email = data.get('email')
    if email:
        name = data.get('name', email.split('@')[0].title())
        picture = data.get('picture')
        user = get_or_create_user(email=email, name=name, picture=picture, auth_provider='google')
        session['user'] = {
            'user_id': user['user_id'],
            'email': user['email'],
            'name': user['name'],
            'picture': user['picture'],
            'role': user['role'],
            'auth_provider': 'google'
        }
        log_system_event(email, 'GOOGLE_LOGIN', f'Signed in via Google with role {user["role"]}', request.remote_addr)
        return jsonify({'success': True, 'redirect': get_role_portal_url(user['role']), 'user': dict(user)})

    return jsonify({'success': False, 'message': 'Invalid Google Sign-In credentials'}), 400

@app.route('/logout')
def logout():
    """Log out user and clear session"""
    user = session.get('user')
    if user:
        log_system_event(user.get('email'), 'LOGOUT', 'User signed out', request.remote_addr)
    session.pop('user', None)
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('login'))

# ==========================================
# PORTAL ROUTES
# ==========================================

@app.route('/portal/inspector')
@role_required('Safety Inspector')
def portal_inspector():
    """Safety Inspector Portal"""
    user = session['user']
    hazards = get_all_hazards()
    equipment = get_equipment_with_status()
    overdue = [e for e in equipment if e['urgency_status'] == 'overdue']
    approaching = [e for e in equipment if e['urgency_status'] == 'approaching']
    open_hazards = [h for h in hazards if h['status'] in ('Open', 'In Progress')]
    resolved = [h for h in hazards if h['status'] in ('Resolved', 'Verified')]
    locations = get_all_locations()
    equipment_types = get_all_equipment_types()
    return render_template('portal_inspector.html',
        hazards=hazards, open_hazards=open_hazards, resolved_hazards=resolved,
        overdue_equipment=overdue, approaching_equipment=approaching,
        equipment=equipment, locations=locations, equipment_types=equipment_types)

@app.route('/portal/admin')
@role_required('System Administrator')
def portal_admin():
    """System Administrator Portal"""
    users = get_all_users()
    logs = get_system_logs(limit=20)
    stats = get_db_stats()
    return render_template('portal_admin.html', users=users, logs=logs, stats=stats)

@app.route('/portal/auditor')
@role_required('Compliance Auditor')
def portal_auditor():
    """Compliance Auditor Portal"""
    audits = get_all_audits()
    hazards = get_all_hazards()
    equipment = get_equipment_with_status()
    inspections_total = sum(1 for e in equipment)
    overdue_count = sum(1 for e in equipment if e['urgency_status'] == 'overdue')
    resolved_hazards = sum(1 for h in hazards if h['status'] in ('Resolved', 'Verified'))
    total_hazards = len(hazards)
    compliance_pct = round((resolved_hazards / total_hazards * 100) if total_hazards else 100, 1)
    avg_score = round(sum(a['compliance_score'] for a in audits) / len(audits), 1) if audits else 100.0
    return render_template('portal_auditor.html',
        audits=audits, hazards=hazards, equipment=equipment,
        inspections_total=inspections_total, overdue_count=overdue_count,
        compliance_pct=compliance_pct, avg_score=avg_score,
        resolved_hazards=resolved_hazards, total_hazards=total_hazards)

# ==========================================
# ADMIN: USER MANAGEMENT ROUTES
# ==========================================

@app.route('/admin/users/create', methods=['POST'])
@role_required('System Administrator')
def admin_create_user():
    email = request.form.get('email', '').strip()
    name = request.form.get('name', '').strip()
    role = request.form.get('role', 'Safety Inspector')
    password = request.form.get('password', '').strip() or None
    if not email or '@' not in email:
        flash('Valid email is required.', 'error')
    elif not name:
        flash('Full name is required.', 'error')
    elif not password:
        flash('Password is required.', 'error')
    else:
        try:
            create_user_admin(email, name, role, 'Active', password)
            log_system_event(session['user']['email'], 'CREATE_USER', f'Created user {email} with role {role}', request.remote_addr)
            flash(f'User account for {name} ({email}) created successfully with role "{role}".', 'success')
        except Exception as e:
            flash(f'Error creating user: {e}', 'error')
    return redirect(url_for('portal_admin'))

@app.route('/admin/users/<int:user_id>/edit', methods=['POST'])
@role_required('System Administrator')
def admin_edit_user(user_id):
    name = request.form.get('name', '').strip()
    role = request.form.get('role', 'Safety Inspector')
    status = request.form.get('status', 'Active')
    password = request.form.get('password', '').strip() or None
    try:
        update_user_admin(user_id, name, role, status, password)
        log_system_event(session['user']['email'], 'EDIT_USER', f'Updated user ID {user_id}: role={role}, status={status}', request.remote_addr)
        flash('User updated successfully.', 'success')
    except Exception as e:
        flash(f'Error updating user: {e}', 'error')
    return redirect(url_for('portal_admin'))

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@role_required('System Administrator')
def admin_delete_user(user_id):
    u = get_user_by_id(user_id)
    if u and u['email'] == session['user']['email']:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('portal_admin'))
    try:
        delete_user_admin(user_id)
        log_system_event(session['user']['email'], 'DELETE_USER', f'Deleted user ID {user_id}', request.remote_addr)
        flash('User deleted.', 'success')
    except Exception as e:
        flash(f'Error deleting user: {e}', 'error')
    return redirect(url_for('portal_admin'))

@app.route('/admin/backup')
@role_required('System Administrator')
def admin_backup():
    """Download a copy of the SQLite database"""
    from database import DATABASE
    if not os.path.exists(DATABASE):
        flash('Database backup is not available in this environment.', 'error')
        return redirect(url_for('portal_admin'))
    log_system_event(session['user']['email'], 'BACKUP_DOWNLOAD', 'Admin downloaded DB backup', request.remote_addr)
    return send_file(DATABASE, as_attachment=True, download_name='fire_safety_backup.db', mimetype='application/octet-stream')

# ==========================================
# HAZARD MANAGEMENT ROUTES
# ==========================================

@app.route('/hazards')
def hazards_list():
    """All hazards and incidents list"""
    status_filter = request.args.get('status', '')
    severity_filter = request.args.get('severity', '')
    hazards = get_all_hazards(status_filter or None, severity_filter or None)
    return render_template('hazards_list.html', hazards=hazards, status_filter=status_filter, severity_filter=severity_filter)

@app.route('/hazards/add', methods=['POST'])
@role_required('Safety Inspector')
def hazard_add():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    location_id = request.form.get('location_id', '')
    equipment_id = request.form.get('equipment_id', '') or None
    severity = request.form.get('severity', 'Medium')
    suggested_action = request.form.get('suggested_action', '').strip()
    reporter = session['user']['name']
    if not title or not description or not location_id:
        flash('Title, description, and location are required.', 'error')
    else:
        try:
            add_hazard(title, description, int(location_id), int(equipment_id) if equipment_id else None, severity, suggested_action, reporter)
            log_system_event(session['user']['email'], 'REPORT_HAZARD', f'Reported hazard: {title}', request.remote_addr)
            flash(f'Hazard "{title}" reported successfully.', 'success')
        except Exception as e:
            flash(f'Error reporting hazard: {e}', 'error')
    return redirect(url_for('portal_inspector'))

@app.route('/hazards/<int:hazard_id>/update', methods=['POST'])
@role_required('Safety Inspector')
def hazard_update(hazard_id):
    status = request.form.get('status', 'Open')
    corrective_action = request.form.get('corrective_action', '').strip() or None
    verified_by = session['user']['name'] if status == 'Verified' else None
    try:
        update_hazard_status(hazard_id, status, corrective_action, verified_by)
        log_system_event(session['user']['email'], 'UPDATE_HAZARD', f'Hazard {hazard_id} status updated to {status}', request.remote_addr)
        flash(f'Hazard status updated to {status}.', 'success')
    except Exception as e:
        flash(f'Error updating hazard: {e}', 'error')
    return redirect(url_for('portal_inspector'))

# ==========================================
# AUDIT MANAGEMENT ROUTES
# ==========================================

@app.route('/audits/create', methods=['POST'])
@role_required('Compliance Auditor')
def audit_create():
    audit_title = request.form.get('audit_title', '').strip()
    audit_type = request.form.get('audit_type', 'Internal')
    scope = request.form.get('scope', '').strip()
    compliance_score = float(request.form.get('compliance_score', 100))
    status = request.form.get('status', 'Completed')
    findings = request.form.get('findings', '').strip()
    recommendations = request.form.get('recommendations', '').strip()
    audit_date = request.form.get('audit_date', datetime.now().strftime('%Y-%m-%d'))
    user = session['user']
    if not audit_title or not scope:
        flash('Audit title and scope are required.', 'error')
    else:
        try:
            a_id = create_audit(audit_title, audit_type, user['user_id'], user['name'], scope,
                                compliance_score, status, findings, recommendations, audit_date)
            log_system_event(user['email'], 'CREATE_AUDIT', f'Created audit: {audit_title}', request.remote_addr)
            flash(f'Audit "{audit_title}" created.', 'success')
        except Exception as e:
            flash(f'Error creating audit: {e}', 'error')
    return redirect(url_for('portal_auditor'))

@app.route('/audits/<int:audit_id>/report')
def audit_report(audit_id):
    """View detailed audit report"""
    audit = get_audit_by_id(audit_id)
    if not audit:
        flash('Audit report not found.', 'error')
        return redirect(url_for('portal_auditor'))
    return render_template('audit_report.html', audit=audit)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
