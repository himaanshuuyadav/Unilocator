document.addEventListener('DOMContentLoaded', function() {
    // Initialize navigation slider
    const slider = document.createElement('div');
    slider.className = 'nav-slider';
    document.querySelector('.nav-links')?.appendChild(slider);

    function updateSlider(target) {
        const navItem = target.closest('.nav-item');
        if (!navItem) return;

        const navRect = navItem.getBoundingClientRect();
        const navLinksRect = document.querySelector('.nav-links').getBoundingClientRect();

        slider.style.width = `${navRect.width}px`;
        slider.style.left = `${navRect.left - navLinksRect.left}px`;
        slider.style.opacity = '1';
    }

    // Function to switch active page
    function switchPage(pageId) {
        // Hide all pages
        document.querySelectorAll('.page-content').forEach(page => {
            page.classList.remove('active');
            page.style.display = 'none';
        });

        // Show selected page
        const selectedPage = document.getElementById(`${pageId}-page`);
        if (selectedPage) {
            selectedPage.classList.add('active');
            selectedPage.style.display = 'flex';
        }
    }

    // Handle navigation link clicks
    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Remove active class from all links
            navLinks.forEach(l => l.parentElement.classList.remove('active'));
            
            // Add active class to clicked link
            link.parentElement.classList.add('active');
            
            // Update slider position
            updateSlider(link);
            
            // Switch to the corresponding page
            const page = link.getAttribute('data-page');
            switchPage(page);
        });
    });

    // Set initial slider position for active tab
    const activeTab = document.querySelector('.nav-item.active .nav-link');
    if (activeTab) {
        updateSlider(activeTab);
        // Set initial page
        const initialPage = activeTab.getAttribute('data-page');
        switchPage(initialPage);
    }

    // Display Firebase username in navbar
    function updateNavbarUsername(user) {
        var name = '';
        if (user) {
            name = user.displayName || user.email || 'User';
        }
        var nameSpan = document.getElementById('navbar-username');
        if (nameSpan) nameSpan.textContent = name;
    }
    
    // Initialize Firebase auth listener when available
    function initializeAuth() {
        if (window.firebase && window.firebase.auth) {
            window.firebase.auth().onAuthStateChanged(updateNavbarUsername);
        } else if (window.authService && window.authService.onAuthStateChanged) {
            window.authService.onAuthStateChanged(updateNavbarUsername);
        } else {
            // Retry in 100ms if Firebase is not ready yet
            setTimeout(initializeAuth, 100);
        }
    }
    
    initializeAuth();

    console.log('Main script loading...');

    // Initialize Socket.IO with proper configuration
    const socket = io({
        transports: ['polling', 'websocket'],
        reconnectionAttempts: 5,
        reconnectionDelay: 1000
    });

    // Connection event handlers
    socket.on('connect', () => {
        console.log('Successfully connected to server');
        document.dispatchEvent(new CustomEvent('socketConnected'));
    });

    socket.on('server_status', (data) => {
        console.log('Server status:', data);
    });

    socket.on('device_connected', (data) => {
        console.log('New device connected:', data);
        addDeviceToUI(data);
    });

    socket.on('connect_error', (error) => {
        console.error('Connection error:', error);
    });

    function addDeviceToUI(device) {
        const devicesGrid = document.querySelector('.devices-grid');
        if (!devicesGrid) return;

        const deviceCard = document.createElement('div');
        deviceCard.className = 'device-card';
        deviceCard.dataset.deviceId = device.id;
        deviceCard.innerHTML = `
            <div class="device-header">
                <h3>${device.device_name}</h3>
                <span class="device-status">Connected</span>
            </div>
            <div class="device-info">
                <p><i class="fas fa-qrcode"></i> ID: ${device.device_code}</p>
                <p><i class="fas fa-clock"></i> Added: Just now</p>
            </div>
            <div class="device-actions">
                <button class="device-menu-btn"><i class="fas fa-ellipsis-v"></i></button>
                <div class="device-menu-dropdown">
                    <button class="remove-device-btn" data-device-code="${device.device_code}">Remove Device</button>
                </div>
            </div>
        `;
        devicesGrid.appendChild(deviceCard);
    }

    // Listen for new devices
    socket.on('device_added', function(device) {
        console.log('New device added:', device);
        addDeviceToUI(device);
    });

    // Device menu functionality
    function initializeDeviceMenus() {
        const deviceMenuBtns = document.querySelectorAll('.device-menu-btn');
        
        deviceMenuBtns.forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                
                // Close all other dropdowns
                document.querySelectorAll('.device-menu-dropdown').forEach(dropdown => {
                    if (dropdown !== this.nextElementSibling) {
                        dropdown.classList.remove('show');
                        dropdown.classList.add('hidden');
                    }
                });
                
                // Toggle current dropdown
                const dropdown = this.nextElementSibling;
                if (dropdown && dropdown.classList.contains('device-menu-dropdown')) {
                    dropdown.classList.toggle('show');
                    dropdown.classList.toggle('hidden');
                }
            });
        });

        // Close dropdowns when clicking outside
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.device-actions')) {
                document.querySelectorAll('.device-menu-dropdown').forEach(dropdown => {
                    dropdown.classList.remove('show');
                    dropdown.classList.add('hidden');
                });
            }
        });

        // Handle remove device buttons
        const removeDeviceBtns = document.querySelectorAll('.remove-device-btn');
        removeDeviceBtns.forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const deviceCode = this.getAttribute('data-device-code');
                if (deviceCode && confirm('Are you sure you want to remove this device?')) {
                    removeDevice(deviceCode);
                }
            });
        });
    }

    // Remove device function
    function removeDevice(deviceCode) {
        fetch('/devices/remove-device', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify({ device_code: deviceCode })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Reload the page to refresh the device list
                window.location.reload();
            } else {
                alert('Failed to remove device: ' + (data.message || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error removing device:', error);
            alert('Failed to remove device. Please try again.');
        });
    }

    // Initialize device menus
    initializeDeviceMenus();

    console.log('Main script initialized');
    
    // Load battery status for all devices
    loadDeviceBatteryStatus();
});

