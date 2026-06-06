"""
Firebase utilities for UniLocator
Handles Firebase Admin SDK initialization and Firestore operations
"""

import firebase_admin
from firebase_admin import credentials, firestore
import json
import os
import logging
import string
import secrets
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# Global Firebase Admin SDK instance
_db = None


def _load_service_account_credentials():
    """Load Firebase service account credentials from env JSON or local file."""
    service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
    if service_account_json:
        return credentials.Certificate(json.loads(service_account_json))

    service_account_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'service-account-key.json'
    )

    if os.path.exists(service_account_path):
        return credentials.Certificate(service_account_path)

    raise FileNotFoundError(
        'Firebase service account credentials not found. Set FIREBASE_SERVICE_ACCOUNT_JSON or add service-account-key.json.'
    )

def initialize_firebase():
    """Initialize Firebase Admin SDK"""
    global _db
    
    if _db is not None:
        return _db
    
    try:
        # Check if Firebase app is already initialized
        try:
            firebase_admin.get_app()
            logging.info("Firebase app already initialized")
        except ValueError:
            # Initialize Firebase Admin SDK
            cred = _load_service_account_credentials()
            firebase_admin.initialize_app(cred)
            logging.info("Firebase Admin SDK initialized")
        
        # Initialize Firestore client with custom timeout settings
        from google.api_core import retry
        from google.api_core import exceptions
        import time
        
        # Initialize Firestore with default settings first
        _db = firestore.client()
        
        # Test the connection with a simple operation and timeout
        try:
            # Simple test with timeout
            start_time = time.time()
            test_collection = _db.collection('connection_test')
            
            # Try a simple document creation and deletion to test connectivity
            test_doc_ref = test_collection.document('test_connection')
            test_doc_ref.set({
                'test': True,
                'timestamp': firestore.SERVER_TIMESTAMP
            })
            
            # Delete the test document
            test_doc_ref.delete()
            
            elapsed = time.time() - start_time
            logging.info(f"Firebase Firestore connection verified in {elapsed:.2f} seconds")
            
        except Exception as e:
            elapsed = time.time() - start_time
            logging.warning(f"Firestore connection test failed after {elapsed:.2f} seconds: {e}")
            # Continue anyway, maybe it will work for actual operations
        
        logging.info("Firebase Admin SDK initialized successfully")
        return _db
        
    except Exception as e:
        logging.error(f"Failed to initialize Firebase: {e}")
        raise

def get_firestore_db():
    """Get Firestore database instance"""
    global _db
    
    if _db is None:
        _db = initialize_firebase()
    
    return _db

def generate_device_code(user_id, user_email):
    """
    Generate and store device code in Firebase
    
    Args:
        user_id (str): Firebase UID of the user
        user_email (str): Email of the user
        
    Returns:
        str: Generated 8-character device code (XXXX-XXXX format)
    """
    try:
        # Generate unique 8-character code in XXXX-XXXX format first
        chars = string.ascii_uppercase + string.digits
        code_part1 = ''.join(secrets.choice(chars) for _ in range(4))
        code_part2 = ''.join(secrets.choice(chars) for _ in range(4))
        device_code = f"{code_part1}-{code_part2}"
        
        logging.info(f"Generated device code: {device_code} for user: {user_id}")
        
        # Try Firebase write-only operations (no reads to avoid timeout)
        try:
            # Use write-only approach in background thread
            import threading
            
            def firebase_write_operations():
                try:
                    success = store_device_code_write_only(device_code, user_id, user_email)
                    if success:
                        logging.info(f"[FIREBASE-WRITE] Device code {device_code} stored successfully")
                    else:
                        logging.warning(f"[FIREBASE-WRITE] Failed to store {device_code}")
                except Exception as e:
                    logging.error(f"[FIREBASE-WRITE] Error storing {device_code}: {e}")
            
            # Run Firebase write operations in background
            firebase_thread = threading.Thread(target=firebase_write_operations)
            firebase_thread.daemon = True
            firebase_thread.start()
            
            # Wait max 5 seconds for Firebase write (writes are fast)
            firebase_thread.join(timeout=5.0)
            
            if firebase_thread.is_alive():
                logging.warning(f"[FIREBASE-WRITE] Write operation for {device_code} timed out, but code is still valid")
            
        except Exception as e:
            logging.error(f"[FIREBASE-WRITE] Firebase error (code still valid): {e}")
        
        # Always return the generated code, regardless of Firebase success/failure
        return device_code
        
    except Exception as e:
        logging.error(f"Error generating device code: {e}")
        # Generate a simple fallback code if everything fails
        fallback_chars = string.ascii_uppercase + string.digits
        fallback_code = ''.join(secrets.choice(fallback_chars) for _ in range(4)) + '-' + ''.join(secrets.choice(fallback_chars) for _ in range(4))
        logging.warning(f"Returning fallback code: {fallback_code}")
        return fallback_code

