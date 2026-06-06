from flask import Blueprint, render_template, redirect, url_for, request, g, jsonify, session
from datetime import datetime

def format_last_seen(timestamp_str):
    """Convert ISO timestamp to readable format"""
    if not timestamp_str:
        return "Never"
    
    try:
        # Parse ISO timestamp
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1] + '+00:00'
        
        dt = datetime.fromisoformat(timestamp_str)
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        
        # Calculate time difference
        diff = now - dt
        
        if diff.days > 0:
            if diff.days == 1:
                return "1 day ago"
            elif diff.days < 7:
                return f"{diff.days} days ago"
            elif diff.days < 30:
                weeks = diff.days // 7
                return f"{weeks} week{'s' if weeks > 1 else ''} ago"
            else:
                months = diff.days // 30
                return f"{months} month{'s' if months > 1 else ''} ago"
        
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif minutes > 0:
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "Just now"
    
    except Exception as e:
        print(f"[DEBUG] Error parsing timestamp {timestamp_str}: {e}")
        return "Unknown"

bp = Blueprint('main', __name__)

# Route for /index to render the landing page (now index.html)
@bp.route('/index')
def index_page():
    return render_template('index.html')

@bp.route('/')
def index():
    # Show the landing page (index.html) for everyone
    return render_template('index.html')

# Dashboard route: Only show if authenticated, else redirect to home
@bp.route('/dashboard')
def dashboard():
    # Use session for authentication
    firebase_uid = session.get('user_id')
    print(f"[DEBUG] /dashboard session['user_id']: {firebase_uid}")
    if not firebase_uid:
        print("[DEBUG] /dashboard: Not authenticated, redirecting to login page.")
        return redirect(url_for('main.login_page'))
    
    devices = []
    
    try:
        print(f"[DEBUG] /dashboard: About to fetch devices for user: {firebase_uid}")
        
        # Use new REST API client
        from app.utils.firebase_rest_api import fetch_user_devices_rest
        
        print("[DEBUG] /dashboard: Using REST API client...")
        devices_list = fetch_user_devices_rest(firebase_uid)
        
        print(f"[DEBUG] /dashboard: REST API returned {len(devices_list)} devices")
        
        # Transform the REST API data to dashboard format
        for device_data in devices_list:
            print(f"[DEBUG] Processing device: {device_data.keys()}")
            
            device_info = device_data.get('deviceInfo', {})
            
            # Try multiple sources for device name
            device_name = (
                device_data.get('deviceName') or  # Top level deviceName
                device_info.get('deviceName') or  # Inside deviceInfo
                device_data.get('deviceModel') or  # Fallback to model
                'Unknown Device'
            )
            
            # Try multiple sources for device model
            device_model = (
                device_data.get('deviceModel') or
                device_info.get('deviceModel') or
                'Unknown'
            )
            
            # Format last seen timestamp
            last_seen_raw = device_data.get('lastSeenAt', '')
            last_seen_formatted = format_last_seen(last_seen_raw)
            
            device = {
                'code': device_data.get('deviceId', device_data.get('deviceCode', 'unknown')),
                'name': device_name,
                'device_name': device_name,
                'device_model': device_model,
                'device_type': device_data.get('deviceType', 'android'),
                'is_active': device_data.get('isActive', False),
                'android_version': device_data.get('androidVersion', device_info.get('androidVersion', 'Unknown')),
                'app_version': device_data.get('appVersion', device_info.get('appVersion', 'Unknown')),
                'last_seen_at': last_seen_formatted,  # Use formatted timestamp
                'last_seen_raw': last_seen_raw,  # Keep raw for debugging
                'registered_at': device_data.get('registeredAt', ''),
                'brand': device_data.get('brand', device_info.get('brand', 'Unknown')),
                'manufacturer': device_data.get('manufacturer', device_info.get('manufacturer', 'Unknown')),
                'location': {
                    'latitude': device_data.get('latitude'),
                    'longitude': device_data.get('longitude')
                }
            }
            devices.append(device)
        
        print(f"[DEBUG] /dashboard: Successfully processed {len(devices)} devices")
            
        print(f"[DASHBOARD] Successfully loaded {len(devices)} devices from Firebase")
        print(f"[DASHBOARD] Device names: {[d.get('name', 'Unknown') for d in devices]}")
                
    except Exception as e:
        print(f"[DASHBOARD] Error fetching Firebase devices: {e}")
        devices = []
        
    return render_template('Dashboard.html', devices=devices, user_name='User')


