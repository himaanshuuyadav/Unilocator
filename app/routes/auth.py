from flask import Blueprint, request, redirect, url_for, session, jsonify, Response
from datetime import datetime
import json
from ..utils.firebase_utils import get_firestore_db

bp = Blueprint('auth', __name__)

@bp.route('/login', methods=['POST'])
def login():
    # Expect JSON with {"firebase_uid": ..., "email": ..."}
    data = request.get_json()
    firebase_uid = data.get('firebase_uid')
    user_email = data.get('email', '')
    print(f"[DEBUG] /login called. firebase_uid: {firebase_uid}, email: {user_email}")
    if not firebase_uid:
        print("[DEBUG] /login failed: Missing firebase_uid")
        return jsonify({'success': False, 'error': 'Missing firebase_uid'}), 400
    # Set session cookies
    session['user_id'] = firebase_uid
    session['user_email'] = user_email
    print(f"[DEBUG] /login success. session['user_id']: {session.get('user_id')}, session['user_email']: {session.get('user_email')}")
    return jsonify({'success': True, 'redirect': url_for('main.dashboard')})

@bp.route('/logout', methods=['POST'])
def logout():
    print(f"[DEBUG] /logout called. session before clear: {session.get('user_id')}")
    session.pop('user_id', None)
    print(f"[DEBUG] /logout success. session after clear: {session.get('user_id')}")
    return jsonify({'success': True, 'redirect': url_for('main.index')})

@bp.route('/download-data', methods=['GET'])
def download_data():
    firebase_uid = session.get('user_id')
    if not firebase_uid:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        db = get_firestore_db()
        
        # Get user data from Firebase (if you store user profiles)
        user_doc = db.collection('users').document(firebase_uid).get()
        user_data = user_doc.to_dict() if user_doc.exists else None
        
        # Get devices data from Firebase
        from google.cloud.firestore_v1.base_query import FieldFilter
        devices_ref = db.collection('connected_devices').where(filter=FieldFilter('user_id', '==', firebase_uid))
        devices_docs = devices_ref.get()
        devices_data = [doc.to_dict() for doc in devices_docs]
        
        # Format data for download
        export_data = {
            'user_id': firebase_uid,
            'export_date': str(datetime.now()),
            'user_info': user_data,
            'devices': devices_data
        }
        
        response = Response(
            json.dumps(export_data, indent=2),
            mimetype='application/json',
            headers={"Content-Disposition": "attachment;filename=unilocator-data.json"}
        )
        return response
        
    except Exception as e:
        print(f"[DEBUG] Error downloading data: {e}")
        return jsonify({'success': False, 'error': 'Failed to export data'}), 500

@bp.route('/save-setting', methods=['POST'])
def save_setting():
    firebase_uid = session.get('user_id')
    if not firebase_uid:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    setting_name = data.get('setting')
    setting_value = data.get('value')
    
    print(f"[DEBUG] Saving setting {setting_name}: {setting_value} for user {firebase_uid}")
    
    # In a real implementation, you'd save this to a user_settings table
    # For now, just return success
    return jsonify({'success': True})

@bp.route('/delete-account', methods=['POST'])
def delete_account():
    firebase_uid = session.get('user_id')
    if not firebase_uid:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        db = get_firestore_db()
        from google.cloud.firestore_v1.base_query import FieldFilter
        
        # Delete user's devices from Firebase
        devices_ref = db.collection('connected_devices').where(filter=FieldFilter('user_id', '==', firebase_uid))
        devices_docs = devices_ref.get()
        for doc in devices_docs:
            doc.reference.delete()
        
        # Delete device codes associated with user
        codes_ref = db.collection('device_codes').where(filter=FieldFilter('userId', '==', firebase_uid))
        codes_docs = codes_ref.get()
        for doc in codes_docs:
            doc.reference.delete()
        
        # Delete user profile if it exists
        user_doc_ref = db.collection('users').document(firebase_uid)
        if user_doc_ref.get().exists:
            user_doc_ref.delete()
        
        # Clear session
        session.pop('user_id', None)
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"[DEBUG] Error deleting account: {e}")
        return jsonify({'success': False, 'error': 'Failed to delete account'}), 500

