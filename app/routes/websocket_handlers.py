from flask import request, session
from flask_socketio import emit, join_room, leave_room, disconnect
from app import socketio
import logging

logger = logging.getLogger(__name__)

# Store connected users and their rooms
connected_users = {}

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f'Client connected: {request.sid}')
    user_id = session.get('user_id')
    
    if user_id:
        # Join user-specific room for targeted messages
        join_room(f'user_{user_id}')
        connected_users[request.sid] = user_id
        logger.info(f'User {user_id} joined room: user_{user_id}')
        
        emit('server_status', {
            'status': 'connected',
            'message': 'Successfully connected to UniLocator server',
            'timestamp': datetime.now().isoformat(),
            'user_id': user_id
        })
    else:
        logger.warning(f'Client {request.sid} connected without authentication')
        emit('server_status', {
            'status': 'connected',
            'message': 'Connected to UniLocator server (not authenticated)',
            'timestamp': datetime.now().isoformat()
        })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f'Client disconnected: {request.sid}')
    user_id = connected_users.pop(request.sid, None)
    
    if user_id:
        leave_room(f'user_{user_id}')
        logger.info(f'User {user_id} left room: user_{user_id}')

@socketio.on('ping')
def handle_ping():
    """Handle ping for latency testing"""
    emit('pong', {'timestamp': datetime.now().isoformat()})

@socketio.on('echo')
def handle_echo(data):
    """Echo test for debugging"""
    logger.info(f'Echo request from {request.sid}: {data}')
    emit('echo', data)

@socketio.on('location_update')
def handle_location_update(data):
    """Handle real-time location updates from devices"""
    try:
        logger.info(f'Location update from {request.sid}: {data}')
        
        device_id = data.get('device_id')
        lat = data.get('lat')
        lng = data.get('lng')
        
        if not device_id or lat is None or lng is None:
            emit('error', {'message': 'Invalid location data'})
            return
        
        # Broadcast to all clients (or specific user room)
        user_id = session.get('user_id')
        if user_id:
            # Emit to user's room
            socketio.emit('location_update', {
                'device_id': device_id,
                'lat': lat,
                'lng': lng,
                'timestamp': data.get('timestamp', datetime.now().isoformat())
            }, room=f'user_{user_id}')
        else:
            # Broadcast to sender only
            emit('location_update', {
                'device_id': device_id,
                'lat': lat,
                'lng': lng,
                'timestamp': data.get('timestamp', datetime.now().isoformat())
            })
        
        logger.info(f'Location update broadcasted for device {device_id}')
        
    except Exception as e:
        logger.error(f'Error handling location update: {e}')
        emit('error', {'message': f'Failed to process location update: {str(e)}'})

@socketio.on('device_status')
def handle_device_status(data):
    """Handle device status updates"""
    try:
        logger.info(f'Device status update from {request.sid}: {data}')
        
        device_id = data.get('device_id')
        status = data.get('status')
        
        if not device_id or not status:
            emit('error', {'message': 'Invalid device status data'})
            return
        
        user_id = session.get('user_id')
        if user_id:
            socketio.emit('device_status_update', {
                'device_id': device_id,
                'status': status,
                'timestamp': datetime.now().isoformat()
            }, room=f'user_{user_id}')
        
        emit('status_update_received', {'success': True})
        
    except Exception as e:
        logger.error(f'Error handling device status: {e}')
        emit('error', {'message': f'Failed to process device status: {str(e)}'})

@socketio.on('subscribe_device')
def handle_subscribe_device(data):
    """Subscribe to updates for a specific device"""
    try:
        device_id = data.get('device_id')
        if not device_id:
            emit('error', {'message': 'Device ID required'})
            return
        
        room_name = f'device_{device_id}'
        join_room(room_name)
        
        logger.info(f'Client {request.sid} subscribed to device {device_id}')
        emit('subscription_confirmed', {
            'device_id': device_id,
            'message': f'Subscribed to updates for device {device_id}'
        })
        
    except Exception as e:
        logger.error(f'Error subscribing to device: {e}')
        emit('error', {'message': f'Failed to subscribe to device: {str(e)}'})

@socketio.on('unsubscribe_device')
def handle_unsubscribe_device(data):
    """Unsubscribe from device updates"""
    try:
        device_id = data.get('device_id')
        if not device_id:
            emit('error', {'message': 'Device ID required'})
            return
        
        room_name = f'device_{device_id}'
        leave_room(room_name)
        
        logger.info(f'Client {request.sid} unsubscribed from device {device_id}')
        emit('unsubscription_confirmed', {
            'device_id': device_id,
            'message': f'Unsubscribed from updates for device {device_id}'
        })
        
    except Exception as e:
        logger.error(f'Error unsubscribing from device: {e}')
        emit('error', {'message': f'Failed to unsubscribe from device: {str(e)}'})

@socketio.on_error_default
def default_error_handler(e):
    """Handle all WebSocket errors"""
    logger.error(f'WebSocket error from {request.sid}: {e}')
    emit('error', {
        'message': 'An error occurred',
        'details': str(e)
    })

from datetime import datetime

def notify_device_connected(user_id, device_data):
    """Notify user when a device connects"""
    try:
        socketio.emit('device_connected', device_data, room=f'user_{user_id}')
        logger.info(f'Device connection notification sent to user {user_id}')
    except Exception as e:
        logger.error(f'Error notifying device connection: {e}')

def notify_device_disconnected(user_id, device_id):
    """Notify user when a device disconnects"""
    try:
        socketio.emit('device_disconnected', {
            'device_id': device_id,
            'timestamp': datetime.now().isoformat()
        }, room=f'user_{user_id}')
        logger.info(f'Device disconnection notification sent to user {user_id}')
    except Exception as e:
        logger.error(f'Error notifying device disconnection: {e}')

def broadcast_location_update(device_id, location_data):
    """Broadcast location update to all subscribed clients"""
    try:
        socketio.emit('location_update', {
            'device_id': device_id,
            **location_data,
            'timestamp': datetime.now().isoformat()
        }, room=f'device_{device_id}')
        logger.info(f'Location update broadcasted for device {device_id}')
    except Exception as e:
        logger.error(f'Error broadcasting location update: {e}')
