from flask import Blueprint, render_template, redirect, url_for, request, jsonify, session
from flask_socketio import emit
from app import socketio
from functools import wraps
from ..utils.firebase_utils import get_firestore_db, generate_device_code
import logging
import secrets
import string
import qrcode
import io
import base64
import json
import os
from datetime import datetime, timedelta
from flask_jwt_extended import jwt_required, get_jwt_identity
from google.cloud.firestore_v1.base_query import FieldFilter

bp = Blueprint('devices', __name__, url_prefix='/devices')

@bp.route('/verify-device', methods=['POST'])
def verify_device():
    data = request.get_json()
    device_code = data.get('device_code')
    logging.info(f"[DEBUG] Received device_code from Android app: {device_code}")
    
    try:
        db = get_firestore_db()
        # Check if code exists in device_codes collection
        codes_ref = db.collection('device_codes').where(filter=FieldFilter('code', '==', device_code))
        codes_docs = codes_ref.get()
        exists = len(codes_docs) > 0
        
        logging.info(f"[DEBUG] Exists in device_codes: {exists}")
        return jsonify({
            'received': True,
            'device_code': device_code,
            'exists_in_pending': exists
        })
    except Exception as e:
        logging.error(f"[DEBUG] Error verifying device: {e}")
        return jsonify({
            'received': True,
            'device_code': device_code,
            'exists_in_pending': False
        })

@bp.route('/connect-device', methods=['POST'])
def connect_device():
    data = request.get_json()
    device_code = data.get('device_code')
    logging.info(f"[CONNECT] Attempting to connect device: {device_code}")
    
    try:
        db = get_firestore_db()
        
        # Check if device code exists and is active
        codes_ref = db.collection('device_codes').where(filter=FieldFilter('code', '==', device_code)).where(filter=FieldFilter('active', '==', True))
        codes_docs = codes_ref.get()
        
        if not codes_docs:
            logging.info(f"[CONNECT] No active device code found: {device_code}")
            return jsonify({
                "success": False,
                "message": "Invalid or expired code"
            }), 200
        
        code_doc = codes_docs[0]
        code_data = code_doc.to_dict()
        user_id = code_data.get('userId')
        device_name = data.get('device_name') or f"Device_{device_code[:6]}"
        
        # Add to connected_devices collection
        device_data = {
            'user_id': user_id,
            'device_code': device_code,
            'device_name': device_name,
            'connected_at': datetime.now(),
            'last_seen': datetime.now()
        }
        db.collection('connected_devices').add(device_data)
        
        # Deactivate the device code
        code_doc.reference.update({'active': False, 'used_at': datetime.now()})
        
        logging.info(f"[CONNECT] Device {device_code} connected successfully for user {user_id}")
        
        # Emit socket event for real-time update
        socketio.emit('device_connected', {
            'device_code': device_code,
            'device_name': device_name,
            'user_id': user_id
        })
        
        return jsonify({
            "success": True,
            "message": "Device connected successfully",
            "device_name": device_name
        })
        
    except Exception as e:
        logging.error(f"[CONNECT] Error connecting device: {e}")
        return jsonify({
            "success": False,
            "message": "Connection failed"
        }), 500

@bp.route('/remove-device', methods=['POST'])
def remove_device():
    data = request.get_json()
    device_code = data.get('device_code')
    
    # Use session authentication
    firebase_uid = session.get('user_id')
    if not firebase_uid:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        db = get_firestore_db()
        
        # Find and remove the device
        devices_ref = db.collection('connected_devices').where(filter=FieldFilter('device_code', '==', device_code)).where(filter=FieldFilter('user_id', '==', firebase_uid))
        devices_docs = devices_ref.get()
        
        if not devices_docs:
            return jsonify({
                'success': False,
                'message': 'Device not found or not authorized.'
            }), 200
        
        # Delete the device
        for doc in devices_docs:
            doc.reference.delete()
        
        logging.info(f"[REMOVE] Device {device_code} removed for user {firebase_uid}")
        
        return jsonify({
            'success': True,
            'message': 'Device removed successfully',
            'user_id': firebase_uid
        })
        
    except Exception as e:
        logging.error(f"[REMOVE] Error removing device: {e}")
        return jsonify({'success': False, 'error': 'Failed to remove device'}), 500

@bp.route('/update-location', methods=['POST'])
def update_location():
    data = request.get_json()
    device_code = data.get('device_code')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    try:
        db = get_firestore_db()
        
        # Find the connected device and update its location
        devices_ref = db.collection('connected_devices').where(filter=FieldFilter('device_code', '==', device_code))
        devices_docs = devices_ref.get()
        
        if not devices_docs:
            return jsonify({'success': False, 'message': 'Device not found'}), 404
        
        # Update location for all matching devices (should be just one)
        for doc in devices_docs:
            doc.reference.update({
                'latitude': latitude,
                'longitude': longitude,
                'last_seen': datetime.now()
            })
        
        return jsonify({'success': True, 'message': 'Location updated'})
        
    except Exception as e:
        logging.error(f"[UPDATE-LOCATION] Error: {e}")
        return jsonify({'success': False, 'error': 'Failed to update location'}), 500

