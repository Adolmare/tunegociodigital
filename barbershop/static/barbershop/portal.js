(() => {
  "use strict";

  const app = document.getElementById("app");
  const apiBase = app.dataset.apiBase;
  const $ = (id) => document.getElementById(id);

  const state = {
    access: sessionStorage.getItem("barber_access") || sessionStorage.getItem("tn_access") || sessionStorage.getItem("loan_access"),
    refresh: sessionStorage.getItem("barber_refresh") || sessionStorage.getItem("tn_refresh") || sessionStorage.getItem("loan_refresh"),
    username: sessionStorage.getItem("barber_username") || sessionStorage.getItem("tn_username") || sessionStorage.getItem("loan_username") || "",
    memberships: [],
    tenant: null,
    role: "",
    view: "agenda",
    services: [],
    barbers: [],
    customers: [],
    appointments: [],
    chargeTarget: null,
    toastTimer: null,
  };

  const STATUS_LABELS = {
    pending: "Pendiente", confirmed: "Confirmada", in_progress: "En curso",
    completed: "Atendida", cancelled: "Cancelada", no_show: "No vino",
  };
  const METHOD_LABELS = { cash: "Efectivo", transfer: "Transferencia", card: "Tarjeta", other: "Otro" };
  const OPEN = ["pending", "confirmed", "in_progress"];
  const RANK = { employee: 1, manager: 2, admin: 3, owner: 4 };

  const moneyFmt = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
  const money = (value) => moneyFmt.format(Number(value || 0));
  const isManager = () => (RANK[state.role] || 0) >= RANK.manager;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }
  function localDateValue(date = new Date()) {
    const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return d.toISOString().slice(0, 10);
  }
  function localDateTimeValue(date = new Date()) {
    const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return d.toISOString().slice(0, 16);
  }
  const timeOf = (iso) => String(iso).slice(11, 16);
  function displayDate(value) {
    const [y, m, d] = String(value).split("-");
    return `${d}/${m}/${y}`;
  }
  function whatsappUrl(phone, text) {
    const digits = String(phone || "").replace(/\D/g, "");
    if (!digits) return "";
    const full = digits.length === 10 ? `57${digits}` : digits;
    return `https://wa.me/${full}?text=${encodeURIComponent(text)}`;
  }
  const getRows = (data) => (Array.isArray(data) ? data : (data && data.results) || []);

  // ---------------------------------------------------------------- API
  function errorMessage(data, fallback) {
    if (!data) return fallback;
    if (typeof data === "string") return data;
    if (data.detail) return String(data.detail);
    const parts = [];
    Object.values(data).forEach((value) => {
      if (Array.isArray(value)) parts.push(...value.map(String));
      else if (value && typeof value === "object") parts.push(errorMessage(value, ""));
      else if (value) parts.push(String(value));
    });
    return parts.filter(Boolean).join(" ") || fallback;
  }

  function rawRequest(path, options = {}, withAuth = true) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (withAuth && state.access) headers.set("Authorization", `Bearer ${state.access}`);
    if (withAuth && state.tenant) headers.set("X-Tenant-ID", state.tenant.tenant_id);
    return fetch(`${apiBase}${path}`, { ...options, headers });
  }

  async function refreshToken() {
    if (!state.refresh) return false;
    const response = await rawRequest("/auth/refresh/", {
      method: "POST", body: JSON.stringify({ refresh: state.refresh }),
    }, false);
    if (!response.ok) return false;
    const data = await response.json();
    state.access = data.access;
    sessionStorage.setItem("barber_access", data.access);
    if (data.refresh) {
      state.refresh = data.refresh;
      sessionStorage.setItem("barber_refresh", data.refresh);
    }
    return true;
  }

  async function api(path, options = {}) {
    let response = await rawRequest(path, options);
    if (response.status === 401 && await refreshToken()) response = await rawRequest(path, options);
    if (response.status === 401) {
      logout();
      throw new Error("Tu sesión venció. Inicia sesión de nuevo.");
    }
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new Error(errorMessage(data, "No se pudo completar la acción."));
    return data;
  }
  const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
  const patch = (path, body) => api(path, { method: "PATCH", body: JSON.stringify(body) });

  // ---------------------------------------------------------------- UI helpers
  function showError(id, message) {
    const box = $(id);
    box.textContent = message;
    box.hidden = !message;
  }
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
  }
  function busy(button, isBusy, text) {
    if (isBusy) {
      button.dataset.label = button.textContent;
      button.textContent = text;
      button.disabled = true;
    } else {
      button.textContent = button.dataset.label || button.textContent;
      button.disabled = false;
    }
  }
  function setScreen(name) {
    $("auth-screen").hidden = name !== "auth";
    $("workspace").hidden = name !== "workspace";
  }

  // ---------------------------------------------------------------- Sesión
  function saveSession(data) {
    state.access = data.access;
    state.refresh = data.refresh;
    state.username = data.username || state.username;
    ["barber_access", "tn_access"].forEach((k) => sessionStorage.setItem(k, state.access));
    if (state.refresh) ["barber_refresh", "tn_refresh"].forEach((k) => sessionStorage.setItem(k, state.refresh));
    if (state.username) ["barber_username", "tn_username"].forEach((k) => sessionStorage.setItem(k, state.username));
  }

  function logout() {
    ["barber_access", "barber_refresh", "barber_username", "barber_tenant", "tn_access", "tn_refresh", "tn_username"].forEach((k) => sessionStorage.removeItem(k));
    Object.assign(state, {
      access: null, refresh: null, username: "", tenant: null, role: "",
      memberships: [], services: [], barbers: [], customers: [], appointments: [],
    });
    ["agenda-list", "customer-list", "service-list", "barber-list", "caja-rows"].forEach((id) => { const el = $(id); if (el) el.replaceChildren(); });
    setScreen("auth");
  }

  function renderOnboardingBusinesses(memberships) {
    const list = $("onboarding-businesses-list");
    if (!list) return;
    list.replaceChildren();
    if (!memberships.length) return;
    memberships.forEach((m) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:var(--bg-soft);border-radius:6px;";
      row.innerHTML =
        `<div><strong>${escapeHtml(m.tenant_name)}</strong><br><small style="color:var(--accent);">💰 Préstamos</small></div>` +
        `<button class="btn btn-ghost btn-sm" type="button">Abrir préstamos ↗</button>`;
      row.querySelector("button").addEventListener("click", () => {
        sessionStorage.setItem("loan_tenant", JSON.stringify(m));
        window.location.href = "/loans/";
      });
      list.append(row);
    });
  }

  async function enterWorkspace() {
    const memberships = getRows(await api("/auth/me/tenants/"));
    state.memberships = memberships;
    const shops = memberships.filter((m) => m.tenant_business_type === "barberia");
    if (!shops.length) {
      $("auth-screen").hidden = false;
      $("workspace").hidden = true;
      $("login-form").hidden = true;
      $("register-form").hidden = true;
      const onboarding = $("onboarding-no-shop");
      if (onboarding) {
        onboarding.hidden = false;
        $("onboarding-username").textContent = state.username || "Usuario";
        renderOnboardingBusinesses(memberships);
      }
      return;
    }
    const onboarding = $("onboarding-no-shop");
    if (onboarding) onboarding.hidden = true;
    const savedTenantId = sessionStorage.getItem("barber_tenant");
    const active = shops.find((s) => s.tenant_id === savedTenantId) || shops[0];
    state.tenant = active;
    state.role = active.role;
    sessionStorage.setItem("barber_tenant", active.tenant_id);
    $("shop-name").textContent = state.tenant.tenant_name;
    $("user-name").textContent = state.username;
    document.querySelectorAll(".owner-only").forEach((el) => { el.hidden = !isManager(); });
    $("agenda-date").value = localDateValue();
    $("caja-date").value = localDateValue();
    setScreen("workspace");
    showError("auth-error", "");
    await Promise.all([loadServices(), loadBarbers(), loadCustomers()]);
    showView(state.view);
  }

  // ---------------------------------------------------------------- Carga de datos
  async function loadServices() {
    state.services = getRows(await api("/barbershop/services/"));
    renderServices();
  }
  async function loadBarbers() {
    state.barbers = getRows(await api("/barbershop/barbers/"));
    renderBarbers();
    const select = $("agenda-barber");
    const previous = select.value;
    select.replaceChildren(new Option("Todos los barberos", ""));
    state.barbers.filter((b) => b.is_active).forEach((b) => select.add(new Option(b.full_name, b.id)));
    select.value = state.barbers.some((b) => b.id === previous) ? previous : "";
  }
  async function loadCustomers() {
    state.customers = getRows(await api("/customers/"));
    renderCustomers();
  }
  async function loadAgenda() {
    const params = new URLSearchParams({ date: $("agenda-date").value || localDateValue() });
    if ($("agenda-barber").value) params.set("barber", $("agenda-barber").value);
    state.appointments = getRows(await api(`/barbershop/appointments/?${params}`));
    renderAgenda();
  }

  function showView(view) {
    state.view = view;
    document.querySelectorAll(".view").forEach((el) => { el.hidden = el.id !== `view-${view}`; });
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
    showError("error", "");
    const loaders = { agenda: loadAgenda, caja: loadCaja, clientes: loadCustomers, servicios: loadServices, barberos: loadBarbers };
    Promise.resolve(loaders[view]()).catch((e) => showError("error", e.message));
  }

  // ---------------------------------------------------------------- Agenda
  function renderAgenda() {
    const list = $("agenda-list");
    list.replaceChildren();
    const items = state.appointments;
    $("agenda-empty").hidden = items.length > 0;
    $("stat-pending").textContent = items.filter((a) => OPEN.includes(a.status)).length;
    $("stat-done").textContent = items.filter((a) => a.status === "completed").length;
    $("stat-total").textContent = money(items.reduce((s, a) => s + (a.sale ? Number(a.sale.total) : 0), 0));

    items.forEach((a) => {
      const open = OPEN.includes(a.status);
      const row = document.createElement("article");
      row.className = `row${a.status === "completed" ? " is-done" : ""}${["cancelled", "no_show"].includes(a.status) ? " is-void" : ""}`;
      const services = a.services.map((s) => s.name).join(" + ");
      const wa = whatsappUrl(a.customer.phone,
        `Hola ${a.customer.name}, te esperamos en ${state.tenant.tenant_name} a las ${timeOf(a.starts_at)}.`);
      const amount = a.sale ? a.sale.total : a.total;
      const payInfo = a.sale
        ? `<span>${escapeHtml(METHOD_LABELS[a.sale.payment_method] || a.sale.payment_method)}${Number(a.sale.tip) ? ` · propina ${money(a.sale.tip)}` : ""}</span>`
        : "";
      row.innerHTML =
        `<div class="row-top"><div class="row-main">` +
        `<span class="time-badge">${timeOf(a.starts_at)} – ${timeOf(a.ends_at)}</span>` +
        `<strong>${escapeHtml(a.customer.name)}</strong>` +
        `<span>${escapeHtml(services)}</span>` +
        `<span>✂ ${escapeHtml(a.barber ? a.barber.name : "Sin barbero")}</span>${payInfo}</div>` +
        `<div class="row-amount">${money(amount)}<br><span class="status status-${a.status}">${escapeHtml(STATUS_LABELS[a.status] || a.status)}</span></div></div>` +
        (open || wa
          ? `<div class="row-actions">` +
            (open ? `<button class="btn btn-ok btn-sm" data-act="charge" data-id="${a.id}" type="button">💵 Cobrar</button>` : "") +
            (open ? `<button class="btn btn-ghost btn-sm" data-act="no_show" data-id="${a.id}" type="button">No vino</button>` : "") +
            (open ? `<button class="btn btn-danger btn-sm" data-act="cancel" data-id="${a.id}" type="button">Cancelar</button>` : "") +
            (wa && open ? `<a class="btn btn-ghost btn-sm" target="_blank" rel="noopener" href="${escapeHtml(wa)}">💬 Avisar</a>` : "") +
            `</div>`
          : "");
      list.append(row);
    });
  }

  $("agenda-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-act]");
    if (!button) return;
    const id = button.dataset.id;
    const appointment = state.appointments.find((a) => a.id === id);
    try {
      if (button.dataset.act === "charge") return openCharge(appointment);
      const label = button.dataset.act === "cancel" ? "cancelar esta cita" : "marcar que el cliente no vino";
      if (!window.confirm(`¿Seguro que quieres ${label}?`)) return;
      const action = button.dataset.act === "cancel" ? "cancel" : "no-show";
      await post(`/barbershop/appointments/${id}/${action}/`);
      toast("Cita actualizada.");
      await loadAgenda();
    } catch (error) {
      showError("error", error.message);
    }
  });

  function shiftDay(days) {
    const input = $("agenda-date");
    const d = new Date(`${input.value || localDateValue()}T12:00:00`);
    d.setDate(d.getDate() + days);
    input.value = localDateValue(d);
    loadAgenda().catch((e) => showError("error", e.message));
  }
  $("day-prev").addEventListener("click", () => shiftDay(-1));
  $("day-next").addEventListener("click", () => shiftDay(1));
  $("day-today").addEventListener("click", () => { $("agenda-date").value = localDateValue(); loadAgenda().catch((e) => showError("error", e.message)); });
  $("agenda-date").addEventListener("change", () => loadAgenda().catch((e) => showError("error", e.message)));
  $("agenda-barber").addEventListener("change", () => loadAgenda().catch((e) => showError("error", e.message)));

  // ---------------------------------------------------------------- Nueva cita
  const appointmentDialog = $("appointment-dialog");

  function renderServiceChecks() {
    const box = $("appointment-services");
    box.replaceChildren();
    const active = state.services.filter((s) => s.is_active);
    if (!active.length) {
      box.innerHTML = '<p class="hint">Primero crea tus servicios en la sección «Servicios».</p>';
    }
    active.forEach((s) => {
      const label = document.createElement("label");
      label.className = "service-check";
      label.innerHTML =
        `<input type="checkbox" value="${s.id}"><span>${escapeHtml(s.name)}<small>${s.duration_minutes} min</small></span>` +
        `<strong>${money(s.price)}</strong>`;
      box.append(label);
    });
    updateAppointmentTotals();
  }

  function selectedServices() {
    const ids = [...$("appointment-services").querySelectorAll("input:checked")].map((i) => i.value);
    return state.services.filter((s) => ids.includes(s.id));
  }
  function updateAppointmentTotals() {
    const chosen = selectedServices();
    document.querySelectorAll("#appointment-services .service-check").forEach((label) => {
      label.classList.toggle("is-on", label.querySelector("input").checked);
    });
    const minutes = chosen.reduce((s, x) => s + x.duration_minutes, 0);
    $("appointment-duration").textContent = `${minutes || 30} min`;
    $("appointment-total").textContent = money(chosen.reduce((s, x) => s + Number(x.price), 0));
  }
  $("appointment-services").addEventListener("change", updateAppointmentTotals);

  function openAppointmentDialog(customer) {
    showError("appointment-error", "");
    $("appointment-form").reset();
    const barberSelect = $("appointment-barber");
    barberSelect.replaceChildren();
    const activeBarbers = state.barbers.filter((b) => b.is_active);
    activeBarbers.forEach((b) => barberSelect.add(new Option(b.full_name, b.id)));
    if ($("agenda-barber").value) barberSelect.value = $("agenda-barber").value;
    const date = $("agenda-date").value || localDateValue();
    const now = new Date();
    const start = date === localDateValue() ? localDateTimeValue(now) : `${date}T09:00`;
    $("appointment-start").value = start;
    $("customer-options").replaceChildren(...state.customers.map((c) => new Option(c.phone ? `${c.full_name}` : c.full_name, c.full_name)));
    if (customer) {
      $("appointment-customer").value = customer.full_name;
      $("appointment-phone").value = customer.phone || "";
    }
    if (!activeBarbers.length) showError("appointment-error", "Primero agrega al menos un barbero en la sección «Barberos».");
    renderServiceChecks();
    appointmentDialog.showModal();
  }
  $("new-appointment").addEventListener("click", () => openAppointmentDialog());
  $("appointment-now").addEventListener("click", () => { $("appointment-start").value = localDateTimeValue(new Date()); });
  $("appointment-customer").addEventListener("input", (event) => {
    const match = state.customers.find((c) => c.full_name.toLowerCase() === event.target.value.trim().toLowerCase());
    if (match && !$("appointment-phone").value) $("appointment-phone").value = match.phone || "";
  });

  $("appointment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("appointment-error", "");
    const form = new FormData(event.currentTarget);
    const chosen = selectedServices();
    if (!chosen.length) return showError("appointment-error", "Selecciona al menos un servicio.");
    const name = String(form.get("customer_name") || "").trim();
    const match = state.customers.find((c) => c.full_name.toLowerCase() === name.toLowerCase());
    const payload = {
      barber: form.get("barber"),
      starts_at: new Date(form.get("starts_at")).toISOString(),
      services: chosen.map((s) => s.id),
      notes: String(form.get("notes") || "").trim(),
    };
    if (match) payload.customer = match.id;
    else {
      payload.customer_name = name;
      payload.customer_phone = String(form.get("customer_phone") || "").trim();
    }
    const button = $("appointment-submit");
    busy(button, true, "Guardando…");
    try {
      const created = await post("/barbershop/appointments/", payload);
      appointmentDialog.close();
      $("agenda-date").value = created.starts_at.slice(0, 10);
      toast("Cita guardada.");
      await Promise.all([loadAgenda(), loadCustomers()]);
    } catch (error) {
      showError("appointment-error", error.message);
    } finally {
      busy(button, false);
    }
  });

  // ---------------------------------------------------------------- Cobro
  const chargeDialog = $("charge-dialog");

  function updateChargePreview() {
    const a = state.chargeTarget;
    if (!a) return;
    const tip = Number($("charge-tip").value || 0);
    const subtotal = Number(a.total);
    const barber = state.barbers.find((b) => a.barber && b.id === a.barber.id);
    const percent = barber ? Number(barber.commission_percent) : 0;
    const commission = Math.round(subtotal * percent) / 100;
    $("charge-total").textContent = money(subtotal + tip);
    $("charge-split").textContent =
      `Barbero (${percent}%): ${money(commission + tip)} (incluye propina) · Negocio: ${money(subtotal - commission)}`;
  }

  function openCharge(appointment) {
    state.chargeTarget = appointment;
    showError("charge-error", "");
    $("charge-form").reset();
    $("charge-summary").innerHTML =
      `<strong>${escapeHtml(appointment.customer.name)}</strong>` +
      `<span class="muted">${escapeHtml(appointment.services.map((s) => `${s.name} (${money(s.price)})`).join(" + "))}</span>` +
      `<span class="muted">Subtotal: ${money(appointment.total)}</span>`;
    updateChargePreview();
    chargeDialog.showModal();
  }
  $("charge-tip").addEventListener("input", updateChargePreview);

  $("charge-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const a = state.chargeTarget;
    if (!a) return;
    const button = $("charge-submit");
    busy(button, true, "Cobrando…");
    try {
      await post(`/barbershop/appointments/${a.id}/complete/`, {
        payment_method: $("charge-method").value,
        tip: String(Number($("charge-tip").value || 0)),
      });
      chargeDialog.close();
      toast("Cobro registrado.");
      await loadAgenda();
    } catch (error) {
      showError("charge-error", error.message);
    } finally {
      busy(button, false);
    }
  });

  // ---------------------------------------------------------------- Caja
  async function loadCaja() {
    const params = new URLSearchParams({
      period: $("caja-period").value,
      date: $("caja-date").value || localDateValue(),
    });
    const report = await api(`/barbershop/summary/?${params}`);
    const t = report.totals;
    $("caja-range").textContent = report.start_date === report.end_date
      ? displayDate(report.start_date)
      : `${displayDate(report.start_date)} – ${displayDate(report.end_date)}`;
    const kpis = [
      ["Total cobrado", money(t.collected), "kpi-accent"],
      ["Servicios (ventas)", money(t.subtotal), ""],
      ["Comisión barberos", money(t.commission), ""],
      ["Propinas", money(t.tips), ""],
      ["Neto del negocio", money(t.owner_net), ""],
      ["Atenciones", `${t.services} · ${report.appointments.pending} pend.`, ""],
    ];
    $("caja-kpis").innerHTML = kpis.map(([label, value, cls]) =>
      `<div class="kpi ${cls}"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
    $("caja-rows").innerHTML = report.rows.map((r) =>
      `<tr><td>${escapeHtml(r.barber_name)} <small class="muted">${Number(r.commission_percent)}%</small></td>` +
      `<td>${r.services}</td><td>${money(r.subtotal)}</td><td>${money(r.commission)}</td>` +
      `<td>${money(r.tips)}</td><td><strong>${money(r.barber_pay)}</strong></td><td>${money(r.owner_net)}</td></tr>`).join("")
      || '<tr><td colspan="7" class="muted">Sin barberos todavía.</td></tr>';
    const methods = Object.entries(report.by_method);
    $("caja-methods").innerHTML = methods.length
      ? methods.map(([m, v]) => `<span class="chip">${escapeHtml(METHOD_LABELS[m] || m)}: ${money(v)}</span>`).join("")
      : '<span class="muted">Sin cobros en este período.</span>';
  }
  $("caja-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadCaja().catch((e) => showError("error", e.message));
  });

  // ---------------------------------------------------------------- Clientes
  function renderCustomers() {
    const query = $("customer-search").value.trim().toLowerCase();
    const list = $("customer-list");
    list.replaceChildren();
    const rows = state.customers.filter((c) =>
      !query || c.full_name.toLowerCase().includes(query) || String(c.phone || "").includes(query));
    $("customer-empty").hidden = rows.length > 0;
    rows.forEach((c) => {
      const row = document.createElement("article");
      row.className = "row";
      const wa = whatsappUrl(c.phone, `Hola ${c.full_name}, te escribimos de ${state.tenant ? state.tenant.tenant_name : "la barbería"}.`);
      row.innerHTML =
        `<div class="row-top"><div class="row-main"><strong>${escapeHtml(c.full_name)}</strong>` +
        `<span>${escapeHtml(c.phone || "Sin teléfono")}</span></div>` +
        `<div class="row-actions"><button class="btn btn-quiet btn-sm" data-book="${c.id}" type="button">Agendar</button>` +
        (wa ? `<a class="btn btn-ghost btn-sm" target="_blank" rel="noopener" href="${escapeHtml(wa)}">💬</a>` : "") +
        `</div></div>`;
      list.append(row);
    });
  }
  $("customer-search").addEventListener("input", renderCustomers);
  $("customer-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-book]");
    if (!button) return;
    openAppointmentDialog(state.customers.find((c) => c.id === button.dataset.book));
  });

  // ---------------------------------------------------------------- Servicios
  const serviceDialog = $("service-dialog");
  function renderServices() {
    const list = $("service-list");
    list.replaceChildren();
    $("service-empty").hidden = state.services.length > 0;
    state.services.forEach((s) => {
      const row = document.createElement("article");
      row.className = `row${s.is_active ? "" : " is-void"}`;
      row.innerHTML =
        `<div class="row-top"><div class="row-main"><strong>${escapeHtml(s.name)}</strong>` +
        `<span>${s.duration_minutes} min${s.is_active ? "" : " · No disponible"}</span></div>` +
        `<div class="row-amount">${money(s.price)}</div></div>` +
        (isManager() ? `<div class="row-actions"><button class="btn btn-ghost btn-sm" data-edit-service="${s.id}" type="button">Editar</button></div>` : "");
      list.append(row);
    });
  }
  function openServiceDialog(service) {
    showError("service-error", "");
    const form = $("service-form");
    form.reset();
    $("service-title").textContent = service ? "Editar servicio" : "Nuevo servicio";
    form.elements.id.value = service ? service.id : "";
    if (service) {
      form.elements.name.value = service.name;
      form.elements.price.value = Number(service.price);
      form.elements.duration_minutes.value = service.duration_minutes;
      form.elements.is_active.checked = service.is_active;
    }
    serviceDialog.showModal();
  }
  $("new-service").addEventListener("click", () => openServiceDialog());
  $("service-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-edit-service]");
    if (button) openServiceDialog(state.services.find((s) => s.id === button.dataset.editService));
  });
  $("service-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      name: form.elements.name.value.trim(),
      price: String(form.elements.price.value),
      duration_minutes: Number(form.elements.duration_minutes.value),
      is_active: form.elements.is_active.checked,
    };
    try {
      if (form.elements.id.value) await patch(`/barbershop/services/${form.elements.id.value}/`, payload);
      else await post("/barbershop/services/", payload);
      serviceDialog.close();
      toast("Servicio guardado.");
      await loadServices();
    } catch (error) {
      showError("service-error", error.message);
    }
  });

  // ---------------------------------------------------------------- Barberos
  const barberDialog = $("barber-dialog");
  function renderBarbers() {
    const list = $("barber-list");
    list.replaceChildren();
    $("barber-empty").hidden = state.barbers.length > 0;
    state.barbers.forEach((b) => {
      const row = document.createElement("article");
      row.className = `row${b.is_active ? "" : " is-void"}`;
      row.innerHTML =
        `<div class="row-top"><div class="row-main"><strong>${escapeHtml(b.full_name)}</strong>` +
        `<span>${escapeHtml(b.phone || "Sin teléfono")}${b.is_active ? "" : " · Inactivo"}</span></div>` +
        `<div class="row-amount">${Number(b.commission_percent)}%<br><small class="muted">comisión</small></div></div>` +
        (isManager() ? `<div class="row-actions"><button class="btn btn-ghost btn-sm" data-edit-barber="${b.id}" type="button">Editar</button></div>` : "");
      list.append(row);
    });
  }
  function openBarberDialog(barber) {
    showError("barber-error", "");
    const form = $("barber-form");
    form.reset();
    $("barber-title").textContent = barber ? "Editar barbero" : "Nuevo barbero";
    form.elements.id.value = barber ? barber.id : "";
    if (barber) {
      form.elements.full_name.value = barber.full_name;
      form.elements.phone.value = barber.phone || "";
      form.elements.commission_percent.value = Number(barber.commission_percent);
      form.elements.is_active.checked = barber.is_active;
    }
    barberDialog.showModal();
  }
  $("new-barber").addEventListener("click", () => openBarberDialog());
  $("barber-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-edit-barber]");
    if (button) openBarberDialog(state.barbers.find((b) => b.id === button.dataset.editBarber));
  });
  $("barber-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      full_name: form.elements.full_name.value.trim(),
      phone: form.elements.phone.value.trim(),
      commission_percent: String(form.elements.commission_percent.value),
      is_active: form.elements.is_active.checked,
    };
    try {
      if (form.elements.id.value) await patch(`/barbershop/barbers/${form.elements.id.value}/`, payload);
      else await post("/barbershop/barbers/", payload);
      barberDialog.close();
      toast("Barbero guardado.");
      await loadBarbers();
    } catch (error) {
      showError("barber-error", error.message);
    }
  });

  // ---------------------------------------------------------------- Diálogos
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();
    });
  });

  // ---------------------------------------------------------------- Acceso
  function setAuthMode(register) {
    $("login-form").hidden = register;
    $("register-form").hidden = !register;
    $("tab-login").classList.toggle("is-active", !register);
    $("tab-register").classList.toggle("is-active", register);
    showError("auth-error", "");
  }
  $("tab-login").addEventListener("click", () => setAuthMode(false));
  $("tab-register").addEventListener("click", () => setAuthMode(true));

  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("auth-error", "");
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector("button[type=submit]");
    busy(button, true, "Entrando…");
    try {
      const response = await rawRequest("/auth/login/", {
        method: "POST",
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      }, false);
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(data, "Usuario o contraseña incorrectos."));
      saveSession(data);
      event.currentTarget.reset();
      await enterWorkspace();
    } catch (error) {
      showError("auth-error", error.message);
    } finally {
      busy(button, false);
    }
  });

  $("register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("auth-error", "");
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    const password = String(form.get("password") || "");
    const confirm = String(form.get("password_confirm") || "");
    if (password !== confirm) return showError("auth-error", "Las contraseñas no coinciden.");
    if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      return showError("auth-error", "La contraseña debe tener letras y números.");
    }
    const button = formEl.querySelector("button[type=submit]");
    busy(button, true, "Creando…");
    try {
      const response = await rawRequest("/auth/register/", {
        method: "POST",
        body: JSON.stringify({
          username: String(form.get("username")).trim(),
          email: String(form.get("email")).trim().toLowerCase(),
          full_name: String(form.get("full_name")).trim(),
          password,
          password_confirm: confirm,
          register_role: "owner",
          business_type: "barberia",
          business_name: String(form.get("business_name")).trim(),
        }),
      }, false);
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(data, "No se pudo crear la cuenta."));
      saveSession(data);
      formEl.reset();
      setAuthMode(false);
      await enterWorkspace();
      toast("¡Barbería creada! Empieza agregando tus barberos y servicios.");
      showView("barberos");
    } catch (error) {
      showError("auth-error", error.message);
    } finally {
      busy(button, false);
    }
  });

  document.querySelectorAll(".nav-btn").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  $("logout-button").addEventListener("click", logout);


  // ---------------------------------------------------------------- Negocios / Switcher
  const switchDialog = $("switch-dialog");
  async function openSwitchDialog() {
    if (!switchDialog) return;
    try {
      const memberships = getRows(await api("/auth/me/tenants/"));
      state.memberships = memberships;
      const list = $("switch-business-list");
      list.replaceChildren();
      memberships.forEach((m) => {
        const item = document.createElement("div");
        item.style.cssText = "display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:var(--bg-soft);border-radius:8px;";
        const isCurrent = state.tenant && m.tenant_id === state.tenant.tenant_id;
        const isBarber = m.tenant_business_type === "barberia";
        const badge = isBarber ? "💈 Barbería" : "💰 Préstamos";
        item.innerHTML =
          `<div><strong>${escapeHtml(m.tenant_name)}</strong><br><small style="color:var(--accent);font-weight:600;">${escapeHtml(badge)}</small> · ${escapeHtml(m.role)}</div>` +
          (isCurrent
            ? `<span class="pill" style="align-self:center;">Actual</span>`
            : `<button class="btn btn-ghost btn-sm" type="button">${isBarber ? "Cambiar" : "Abrir ↗"}</button>`);
        if (!isCurrent) {
          item.querySelector("button").addEventListener("click", () => {
            switchDialog.close();
            if (isBarber) {
              sessionStorage.setItem("barber_tenant", m.tenant_id);
              enterWorkspace();
            } else {
              sessionStorage.setItem("loan_tenant", JSON.stringify(m));
              window.location.href = "/loans/";
            }
          });
        }
        list.append(item);
      });
      switchDialog.showModal();
    } catch (e) {
      toast(e.message);
    }
  }

  const btnSwitchBusiness = $("btn-switch-business");
  if (btnSwitchBusiness) btnSwitchBusiness.addEventListener("click", openSwitchDialog);

  const switchCreateForm = $("switch-create-form");
  if (switchCreateForm) {
    switchCreateForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const name = form.elements.name.value.trim();
      const bType = form.elements.business_type.value;
      const button = form.querySelector("button[type=submit]");
      busy(button, true, "Creando…");
      try {
        const res = await post("/tenants/", { name, business_type: bType });
        switchDialog.close();
        toast("Negocio creado exitosamente.");
        if (bType === "barberia") {
          sessionStorage.setItem("barber_tenant", res.tenant ? res.tenant.id : "");
          await enterWorkspace();
        } else {
          sessionStorage.setItem("loan_tenant", JSON.stringify({
            tenant_id: res.tenant.id,
            tenant_name: res.tenant.name,
            role: "owner",
            tenant_currency: res.tenant.currency || "COP",
            tenant_business_type: "prestamista",
          }));
          window.location.href = "/loans/";
        }
      } catch (e) {
        toast(e.message);
      } finally {
        busy(button, false);
      }
    });
  }

  const onboardingCreateForm = $("onboarding-create-form");
  if (onboardingCreateForm) {
    onboardingCreateForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const name = form.elements.name.value.trim();
      const button = form.querySelector("button[type=submit]");
      busy(button, true, "Creando barbería…");
      try {
        const res = await post("/tenants/", { name, business_type: "barberia" });
        sessionStorage.setItem("barber_tenant", res.tenant ? res.tenant.id : "");
        $("onboarding-no-shop").hidden = true;
        toast("¡Barbería creada!");
        await enterWorkspace();
      } catch (e) {
        showError("auth-error", e.message);
      } finally {
        busy(button, false);
      }
    });
  }

  (async function init() {
    if (!state.access) return setScreen("auth");
    try {
      await enterWorkspace();
    } catch (error) {
      logout();
      showError("auth-error", error.message);
    }
  })();
})();
