from ..utils.firebase_utils import get_firestore_db
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from google.cloud.firestore_v1.base_query import FieldFilter

class User:
    def __init__(self, firebase_uid, username=None, email=None, password_hash=None, created_at=None):
        self.firebase_uid = firebase_uid
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.created_at = created_at

    @staticmethod
    def get_by_firebase_uid(firebase_uid):
        """Get user by Firebase UID"""
        try:
            db = get_firestore_db()
            user_doc = db.collection('users').document(firebase_uid).get()
            if user_doc.exists:
                data = user_doc.to_dict()
                return User(
                    firebase_uid=firebase_uid,
                    username=data.get('username'),
                    email=data.get('email'),
                    password_hash=data.get('password_hash'),
                    created_at=data.get('created_at')
                )
            return None
        except Exception as e:
            print(f"Error getting user by Firebase UID: {e}")
            return None

    @staticmethod
    def get_by_username(username):
        """Get user by username"""
        try:
            db = get_firestore_db()
            users_ref = db.collection('users').where(filter=FieldFilter('username', '==', username))
            users_docs = users_ref.get()
            
            if users_docs:
                doc = users_docs[0]
                data = doc.to_dict()
                return User(
                    firebase_uid=doc.id,
                    username=data.get('username'),
                    email=data.get('email'),
                    password_hash=data.get('password_hash'),
                    created_at=data.get('created_at')
                )
            return None
        except Exception as e:
            print(f"Error getting user by username: {e}")
            return None

    @staticmethod
    def get_by_email(email):
        """Get user by email"""
        try:
            db = get_firestore_db()
            users_ref = db.collection('users').where(filter=FieldFilter('email', '==', email))
            users_docs = users_ref.get()
            
            if users_docs:
                doc = users_docs[0]
                data = doc.to_dict()
                return User(
                    firebase_uid=doc.id,
                    username=data.get('username'),
                    email=data.get('email'),
                    password_hash=data.get('password_hash'),
                    created_at=data.get('created_at')
                )
            return None
        except Exception as e:
            print(f"Error getting user by email: {e}")
            return None

    @staticmethod
    def create_or_update(firebase_uid, username=None, email=None, password=None):
        """Create or update user in Firebase"""
        try:
            db = get_firestore_db()
            user_data = {
                'firebase_uid': firebase_uid,
                'email': email,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            
            if username:
                user_data['username'] = username
            
            if password:
                user_data['password_hash'] = generate_password_hash(password)
            
            # Use Firebase UID as document ID
            db.collection('users').document(firebase_uid).set(user_data, merge=True)
            
            return User(
                firebase_uid=firebase_uid,
                username=username,
                email=email,
                password_hash=user_data.get('password_hash'),
                created_at=user_data['created_at']
            )
        except Exception as e:
            print(f"Error creating/updating user: {e}")
            return None

    @staticmethod
    def username_exists(username, exclude_firebase_uid=None):
        """Check if username already exists"""
        try:
            db = get_firestore_db()
            users_ref = db.collection('users').where(filter=FieldFilter('username', '==', username))
            users_docs = users_ref.get()
            
            for doc in users_docs:
                if exclude_firebase_uid and doc.id == exclude_firebase_uid:
                    continue
                return True
            return False
        except Exception as e:
            print(f"Error checking username existence: {e}")
            return False

    def verify_password(self, password):
        """Verify password (if using local password authentication)"""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def get_devices(self):
        """Get all devices connected to this user"""
        try:
            db = get_firestore_db()
            devices_ref = db.collection('connected_devices').where(filter=FieldFilter('user_id', '==', self.firebase_uid))
            devices_docs = devices_ref.get()
            
            devices = []
            for doc in devices_docs:
                devices.append(doc.to_dict())
            return devices
        except Exception as e:
            print(f"Error getting user devices: {e}")
            return []

    def update_profile(self, **kwargs):
        """Update user profile"""
        try:
            db = get_firestore_db()
            update_data = {
                'updated_at': datetime.now()
            }
            
            if 'username' in kwargs:
                update_data['username'] = kwargs['username']
                self.username = kwargs['username']
            
            if 'email' in kwargs:
                update_data['email'] = kwargs['email']
                self.email = kwargs['email']
            
            db.collection('users').document(self.firebase_uid).update(update_data)
            return True
        except Exception as e:
            print(f"Error updating user profile: {e}")
            return False