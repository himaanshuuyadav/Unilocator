from flask import Blueprint, request, jsonify, session, current_app as app
from ..utils.firebase_rest_api import get_firebase_client, update_user_device_rest
from datetime import datetime
import logging

bp = Blueprint('api', __name__, url_prefix='/api')
logger = logging.getLogger(__name__)

@bp.route('/location/<device_id>', methods=['POST'])
def update_location(device_id):
    """Update device location with comprehensive error handling"""
    try:
        # Validate request data
        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No data provided',
                'code': 'MISSING_DATA'
            }), 400
        
        if 'lat' not in data or 'lng' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Missing required fields: lat and lng',
                'code': 'INVALID_DATA'
            }), 400

        # Validate latitude and longitude ranges
        try:
            lat = float(data['lat'])
            lng = float(data['lng'])
            
            if not (-90 <= lat <= 90):
                return jsonify({
                    'status': 'error',
                    'message': 'Latitude must be between -90 and 90',
                    'code': 'INVALID_LATITUDE'
                }), 400
                
            if not (-180 <= lng <= 180):
                return jsonify({
                    'status': 'error',
                    'message': 'Longitude must be between -180 and 180',
                    'code': 'INVALID_LONGITUDE'
                }), 400
        except (ValueError, TypeError) as e:
            return jsonify({
                'status': 'error',
                'message': 'Latitude and longitude must be valid numbers',
                'code': 'INVALID_NUMBER_FORMAT'
            }), 400

        try:
            client = get_firebase_client()
            
            # Find the device by device_id using REST API
            where_clauses = [{
                "fieldFilter": {
                    "field": {"fieldPath": "deviceId"},
                    "op": "EQUAL",
                    "value": {"stringValue": device_id}
                }
            }]
            
            devices_docs = client.query_collection("user_devices", where_clauses, limit=1)
            
            if not devices_docs:
                return jsonify({
                    'status': 'error',
                    'message': 'Device not found',
                    'code': 'DEVICE_NOT_FOUND',
                    'device_id': device_id
                }), 404
            
            # Update the device location
            update_data = {
                'latitude': lat,
                'longitude': lng,
                'lastSeenAt': datetime.now().isoformat() + "Z"
            }
            
            # Extract document ID from the first device
            doc_name = devices_docs[0].get("name", "")
            doc_id = doc_name.split("/")[-1] if doc_name else device_id
            
            success = update_user_device_rest(doc_id, update_data)
            
            if success:
                # Broadcast location update via WebSocket
                from .websocket_handlers import broadcast_location_update
                broadcast_location_update(device_id, {
                    'lat': lat,
                    'lng': lng
                })
                
                return jsonify({
                    'status': 'ok',
                    'message': 'Location updated successfully',
                    'device_id': device_id,
                    'location': {'lat': lat, 'lng': lng}
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'Failed to update device in database',
                    'code': 'UPDATE_FAILED'
                }), 500
            
        except Exception as db_error:
            logger.error(f"Database error updating location for {device_id}: {db_error}")
            return jsonify({
                'status': 'error',
                'message': 'Database error occurred',
                'code': 'DATABASE_ERROR',
                'details': str(db_error) if app.debug else None
            }), 500
            
    except Exception as e:
        logger.error(f"Unexpected error in update_location for {device_id}: {e}")
        return jsonify({
            'status': 'error',
            'message': 'Internal server error',
            'code': 'INTERNAL_ERROR',
            'details': str(e) if app.debug else None
        }), 500