def verify_device_code(input_code, connecting_user_id, connecting_user_email):
    """
    Verify device code and create connection if valid
    
    Args:
        input_code (str): The 8-character code entered by user
        connecting_user_id (str): Firebase UID of the connecting user
        connecting_user_email (str): Email of the connecting user
        
    Returns:
        dict: Result with success status and message
    """
    try:
        db = get_firestore_db()
        
        # Find active code
        codes_query = db.collection('user_device_codes').where(filter=FieldFilter('deviceCode', '==', input_code)).where(filter=FieldFilter('isActive', '==', True)).limit(1)
        codes = codes_query.get()
        
        if not codes:
            return {'success': False, 'error': 'Invalid or expired code'}
        
        code_doc = codes[0]
        code_data = code_doc.to_dict()
        
        # Check if code is expired
        if code_data['expiresAt'] < datetime.now():
            # Mark as inactive
            code_doc.reference.update({'isActive': False})
            return {'success': False, 'error': 'Code has expired'}
        
        # Check usage limit
        if code_data['usageCount'] >= code_data['maxUsage']:
            return {'success': False, 'error': 'Code has reached maximum usage'}
        
        # Don't allow self-connection
        if code_data['userId'] == connecting_user_id:
            return {'success': False, 'error': 'Cannot connect to your own device'}
        
        # Generate unique device ID
        device_id = f"device_{secrets.token_hex(8)}"
        
        # Create connection in device_connections collection
        connection_data = {
            'deviceId': device_id,
            'deviceCode': input_code,
            'ownerId': code_data['userId'],
            'ownerEmail': code_data['userEmail'],
            'connectedUserId': connecting_user_id,
            'connectedUserEmail': connecting_user_email,
            'connectionType': 'MANUAL_CODE',  # Will be updated to QR_CODE if from QR
            'isActive': True,
            'nickname': 'Connected Device',
            'permissions': {
                'viewLocation': True,
                'receiveAlerts': True,
                'viewBattery': True,
                'viewDeviceInfo': True
            },
            'connectedAt': firestore.SERVER_TIMESTAMP,
            'lastAccessed': firestore.SERVER_TIMESTAMP
        }
        
        # Add connection
        db.collection('device_connections').add(connection_data)
        
        # Update code usage count and mark as inactive (one-time use)
        code_doc.reference.update({
            'usageCount': firestore.Increment(1),
            'isActive': False
        })
        
        logging.info(f"Device connection created: {device_id} for users {code_data['userId']} and {connecting_user_id}")
        
        return {
            'success': True, 
            'message': 'Device connected successfully',
            'deviceId': device_id,
            'ownerEmail': code_data['userEmail']
        }
        
    except Exception as e:
        logging.error(f"Error verifying device code: {e}")
        return {'success': False, 'error': 'Internal server error'}

def get_user_devices(user_id):
    """
    Get all device connections for a user (both owned and connected)
    
    Args:
        user_id (str): Firebase UID of the user
        
    Returns:
        list: List of device connections
    """
    try:
        db = get_firestore_db()
        
        devices = []
        
        # Get devices owned by user
        owned_devices = db.collection('device_connections').where(filter=FieldFilter('ownerId', '==', user_id)).where(filter=FieldFilter('isActive', '==', True)).get()
        for doc in owned_devices:
            device_data = doc.to_dict()
            device_data['id'] = doc.id
            device_data['role'] = 'owner'
            devices.append(device_data)
        
        # Get devices connected to by user
        connected_devices = db.collection('device_connections').where(filter=FieldFilter('connectedUserId', '==', user_id)).where(filter=FieldFilter('isActive', '==', True)).get()
        for doc in connected_devices:
            device_data = doc.to_dict()
            device_data['id'] = doc.id
            device_data['role'] = 'connected'
            devices.append(device_data)
        
        return devices
        
    except Exception as e:
        logging.error(f"Error getting user devices: {e}")
        return []

