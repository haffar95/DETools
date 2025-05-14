from functools import wraps
from flask import session, redirect, url_for, flash, request
from app.models.user import User

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.get_user(session['user_id'])
        if not user or not user.is_admin:
            flash('Admin access required', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def connection_access_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        user = User.get_user(session['user_id'])
        if not user:
            return redirect(url_for('login'))

        # Get the connection name from the request
        connection_name = request.form.get('selected_db')
        if not connection_name:
            connection_name = session.get('current_connection')

        if not connection_name or not user.can_access_connection(connection_name):
            flash('You do not have access to this connection', 'danger')
            return redirect(url_for('database_config'))
            
        return f(*args, **kwargs)
    return decorated_function