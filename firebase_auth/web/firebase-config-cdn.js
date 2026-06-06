// Firebase v9+ CDN config for browser
// Add this script after loading Firebase libraries from CDN in your HTML

const firebaseConfig = {
  apiKey: "AIzaSyAMZsPPkGMVZnYBRPBdbJ3h2xLCd68CRg8",
  authDomain: "unilocator-368db.firebaseapp.com",
  projectId: "unilocator-368db",
  storageBucket: "unilocator-368db.firebasestorage.app",
  messagingSenderId: "351670538754",
  appId: "1:351670538754:web:44b371eb90bcf23df00d1b",
  measurementId: "G-PYTNC78FVJ"
};

// Initialize Firebase
const app = firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();
const db = firebase.firestore();