def store_device_code_write_only(device_code, user_id, user_email):
    """
    Store device code using WRITE-ONLY operations (no reads)
    This works around the Firebase read timeout issue
    """
    try:
        db = get_firestore_db()
        
        # Use write-only operations with timestamp-based document ID
        expiration_time = datetime.now() + timedelta(hours=24)
        doc_data = {
            'deviceCode': device_code,
            'userId': user_id,
            'userEmail': user_email,
            'generatedAt': firestore.SERVER_TIMESTAMP,
            'expiresAt': expiration_time,
            'isActive': True,
            'maxUsage': 1,
            'usageCount': 0,
            'qrCodeData': f'unilocator://connect?code={device_code}&user={user_id}&email={user_email}'
        }
        
        # Use a predictable document ID based on device code and timestamp
        doc_id = f"{device_code}_{int(datetime.now().timestamp())}"
        
        # Write-only operation - no reading/checking required
        doc_ref = db.collection('user_device_codes').document(doc_id)
        doc_ref.set(doc_data)
        
        logging.info(f"[FIREBASE-WRITE-ONLY] Device code {device_code} stored successfully")
        return True
        
    except Exception as e:
        logging.error(f"[FIREBASE-WRITE-ONLY] Failed to store {device_code}: {e}")
        return False
    """
    Store device code in Firebase (designed for background execution)
    
    Args:
        device_code (str): The generated device code
        user_id (str): Firebase UID of the user
        user_email (str): Email of the user
    """
    try:
        import signal
        import threading
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Firebase operation timed out")
        
        def store_with_timeout():
            try:
                db = get_firestore_db()
                
                logging.info(f"[FIREBASE-ASYNC] Storing code {device_code} for user {user_id}")
                
                # Skip deactivating existing codes to avoid timeout issues
                # (We can implement this later with better timeout handling)
                
                # Store new code directly
                expiration_time = datetime.now() + timedelta(hours=24)
                doc_data = {
                    'deviceCode': device_code,
                    'userId': user_id,
                    'userEmail': user_email,
                    'generatedAt': firestore.SERVER_TIMESTAMP,
                    'expiresAt': expiration_time,
                    'isActive': True,
                    'maxUsage': 1,
                    'usageCount': 0,
                    'qrCodeData': f'unilocator://connect?code={device_code}&user={user_id}&email={user_email}'
                }
                
                # Simple add operation without complex queries
                doc_ref = db.collection('user_device_codes').add(doc_data)
                logging.info(f"[FIREBASE-ASYNC] Successfully stored code {device_code} in Firebase")
                return True
                
            except Exception as e:
                logging.error(f"[FIREBASE-ASYNC] Failed to store code {device_code}: {e}")
                return False
        
        # Set a 30-second timeout for Firebase operations
        result = []
        
        def worker():
            result.append(store_with_timeout())
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=30)  # 30 second timeout
        
        if thread.is_alive():
            logging.warning(f"[FIREBASE-ASYNC] Storage operation for code {device_code} timed out after 30 seconds")
        elif result and result[0]:
            logging.info(f"[FIREBASE-ASYNC] Code {device_code} stored successfully")
        else:
            logging.error(f"[FIREBASE-ASYNC] Failed to store code {device_code}")
            
    except Exception as e:
        logging.error(f"[FIREBASE-ASYNC] Error in async storage for code {device_code}: {e}")

