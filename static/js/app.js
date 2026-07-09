// ============================================================
// SkillSync AI — Essential Frontend Utilities
// Only functions used across templates are kept.
// ============================================================

/* ────────────────────────────────────────────────────────────
   TOKEN & SESSION
   ──────────────────────────────────────────────────────────── */
function token() {
  return localStorage.getItem("access");
}

function isTokenExpired(token) {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.exp * 1000 < Date.now();
  } catch {
    return true;
  }
}

function getCSRFToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function ensureJWTToken() {
  const existing = localStorage.getItem("access");
  if (existing && !isTokenExpired(existing)) return existing;

  if (existing && isTokenExpired(existing)) {
    const refreshed = await refreshToken();
    if (refreshed) return refreshed;
  }

  try {
    const csrfToken = getCSRFToken();
    const headers = { "Content-Type": "application/json" };
    if (csrfToken) headers["X-CSRFToken"] = csrfToken;

    const resp = await fetch("/api/auth/token/", {
      method: "POST",
      credentials: "include",
      headers: headers,
      body: "{}"
    });

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail || "Not authenticated");
    }

    const data = await resp.json();
    saveSession(data);
    return data.access;
  } catch (e) {
    console.debug("ensureJWTToken:", e.message);
    return null;
  }
}

function saveSession(result) {
  localStorage.setItem("access", result.access);
  localStorage.setItem("refresh", result.refresh);
  saveUser(result.user);
}

function saveUser(user) {
  localStorage.setItem("role", user.role || "");
  localStorage.setItem("email", user.email || "");
  localStorage.setItem("username", user.username || user.email || "User");
  localStorage.setItem("profile_picture", user.profile_picture || "");
}

function logout() {
  localStorage.clear();
  window.location.href = "/login/";
}

function routeByRole(role) {
  const routes = {
    job_seeker: "/dashboard/seeker/",
    recruiter: "/dashboard/recruiter/",
    admin: "/dashboard/admin/"
  };
  window.location.href = routes[role] || "/login/";
}

function requireAuthenticated() {
  if (!token()) {
    window.location.href = "/login/";
    return false;
  }
  return true;
}

function requireRole(role) {
  if (!requireAuthenticated()) return;
  const allowed = Array.isArray(role) ? role : [role];
  const userRole = localStorage.getItem("role");
  if (!allowed.includes(userRole)) {
    routeByRole(userRole);
  }
}

/* ────────────────────────────────────────────────────────────
   API
   ──────────────────────────────────────────────────────────── */
let _refreshPromise = null;

async function refreshToken() {
  if (_refreshPromise) return _refreshPromise;

  _refreshPromise = (async () => {
    try {
      const refresh = localStorage.getItem("refresh");
      if (!refresh) return null;

      const resp = await fetch("/api/auth/refresh/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh })
      });

      if (!resp.ok) return null;

      const data = await resp.json();
      localStorage.setItem("access", data.access);
      if (data.refresh) localStorage.setItem("refresh", data.refresh);
      return data.access;
    } catch {
      return null;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}

async function api(url, options = {}, auth = true) {
  const isFormData = options.body instanceof FormData;
  const headers = { ...(options.headers || {}) };

  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }

  if (auth && token()) {
    headers["Authorization"] = `Bearer ${token()}`;
  }

  const method = (options.method || "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    const csrfToken = getCSRFToken();
    if (csrfToken) headers["X-CSRFToken"] = csrfToken;
  }

  let response = await fetch(url, { ...options, headers });

  if (response.status === 401 && auth) {
    const newToken = await refreshToken();
    if (newToken) {
      headers["Authorization"] = `Bearer ${newToken}`;
      response = await fetch(url, { ...options, headers });
    } else {
      logout();
      throw new Error("Session expired");
    }
  }

  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_) {
    data = { detail: text || "Unexpected response" };
  }

  if (!response.ok) {
    const msg = data.detail || data.message || JSON.stringify(data);
    throw new Error(msg);
  }

  return data;
}

/* ────────────────────────────────────────────────────────────
   UI HELPERS
   ──────────────────────────────────────────────────────────── */
function showMessage(message, type = "info") {
  const target = document.getElementById("message");
  if (!target) return;

  const typeMap = {
    success: "text-success",
    danger: "text-danger",
    warning: "text-warning",
    info: "text-info",
  };

  const className = typeMap[type] || "text-info";
  target.innerHTML = `<div class="${className}">${escapeHtml(message)}</div>`;
}

