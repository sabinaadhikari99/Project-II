// file path: static/js/app.js
function token() {
  return localStorage.getItem("access");
}

function saveSession(result) {
  localStorage.setItem("access", result.access);
  localStorage.setItem("refresh", result.refresh);
  saveUser(result.user);
}

function saveUser(user) {
  localStorage.setItem("role", user.role);
  localStorage.setItem("email", user.email);
  localStorage.setItem("username", user.username || user.email);
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

async function api(url, options = {}, auth = true) {
  const isFormData = options.body instanceof FormData;
  const headers = {...(options.headers || {})};
  if (!isFormData) headers["Content-Type"] = "application/json";
  if (auth && token()) headers.Authorization = `Bearer ${token()}`;
  const response = await fetch(url, {...options, headers});
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (error) {
    data = {detail: text};
  }
  if (!response.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

function showMessage(message, type = "info") {
  const target = document.getElementById("message");
  if (target) target.innerHTML = `<div class="alert alert-${type} border-0 shadow-sm">${escapeHtml(message)}</div>`;
}

function requireRole(role) {
  if (!requireAuthenticated()) return;
  const allowed = Array.isArray(role) ? role : [role];
  if (!allowed.includes(localStorage.getItem("role"))) routeByRole(localStorage.getItem("role"));
}

function roleLabel(role) {
  return {
    job_seeker: "Jobseeker",
    recruiter: "Recruiter",
    admin: "Admin"
  }[role] || "Guest";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function initials(nameOrEmail) {
  const value = String(nameOrEmail || "S").trim();
  const pieces = value.includes("@") ? [value[0]] : value.split(/\s+/);
  return pieces.slice(0, 2).map(piece => piece[0] || "").join("").toUpperCase() || "S";
}

function renderAvatar(src, label, classes = "") {
  const safeLabel = escapeHtml(label || "SkillSync user");
  if (src) {
    return `<img class="avatar ${classes}" src="${escapeHtml(src)}" alt="${safeLabel}">`;
  }
  return `<span class="avatar avatar-fallback ${classes}" aria-label="${safeLabel}">${escapeHtml(initials(label))}</span>`;
}

function renderCompanyLogo(src, company, classes = "") {
  if (src) {
    return `<img class="company-logo ${classes}" src="${escapeHtml(src)}" alt="${escapeHtml(company || "Company")} logo">`;
  }
  return `<span class="company-logo company-logo-fallback ${classes}" aria-label="${escapeHtml(company || "Company")}">${escapeHtml(initials(company || "S"))}</span>`;
}

function workModeLabel(value) {
  return {
    remote: "Remote",
    hybrid: "Hybrid",
    onsite: "On-site"
  }[value] || "On-site";
}

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

async function submitJobApplication(id, button) {
  const original = button ? button.innerHTML : "";
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Applying';
  }
  try {
    await api(`/api/jobs/apply/${id}/`, {method: "POST", body: JSON.stringify({cover_letter: "Submitted from SkillSync AI"})});
    if (button) {
      button.className = "btn btn-success btn-sm";
      button.innerHTML = '<i class="bi bi-check2-circle"></i> Applied';
    }
  } catch (error) {
    if (button) {
      button.disabled = false;
      button.innerHTML = original;
    }
    alert(error.message);
  }
}

async function toggleSavedJob(id, button) {
  const result = await api(`/api/jobs/saved/${id}/`, {method: "POST"});
  if (button) {
    button.classList.toggle("btn-primary", result.saved);
    button.classList.toggle("btn-outline-primary", !result.saved);
    button.innerHTML = result.saved ? '<i class="bi bi-bookmark-fill"></i> Bookmarked' : '<i class="bi bi-bookmark"></i> Bookmark';
  }
  return result.saved;
}

async function markRecentlyViewed(id) {
  try {
    await api(`/api/jobs/viewed/${id}/`, {method: "POST"});
  } catch (error) {
    console.warn(error.message);
  }
}

async function loadNotificationBell() {
  const badge = document.getElementById("notificationBadge");
  if (!badge || !token() || localStorage.getItem("role") !== "job_seeker") return;
  try {
    const notifications = await api("/api/notifications/");
    const unread = notifications.filter(item => !item.is_read).length;
    badge.textContent = unread;
    badge.classList.toggle("d-none", unread === 0);
  } catch (error) {
    badge.classList.add("d-none");
  }
}

function hydrateNavbar() {
  const role = localStorage.getItem("role");
  const email = localStorage.getItem("email");
  const username = localStorage.getItem("username") || email;
  const profilePicture = localStorage.getItem("profile_picture");
  document.querySelectorAll("[data-auth-only]").forEach(item => item.classList.toggle("d-none", !token()));
  document.querySelectorAll("[data-guest-only]").forEach(item => item.classList.toggle("d-none", Boolean(token())));
  document.querySelectorAll("[data-role]").forEach(item => {
    const roles = String(item.dataset.role || "").split(",").map(value => value.trim());
    item.classList.toggle("d-none", !token() || !roles.includes(role));
  });

  const nameTarget = document.getElementById("navUserName");
  const roleTarget = document.getElementById("navUserRole");
  const avatarTarget = document.getElementById("navAvatar");
  if (nameTarget) nameTarget.textContent = username || "Guest";
  if (roleTarget) roleTarget.textContent = roleLabel(role);
  if (avatarTarget) avatarTarget.innerHTML = renderAvatar(profilePicture, username, "avatar-sm");
  const sidebarAvatarTarget = document.getElementById("sidebarAvatar");
  const sidebarNameTarget = document.getElementById("sidebarUserName");
  const sidebarRoleTarget = document.getElementById("sidebarUserRole");
  if (sidebarAvatarTarget) sidebarAvatarTarget.innerHTML = renderAvatar(profilePicture, username, "avatar-sm");
  if (sidebarNameTarget) sidebarNameTarget.textContent = username || "Guest";
  if (sidebarRoleTarget) sidebarRoleTarget.textContent = roleLabel(role);

  const path = window.location.pathname;
  document.querySelectorAll(".navbar .nav-link, .app-sidebar .nav-link").forEach(link => {
    const href = link.getAttribute("href");
    link.classList.toggle("active", href !== "/" && path.startsWith(href));
  });
}

document.addEventListener("DOMContentLoaded", hydrateNavbar);
document.addEventListener("DOMContentLoaded", loadNotificationBell);
setInterval(loadNotificationBell, 30000);