# Home route (optional, can be removed if not needed)
@bp.route('/home')
def home():
    try:
        return render_template('index.html')
    except Exception as e:
        print(f"Error rendering home: {e}")
        return "Error loading home page.", 500

@bp.route('/map/<device_id>')
def show_map(device_id):
    try:
        # You can fetch device info from the database if needed
        return render_template('map.html', device_id=device_id)
    except Exception as e:
        print(f"Error rendering map for device {device_id}: {e}")
        return f"Error loading map for device {device_id}.", 500

@bp.route('/get_location/<device_id>')
def get_location(device_id):
    # Fetch the latest location for the device from Firebase
    try:
        from app.utils.firebase_rest_api import get_firebase_client
        
        firebase_uid = session.get('user_id')
        if not firebase_uid:
            return jsonify({'error': 'Not authenticated'}), 401
            
        client = get_firebase_client()
        
        # Find the device by device_code and user_id using REST API
        where_clauses = [
            {
                "fieldFilter": {
                    "field": {"fieldPath": "deviceId"},
                    "op": "EQUAL",
                    "value": {"stringValue": device_id}
                }
            },
            {
                "fieldFilter": {
                    "field": {"fieldPath": "userId"},
                    "op": "EQUAL",
                    "value": {"stringValue": firebase_uid}
                }
            }
        ]
        
        devices_docs = client.query_collection("user_devices", where_clauses, limit=1)
        
        if devices_docs:
            device_data = client._convert_from_firestore_format(devices_docs[0])
            lat = device_data.get('latitude', 0.0)
            lng = device_data.get('longitude', 0.0)
            battery = device_data.get('battery_level', '--')
            network = device_data.get('network_type', '--')
        else:
            lat, lng, battery, network = 0.0, 0.0, '--', '--'
            
        return jsonify({
            'lat': lat,
            'lng': lng,
            'battery': battery,
            'network': network
        })
    except Exception as e:
        print(f"Error getting location for device {device_id}: {e}")
        return jsonify({'error': 'Failed to get device location.'}), 500


# Authentication routes - serve Firebase auth pages
@bp.route('/login')
def login_page():
    try:
        import os
        from flask import send_from_directory, current_app
        firebase_web_dir = os.path.join(current_app.root_path, '..', 'firebase_auth', 'web')
        return send_from_directory(firebase_web_dir, 'login.html')
    except Exception as e:
        print(f"Error serving login page: {e}")
        return "Error loading login page.", 500

@bp.route('/register')
def register_page():
    try:
        import os
        from flask import send_from_directory, current_app
        firebase_web_dir = os.path.join(current_app.root_path, '..', 'firebase_auth', 'web')
        return send_from_directory(firebase_web_dir, 'register.html')
    except Exception as e:
        print(f"Error serving register page: {e}")
        return "Error loading register page.", 500

# Profile route: Only show if authenticated
@bp.route('/profile')
def profile():
    # Use session for authentication
    firebase_uid = session.get('user_id')
    print(f"[DEBUG] /profile session['user_id']: {firebase_uid}")
    if not firebase_uid:
        print("[DEBUG] /profile: Not authenticated, redirecting to login page.")
        return redirect(url_for('main.login_page'))
    
    try:
        from app.utils.firebase_rest import FirebaseRestClient
        
        firebase_client = FirebaseRestClient()
        device_count = 0
        
        try:
            # Get device count from Firebase
            firebase_devices = firebase_client.fetch_user_devices(firebase_uid)
            if firebase_devices and 'success' in firebase_devices and firebase_devices['success']:
                device_count = len(firebase_devices.get('devices', []))
        except Exception as e:
            print(f"[DEBUG] Error fetching device count: {e}")
        
        profile_data = {
            'user_id': firebase_uid,
            'created_at': 'Recently',  # Could implement user creation date in Firebase
            'device_count': device_count
        }
        
        return render_template('profile.html', profile=profile_data)
    except Exception as e:
        print(f"[DEBUG] Error loading profile: {e}")
        return redirect(url_for('main.dashboard'))

# WebSocket test page
@bp.route('/test-websocket')
def test_websocket():
    """Render the WebSocket testing dashboard"""
    try:
        return render_template('test_websocket.html')
    except Exception as e:
        print(f"Error rendering WebSocket test page: {e}")
        return "Error loading WebSocket test page.", 500