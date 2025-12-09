/**
 * Lab Document Intelligence System - Main JavaScript
 * HIPAA-Compliant Document Processing
 * MiraVista Diagnostics
 */

// Session Management
let sessionTimer;
let warningTimer;
let sessionTimeLeft = 15 * 60; // 15 minutes in seconds
const WARNING_THRESHOLD = 2 * 60; // Show warning at 2 minutes

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    initTheme();
    initSession();
    checkAuth();
    updateUserDisplay();
});

// =============================================================================
// THEME MANAGEMENT
// =============================================================================

/**
 * Initialize theme based on user preference or system setting
 */
function initTheme() {
    const theme = getPreferredTheme();
    setTheme(theme);

    // Listen for system theme changes (only if user hasn't set a preference)
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!localStorage.getItem('theme')) {
            setTheme(e.matches ? 'dark' : 'light');
        }
    });
}

/**
 * Get the preferred theme
 */
function getPreferredTheme() {
    // First check if user has explicitly set a preference
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        return savedTheme;
    }

    // Otherwise, detect system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
    }
    return 'light';
}

/**
 * Set the theme
 */
function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);

    // Update toggle switch visual state if it exists
    const toggleSwitch = document.querySelector('.toggle-switch');
    if (toggleSwitch) {
        // The CSS handles the visual state based on data-theme
    }
}

/**
 * Toggle between light and dark themes
 */
function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
    // Save user's explicit preference
    localStorage.setItem('theme', newTheme);
}

/**
 * Get current theme
 */
function getCurrentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'light';
}

// =============================================================================
// ERROR DETAIL MODAL
// =============================================================================

/**
 * Show error detail modal for failed items
 * @param {string} itemName - Name/identifier of the failed item
 * @param {string} errorMessage - The error message to display
 * @param {string} status - Status badge HTML or text
 * @param {function} retryCallback - Optional callback for retry button
 */
function showErrorDetail(itemName, errorMessage, status, retryCallback) {
    const modal = document.getElementById('errorDetailModal');
    if (!modal) return;

    document.getElementById('errorDetailItem').textContent = itemName || 'Unknown';
    document.getElementById('errorDetailStatus').innerHTML = status || '<span class="badge bg-danger">Failed</span>';
    document.getElementById('errorDetailMessage').textContent = errorMessage || 'No error details available';

    const retryBtn = document.getElementById('errorDetailRetryBtn');
    if (retryCallback && typeof retryCallback === 'function') {
        retryBtn.style.display = 'inline-block';
        retryBtn.onclick = function() {
            bootstrap.Modal.getInstance(modal).hide();
            retryCallback();
        };
    } else {
        retryBtn.style.display = 'none';
    }

    new bootstrap.Modal(modal).show();
}

/**
 * Initialize session timer and activity tracking
 */
function initSession() {
    resetSessionTimer();

    // Track user activity
    ['click', 'keypress', 'scroll', 'mousemove'].forEach(event => {
        document.addEventListener(event, resetSessionTimer, { passive: true });
    });
}

/**
 * Reset session timer on user activity
 */
function resetSessionTimer() {
    sessionTimeLeft = 15 * 60;
    updateTimerDisplay();

    // Clear existing timers
    clearInterval(sessionTimer);
    clearTimeout(warningTimer);

    // Hide warning modal if open
    const modal = bootstrap.Modal.getInstance(document.getElementById('sessionTimeoutModal'));
    if (modal) {
        modal.hide();
    }

    // Start countdown
    sessionTimer = setInterval(() => {
        sessionTimeLeft--;
        updateTimerDisplay();

        if (sessionTimeLeft === WARNING_THRESHOLD) {
            showSessionWarning();
        }

        if (sessionTimeLeft <= 0) {
            logout();
        }
    }, 1000);
}

/**
 * Update session timer display
 */
function updateTimerDisplay() {
    const minutes = Math.floor(sessionTimeLeft / 60);
    const seconds = sessionTimeLeft % 60;
    const display = `${minutes}:${seconds.toString().padStart(2, '0')}`;

    const timerElement = document.getElementById('timer-display');
    if (timerElement) {
        timerElement.textContent = display;

        // Change color based on time remaining
        if (sessionTimeLeft <= WARNING_THRESHOLD) {
            timerElement.parentElement.classList.add('text-warning');
        } else {
            timerElement.parentElement.classList.remove('text-warning');
        }
    }

    // Update warning modal countdown
    const countdownElement = document.getElementById('timeout-countdown');
    if (countdownElement && sessionTimeLeft <= WARNING_THRESHOLD) {
        countdownElement.textContent = display;
    }
}

