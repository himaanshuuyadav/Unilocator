import logging
import os
import socket
from app import create_app, socketio

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # or DEBUG for more verbosity
    format='%(asctime)s %(levelname)s %(message)s'
)

def get_local_ip():
    """Get the local IP address of the machine"""
    try:
        # Create a socket connection to determine the local IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Connect to a remote address (doesn't actually send data)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        return local_ip
    except Exception:
        # Fallback to localhost if unable to determine IP
        return "127.0.0.1"

app = create_app()

if __name__ == '__main__':
    local_ip = get_local_ip()
    port = int(os.environ.get('PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    print("Starting UniLocator server...")
    print(f"Local IP detected: {local_ip}")
    print(f"Open http://{local_ip}:{port} in your browser.")
    print("Or use http://localhost:5000 for local access only.")
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)