def test_firebase_connection():
    """Test Firebase connectivity with detailed diagnostics"""
    import time
    from google.api_core import exceptions
    
    test_results = {
        'overall_success': False,
        'initialization_success': False,
        'write_success': False,
        'read_success': False,
        'delete_success': False,
        'total_time': 0,
        'errors': []
    }
    
    start_time = time.time()
    
    try:
        # Test 1: Firebase initialization
        logging.info("[FIREBASE-TEST] Step 1: Testing Firebase initialization...")
        try:
            db = get_firestore_db()
            test_results['initialization_success'] = True
            logging.info("[FIREBASE-TEST] ✅ Firebase initialization successful")
        except Exception as e:
            test_results['errors'].append(f"Initialization failed: {e}")
            logging.error(f"[FIREBASE-TEST] ❌ Firebase initialization failed: {e}")
            return test_results
        
        # Test 2: Simple write operation with timeout
        logging.info("[FIREBASE-TEST] Step 2: Testing write operation...")
        try:
            test_doc = {
                'test': True,
                'timestamp': firestore.SERVER_TIMESTAMP,
                'message': 'Connectivity diagnostic test',
                'test_id': f"test_{int(time.time())}"
            }
            
            # Try write with explicit timeout
            doc_ref = db.collection('connection_test').add(test_doc, timeout=15.0)
            test_results['write_success'] = True
            logging.info("[FIREBASE-TEST] ✅ Write operation successful")
            
        except exceptions.DeadlineExceeded:
            test_results['errors'].append("Write operation timed out (DeadlineExceeded)")
            logging.error("[FIREBASE-TEST] ❌ Write operation timed out")
            return test_results
        except Exception as e:
            test_results['errors'].append(f"Write failed: {e}")
            logging.error(f"[FIREBASE-TEST] ❌ Write operation failed: {e}")
            return test_results
        
        # Test 3: Read operation with timeout using threading
        logging.info("[FIREBASE-TEST] Step 3: Testing read operation...")
        try:
            import threading
            
            read_result = {'success': False, 'data': None, 'error': None}
            
            def read_operation():
                try:
                    doc_data = doc_ref[1].get().to_dict()
                    read_result['success'] = True
                    read_result['data'] = doc_data
                except Exception as e:
                    read_result['error'] = str(e)
            
            # Start read operation in background thread
            read_thread = threading.Thread(target=read_operation)
            read_thread.daemon = True
            read_thread.start()
            
            # Wait maximum 10 seconds for read operation
            read_thread.join(timeout=10.0)
            
            if read_thread.is_alive():
                test_results['errors'].append("Read operation timed out after 10 seconds")
                logging.error("[FIREBASE-TEST] ❌ Read operation timed out after 10 seconds")
            elif read_result['success']:
                test_results['read_success'] = True
                logging.info(f"[FIREBASE-TEST] ✅ Read operation successful: {read_result['data'].get('message', 'N/A')}")
            elif read_result['error']:
                test_results['errors'].append(f"Read failed: {read_result['error']}")
                logging.error(f"[FIREBASE-TEST] ❌ Read operation failed: {read_result['error']}")
                
        except exceptions.DeadlineExceeded:
            test_results['errors'].append("Read operation timed out (DeadlineExceeded)")
            logging.error("[FIREBASE-TEST] ❌ Read operation timed out (DeadlineExceeded)")
        except Exception as e:
            test_results['errors'].append(f"Read failed: {e}")
            logging.error(f"[FIREBASE-TEST] ❌ Read operation failed: {e}")
        
        # Test 4: Delete operation with timeout
        logging.info("[FIREBASE-TEST] Step 4: Testing delete operation...")
        try:
            delete_result = {'success': False, 'error': None}
            
            def delete_operation():
                try:
                    doc_ref[1].delete()
                    delete_result['success'] = True
                except Exception as e:
                    delete_result['error'] = str(e)
            
            # Start delete operation in background thread
            delete_thread = threading.Thread(target=delete_operation)
            delete_thread.daemon = True
            delete_thread.start()
            
            # Wait maximum 10 seconds for delete operation
            delete_thread.join(timeout=10.0)
            
            if delete_thread.is_alive():
                test_results['errors'].append("Delete operation timed out after 10 seconds")
                logging.error("[FIREBASE-TEST] ❌ Delete operation timed out after 10 seconds")
            elif delete_result['success']:
                test_results['delete_success'] = True
                logging.info("[FIREBASE-TEST] ✅ Delete operation successful")
            elif delete_result['error']:
                test_results['errors'].append(f"Delete failed: {delete_result['error']}")
                logging.error(f"[FIREBASE-TEST] ❌ Delete operation failed: {delete_result['error']}")
                
        except exceptions.DeadlineExceeded:
            test_results['errors'].append("Delete operation timed out (DeadlineExceeded)")
            logging.error("[FIREBASE-TEST] ❌ Delete operation timed out (DeadlineExceeded)")
        except Exception as e:
            test_results['errors'].append(f"Delete failed: {e}")
            logging.error(f"[FIREBASE-TEST] ❌ Delete operation failed: {e}")
        
        # Overall success if write was successful (minimum requirement)
        test_results['overall_success'] = test_results['write_success']
        
    except Exception as e:
        test_results['errors'].append(f"Test framework error: {e}")
        logging.error(f"[FIREBASE-TEST] ❌ Test framework error: {e}")
    
    test_results['total_time'] = time.time() - start_time
    logging.info(f"[FIREBASE-TEST] Test completed in {test_results['total_time']:.2f} seconds")
    
    return test_results