/**
 * Show session timeout warning modal
 */
function showSessionWarning() {
    const modal = new bootstrap.Modal(document.getElementById('sessionTimeoutModal'));
    modal.show();
}

/**
 * Extend session (called from warning modal)
 */
function extendSession() {
    resetSessionTimer();

    // Optionally call API to refresh token
    fetch('/api/auth/refresh', {
        method: 'POST',
        headers: getAuthHeaders()
    }).catch(err => console.warn('Token refresh failed:', err));
}

/**
 * Get cookie value by name
 */
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

/**
 * Transfer SSO cookies to localStorage (for API calls)
 * This ensures tokens set via SSO callback are available to the app
 */
function transferSSOCookiesToLocalStorage() {
    const userInfoCookie = getCookie('user_info');
    const jsAccessToken = getCookie('js_access_token');

    if (userInfoCookie && jsAccessToken) {
        try {
            // Only update if localStorage doesn't have the token or has a different one
            const existingToken = localStorage.getItem('access_token');
            if (!existingToken || existingToken !== jsAccessToken) {
                const user = JSON.parse(decodeURIComponent(userInfoCookie));
                localStorage.setItem('user', JSON.stringify(user));
                localStorage.setItem('access_token', jsAccessToken);
                console.log('SSO: Transferred auth cookies to localStorage');
                return true;
            }
        } catch (e) {
            console.error('Failed to parse SSO cookies:', e);
        }
    }
    return false;
}

/**
 * Check if user is authenticated
 */
function checkAuth() {
    // DEVELOPMENT MODE: Skip authentication check for localhost or Azure dev
    const isLocalhost = window.location.hostname === 'localhost' ||
                       window.location.hostname === '127.0.0.1' ||
                       window.location.hostname === '::1';

    // Check if this is a development Azure deployment (server sets this in response)
    const isDevelopmentMode = document.body.dataset.environment === 'development' ||
                             window.__ENVIRONMENT__ === 'development';

    if (isLocalhost || isDevelopmentMode) {
        console.log('Development mode: Bypassing client-side authentication check');
        return;
    }

    // First, try to transfer SSO cookies to localStorage
    transferSSOCookiesToLocalStorage();

    const token = localStorage.getItem('access_token');
    const currentPath = window.location.pathname;

    // Public paths that don't require auth
    const publicPaths = ['/', '/login', '/api/docs', '/api/redoc'];

    if (!token && !publicPaths.includes(currentPath)) {
        // Redirect to login
        window.location.href = '/login';
    }
}

/**
 * Update user display in navbar
 */
function updateUserDisplay() {
    // DEVELOPMENT MODE: Show admin menu for localhost or Azure dev
    const isLocalhost = window.location.hostname === 'localhost' ||
                       window.location.hostname === '127.0.0.1' ||
                       window.location.hostname === '::1';

    // Check if this is a development Azure deployment
    const isDevelopmentMode = document.body.dataset.environment === 'development' ||
                             window.__ENVIRONMENT__ === 'development';

    if (isLocalhost || isDevelopmentMode) {
        // Show admin, power user, and lab staff menus in development mode
        const adminItems = document.querySelectorAll('.admin-only');
        adminItems.forEach(item => item.style.display = 'block');
        const powerUserItems = document.querySelectorAll('.power-user-only');
        powerUserItems.forEach(item => item.style.display = 'block');
        const labStaffItems = document.querySelectorAll('.lab-staff-only');
        labStaffItems.forEach(item => item.style.display = 'block');

        // Set default user display
        const userNameElement = document.getElementById('user-name');
        if (userNameElement) {
            userNameElement.textContent = 'Development User (Admin)';
        }
        return;
    }

    const userJson = localStorage.getItem('user');
    if (userJson) {
        const user = JSON.parse(userJson);
        const userNameElement = document.getElementById('user-name');
        if (userNameElement) {
            userNameElement.textContent = user.full_name;
        }

        // Show admin menu if admin
        if (user.role === 'admin') {
            const adminItems = document.querySelectorAll('.admin-only');
            adminItems.forEach(item => item.style.display = 'block');
            // Admin also gets power user access
            const powerUserItems = document.querySelectorAll('.power-user-only');
            powerUserItems.forEach(item => item.style.display = 'block');
            // Admin also gets lab staff access
            const labStaffItems = document.querySelectorAll('.lab-staff-only');
            labStaffItems.forEach(item => item.style.display = 'block');
        }

        // Show power user menu if admin or reviewer
        if (user.role === 'admin' || user.role === 'reviewer') {
            const powerUserItems = document.querySelectorAll('.power-user-only');
            powerUserItems.forEach(item => item.style.display = 'block');
            // Reviewers also get lab staff access
            const labStaffItems = document.querySelectorAll('.lab-staff-only');
            labStaffItems.forEach(item => item.style.display = 'block');
        }

        // Show lab staff menu for lab_staff role (and above)
        if (user.role === 'lab_staff' || user.role === 'reviewer' || user.role === 'admin') {
            const labStaffItems = document.querySelectorAll('.lab-staff-only');
            labStaffItems.forEach(item => item.style.display = 'block');
        }
    }
}