// Load battery status for all devices
function loadDeviceBatteryStatus() {
    const batteryElements = document.querySelectorAll('.device-battery');
    
    batteryElements.forEach(element => {
        const deviceId = element.dataset.deviceId;
        if (deviceId) {
            fetch(`/api/device/${deviceId}/battery`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        updateBatteryDisplay(element, data.battery_level, data.is_charging);
                    } else {
                        element.querySelector('.battery-level').textContent = '--';
                    }
                })
                .catch(error => {
                    console.error('Error loading battery status:', error);
                    element.querySelector('.battery-level').textContent = '--';
                });
        }
    });
}

// Update battery display with icon and level
function updateBatteryDisplay(element, level, isCharging) {
    const icon = element.querySelector('i');
    const levelSpan = element.querySelector('.battery-level');
    
    // Update icon based on battery level
    if (isCharging) {
        icon.className = 'fas fa-battery-bolt';
        element.style.color = '#10b981';
    } else if (level >= 75) {
        icon.className = 'fas fa-battery-full';
        element.style.color = '#10b981';
    } else if (level >= 50) {
        icon.className = 'fas fa-battery-three-quarters';
        element.style.color = '#10b981';
    } else if (level >= 25) {
        icon.className = 'fas fa-battery-half';
        element.style.color = '#f59e0b';
    } else if (level >= 10) {
        icon.className = 'fas fa-battery-quarter';
        element.style.color = '#ef4444';
    } else {
        icon.className = 'fas fa-battery-empty';
        element.style.color = '#ef4444';
    }
    
    levelSpan.textContent = `${level}%`;
}

// Show location history modal
function showLocationHistory(deviceId) {
    const modal = document.createElement('div');
    modal.className = 'history-modal';
    modal.innerHTML = `
        <div class="history-modal-content">
            <div class="history-modal-header">
                <h2><i class="fas fa-history"></i> Location History</h2>
                <button class="close-modal" onclick="this.closest('.history-modal').remove()">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="history-controls">
                <button onclick="loadHistoryData('${deviceId}', 1)" class="history-btn-filter">Last 24 Hours</button>
                <button onclick="loadHistoryData('${deviceId}', 7)" class="history-btn-filter active">Last 7 Days</button>
                <button onclick="loadHistoryData('${deviceId}', 30)" class="history-btn-filter">Last 30 Days</button>
            </div>
            <div class="history-content" id="historyContent">
                <div class="loading-spinner">
                    <i class="fas fa-spinner fa-spin"></i> Loading history...
                </div>
            </div>
            <div class="history-chart" id="historyChart">
                <canvas id="locationChart"></canvas>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Load initial data (7 days)
    loadHistoryData(deviceId, 7);
    
    // Close on outside click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

// Load history data from API
function loadHistoryData(deviceId, days) {
    const content = document.getElementById('historyContent');
    const chartCanvas = document.getElementById('locationChart');
    
    content.innerHTML = '<div class="loading-spinner"><i class="fas fa-spinner fa-spin"></i> Loading history...</div>';
    
    fetch(`/api/device/${deviceId}/location-history?days=${days}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                displayLocationHistory(data.history, content);
                renderLocationChart(data.history, chartCanvas);
            } else {
                content.innerHTML = `<div class="error-message"><i class="fas fa-exclamation-circle"></i> ${data.error}</div>`;
            }
        })
        .catch(error => {
            console.error('Error loading history:', error);
            content.innerHTML = '<div class="error-message"><i class="fas fa-exclamation-circle"></i> Failed to load history</div>';
        });
}