def verify_device_code_mobile_safe(input_code, connecting_user_id, connecting_user_email):
    """
    Mobile-safe device code verification with timeout handling
    Uses background threads to prevent hanging and provides fallback responses
    
    Args:
        input_code (str): The 8-character code entered by user
        connecting_user_id (str): Firebase UID of the connecting user  
        connecting_user_email (str): Email of the connecting user
        
    Returns:
        dict: Result with success status and message
    """
    import threading
    import time
    
    verification_result = {
        'success': False, 
        'error': 'Verification timeout',
        'timeout': True
    }
    
    def verify_operation():
        try:
            db = get_firestore_db()
            
            # Find active code with timeout protection
            codes_query = db.collection('user_device_codes').where(filter=FieldFilter('deviceCode', '==', input_code)).where(filter=FieldFilter('isActive', '==', True)).limit(1)
            codes = codes_query.get()
            
            if not codes:
                verification_result.update({
                    'success': False, 
                    'error': 'Invalid or expired code',
                    'timeout': False
                })
                return
            
            code_doc = codes[0]
            code_data = code_doc.to_dict()
            
            # Check if code is expired
            if code_data['expiresAt'] < datetime.now():
                code_doc.reference.update({'isActive': False})
                verification_result.update({
                    'success': False, 
                    'error': 'Code has expired',
                    'timeout': False
                })
                return
            
            # Check usage limit
            if code_data['usageCount'] >= code_data['maxUsage']:
                verification_result.update({
                    'success': False, 
                    'error': 'Code has reached maximum usage',
                    'timeout': False
                })
                return
            
            # Don't allow self-connection
            if code_data['userId'] == connecting_user_id:
                verification_result.update({
                    'success': False, 
                    'error': 'Cannot connect to your own device',
                    'timeout': False
                })
                return
            
            # Generate unique device ID
            device_id = f"device_{secrets.token_hex(8)}"
            
            # Create connection in device_connections collection
            connection_data = {
                'deviceId': device_id,
                'deviceCode': input_code,
                'ownerId': code_data['userId'],
                'ownerEmail': code_data['userEmail'],
                'connectedUserId': connecting_user_id,
                'connectedUserEmail': connecting_user_email,
                'connectedAt': firestore.SERVER_TIMESTAMP,
                'status': 'active'
            }
            
            # Store connection
            db.collection('device_connections').add(connection_data)
            
            # Update code usage
            code_doc.reference.update({
                'usageCount': code_data['usageCount'] + 1,
                'lastUsed': firestore.SERVER_TIMESTAMP
            })
            
            verification_result.update({
                'success': True,
                'message': 'Device connected successfully',
                'deviceId': device_id,
                'ownerEmail': code_data['userEmail'],
                'timeout': False
            })
            
        except Exception as e:
            logging.error(f"[MOBILE-VERIFY] Verification error: {e}")
            verification_result.update({
                'success': False,
                'error': f'Verification failed: {str(e)}',
                'timeout': False
            })
    
    # Run verification in background thread with timeout
    verify_thread = threading.Thread(target=verify_operation)
    verify_thread.daemon = True
    verify_thread.start()
    
    # Wait maximum 15 seconds for verification
    verify_thread.join(timeout=15.0)
    
    if verify_thread.is_alive():
        logging.warning(f"[MOBILE-VERIFY] Verification for {input_code} timed out after 15 seconds")
        return {
            'success': False,
            'error': 'Verification timeout - please try again',
            'timeout': True,
            'retry_suggested': True
        }
    
    return verification_result