/**
 * Get authentication headers for API requests
 */
function getAuthHeaders() {
    const token = localStorage.getItem('access_token');
    return {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    };
}

/**
 * Logout user
 */
async function logout() {
    try {
        await fetch('/api/auth/logout', {
            method: 'POST',
            headers: getAuthHeaders(),
            credentials: 'include'  // Ensure cookies are sent/cleared
        });
    } catch (error) {
        console.warn('Logout API call failed:', error);
    }

    // Clear local storage
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');

    // Clear all auth cookies from client side as well
    document.cookie = 'access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    document.cookie = 'js_access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    document.cookie = 'token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    document.cookie = 'user_info=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    document.cookie = 'last_activity=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';

    // Clear session storage
    sessionStorage.clear();

    // Clear session timer
    clearInterval(sessionTimer);

    // Redirect to login page
    window.location.href = '/login';
}

/**
 * Format date for display
 */
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Get confidence score CSS class
 */
function getConfidenceClass(score) {
    if (score >= 0.90) return 'bg-success';
    if (score >= 0.70) return 'bg-warning text-dark';
    return 'bg-danger';
}

/**
 * Show toast notification
 */
function showToast(message, type = 'info') {
    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto"
                    data-bs-dismiss="toast"></button>
        </div>
    `;

    // Add to container or create one
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        document.body.appendChild(container);
    }

    container.appendChild(toast);

    // Show toast
    const bsToast = new bootstrap.Toast(toast, { autohide: true, delay: 5000 });
    bsToast.show();

    // Remove after hidden
    toast.addEventListener('hidden.bs.toast', () => toast.remove());
}

/**
 * Debounce function for search inputs
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Validate form data
 */
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form.checkValidity()) {
        form.reportValidity();
        return false;
    }
    return true;
}

/**
 * Mask PHI data for display
 */
function maskPHI(value, showChars = 3) {
    if (!value) return 'N/A';
    if (value.length <= showChars) return '*'.repeat(value.length);
    return value.substring(0, showChars) + '*'.repeat(value.length - showChars);
}

/**
 * Handle API errors
 */
function handleApiError(error, customMessage = 'An error occurred') {
    console.error('API Error:', error);

    if (error.status === 401) {
        showToast('Session expired. Please login again.', 'danger');
        logout();
    } else if (error.status === 403) {
        showToast('You do not have permission to perform this action.', 'danger');
    } else if (error.status === 404) {
        showToast('Resource not found.', 'warning');
    } else {
        showToast(customMessage, 'danger');
    }
}

/**
 * Confirm action with modal
 */
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

/**
 * Export table data to CSV
 */
function exportTableToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    const rows = table.querySelectorAll('tr');
    let csv = [];

    rows.forEach(row => {
        const cols = row.querySelectorAll('td, th');
        const rowData = [];
        cols.forEach(col => {
            rowData.push('"' + col.innerText.replace(/"/g, '""') + '"');
        });
        csv.push(rowData.join(','));
    });

    const csvContent = csv.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'export.csv';
    a.click();

    window.URL.revokeObjectURL(url);
}

// HIPAA compliance indicator
document.addEventListener('DOMContentLoaded', function() {
    const badge = document.createElement('div');
    badge.className = 'hipaa-badge';
    badge.innerHTML = '<i class="bi bi-shield-check"></i> HIPAA Compliant';
    document.body.appendChild(badge);
});