// Display location history as a list
function displayLocationHistory(history, container) {
    if (!history || history.length === 0) {
        container.innerHTML = '<div class="no-history"><i class="fas fa-map-marker-alt"></i> No location history available</div>';
        return;
    }
    
    const html = history.map(location => {
        const date = new Date(location.timestamp);
        const timeStr = date.toLocaleString();
        
        return `
            <div class="history-item">
                <div class="history-time">
                    <i class="fas fa-clock"></i>
                    ${timeStr}
                </div>
                <div class="history-coords">
                    <i class="fas fa-map-marker-alt"></i>
                    ${location.latitude.toFixed(6)}, ${location.longitude.toFixed(6)}
                </div>
                ${location.accuracy ? `<div class="history-accuracy">±${location.accuracy}m</div>` : ''}
            </div>
        `;
    }).join('');
    
    container.innerHTML = html;
}

// Render location history chart
function renderLocationChart(history, canvas) {
    if (!history || history.length === 0) return;
    
    const ctx = canvas.getContext('2d');
    
    // Simple line chart showing movement over time
    const timestamps = history.map(h => new Date(h.timestamp).toLocaleTimeString());
    const latitudes = history.map(h => h.latitude);
    const longitudes = history.map(h => h.longitude);
    
    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // Set canvas size
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 300;
    
    // Draw grid
    ctx.strokeStyle = '#e0e0e0';
    ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) {
        const y = (canvas.height / 5) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
    }
    
    // Draw latitude line
    ctx.strokeStyle = '#667eea';
    ctx.lineWidth = 2;
    ctx.beginPath();
    
    const latMin = Math.min(...latitudes);
    const latMax = Math.max(...latitudes);
    const latRange = latMax - latMin || 0.001;
    
    latitudes.forEach((lat, index) => {
        const x = (canvas.width / (latitudes.length - 1)) * index;
        const y = canvas.height - ((lat - latMin) / latRange) * canvas.height;
        
        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();
    
    // Add legend
    ctx.font = '12px sans-serif';
    ctx.fillStyle = '#667eea';
    ctx.fillText('Movement Pattern', 10, 20);
}

console.log('Main script initialized');

// Device Action Functions
function locateDevice(deviceId) {
    console.log('Locating device:', deviceId);
    // You can implement location tracking here
    alert('Location tracking for device ' + deviceId + ' will be implemented soon.');
}

function ringDevice(deviceId) {
    console.log('Ringing device:', deviceId);
    // You can implement device ringing here
    alert('Ring command sent to device ' + deviceId);
}

function inspectDeviceData(deviceId) {
    console.log('Inspecting device data for:', deviceId);
    
    fetch('/api/debug-device-data', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ device_id: deviceId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success && data.devices && data.devices.length > 0) {
            const device = data.devices.find(d => d.id === deviceId) || data.devices[0];
            
            // Create a modal or alert to show device data
            const deviceInfo = JSON.stringify(device, null, 2);
            const popup = window.open('', '_blank', 'width=800,height=600,scrollbars=yes');
            popup.document.write(`
                <html>
                <head>
                    <title>Device Data Inspector</title>
                    <style>
                        body { 
                            font-family: monospace; 
                            background: #1a1a1a; 
                            color: #10b981; 
                            padding: 20px; 
                        }
                        pre { 
                            white-space: pre-wrap; 
                            word-wrap: break-word; 
                            background: #111; 
                            padding: 15px; 
                            border-radius: 5px; 
                            border: 1px solid #333;
                        }
                    </style>
                </head>
                <body>
                    <h2>🔬 Device Data Inspector</h2>
                    <p>Raw Firebase data for device: <strong>${deviceId}</strong></p>
                    <pre>${deviceInfo}</pre>
                </body>
                </html>
            `);
        } else {
            alert('No device data found for device: ' + deviceId);
        }
    })
    .catch(error => {
        console.error('Error inspecting device data:', error);
        alert('Failed to inspect device data. Please try again.');
    });
}