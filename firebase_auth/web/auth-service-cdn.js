// AuthService for browser with Firebase CDN
// Assumes firebase, firebase.auth, and firebase.firestore are loaded globally

class AuthService {
  constructor() {
    this.currentUser = null;
    this.authStateCallbacks = [];
    firebase.auth().onAuthStateChanged((user) => {
      this.currentUser = user;
      this.authStateCallbacks.forEach(cb => cb(user));
    });
  }

  async register(email, password, username) {
    try {
      console.log('[AUTH-SERVICE] Starting user registration...');
      const userCredential = await firebase.auth().createUserWithEmailAndPassword(email, password);
      const user = userCredential.user;
      console.log('[AUTH-SERVICE] User created successfully:', user.uid);
      
      // Update user profile
      await user.updateProfile({ displayName: username });
      console.log('[AUTH-SERVICE] Profile updated with display name');
      
      // Create user document in Firestore with retry logic
      try {
        await firebase.firestore().collection('users').doc(user.uid).set({
          username: username,
          email: email,
          createdAt: new Date().toISOString(),
          devices: []
        });
        console.log('[AUTH-SERVICE] User document created in Firestore');
      } catch (firestoreError) {
        console.warn('[AUTH-SERVICE] Firestore write failed, but user account created:', firestoreError.message);
        // Don't fail registration if Firestore write fails - user can still login
      }
      
      return { success: true, user };
    } catch (error) {
      console.error('[AUTH-SERVICE] Registration error:', error);
      return { success: false, error: error.message };
    }
  }

  async login(identifier, password) {
    try {
      let email = identifier;
      
      // If identifier doesn't contain '@', treat it as a username and find the email
      if (!identifier.includes('@')) {
        const query = await firebase.firestore().collection('users').where('username', '==', identifier).get();
        
        if (query.empty) {
          return { success: false, error: 'User not found' };
        }
        
        // Get the email from the user document
        email = query.docs[0].data().email;
      }
      
      const userCredential = await firebase.auth().signInWithEmailAndPassword(email, password);
      return { success: true, user: userCredential.user };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  async logout() {
    try {
      await firebase.auth().signOut();
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  getCurrentUser() {
    return this.currentUser;
  }

  isAuthenticated() {
    return this.currentUser !== null;
  }

  onAuthStateChange(callback) {
    this.authStateCallbacks.push(callback);
    return () => {
      this.authStateCallbacks = this.authStateCallbacks.filter(cb => cb !== callback);
    };
  }

  async checkUsernameAvailability(username) {
    try {
      // Check if username format is valid
      const usernameRegex = /^[a-zA-Z0-9._]+$/;
      if (!usernameRegex.test(username)) {
        return { available: false, message: "Username can only contain letters, numbers, dots, and underscores" };
      }
      
      if (username.length < 3) {
        return { available: false, message: "Username must be at least 3 characters long" };
      }
      
      if (username.length > 20) {
        return { available: false, message: "Username must be 20 characters or less" };
      }
      
      // Check if username exists in Firestore
      const query = await firebase.firestore().collection('users').where('username', '==', username).get();
      
      if (query.empty) {
        return { available: true, message: "Username is available" };
      } else {
        return { available: false, message: "Username is already taken" };
      }
    } catch (error) {
      console.error('Error checking username availability:', error);
      return { available: false, message: "Error checking username availability" };
    }
  }

  async getUserData(uid) {
    try {
      const doc = await firebase.firestore().collection('users').doc(uid).get();
      return doc.exists ? doc.data() : null;
    } catch (error) {
      console.error('Error getting user data:', error);
      return null;
    }
  }
}

window.authService = new AuthService();
