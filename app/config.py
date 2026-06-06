import os
import secrets

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    
    # Firebase configuration
    FIREBASE_PROJECT_ID = os.environ.get('FIREBASE_PROJECT_ID') or 'unilocator-368db'
    FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
    FIREBASE_SERVICE_ACCOUNT_PATH = os.environ.get(
        'FIREBASE_SERVICE_ACCOUNT_PATH',
        os.path.join(BASE_DIR, 'service-account-key.json')
    )