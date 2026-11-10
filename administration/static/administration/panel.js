(() => {
  "use strict";

  const app = document.getElementById("admin-app");
  const apiBase = app.dataset.apiBase;
  const $ = (id) => document.getElementById(id);

  const state = {
    access: sessionStorage.getItem("admin_access") || sessionStorage.getItem("tn_access") || sessionStorage.getItem("loan_access") || sessionStorage.getItem("barber_access"),
    refresh: sessionStorage.getItem("admin_refresh") || sessionStorage.getItem("tn_refresh") || sessionStorage.getItem("loan_refresh") || sessionStorage.getItem("barber_refresh"),
    username: sessionStorage.getItem("admin_username") || sessionStorage.getItem("tn_username") || "",
    users: [],
    toastTimer: null,
  };

  function initials(name) {
    return String(name || "U")
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0] || "")
      .join("")
      .toUpperCase();
  }

  function escapeHtml(str) {
    return String(str ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function toast(message) {
    const el = $("toast");
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
  }

  function setScreen(screen) {
    $("auth-screen").hidden = screen !== "auth";
    $("dashboard-screen").hidden = screen !== "dashboard";
  }

  async function rawRequest(path, options = {}, withAuth = true) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (withAuth && state.access) headers.set("Authorization", `Bearer ${state.access}`);
    return fetch(`${apiBase}${path}`, { ...options, headers });
  }

  async function refreshToken() {
    if (!state.refresh) return false;
    const response = await rawRequest("/auth/refresh/", {
      method: "POST",
      body: JSON.stringify({ refresh: state.refresh }),
    }, false);
    if (!response.ok) return false;
    const data = await response.json();
    state.access = data.access;
    sessionStorage.setItem("admin_access", data.access);
    sessionStorage.setItem("tn_access", data.access);
    return true;
  }

  async function api(path, options = {}) {
    let response = await rawRequest(path, options);
    if (response.status === 401 && await refreshToken()) {
      response = await rawRequest(path, options);
    }
    if (response.status === 401 || response.status === 403) {
      if (response.status === 403) {
        showAuthError("Acceso denegado: solo administradores de TuNegocio Digital pueden ingresar.");
      }
      logout(false);
      throw new Error("Sesión requerida como administrador.");
    }
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      const msg = data && data.detail ? data.detail : "Error en la solicitud.";
      throw new Error(msg);
    }
    return data;
  }

  function showAuthError(msg) {
    const el = $("auth-error");
    if (el) {
      el.textContent = msg;
      el.hidden = !msg;
    }
  }

  function logout(clearNotice = true) {
    ["admin_access", "admin_refresh", "admin_username"].forEach((k) => sessionStorage.removeItem(k));
    state.access = null;
    state.refresh = null;
    state.username = "";
    if (clearNotice) showAuthError("");
    setScreen("auth");
  }

  // ---------------------------------------------------------------- Data Loading & Rendering
  async function loadUsers() {
    try {
      const users = await api("/admin/users-modules/");
      state.users = users;
      renderKPIs(users);
      renderTable(users);
    } catch (e) {
      toast(e.message);
    }
  }

  function renderKPIs(users) {
    let totalTenants = 0;
    let totalLoans = 0;
    let totalBarbershops = 0;

    users.forEach((u) => {
      totalTenants += (u.tenants || []).length;
      if (u.modules && u.modules.loans) totalLoans++;
      if (u.modules && u.modules.barbershop) totalBarbershops++;
    });

    $("kpi-users").textContent = users.length;
    $("kpi-tenants").textContent = totalTenants;
    $("kpi-loans").textContent = totalLoans;
    $("kpi-barbershop").textContent = totalBarbershops;
  }

  function renderTable(users) {
    const tbody = $("users-table-body");
    tbody.replaceChildren();

    const search = ($("user-search").value || "").toLowerCase().trim();
    const filtered = users.filter((u) => {
      if (!search) return true;
      return (
        (u.username && u.username.toLowerCase().includes(search)) ||
        (u.full_name && u.full_name.toLowerCase().includes(search)) ||
        (u.email && u.email.toLowerCase().includes(search))
      );
    });

    if (!filtered.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td colspan="7" class="text-center muted" style="padding: 2rem;">No se encontraron usuarios coincidentes.</td>`;
      tbody.append(tr);
      return;
    }

    filtered.forEach((u) => {
      const tr = document.createElement("tr");

      // User cell
      const userCell = document.createElement("td");
      userCell.innerHTML = `
        <div class="user-cell">
          <div class="user-avatar">${escapeHtml(initials(u.full_name || u.username))}</div>
          <div class="user-info">
            <strong>${escapeHtml(u.full_name || u.username)} ${u.is_superuser ? '<span class="badge badge-admin">Admin</span>' : ''}</strong>
            <small>@${escapeHtml(u.username)} · ${escapeHtml(u.email)}</small>
          </div>
        </div>
      `;
      tr.append(userCell);

      // Tenants cell
      const tenantsCell = document.createElement("td");
      if (u.tenants && u.tenants.length) {
        tenantsCell.innerHTML = u.tenants
          .map((t) => {
            const badgeType = t.business_type === "barberia" ? "💈" : (t.business_type === "prestamista" ? "💰" : "🏢");
            return `<span class="tenant-tag" title="Rol: ${escapeHtml(t.role)}">${badgeType} ${escapeHtml(t.name)}</span>`;
          })
          .join("");
      } else {
        tenantsCell.innerHTML = `<span class="muted"><small>Sin empresas asignadas</small></span>`;
      }
      tr.append(tenantsCell);

      // Toggle modules cells: loans, barbershop, restaurante, lavadero
      ["loans", "barbershop", "restaurante", "lavadero"].forEach((mod) => {
        const td = document.createElement("td");
        td.className = "text-center";
        const isChecked = u.modules && u.modules[mod];

        const wrap = document.createElement("div");
        wrap.className = "toggle-wrap";

        const label = document.createElement("label");
        label.className = "toggle-switch";

        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = !!isChecked;

        input.addEventListener("change", async (event) => {
          const checked = event.target.checked;
          input.disabled = true;
          try {
            await api("/admin/toggle-module/", {
              method: "POST",
              body: JSON.stringify({
                user_id: u.id,
                module: mod,
                enabled: checked,
              }),
            });
            toast(`Módulo ${mod} ${checked ? 'activado' : 'desactivado'} para @${u.username}.`);
            await loadUsers();
          } catch (err) {
            event.target.checked = !checked;
            toast(`Error: ${err.message}`);
          } finally {
            input.disabled = false;
          }
        });

        const span = document.createElement("span");
        span.className = "toggle-slider";

        label.append(input, span);
        wrap.append(label);
        td.append(wrap);
        tr.append(td);
      });

      // Actions cell
      const actionsCell = document.createElement("td");
      actionsCell.className = "text-right";
      const btnAddTenant = document.createElement("button");
      btnAddTenant.type = "button";
      btnAddTenant.className = "btn btn-quiet btn-sm";
      btnAddTenant.textContent = "＋ Negocio";
      btnAddTenant.addEventListener("click", () => openCreateTenantModal(u));
      actionsCell.append(btnAddTenant);
      tr.append(actionsCell);

      tbody.append(tr);
    });
  }

  // ---------------------------------------------------------------- Modal: Crear Negocio
  const createTenantDialog = $("create-tenant-dialog");
  function openCreateTenantModal(user) {
    $("modal-user-id").value = user.id;
    $("modal-user-name").textContent = `@${user.username} (${user.full_name || ''})`;
    $("modal-business-name").value = "";
    $("modal-error").hidden = true;
    createTenantDialog.showModal();
  }

  $("create-tenant-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const userId = form.elements.user_id.value;
    const bType = form.elements.business_type.value;
    const name = form.elements.name.value.trim();
    const btn = form.querySelector("button[type=submit]");

    btn.disabled = true;
    btn.textContent = "Creando...";
    $("modal-error").hidden = true;

    try {
      await api("/admin/create-tenant/", {
        method: "POST",
        body: JSON.stringify({
          user_id: userId,
          business_type: bType,
          name: name,
        }),
      });
      createTenantDialog.close();
      toast("Negocio creado y módulo activado exitosamente.");
      await loadUsers();
    } catch (e) {
      $("modal-error").textContent = e.message;
      $("modal-error").hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = "Crear y Activar Módulo";
    }
  });

  // Close dialog buttons
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();
    });
  });

  // ---------------------------------------------------------------- Auth form & listeners
  $("admin-login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showAuthError("");
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "Verificando...";

    try {
      const response = await rawRequest("/auth/login/", {
        method: "POST",
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      }, false);
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data && data.detail ? data.detail : "Usuario o contraseña incorrectos.");

      if (!data.is_staff && !data.is_superuser) {
        throw new Error("Tu cuenta no tiene privilegios de administrador de plataforma.");
      }

      state.access = data.access;
      state.refresh = data.refresh;
      state.username = data.username;
      sessionStorage.setItem("admin_access", data.access);
      sessionStorage.setItem("admin_refresh", data.refresh);
      sessionStorage.setItem("admin_username", data.username);
      sessionStorage.setItem("tn_access", data.access);

      $("admin-username").textContent = state.username;
      setScreen("dashboard");
      await loadUsers();
    } catch (err) {
      showAuthError(err.message);
    } finally {
      button.disabled = false;
      button.textContent = "Ingresar al panel";
    }
  });

  $("btn-logout").addEventListener("click", () => logout(true));
  $("btn-refresh").addEventListener("click", loadUsers);
  $("user-search").addEventListener("input", () => renderTable(state.users));

  // ---------------------------------------------------------------- Init
  (async function init() {
    if (!state.access) {
      setScreen("auth");
      return;
    }
    try {
      $("admin-username").textContent = state.username || "Admin";
      setScreen("dashboard");
      await loadUsers();
    } catch {
      setScreen("auth");
    }
  })();
})();