@bp.route('/check-username', methods=['POST'])
def check_username():
    """Check if a username is available"""
    data = request.get_json()
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({'available': False, 'error': 'Username is required'}), 400
    
    # Validate username format (letters, numbers, dots, underscores only)
    import re
    if not re.match(r'^[a-zA-Z0-9._]+$', username):
        return jsonify({
            'available': False, 
            'error': 'Username can only contain letters, numbers, dots, and underscores'
        }), 400
    
    if len(username) < 3 or len(username) > 30:
        return jsonify({
            'available': False, 
            'error': 'Username must be between 3 and 30 characters'
        }), 400
    
    try:
        from ..models.user import User
        exists = User.username_exists(username)
        
        return jsonify({
            'available': not exists,
            'username': username
        })
        
    except Exception as e:
        print(f"[DEBUG] Error checking username: {e}")
        return jsonify({'available': False, 'error': 'Failed to check username'}), 500

@bp.route('/set-username', methods=['POST'])
def set_username():
    """Set or update username for the current user"""
    firebase_uid = session.get('user_id')
    if not firebase_uid:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({'success': False, 'error': 'Username is required'}), 400
    
    # Validate username format
    import re
    if not re.match(r'^[a-zA-Z0-9._]+$', username):
        return jsonify({
            'success': False, 
            'error': 'Username can only contain letters, numbers, dots, and underscores'
        }), 400
    
    if len(username) < 3 or len(username) > 30:
        return jsonify({
            'success': False, 
            'error': 'Username must be between 3 and 30 characters'
        }), 400
    
    try:
        from ..models.user import User
        
        # Check if username is already taken by another user
        if User.username_exists(username, exclude_firebase_uid=firebase_uid):
            return jsonify({
                'success': False, 
                'error': 'Username is already taken'
            }), 400
        
        # Update the user's username
        user = User.get_by_firebase_uid(firebase_uid)
        if user:
            success = user.update_profile(username=username)
            if success:
                return jsonify({'success': True, 'username': username})
            else:
                return jsonify({'success': False, 'error': 'Failed to update username'}), 500
        else:
            # Create user profile if it doesn't exist
            user_email = session.get('user_email', '')
            user = User.create_or_update(firebase_uid, username=username, email=user_email)
            if user:
                return jsonify({'success': True, 'username': username})
            else:
                return jsonify({'success': False, 'error': 'Failed to create user profile'}), 500
        
    except Exception as e:
        print(f"[DEBUG] Error setting username: {e}")
        return jsonify({'success': False, 'error': 'Failed to set username'}), 500

@bp.route('/login-with-username', methods=['POST'])
def login_with_username():
    """Login with username or email (for future use when implementing password auth)"""
    data = request.get_json()
    identifier = data.get('identifier', '').strip()  # Can be username or email
    firebase_uid = data.get('firebase_uid')  # Still requires Firebase auth
    
    if not identifier or not firebase_uid:
        return jsonify({'success': False, 'error': 'Missing credentials'}), 400
    
    try:
        from ..models.user import User
        
        # Try to find user by username or email
        user = User.get_by_username(identifier)
        if not user:
            user = User.get_by_email(identifier)
        
        if user and user.firebase_uid == firebase_uid:
            # Set session
            session['user_id'] = firebase_uid
            session['user_email'] = user.email
            session['username'] = user.username
            
            return jsonify({
                'success': True, 
                'redirect': url_for('main.dashboard'),
                'username': user.username
            })
        else:
            return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
            
    except Exception as e:
        print(f"[DEBUG] Error in username login: {e}")
        return jsonify({'success': False, 'error': 'Login failed'}), 500