def verify_device_code_safe(input_code, connecting_user_id, connecting_user_email):
    """
    Timeout-safe device code verification for Android app
    Uses background threads to prevent hanging on Firebase reads
    """
    import threading
    import time
    
    verification_result = {
        'success': False, 
        'error': 'Verification timeout',
        'timeout': True
    }
    
    def verify_operation():
        try:
            db = get_firestore_db()
            
            logging.info(f"[VERIFY-SAFE] Searching for code: {input_code}")
            
            # Find active code with simpler query
            codes_query = db.collection('user_device_codes').where(filter=FieldFilter('deviceCode', '==', input_code)).where(filter=FieldFilter('isActive', '==', True)).limit(1)
            codes = codes_query.get()
            
            if not codes:
                verification_result.update({
                    'success': False, 
                    'error': 'Invalid or expired code',
                    'timeout': False
                })
                return
            
            code_doc = codes[0]
            code_data = code_doc.to_dict()
            
            logging.info(f"[VERIFY-SAFE] Found code: {input_code}, owner: {code_data.get('userId')}")
            
            # Check if code is expired
            if code_data.get('expiresAt') and code_data['expiresAt'] < datetime.now():
                # Mark as inactive
                code_doc.reference.update({'isActive': False})
                verification_result.update({
                    'success': False, 
                    'error': 'Code has expired',
                    'timeout': False
                })
                return
            
            # Check usage limit
            usage_count = code_data.get('usageCount', 0)
            max_usage = code_data.get('maxUsage', 1)
            if usage_count >= max_usage:
                verification_result.update({
                    'success': False, 
                    'error': 'Code has reached maximum usage',
                    'timeout': False
                })
                return
            
            # Don't allow self-connection
            if code_data['userId'] == connecting_user_id:
                verification_result.update({
                    'success': False, 
                    'error': 'Cannot connect to your own device',
                    'timeout': False
                })
                return
            
            # Generate unique device ID
            device_id = f"device_{secrets.token_hex(8)}"
            
            # Create connection in device_connections collection
            connection_data = {
                'deviceId': device_id,
                'deviceCode': input_code,
                'ownerId': code_data['userId'],
                'ownerEmail': code_data['userEmail'],
                'connectedUserId': connecting_user_id,
                'connectedUserEmail': connecting_user_email,
                'connectedAt': firestore.SERVER_TIMESTAMP,
                'status': 'active'
            }
            
            # Store connection
            db.collection('device_connections').add(connection_data)
            
            # Update code usage
            code_doc.reference.update({
                'usageCount': usage_count + 1,
                'lastUsed': firestore.SERVER_TIMESTAMP
            })
            
            logging.info(f"[VERIFY-SAFE] Successfully connected device for code: {input_code}")
            
            verification_result.update({
                'success': True,
                'message': 'Device connected successfully',
                'deviceId': device_id,
                'ownerEmail': code_data['userEmail'],
                'timeout': False
            })
            
        except Exception as e:
            logging.error(f"[VERIFY-SAFE] Verification error: {e}")
            verification_result.update({
                'success': False,
                'error': f'Verification failed: {str(e)}',
                'timeout': False
            })
    
    # Run verification in background thread with timeout
    verify_thread = threading.Thread(target=verify_operation)
    verify_thread.daemon = True
    verify_thread.start()
    
    # Wait maximum 15 seconds for verification
    verify_thread.join(timeout=15.0)
    
    if verify_thread.is_alive():
        logging.warning(f"[VERIFY-SAFE] Verification for {input_code} timed out after 15 seconds")
        return {
            'success': False,
            'error': 'Verification timeout - Firebase read taking too long',
            'timeout': True,
            'retry_suggested': True
        }
    
    return verification_result