function escapeHtml(value) {
  if (value == null) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function roleLabel(role) {
  const map = {
    job_seeker: "Job Seeker",
    recruiter: "Recruiter",
    admin: "Admin"
  };
  return map[role] || "Guest";
}

function initials(nameOrEmail) {
  if (!nameOrEmail) return "S";
  const str = String(nameOrEmail).trim();
  if (str.includes("@")) return str.charAt(0).toUpperCase();
  const parts = str.split(/\s+/);
  const init = parts.slice(0, 2).map(p => p.charAt(0)).join("");
  return init.toUpperCase() || "S";
}

function workModeLabel(value) {
  const map = {
    remote: "Remote",
    hybrid: "Hybrid",
    onsite: "On-site"
  };
  return map[value] || "On-site";
}

/* ────────────────────────────────────────────────────────────
   RENDER HELPERS
   ──────────────────────────────────────────────────────────── */
function renderAvatar(src, label, classes = "") {
  const safeLabel = escapeHtml(label || "User");
  if (src) {
    return `<img class="avatar ${classes}" src="${escapeHtml(src)}" alt="${safeLabel}">`;
  }
  const init = escapeHtml(initials(label));
  return `<span class="avatar avatar-fallback ${classes}" aria-label="${safeLabel}">${init}</span>`;
}

function renderCompanyLogo(src, company, classes = "") {
  const safeCompany = escapeHtml(company || "Company");
  if (src) {
    return `<img class="company-logo ${classes}" src="${escapeHtml(src)}" alt="${safeCompany} logo">`;
  }
  const init = escapeHtml(initials(company || "S"));
  return `<span class="company-logo company-logo-fallback ${classes}" aria-label="${safeCompany}">${init}</span>`;
}

/* ────────────────────────────────────────────────────────────
   FILE HELPERS
   ──────────────────────────────────────────────────────────── */
function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file) {
      resolve("");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/* ────────────────────────────────────────────────────────────
   JOB ACTIONS
   ──────────────────────────────────────────────────────────── */
async function submitJobApplication(id, button) {
  const original = button ? button.innerHTML : "";
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Applying';
  }

  try {
    await api(`/api/jobs/apply/${id}/`, {
      method: "POST",
      body: JSON.stringify({ cover_letter: "Submitted from SkillSync AI" })
    });

    if (button) {
      button.classList.remove("btn-apply");
      button.classList.add("btn-success", "btn-applied");
      button.innerHTML = '<i class="bi bi-check2-circle me-1"></i> Applied';
      button.disabled = true;
    }
  } catch (error) {
    if (button) {
      button.disabled = false;
      button.innerHTML = original;
    }
    showMessage(error.message || "Application failed.", "danger");
  }
}

async function toggleSavedJob(id, button) {
  try {
    const result = await api(`/api/jobs/saved/${id}/`, { method: "POST" });
    if (button) {
      button.classList.toggle("btn-primary", result.saved);
      button.classList.toggle("btn-outline-primary", !result.saved);
      button.innerHTML = result.saved
        ? '<i class="bi bi-bookmark-fill me-1"></i> Bookmarked'
        : '<i class="bi bi-bookmark me-1"></i> Bookmark';
    }
    return result.saved;
  } catch (error) {
    showMessage(error.message || "Failed to toggle bookmark.", "danger");
    return false;
  }
}

async function markRecentlyViewed(id) {
  try {
    await api(`/api/jobs/viewed/${id}/`, { method: "POST" });
  } catch (_) {
    // silent fail
  }
}

/* ────────────────────────────────────────────────────────────
   NOTIFICATION BELL
   ──────────────────────────────────────────────────────────── */
async function loadNotificationBell() {
  const badge = document.getElementById("notificationBadge");
  if (!badge || !token() || localStorage.getItem("role") !== "job_seeker") return;

  try {
    const notifications = await api("/api/notifications/");
    const unread = notifications.filter(n => !n.is_read).length;
    badge.textContent = unread;
    badge.classList.toggle("d-none", unread === 0);
  } catch (_) {
    badge.classList.add("d-none");
  }
}

/* ────────────────────────────────────────────────────────────
   SIDEBAR TOGGLE (mobile)
   ──────────────────────────────────────────────────────────── */
