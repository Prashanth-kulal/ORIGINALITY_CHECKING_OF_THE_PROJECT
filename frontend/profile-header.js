/**
 * ==========================================================================
 * COMMON USER PROFILE & TOP HEADER COMPONENT
 * Project Management System
 * ==========================================================================
 */

(function () {
  'use strict';

  // Global state for authenticated profile
  let currentProfile = null;

  // Save token from URL query params (e.g. Google OAuth login or direct session transfer)
  try {
    const urlParams = new URLSearchParams(window.location.search);
    const urlToken = urlParams.get('token');
    if (urlToken) {
      localStorage.setItem('token', urlToken);
    }
  } catch (e) {
    console.error('Error reading urlToken:', e);
  }

  // Utility to compute initials: 'Prashanth Kulal' -> 'PK', 'Mahadevi' -> 'M'
  function computeAvatarInitials(name) {
    if (!name) return 'U';
    const parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'U';
    if (parts.length === 1) {
      return parts[0].charAt(0).toUpperCase();
    }
    return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
  }

  // Toast notification helper
  function showToast(message, type = 'info') {
    let toast = document.getElementById('profileToastAlert');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'profileToastAlert';
      toast.className = 'profile-toast-alert';
      document.body.appendChild(toast);
    }
    toast.className = `profile-toast-alert ${type} show`;
    toast.innerHTML = `<span>${type === 'success' ? '✅' : type === 'error' ? '⚠️' : 'ℹ️'}</span> <span>${message}</span>`;
    setTimeout(() => {
      toast.classList.remove('show');
    }, 4000);
  }

  // Fetch profile from backend
  async function fetchUserProfile() {
    const token = localStorage.getItem('token');
    if (!token) return null;

    try {
      const res = await fetch('/api/profile', {
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (!res.ok) {
        if (res.status === 401) {
          console.warn('Session expired or unauthorized.');
          return null;
        }
        throw new Error('Failed to load profile');
      }

      const data = await res.json();
      currentProfile = data.profile;
      return currentProfile;
    } catch (err) {
      console.error('Error in fetchUserProfile:', err);
      return null;
    }
  }

  // Build and inject topbar controls
  function injectHeaderControls() {
    // Detect dark theme on body (e.g. Faculty dashboard)
    const isDark = document.body.style.background.includes('12121b') ||
                   window.getComputedStyle(document.body).backgroundColor === 'rgb(18, 18, 27)';
    if (isDark) {
      document.body.classList.add('dark-dashboard');
    }

    // Identify target topbar
    let topbar = document.querySelector('.topbar');
    if (!topbar) {
      // If faculty dashboard has <h1> in .main without .topbar, wrap nicely
      const mainEl = document.querySelector('.main');
      if (mainEl) {
        const heading = mainEl.querySelector('h1');
        topbar = document.createElement('div');
        topbar.className = 'topbar';
        topbar.style.cssText = `
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 25px;
          padding: 16px 22px;
          background: #1f1f35;
          border-radius: 16px;
          box-shadow: 0 6px 20px rgba(0,0,0,0.3);
          border: 1px solid #2e2e4a;
        `;
        if (heading) {
          heading.style.margin = '0';
          heading.style.textAlign = 'left';
          heading.style.fontSize = '20px';
          mainEl.insertBefore(topbar, heading);
          topbar.appendChild(heading);
        } else {
          mainEl.insertBefore(topbar, mainEl.firstChild);
        }
      }
    }

    if (!topbar) return;

    // Check if controls already present
    if (topbar.querySelector('.topbar-profile-controls')) return;

    // Make sure topbar uses flex space-between
    topbar.style.display = 'flex';
    topbar.style.justifyContent = 'space-between';
    topbar.style.alignItems = 'center';

    const controlsWrapper = document.createElement('div');
    controlsWrapper.className = 'topbar-profile-controls';

    controlsWrapper.innerHTML = `
      <!-- Notification Icon -->
      <button class="header-notif-btn" id="headerNotifBtn" title="Notifications" aria-label="Notifications">
        🔔
        <span class="header-notif-badge" id="headerNotifBadge">0</span>
      </button>

      <!-- Notification Popover -->
      <div class="header-notif-popover" id="headerNotifPopover">
        <div class="notif-popover-header">
          <span class="notif-popover-title">🔔 Notifications</span>
          <span style="font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase;">Realtime</span>
        </div>
        <div class="notif-empty-state">
          <div class="notif-empty-icon">🔔</div>
          <div class="notif-empty-text">No new notifications</div>
          <div class="notif-empty-subtext">You're all caught up with project updates!</div>
        </div>
      </div>

      <!-- User Avatar / Profile Pill -->
      <div class="header-user-pill" id="headerUserPill" title="Account Menu">
        <div class="header-avatar-circle" id="headerAvatarCircle">...</div>
        <div class="header-user-meta">
          <span class="header-user-name" id="headerUserName">Loading...</span>
          <span class="header-user-role-badge" id="headerUserRoleBadge">User</span>
        </div>
        <span class="header-chevron">▼</span>
      </div>

      <!-- Profile Dropdown Menu -->
      <div class="header-dropdown-menu" id="headerDropdownMenu">
        <div class="dropdown-user-summary">
          <div class="dropdown-avatar-circle" id="dropdownAvatarCircle">...</div>
          <div class="dropdown-user-info">
            <div class="dropdown-name" id="dropdownUserName">Loading...</div>
            <div class="dropdown-email" id="dropdownUserEmail">...</div>
            <span class="dropdown-role-pill" id="dropdownRolePill">Role</span>
          </div>
        </div>
        <div class="dropdown-divider"></div>
        <button class="dropdown-item" id="menuItemProfile">
          <span>👤</span>
          <span>My Profile</span>
        </button>
        <button class="dropdown-item" id="menuItemNotif">
          <span>🔔</span>
          <span>Notifications</span>
        </button>
        <button class="dropdown-item" id="menuItemPassword">
          <span>🔑</span>
          <span>Change Password</span>
        </button>
        <div class="dropdown-divider"></div>
        <button class="dropdown-item danger" id="menuItemLogout">
          <span>🚪</span>
          <span>Logout</span>
        </button>
      </div>
    `;

    topbar.appendChild(controlsWrapper);

    injectModals();
    bindEventListeners();
  }

  // Inject Profile Modal & Change Password Modal into document.body
  function injectModals() {
    if (document.getElementById('profileModalOverlay')) return;

    const modalContainer = document.createElement('div');
    modalContainer.innerHTML = `
      <!-- My Profile Modal -->
      <div class="profile-modal-overlay" id="profileModalOverlay">
        <div class="profile-modal-box">
          <div class="profile-modal-header">
            <div class="profile-modal-title">
              <span>👤</span>
              <span>Account Profile</span>
            </div>
            <button class="profile-modal-close" id="profileModalClose" title="Close">✕</button>
          </div>
          <div class="profile-modal-body">
            <!-- Hero summary -->
            <div class="modal-profile-hero">
              <div class="modal-hero-avatar" id="modalHeroAvatar">--</div>
              <div class="modal-hero-details">
                <h3 id="modalHeroName">User Full Name</h3>
                <span class="modal-hero-role" id="modalHeroRole">Student</span>
              </div>
            </div>

            <!-- View Mode -->
            <div id="profileViewSection">
              <div class="profile-info-grid" id="profileInfoGrid">
                <!-- Dynamically populated -->
              </div>
              <div class="profile-modal-actions">
                <button class="btn-profile-secondary" id="btnEditProfileToggle">✏️ Edit Personal Details</button>
                <button class="btn-profile-primary" id="btnProfileDone">Done</button>
              </div>
            </div>

            <!-- Edit Mode -->
            <div id="profileEditSection" class="profile-edit-form">
              <div class="form-notice">
                🔒 Academic records, allocations, USN, marks, and evaluation assignments are system-controlled and protected. You may safely update your personal name and contact details below.
              </div>
              <form id="profileEditForm">
                <div class="form-group">
                  <label>Full Name</label>
                  <input type="text" id="editProfileName" required placeholder="Enter your full name" />
                </div>
                <div class="form-group">
                  <label>Phone Number</label>
                  <input type="text" id="editProfilePhone" placeholder="Enter contact phone number (e.g. +91 9876543210)" />
                </div>
                <div class="form-group" id="editFacultyDeptGroup" style="display:none;">
                  <label>Department</label>
                  <input type="text" id="editProfileDept" placeholder="Department" />
                </div>
                <div class="profile-modal-actions">
                  <button type="button" class="btn-profile-secondary" id="btnCancelEditProfile">Cancel</button>
                  <button type="submit" class="btn-profile-primary" id="btnSaveProfile">Save Changes</button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </div>

      <!-- Change Password Modal -->
      <div class="profile-modal-overlay" id="passwordModalOverlay">
        <div class="profile-modal-box" style="max-width: 440px;">
          <div class="profile-modal-header">
            <div class="profile-modal-title">
              <span>🔑</span>
              <span>Change Password</span>
            </div>
            <button class="profile-modal-close" id="passwordModalClose" title="Close">✕</button>
          </div>
          <div class="profile-modal-body">
            <form id="changePasswordForm">
              <div class="form-group">
                <label>Current Password</label>
                <input type="password" id="currentPasswordInput" required placeholder="Enter current password" />
              </div>
              <div class="form-group">
                <label>New Password (min 6 characters)</label>
                <input type="password" id="newPasswordInput" required minlength="6" placeholder="Enter new password" />
              </div>
              <div class="form-group">
                <label>Confirm New Password</label>
                <input type="password" id="confirmPasswordInput" required minlength="6" placeholder="Confirm new password" />
              </div>
              <div class="profile-modal-actions">
                <button type="button" class="btn-profile-secondary" id="btnCancelPassword">Cancel</button>
                <button type="submit" class="btn-profile-primary" id="btnSubmitPassword">Update Password</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modalContainer);
  }

  // Update header DOM with active profile
  function renderHeaderProfile(p) {
    if (!p) return;

    const initials = p.avatar_initials || computeAvatarInitials(p.name);

    const elHeaderInitials = document.getElementById('headerAvatarCircle');
    const elHeaderName = document.getElementById('headerUserName');
    const elHeaderRole = document.getElementById('headerUserRoleBadge');
    const elDropdownInitials = document.getElementById('dropdownAvatarCircle');
    const elDropdownName = document.getElementById('dropdownUserName');
    const elDropdownEmail = document.getElementById('dropdownUserEmail');
    const elDropdownRole = document.getElementById('dropdownRolePill');

    if (elHeaderInitials) elHeaderInitials.innerText = initials;
    if (elHeaderName) elHeaderName.innerText = p.name || 'User';
    if (elHeaderRole) elHeaderRole.innerText = p.role_label || p.role || 'User';

    if (elDropdownInitials) elDropdownInitials.innerText = initials;
    if (elDropdownName) elDropdownName.innerText = p.name || 'User';
    if (elDropdownEmail) elDropdownEmail.innerText = p.email || 'Not provided';
    if (elDropdownRole) elDropdownRole.innerText = p.role_label || p.role || 'User';
  }

  // Populate My Profile modal with role-tailored fields
  function renderProfileModal(p) {
    if (!p) return;

    const initials = p.avatar_initials || computeAvatarInitials(p.name);
    const heroAvatar = document.getElementById('modalHeroAvatar');
    const heroName = document.getElementById('modalHeroName');
    const heroRole = document.getElementById('modalHeroRole');

    if (heroAvatar) heroAvatar.innerText = initials;
    if (heroName) heroName.innerText = p.name;
    if (heroRole) heroRole.innerText = p.role_label || p.role;

    const grid = document.getElementById('profileInfoGrid');
    if (!grid) return;
    grid.innerHTML = '';

    const addCard = (label, value, isLocked = false) => {
      const card = document.createElement('div');
      card.className = 'profile-info-card';
      card.innerHTML = `
        <div class="profile-info-label">
          <span>${label}</span>
          ${isLocked ? '<span class="lock-pill" title="Protected System Record">🔒 System</span>' : ''}
        </div>
        <div class="profile-info-value">${value || 'Not provided'}</div>
      `;
      grid.appendChild(card);
    };

    if (p.role === 'student') {
      addCard('Full Name', p.name, false);
      addCard('USN', p.usn, true);
      addCard('Email Address', p.email, true);
      addCard('Phone Number', p.phone, false);
      addCard('Department', p.department, true);
      addCard('Semester', p.semester, true);
      addCard('Team Role', p.role_label, true);
      addCard('Team Name', p.team_name, true);
      addCard('Faculty Guide', p.faculty_name, true);
      if (Array.isArray(p.interests) && p.interests.length) {
        addCard('Project Interests', p.interests.join(', '), true);
      }
    } else if (p.role === 'faculty') {
      addCard('Full Name', p.name, false);
      addCard('Email Address', p.email, true);
      addCard('Phone Number', p.phone, false);
      addCard('Department', p.department, false);
      addCard('Role Designation', p.role_label, true);
      addCard('Allocated Teams Count', `${p.assigned_teams_count || 0} Teams`, true);
      if (Array.isArray(p.expertise) && p.expertise.length) {
        addCard('Areas of Expertise', p.expertise.join(', '), false);
      }
    } else if (p.role === 'coordinator') {
      addCard('Full Name', p.name, false);
      addCard('Email Address', p.email, true);
      addCard('Phone Number', p.phone, false);
      addCard('Department', p.department, false);
      addCard('System Role', p.role_label, true);
      if (Array.isArray(p.expertise) && p.expertise.length) {
        addCard('Responsibilities', p.expertise.join(', '), true);
      }
    }

    // Prepopulate edit form
    const editName = document.getElementById('editProfileName');
    const editPhone = document.getElementById('editProfilePhone');
    const editDept = document.getElementById('editProfileDept');
    const deptGroup = document.getElementById('editFacultyDeptGroup');

    if (editName) editName.value = p.name || '';
    if (editPhone) editPhone.value = p.phone === 'Not provided' ? '' : (p.phone || '');
    if (editDept) editDept.value = p.department === 'Not provided' ? '' : (p.department || '');

    if (deptGroup) {
      deptGroup.style.display = (p.role === 'faculty' || p.role === 'coordinator') ? 'block' : 'none';
    }
  }

  // Bind interactive events
  function bindEventListeners() {
    const notifBtn = document.getElementById('headerNotifBtn');
    const notifPopover = document.getElementById('headerNotifPopover');
    const userPill = document.getElementById('headerUserPill');
    const dropdownMenu = document.getElementById('headerDropdownMenu');

    const profileModalOverlay = document.getElementById('profileModalOverlay');
    const passwordModalOverlay = document.getElementById('passwordModalOverlay');
    const profileModalClose = document.getElementById('profileModalClose');
    const passwordModalClose = document.getElementById('passwordModalClose');

    const menuItemProfile = document.getElementById('menuItemProfile');
    const menuItemNotif = document.getElementById('menuItemNotif');
    const menuItemPassword = document.getElementById('menuItemPassword');
    const menuItemLogout = document.getElementById('menuItemLogout');

    const btnEditProfileToggle = document.getElementById('btnEditProfileToggle');
    const btnCancelEditProfile = document.getElementById('btnCancelEditProfile');
    const btnProfileDone = document.getElementById('btnProfileDone');
    const profileEditForm = document.getElementById('profileEditForm');
    const profileViewSection = document.getElementById('profileViewSection');
    const profileEditSection = document.getElementById('profileEditSection');

    const btnCancelPassword = document.getElementById('btnCancelPassword');
    const changePasswordForm = document.getElementById('changePasswordForm');

    // Toggle Notifications
    if (notifBtn && notifPopover) {
      notifBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (dropdownMenu) dropdownMenu.classList.remove('show');
        if (userPill) userPill.classList.remove('active');
        notifPopover.classList.toggle('show');
      });
    }

    // Toggle Profile Dropdown
    if (userPill && dropdownMenu) {
      userPill.addEventListener('click', (e) => {
        e.stopPropagation();
        if (notifPopover) notifPopover.classList.remove('show');
        userPill.classList.toggle('active');
        dropdownMenu.classList.toggle('show');
      });
    }

    // Close on Click Outside
    document.addEventListener('click', (e) => {
      if (dropdownMenu && !dropdownMenu.contains(e.target) && (!userPill || !userPill.contains(e.target))) {
        dropdownMenu.classList.remove('show');
        if (userPill) userPill.classList.remove('active');
      }
      if (notifPopover && !notifPopover.contains(e.target) && (!notifBtn || !notifBtn.contains(e.target))) {
        notifPopover.classList.remove('show');
      }
    });

    // Close on Escape Key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (dropdownMenu) dropdownMenu.classList.remove('show');
        if (userPill) userPill.classList.remove('active');
        if (notifPopover) notifPopover.classList.remove('show');
        if (profileModalOverlay) profileModalOverlay.classList.remove('show');
        if (passwordModalOverlay) passwordModalOverlay.classList.remove('show');
      }
    });

    // Menu Item Actions
    if (menuItemProfile) {
      menuItemProfile.addEventListener('click', () => {
        if (dropdownMenu) dropdownMenu.classList.remove('show');
        if (userPill) userPill.classList.remove('active');
        if (profileViewSection) profileViewSection.style.display = 'block';
        if (profileEditSection) profileEditSection.classList.remove('active');
        renderProfileModal(currentProfile);
        if (profileModalOverlay) profileModalOverlay.classList.add('show');
      });
    }

    if (menuItemNotif) {
      menuItemNotif.addEventListener('click', () => {
        if (dropdownMenu) dropdownMenu.classList.remove('show');
        if (userPill) userPill.classList.remove('active');
        if (notifPopover) notifPopover.classList.add('show');
      });
    }

    if (menuItemPassword) {
      menuItemPassword.addEventListener('click', () => {
        if (dropdownMenu) dropdownMenu.classList.remove('show');
        if (userPill) userPill.classList.remove('active');
        if (changePasswordForm) changePasswordForm.reset();
        if (passwordModalOverlay) passwordModalOverlay.classList.add('show');
      });
    }

    if (menuItemLogout) {
      menuItemLogout.addEventListener('click', () => {
        if (typeof window.logout === 'function') {
          window.logout();
        } else {
          localStorage.removeItem('token');
          localStorage.removeItem('user');
          window.location.href = 'login.html';
        }
      });
    }

    // Modal Close Buttons
    if (profileModalClose) {
      profileModalClose.addEventListener('click', () => {
        if (profileModalOverlay) profileModalOverlay.classList.remove('show');
      });
    }

    if (btnProfileDone) {
      btnProfileDone.addEventListener('click', () => {
        if (profileModalOverlay) profileModalOverlay.classList.remove('show');
      });
    }

    if (passwordModalClose) {
      passwordModalClose.addEventListener('click', () => {
        if (passwordModalOverlay) passwordModalOverlay.classList.remove('show');
      });
    }

    if (btnCancelPassword) {
      btnCancelPassword.addEventListener('click', () => {
        if (passwordModalOverlay) passwordModalOverlay.classList.remove('show');
      });
    }

    // Toggle between View & Edit Profile
    if (btnEditProfileToggle) {
      btnEditProfileToggle.addEventListener('click', () => {
        if (profileViewSection) profileViewSection.style.display = 'none';
        if (profileEditSection) profileEditSection.classList.add('active');
      });
    }

    if (btnCancelEditProfile) {
      btnCancelEditProfile.addEventListener('click', () => {
        if (profileEditSection) profileEditSection.classList.remove('active');
        if (profileViewSection) profileViewSection.style.display = 'block';
      });
    }

    // Profile Edit Form Submit
    if (profileEditForm) {
      profileEditForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const token = localStorage.getItem('token');
        if (!token) return;

        const newName = document.getElementById('editProfileName').value.trim();
        const newPhone = document.getElementById('editProfilePhone').value.trim();
        const newDept = document.getElementById('editProfileDept') ? document.getElementById('editProfileDept').value.trim() : '';

        const saveBtn = document.getElementById('btnSaveProfile');
        if (saveBtn) {
          saveBtn.disabled = true;
          saveBtn.innerText = 'Saving...';
        }

        try {
          const payload = { name: newName, phone: newPhone };
          if (newDept && (currentProfile.role === 'faculty' || currentProfile.role === 'coordinator')) {
            payload.department = newDept;
          }

          const res = await fetch('/api/profile', {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify(payload)
          });

          const resData = await res.json();
          if (res.ok) {
            showToast('Profile updated successfully!', 'success');
            // Refresh profile data
            const updated = await fetchUserProfile();
            if (updated) {
              renderHeaderProfile(updated);
              renderProfileModal(updated);
            }
            if (profileEditSection) profileEditSection.classList.remove('active');
            if (profileViewSection) profileViewSection.style.display = 'block';
          } else {
            showToast(resData.error || 'Failed to update profile', 'error');
          }
        } catch (err) {
          console.error(err);
          showToast('Server error updating profile.', 'error');
        } finally {
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerText = 'Save Changes';
          }
        }
      });
    }

    // Change Password Form Submit
    if (changePasswordForm) {
      changePasswordForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const token = localStorage.getItem('token');
        if (!token) return;

        const current_password = document.getElementById('currentPasswordInput').value;
        const new_password = document.getElementById('newPasswordInput').value;
        const confirm_password = document.getElementById('confirmPasswordInput').value;

        if (new_password !== confirm_password) {
          showToast('New passwords do not match!', 'error');
          return;
        }

        if (new_password.length < 6) {
          showToast('Password must be at least 6 characters long!', 'error');
          return;
        }

        const submitBtn = document.getElementById('btnSubmitPassword');
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.innerText = 'Updating...';
        }

        try {
          const res = await fetch('/api/profile/change-password', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ current_password, new_password, confirm_password })
          });

          const resData = await res.json();
          if (res.ok) {
            showToast('Password changed successfully!', 'success');
            changePasswordForm.reset();
            if (passwordModalOverlay) passwordModalOverlay.classList.remove('show');
          } else {
            showToast(resData.error || 'Failed to change password.', 'error');
          }
        } catch (err) {
          console.error(err);
          showToast('Server error changing password.', 'error');
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerText = 'Update Password';
          }
        }
      });
    }
  }

  // Initialize on DOM load
  async function initProfileHeader() {
    injectHeaderControls();
    const profile = await fetchUserProfile();
    if (profile) {
      renderHeaderProfile(profile);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initProfileHeader);
  } else {
    initProfileHeader();
  }

  // Expose helper on window if needed
  window.refreshCommonProfileHeader = async function () {
    const profile = await fetchUserProfile();
    if (profile) {
      renderHeaderProfile(profile);
    }
  };
})();