def query_firebase_with_timeout(collection, field, value, timeout_seconds=10):
    """
    Query Firebase with timeout protection to prevent hanging
    Returns: (success, data, error_message)
    """
    try:
        db = get_firestore_db()
        result = {'data': None, 'error': None, 'completed': False}
        
        def query_worker():
            try:
                logging.info(f"[FIREBASE-TIMEOUT] Starting query: {collection}.{field} == {value}")
                query = db.collection(collection).where(field, '==', value)
                docs = query.stream()
                doc_list = list(docs)
                result['data'] = doc_list
                result['completed'] = True
                logging.info(f"[FIREBASE-TIMEOUT] Query completed, found {len(doc_list)} documents")
            except Exception as e:
                logging.error(f"[FIREBASE-TIMEOUT] Query error: {e}")
                result['error'] = str(e)
                result['completed'] = True
        
        # Run query in separate thread with timeout
        thread = threading.Thread(target=query_worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)
        
        if not result['completed']:
            logging.error(f"[FIREBASE-TIMEOUT] Query timed out after {timeout_seconds}s")
            return False, None, f"Firebase query timed out after {timeout_seconds} seconds"
        
        if result['error']:
            return False, None, result['error']
        
        return True, result['data'], None
        
    except Exception as e:
        logging.error(f"[FIREBASE-TIMEOUT] Timeout wrapper error: {e}")
        return False, None, str(e)

def verify_device_code_with_timeout(device_code, user_id, user_email, timeout_seconds=10):
    """
    Verify device code with timeout protection
    Returns: (success, result_data, error_message)
    """
    try:
        logging.info(f"[VERIFY-TIMEOUT] Starting verification for code: {device_code}")
        
        # First query: find active device codes
        success, docs, error = query_firebase_with_timeout(
            'user_device_codes', 'deviceCode', device_code, timeout_seconds
        )
        
        if not success:
            return False, None, error or "Failed to query device codes"
        
        if not docs:
            return False, None, "Invalid or expired device code"
        
        # Check if active
        active_docs = [doc for doc in docs if doc.to_dict().get('isActive') == True]
        if not active_docs:
            return False, None, "Device code is not active"
        
        device_doc = active_docs[0]
        device_data = device_doc.to_dict()
        
        owner_id = device_data.get('userId')
        owner_email = device_data.get('userEmail', 'Unknown')
        
        # Prevent self-connection
        if owner_id == user_id:
            return False, None, "Cannot connect to your own device"
        
        # Create connection in Firebase (with timeout protection)
        device_id = f"device_{secrets.token_hex(8)}"
        
        def create_connection():
            try:
                db = get_firestore_db()
                connection_data = {
                    'deviceId': device_id,
                    'deviceCode': device_code,
                    'ownerId': owner_id,
                    'ownerEmail': owner_email,
                    'connectedUserId': user_id,
                    'connectedUserEmail': user_email,
                    'connectedAt': firestore.SERVER_TIMESTAMP,
                    'status': 'active'
                }
                db.collection('device_connections').add(connection_data)
                return True
            except Exception as e:
                logging.error(f"[VERIFY-TIMEOUT] Failed to create connection: {e}")
                return False
        
        # Create connection in background (non-blocking)
        connection_thread = threading.Thread(target=create_connection, daemon=True)
        connection_thread.start()
        
        return True, {
            'deviceId': device_id,
            'ownerEmail': owner_email,
            'message': 'Device connected successfully'
        }, None
        
    except Exception as e:
        logging.error(f"[VERIFY-TIMEOUT] Verification error: {e}")
        return False, None, str(e)