function initSidebarToggle() {
  const sidebar = document.getElementById('appSidebar');
  const overlay = document.getElementById('sidebarOverlay');
  const toggleBtn = document.getElementById('sidebarToggle');

  if (!sidebar || !overlay) return;

  function toggleSidebar(open) {
    const isOpen = typeof open === 'boolean' ? open : sidebar.classList.toggle('open');
    sidebar.classList.toggle('open', isOpen);
    overlay.classList.toggle('active', isOpen);
    document.body.style.overflow = isOpen ? 'hidden' : '';
  }

  if (toggleBtn) {
    toggleBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      toggleSidebar();
    });
  }

  overlay.addEventListener('click', function() {
    toggleSidebar(false);
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && sidebar.classList.contains('open')) {
      toggleSidebar(false);
    }
  });

  sidebar.querySelectorAll('a.nav-link').forEach(function(link) {
    link.addEventListener('click', function() {
      if (window.innerWidth <= 1199.98) {
        toggleSidebar(false);
      }
    });
  });

  window.toggleAppSidebar = toggleSidebar;
}

/* ────────────────────────────────────────────────────────────
   NAVBAR / SIDEBAR HYDRATION
   ──────────────────────────────────────────────────────────── */
function hydrateNavbar() {
  const role = localStorage.getItem("role");
  const email = localStorage.getItem("email");
  const username = localStorage.getItem("username") || email || "Guest";
  const profilePicture = localStorage.getItem("profile_picture");
  const hasToken = Boolean(token());

  document.querySelectorAll("[data-auth-only]").forEach(el => {
    el.classList.toggle("d-none", !hasToken);
  });

  document.querySelectorAll("[data-guest-only]").forEach(el => {
    el.classList.toggle("d-none", hasToken);
  });

  document.querySelectorAll("[data-role]").forEach(el => {
    const roles = String(el.dataset.role || "").split(",").map(s => s.trim());
    const show = hasToken && roles.includes(role);
    el.classList.toggle("d-none", !show);
  });

  const nameTarget = document.getElementById("navUserName");
  const roleTarget = document.getElementById("navUserRole");
  const avatarTarget = document.getElementById("navAvatar");

  if (nameTarget) nameTarget.textContent = username;
  if (roleTarget) roleTarget.textContent = roleLabel(role);
  if (avatarTarget) avatarTarget.innerHTML = renderAvatar(profilePicture, username, "avatar-sm");

  const sidebarAvatar = document.getElementById("sidebarAvatar");
  const sidebarName = document.getElementById("sidebarUserName");
  const sidebarRole = document.getElementById("sidebarUserRole");

  if (sidebarAvatar) sidebarAvatar.innerHTML = renderAvatar(profilePicture, username, "avatar-sm");
  if (sidebarName) sidebarName.textContent = username;
  if (sidebarRole) sidebarRole.textContent = roleLabel(role);

  const path = window.location.pathname;
  document.querySelectorAll(".navbar .nav-link, .app-sidebar .nav-link").forEach(link => {
    const href = link.getAttribute("href");
    if (!href) return;
    const isActive = href === "/" ? path === "/" : path.startsWith(href);
    link.classList.toggle("active", isActive);
  });

  const sidebar = document.getElementById('appSidebar');
  if (sidebar) {
    const isVisible = !sidebar.classList.contains('d-none');
    document.body.classList.toggle('has-sidebar', isVisible);
  }
}

/* ────────────────────────────────────────────────────────────
   INIT
   ──────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async function() {
  await ensureJWTToken();
  hydrateNavbar();
  loadNotificationBell();
  initSidebarToggle();
});

setInterval(loadNotificationBell, 30000);

window.addEventListener("storage", function(e) {
  if (e.key === "access" && e.newValue === null) {
    window.location.href = "/login/";
  }
});

// Expose essential functions globally
window.token = token;
window.saveSession = saveSession;
window.saveUser = saveUser;
window.logout = logout;
window.routeByRole = routeByRole;
window.requireAuthenticated = requireAuthenticated;
window.requireRole = requireRole;
window.api = api;
window.showMessage = showMessage;
window.escapeHtml = escapeHtml;
window.roleLabel = roleLabel;
window.initials = initials;
window.workModeLabel = workModeLabel;
window.renderAvatar = renderAvatar;
window.renderCompanyLogo = renderCompanyLogo;
window.fileToDataUrl = fileToDataUrl;
window.submitJobApplication = submitJobApplication;
window.toggleSavedJob = toggleSavedJob;
window.markRecentlyViewed = markRecentlyViewed;
window.loadNotificationBell = loadNotificationBell;
window.hydrateNavbar = hydrateNavbar;
window.initSidebarToggle = initSidebarToggle;
window.ensureJWTToken = ensureJWTToken;
window.isTokenExpired = isTokenExpired;
window.refreshToken = refreshToken;
window.getCSRFToken = getCSRFToken;