(() => {
  const app = document.getElementById("loan-app");
  const apiBase = app.dataset.apiBase.replace(/\/$/, "");
  const state = {
    access: sessionStorage.getItem("loan_access"),
    refresh: sessionStorage.getItem("loan_refresh"),
    username: sessionStorage.getItem("loan_username") || "",
    tenant: null,
    currency: "COP",
    role: "",
    loans: [],
    collections: [],
    ledger: null,
    cashSummary: null,
    customerSummary: null,
    employees: [],
    view: "home",
    eventController: null,
    lastEventId: "",
    toastTimer: null,
  };
  const rank = { employee: 1, manager: 2, admin: 3, owner: 4 };
  const labels = {
    daily: "Diario",
    weekly: "Semanal",
    biweekly: "Quincenal",
    monthly: "Mensual",
    active: "Activo",
    pending: "Pendiente",
    delinquent: "Moroso",
    paid: "Pagado",
    cancelled: "Cancelado",
    partial: "Parcial",
  };
  const elements = {
    auth: document.getElementById("auth-screen"),
    tenants: document.getElementById("tenant-screen"),
    workspace: document.getElementById("workspace"),
    notice: document.getElementById("notice"),
    error: document.getElementById("error-notice"),
    loans: document.getElementById("loan-list"),
    collections: document.getElementById("collection-list"),
    ledgerRows: document.getElementById("ledger-rows"),
    dialog: document.getElementById("payment-dialog"),
  };

  function showError(message) {
    elements.notice.hidden = true;
    const target = elements.workspace.hidden
      ? (elements.tenants.hidden ? document.getElementById("auth-error") : document.getElementById("tenant-error"))
      : elements.error;
    target.textContent = message;
    target.hidden = false;
  }

  function showNotice(message) {
    elements.error.hidden = true;
    elements.notice.textContent = message;
    elements.notice.hidden = false;
  }

  function clearMessages() {
    elements.notice.hidden = true;
    elements.error.hidden = true;
    document.getElementById("auth-error").hidden = true;
    document.getElementById("tenant-error").hidden = true;
    document.getElementById("auth-status").hidden = true;
    document.getElementById("tenant-status").hidden = true;
  }

  function errorMessage(data, fallback) {
    if (!data) return fallback;
    if (typeof data === "string") return data;
    if (data.detail) return data.detail;
    const first = Object.values(data).flat(Infinity).find((value) => typeof value === "string");
    return first || fallback;
  }

  async function rawRequest(path, options = {}, authenticated = true) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (authenticated && state.access) headers.set("Authorization", `Bearer ${state.access}`);
    if (authenticated && state.tenant) headers.set("X-Tenant-ID", state.tenant.tenant_id);
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
    sessionStorage.setItem("loan_access", data.access);
    if (data.refresh) {
      state.refresh = data.refresh;
      sessionStorage.setItem("loan_refresh", data.refresh);
    }
    return true;
  }

  async function api(path, options = {}) {
    let response = await rawRequest(path, options);
    if (response.status === 401 && state.refresh && await refreshToken()) {
      response = await rawRequest(path, options);
    }
    if (response.status === 401) {
      logout(false);
      throw new Error("Tu sesión expiró. Ingresa nuevamente.");
    }
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new Error(errorMessage(data, "No se pudo completar la solicitud."));
    return data;
  }

  function getRows(data) {
    return Array.isArray(data) ? data : (data && Array.isArray(data.results) ? data.results : []);
  }

  function money(value) {
    const amount = Number(value || 0);
    return new Intl.NumberFormat("es-CO", {
      style: "currency",
      currency: state.currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(Number.isFinite(amount) ? amount : 0);
  }

  function localDateValue(date = new Date()) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function displayDate(value) {
    if (!value) return "";
    const [year, month, day] = value.split("-").map(Number);
    return new Intl.DateTimeFormat("es-CO", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(new Date(year, month - 1, day));
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function initials(name) {
    return String(name || "C")
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0] || "")
      .join("")
      .toUpperCase();
  }

  function statusClass(status) {
    return `status-${String(status || "pending").toLowerCase()}`;
  }

  function setBusy(button, busy, text) {
    if (busy) {
      button.dataset.originalText = button.innerHTML;
      button.disabled = true;
      button.textContent = text;
    } else {
      button.disabled = false;
      if (button.dataset.originalText) button.innerHTML = button.dataset.originalText;
      delete button.dataset.originalText;
    }
  }

  function setScreen(screen) {
    elements.auth.hidden = screen !== "auth";
    elements.tenants.hidden = screen !== "tenants";
    elements.workspace.hidden = screen !== "workspace";
  }

  async function login(username, password) {
    const response = await rawRequest("/auth/login/", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }, false);
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(errorMessage(data, "Usuario o contraseña incorrectos."));
    state.access = data.access;
    state.refresh = data.refresh;
    state.username = username;
    sessionStorage.setItem("loan_access", state.access);
    sessionStorage.setItem("loan_refresh", state.refresh);
    sessionStorage.setItem("loan_username", username);
    await loadTenants();
  }

  async function loadTenants() {
    try {
      const memberships = getRows(await api("/auth/me/tenants/"));
      if (!memberships.length) {
        setScreen("tenants");
        document.getElementById("tenant-options").innerHTML =
          '<p class="muted">Tu usuario todavía no tiene una empresa activa. Si ya solicitaste acceso con un código, espera la aprobación del propietario.</p>';
        return;
      }
      const options = document.getElementById("tenant-options");
      options.replaceChildren();
      memberships.forEach((membership) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "tenant-choice";
        button.innerHTML =
          `<div><strong>${escapeHtml(membership.tenant_name)}</strong>` +
          `<span>${escapeHtml(membership.role)}</span></div><span aria-hidden="true">→</span>`;
        button.addEventListener("click", () => openWorkspace(membership));
        options.append(button);
      });
      setScreen("tenants");
    } catch (error) {
      setScreen("auth");
      showError(error.message);
    }
  }

  async function openWorkspace(membership) {
    state.tenant = membership;
    state.role = membership.role;
    state.currency = membership.tenant_currency || "COP";
    sessionStorage.setItem("loan_tenant", JSON.stringify(membership));
    setScreen("workspace");
    const displayName = state.username || membership.username || "Tu cuenta";
    document.getElementById("sidebar-user-name").textContent = displayName;
    document.getElementById("sidebar-tenant-name").textContent = membership.tenant_name;
    document.getElementById("topbar-tenant-name").textContent = membership.tenant_name;
    document.getElementById("sidebar-avatar").textContent = initials(displayName);
    document.getElementById("topbar-avatar").textContent = initials(displayName);
    const isOwner = state.role === "owner";
    document.getElementById("ledger-nav").hidden = !isOwner;
    document.getElementById("mobile-ledger-nav").hidden = !isOwner;
    document.getElementById("mobile-cashflow-nav").hidden = false;
    document.getElementById("mobile-customer-nav").hidden = false;
    document.getElementById("employee-requests-nav").hidden = !isOwner;
    document.getElementById("mobile-employee-requests-nav").hidden = !isOwner;
    document.getElementById("today-label").textContent = new Intl.DateTimeFormat("es", {
      weekday: "long",
      day: "numeric",
      month: "long",
    }).format(new Date()).toUpperCase();
    const today = new Date();
    document.getElementById("start-date").value = localDateValue(today);
    document.getElementById("ledger-date").value = localDateValue(today);
    ["cash-date", "cash-opening-date", "expense-date"].forEach((id) => {
      document.getElementById(id).value = localDateValue(today);
    });
    clearMessages();
    await loadDashboard();
    if ((rank[state.role] || 0) >= rank.manager) await loadEmployees();
    if ((rank[state.role] || 0) >= rank.admin) startPaymentStream();
    showView(state.view);
  }

  async function loadEmployees() {
    try {
      state.employees = getRows(await api("/employees/"));
      populateCollectors();
    } catch (error) {
      showError(`No se pudo cargar la lista de cobradores: ${error.message}`);
    }
  }

  function populateCollectors() {
    const loanSelect = document.getElementById("loan-collector");
    const paymentSelect = document.getElementById("payment-collector");
    const openingSelect = document.getElementById("cash-opening-collector");
    const expenseSelect = document.getElementById("expense-collector");
    const selectedLoanCollector = loanSelect.value;
    loanSelect.replaceChildren(new Option("Sin asignar", ""));
    paymentSelect.replaceChildren(new Option("Selecciona un cobrador", ""));
    openingSelect.replaceChildren(new Option("Selecciona un cobrador", ""));
    expenseSelect.replaceChildren(new Option("Selecciona un cobrador", ""));
    state.employees.forEach((employee) => {
      const label = employee.full_name || employee.email || `Cobrador ${employee.id}`;
      loanSelect.add(new Option(label, employee.id));
      paymentSelect.add(new Option(label, employee.id));
      openingSelect.add(new Option(label, employee.id));
      expenseSelect.add(new Option(label, employee.id));
    });
    loanSelect.value = selectedLoanCollector;
    const manager = (rank[state.role] || 0) >= rank.manager;
    document.getElementById("collector-field").hidden = !manager;
    document.getElementById("payment-collector-field").hidden = !manager;
    document.getElementById("cash-opening-collector-field").hidden = !manager;
    document.getElementById("expense-collector-field").hidden = !manager;
    openingSelect.required = manager;
    expenseSelect.required = manager;
  }

  async function loadDashboard() {
    clearMessages();
    try {
      const [loanData, collectionData] = await Promise.all([
        api("/loans/"),
        api("/loans/collection-today/"),
      ]);
      state.loans = getRows(loanData);
      state.collections = getRows(collectionData);
      renderLoans();
      renderCollections();
      const activeLoans = state.loans.filter((loan) => !["paid", "cancelled"].includes(loan.status));
      document.getElementById("total-balance").textContent =
        money(activeLoans.reduce((total, loan) => total + Number(loan.balance || 0), 0));
      document.getElementById("active-count").textContent = activeLoans.length;
      document.getElementById("loan-count").textContent = state.loans.length;
      document.getElementById("today-count").textContent = state.collections.length;
      document.getElementById("collection-pill").textContent =
        `${state.collections.length} ${state.collections.length === 1 ? "pendiente" : "pendientes"}`;
    } catch (error) {
      showError(error.message);
    }
  }

  function renderLoans() {
    elements.loans.replaceChildren();
    document.getElementById("loans-empty").hidden = state.loans.length > 0;
    state.loans.forEach((loan) => {
      const row = document.createElement("article");
      row.className = "loan-row";
      const name = loan.customer_name || "Cliente";
      const paymentPlan = loan.is_open_ended
        ? "Abierto"
        : `${Number(loan.installments || 0)} cuotas`;
      const collectionSummary = Number(loan.collection_amount || 0) > 0
        ? `Cuota ${money(loan.collection_amount)} · ${escapeHtml(labels[loan.frequency] || loan.frequency)}`
        : paymentPlan;
      const nextInstallment = (loan.installment_schedule || [])
        .find((installment) => Number(installment.amount_paid) < Number(installment.amount_due));
      const suggested = nextInstallment
        ? Math.min(Number(nextInstallment.amount_due) - Number(nextInstallment.amount_paid), Number(loan.balance))
        : Number(loan.balance);
      row.innerHTML =
        `<div class="loan-person"><span class="customer-avatar">${escapeHtml(initials(name))}</span>` +
        `<div><strong>${escapeHtml(name)}</strong><span>${escapeHtml(loan.neighborhood || "Sin barrio")}</span>` +
        `<span>${escapeHtml(loan.document_id || "Sin cédula")}</span></div></div>` +
        `<div class="loan-detail"><strong>${money(loan.balance)}</strong>` +
        `<span>Total ${money(loan.total_payable)} · Abono ${money(Number(loan.total_payable) - Number(loan.balance))}</span>` +
        `<span>Papelería ${money(loan.paperwork_fee)} aparte</span></div>` +
        `<div class="loan-detail"><strong>${collectionSummary}</strong><span>${paymentPlan}</span></div>` +
        `<button class="loan-action" type="button" data-payment-loan="${escapeHtml(loan.id)}" ` +
        `data-payment-name="${escapeHtml(name)}" data-payment-suggested="${escapeHtml(suggested)}">Registrar pago</button>` +
        `<span class="status-pill ${statusClass(loan.status)}">${escapeHtml(labels[loan.status] || loan.status)}</span>`;
      elements.loans.append(row);
    });
  }

  function renderCollections() {
    elements.collections.replaceChildren();
    document.getElementById("collections-empty").hidden = state.collections.length > 0;
    state.collections.forEach((installment) => {
      const row = document.createElement("article");
      row.className = "loan-row";
      const name = installment.customer_name || "Cliente";
      const pending = installment.pending_amount ??
        (Number(installment.amount_due || 0) - Number(installment.amount_paid || 0));
      const overdue = Boolean(installment.is_overdue);
      const collectionType = installment.is_open_ended
        ? `Cuota ${escapeHtml(installment.number)} · ${escapeHtml(labels[installment.frequency] || installment.frequency)}`
        : `Cuota ${escapeHtml(installment.number)}`;
      row.innerHTML =
        `<div class="loan-person"><span class="customer-avatar">${escapeHtml(initials(name))}</span>` +
        `<div><strong>${escapeHtml(name)}</strong><span>${collectionType} · ` +
        `${escapeHtml(installment.due_date)}</span></div></div>` +
        `<div class="loan-detail"><strong>${money(pending)}</strong><span>Saldo de cuota</span></div>` +
        `<div class="loan-detail"><strong>${money(installment.amount_due)}</strong><span>Cuota completa</span></div>` +
        `<button class="loan-action" type="button" data-payment-loan="${escapeHtml(installment.loan)}" ` +
        `data-payment-name="${escapeHtml(name)}" data-payment-suggested="${escapeHtml(pending)}">Cobrar</button>` +
        `<span class="status-pill ${overdue ? "status-delinquent" : "status-active"}">` +
        `${overdue ? "Vencida" : "Pendiente"}</span>`;
      elements.collections.append(row);
    });
  }



  async function loadEmployeeRequests() {
    const container = document.getElementById("employee-request-list");
    try {
      const requests = getRows(await api("/tenant-join-requests/manage/"));
      document.getElementById("employee-requests-empty").hidden = requests.length > 0;
      container.replaceChildren();
      requests.forEach((item) => {
        const row = document.createElement("article");
        row.className = "loan-row employee-request-row";
        const name = item.full_name || item.username || "Usuario";
        row.innerHTML =
          `<div class="loan-person"><span class="customer-avatar">${escapeHtml(initials(name))}</span>` +
          `<div><strong>${escapeHtml(name)}</strong><span>${escapeHtml(item.email)}</span>` +
          `<span>Solicitud ${escapeHtml(displayDate(String(item.created_at || "").slice(0, 10)))}</span></div></div>` +
          `<div class="loan-detail"><strong>Acceso como cobrador</strong><span>Solo se habilita al aprobar</span></div>` +
          `<div class="employee-request-actions"><button class="button button-primary" type="button" data-request-accept="${escapeHtml(item.id)}">Aceptar</button>` +
          `<button class="button button-quiet" type="button" data-request-reject="${escapeHtml(item.id)}">Rechazar</button></div>`;
        container.append(row);
      });
    } catch (error) {
      showError(error.message);
    }
  }

  async function decideEmployeeRequest(requestId, decision, button) {
    setBusy(button, true, decision === "accept" ? "Aceptando…" : "Rechazando…");
    try {
      await api("/tenant-join-requests/manage/", {
        method: "POST",
        body: JSON.stringify({ request_id: requestId, decision }),
      });
      await loadEmployeeRequests();
      await loadEmployees();
      showToast(decision === "accept" ? "Cobrador aceptado en el negocio." : "Solicitud rechazada.");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  }

  async function loadCashSummary() {
    const form = document.getElementById("cash-summary-filters");
    const params = new URLSearchParams({
      period: form.elements.period.value,
      date: form.elements.date.value || localDateValue(),
    });
    const button = document.getElementById("cash-summary-search");
    setBusy(button, true, "Consultando…");
    try {
      const report = await api(`/collector-cash-summary/?${params.toString()}`);
      state.cashSummary = report;
      const totals = report.totals || {};
      document.getElementById("cash-opening-total").textContent = money(totals.opening_cash);
      document.getElementById("cash-collected-total").textContent = money(totals.collected);
      document.getElementById("cash-expenses-total").textContent = money(totals.expenses);
      document.getElementById("cash-principal-total").textContent = money(totals.principal_lent);
      document.getElementById("cash-paperwork-total").textContent = money(totals.paperwork);
      document.getElementById("cash-expected-total").textContent = money(totals.expected_cash);
      document.getElementById("cash-summary-rows").innerHTML = (report.rows || []).map((row) =>
        `<tr><td>${escapeHtml(row.collector_name)}</td><td>${money(row.opening_cash)}</td>` +
        `<td>${money(row.collected)}</td><td>${money(row.expenses)}</td>` +
        `<td>${money(row.principal_lent)}</td><td>${money(row.paperwork)}</td>` +
        `<td><strong>${money(row.expected_cash)}</strong></td></tr>`
      ).join("");
      await loadExpenses(report.start_date, report.end_date);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  }

  async function loadExpenses(start, end) {
    const params = new URLSearchParams();
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    const expenses = getRows(await api(`/collector-expenses/?${params.toString()}`));
    const labelsByCategory = {
      transport: "Transporte", food: "Alimentación", supplies: "Papelería e insumos", other: "Otro",
    };
    document.getElementById("expense-rows").innerHTML = expenses.map((expense) =>
      `<tr><td>${escapeHtml(displayDate(expense.spent_on))}</td>` +
      `<td>${escapeHtml(expense.collector_name || "")}</td>` +
      `<td>${escapeHtml(labelsByCategory[expense.category] || expense.category)}</td>` +
      `<td>${escapeHtml(expense.description)}</td><td>${money(expense.amount)}</td></tr>`
    ).join("");
    document.getElementById("expenses-empty").hidden = expenses.length > 0;
  }

  async function loadCustomerSummary() {
    const form = document.getElementById("customer-summary-filters");
    const params = new URLSearchParams();
    if (form.elements.search.value.trim()) params.set("search", form.elements.search.value.trim());
    if (form.elements.start.value) params.set("start", form.elements.start.value);
    if (form.elements.end.value) params.set("end", form.elements.end.value);
    const button = document.getElementById("customer-summary-button");
    setBusy(button, true, "Buscando…");
    try {
      const report = await api(`/customer-loan-summary/?${params.toString()}`);
      state.customerSummary = report;
      const rows = report.rows || [];
      document.getElementById("customer-summary-empty").hidden = rows.length > 0;
      document.getElementById("customer-summary-rows").innerHTML = rows.map((customer) => {
        const loans = (customer.loans || []).map((loan) => {
          const installments = (loan.installments || []).map((installment) =>
            `<tr><td>${escapeHtml(installment.number)}</td><td>${escapeHtml(displayDate(installment.due_date))}</td>` +
            `<td>${money(installment.amount_due)}</td><td>${money(installment.amount_paid)}</td>` +
            `<td>${money(installment.pending_amount)}</td><td>${escapeHtml(labels[installment.status] || installment.status)}</td></tr>`
          ).join("");
          return `<section class="amortization-loan"><h4>Préstamo ${escapeHtml(loan.date)} · ${escapeHtml(labels[loan.frequency] || loan.frequency)}</h4>` +
            `<p>Capital ${money(loan.principal)} · Interés ${money(loan.interest)} · Papelería ${money(loan.paperwork)} · Saldo ${money(loan.balance)}</p>` +
            `<div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>CUOTA</th><th>VENCIMIENTO</th><th>VALOR</th><th>PAGADO</th><th>PENDIENTE</th><th>ESTADO</th></tr></thead><tbody>${installments}</tbody></table></div></section>`;
        }).join("");
        return `<tr><td><strong>${escapeHtml(customer.customer_name)}</strong></td><td>${escapeHtml(customer.loan_count)}</td>` +
          `<td>${money(customer.principal)}</td><td>${money(customer.paperwork)}</td><td>${money(customer.interest)}</td>` +
          `<td>${money(customer.total_payable)}</td><td>${money(customer.collected)}</td><td><strong>${money(customer.balance)}</strong></td>` +
          `<td><details class="amortization-details"><summary>Ver amortización</summary>${loans || "<p>Sin detalle de préstamos.</p>"}</details></td></tr>`;
      }).join("");
      const totals = report.totals || {};
      document.getElementById("customer-summary-totals").innerHTML = rows.length
        ? `<tr><th>TOTALES</th><td>${escapeHtml(totals.loan_count || 0)}</td><td>${money(totals.principal)}</td>` +
          `<td>${money(totals.paperwork)}</td><td>${money(totals.interest)}</td><td>${money(totals.total_payable)}</td>` +
          `<td>${money(totals.collected)}</td><td>${money(totals.balance)}</td><td></td></tr>`
        : "";
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  }

  function showView(view) {
    if ((view === "ledger" || view === "employee-requests") && state.role !== "owner") view = "home";
    state.view = view;
    const titles = {
      home: ["Resumen", "Una mirada clara a tus préstamos."],
      collections: ["Cobros de hoy", "Cuotas pendientes de tu cartera."],
      ledger: ["Libro de cartera", "Consulta el formato del Excel por período y frecuencia."],
      cashflow: ["Caja y gastos", "Controla el dinero inicial, los cobros, los préstamos y los gastos."],
      "customer-summary": ["Resumen por cliente", "Consulta la cartera consolidada y el detalle de amortización."],
      "employee-requests": ["Solicitudes de empleados", "Aprueba o rechaza las solicitudes de acceso al negocio."],
      "new-loan": ["Nuevo préstamo", "Registra un cliente y define su frecuencia de cobro."],
    };
    document.getElementById("view-title").textContent = titles[view][0];
    document.getElementById("view-subtitle").textContent = titles[view][1];
    document.querySelectorAll(".view-panel").forEach((panel) => {
      panel.hidden = panel.id !== `${view}-view`;
    });
  
  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");
  const registerToggle = document.getElementById("show-register");

  function toggleRegistration(show) {
    loginForm.hidden = show;
    loginForm.querySelectorAll("input, button").forEach((field) => { field.disabled = show; });
    registerForm.hidden = !show;
    registerForm.querySelectorAll("input, button").forEach((field) => { field.disabled = !show; });
    registerToggle.hidden = show;
    document.getElementById("login-title").innerHTML = show
      ? "Crea tu cuenta<br>de cobrador."
      : "Tus préstamos,<br>más cerca.";
  }

  registerToggle.addEventListener("click", () => toggleRegistration(true));
  document.getElementById("cancel-register").addEventListener("click", () => toggleRegistration(false));

  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessages();
    const button = registerForm.querySelector('button[type="submit"]');
    const form = new FormData(registerForm);
    const username = String(form.get("username") || "").trim();
    const password = String(form.get("password") || "");
    const joinCode = String(form.get("join_code") || "").trim().toUpperCase();
    setBusy(button, true, "Creando cuenta…");
    try {
      const registration = await rawRequest("/auth/register/", {
        method: "POST",
        body: JSON.stringify({
          username,
          email: String(form.get("email") || "").trim(),
          full_name: String(form.get("full_name") || "").trim(),
          password,
        }),
      }, false);
      const registrationData = await registration.json().catch(() => null);
      if (!registration.ok) throw new Error(errorMessage(registrationData, "No se pudo crear la cuenta."));
      const loginResponse = await rawRequest("/auth/login/", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }, false);
      const loginData = await loginResponse.json().catch(() => null);
      if (!loginResponse.ok) throw new Error(errorMessage(loginData, "La cuenta se creó, pero no fue posible iniciar sesión."));
      state.access = loginData.access;
      state.refresh = loginData.refresh;
      state.username = username;
      state.tenant = null;
      sessionStorage.setItem("loan_access", state.access);
      sessionStorage.setItem("loan_refresh", state.refresh);
      sessionStorage.setItem("loan_username", username);
      const joinResponse = await rawRequest("/tenant-join-requests/", {
        method: "POST",
        body: JSON.stringify({ join_code: joinCode }),
      });
      const joinData = await joinResponse.json().catch(() => null);
      setScreen("tenants");
      if (!joinResponse.ok) {
        document.getElementById("tenant-options").innerHTML =
          '<p class="muted">Tu cuenta está creada. Corrige el código o solicita acceso a otro negocio.</p>';
        showError(errorMessage(joinData, "No se pudo enviar la solicitud de acceso."));
        toggleRegistration(false);
        registerForm.reset();
        return;
      }
      registerForm.reset();
      loginForm.reset();
      document.getElementById("tenant-options").innerHTML =
        '<p class="muted">Solicitud enviada. Podrás entrar al negocio cuando el propietario la acepte.</p>';
      document.getElementById("tenant-join-code").value = "";
      document.getElementById("tenant-status").textContent = "Cuenta creada y solicitud enviada al propietario.";
      document.getElementById("tenant-status").hidden = false;
      toggleRegistration(false);
    } catch (error) {
      setScreen("auth");
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  document.getElementById("tenant-join-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessages();
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector('button[type="submit"]');
    setBusy(button, true, "Enviando…");
    try {
      const response = await rawRequest("/tenant-join-requests/", {
        method: "POST",
        body: JSON.stringify({ join_code: String(form.get("join_code") || "").trim().toUpperCase() }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(data, "No se pudo enviar la solicitud."));
      event.currentTarget.reset();
      document.getElementById("tenant-status").textContent =
        `Solicitud enviada a ${data.tenant_name}. Espera la aprobación del propietario.`;
      document.getElementById("tenant-status").hidden = false;
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  document.getElementById("cash-summary-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadCashSummary();
  });
  document.getElementById("customer-summary-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadCustomerSummary();
  });

  document.getElementById("cash-opening-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const data = {
      date: form.get("date"),
      opening_amount: form.get("opening_amount"),
      notes: form.get("notes") || "",
    };
    if ((rank[state.role] || 0) >= rank.manager) data.collector = form.get("collector");
    setBusy(button, true, "Guardando…");
    try {
      await api("/collector-daily-cash/", { method: "POST", body: JSON.stringify(data) });
      event.currentTarget.reset();
      document.getElementById("cash-opening-date").value = localDateValue();
      await loadCashSummary();
      showToast("Dinero inicial registrado.");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  document.getElementById("expense-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const data = {
      spent_on: form.get("spent_on"),
      category: form.get("category"),
      description: String(form.get("description") || "").trim(),
      amount: form.get("amount"),
      notes: form.get("notes") || "",
    };
    if ((rank[state.role] || 0) >= rank.manager) data.collector = form.get("collector");
    setBusy(button, true, "Guardando…");
    try {
      await api("/collector-expenses/", { method: "POST", body: JSON.stringify(data) });
      event.currentTarget.reset();
      document.getElementById("expense-date").value = localDateValue();
      await loadCashSummary();
      showToast("Gasto registrado.");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  document.querySelectorAll("[data-view]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.view === view);
    });
    if (view === "new-loan" && (rank[state.role] || 0) >= rank.manager && !state.employees.length) {
      loadEmployees();
    }
    if (view === "ledger") loadLedger();
    if (view === "cashflow") loadCashSummary();
    if (view === "customer-summary") loadCustomerSummary();
    if (view === "employee-requests") loadEmployeeRequests();
    clearMessages();
  }

  async function loadLedger() {
    const form = document.getElementById("ledger-filters");
    const button = document.getElementById("ledger-search");
    const params = new URLSearchParams({
      period: form.elements.period.value,
      date: form.elements.date.value,
      frequency: form.elements.frequency.value,
    });
    setBusy(button, true, "Consultando…");
    try {
      const report = await api(`/loans/ledger/?${params.toString()}`);
      state.ledger = report;
      const rows = Array.isArray(report.rows) ? report.rows : [];
      document.getElementById("ledger-period-label").textContent =
        `${displayDate(report.period_start)} – ${displayDate(report.period_end)}`;
      document.getElementById("ledger-empty").hidden = rows.length > 0;
      elements.ledgerRows.innerHTML = rows.map((row) => (
        `<tr><td>${escapeHtml(row.item)}</td><td>${escapeHtml(displayDate(row.date))}</td>` +
        `<td>${escapeHtml(row.day)}</td><td>${escapeHtml(row.customer)}</td>` +
        `<td>${escapeHtml(row.neighborhood || "")}</td><td>${escapeHtml(row.concept)}</td>` +
        `<td>${money(row.principal)}</td><td>${money(row.paperwork_fee)}</td>` +
        `<td>${money(row.interest)}</td><td>${money(row.total_payable)}</td>` +
        `<td>${money(row.abono)}</td><td>${money(row.collected)}</td>` +
        `<td>${money(row.remaining)}</td></tr>`
      )).join("");
      const totals = report.totals;
      document.getElementById("ledger-totals").innerHTML = rows.length
        ? `<tr><th colspan="6">TOTALES</th><td>${money(totals.principal)}</td>` +
          `<td>${money(totals.paperwork_fee)}</td><td>${money(totals.interest)}</td>` +
          `<td>${money(totals.total_payable)}</td><td>${money(totals.abono)}</td>` +
          `<td>${money(totals.collected)}</td><td>${money(totals.remaining)}</td></tr>`
        : "";
    } catch (error) {
      elements.ledgerRows.replaceChildren();
      document.getElementById("ledger-totals").replaceChildren();
      document.getElementById("ledger-empty").hidden = false;
      showError(`No se pudo cargar el libro de cartera: ${error.message}`);
    } finally {
      setBusy(button, false);
    }
  }

  function openPayment(button) {
    const loanId = button.dataset.paymentLoan;
    const loan = state.loans.find((item) => String(item.id) === String(loanId));
    const balance = Number((loan && loan.balance) || 0);
    const suggested = Math.min(
      Number(button.dataset.paymentSuggested || balance),
      balance,
    );
    document.getElementById("payment-loan-id").value = loanId;
    document.getElementById("payment-customer").textContent = button.dataset.paymentName || "Cliente";
    document.getElementById("payment-amount").value = suggested > 0 ? suggested.toFixed(2) : "";
    document.getElementById("payment-amount").max = balance.toFixed(2);
    document.getElementById("payment-balance").textContent = money(balance);
    document.getElementById("payment-suggestion").textContent =
      suggested > 0
        ? `Cuota sugerida: ${money(suggested)}. Puedes cambiarla por el valor recibido.`
        : "No hay saldo pendiente para cobrar.";
    if ((rank[state.role] || 0) >= rank.manager) {
      document.getElementById("payment-collector-field").hidden = false;
      document.getElementById("payment-collector").required = true;
    } else {
      document.getElementById("payment-collector-field").hidden = true;
      document.getElementById("payment-collector").required = false;
    }
    elements.dialog.showModal();
  }

  function startPaymentStream() {
    if (state.eventController) state.eventController.abort();
    state.eventController = new AbortController();
    const { signal } = state.eventController;
    const connect = async () => {
      let delay = 1500;
      while (!signal.aborted && state.tenant) {
        try {
          const headers = new Headers({
            Authorization: `Bearer ${state.access}`,
            "X-Tenant-ID": state.tenant.tenant_id,
          });
          if (state.lastEventId) headers.set("Last-Event-ID", state.lastEventId);
          const response = await fetch(`${apiBase}/loan-payment-events/stream/`, {
            headers,
            signal,
          });
          if (response.status === 401 && await refreshToken()) continue;
          if (!response.ok || !response.body) throw new Error("No fue posible conectar las actualizaciones.");
          delay = 1500;
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let boundary = buffer.indexOf("\n\n");
            while (boundary !== -1) {
              const block = buffer.slice(0, boundary);
              buffer = buffer.slice(boundary + 2);
              handleStreamBlock(block);
              boundary = buffer.indexOf("\n\n");
            }
          }
        } catch (error) {
          if (signal.aborted) return;
          await new Promise((resolve) => window.setTimeout(resolve, delay));
          delay = Math.min(delay * 2, 15000);
        }
      }
    };
    connect();
  }

  function handleStreamBlock(block) {
    let eventName = "";
    let data = "";
    block.split(/\r?\n/).forEach((line) => {
      if (line.startsWith("id:")) state.lastEventId = line.slice(3).trim();
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      if (line.startsWith("data:")) data += line.slice(5).trim();
    });
    if (eventName !== "loan.payment_received" || !data) return;
    const event = JSON.parse(data);
    const payload = event.payload || {};
    showToast(`Nuevo cobro recibido: ${money(payload.amount)}.`);
    loadDashboard();
  }

  function showToast(message) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => { toast.hidden = true; }, 4500);
  }

  function logout(showLogin = true) {
    if (state.eventController) state.eventController.abort();
    state.eventController = null;
    ["loan_access", "loan_refresh", "loan_email", "loan_username", "loan_tenant"].forEach((key) => sessionStorage.removeItem(key));
    state.access = null;
    state.refresh = null;
    state.username = "";
    state.tenant = null;
    state.role = "";
    state.loans = [];
    state.collections = [];
    if (showLogin) setScreen("auth");
  }

  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessages();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    setBusy(button, true, "Ingresando…");
    try {
      const form = new FormData(event.currentTarget);
      await login(form.get("username"), form.get("password"));
    } catch (error) {
      setScreen("auth");
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  document.getElementById("refresh-button").addEventListener("click", loadDashboard);
  document.getElementById("refresh-employee-requests").addEventListener("click", loadEmployeeRequests);
  document.addEventListener("click", (event) => {
    const accept = event.target.closest("[data-request-accept]");
    const reject = event.target.closest("[data-request-reject]");
    if (accept) decideEmployeeRequest(accept.dataset.requestAccept, "accept", accept);
    if (reject) decideEmployeeRequest(reject.dataset.requestReject, "reject", reject);
  });
  document.getElementById("logout-button").addEventListener("click", () => logout());
  document.getElementById("topbar-avatar").addEventListener("click", () => logout());
  document.getElementById("mobile-logout").addEventListener("click", () => logout());
  document.getElementById("tenant-logout").addEventListener("click", () => logout());

  const neighborhoodSelect = document.getElementById("customer-neighborhood");
  const otherNeighborhood = document.getElementById("customer-other-neighborhood");
  function syncOtherNeighborhood() {
    const isOther = neighborhoodSelect.value === "__other__";
    otherNeighborhood.hidden = !isOther;
    otherNeighborhood.required = isOther;
    if (!isOther) otherNeighborhood.value = "";
  }
  neighborhoodSelect.addEventListener("change", syncOtherNeighborhood);

  function updateLoanEstimate() {
    const principal = Number(document.getElementById("principal").value || 0);
    const rate = Number(document.getElementById("interest-rate").value || 0);
    const total = principal + principal * rate / 100;
    document.getElementById("preview-total").textContent = money(total);
  }
  ["principal", "interest-rate"].forEach((id) => {
    document.getElementById(id).addEventListener("input", updateLoanEstimate);
  });
  document.getElementById("frequency").addEventListener("change", (event) => {
    document.getElementById("preview-frequency").textContent =
      labels[event.currentTarget.value] || event.currentTarget.value;
  });

  document.getElementById("loan-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    clearMessages();
    const button = document.getElementById("create-loan-button");
    const form = new FormData(event.currentTarget);
    const selectedNeighborhood = form.get("neighborhood");
    const data = {
      customer_details: {
        full_name: form.get("full_name").trim(),
        document_id: form.get("document_id").trim(),
        neighborhood: selectedNeighborhood === "__other__"
          ? otherNeighborhood.value.trim()
          : selectedNeighborhood,
      },
      principal: form.get("principal"),
      interest_rate: form.get("interest_rate"),
      is_open_ended: true,
      paperwork_fee: form.get("paperwork_fee") || "0",
      frequency: form.get("frequency"),
      start_date: form.get("start_date"),
    };
    if (form.get("collector")) data.collector = form.get("collector");
    setBusy(button, true, "Guardando…");
    try {
      const loan = await api("/loans/", { method: "POST", body: JSON.stringify(data) });
      formElement.reset();
      syncOtherNeighborhood();
      document.getElementById("start-date").value = new Date().toISOString().slice(0, 10);
      document.getElementById("preview-frequency").textContent =
        labels[document.getElementById("frequency").value];
      updateLoanEstimate();
      await loadDashboard();
      showView("home");
      showNotice(`Préstamo creado para ${loan.customer_name || data.customer_details.full_name}.`);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  document.getElementById("ledger-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadLedger();
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-payment-loan]");
    if (button) openPayment(button);
  });
  document.getElementById("close-payment").addEventListener("click", () => elements.dialog.close());
  document.getElementById("cancel-payment").addEventListener("click", () => elements.dialog.close());
  elements.dialog.addEventListener("click", (event) => {
    if (event.target === elements.dialog) elements.dialog.close();
  });
  document.getElementById("payment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("submit-payment");
    const loanId = document.getElementById("payment-loan-id").value;
    const payment = {
      loan: loanId,
      amount: document.getElementById("payment-amount").value,
      method: document.getElementById("payment-method").value,
    };
    const collector = document.getElementById("payment-collector").value;
    if ((rank[state.role] || 0) >= rank.manager) {
      if (!collector) {
        showToast("Selecciona quién recibió el pago.");
        return;
      }
      payment.collector = collector;
    }
    setBusy(button, true, "Registrando…");
    try {
      await api("/loan-payments/", { method: "POST", body: JSON.stringify(payment) });
      elements.dialog.close();
      await loadDashboard();
      showToast("Pago registrado correctamente.");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  async function restoreSession() {
    if (!state.access) {
      setScreen("auth");
      return;
    }
    try {
      const user = await api("/auth/me/");
      state.username = user.username;
      sessionStorage.setItem("loan_username", user.username);
      const storedTenant = sessionStorage.getItem("loan_tenant");
      if (storedTenant) {
        const membership = JSON.parse(storedTenant);
        const memberships = getRows(await api("/auth/me/tenants/"));
        if (memberships.some((item) => item.tenant_id === membership.tenant_id)) {
          await openWorkspace(memberships.find((item) => item.tenant_id === membership.tenant_id));
          return;
        }
      }
      await loadTenants();
    } catch (error) {
      setScreen("auth");
      showError(error.message);
    }
  }

  toggleRegistration(false);
  restoreSession();
})();
