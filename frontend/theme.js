/**
 * ==========================================================================
 * STUDENT PROJECT MANAGEMENT SYSTEM - THEME CONTROLLER
 * Reliable, zero-dependency Light/Dark mode state management & persistence
 * ==========================================================================
 */

(function () {
  'use strict';

  var STORAGE_KEY = 'app_theme';

  // 1. Get stored theme preference or default to 'light' (Phase 3 requirement)
  function getSavedTheme() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved === 'dark' || saved === 'light') {
        return saved;
      }
    } catch (e) {
      console.warn('localStorage not accessible for theme:', e);
    }
    // Default to Light Mode for first-time visitors
    return 'light';
  }

  // 2. Apply theme to DOM elements immediately
  function applyTheme(theme) {
    var isDark = theme === 'dark';
    var root = document.documentElement;

    root.setAttribute('data-theme', theme);
    if (isDark) {
      root.classList.add('dark-theme');
      root.classList.remove('light-theme');
    } else {
      root.classList.add('light-theme');
      root.classList.remove('dark-theme');
    }

    if (document.body) {
      document.body.setAttribute('data-theme', theme);
      if (isDark) {
        document.body.classList.add('dark-theme');
        document.body.classList.add('dark-dashboard');
        document.body.classList.remove('light-theme');
      } else {
        document.body.classList.add('light-theme');
        document.body.classList.remove('dark-theme');
        document.body.classList.remove('dark-dashboard');
      }
    }

    // Update all toggle buttons on the page
    updateToggleButtons(theme);

    // Notify listeners (e.g., Chart.js redraws)
    try {
      window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: theme, isDark: isDark } }));
    } catch (e) {
      // IE / older fallback if needed
    }
  }

  // 3. Update all toggle button icons and accessible labels
  function updateToggleButtons(theme) {
    var isDark = theme === 'dark';
    var nextThemeLabel = isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode';
    var icon = isDark ? '☀️' : '🌙';

    var buttons = document.querySelectorAll('.theme-toggle-btn, #authThemeToggleBtn, #headerThemeToggleBtn');
    buttons.forEach(function (btn) {
      btn.setAttribute('aria-label', nextThemeLabel);
      btn.setAttribute('title', nextThemeLabel);
      btn.setAttribute('type', 'button'); // Strictly enforce button type so forms never submit

      var iconSpan = btn.querySelector('.theme-toggle-icon');
      if (iconSpan) {
        iconSpan.textContent = icon;
      } else {
        btn.textContent = icon;
      }
    });
  }

  // 4. Save theme preference
  function setTheme(theme) {
    if (theme !== 'light' && theme !== 'dark') return;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      console.warn('Unable to persist theme to localStorage:', e);
    }
    applyTheme(theme);
  }

  // 5. Toggle theme function
  function toggleTheme() {
    var current = getSavedTheme();
    var next = current === 'dark' ? 'light' : 'dark';
    setTheme(next);
    return next;
  }

  // Expose global methods
  window.getTheme = getSavedTheme;
  window.setTheme = setTheme;
  window.toggleTheme = toggleTheme;

  // Immediately apply saved theme on initial script execution to avoid flash of wrong theme
  applyTheme(getSavedTheme());

  // 6. Bind click events to any toggle buttons present in the DOM
  function bindToggleButtons() {
    var buttons = document.querySelectorAll('.theme-toggle-btn, #authThemeToggleBtn, #headerThemeToggleBtn');
    buttons.forEach(function (btn) {
      btn.setAttribute('type', 'button'); // Never submit forms
      if (btn.dataset.themeBound === 'true') return;
      btn.dataset.themeBound = 'true';

      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        toggleTheme();
      });

      // Keyboard support
      btn.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          e.stopPropagation();
          toggleTheme();
        }
      });
    });

    updateToggleButtons(getSavedTheme());
  }

  // Bind on DOM ready and also expose for dynamically inserted headers
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      applyTheme(getSavedTheme());
      bindToggleButtons();
    });
  } else {
    applyTheme(getSavedTheme());
    bindToggleButtons();
  }

  window.bindThemeToggleButtons = bindToggleButtons;
})();