@bp.route('/get-location', methods=['POST'])
def get_location():
    data = request.get_json()
    device_code = data.get('device_code')
    
    try:
        db = get_firestore_db()
        
        # Find the device and get its location
        devices_ref = db.collection('connected_devices').where(filter=FieldFilter('device_code', '==', device_code))
        devices_docs = devices_ref.get()
        
        if not devices_docs:
            return jsonify({'success': False, 'message': 'Device not found'}), 404
        
        device_data = devices_docs[0].to_dict()
        
        return jsonify({
            'success': True,
            'latitude': device_data.get('latitude'),
            'longitude': device_data.get('longitude'),
            'last_seen': device_data.get('last_seen').isoformat() if device_data.get('last_seen') else None
        })
        
    except Exception as e:
        logging.error(f"[GET-LOCATION] Error: {e}")
        return jsonify({'success': False, 'error': 'Failed to get location'}), 500

@bp.route('/send-notification', methods=['POST'])
def send_notification():
    data = request.get_json()
    device_code = data.get('device_code')
    
    try:
        db = get_firestore_db()
        
        # Find the device and update notification flag
        devices_ref = db.collection('connected_devices').where(filter=FieldFilter('device_code', '==', device_code))
        devices_docs = devices_ref.get()
        
        if not devices_docs:
            return jsonify({'success': False, 'message': 'Device not found'}), 404
        
        # Update notification status
        for doc in devices_docs:
            doc.reference.update({
                'notification_sent': True,
                'notification_time': datetime.now(),
                'last_seen': datetime.now()
            })
        
        return jsonify({'success': True, 'message': 'Notification sent'})
        
    except Exception as e:
        logging.error(f"[SEND-NOTIFICATION] Error: {e}")
        return jsonify({'success': False, 'error': 'Failed to send notification'}), 500

@bp.route('/list-devices', methods=['GET'])
def list_devices():
    firebase_uid = session.get('user_id')
    if not firebase_uid:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        db = get_firestore_db()
        
        # Get all devices for the user
        devices_ref = db.collection('connected_devices').where(filter=FieldFilter('user_id', '==', firebase_uid))
        devices_docs = devices_ref.get()
        
        result = []
        for doc in devices_docs:
            device_data = doc.to_dict()
            result.append({
                "device_name": device_data.get("device_name"),
                "device_code": device_data.get("device_code"),
                "last_seen": device_data.get("last_seen").isoformat() if device_data.get("last_seen") else None,
                "latitude": device_data.get("latitude"),
                "longitude": device_data.get("longitude")
            })
        
        return jsonify(result)
        
    except Exception as e:
        logging.error(f"[LIST-DEVICES] Error: {e}")
        return jsonify([])

@bp.route('/disconnect-all', methods=['POST'])
def disconnect_all_devices():
    firebase_uid = session.get('user_id')
    if not firebase_uid:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        db = get_firestore_db()
        
        # Delete all user's devices
        devices_ref = db.collection('connected_devices').where(filter=FieldFilter('user_id', '==', firebase_uid))
        devices_docs = devices_ref.get()
        
        deleted_count = 0
        for doc in devices_docs:
            doc.reference.delete()
            deleted_count += 1
        
        # Also delete any active device codes for the user
        codes_ref = db.collection('device_codes').where(filter=FieldFilter('userId', '==', firebase_uid)).where(filter=FieldFilter('active', '==', True))
        codes_docs = codes_ref.get()
        
        for doc in codes_docs:
            doc.reference.update({'active': False, 'deactivated_at': datetime.now()})
        
        return jsonify({'success': True, 'message': f'Disconnected {deleted_count} devices'})
        
    except Exception as e:
        logging.error(f"[DISCONNECT-ALL] Error: {e}")
        return jsonify({'success': False, 'error': 'Failed to disconnect devices'}), 500

@bp.route('/generate-qr', methods=['POST'])
def generate_qr():
    firebase_uid = session.get('user_id')
    user_email = session.get('user_email', '')
    
    if not firebase_uid:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        logging.info(f"[GENERATE-CODE] Starting code generation for user: {firebase_uid}, email: {user_email}")
        
        # Generate device code using Firebase utils
        code = generate_device_code(firebase_uid, user_email)
        
        if not code:
            return jsonify({'success': False, 'error': 'Failed to generate code'}), 500
        
        # Create connection data
        connection_data = f"unilocator://connect?code={code}&user={firebase_uid}&email={user_email}"
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(connection_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        logging.info(f"[GENERATE-CODE] QR code generated successfully for code: {code}")
        
        return jsonify({
            'success': True,
            'qr_code': f"data:image/png;base64,{img_base64}",
            'device_code': code,
            'connection_data': connection_data
        })
        
    except Exception as e:
        logging.error(f"[GENERATE-CODE] Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