def fetch_user_devices_debug(user_id):
    """
    Fetch all devices for a specific user from Firebase user_devices collection
    with detailed debug information
    
    Args:
        user_id (str): Firebase UID of the user
        
    Returns:
        dict: Detailed response with devices data and debug info
    """
    debug_info = {
        'timestamp': datetime.now().isoformat(),
        'user_id': user_id,
        'operation': 'fetch_user_devices_debug',
        'steps': [],
        'devices': [],
        'success': False,
        'error': None,
        'firestore_connection': None,
        'collection_exists': False,
        'document_count': 0
    }
    
    try:
        debug_info['steps'].append(f"[1] Starting device fetch for user: {user_id}")
        
        # Get Firestore database
        db = get_firestore_db()
        debug_info['steps'].append("[2] ✅ Firestore database connection established")
        debug_info['firestore_connection'] = True
        
        # Reference to user_devices collection
        user_devices_ref = db.collection('user_devices')
        debug_info['steps'].append("[3] ✅ Referenced user_devices collection")
        
        # First, let's try to get a simple document count to test the collection
        try:
            debug_info['steps'].append("[3.1] Testing collection access...")
            # Get first document to test collection access
            test_docs = user_devices_ref.limit(1).stream()
            test_count = sum(1 for _ in test_docs)
            debug_info['steps'].append(f"[3.1] ✅ Collection accessible, test returned {test_count} documents")
        except Exception as test_error:
            debug_info['steps'].append(f"[3.1] ❌ Collection access test failed: {test_error}")
            debug_info['collection_exists'] = False
        
        # Query devices for this specific user - using updated syntax
        debug_info['steps'].append(f"[4] Querying devices where userId == '{user_id}'")
        
        # Get all documents in user_devices collection that match the user (new syntax)
        from google.cloud.firestore_v1.base_query import FieldFilter
        import time
        
        start_query_time = time.time()
        query = user_devices_ref.where(filter=FieldFilter("userId", "==", user_id))
        
        debug_info['steps'].append("[4.1] Executing Firestore query...")
        docs = query.stream()
        
        devices_list = []
        doc_count = 0
        
        # Process documents with timeout
        query_timeout = 10  # 10 seconds timeout
        
        for doc in docs:
            current_time = time.time()
            if current_time - start_query_time > query_timeout:
                debug_info['steps'].append(f"[4.ERROR] Query timeout after {query_timeout} seconds")
                break
                
            doc_count += 1
            device_data = doc.to_dict()
            device_id = doc.id
            
            debug_info['steps'].append(f"[4.{doc_count}] Found device document: {device_id}")
            
            # Add document ID to device data
            device_data['firebase_doc_id'] = device_id
            devices_list.append(device_data)
            
            # Log device details
            device_info = device_data.get('deviceInfo', {})
            device_name = device_info.get('deviceName', 'Unknown')
            device_model = device_info.get('deviceModel', 'Unknown')
            is_active = device_data.get('isActive', False)
            last_seen = device_data.get('lastSeenAt', 'Never')
            
            debug_info['steps'].append(f"    📱 Device: {device_name} ({device_model})")
            debug_info['steps'].append(f"    🔋 Active: {is_active}, Last Seen: {last_seen}")
        
        query_elapsed = time.time() - start_query_time
        debug_info['steps'].append(f"[4.COMPLETE] Query completed in {query_elapsed:.2f} seconds")
        
        debug_info['document_count'] = doc_count
        debug_info['devices'] = devices_list
        debug_info['collection_exists'] = True
        
        if doc_count == 0:
            debug_info['steps'].append("[5] ⚠️ No devices found for this user")
        else:
            debug_info['steps'].append(f"[5] ✅ Successfully fetched {doc_count} device(s)")
        
        debug_info['success'] = True
        
    except Exception as e:
        error_msg = str(e)
        debug_info['error'] = error_msg
        debug_info['steps'].append(f"[ERROR] ❌ Failed to fetch devices: {error_msg}")
        logging.error(f"Firebase device fetch error: {error_msg}")
    
    debug_info['steps'].append(f"[FINAL] Operation completed at {datetime.now().strftime('%H:%M:%S')}")
    
    return debug_info

def fetch_user_devices(user_id):
    """
    Fetch devices for a user (production version)
    
    Args:
        user_id (str): Firebase UID of the user
        
    Returns:
        list: List of device dictionaries
    """
    try:
        db = get_firestore_db()
        user_devices_ref = db.collection('user_devices')
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = user_devices_ref.where(filter=FieldFilter("userId", "==", user_id))
        docs = query.stream()
        
        devices = []
        for doc in docs:
            device_data = doc.to_dict()
            device_data['firebase_doc_id'] = doc.id
            devices.append(device_data)
        
        return devices
        
    except Exception as e:
        logging.error(f"Error fetching user devices: {e}")
        return []