@bp.route('/fetch-devices-debug', methods=['POST'])
def fetch_devices_debug():
    """
    Debug endpoint to fetch devices using REST API
    Returns detailed debug information and device data
    """
    from flask import session
    from ..utils.firebase_rest_api import fetch_user_devices_rest
    import logging
    from datetime import datetime
    
    try:
        # Get user ID from session
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'User not authenticated - please login again',
                'debug_info': {
                    'session_data': {k: v for k, v in dict(session).items() if k != 'csrf_token'},
                    'timestamp': datetime.now().isoformat(),
                    'message': 'Session may have expired. Please refresh and login again.'
                }
            }), 401
        
        logging.info(f"[DEBUG API] Starting device fetch for user: {user_id}")
        
        # Use REST API strategy
        try:
            logging.info("[DEBUG API] Using Firebase REST API")
            devices_list = fetch_user_devices_rest(user_id)
            
            if devices_list:
                return jsonify({
                    'success': True,
                    'devices': devices_list,
                    'device_count': len(devices_list),
                    'strategy_used': 'rest_api',
                    'logs': [
                        f'✅ Successfully fetched {len(devices_list)} devices',
                        f'🔥 Using Firebase REST API',
                        f'📱 Device count: {len(devices_list)}'
                    ]
                })
            else:
                return jsonify({
                    'success': True,
                    'devices': [],
                    'device_count': 0,
                    'strategy_used': 'rest_api',
                    'logs': [
                        '✅ REST API call successful',
                        '📭 No devices found for this user',
                        '🔍 This may be normal for new users'
                    ]
                })
        
        except Exception as e:
            logging.error(f"[DEBUG API] REST API error: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
                'strategy_used': 'rest_api',
                'logs': [f'❌ REST API exception: {e}']
            })
        
    except Exception as e:
        logging.error(f"[DEBUG API] Critical error: {e}")
        return jsonify({
            'success': False,
            'error': f'Critical error: {str(e)}',
            'debug_info': {
                'timestamp': datetime.now().isoformat(),
                'user_id': user_id if 'user_id' in locals() else 'unknown'
            }
        }), 500
        
        # Fetch devices with debug info
        debug_result = fetch_user_devices_debug(user_id)
        
        # Log the result
        logging.info(f"[DEBUG API] Device fetch completed. Success: {debug_result['success']}, Count: {debug_result['document_count']}")
        
        return jsonify({
            'success': debug_result['success'],
            'user_id': user_id,
            'device_count': debug_result['document_count'],
            'devices': debug_result['devices'],
            'debug_info': debug_result,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        error_msg = str(e)
        logging.error(f"[DEBUG API] Error in fetch-devices-debug: {error_msg}")
        
        return jsonify({
            'success': False,
            'error': error_msg,
            'debug_info': {
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'user_id': session.get('user_id', 'Not found')
            }
        }), 500

@bp.route('/test-firebase-simple', methods=['POST'])
def test_firebase_simple():
    """
    Simple Firebase connectivity test without complex queries
    """
    from flask import session
    from ..utils.firebase_utils import get_firestore_db
    import logging
    from datetime import datetime
    
    debug_result = {
        'timestamp': datetime.now().isoformat(),
        'steps': [],
        'success': False,
        'user_id': None,
        'error': None
    }
    
    try:
        # Step 1: Check user authentication
        user_id = session.get('user_id')
        debug_result['user_id'] = user_id
        debug_result['steps'].append(f"[1] ✅ User ID from session: {user_id}")
        
        if not user_id:
            debug_result['error'] = 'User not authenticated - please login again'
            debug_result['debug_info'] = {
                'session_data': {k: v for k, v in dict(session).items() if k != 'csrf_token'},
                'message': 'Session may have expired. Please refresh and login again.'
            }
            return jsonify(debug_result), 401
            
        # Step 2: Get Firebase connection
        debug_result['steps'].append("[2] Connecting to Firestore...")
        db = get_firestore_db()
        debug_result['steps'].append("[2] ✅ Firestore connection established")
        
        # Step 3: Test basic collection access (simplified)
        debug_result['steps'].append("[3] Testing user_devices collection access...")
        user_devices_ref = db.collection('user_devices')
        debug_result['steps'].append("[3] ✅ Referenced user_devices collection")
        
        # Step 4: Try a simple count operation instead of listing all collections
        try:
            debug_result['steps'].append("[4] Attempting simple document count...")
            # Use a simple limit query instead of collections listing
            docs = user_devices_ref.limit(1).get()
            doc_count = len(docs)
            debug_result['steps'].append(f"[4] ✅ Simple query successful, found {doc_count} sample documents")
            
            if doc_count > 0:
                debug_result['steps'].append("[5] Checking document structure...")
                sample_doc = docs[0]
                sample_data = sample_doc.to_dict()
                
                debug_result['steps'].append(f"[5] Sample document ID: {sample_doc.id}")
                debug_result['steps'].append(f"[5] Sample document keys: {list(sample_data.keys())}")
                
                # Check if userId field exists
                if 'userId' in sample_data:
                    debug_result['steps'].append(f"[5] ✅ userId field found: {sample_data['userId']}")
                    
                    # Check if it matches our user
                    if sample_data['userId'] == user_id:
                        debug_result['steps'].append("[5] ✅ Found device belonging to current user!")
                    else:
                        debug_result['steps'].append(f"[5] ⚠️ Sample device belongs to different user: {sample_data['userId']}")
                else:
                    debug_result['steps'].append("[5] ⚠️ No userId field in documents")
            else:
                debug_result['steps'].append("[5] ⚠️ No devices found in user_devices collection")
                
        except Exception as query_error:
            debug_result['steps'].append(f"[4] ❌ Query failed: {query_error}")
            debug_result['collection_exists'] = False
        
        debug_result['success'] = True
        debug_result['steps'].append("[FINAL] ✅ Firebase connectivity test completed successfully")
        
    except Exception as e:
        error_msg = str(e)
        debug_result['error'] = error_msg
        debug_result['steps'].append(f"[ERROR] ❌ {error_msg}")
        logging.error(f"Firebase simple test error: {error_msg}")
    
    return jsonify(debug_result)

@bp.route('/test-firebase-direct', methods=['POST'])
def test_firebase_direct():
    """
    Direct Firebase test - bypasses collections() call and goes straight to user_devices
    """
    from flask import session
    from ..utils.firebase_utils import get_firestore_db
    import logging
    from datetime import datetime
    
    debug_result = {
        'timestamp': datetime.now().isoformat(),
        'steps': [],
        'success': False,
        'user_id': None,
        'error': None
    }
    
    try:
        # Step 1: Check user authentication
        user_id = session.get('user_id')
        debug_result['user_id'] = user_id
        debug_result['steps'].append(f"[1] ✅ User ID from session: {user_id}")
        
        if not user_id:
            debug_result['error'] = 'User not authenticated - please login again'
            return jsonify(debug_result), 401
            
        # Step 2: Get Firebase connection
        debug_result['steps'].append("[2] Connecting to Firestore...")
        db = get_firestore_db()
        debug_result['steps'].append("[2] ✅ Firestore connection established")
        
        # Step 3: Direct test of user_devices collection
        debug_result['steps'].append("[3] Testing user_devices collection directly...")
        user_devices_ref = db.collection('user_devices')
        debug_result['steps'].append("[3] ✅ user_devices collection reference created")
        
        # Step 4: Try to get just 1 document to test collection access
        debug_result['steps'].append("[4] Attempting to get 1 document from user_devices...")
        
        import time
        start_time = time.time()
        
        # Use get() with limit instead of stream() 
        docs = user_devices_ref.limit(1).get()
        
        elapsed = time.time() - start_time
        debug_result['steps'].append(f"[4] ✅ Query completed in {elapsed:.2f} seconds")
        
        doc_count = len(docs)
        debug_result['steps'].append(f"[4] Found {doc_count} documents in collection")
        
        if doc_count > 0:
            sample_doc = docs[0]
            sample_data = sample_doc.to_dict()
            debug_result['steps'].append(f"[5] Sample document ID: {sample_doc.id}")
            debug_result['steps'].append(f"[5] Sample document keys: {list(sample_data.keys())}")
            
            # Check if this is our user's device
            doc_user_id = sample_data.get('userId', 'Not found')
            debug_result['steps'].append(f"[5] Sample document userId: {doc_user_id}")
            
            if doc_user_id == user_id:
                debug_result['steps'].append("[5] ✅ Found device belonging to current user!")
            else:
                debug_result['steps'].append("[5] ⚠️ Sample device belongs to different user")
        else:
            debug_result['steps'].append("[5] ⚠️ No documents found in user_devices collection")
        
        debug_result['success'] = True
        debug_result['steps'].append("[FINAL] ✅ Direct Firebase test completed successfully")
        
    except Exception as e:
        error_msg = str(e)
        debug_result['error'] = error_msg
        debug_result['steps'].append(f"[ERROR] ❌ {error_msg}")
        logging.error(f"Firebase direct test error: {error_msg}")
    
    return jsonify(debug_result)

@bp.route('/test-basic-auth', methods=['POST'])
def test_basic_auth():
    """
    Ultra-simple authentication test - no Firebase queries
    """
    from flask import session
    from datetime import datetime
    
    result = {
        'timestamp': datetime.now().isoformat(),
        'success': True,
        'user_id': session.get('user_id'),
        'session_keys': list(session.keys()),
        'session_data': {k: v for k, v in dict(session).items() if k != 'csrf_token'},
        'message': 'Basic auth test completed'
    }
    
    return jsonify(result)

@bp.route('/test-web-sdk', methods=['POST'])
def test_web_sdk():
    """
    Test Firebase Web SDK connectivity from client-side
    This endpoint just validates session, actual work is done in JavaScript
    """
    from flask import session
    from datetime import datetime
    import logging
    
    try:
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'User not authenticated',
                'message': 'Please login first'
            }), 401
        
        logging.info(f"[WEB SDK TEST] User {user_id} testing Web SDK")
        
        return jsonify({
            'success': True,
            'user_id': user_id,
            'message': 'Session valid, proceed with Web SDK test',
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logging.error(f"[WEB SDK TEST] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/test-simple-connection', methods=['POST'])
def test_simple_connection():
    """
    Ultra-simple Firebase connectivity test
    Tests basic connection without complex authentication
    """
    from ..utils.simple_firebase_test import simple_firebase_test, test_with_api_key
    import logging
    from datetime import datetime
    
    try:
        logging.info("[SIMPLE TEST] Starting simple Firebase test")
        
        results = []
        
        # Test 1: Basic connectivity
        basic_result = simple_firebase_test()
        results.append({
            'test': 'basic_connectivity',
            'result': basic_result
        })
        
        # Test 2: API key test
        api_result = test_with_api_key()
        results.append({
            'test': 'api_key_test',
            'result': api_result
        })
        
        # Determine overall success
        overall_success = any(test['result']['success'] for test in results)
        
        return jsonify({
            'success': overall_success,
            'timestamp': datetime.now().isoformat(),
            'tests': results,
            'summary': {
                'total_tests': len(results),
                'passed_tests': sum(1 for test in results if test['result']['success'])
            }
        })
        
    except Exception as e:
        logging.error(f"[SIMPLE TEST] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@bp.route('/fetch-devices-production', methods=['POST'])
def fetch_devices_production():
    """
    Production endpoint to fetch devices using the working REST API method
    Returns devices in format ready for dashboard display
    """
    from flask import session
    from ..utils.firebase_rest import get_rest_client
    import logging
    from datetime import datetime
    
    try:
        # Get user ID from session
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'User not authenticated'
            }), 401
        
        logging.info(f"[PRODUCTION] Fetching devices for user: {user_id}")
        
        # Use the working REST API method
        rest_client = get_rest_client()
        if not rest_client or not rest_client.credentials:
            return jsonify({
                'success': False,
                'error': 'Firebase REST client not available'
            }), 500
        
        result = rest_client.fetch_user_devices(user_id)
        
        if result['success']:
            # Format devices for dashboard display using the correct Firebase structure
            formatted_devices = []
            for device in result['devices']:
                device_info = device.get('deviceInfo', {})
                formatted_device = {
                    'id': device.get('deviceId', 'Unknown'),
                    'name': device.get('deviceName', 'Unknown Device'),  # Direct field
                    'device_code': device.get('deviceId', 'Unknown'),
                    'device_name': device.get('deviceName', 'Unknown Device'),  # Direct field
                    'model': device.get('deviceModel', 'Unknown Model'),  # Direct field
                    'brand': device_info.get('brand', 'Unknown').title(),  # From deviceInfo
                    'manufacturer': device_info.get('manufacturer', 'Unknown').title(),  # From deviceInfo
                    'product': device_info.get('product', 'Unknown'),  # From deviceInfo
                    'android_version': device.get('androidVersion', 'Unknown'),  # Direct field
                    'app_version': device.get('appVersion', 'Unknown'),  # Direct field
                    'device_type': device.get('deviceType', 'android'),  # Direct field
                    'is_active': device.get('isActive', False),  # Direct field
                    'os_version': f"Android {device.get('androidVersion', 'Unknown')}",
                    'connected_at': device.get('registeredAt', 'Unknown'),  # registeredAt field
                    'last_seen': device.get('lastSeenAt', 'Unknown'),  # lastSeenAt field
                    'location': {
                        'lat': device.get('lastLocation', {}).get('latitude', 0),
                        'lng': device.get('lastLocation', {}).get('longitude', 0)
                    },
                    'status': 'connected' if device.get('isActive', False) else 'offline'
                }
                formatted_devices.append(formatted_device)
            
            logging.info(f"[PRODUCTION] Successfully formatted {len(formatted_devices)} devices")
            
            return jsonify({
                'success': True,
                'devices': formatted_devices,
                'count': len(formatted_devices),
                'user_id': user_id
            })
        else:
            logging.error(f"[PRODUCTION] Device fetch failed: {result['error']}")
            return jsonify({
                'success': False,
                'error': result['error'],
                'logs': result.get('logs', [])
            }), 500
            
    except Exception as e:
        logging.error(f"[PRODUCTION] Critical error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/debug-device-data', methods=['POST'])
def debug_device_data():
    """
    Debug endpoint to see the raw Firebase device data structure
    """
    from flask import session
    from ..utils.firebase_rest import get_rest_client
    import logging
    from datetime import datetime
    from google.cloud.firestore_v1.base_query import FieldFilter
    
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'Not authenticated'}), 401
        
        logging.info(f"[DEBUG DATA] Fetching raw device data for user: {user_id}")
        
        rest_client = get_rest_client()
        if not rest_client or not rest_client.credentials:
            return jsonify({'success': False, 'error': 'REST client not available'}), 500
        
        result = rest_client.fetch_user_devices(user_id)
        
        if result['success']:
            # Return the raw device data for inspection
            return jsonify({
                'success': True,
                'raw_devices': result['devices'],
                'device_count': len(result['devices']),
                'sample_device': result['devices'][0] if result['devices'] else None,
                'all_device_keys': [list(device.keys()) for device in result['devices'][:2]]  # First 2 devices' keys
            })
        else:
            return jsonify({
                'success': False,
                'error': result['error'],
                'logs': result.get('logs', [])
            })
            
    except Exception as e:
        logging.error(f"[DEBUG DATA] Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/device/<device_id>/battery', methods=['GET'])
def get_device_battery(device_id):
    """Get device battery status"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Not authenticated'
            }), 401
        
        client = get_firebase_client()
        
        # Find the device
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
                    "value": {"stringValue": user_id}
                }
            }
        ]
        
        devices_docs = client.query_collection("user_devices", where_clauses, limit=1)
        
        if devices_docs:
            device_data = client._convert_from_firestore_format(devices_docs[0])
            
            # Get battery info from deviceInfo or top level
            device_info = device_data.get('deviceInfo', {})
            battery_level = device_data.get('batteryLevel', device_info.get('batteryLevel', 75))  # Default 75%
            battery_status = device_data.get('batteryStatus', device_info.get('batteryStatus', 'unknown'))
            is_charging = device_data.get('isCharging', device_info.get('isCharging', False))
            
            return jsonify({
                'success': True,
                'battery_level': battery_level,
                'battery_status': battery_status,
                'is_charging': is_charging
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Device not found'
            }), 404
            
    except Exception as e:
        logger.error(f"Error getting battery status for {device_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/device/<device_id>/location-history', methods=['GET'])
def get_location_history(device_id):
    """Get device location history"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Not authenticated'
            }), 401
        
        # Get days parameter (default 7 days)
        days = int(request.args.get('days', 7))
        
        client = get_firebase_client()
        
        # Find the device
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
                    "value": {"stringValue": user_id}
                }
            }
        ]
        
        devices_docs = client.query_collection("user_devices", where_clauses, limit=1)
        
        if not devices_docs:
            return jsonify({
                'success': False,
                'error': 'Device not found'
            }), 404
        
        device_data = client._convert_from_firestore_format(devices_docs[0])
        
        # Get location history from locationHistory field or create sample
        location_history = device_data.get('locationHistory', [])
        
        # If no history, create sample based on current location
        if not location_history:
            current_lat = device_data.get('lastLocation', {}).get('latitude', 0)
            current_lng = device_data.get('lastLocation', {}).get('longitude', 0)
            
            if current_lat and current_lng:
                # Generate sample history for demo
                from datetime import datetime, timedelta
                import random
                
                history = []
                for i in range(24):  # Last 24 hours
                    timestamp = datetime.now() - timedelta(hours=i)
                    # Add small random offset for realistic movement
                    lat_offset = random.uniform(-0.01, 0.01)
                    lng_offset = random.uniform(-0.01, 0.01)
                    
                    history.append({
                        'latitude': current_lat + lat_offset,
                        'longitude': current_lng + lng_offset,
                        'timestamp': timestamp.isoformat(),
                        'accuracy': random.randint(5, 50)
                    })
                
                location_history = history
        
        return jsonify({
            'success': True,
            'device_id': device_id,
            'history': location_history[:100],  # Limit to 100 points
            'count': len(location_history)
        })
            
    except Exception as e:
        logger.error(f"Error getting location history for {device_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
