(() => {
  const app = document.getElementById("loan-app");
  const apiBase = app.dataset.apiBase.replace(/\/$/, "");
  const state = {
    access: sessionStorage.getItem("loan_access") || sessionStorage.getItem("tn_access") || sessionStorage.getItem("barber_access"),
    refresh: sessionStorage.getItem("loan_refresh") || sessionStorage.getItem("tn_refresh") || sessionStorage.getItem("barber_refresh"),
    username: sessionStorage.getItem("loan_username") || sessionStorage.getItem("tn_username") || sessionStorage.getItem("barber_username") || "",
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
    seenEventIds: new Set(),
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
    const fieldNames = {
      username: "Usuario",
      email: "Correo",
      full_name: "Nombre",
      password: "Contraseña",
      password_confirm: "Confirmación",
      join_code: "Código del negocio",
      business_name: "Nombre del negocio",
    };
    const parts = [];
    Object.entries(data).forEach(([key, val]) => {
      const msg = [val].flat(Infinity).find((item) => typeof item === "string");
      if (!msg) return;
      const label = fieldNames[key];
      parts.push(label ? `${label}: ${msg}` : msg);
    });
    return parts.join(" · ") || fallback;
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
    sessionStorage.setItem("tn_access", data.access);
    if (data.refresh) {
      state.refresh = data.refresh;
      sessionStorage.setItem("loan_refresh", data.refresh);
      sessionStorage.setItem("tn_refresh", data.refresh);
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

  function cleanPhoneForWhatsApp(phone) {
    const digits = String(phone || "").replace(/\D+/g, "");
    if (!digits || digits.length < 7) return "";
    if (digits.length === 10 && digits.startsWith("3")) return `57${digits}`;
    return digits;
  }

  function whatsappUrl(phone, text) {
    const clean = cleanPhoneForWhatsApp(phone);
    const encoded = encodeURIComponent(text || "");
    return clean ? `https://wa.me/${clean}?text=${encoded}` : `https://api.whatsapp.com/send?text=${encoded}`;
  }

  function populateExistingCustomers() {
    const select = document.getElementById("existing-customer-select");
    if (!select) return;
    const byDoc = new Map();
    state.loans.forEach((loan) => {
      const key = loan.document_id || loan.customer_name;
      if (!key || byDoc.has(key)) return;
      byDoc.set(key, {
        full_name: loan.customer_name || "",
        document_id: loan.document_id || "",
        phone: loan.customer_phone || "",
        neighborhood: loan.neighborhood || "",
      });
    });
    if (state.customerSummary && Array.isArray(state.customerSummary.rows)) {
      state.customerSummary.rows.forEach((row) => {
        const key = row.customer_document || row.customer_name;
        if (!key) return;
        byDoc.set(key, {
          full_name: row.customer_name || "",
          document_id: row.customer_document || "",
          phone: row.customer_phone || "",
          neighborhood: row.customer_neighborhood || "",
        });
      });
    }
    const currentVal = select.value;
    select.replaceChildren(new Option("＋ Nuevo cliente (ingresar datos manualmente)", ""));
    Array.from(byDoc.values())
      .sort((a, b) => a.full_name.localeCompare(b.full_name, "es"))
      .forEach((customer) => {
        const label = `${customer.full_name}${customer.document_id ? ` (${customer.document_id})` : ""}${customer.neighborhood ? ` · ${customer.neighborhood}` : ""}`;
        const option = new Option(label, customer.document_id || customer.full_name);
        option.dataset.fullName = customer.full_name;
        option.dataset.documentId = customer.document_id;
        option.dataset.phone = customer.phone;
        option.dataset.neighborhood = customer.neighborhood;
        select.add(option);
      });
    select.value = currentVal;
  }

  function prefillCustomerForm({ fullName = "", documentId = "", phone = "", neighborhood = "" }) {
    document.getElementById("customer-name").value = fullName;
    document.getElementById("customer-document").value = documentId;
    const phoneInput = document.getElementById("customer-phone");
    if (phoneInput) phoneInput.value = phone;
    const renewalPill = document.getElementById("renewal-active-pill");
    if (renewalPill) renewalPill.hidden = !(fullName || documentId);
    const existingSelect = document.getElementById("existing-customer-select");
    if (existingSelect && (documentId || fullName)) {
      const optMatch = Array.from(existingSelect.options).find(
        (opt) => opt.value && (opt.dataset.documentId === documentId || opt.dataset.fullName === fullName)
      );
      if (optMatch) existingSelect.value = optMatch.value;
    } else if (existingSelect && !fullName && !documentId) {
      existingSelect.value = "";
    }
    const neighborhoodSelect = document.getElementById("customer-neighborhood");
    const otherNeighborhood = document.getElementById("customer-other-neighborhood");
    if (neighborhood) {
      const match = Array.from(neighborhoodSelect.options).find(
        (opt) => opt.value.toUpperCase() === neighborhood.toUpperCase() && opt.value !== "__other__"
      );
      if (match) {
        neighborhoodSelect.value = match.value;
        otherNeighborhood.hidden = true;
        otherNeighborhood.required = false;
        otherNeighborhood.value = "";
      } else {
        neighborhoodSelect.value = "__other__";
        otherNeighborhood.hidden = false;
        otherNeighborhood.required = true;
        otherNeighborhood.value = neighborhood;
      }
    } else {
      neighborhoodSelect.value = "";
      otherNeighborhood.hidden = true;
      otherNeighborhood.required = false;
      otherNeighborhood.value = "";
    }
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
    if (data.is_staff) sessionStorage.setItem("is_staff", "true");
    if (data.is_superuser) sessionStorage.setItem("is_superuser", "true");
    const adminLink = document.getElementById("topbar-admin-link");
    if (adminLink) {
      const isAdmin = data.is_staff || data.is_superuser;
      adminLink.style.display = isAdmin ? "inline-flex" : "none";
    }
    await loadTenants();
  }

  async function loadTenants() {
    try {
      const allMemberships = getRows(await api("/auth/me/tenants/"));
      const loanMemberships = allMemberships.filter((m) => {
        const tools = m.enabled_tools || [];
        return tools.includes("loans") || m.tenant_business_type === "prestamista";
      });

      const options = document.getElementById("tenant-options");
      options.replaceChildren();

      if (!loanMemberships.length) {
        setScreen("tenants");
        options.innerHTML =
          '<div class="notice notice-error" style="display:block;"><strong>Módulo no habilitado</strong><br>Tu cuenta no tiene habilitado el módulo de Préstamos. Solicita a tu administrador de TuNegocio Digital que active este módulo para poder ingresar.</div>';
        const createForm = document.getElementById("tenant-create-form");
        if (createForm) createForm.hidden = true;
        return;
      }

      const createForm = document.getElementById("tenant-create-form");
      if (createForm) createForm.hidden = false;

      loanMemberships.forEach((membership) => {
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
    const isEmployee = state.role === "employee";
    const adminLink = document.getElementById("topbar-admin-link");
    if (adminLink) {
      const isAdmin = sessionStorage.getItem("is_staff") === "true" || sessionStorage.getItem("is_superuser") === "true";
      adminLink.style.display = isAdmin ? "inline-flex" : "none";
    }
    document.getElementById("business-code-panel").hidden = !isOwner;
    document.getElementById("business-join-code").textContent = membership.tenant_join_code || "—";
    document.getElementById("ledger-nav").hidden = !isOwner;
    document.getElementById("mobile-ledger-nav").hidden = !isOwner;
    document.getElementById("employee-requests-nav").hidden = !isOwner;
    const trashNav = document.getElementById("trash-nav");
    if (trashNav) trashNav.hidden = !isOwner;
    const mobileTrashNav = document.getElementById("mobile-trash-nav");
    if (mobileTrashNav) mobileTrashNav.hidden = !isOwner;
    // La pestaña móvil de Solicitudes se mantiene oculta salvo que haya pendientes (accesible desde el panel de código)
    document.getElementById("mobile-employee-requests-nav").hidden = true;

    // Unificación para el cobrador: Inicio ya contiene su ruta completa del día
    const collectionsNav = document.getElementById("collections-nav");
    const mobileCollectionsNav = document.getElementById("mobile-collections-nav");
    const homeGotoCollections = document.getElementById("home-goto-collections");
    if (collectionsNav) collectionsNav.hidden = isEmployee;
    if (mobileCollectionsNav) mobileCollectionsNav.hidden = isEmployee;
    if (homeGotoCollections) homeGotoCollections.hidden = isEmployee;

    // Solo cobros del dia, saldo por cobrar y gastos para el cobrador
    document.getElementById("customer-summary-nav").hidden = isEmployee;
    document.getElementById("mobile-customer-nav").hidden = isEmployee;
    document.getElementById("new-loan-nav").hidden = false;
    document.getElementById("mobile-add-button").hidden = false;
    document.getElementById("desktop-new-button").hidden = false;
    const ownerDailySection = document.getElementById("home-owner-daily-section");
    if (ownerDailySection) ownerDailySection.hidden = isEmployee;
    const ownerDailyDate = document.getElementById("owner-daily-date");
    if (ownerDailyDate) ownerDailyDate.value = localDateValue();
    const ownerDailyCollector = document.getElementById("owner-daily-collector");
    if (ownerDailyCollector) ownerDailyCollector.value = "";
    const mainKpiCard = document.getElementById("main-kpi-card");
    if (mainKpiCard) mainKpiCard.hidden = isEmployee;
    const homeSummaryGrid = document.getElementById("home-summary-grid");
    if (homeSummaryGrid) homeSummaryGrid.classList.toggle("is-collector-grid", isEmployee);
    document.getElementById("home-portfolio-card").hidden = false;
    document.getElementById("home-loans-section").hidden = isEmployee;
    document.getElementById("home-collections-section").hidden = !isEmployee;
    const cashSummaryOwnerSection = document.getElementById("cash-summary-owner-section");
    if (cashSummaryOwnerSection) cashSummaryOwnerSection.hidden = isEmployee;
    const cashflowForms = document.querySelector(".cashflow-forms");
    if (cashflowForms) cashflowForms.classList.toggle("is-collector-forms", isEmployee);
    document.getElementById("cash-opening-section").hidden = isEmployee;
    document.getElementById("expense-collector-field").hidden = isEmployee;
    const expensesSubtitle = document.getElementById("expenses-section-subtitle");
    if (expensesSubtitle) {
      expensesSubtitle.textContent = isEmployee
        ? "Solo se muestran los gastos registrados en tu sesión de cobrador."
        : "Cada gasto queda asociado a un cobrador y una fecha.";
    }
    const expenseRows = document.getElementById("expense-rows");
    if (expenseRows) expenseRows.replaceChildren();
    const cashSummaryRows = document.getElementById("cash-summary-rows");
    if (cashSummaryRows) cashSummaryRows.replaceChildren();
    const cashExportBtn = document.getElementById("cash-export-excel");
    if (cashExportBtn) cashExportBtn.hidden = isEmployee;
    const openExcelDialogBtn = document.getElementById("open-excel-dialog-button");
    if (openExcelDialogBtn) openExcelDialogBtn.hidden = isEmployee;
    const customerExportBtn = document.getElementById("customer-export-excel");
    if (customerExportBtn) customerExportBtn.hidden = isEmployee;
    document.getElementById("mobile-cashflow-nav").hidden = false;
    document.getElementById("today-label").textContent = new Intl.DateTimeFormat("es", {
      weekday: "long",
      day: "numeric",
      month: "long",
    }).format(new Date()).toUpperCase();
    const today = new Date();
    document.getElementById("start-date").value = localDateValue(today);
    document.getElementById("ledger-period").value = "day";
    document.getElementById("ledger-frequency").value = "daily";
    document.getElementById("ledger-date").value = localDateValue(today);
    const excelModalDate = document.getElementById("excel-modal-date");
    if (excelModalDate) excelModalDate.value = localDateValue(today);
    ["cash-date", "cash-opening-date", "expense-date"].forEach((id) => {
      document.getElementById(id).value = localDateValue(today);
    });
    clearMessages();
    await loadDashboard();
    if ((rank[state.role] || 0) >= rank.manager) await loadEmployees();
    if (isOwner) loadEmployeeRequests();
    if ((rank[state.role] || 0) >= rank.employee) startPaymentStream();
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
    const filterSelect = document.getElementById("loan-collector-filter");
    const manageSelect = document.getElementById("manage-collector-select");
    const selectedLoanCollector = loanSelect.value;
    const selectedFilterCollector = filterSelect ? filterSelect.value : "";
    loanSelect.replaceChildren(new Option("Sin asignar", ""));
    paymentSelect.replaceChildren(new Option("Selecciona un cobrador", ""));
    openingSelect.replaceChildren(new Option("Selecciona un cobrador", ""));
    expenseSelect.replaceChildren(new Option("Selecciona un cobrador", ""));
    if (filterSelect) {
      filterSelect.replaceChildren(
        new Option("Todos los cobradores", ""),
        new Option("Sin cobrador asignado", "__none__"),
      );
    }
    if (manageSelect) {
      manageSelect.replaceChildren(new Option("Sin cobrador asignado", ""));
    }
    state.employees.forEach((employee) => {
      const label = employee.full_name || employee.email || `Cobrador ${employee.id}`;
      loanSelect.add(new Option(label, employee.id));
      paymentSelect.add(new Option(label, employee.id));
      openingSelect.add(new Option(label, employee.id));
      expenseSelect.add(new Option(label, employee.id));
      if (filterSelect) filterSelect.add(new Option(`Cobrador: ${label}`, employee.id));
      if (manageSelect) manageSelect.add(new Option(label, employee.id));
    });
    loanSelect.value = selectedLoanCollector;
    if (filterSelect) filterSelect.value = selectedFilterCollector;
    const manager = (rank[state.role] || 0) >= rank.manager;
    document.getElementById("collector-field").hidden = !manager;
    document.getElementById("payment-collector-field").hidden = !manager;
    document.getElementById("cash-opening-collector-field").hidden = !manager;
    document.getElementById("expense-collector-field").hidden = !manager;
    if (filterSelect) filterSelect.hidden = !manager;
    openingSelect.required = manager;
    expenseSelect.required = manager;
  }

  function computeCollectedToday() {
    const todayStr = localDateValue();
    const byCustomerLoan = [];
    let totalCollectedToday = 0;
    state.loans.forEach((loan) => {
      const paymentsToday = (loan.payment_history || []).filter(
        (p) => p.date === todayStr && p.direction === "payment" && !p.is_reversed
      );
      if (!paymentsToday.length) return;
      const sumToday = paymentsToday.reduce((acc, p) => acc + Number(p.amount || 0), 0);
      totalCollectedToday += sumToday;
      byCustomerLoan.push({
        loan,
        customer_name: loan.customer_name || "Cliente",
        customer_phone: loan.customer_phone || "",
        neighborhood: loan.neighborhood || "",
        amount_today: sumToday,
        payments_count: paymentsToday.length,
        last_payment: paymentsToday[0],
      });
    });
    return { items: byCustomerLoan, totalAmount: totalCollectedToday };
  }

  function renderOwnerDailyCollections() {
    const section = document.getElementById("home-owner-daily-section");
    if (!section) return;
    if (state.role === "employee" || !state.role) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    const dateInput = document.getElementById("owner-daily-date");
    const collectorSelect = document.getElementById("owner-daily-collector");
    if (!dateInput.value) dateInput.value = localDateValue();
    const selectedDate = dateInput.value;

    // Abonos del día seleccionado, agrupados por préstamo y cobrador
    const groups = new Map();
    state.loans.forEach((loan) => {
      (loan.payment_history || []).forEach((payment) => {
        if (payment.date !== selectedDate || payment.direction !== "payment" || payment.is_reversed) return;
        const collectorName = payment.collector_name || "Sin cobrador";
        const key = `${loan.id}|${collectorName}`;
        if (!groups.has(key)) {
          groups.set(key, { loan, collectorName, amount: 0, count: 0, lastTime: "", methods: new Set() });
        }
        const group = groups.get(key);
        group.amount += Number(payment.amount || 0);
        group.count += 1;
        if ((payment.time || "") > group.lastTime) group.lastTime = payment.time || "";
        group.methods.add(payment.method);
      });
    });

    // Opciones del filtro de cobrador (conserva la selección actual)
    const previousCollector = collectorSelect.value;
    const collectorNames = [...new Set([...groups.values()].map((g) => g.collectorName))].sort();
    collectorSelect.replaceChildren(new Option("Todos los cobradores", ""));
    collectorNames.forEach((name) => collectorSelect.add(new Option(name, name)));
    collectorSelect.value = collectorNames.includes(previousCollector) ? previousCollector : "";

    const entries = [...groups.values()]
      .filter((g) => !collectorSelect.value || g.collectorName === collectorSelect.value)
      .sort((a, b) => b.lastTime.localeCompare(a.lastTime));
    const total = entries.reduce((sum, g) => sum + g.amount, 0);
    const methodLabels = { cash: "Efectivo", transfer: "Transferencia", other: "Otro" };

    document.getElementById("owner-daily-total").textContent = money(total);
    document.getElementById("owner-daily-pill").textContent =
      `${entries.length} ${entries.length === 1 ? "persona" : "personas"}`;
    document.getElementById("owner-daily-empty").hidden = entries.length > 0;
    const list = document.getElementById("owner-daily-list");
    list.replaceChildren();
    entries.forEach((entry) => {
      const loan = entry.loan;
      const name = loan.customer_name || "Cliente";
      const methods = [...entry.methods].map((m) => methodLabels[m] || m).join(", ");
      const row = document.createElement("article");
      row.className = "loan-row";
      row.innerHTML =
        `<div class="loan-person"><span class="customer-avatar">${escapeHtml(initials(name))}</span>` +
        `<div><strong>${escapeHtml(name)}</strong>` +
        `<span>${escapeHtml(loan.neighborhood || "Sin barrio")} · ${entry.count} ${entry.count === 1 ? "abono" : "abonos"}` +
        `${entry.lastTime ? ` · ${escapeHtml(entry.lastTime)}` : ""}</span></div></div>` +
        `<div class="loan-detail"><strong class="text-emerald">${money(entry.amount)}</strong><span>Cobrado ese día</span></div>` +
        `<div class="loan-detail"><strong>${escapeHtml(entry.collectorName)}</strong><span>${escapeHtml(methods)}</span></div>` +
        `<span class="status-pill status-paid">Cobrado ✓</span>` +
        `<div class="loan-row-actions">` +
        `<button class="loan-action-secondary" type="button" data-open-amortization="${escapeHtml(loan.id)}">📊 Ver amortización</button>` +
        `</div>`;
      list.append(row);
    });
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
      state.collectedToday = computeCollectedToday();
      populateExistingCustomers();
      renderLoans();
      renderCollections();
      renderOwnerDailyCollections();

      const isEmployee = state.role === "employee";
      const mainLabel = document.getElementById("main-kpi-label");
      const mainCaption = document.getElementById("main-kpi-caption");
      const secondLabel = document.getElementById("second-kpi-label");
      const secondCaption = document.getElementById("second-kpi-caption");
      const thirdLabel = document.getElementById("third-kpi-label");
      const thirdCaption = document.getElementById("third-kpi-caption");

      if (isEmployee) {
        const pendingTodayAmount = state.collections.reduce((sum, item) => {
          const pending = item.pending_amount ?? (Number(item.amount_due || 0) - Number(item.amount_paid || 0));
          return sum + Number(pending || 0);
        }, 0);
        const collectedTodayAmount = state.collectedToday.totalAmount;
        const dailyTargetAmount = pendingTodayAmount + collectedTodayAmount;

        if (mainLabel) mainLabel.textContent = "Por cobrar hoy";
        document.getElementById("total-balance").textContent = money(pendingTodayAmount);
        if (mainCaption) {
          mainCaption.textContent = `Recogido hoy: ${money(collectedTodayAmount)} · Meta del día: ${money(dailyTargetAmount)}`;
        }
        if (secondLabel) secondLabel.textContent = "Cuotas pendientes hoy";
        document.getElementById("today-count").textContent = String(state.collections.length);
        if (secondCaption) {
          secondCaption.hidden = false;
          secondCaption.textContent = "Cuotas por cobrar en tu ruta";
        }
        if (thirdLabel) thirdLabel.textContent = "Personas cobradas hoy";
        document.getElementById("loan-count").textContent = String(state.collectedToday.items.length);
        if (thirdCaption) {
          thirdCaption.textContent = `Cobrado hoy: ${money(collectedTodayAmount)}`;
        }
      } else {
        const activeLoans = state.loans.filter((loan) => !["paid", "cancelled"].includes(loan.status));
        if (mainLabel) mainLabel.textContent = "Saldo por cobrar";
        document.getElementById("total-balance").textContent =
          money(activeLoans.reduce((total, loan) => total + Number(loan.balance || 0), 0));
        if (mainCaption) {
          mainCaption.innerHTML = `<span id="active-count">${activeLoans.length}</span> préstamos activos en ruta`;
        }
        if (secondLabel) secondLabel.textContent = "Cobros para hoy";
        document.getElementById("today-count").textContent = String(state.collections.length);
        if (secondCaption) secondCaption.hidden = true;
        if (thirdLabel) thirdLabel.textContent = "Préstamos en cartera";
        document.getElementById("loan-count").textContent = String(state.loans.length);
        if (thirdCaption) thirdCaption.textContent = "Total histórico registrado";
      }

      document.getElementById("collection-pill").textContent =
        `${state.collections.length} ${state.collections.length === 1 ? "pendiente" : "pendientes"}`;
    } catch (error) {
      showError(error.message);
    }
  }

  function renderLoans() {
    elements.loans.replaceChildren();
    const searchInput = document.getElementById("loan-quick-search");
    const collectorFilter = document.getElementById("loan-collector-filter");
    const query = (searchInput ? searchInput.value : "").trim().toLowerCase();
    const selectedCollector = collectorFilter ? collectorFilter.value : "";
    const filteredLoans = state.loans.filter((loan) => {
      if (selectedCollector === "__none__" && loan.collector) return false;
      if (selectedCollector && selectedCollector !== "__none__" && String(loan.collector || "") !== String(selectedCollector)) {
        return false;
      }
      if (!query) return true;
      return [loan.customer_name, loan.neighborhood, loan.document_id, loan.collector_name]
        .some((field) => String(field || "").toLowerCase().includes(query));
    });
    document.getElementById("loans-empty").hidden = filteredLoans.length > 0;
    const isManager = (rank[state.role] || 0) >= rank.manager;
    filteredLoans.forEach((loan) => {
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
      const phone = loan.customer_phone || "";
      const contactHtml = cleanPhoneForWhatsApp(phone)
        ? `<div class="customer-cell-meta">` +
          `<a class="contact-chip" href="tel:${escapeHtml(phone)}">📞 Llamar</a>` +
          `<a class="contact-chip" target="_blank" rel="noopener" href="${escapeHtml(whatsappUrl(phone, `Hola ${name}, te escribimos de ${state.tenant ? state.tenant.tenant_name : "TuNegocio"}. Tu saldo pendiente es ${money(loan.balance)}.`))}">💬 WhatsApp</a>` +
          `</div>`
        : "";
      const collectorMeta = loan.collector_name
        ? ` · Cobrador: ${escapeHtml(loan.collector_name)}`
        : " · Sin cobrador";
      const paymentsCount = Array.isArray(loan.payment_history) ? loan.payment_history.length : 0;
      const amortBtnHtml =
        `<button class="loan-action-secondary" type="button" data-open-amortization="${escapeHtml(loan.id)}">` +
        `📊 Amortización</button>`;
      const manageBtnHtml =
        `<button class="loan-action-secondary" type="button" data-manage-loan="${escapeHtml(loan.id)}">` +
        `🧾 Abonos (${paymentsCount})</button>`;
      const renewBtnHtml = isManager
        ? `<button class="loan-action-secondary" type="button" data-renew-customer="1" ` +
          `data-full-name="${escapeHtml(name)}" ` +
          `data-document-id="${escapeHtml(loan.document_id || "")}" ` +
          `data-phone="${escapeHtml(phone)}" ` +
          `data-neighborhood="${escapeHtml(loan.neighborhood || "")}">＋ Renovar</button>`
        : "";
      row.innerHTML =
        `<div class="loan-person"><span class="customer-avatar">${escapeHtml(initials(name))}</span>` +
        `<div><strong>${escapeHtml(name)}</strong><span>${escapeHtml(loan.neighborhood || "Sin barrio")}${collectorMeta}</span>` +
        `<span>${escapeHtml(loan.document_id || "Sin cédula")}</span>${contactHtml}</div></div>` +
        `<div class="loan-detail"><strong>${money(loan.balance)}</strong>` +
        `<span>Total ${money(loan.total_payable)} · Abono ${money(Number(loan.total_payable) - Number(loan.balance))}</span>` +
        `<span>Papelería ${money(loan.paperwork_fee)} aparte</span></div>` +
        `<div class="loan-detail"><strong>${collectionSummary}</strong><span>${paymentPlan}</span></div>` +
        `<button class="loan-action" type="button" data-payment-loan="${escapeHtml(loan.id)}" ` +
        `data-payment-name="${escapeHtml(name)}" data-payment-phone="${escapeHtml(phone)}" data-payment-suggested="${escapeHtml(suggested)}">Registrar pago</button>` +
        `<span class="status-pill ${statusClass(loan.status)}">${escapeHtml(labels[loan.status] || loan.status)}</span>` +
        `<div class="loan-row-actions">${amortBtnHtml}${manageBtnHtml}${renewBtnHtml}</div>`;
      elements.loans.append(row);
    });
  }

  function renderCollections() {
    const searchInput = document.getElementById("collection-quick-search");
    const query = (searchInput ? searchInput.value : "").trim().toLowerCase();
    const filteredCollections = query
      ? state.collections.filter((installment) =>
          [installment.customer_name, installment.due_date, labels[installment.frequency]]
            .some((field) => String(field || "").toLowerCase().includes(query))
        )
      : state.collections;

    const homeSearchInput = document.getElementById("home-collection-quick-search");
    const homeQuery = (homeSearchInput ? homeSearchInput.value : "").trim().toLowerCase();
    const filteredHomeCollections = homeQuery
      ? state.collections.filter((installment) =>
          [installment.customer_name, installment.due_date, labels[installment.frequency]]
            .some((field) => String(field || "").toLowerCase().includes(homeQuery))
        )
      : state.collections;

    const targets = [
      { list: elements.collections, empty: document.getElementById("collections-empty"), items: filteredCollections },
    ];
    const homeList = document.getElementById("home-collection-list");
    const homeEmpty = document.getElementById("home-collections-empty");
    if (homeList && homeEmpty) {
      targets.push({ list: homeList, empty: homeEmpty, items: filteredHomeCollections });
    }
    targets.forEach(({ list, empty, items }) => {
      list.replaceChildren();
      empty.hidden = items.length > 0;
      items.forEach((installment) => {
        const row = document.createElement("article");
        row.className = "loan-row";
        const name = installment.customer_name || "Cliente";
        const phone = installment.customer_phone || "";
        const pending = installment.pending_amount ??
          (Number(installment.amount_due || 0) - Number(installment.amount_paid || 0));
        const overdue = Boolean(installment.is_overdue);
        const collectionType = installment.is_open_ended
          ? `Cuota ${escapeHtml(installment.number)} · ${escapeHtml(labels[installment.frequency] || installment.frequency)}`
          : `Cuota ${escapeHtml(installment.number)}`;
        const contactHtml = cleanPhoneForWhatsApp(phone)
          ? `<div class="customer-cell-meta">` +
            `<a class="contact-chip" href="tel:${escapeHtml(phone)}">📞 Llamar</a>` +
            `<a class="contact-chip" target="_blank" rel="noopener" href="${escapeHtml(whatsappUrl(phone, `Hola ${name}, te recordamos tu cuota de hoy por ${money(pending)}.`))}">💬 WhatsApp</a>` +
            `</div>`
          : "";
        row.innerHTML =
          `<div class="loan-person"><span class="customer-avatar">${escapeHtml(initials(name))}</span>` +
          `<div><strong>${escapeHtml(name)}</strong><span>${collectionType} · ` +
          `${escapeHtml(installment.due_date)}</span>${contactHtml}</div></div>` +
          `<div class="loan-detail"><strong>${money(pending)}</strong><span>Cuota por cobrar hoy</span></div>` +
          `<div class="loan-detail"><strong>${money(installment.amount_due)}</strong><span>Valor cuota</span></div>` +
          `<button class="loan-action" type="button" data-payment-loan="${escapeHtml(installment.loan)}" ` +
          `data-payment-name="${escapeHtml(name)}" data-payment-phone="${escapeHtml(phone)}" data-payment-suggested="${escapeHtml(pending)}">Cobrar</button>` +
          `<span class="status-pill ${overdue ? "status-delinquent" : "status-active"}">` +
          `${overdue ? "Vencida" : "Pendiente"}</span>` +
          `<div class="loan-row-actions"><button class="loan-action-secondary" type="button" data-open-amortization="${escapeHtml(installment.loan)}">📊 Ver amortización</button></div>`;
        list.append(row);
      });
    });
    const homePill = document.getElementById("home-collection-pill");
    if (homePill) {
      homePill.textContent = `${state.collections.length} ${state.collections.length === 1 ? "pendiente" : "pendientes"}`;
    }

    // Renderizar lista de personas ya cobradas hoy para el cobrador
    const collectedTodayData = state.collectedToday || { items: [], totalAmount: 0 };
    const collectedPill = document.getElementById("home-collected-pill");
    if (collectedPill) {
      const cCount = collectedTodayData.items.length;
      collectedPill.textContent = `${cCount} ${cCount === 1 ? "cobrada" : "cobradas"}`;
    }
    const collectedList = document.getElementById("home-collected-today-list");
    const collectedEmpty = document.getElementById("home-collected-today-empty");
    if (collectedList && collectedEmpty) {
      const filteredCollected = homeQuery
        ? collectedTodayData.items.filter((entry) =>
            [entry.customer_name, entry.neighborhood]
              .some((field) => String(field || "").toLowerCase().includes(homeQuery))
          )
        : collectedTodayData.items;
      collectedList.replaceChildren();
      collectedEmpty.hidden = filteredCollected.length > 0;
      filteredCollected.forEach((entry) => {
        const row = document.createElement("article");
        row.className = "loan-row";
        const name = entry.customer_name;
        const phone = entry.customer_phone;
        const receiptText =
          `Comprobante de abono - ${state.tenant ? state.tenant.tenant_name : "TuNegocio"}
` +
          `Cliente: ${name}
` +
          `Abono recibido hoy: ${money(entry.amount_today)}
` +
          `Fecha: ${displayDate(localDateValue())}`;
        row.innerHTML =
          `<div class="loan-person"><span class="customer-avatar">${escapeHtml(initials(name))}</span>` +
          `<div><strong>${escapeHtml(name)}</strong><span>${escapeHtml(entry.neighborhood || "En ruta")} · ${entry.payments_count} ${entry.payments_count === 1 ? "abono hoy" : "abonos hoy"}</span></div></div>` +
          `<div class="loan-detail"><strong class="text-emerald">${money(entry.amount_today)}</strong><span>Recogido hoy</span></div>` +
          `<div class="loan-detail"><strong>${money(entry.loan.balance)}</strong><span>Restante del crédito</span></div>` +
          `<span class="status-pill status-paid">Cobrado hoy ✓</span>` +
          `<div class="loan-row-actions">` +
          `<button class="loan-action-secondary" type="button" data-open-amortization="${escapeHtml(entry.loan.id)}">📊 Ver amortización</button>` +
          `<a class="loan-action-secondary" target="_blank" rel="noopener" href="${escapeHtml(whatsappUrl(phone, receiptText))}">📲 Enviar recibo</a>` +
          `</div>`;
        collectedList.append(row);
      });
    }
  }

  async function loadEmployeeRequests() {
    const container = document.getElementById("employee-request-list");
    try {
      const requests = getRows(await api("/tenant-join-requests/manage/"));
      document.getElementById("employee-requests-empty").hidden = requests.length > 0;
      const badge = document.getElementById("employee-requests-badge");
      if (badge) {
        badge.textContent = String(requests.length);
        badge.hidden = requests.length === 0;
      }
      const mobileRequestsNav = document.getElementById("mobile-employee-requests-nav");
      if (mobileRequestsNav && state.role === "owner") {
        mobileRequestsNav.hidden = requests.length === 0;
      }
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
      const isManager = (rank[state.role] || 0) >= rank.manager;
      document.getElementById("cash-summary-rows").innerHTML = (report.rows || []).map((row) => {
        const editBtn = isManager
          ? ` <button class="button button-quiet button-xs" type="button" data-edit-opening-collector="${escapeHtml(row.collector_id)}" data-edit-opening-amount="${escapeHtml(row.opening_cash)}" title="Modificar dinero inicial">✎</button>`
          : "";
        return (
          `<tr><td>${escapeHtml(row.collector_name)}</td><td>${money(row.opening_cash)}${editBtn}</td>` +
          `<td>${money(row.collected)}</td><td>${money(row.expenses)}</td>` +
          `<td>${money(row.principal_lent)}</td><td>${money(row.paperwork)}</td>` +
          `<td><strong>${money(row.expected_cash)}</strong></td></tr>`
        );
      }).join("");
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
    document.getElementById("expense-rows").innerHTML = expenses.map((expense) => {
      const detail = [expense.description, expense.notes].filter(Boolean).join(" · ")
        || labelsByCategory[expense.category]
        || "—";
      return (
        `<tr><td>${escapeHtml(displayDate(expense.spent_on))}</td>` +
        `<td>${escapeHtml(expense.collector_name || "")}</td>` +
        `<td>${escapeHtml(labelsByCategory[expense.category] || expense.category)}</td>` +
        `<td>${escapeHtml(detail)}</td><td>${money(expense.amount)}</td></tr>`
      );
    }).join("");
    document.getElementById("expenses-empty").hidden = expenses.length > 0;
  }

  function findLoanById(loanId) {
    const direct = state.loans.find((item) => String(item.id) === String(loanId));
    if (direct) return direct;
    if (state.customerSummary && Array.isArray(state.customerSummary.rows)) {
      for (const customer of state.customerSummary.rows) {
        const match = (customer.loans || []).find((item) => String(item.id) === String(loanId));
        if (match) {
          return {
            ...match,
            customer_name: customer.customer_name,
            document_id: customer.customer_document,
            customer_phone: customer.customer_phone,
            neighborhood: customer.customer_neighborhood,
            collector: match.collector_id,
            paperwork_fee: match.paperwork,
            start_date: match.date,
            installment_schedule: match.installments,
            payment_history: match.payments,
          };
        }
      }
    }
    return null;
  }

  function openLoanManageDialog(loanId) {
    const dialog = document.getElementById("loan-manage-dialog");
    const loan = findLoanById(loanId);
    if (!dialog || !loan) return;
    state.activeManagedLoanId = String(loan.id);
    const isOwner = state.role === "owner";
    const isManager = (rank[state.role] || 0) >= rank.manager;
    const name = loan.customer_name || "Cliente";
    const phone = loan.customer_phone || "";
    const doc = loan.document_id || "Sin cédula";
    const neighborhood = loan.neighborhood || "Sin barrio";
    const freqLabel = labels[loan.frequency] || loan.frequency || "Diario";

    document.getElementById("manage-loan-eyebrow").textContent =
      `CRÉDITO ${freqLabel.toUpperCase()} · INICIO ${displayDate(loan.start_date || loan.date || "")}`;
    document.getElementById("manage-loan-title").textContent = name;
    document.getElementById("manage-loan-subtitle").textContent = `${doc} · ${neighborhood}`;

    const nextInstallment = (loan.installment_schedule || [])
      .find((inst) => Number(inst.amount_paid) < Number(inst.amount_due));
    const suggested = nextInstallment
      ? Math.min(Number(nextInstallment.amount_due) - Number(nextInstallment.amount_paid), Number(loan.balance))
      : Number(loan.balance);

    const quickActions = [
      `<button class="button button-primary button-sm" type="button" data-payment-loan="${escapeHtml(loan.id)}" ` +
        `data-payment-name="${escapeHtml(name)}" data-payment-phone="${escapeHtml(phone)}" ` +
        `data-payment-suggested="${escapeHtml(suggested)}">＋ Registrar abono</button>`,
      `<button class="button button-outline button-sm" type="button" data-open-amortization="${escapeHtml(loan.id)}">📊 Ver amortización completa</button>`,
      isManager
        ? `<button class="button button-outline button-sm" type="button" data-renew-customer="1" ` +
          `data-full-name="${escapeHtml(name)}" data-document-id="${escapeHtml(loan.document_id || "")}" ` +
          `data-phone="${escapeHtml(phone)}" data-neighborhood="${escapeHtml(loan.neighborhood || "")}">🔄 Renovar crédito</button>`
        : "",
      cleanPhoneForWhatsApp(phone)
        ? `<a class="button button-quiet button-sm" href="tel:${escapeHtml(phone)}">📞 Llamar</a>` +
          `<a class="button button-quiet button-sm" target="_blank" rel="noopener" href="${escapeHtml(whatsappUrl(phone, `Hola ${name}, te escribimos de ${state.tenant ? state.tenant.tenant_name : "TuNegocio"}. Tu saldo actual es ${money(loan.balance)}.`))}">💬 WhatsApp</a>`
        : "",
    ].filter(Boolean).join("");
    document.getElementById("manage-quick-actions").innerHTML = quickActions;

    const principal = Number(loan.principal || 0);
    const totalPayable = Number(loan.total_payable || 0);
    const interest = loan.interest !== undefined ? Number(loan.interest) : (totalPayable - principal);
    const paperwork = Number(loan.paperwork_fee ?? loan.paperwork ?? 0);
    const balance = Number(loan.balance || 0);
    const collected = totalPayable - balance;

    document.getElementById("manage-kpi-grid").innerHTML =
      `<div class="manage-kpi-item"><span>Capital</span><strong>${money(principal)}</strong></div>` +
      `<div class="manage-kpi-item"><span>Interés</span><strong>${money(interest)}</strong></div>` +
      `<div class="manage-kpi-item"><span>Papelería</span><strong>${money(paperwork)}</strong></div>` +
      `<div class="manage-kpi-item"><span>Total a pagar</span><strong>${money(totalPayable)}</strong></div>` +
      `<div class="manage-kpi-item"><span>Total abonado</span><strong class="text-emerald">${money(collected)}</strong></div>` +
      `<div class="manage-kpi-item"><span>Saldo pendiente</span><strong>${money(balance)}</strong></div>`;

    const collectorBox = document.getElementById("manage-collector-box");
    const collectorSelect = document.getElementById("manage-collector-select");
    if (collectorBox && collectorSelect) {
      collectorBox.hidden = !isManager;
      collectorSelect.value = String(loan.collector || loan.collector_id || "");
    }

    const payments = loan.payment_history || loan.payments || [];
    document.getElementById("manage-payments-count").textContent =
      `${payments.length} ${payments.length === 1 ? "movimiento" : "movimientos"}`;
    const paymentsList = document.getElementById("manage-payments-list");
    const methodLabels = { cash: "Efectivo", transfer: "Transferencia", other: "Otro" };
    if (!payments.length) {
      paymentsList.innerHTML = `<p class="muted">Aún no se han registrado abonos individuales en este préstamo.</p>`;
    } else {
      paymentsList.innerHTML = payments.map((payment) => {
        const isReversal = payment.direction === "reversal";
        const isReversed = Boolean(payment.is_reversed);
        const receiptText =
          `Comprobante de abono - ${state.tenant ? state.tenant.tenant_name : "TuNegocio"}\n` +
          `Cliente: ${name}\n` +
          `Valor abonado: ${money(Math.abs(Number(payment.amount || 0)))}\n` +
          `Fecha: ${displayDate(payment.date)}\n` +
          `Saldo pendiente actual: ${money(balance)}`;
        const receiptBtn = !isReversal && !isReversed
          ? `<a class="button button-quiet button-xs" target="_blank" rel="noopener" href="${escapeHtml(whatsappUrl(phone, receiptText))}">📲 Recibo WhatsApp</a>`
          : "";
        const reverseControl = !isReversal
          ? (isReversed
              ? `<span class="status-pill status-cancelled">Reversado</span>`
              : (isOwner
                  ? `<button class="button button-danger-outline button-xs" type="button" data-reverse-payment="${escapeHtml(payment.id)}">↩ Reversar pago</button>`
                  : `<span class="status-pill status-paid">Aplicado</span>`))
          : `<span class="status-pill status-delinquent">Reversa</span>`;
        return (
          `<article class="payment-history-item ${isReversed ? "is-reversed" : ""}">` +
          `<div class="payment-history-meta">` +
          `<strong>${money(payment.amount)} · ${escapeHtml(isReversal ? "Reversa contable" : "Abono recibido")}</strong>` +
          `<span>${escapeHtml(displayDate(payment.date))} · ${escapeHtml(methodLabels[payment.method] || payment.method || "Efectivo")}` +
          `${payment.collector_name ? ` · Cobrador: ${escapeHtml(payment.collector_name)}` : ""}</span>` +
          `</div>` +
          `<div class="payment-history-actions">${receiptBtn}${reverseControl}</div>` +
          `</article>`
        );
      }).join("");
    }

    const schedule = loan.installment_schedule || loan.installments || [];
    document.getElementById("manage-installments-count").textContent = String(schedule.length);
    document.getElementById("manage-installments-rows").innerHTML = schedule.map((inst) => {
      const pending = inst.pending_amount ?? (Number(inst.amount_due || 0) - Number(inst.amount_paid || 0));
      return (
        `<tr><td>${escapeHtml(inst.number)}</td><td>${escapeHtml(displayDate(inst.due_date))}</td>` +
        `<td>${money(inst.amount_due)}</td><td>${money(inst.amount_paid)}</td>` +
        `<td>${money(pending)}</td><td>${escapeHtml(labels[inst.status] || inst.status)}</td></tr>`
      );
    }).join("");

    const ownerActions = document.getElementById("manage-owner-actions");
    if (ownerActions) {
      ownerActions.hidden = !isManager;
    }

    if (!dialog.open) dialog.showModal();
  }

  async function reversePayment(paymentId, button) {
    setBusy(button, true, "Reversando…");
    try {
      await api(`/loan-payments/${paymentId}/reverse/`, {
        method: "POST",
        body: JSON.stringify({ reason: "Reversado desde el portal" }),
      });
      const tasks = [loadDashboard()];
      if (state.view === "customer-summary" || state.customerSummary) {
        tasks.push(loadCustomerSummary(state.customerSummaryPage || 1));
      }
      await Promise.all(tasks);
      const manageDialog = document.getElementById("loan-manage-dialog");
      if (manageDialog && manageDialog.open && state.activeManagedLoanId) {
        openLoanManageDialog(state.activeManagedLoanId);
      }
      showToast("Pago reversado correctamente.");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  }

  async function assignLoanCollector(loanId, collectorId, controlEl) {
    if (controlEl) controlEl.disabled = true;
    try {
      await api(`/loans/${loanId}/`, {
        method: "PATCH",
        body: JSON.stringify({ collector: collectorId || null }),
      });
      await loadDashboard();
      if (state.view === "customer-summary") {
        await loadCustomerSummary(state.customerSummaryPage || 1);
      }
      const manageDialog = document.getElementById("loan-manage-dialog");
      if (manageDialog && manageDialog.open && state.activeManagedLoanId) {
        openLoanManageDialog(state.activeManagedLoanId);
      }
      showToast("Cobrador asignado al préstamo.");
    } catch (error) {
      showError(error.message);
    } finally {
      if (controlEl) controlEl.disabled = false;
    }
  }

  async function loadCustomerSummary(page = 1) {
    const form = document.getElementById("customer-summary-filters");
    const params = new URLSearchParams();
    if (form.elements.search.value.trim()) params.set("search", form.elements.search.value.trim());
    if (form.elements.start.value) params.set("start", form.elements.start.value);
    if (form.elements.end.value) params.set("end", form.elements.end.value);
    params.set("page", String(page));
    const button = document.getElementById("customer-summary-button");
    setBusy(button, true, "Buscando…");
    try {
      const report = await api(`/customer-loan-summary/?${params.toString()}`);
      state.customerSummary = report;
      state.customerSummaryPage = report.page || page;
      populateExistingCustomers();
      const rows = report.rows || [];
      const isOwner = state.role === "owner";
      const isManager = (rank[state.role] || 0) >= rank.manager;
      document.getElementById("customer-summary-empty").hidden = rows.length > 0;
      document.getElementById("customer-summary-rows").innerHTML = rows.map((customer) => {
        const loans = (customer.loans || []).map((loan) => {
          const installments = (loan.installments || []).map((installment) =>
            `<tr><td>${escapeHtml(installment.number)}</td><td>${escapeHtml(displayDate(installment.due_date))}</td>` +
            `<td>${money(installment.amount_due)}</td><td>${money(installment.amount_paid)}</td>` +
            `<td>${money(installment.pending_amount)}</td><td>${escapeHtml(labels[installment.status] || installment.status)}</td></tr>`
          ).join("");
          const paymentHistory = (loan.payments || []).map((payment) => {
            let actionCell = "";
            if (payment.direction === "payment") {
              if (payment.is_reversed) {
                actionCell = `<span class="muted">Reversado</span>`;
              } else if (isOwner) {
                actionCell = `<button class="button button-quiet button-xs" type="button" data-reverse-payment="${escapeHtml(payment.id)}">Reversar</button>`;
              }
            }
            return `<tr><td>${escapeHtml(displayDate(payment.date))}</td><td>${money(payment.amount)}</td>` +
              `<td>${escapeHtml(payment.direction === "reversal" ? "Reversa" : "Abono")}</td>` +
              `<td>${escapeHtml(payment.collector_name || "")}</td><td>${escapeHtml(payment.method || "")}</td>` +
              `<td>${actionCell}</td></tr>`;
          }).join("");
          const collectorOptions = [
            `<option value="">Sin cobrador asignado</option>`,
            ...state.employees.map((emp) => {
              const label = emp.full_name || emp.email || `Cobrador ${emp.id}`;
              const selected = String(emp.id) === String(loan.collector_id || "") ? " selected" : "";
              return `<option value="${escapeHtml(emp.id)}"${selected}>Cobrador: ${escapeHtml(label)}</option>`;
            }),
          ].join("");
          const collectorControl = isManager
            ? `<select class="collector-select-inline" data-assign-loan="${escapeHtml(loan.id)}" aria-label="Asignar cobrador">${collectorOptions}</select>`
            : (loan.collector_name ? `<span class="muted">Cobrador: ${escapeHtml(loan.collector_name)}</span>` : "");
          return `<section class="amortization-loan"><div class="amortization-header"><h4>Préstamo ${escapeHtml(loan.date)} · ${escapeHtml(labels[loan.frequency] || loan.frequency)}</h4>` +
            `<div class="business-code-actions">${collectorControl}<button class="button button-outline button-xs" type="button" data-manage-loan="${escapeHtml(loan.id)}">🧾 Gestionar préstamo</button></div></div>` +
            `<p>Capital ${money(loan.principal)} · Interés ${money(loan.interest)} · Papelería ${money(loan.paperwork)} · Saldo ${money(loan.balance)}</p>` +
            `<div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>CUOTA</th><th>VENCIMIENTO</th><th>VALOR</th><th>PAGADO</th><th>PENDIENTE</th><th>ESTADO</th></tr></thead><tbody>${installments}</tbody></table></div>` +
            `<h5>Historial de pagos</h5><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>FECHA</th><th>VALOR NETO</th><th>MOVIMIENTO</th><th>COBRADOR</th><th>MÉTODO</th><th>ACCIÓN</th></tr></thead><tbody>${paymentHistory}</tbody></table></div></section>`;
        }).join("");
        const phone = customer.customer_phone || "";
        const contactChips = [
          isManager
            ? `<button class="contact-chip" type="button" data-renew-customer="1" ` +
              `data-full-name="${escapeHtml(customer.customer_name || "")}" ` +
              `data-document-id="${escapeHtml(customer.customer_document || "")}" ` +
              `data-phone="${escapeHtml(phone)}" ` +
              `data-neighborhood="${escapeHtml(customer.customer_neighborhood || "")}">＋ Prestar / Renovar</button>`
            : "",
          cleanPhoneForWhatsApp(phone)
            ? `<a class="contact-chip" target="_blank" rel="noopener" href="${escapeHtml(whatsappUrl(phone, `Hola ${customer.customer_name}, te escribimos de ${state.tenant ? state.tenant.tenant_name : "TuNegocio"}.`))}">💬 WhatsApp</a>`
            : "",
        ].filter(Boolean).join("");
        const firstLoanId = (customer.loans && customer.loans[0] && customer.loans[0].id) || "";
        const amortBtn = firstLoanId
          ? `<button class="button button-primary button-xs" type="button" data-open-amortization="${escapeHtml(firstLoanId)}">📊 Ver amortización</button>`
          : `<span class="muted">Sin préstamos</span>`;
        return `<tr><td><strong>${escapeHtml(customer.customer_name)}</strong>` +
          (contactChips ? `<div class="customer-cell-meta">${contactChips}</div>` : "") +
          `</td><td>${escapeHtml(customer.loan_count)}</td>` +
          `<td>${money(customer.principal)}</td><td>${money(customer.paperwork)}</td><td>${money(customer.interest)}</td>` +
          `<td>${money(customer.total_payable)}</td><td>${money(customer.collected)}</td><td><strong>${money(customer.balance)}</strong></td>` +
          `<td>${amortBtn}</td></tr>`;
      }).join("");
      const totals = report.totals || {};
      document.getElementById("customer-summary-totals").innerHTML = rows.length
        ? `<tr><th>TOTALES</th><td>${escapeHtml(totals.loan_count || 0)}</td><td>${money(totals.principal)}</td>` +
          `<td>${money(totals.paperwork)}</td><td>${money(totals.interest)}</td><td>${money(totals.total_payable)}</td>` +
          `<td>${money(totals.collected)}</td><td>${money(totals.balance)}</td><td></td></tr>`
        : "";
      const pagination = document.getElementById("customer-summary-pagination");
      if (pagination) {
        const totalPages = report.total_pages || 1;
        const currentPage = report.page || 1;
        pagination.hidden = totalPages <= 1;
        document.getElementById("customer-summary-page-info").textContent =
          `Página ${currentPage} de ${totalPages} (${report.customer_count || 0} clientes)`;
        document.getElementById("customer-summary-prev").disabled = !report.has_previous;
        document.getElementById("customer-summary-next").disabled = !report.has_next;
      }
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  }

  function showView(view) {
    if (state.role === "employee" && ["collections", "ledger", "employee-requests", "customer-summary", "new-loan"].includes(view)) {
      view = "home";
    } else if ((view === "ledger" || view === "employee-requests") && state.role !== "owner") {
      view = "home";
    }
    if (view !== "amortization" && state.view !== "amortization") {
      state.previousView = view;
    }
    state.view = view;
    const isEmployee = state.role === "employee";
    const titles = {
      home: [isEmployee ? "Mi ruta de hoy" : "Resumen", isEmployee ? "Cuotas por cobrar hoy y personas cobradas en tu jornada." : "Una mirada clara a tus préstamos."],
      collections: ["Cobros de hoy", "Cuotas pendientes de tu cartera."],
      ledger: ["Libro de cartera", "Consulta el formato del Excel por período y frecuencia."],
      cashflow: ["Caja y gastos", isEmployee ? "Registra tus gastos diarios y consulta tus gastos del período." : "Controla el dinero inicial, los cobros, los préstamos y los gastos."],
      "customer-summary": ["Resumen por cliente", "Consulta la cartera consolidada y abre la amortización de cualquier cliente."],
      amortization: ["Amortización del cliente", "Plan de cuotas móvil, historial de pagos y opciones para compartir o descargar."],
      "employee-requests": ["Solicitudes de empleados", "Aprueba o rechaza las solicitudes de acceso al negocio."],
      trash: ["Papelera de préstamos", "Préstamos eliminados. Puedes consultarlos o restaurarlos al cobro activo."],
      "new-loan": ["Nuevo préstamo", "Registra un cliente o renueva su crédito en segundos."],
    };
    document.getElementById("view-title").textContent = titles[view][0];
    document.getElementById("view-subtitle").textContent = titles[view][1];
    document.querySelectorAll(".view-panel").forEach((panel) => {
      panel.hidden = panel.id !== `${view}-view`;
    });
    document.querySelectorAll("[data-view]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.view === view);
    });
    if (view === "new-loan" && (rank[state.role] || 0) >= rank.manager && !state.employees.length) {
      loadEmployees();
    }
    if (view === "ledger") loadLedger();
    if (view === "cashflow") {
      if (state.role === "employee") {
        const expDate = (document.getElementById("expense-date") && document.getElementById("expense-date").value) || localDateValue();
        loadExpenses(expDate, expDate);
      } else {
        loadCashSummary();
      }
    }
    if (view === "customer-summary") loadCustomerSummary();
    if (view === "employee-requests") loadEmployeeRequests();
    if (view === "trash") loadTrash();
    clearMessages();
  }

  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");
  const registerToggle = document.getElementById("show-register");
  const authTabLogin = document.getElementById("auth-tab-login");
  const authTabRegister = document.getElementById("auth-tab-register");

  function syncRegisterRoleFields() {
    const roleInput = document.getElementById("register-role-input");
    const role = (roleInput && roleInput.value) || "collector";
    const isOwnerRole = role === "owner";
    const joinField = document.getElementById("register-join-code-field");
    const joinInput = document.getElementById("register-join-code");
    const bizField = document.getElementById("register-business-name-field");
    const bizInput = document.getElementById("register-business-name");
    const submitLabel = document.getElementById("register-submit-label");
    document.querySelectorAll("[data-register-role]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.registerRole === role);
    });
    if (joinField) joinField.hidden = isOwnerRole;
    if (joinInput) joinInput.required = !registerForm.hidden && !isOwnerRole;
    if (bizField) bizField.hidden = !isOwnerRole;
    if (bizInput) bizInput.required = !registerForm.hidden && isOwnerRole;
    if (submitLabel) {
      submitLabel.textContent = isOwnerRole
        ? "Crear cuenta y mi negocio"
        : "Crear cuenta y enviar solicitud";
    }
    if (!registerForm.hidden) {
      document.getElementById("login-title").innerHTML = isOwnerRole
        ? "Crea tu cuenta<br>y tu negocio."
        : "Crea tu cuenta<br>de cobrador.";
    }
  }

  const regPwdInput = document.getElementById("register-password");
  const regPwdConfirmInput = document.getElementById("register-password-confirm");
  function updatePasswordChecklist() {
    const pwd = regPwdInput ? regPwdInput.value : "";
    const confirm = regPwdConfirmInput ? regPwdConfirmInput.value : "";
    const lenOk = pwd.length >= 8;
    const mixOk = /[A-Za-z]/.test(pwd) && /[0-9]/.test(pwd);
    const matchOk = pwd.length >= 8 && pwd === confirm;
    const setCheck = (id, ok, text) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.classList.toggle("is-met", ok);
      el.textContent = `${ok ? "✓" : "○"} ${text}`;
    };
    setCheck("pwd-check-len", lenOk, "Mínimo 8 caracteres");
    setCheck("pwd-check-mix", mixOk, "Incluye letras y números");
    setCheck("pwd-check-match", matchOk, "Las contraseñas coinciden");
  }
  if (regPwdInput) regPwdInput.addEventListener("input", updatePasswordChecklist);
  if (regPwdConfirmInput) regPwdConfirmInput.addEventListener("input", updatePasswordChecklist);

  document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.togglePassword);
      if (!input) return;
      const showPlain = input.type === "password";
      input.type = showPlain ? "text" : "password";
      btn.textContent = showPlain ? "Ocultar" : "Mostrar";
    });
  });

  function toggleRegistration(show) {
    clearMessages();
    loginForm.hidden = show;
    loginForm.querySelectorAll("input, button").forEach((field) => { field.disabled = show; });
    registerForm.hidden = !show;
    registerForm.querySelectorAll("input, button").forEach((field) => { field.disabled = !show; });
    if (registerToggle) registerToggle.hidden = show;
    if (authTabLogin) {
      authTabLogin.classList.toggle("is-active", !show);
      authTabLogin.setAttribute("aria-selected", String(!show));
    }
    if (authTabRegister) {
      authTabRegister.classList.toggle("is-active", show);
      authTabRegister.setAttribute("aria-selected", String(show));
    }
    const authSubtitle = document.getElementById("auth-subtitle");
    if (!show) {
      document.getElementById("login-title").innerHTML = "Tus préstamos,<br>más cerca.";
      if (authSubtitle) {
        authSubtitle.textContent = "Consulta saldos, cobra en ruta y lleva el control diario desde cualquier celular o computador.";
      }
    } else if (authSubtitle) {
      authSubtitle.textContent = "Regístrate como cobrador con el código de tu jefe o crea tu propio negocio de préstamos.";
    }
    syncRegisterRoleFields();
    updatePasswordChecklist();
  }

  if (registerToggle) registerToggle.addEventListener("click", () => toggleRegistration(true));
  if (authTabLogin) authTabLogin.addEventListener("click", () => toggleRegistration(false));
  if (authTabRegister) authTabRegister.addEventListener("click", () => toggleRegistration(true));
  document.getElementById("cancel-register").addEventListener("click", () => toggleRegistration(false));
  document.querySelectorAll("[data-register-role]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const roleInput = document.getElementById("register-role-input");
      if (roleInput) roleInput.value = btn.dataset.registerRole;
      syncRegisterRoleFields();
    });
  });

  function buildBusinessSlug(name) {
    const base = String(name || "negocio")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 38) || "negocio";
    const suffix = Math.random().toString(36).slice(2, 7);
    return `${base}-${suffix}`;
  }

  async function createBusiness(businessName, businessType = "prestamista") {
    const response = await rawRequest("/tenants/", {
      method: "POST",
      body: JSON.stringify({
        name: businessName,
        slug: buildBusinessSlug(businessName),
        business_type: businessType,
      }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(errorMessage(data, "No se pudo crear el negocio."));
    return data;
  }
  const createLendingBusiness = createBusiness;

  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessages();
    const button = registerForm.querySelector('button[type="submit"]');
    const form = new FormData(registerForm);
    const username = String(form.get("username") || "").trim();
    const email = String(form.get("email") || "").trim().toLowerCase();
    const fullName = String(form.get("full_name") || "").trim();
    const password = String(form.get("password") || "");
    const passwordConfirm = String(form.get("password_confirm") || "");
    const registerRole = String(form.get("register_role") || "collector");
    const joinCode = String(form.get("join_code") || "").trim().toUpperCase();
    const businessName = String(form.get("business_name") || "").trim();

    if (password.length < 8) {
      showError("La contraseña debe tener al menos 8 caracteres.");
      return;
    }
    if (/^\d+$/.test(password)) {
      showError("Por seguridad, la contraseña no puede ser solo números; incluye al menos una letra.");
      return;
    }
    if (password !== passwordConfirm) {
      showError("Las contraseñas no coinciden. Verifícalas e inténtalo de nuevo.");
      return;
    }

    setBusy(button, true, "Creando cuenta…");
    try {
      const registration = await rawRequest("/auth/register/", {
        method: "POST",
        body: JSON.stringify({
          username,
          email,
          full_name: fullName,
          password,
          password_confirm: passwordConfirm,
          register_role: registerRole,
          join_code: registerRole === "collector" ? joinCode : "",
          business_name: registerRole === "owner" ? (businessName || `Cartera de ${fullName || username}`) : "",
        }),
      }, false);
      const registrationData = await registration.json().catch(() => null);
      if (!registration.ok) throw new Error(errorMessage(registrationData, "No se pudo crear la cuenta."));

      state.access = registrationData.access;
      state.refresh = registrationData.refresh;
      state.username = registrationData.username || username;
      state.tenant = null;
      sessionStorage.setItem("loan_access", state.access);
      sessionStorage.setItem("loan_refresh", state.refresh);
      sessionStorage.setItem("loan_username", state.username);

      registerForm.reset();
      loginForm.reset();
      updatePasswordChecklist();
      toggleRegistration(false);

      if (registerRole === "owner") {
        if (registrationData.tenant) {
          await openWorkspace(registrationData.tenant);
          showToast("¡Cuenta y negocio creados! Ya puedes operar.");
          return;
        }
        const memberships = getRows(await api("/auth/me/tenants/"));
        if (memberships.length) {
          await openWorkspace(memberships[0]);
          showToast("¡Cuenta y negocio creados! Ya puedes operar.");
          return;
        }
        await loadTenants();
        return;
      }

      setScreen("tenants");
      const targetName = (registrationData.join_request && registrationData.join_request.tenant_name) || "el negocio";
      document.getElementById("tenant-options").innerHTML =
        `<p class="muted">Solicitud enviada a <strong>${escapeHtml(targetName)}</strong>. Podrás entrar cuando el propietario la apruebe en "Solicitudes de empleados".</p>`;
      document.getElementById("tenant-join-code").value = "";
      document.getElementById("tenant-status").textContent =
        `Cuenta creada y solicitud enviada a ${targetName}.`;
      document.getElementById("tenant-status").hidden = false;
      showToast("Cuenta creada y solicitud enviada.");
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
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const button = formElement.querySelector('button[type="submit"]');
    setBusy(button, true, "Enviando…");
    try {
      const response = await rawRequest("/tenant-join-requests/", {
        method: "POST",
        body: JSON.stringify({ join_code: String(form.get("join_code") || "").trim().toUpperCase() }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(data, "No se pudo enviar la solicitud."));
      formElement.reset();
      document.getElementById("tenant-status").textContent =
        `Solicitud enviada a ${data.tenant_name}. Espera la aprobación del propietario.`;
      document.getElementById("tenant-status").hidden = false;
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  const tenantCreateForm = document.getElementById("tenant-create-form");
  if (tenantCreateForm) {
    tenantCreateForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearMessages();
      const form = new FormData(tenantCreateForm);
      const businessName = String(form.get("name") || "").trim();
      const button = tenantCreateForm.querySelector('button[type="submit"]');
      setBusy(button, true, "Creando negocio…");
      try {
        await createLendingBusiness(businessName);
        tenantCreateForm.reset();
        await loadTenants();
        showToast("Negocio de préstamos creado correctamente.");
      } catch (error) {
        showError(error.message);
      } finally {
        setBusy(button, false);
      }
    });
  }

  document.getElementById("cash-summary-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadCashSummary();
  });
  document.getElementById("customer-summary-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadCustomerSummary(1);
  });
  document.getElementById("customer-summary-prev").addEventListener("click", () => {
    const current = state.customerSummaryPage || 1;
    if (current > 1) loadCustomerSummary(current - 1);
  });
  document.getElementById("customer-summary-next").addEventListener("click", () => {
    const current = state.customerSummaryPage || 1;
    loadCustomerSummary(current + 1);
  });

  const cashOpeningAmountInput = document.getElementById("cash-opening-amount");
  const cashOpeningPreview = document.getElementById("cash-opening-preview");
  function updateCashOpeningPreview() {
    if (!cashOpeningPreview || !cashOpeningAmountInput) return;
    const val = Number(cashOpeningAmountInput.value || 0);
    cashOpeningPreview.textContent = `Valor a registrar: ${money(val)}`;
  }
  if (cashOpeningAmountInput) {
    cashOpeningAmountInput.addEventListener("input", updateCashOpeningPreview);
  }

  document.getElementById("cash-opening-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const button = formElement.querySelector('button[type="submit"]');
    const data = {
      date: form.get("date"),
      opening_amount: form.get("opening_amount"),
      notes: form.get("notes") || "",
    };
    if ((rank[state.role] || 0) >= rank.manager) data.collector = form.get("collector");
    setBusy(button, true, "Guardando…");
    try {
      await api("/collector-daily-cash/", { method: "POST", body: JSON.stringify(data) });
      formElement.reset();
      document.getElementById("cash-opening-date").value = localDateValue();
      updateCashOpeningPreview();
      await loadCashSummary();
      showToast("Dinero inicial registrado.");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  const expenseCategorySelect = document.getElementById("expense-category");
  const expenseDescriptionInput = document.getElementById("expense-description");
  const expenseNotesInput = document.getElementById("expense-notes");
  const expenseDescriptionLabel = document.getElementById("expense-description-label");
  const expenseNotesLabel = document.getElementById("expense-notes-label");
  const expenseAmountInput = document.getElementById("expense-amount");
  const expenseAmountPreview = document.getElementById("expense-amount-preview");

  function syncExpenseCategoryFields() {
    const isOther = Boolean(expenseCategorySelect && expenseCategorySelect.value === "other");
    if (expenseDescriptionInput) expenseDescriptionInput.required = isOther;
    if (expenseNotesInput) expenseNotesInput.required = isOther;
    if (expenseDescriptionLabel) {
      expenseDescriptionLabel.textContent = isOther
        ? "Descripción (obligatorio)"
        : "Descripción (opcional)";
    }
    if (expenseNotesLabel) {
      expenseNotesLabel.textContent = isOther
        ? "Observaciones (obligatorio)"
        : "Observaciones (opcional)";
    }
  }
  function updateExpenseAmountPreview() {
    if (!expenseAmountPreview || !expenseAmountInput) return;
    const val = Number(expenseAmountInput.value || 0);
    expenseAmountPreview.textContent = `Valor a registrar: ${money(val)}`;
  }
  if (expenseCategorySelect) {
    expenseCategorySelect.addEventListener("change", syncExpenseCategoryFields);
    syncExpenseCategoryFields();
  }
  if (expenseAmountInput) {
    expenseAmountInput.addEventListener("input", updateExpenseAmountPreview);
  }
  const expenseDateInput = document.getElementById("expense-date");
  if (expenseDateInput) {
    expenseDateInput.addEventListener("change", () => {
      if (state.role === "employee" && state.view === "cashflow") {
        const d = expenseDateInput.value || localDateValue();
        loadExpenses(d, d);
      }
    });
  }

  document.getElementById("expense-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const button = formElement.querySelector('button[type="submit"]');
    const data = {
      spent_on: form.get("spent_on"),
      category: form.get("category"),
      description: String(form.get("description") || "").trim(),
      amount: form.get("amount"),
      notes: String(form.get("notes") || "").trim(),
    };
    if ((rank[state.role] || 0) >= rank.manager) data.collector = form.get("collector");
    setBusy(button, true, "Guardando…");
    try {
      await api("/collector-expenses/", { method: "POST", body: JSON.stringify(data) });
      formElement.reset();
      document.getElementById("expense-date").value = localDateValue();
      syncExpenseCategoryFields();
      updateExpenseAmountPreview();
      if (state.role === "employee") {
        const expDate = document.getElementById("expense-date").value || localDateValue();
        await loadExpenses(expDate, expDate);
      } else {
        await loadCashSummary();
      }
      showToast("Gasto registrado.");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

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
    elements.dialog.dataset.customerPhone = button.dataset.paymentPhone || (loan && loan.customer_phone) || "";
    elements.dialog.dataset.customerName = button.dataset.paymentName || (loan && loan.customer_name) || "Cliente";
    const amountInput = document.getElementById("payment-amount");
    amountInput.value = suggested > 0 ? suggested.toFixed(2) : "";
    amountInput.max = balance.toFixed(2);
    amountInput.dataset.suggested = suggested > 0 ? suggested.toFixed(2) : "";
    amountInput.dataset.balance = balance > 0 ? balance.toFixed(2) : "";
    const chipSuggested = document.getElementById("chip-suggested-amount");
    const chipBalance = document.getElementById("chip-full-balance");
    if (chipSuggested) chipSuggested.textContent = `Cuota: ${money(suggested)}`;
    if (chipBalance) chipBalance.textContent = `Saldo: ${money(balance)}`;
    document.getElementById("payment-balance").textContent = money(balance);
    document.getElementById("payment-suggestion").textContent =
      suggested > 0
        ? `Cuota sugerida: ${money(suggested)}. Puedes cambiarla por el valor recibido.`
        : "No hay saldo pendiente para cobrar.";
    if ((rank[state.role] || 0) >= rank.manager) {
      const collectorSelect = document.getElementById("payment-collector");
      document.getElementById("payment-collector-field").hidden = false;
      collectorSelect.required = true;
      if (loan && (loan.collector || loan.collector_id)) {
        collectorSelect.value = String(loan.collector || loan.collector_id);
      }
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
      let delay = 2000;
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
          delay = 2000;
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
          if (!signal.aborted) {
            await new Promise((resolve) => window.setTimeout(resolve, 6000));
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
    let blockId = "";
    let eventName = "";
    let data = "";
    block.split(/\r?\n/).forEach((line) => {
      if (line.startsWith("id:")) blockId = line.slice(3).trim();
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      if (line.startsWith("data:")) data += line.slice(5).trim();
    });
    if (blockId) {
      const isZeroReady = blockId.endsWith("|00000000-0000-0000-0000-000000000000");
      if (!isZeroReady || !state.lastEventId) {
        state.lastEventId = blockId;
      }
    }
    if (!["loan.payment_received", "loan.payment_reversed"].includes(eventName) || !data) return;
    const event = JSON.parse(data);
    if (event.id) {
      const key = `${eventName}:${event.id}`;
      if (state.seenEventIds.has(key)) return;
      state.seenEventIds.add(key);
    }
    const payload = event.payload || {};
    if (eventName === "loan.payment_received") {
      showToast(`Nuevo cobro recibido: ${money(payload.amount)}.`);
    } else {
      showToast(`Cobro reversado: ${money(payload.amount)}.`);
    }
    loadDashboard();
    if (state.view === "cashflow") {
      if (state.role === "employee") {
        const expDate = (document.getElementById("expense-date") && document.getElementById("expense-date").value) || localDateValue();
        loadExpenses(expDate, expDate);
      } else {
        loadCashSummary();
      }
    }
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
    state.collectedToday = { items: [], totalAmount: 0 };
    state.cashSummary = null;
    const expenseRows = document.getElementById("expense-rows");
    if (expenseRows) expenseRows.replaceChildren();
    const cashSummaryRows = document.getElementById("cash-summary-rows");
    if (cashSummaryRows) cashSummaryRows.replaceChildren();
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
  document.getElementById("copy-join-code").addEventListener("click", async () => {
    const code = document.getElementById("business-join-code").textContent;
    if (!code || code === "—") return;
    try {
      await navigator.clipboard.writeText(code);
      showToast("Código del negocio copiado.");
    } catch (error) {
      showToast(`Código del negocio: ${code}`);
    }
  });
  document.getElementById("refresh-button").addEventListener("click", loadDashboard);
  document.getElementById("refresh-employee-requests").addEventListener("click", loadEmployeeRequests);
  document.addEventListener("click", (event) => {
    const accept = event.target.closest("[data-request-accept]");
    const reject = event.target.closest("[data-request-reject]");
    const reverseBtn = event.target.closest("[data-reverse-payment]");
    const renewBtn = event.target.closest("[data-renew-customer]");
    const manageBtn = event.target.closest("[data-manage-loan]");
    const editOpeningBtn = event.target.closest("[data-edit-opening-collector]");
    if (accept) decideEmployeeRequest(accept.dataset.requestAccept, "accept", accept);
    if (reject) decideEmployeeRequest(reject.dataset.requestReject, "reject", reject);
    if (reverseBtn) reversePayment(reverseBtn.dataset.reversePayment, reverseBtn);
    if (manageBtn) openLoanManageDialog(manageBtn.dataset.manageLoan);
    if (editOpeningBtn) {
      const collectorSelect = document.getElementById("cash-opening-collector");
      const amountInput = document.getElementById("cash-opening-amount");
      const dateInput = document.getElementById("cash-opening-date");
      const cashDateFilter = document.getElementById("cash-date");
      if (collectorSelect) collectorSelect.value = editOpeningBtn.dataset.editOpeningCollector;
      if (dateInput && cashDateFilter && cashDateFilter.value) dateInput.value = cashDateFilter.value;
      if (amountInput) {
        amountInput.value = Number(editOpeningBtn.dataset.editOpeningAmount || 0);
        updateCashOpeningPreview();
        amountInput.focus();
        amountInput.select();
      }
      showToast("Modifica el dinero inicial y pulsa Guardar.");
    }
    if (renewBtn) {
      const manageDialog = document.getElementById("loan-manage-dialog");
      if (manageDialog && manageDialog.open) manageDialog.close();
      prefillCustomerForm({
        fullName: renewBtn.dataset.fullName || "",
        documentId: renewBtn.dataset.documentId || "",
        phone: renewBtn.dataset.phone || "",
        neighborhood: renewBtn.dataset.neighborhood || "",
      });
      showView("new-loan");
      showToast(`Datos de ${renewBtn.dataset.fullName || "cliente"} cargados para renovar.`);
    }
  });
  document.addEventListener("change", (event) => {
    const assignSelect = event.target.closest("[data-assign-loan]");
    if (assignSelect) {
      assignLoanCollector(assignSelect.dataset.assignLoan, assignSelect.value, assignSelect);
    }
  });
  document.getElementById("logout-button").addEventListener("click", () => logout());
  const topbarLogoutBtn = document.getElementById("topbar-logout-button");
  if (topbarLogoutBtn) topbarLogoutBtn.addEventListener("click", () => logout());
  document.getElementById("topbar-avatar").addEventListener("click", () => loadTenants());
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

  const ratesPer100k = { daily: 4000, weekly: 20000, biweekly: 40000 };
  function updateLoanEstimate() {
    const principal = Number(document.getElementById("principal").value || 0);
    const rate = Number(document.getElementById("interest-rate").value || 0);
    const freq = document.getElementById("frequency").value || "daily";
    const total = principal + principal * rate / 100;
    const collectionPerInstallment = principal * (ratesPer100k[freq] || 4000) / 100000;
    document.getElementById("preview-total").textContent = money(total);
    const previewInstallment = document.getElementById("preview-installment");
    if (previewInstallment) {
      previewInstallment.textContent = money(collectionPerInstallment);
    }
  }
  ["principal", "interest-rate"].forEach((id) => {
    document.getElementById(id).addEventListener("input", updateLoanEstimate);
  });
  document.getElementById("frequency").addEventListener("change", (event) => {
    document.getElementById("preview-frequency").textContent =
      labels[event.currentTarget.value] || event.currentTarget.value;
    updateLoanEstimate();
  });
  const loanQuickSearch = document.getElementById("loan-quick-search");
  if (loanQuickSearch) loanQuickSearch.addEventListener("input", renderLoans);
  const loanCollectorFilter = document.getElementById("loan-collector-filter");
  if (loanCollectorFilter) loanCollectorFilter.addEventListener("change", renderLoans);
  const collectionQuickSearch = document.getElementById("collection-quick-search");
  if (collectionQuickSearch) collectionQuickSearch.addEventListener("input", renderCollections);
  const ownerDailyDateInput = document.getElementById("owner-daily-date");
  if (ownerDailyDateInput) ownerDailyDateInput.addEventListener("change", renderOwnerDailyCollections);
  const ownerDailyCollectorSelect = document.getElementById("owner-daily-collector");
  if (ownerDailyCollectorSelect) ownerDailyCollectorSelect.addEventListener("change", renderOwnerDailyCollections);
  const ownerDailyTodayBtn = document.getElementById("owner-daily-today");
  if (ownerDailyTodayBtn) {
    ownerDailyTodayBtn.addEventListener("click", () => {
      ownerDailyDateInput.value = localDateValue();
      renderOwnerDailyCollections();
    });
  }
  const ownerDailyYesterdayBtn = document.getElementById("owner-daily-yesterday");
  if (ownerDailyYesterdayBtn) {
    ownerDailyYesterdayBtn.addEventListener("click", () => {
      const d = new Date();
      d.setDate(d.getDate() - 1);
      ownerDailyDateInput.value = localDateValue(d);
      renderOwnerDailyCollections();
    });
  }
  const homeCollectionQuickSearch = document.getElementById("home-collection-quick-search");
  if (homeCollectionQuickSearch) homeCollectionQuickSearch.addEventListener("input", renderCollections);
  const existingCustomerSelect = document.getElementById("existing-customer-select");
  if (existingCustomerSelect) {
    existingCustomerSelect.addEventListener("change", (event) => {
      const opt = event.currentTarget.selectedOptions[0];
      if (!opt || !opt.value) {
        prefillCustomerForm({});
        return;
      }
      prefillCustomerForm({
        fullName: opt.dataset.fullName || "",
        documentId: opt.dataset.documentId || "",
        phone: opt.dataset.phone || "",
        neighborhood: opt.dataset.neighborhood || "",
      });
    });
  }
  const clearRenewalBtn = document.getElementById("clear-renewal-button");
  if (clearRenewalBtn) {
    clearRenewalBtn.addEventListener("click", () => {
      prefillCustomerForm({});
      showToast("Formulario listo para nuevo cliente.");
    });
  }
  const chipSuggested = document.getElementById("chip-suggested-amount");
  if (chipSuggested) {
    chipSuggested.addEventListener("click", () => {
      const amountInput = document.getElementById("payment-amount");
      if (amountInput.dataset.suggested) amountInput.value = amountInput.dataset.suggested;
    });
  }
  const chipBalance = document.getElementById("chip-full-balance");
  if (chipBalance) {
    chipBalance.addEventListener("click", () => {
      const amountInput = document.getElementById("payment-amount");
      if (amountInput.dataset.balance) amountInput.value = amountInput.dataset.balance;
    });
  }

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
        phone: String(form.get("phone") || "").trim(),
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
      document.getElementById("start-date").value = localDateValue();
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

  const periodToFrequency = {
    day: "daily",
    week: "weekly",
    fortnight: "biweekly",
    month: "monthly",
    year: "all",
  };

  const frequencyToPeriod = {
    daily: "day",
    weekly: "week",
    biweekly: "fortnight",
    monthly: "month",
  };

  document.getElementById("ledger-period").addEventListener("change", (event) => {
    const period = event.target.value;
    const freqSelect = document.getElementById("ledger-frequency");
    if (periodToFrequency[period]) {
      freqSelect.value = periodToFrequency[period];
    }
    loadLedger();
  });

  document.getElementById("ledger-frequency").addEventListener("change", (event) => {
    const frequency = event.target.value;
    const periodSelect = document.getElementById("ledger-period");
    if (frequency !== "all" && frequencyToPeriod[frequency]) {
      periodSelect.value = frequencyToPeriod[frequency];
    }
    loadLedger();
  });

  document.getElementById("ledger-date").addEventListener("change", () => {
    loadLedger();
  });

  async function downloadExcel(params, button) {
    setBusy(button, true, "Exportando…");
    try {
      let response = await rawRequest(`/loans/export-excel/?${params.toString()}`);
      if (response.status === 401 && state.refresh && await refreshToken()) {
        response = await rawRequest(`/loans/export-excel/?${params.toString()}`);
      }
      if (!response.ok) {
        const errData = await response.json().catch(() => null);
        throw new Error(errorMessage(errData, "No se pudo exportar el archivo Excel."));
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename = match ? match[1] : `cartera_${params.get("period") || "day"}_${params.get("date") || localDateValue()}.xlsx`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1500);
      showToast("Archivo Excel descargado correctamente.");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  }

  document.getElementById("ledger-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadLedger();
  });

  const ledgerExportBtn = document.getElementById("ledger-export-excel");
  if (ledgerExportBtn) {
    ledgerExportBtn.addEventListener("click", () => {
      const form = document.getElementById("ledger-filters");
      const params = new URLSearchParams({
        period: form.elements.period.value || "day",
        date: form.elements.date.value || localDateValue(),
        frequency: form.elements.frequency.value || "all",
      });
      downloadExcel(params, ledgerExportBtn);
    });
  }

  const cashExportBtn = document.getElementById("cash-export-excel");
  if (cashExportBtn) {
    cashExportBtn.addEventListener("click", () => {
      const form = document.getElementById("cash-summary-filters");
      const params = new URLSearchParams({
        period: form.elements.period.value || "day",
        date: form.elements.date.value || localDateValue(),
        frequency: "all",
      });
      downloadExcel(params, cashExportBtn);
    });
  }

  // Centro de exportación Excel (Modal por día, semana, quincena, mes o año)
  const excelDialog = document.getElementById("excel-export-dialog");
  const openExcelDialogBtn = document.getElementById("open-excel-dialog-button");
  const customerExportBtn = document.getElementById("customer-export-excel");
  function openExcelDialog(defaultPeriod = "day", defaultDate = localDateValue()) {
    if (!excelDialog) return;
    const periodSelect = document.getElementById("excel-modal-period");
    const dateInput = document.getElementById("excel-modal-date");
    if (periodSelect) periodSelect.value = defaultPeriod;
    if (dateInput) dateInput.value = defaultDate;
    document.querySelectorAll("[data-excel-period]").forEach((pill) => {
      pill.classList.toggle("is-active", pill.dataset.excelPeriod === defaultPeriod);
    });
    excelDialog.showModal();
  }
  if (openExcelDialogBtn) {
    openExcelDialogBtn.addEventListener("click", () => openExcelDialog("day", localDateValue()));
  }
  if (customerExportBtn) {
    customerExportBtn.addEventListener("click", () => openExcelDialog("month", localDateValue()));
  }
  document.querySelectorAll("[data-excel-period]").forEach((pill) => {
    pill.addEventListener("click", () => {
      const period = pill.dataset.excelPeriod;
      document.getElementById("excel-modal-period").value = period;
      document.querySelectorAll("[data-excel-period]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.excelPeriod === period);
      });
    });
  });
  const excelChipToday = document.getElementById("excel-chip-today");
  if (excelChipToday) {
    excelChipToday.addEventListener("click", () => {
      document.getElementById("excel-modal-date").value = localDateValue(new Date());
    });
  }
  const excelChipYesterday = document.getElementById("excel-chip-yesterday");
  if (excelChipYesterday) {
    excelChipYesterday.addEventListener("click", () => {
      const d = new Date();
      d.setDate(d.getDate() - 1);
      document.getElementById("excel-modal-date").value = localDateValue(d);
    });
  }
  const excelChipMonthStart = document.getElementById("excel-chip-month-start");
  if (excelChipMonthStart) {
    excelChipMonthStart.addEventListener("click", () => {
      const d = new Date();
      d.setDate(1);
      document.getElementById("excel-modal-date").value = localDateValue(d);
    });
  }
  const closeExcelDialog = document.getElementById("close-excel-dialog");
  const cancelExcelDialog = document.getElementById("cancel-excel-dialog");
  if (closeExcelDialog) closeExcelDialog.addEventListener("click", () => excelDialog.close());
  if (cancelExcelDialog) cancelExcelDialog.addEventListener("click", () => excelDialog.close());
  if (excelDialog) {
    excelDialog.addEventListener("click", (event) => {
      if (event.target === excelDialog) excelDialog.close();
    });
  }
  const excelExportForm = document.getElementById("excel-export-form");
  if (excelExportForm) {
    excelExportForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submitBtn = document.getElementById("submit-excel-export");
      const params = new URLSearchParams({
        period: document.getElementById("excel-modal-period").value || "day",
        date: document.getElementById("excel-modal-date").value || localDateValue(),
        frequency: document.getElementById("excel-modal-frequency").value || "all",
      });
      await downloadExcel(params, submitBtn);
      if (excelDialog && excelDialog.open) excelDialog.close();
    });
  }

  // Modal de gestión integral del préstamo
  const manageLoanDialog = document.getElementById("loan-manage-dialog");
  const closeManageLoan = document.getElementById("close-manage-loan");
  if (closeManageLoan && manageLoanDialog) {
    closeManageLoan.addEventListener("click", () => manageLoanDialog.close());
    manageLoanDialog.addEventListener("click", (event) => {
      if (event.target === manageLoanDialog) manageLoanDialog.close();
    });
  }
  const saveManageCollectorBtn = document.getElementById("save-manage-collector");
  if (saveManageCollectorBtn) {
    saveManageCollectorBtn.addEventListener("click", () => {
      if (!state.activeManagedLoanId) return;
      const collectorId = document.getElementById("manage-collector-select").value;
      assignLoanCollector(state.activeManagedLoanId, collectorId, saveManageCollectorBtn);
    });
  }

  function openLoanEditDialog(loanId) {
    const loan = findLoanById(loanId);
    const dialog = document.getElementById("loan-edit-dialog");
    if (!loan || !dialog) return;

    state.editingLoanId = String(loan.id);

    const nameInput = document.getElementById("edit-customer-name");
    const docInput = document.getElementById("edit-customer-document");
    const phoneInput = document.getElementById("edit-customer-phone");
    const neighborhoodInput = document.getElementById("edit-customer-neighborhood");

    if (nameInput) nameInput.value = loan.customer_name || "";
    if (docInput) docInput.value = loan.document_id || "";
    if (phoneInput) phoneInput.value = loan.customer_phone || "";
    if (neighborhoodInput) neighborhoodInput.value = loan.neighborhood || "";

    const principalInput = document.getElementById("edit-principal");
    const rateInput = document.getElementById("edit-interest-rate");
    const installmentsInput = document.getElementById("edit-installments");
    const freqInput = document.getElementById("edit-frequency");
    const startDateInput = document.getElementById("edit-start-date");
    const paperworkInput = document.getElementById("edit-paperwork-fee");

    if (principalInput) principalInput.value = Number(loan.principal || 0);
    if (rateInput) rateInput.value = Number(loan.interest_rate || 0);
    if (installmentsInput) installmentsInput.value = Number(loan.installments || 1);
    if (freqInput) freqInput.value = loan.frequency || "daily";
    if (startDateInput) startDateInput.value = loan.start_date || localDateValue();
    if (paperworkInput) paperworkInput.value = Number(loan.paperwork_fee ?? loan.paperwork ?? 0);

    const collectorSelect = document.getElementById("edit-collector-select");
    if (collectorSelect) {
      collectorSelect.innerHTML = `<option value="">Sin cobrador asignado</option>` +
        (state.employees || []).map((emp) => `<option value="${escapeHtml(emp.id)}">${escapeHtml(emp.full_name)}</option>`).join("");
      collectorSelect.value = String(loan.collector || loan.collector_id || "");
    }

    const totalCollected = (loan.installment_schedule || []).reduce((acc, inst) => acc + Number(inst.amount_paid || 0), 0);
    const warningEl = document.getElementById("edit-loan-payments-warning");
    const collectedValEl = document.getElementById("edit-loan-collected-val");
    if (warningEl && collectedValEl) {
      if (totalCollected > 0) {
        collectedValEl.textContent = money(totalCollected);
        warningEl.hidden = false;
      } else {
        warningEl.hidden = true;
      }
    }

    const errorEl = document.getElementById("edit-loan-error");
    if (errorEl) {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }

    dialog.showModal();
  }

  async function submitLoanEdit(event) {
    event.preventDefault();
    if (!state.editingLoanId) return;

    const saveBtn = document.getElementById("save-edit-loan-button");
    const errorEl = document.getElementById("edit-loan-error");
    if (errorEl) errorEl.hidden = true;

    const form = event.currentTarget;
    const formData = new FormData(form);

    const payload = {
      customer_details: {
        full_name: (formData.get("full_name") || "").trim(),
        document_id: (formData.get("document_id") || "").trim(),
        phone: (formData.get("phone") || "").trim(),
        neighborhood: (formData.get("neighborhood") || "").trim(),
      },
      principal: formData.get("principal"),
      interest_rate: formData.get("interest_rate"),
      installments: Number(formData.get("installments") || 1),
      frequency: formData.get("frequency"),
      start_date: formData.get("start_date"),
      paperwork_fee: formData.get("paperwork_fee") || "0",
      collector: formData.get("collector") || null,
    };

    setBusy(saveBtn, true, "Guardando…");
    try {
      await api(`/loans/${state.editingLoanId}/`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });

      const dialog = document.getElementById("loan-edit-dialog");
      if (dialog) dialog.close();

      showToast("Préstamo actualizado correctamente.");
      await loadDashboard();
      if (state.view === "customer-summary") {
        await loadCustomerSummary(state.customerSummaryPage || 1);
      }
      openLoanManageDialog(state.editingLoanId);
    } catch (err) {
      if (errorEl) {
        errorEl.textContent = err.message || "Error al actualizar préstamo.";
        errorEl.hidden = false;
      } else {
        showError(err.message);
      }
    } finally {
      setBusy(saveBtn, false);
    }
  }

  async function confirmDeleteLoan(loanId) {
    const loan = findLoanById(loanId);
    const clientName = loan ? loan.customer_name : "este cliente";
    const ok = window.confirm(
      `¿Deseas mover el préstamo de "${clientName}" a la papelera?\n\n` +
      `Dejará de aparecer en la ruta activa de cobro, pero podrás consultarlo y restaurarlo desde la sección "Papelera" cuando lo desees.`
    );
    if (!ok) return;

    const deleteBtn = document.getElementById("manage-delete-loan-btn");
    setBusy(deleteBtn, true, "Moviendo…");
    try {
      await api(`/loans/${loanId}/`, { method: "DELETE" });
      const manageDialog = document.getElementById("loan-manage-dialog");
      if (manageDialog && manageDialog.open) manageDialog.close();

      showToast("Préstamo movido a la papelera.");
      await loadDashboard();
      if (state.view === "customer-summary") {
        await loadCustomerSummary(state.customerSummaryPage || 1);
      }
    } catch (err) {
      showError(err.message || "No se pudo mover el préstamo a la papelera.");
    } finally {
      setBusy(deleteBtn, false);
    }
  }

  async function loadTrash() {
    const tbody = document.getElementById("trash-table-body");
    const emptyEl = document.getElementById("trash-empty");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="8" class="muted text-center" style="padding:2rem;">Cargando papelera…</td></tr>`;
    if (emptyEl) emptyEl.hidden = true;

    try {
      const items = await api("/loans/trash/");
      if (!items || !items.length) {
        tbody.innerHTML = "";
        if (emptyEl) emptyEl.hidden = false;
        return;
      }

      tbody.innerHTML = items.map((loan) => {
        const deletedStr = loan.deleted_at ? displayDate(loan.deleted_at.slice(0, 10)) : "—";
        return (
          `<tr>` +
          `<td><strong>${escapeHtml(loan.customer_name || "Cliente")}</strong></td>` +
          `<td>${escapeHtml(loan.document_id || "—")}</td>` +
          `<td>${escapeHtml(deletedStr)}</td>` +
          `<td>${money(loan.principal)}</td>` +
          `<td>${money(loan.total_payable)}</td>` +
          `<td><strong>${money(loan.balance)}</strong></td>` +
          `<td>${escapeHtml(loan.collector_name || "Sin asignar")}</td>` +
          `<td>` +
          `<button class="button button-outline button-xs" type="button" data-restore-loan="${escapeHtml(loan.id)}">` +
          `🔄 Restaurar` +
          `</button>` +
          `</td>` +
          `</tr>`
        );
      }).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted text-center" style="color:var(--danger, #ef4444);padding:2rem;">Error al cargar papelera: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function restoreLoan(loanId, button) {
    if (button) setBusy(button, true, "Restaurando…");
    try {
      await api(`/loans/${loanId}/restore/`, { method: "POST" });
      showToast("Préstamo restaurado exitosamente.");
      await loadTrash();
      await loadDashboard();
    } catch (err) {
      showError(err.message || "No se pudo restaurar el préstamo.");
    } finally {
      if (button) setBusy(button, false);
    }
  }

  // Event listeners for loan edit & delete buttons
  const manageEditLoanBtn = document.getElementById("manage-edit-loan-btn");
  if (manageEditLoanBtn) {
    manageEditLoanBtn.addEventListener("click", () => {
      if (state.activeManagedLoanId) openLoanEditDialog(state.activeManagedLoanId);
    });
  }
  const manageDeleteLoanBtn = document.getElementById("manage-delete-loan-btn");
  if (manageDeleteLoanBtn) {
    manageDeleteLoanBtn.addEventListener("click", () => {
      if (state.activeManagedLoanId) confirmDeleteLoan(state.activeManagedLoanId);
    });
  }
  const loanEditDialog = document.getElementById("loan-edit-dialog");
  const closeEditLoan = document.getElementById("close-edit-loan");
  const cancelEditLoan = document.getElementById("cancel-edit-loan");
  if (closeEditLoan && loanEditDialog) closeEditLoan.addEventListener("click", () => loanEditDialog.close());
  if (cancelEditLoan && loanEditDialog) cancelEditLoan.addEventListener("click", () => loanEditDialog.close());
  if (loanEditDialog) {
    loanEditDialog.addEventListener("click", (e) => {
      if (e.target === loanEditDialog) loanEditDialog.close();
    });
  }
  const loanEditForm = document.getElementById("loan-edit-form");
  if (loanEditForm) {
    loanEditForm.addEventListener("submit", submitLoanEdit);
  }
  const refreshTrashBtn = document.getElementById("refresh-trash-button");
  if (refreshTrashBtn) {
    refreshTrashBtn.addEventListener("click", loadTrash);
  }
  document.addEventListener("click", (event) => {
    const restoreBtn = event.target.closest("[data-restore-loan]");
    if (restoreBtn) {
      restoreLoan(restoreBtn.dataset.restoreLoan, restoreBtn);
    }
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
      const customerName = elements.dialog.dataset.customerName || "Cliente";
      const customerPhone = elements.dialog.dataset.customerPhone || "";
      await api("/loan-payments/", { method: "POST", body: JSON.stringify(payment) });
      elements.dialog.close();
      await loadDashboard();
      if (manageLoanDialog && manageLoanDialog.open && state.activeManagedLoanId) {
        openLoanManageDialog(state.activeManagedLoanId);
      }
      if (state.view === 'amortization' && state.activeAmortLoan) {
        const refreshedLoan = findLoanById(state.activeAmortLoan.id);
        if (refreshedLoan) {
          state.activeAmortLoan = refreshedLoan;
          renderAmortizationView();
        }
      }
      const updatedLoan = state.loans.find((item) => String(item.id) === String(loanId));
      const newBalance = updatedLoan ? Number(updatedLoan.balance || 0) : 0;
      const receiptText =
        `Comprobante de abono - ${state.tenant ? state.tenant.tenant_name : "TuNegocio"}\n` +
        `Cliente: ${customerName}\n` +
        `Abono recibido: ${money(payment.amount)}\n` +
        `Nuevo saldo pendiente: ${money(newBalance)}\n` +
        `Fecha: ${displayDate(localDateValue())}`;
      elements.error.hidden = true;
      elements.notice.innerHTML =
        `<span>Pago de <strong>${money(payment.amount)}</strong> registrado a ${escapeHtml(customerName)}.</span> ` +
        `<a target="_blank" rel="noopener" href="${escapeHtml(whatsappUrl(customerPhone, receiptText))}">📲 Enviar comprobante por WhatsApp</a>`;
      elements.notice.hidden = false;
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

  // =========================================================================
  // Pestañas de Ruta del Cobrador (Pendientes vs Cobradas hoy)
  // =========================================================================
  document.querySelectorAll("[data-collector-tab]").forEach((tabBtn) => {
    tabBtn.addEventListener("click", () => {
      const targetTab = tabBtn.dataset.collectorTab;
      document.querySelectorAll("[data-collector-tab]").forEach((btn) => {
        btn.classList.toggle("is-active", btn.dataset.collectorTab === targetTab);
      });
      const pendingPanel = document.getElementById("collector-pending-panel");
      const collectedPanel = document.getElementById("collector-collected-panel");
      if (pendingPanel) pendingPanel.hidden = targetTab !== "pending";
      if (collectedPanel) collectedPanel.hidden = targetTab !== "collected";
    });
  });

  // =========================================================================
  // Vista dedicada de Amortización del Cliente (Mobile-First + Compartir / PNG / PDF)
  // =========================================================================
  state.amortFilter = "all";
  state.activeAmortLoan = null;

  function findCustomerLoans(loan) {
    if (!loan) return [];
    const doc = loan.document_id;
    const name = loan.customer_name;
    if (state.customerSummary && Array.isArray(state.customerSummary.rows)) {
      const cust = state.customerSummary.rows.find(
        (r) => (doc && r.customer_document === doc) || r.customer_name === name
      );
      if (cust && Array.isArray(cust.loans) && cust.loans.length) {
        return cust.loans.map((item) => findLoanById(item.id)).filter(Boolean);
      }
    }
    return state.loans.filter(
      (item) => (doc && item.document_id === doc) || item.customer_name === name
    );
  }

  function openAmortizationView(loanId) {
    const loan = findLoanById(loanId);
    if (!loan) {
      showToast("No se encontró el detalle del préstamo.");
      return;
    }
    const manageDialog = document.getElementById("loan-manage-dialog");
    if (manageDialog && manageDialog.open) manageDialog.close();
    if (state.view !== "amortization") {
      state.previousView = state.view || "home";
    }
    state.activeAmortLoan = loan;
    const siblingLoans = findCustomerLoans(loan);
    const pickerWrap = document.getElementById("amortization-loan-picker-wrap");
    const loanSelect = document.getElementById("amortization-loan-select");
    if (pickerWrap && loanSelect) {
      if (siblingLoans.length > 1) {
        pickerWrap.hidden = false;
        loanSelect.replaceChildren();
        siblingLoans.forEach((sib, idx) => {
          const optLabel = `Crédito #${idx + 1} · ${displayDate(sib.start_date || sib.date)} · ${money(sib.principal)}`;
          loanSelect.add(new Option(optLabel, sib.id));
        });
        loanSelect.value = String(loan.id);
      } else {
        pickerWrap.hidden = true;
      }
    }
    renderAmortizationView();
    showView("amortization");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderAmortizationView() {
    const loan = state.activeAmortLoan;
    if (!loan) return;
    const name = loan.customer_name || "Cliente";
    const doc = loan.document_id || "Sin cédula";
    const neighborhood = loan.neighborhood || "Sin barrio";
    const phone = loan.customer_phone || "";
    const freq = labels[loan.frequency] || loan.frequency || "Diario";
    const startDate = displayDate(loan.start_date || loan.date || "");
    const principal = Number(loan.principal || 0);
    const totalPayable = Number(loan.total_payable || 0);
    const interest = loan.interest !== undefined ? Number(loan.interest) : (totalPayable - principal);
    const paperwork = Number(loan.paperwork_fee ?? loan.paperwork ?? 0);
    const balance = Number(loan.balance || 0);
    const collected = Math.max(0, totalPayable - balance);
    const pct = totalPayable > 0 ? Math.min(100, Math.round((collected / totalPayable) * 100)) : 0;

    const schedule = loan.installment_schedule || loan.installments || [];
    const paidCount = schedule.filter((inst) => inst.status === "paid" || Number(inst.amount_paid) >= Number(inst.amount_due)).length;

    const hero = document.getElementById("amortization-hero");
    if (hero) {
      hero.innerHTML =
        `<div class="amortization-hero-top">` +
        `<div><p class="eyebrow" style="color:rgba(255,255,255,0.8)">ESTADO DE CUENTA Y AMORTIZACIÓN</p>` +
        `<h2>${escapeHtml(name)}</h2>` +
        `<div class="amortization-hero-meta">${escapeHtml(doc)} · ${escapeHtml(neighborhood)}${phone ? ` · 📞 ${escapeHtml(phone)}` : ""}</div>` +
        `<div class="amortization-hero-meta">Inicio: ${escapeHtml(startDate)} · Modalidad: ${escapeHtml(freq)}</div></div>` +
        `<button class="button button-secondary button-sm" type="button" data-payment-loan="${escapeHtml(loan.id)}" ` +
        `data-payment-name="${escapeHtml(name)}" data-payment-phone="${escapeHtml(phone)}" data-payment-suggested="${escapeHtml(loan.collection_amount || balance)}">＋ Registrar abono</button>` +
        `</div>` +
        `<div class="amort-progress-wrap">` +
        `<div class="amort-progress-labels"><span>Avance del crédito: ${pct}% pagado</span><span>${paidCount} de ${schedule.length} cuotas cubiertas</span></div>` +
        `<div class="amort-progress-bar"><div class="amort-progress-fill" style="width:${pct}%"></div></div>` +
        `</div>`;
    }

    const kpiGrid = document.getElementById("amortization-kpi-grid");
    if (kpiGrid) {
      kpiGrid.innerHTML =
        `<div class="manage-kpi-item"><span>Capital prestado</span><strong>${money(principal)}</strong></div>` +
        `<div class="manage-kpi-item"><span>Interés</span><strong>${money(interest)}</strong></div>` +
        `<div class="manage-kpi-item"><span>Papelería</span><strong>${money(paperwork)}</strong></div>` +
        `<div class="manage-kpi-item"><span>Total a pagar</span><strong>${money(totalPayable)}</strong></div>` +
        `<div class="manage-kpi-item"><span>Total abonado</span><strong class="text-emerald">${money(collected)}</strong></div>` +
        `<div class="manage-kpi-item"><span>Saldo pendiente</span><strong class="text-danger">${money(balance)}</strong></div>`;
    }

    const filter = state.amortFilter || "all";
    const filteredSchedule = schedule.filter((inst) => {
      const isPaid = inst.status === "paid" || Number(inst.amount_paid) >= Number(inst.amount_due);
      if (filter === "paid") return isPaid;
      if (filter === "pending") return !isPaid;
      return true;
    });

    const cardsContainer = document.getElementById("amortization-installments-cards");
    if (cardsContainer) {
      if (!filteredSchedule.length) {
        cardsContainer.innerHTML = `<p class="muted">No hay cuotas en este filtro.</p>`;
      } else {
        cardsContainer.innerHTML = filteredSchedule.map((inst) => {
          const pending = inst.pending_amount ?? Math.max(0, Number(inst.amount_due || 0) - Number(inst.amount_paid || 0));
          const isPaid = inst.status === "paid" || pending <= 0;
          const isOverdue = inst.status === "delinquent" || Boolean(inst.is_overdue);
          const cardStateClass = isPaid ? "is-paid" : (isOverdue ? "is-overdue" : "");
          const pillLabel = isPaid ? "Pagada ✓" : (isOverdue ? "En mora" : (Number(inst.amount_paid) > 0 ? "Parcial" : "Pendiente"));
          const pillClass = isPaid ? "status-paid" : (isOverdue ? "status-delinquent" : (Number(inst.amount_paid) > 0 ? "status-partial" : "status-pending"));
          return (
            `<article class="amort-installment-card ${cardStateClass}">` +
            `<div class="amort-card-head">` +
            `<div><strong>Cuota #${escapeHtml(inst.number)}</strong><div class="amort-card-date">Vence: ${escapeHtml(displayDate(inst.due_date))}</div></div>` +
            `<span class="status-pill ${pillClass}">${escapeHtml(pillLabel)}</span>` +
            `</div>` +
            `<div class="amort-card-amounts">` +
            `<div><span>Valor cuota</span><strong>${money(inst.amount_due)}</strong></div>` +
            `<div><span>Abonado</span><strong class="text-emerald">${money(inst.amount_paid)}</strong></div>` +
            `<div><span>Pendiente</span><strong>${money(pending)}</strong></div>` +
            `</div>` +
            `</article>`
          );
        }).join("");
      }
    }

    const payments = loan.payment_history || loan.payments || [];
    const paymentsCountEl = document.getElementById("amortization-payments-count");
    if (paymentsCountEl) {
      paymentsCountEl.textContent = `${payments.length} ${payments.length === 1 ? "movimiento" : "movimientos"}`;
    }
    const paymentsListEl = document.getElementById("amortization-payments-list");
    if (paymentsListEl) {
      if (!payments.length) {
        paymentsListEl.innerHTML = `<p class="muted">No se han registrado abonos individuales todavía.</p>`;
      } else {
        const methodLabels = { cash: "Efectivo", transfer: "Transferencia", other: "Otro" };
        paymentsListEl.innerHTML = payments.map((p) => {
          const isRev = p.direction === "reversal";
          return (
            `<article class="payment-history-item ${p.is_reversed ? "is-reversed" : ""}">` +
            `<div class="payment-history-meta">` +
            `<strong>${money(p.amount)} · ${escapeHtml(isRev ? "Reversa" : "Abono recibido")}</strong>` +
            `<span>${escapeHtml(displayDate(p.date))} · ${escapeHtml(methodLabels[p.method] || p.method || "Efectivo")}` +
            `${p.collector_name ? ` · Cobrador: ${escapeHtml(p.collector_name)}` : ""}</span>` +
            `</div>` +
            `</article>`
          );
        }).join("");
      }
    }
  }

  function buildAmortizationText(loan) {
    if (!loan) return "";
    const name = loan.customer_name || "Cliente";
    const totalPayable = Number(loan.total_payable || 0);
    const balance = Number(loan.balance || 0);
    const collected = Math.max(0, totalPayable - balance);
    const schedule = loan.installment_schedule || loan.installments || [];
    const paidCount = schedule.filter((inst) => inst.status === "paid" || Number(inst.amount_paid) >= Number(inst.amount_due)).length;
    const pendingInstallments = schedule.filter((inst) => Number(inst.amount_paid) < Number(inst.amount_due)).slice(0, 8);
    let lines = [
      `📊 *ESTADO DE CUENTA Y AMORTIZACIÓN*`,
      `Negocio: ${state.tenant ? state.tenant.tenant_name : "TuNegocio"}`,
      `Cliente: ${name}`,
      `Modalidad: ${labels[loan.frequency] || loan.frequency}`,
      `Capital: ${money(loan.principal)}`,
      `Total a pagar: ${money(totalPayable)}`,
      `Total abonado: ${money(collected)}`,
      `Saldo pendiente: ${money(balance)}`,
      `Cuotas cubiertas: ${paidCount} de ${schedule.length}`,
    ];
    if (pendingInstallments.length) {
      lines.push(`\n*Próximas cuotas pendientes:*`);
      pendingInstallments.forEach((inst) => {
        const pend = inst.pending_amount ?? (Number(inst.amount_due) - Number(inst.amount_paid));
        lines.push(`• Cuota #${inst.number} (${displayDate(inst.due_date)}): ${money(pend)}`);
      });
    }
    return lines.join("\n");
  }

  function buildAmortizationCanvas(loan) {
    const schedule = loan.installment_schedule || loan.installments || [];
    const rowHeight = 36;
    const headerHeight = 310;
    const footerHeight = 60;
    const width = 960;
    const height = headerHeight + Math.max(1, schedule.length) * rowHeight + footerHeight;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");

    // Fondo general
    ctx.fillStyle = "#f8faf9";
    ctx.fillRect(0, 0, width, height);

    // Cabecera verde oscuro
    ctx.fillStyle = "#0d2e22";
    ctx.fillRect(0, 0, width, 150);

    ctx.fillStyle = "#86efac";
    ctx.font = "bold 14px sans-serif";
    ctx.fillText((state.tenant ? state.tenant.tenant_name : "TUNEGOCIO").toUpperCase() + " · TABLA DE AMORTIZACIÓN", 36, 40);

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 28px sans-serif";
    ctx.fillText(loan.customer_name || "Cliente", 36, 80);

    ctx.fillStyle = "#d1fae5";
    ctx.font = "16px sans-serif";
    const meta = `Doc: ${loan.document_id || "—"} · Barrio: ${loan.neighborhood || "—"} · Modalidad: ${labels[loan.frequency] || loan.frequency}`;
    ctx.fillText(meta, 36, 112);

    // Resumen KPIs
    const totalPayable = Number(loan.total_payable || 0);
    const balance = Number(loan.balance || 0);
    const collected = Math.max(0, totalPayable - balance);
    const kpis = [
      ["CAPITAL", money(loan.principal)],
      ["TOTAL A PAGAR", money(totalPayable)],
      ["TOTAL ABONADO", money(collected)],
      ["SALDO PENDIENTE", money(balance)],
    ];
    kpis.forEach(([label, val], idx) => {
      const boxX = 36 + idx * 224;
      const boxY = 170;
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(boxX, boxY, 210, 74);
      ctx.strokeStyle = "#d5e2dc";
      ctx.strokeRect(boxX, boxY, 210, 74);
      ctx.fillStyle = "#5b6e65";
      ctx.font = "bold 12px sans-serif";
      ctx.fillText(label, boxX + 14, boxY + 26);
      ctx.fillStyle = idx === 2 ? "#15803d" : (idx === 3 ? "#b91c1c" : "#0d2e22");
      ctx.font = "bold 19px sans-serif";
      ctx.fillText(val, boxX + 14, boxY + 54);
    });

    // Encabezado de tabla
    const tableTop = 266;
    ctx.fillStyle = "#e6f4ed";
    ctx.fillRect(36, tableTop, width - 72, 36);
    ctx.fillStyle = "#0d2e22";
    ctx.font = "bold 13px sans-serif";
    const cols = [
      ["CUOTA", 52],
      ["VENCIMIENTO", 160],
      ["VALOR CUOTA", 340],
      ["ABONADO", 520],
      ["PENDIENTE", 690],
      ["ESTADO", 830],
    ];
    cols.forEach(([title, x]) => ctx.fillText(title, x, tableTop + 23));

    schedule.forEach((inst, idx) => {
      const y = tableTop + 36 + idx * rowHeight;
      ctx.fillStyle = idx % 2 === 0 ? "#ffffff" : "#f3f7f5";
      ctx.fillRect(36, y, width - 72, rowHeight);
      const pending = inst.pending_amount ?? Math.max(0, Number(inst.amount_due || 0) - Number(inst.amount_paid || 0));
      const isPaid = inst.status === "paid" || pending <= 0;
      const statusText = isPaid ? "Pagada" : (inst.is_overdue ? "Vencida" : "Pendiente");
      ctx.fillStyle = "#16241e";
      ctx.font = "14px sans-serif";
      ctx.fillText(`#${inst.number}`, 52, y + 23);
      ctx.fillText(displayDate(inst.due_date), 160, y + 23);
      ctx.fillText(money(inst.amount_due), 340, y + 23);
      ctx.fillStyle = "#15803d";
      ctx.fillText(money(inst.amount_paid), 520, y + 23);
      ctx.fillStyle = pending > 0 ? "#b91c1c" : "#5b6e65";
      ctx.fillText(money(pending), 690, y + 23);
      ctx.fillStyle = isPaid ? "#15803d" : "#0d2e22";
      ctx.font = "bold 13px sans-serif";
      ctx.fillText(statusText, 830, y + 23);
    });

    ctx.fillStyle = "#5b6e65";
    ctx.font = "12px sans-serif";
    ctx.fillText(`Generado el ${displayDate(localDateValue())} · TuNegocio`, 36, height - 22);
    return canvas;
  }

  async function downloadAmortizationImage() {
    const loan = state.activeAmortLoan;
    if (!loan) return;
    const canvas = buildAmortizationCanvas(loan);
    const slugName = String(loan.customer_name || "cliente").toLowerCase().replace(/[^a-z0-9]+/g, "_");
    const dataUrl = canvas.toDataURL("image/png");
    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = `amortizacion_${slugName}_${localDateValue()}.png`;
    document.body.append(link);
    link.click();
    link.remove();
    showToast("Imagen de amortización descargada.");
  }

  async function shareAmortization(preferImage = false) {
    const loan = state.activeAmortLoan;
    if (!loan) return;
    const text = buildAmortizationText(loan);
    try {
      const canvas = buildAmortizationCanvas(loan);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      const slugName = String(loan.customer_name || "cliente").toLowerCase().replace(/[^a-z0-9]+/g, "_");
      const file = blob ? new File([blob], `amortizacion_${slugName}.png`, { type: "image/png" }) : null;
      if (navigator.canShare && file && navigator.canShare({ files: [file] })) {
        await navigator.share({
          title: `Amortización - ${loan.customer_name}`,
          text,
          files: [file],
        });
        return;
      }
      if (navigator.share && !preferImage) {
        await navigator.share({
          title: `Amortización - ${loan.customer_name}`,
          text,
        });
        return;
      }
    } catch (err) {
      if (err && err.name === "AbortError") return;
    }
    if (preferImage) {
      await downloadAmortizationImage();
      showToast("Imagen descargada lista para compartir en Instagram o Messenger.");
      return;
    }
    window.open(whatsappUrl(loan.customer_phone || "", text), "_blank", "noopener");
  }

  function exportAmortizationPdf() {
    const loan = state.activeAmortLoan;
    if (!loan) return;
    const canvas = buildAmortizationCanvas(loan);
    const imgData = canvas.toDataURL("image/png");
    const win = window.open("", "_blank");
    if (!win) {
      downloadAmortizationImage();
      return;
    }
    win.document.write(
      `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Amortización - ${escapeHtml(loan.customer_name || "Cliente")}</title>` +
      `<style>body{margin:0;padding:16px;font-family:sans-serif;text-align:center;background:#fff}img{max-width:100%;height:auto}@media print{body{padding:0}}</style></head>` +
      `<body><img src="${imgData}" alt="Tabla de amortización"><script>window.onload=()=>{setTimeout(()=>{window.print();},250);};<\/script></body></html>`
    );
    win.document.close();
  }

  const amortBackBtn = document.getElementById("amortization-back-button");
  if (amortBackBtn) {
    amortBackBtn.addEventListener("click", () => {
      showView(state.previousView || "home");
    });
  }
  const amortLoanSelect = document.getElementById("amortization-loan-select");
  if (amortLoanSelect) {
    amortLoanSelect.addEventListener("change", (event) => {
      const nextLoan = findLoanById(event.target.value);
      if (nextLoan) {
        state.activeAmortLoan = nextLoan;
        renderAmortizationView();
      }
    });
  }
  document.querySelectorAll("[data-amort-filter]").forEach((pill) => {
    pill.addEventListener("click", () => {
      state.amortFilter = pill.dataset.amortFilter;
      document.querySelectorAll("[data-amort-filter]").forEach((p) => {
        p.classList.toggle("is-active", p.dataset.amortFilter === state.amortFilter);
      });
      renderAmortizationView();
    });
  });
  const amortShareBtn = document.getElementById("amortization-share-button");
  if (amortShareBtn) amortShareBtn.addEventListener("click", () => shareAmortization(false));
  const amortImageBtn = document.getElementById("amortization-image-button");
  if (amortImageBtn) amortImageBtn.addEventListener("click", downloadAmortizationImage);
  const amortPdfBtn = document.getElementById("amortization-pdf-button");
  if (amortPdfBtn) amortPdfBtn.addEventListener("click", exportAmortizationPdf);
  const shareWaBtn = document.getElementById("share-amort-whatsapp");
  if (shareWaBtn) {
    shareWaBtn.addEventListener("click", () => {
      if (!state.activeAmortLoan) return;
      const text = buildAmortizationText(state.activeAmortLoan);
      window.open(whatsappUrl(state.activeAmortLoan.customer_phone || "", text), "_blank", "noopener");
    });
  }
  const shareIgBtn = document.getElementById("share-amort-instagram");
  if (shareIgBtn) shareIgBtn.addEventListener("click", () => shareAmortization(true));
  const shareCopyBtn = document.getElementById("share-amort-copy");
  if (shareCopyBtn) {
    shareCopyBtn.addEventListener("click", async () => {
      if (!state.activeAmortLoan) return;
      const text = buildAmortizationText(state.activeAmortLoan);
      try {
        await navigator.clipboard.writeText(text);
        showToast("Resumen de amortización copiado al portapapeles.");
      } catch (e) {
        showToast("No se pudo copiar automáticamente.");
      }
    });
  }

  document.addEventListener("click", (event) => {
    const openAmortBtn = event.target.closest("[data-open-amortization]");
    if (openAmortBtn) {
      openAmortizationView(openAmortBtn.dataset.openAmortization);
    }
  });

  // =========================================================================
  // Modal y Flujo de Cierre del Día
  // =========================================================================
  const dayCloseDialog = document.getElementById("day-close-dialog");
  const countedCashInput = document.getElementById("day-close-counted");
  const diffHint = document.getElementById("day-close-diff-hint");

  function updateDayCloseDiff() {
    if (!countedCashInput || !diffHint) return;
    const expected = Number(state.dayCloseExpectedCash || 0);
    const raw = countedCashInput.value;
    if (!raw) {
      diffHint.textContent = `Saldo esperado en caja: ${money(expected)}`;
      return;
    }
    const counted = Number(raw || 0);
    const diff = counted - expected;
    if (Math.abs(diff) < 1) {
      diffHint.textContent = "✓ Cuadre exacto con el saldo esperado.";
    } else if (diff > 0) {
      diffHint.textContent = `Sobrante en caja: +${money(diff)} sobre lo esperado.`;
    } else {
      diffHint.textContent = `Faltante en caja: ${money(diff)} respecto a lo esperado.`;
    }
  }
  if (countedCashInput) countedCashInput.addEventListener("input", updateDayCloseDiff);

  async function openDayCloseDialog() {
    if (!dayCloseDialog) return;
    const todayStr = localDateValue();
    try {
      const report = await api(`/collector-cash-summary/?period=day&date=${todayStr}`);
      state.cashSummary = report;
      const totals = report.totals || {};
      const collectedTodayData = state.collectedToday || computeCollectedToday();
      const expectedCash = Number(totals.expected_cash || 0);
      state.dayCloseExpectedCash = expectedCash;

      document.getElementById("day-close-subtitle").textContent =
        `Resumen del día ${displayDate(todayStr)} · ${state.tenant ? state.tenant.tenant_name : "TuNegocio"}`;

      document.getElementById("day-close-kpi-grid").innerHTML =
        `<div class="manage-kpi-item"><span>Personas cobradas hoy</span><strong class="text-emerald">${collectedTodayData.items.length}</strong></div>` +
        `<div class="manage-kpi-item"><span>Cuotas pendientes hoy</span><strong>${state.collections.length}</strong></div>` +
        `<div class="manage-kpi-item"><span>Dinero inicial (Base)</span><strong>${money(totals.opening_cash)}</strong></div>` +
        `<div class="manage-kpi-item"><span>Total recogido hoy</span><strong class="text-emerald">${money(totals.collected)}</strong></div>` +
        `<div class="manage-kpi-item"><span>Gastos del día</span><strong class="text-danger">${money(totals.expenses)}</strong></div>` +
        `<div class="manage-kpi-item"><span>Efectivo a entregar</span><strong>${money(expectedCash)}</strong></div>`;

      updateDayCloseDiff();
      dayCloseDialog.showModal();
    } catch (error) {
      showError(error.message);
    }
  }

  function buildDayCloseReportText() {
    const todayStr = localDateValue();
    const totals = (state.cashSummary && state.cashSummary.totals) || {};
    const collectedTodayData = state.collectedToday || computeCollectedToday();
    const counted = countedCashInput && countedCashInput.value ? money(countedCashInput.value) : "No indicado";
    const notes = (document.getElementById("day-close-notes") && document.getElementById("day-close-notes").value.trim()) || "Sin novedades";
    return [
      `🔒 *CIERRE DEL DÍA DE COBRO*`,
      `Fecha: ${displayDate(todayStr)}`,
      `Usuario: ${state.username || "Cobrador"}`,
      `Personas cobradas hoy: ${collectedTodayData.items.length}`,
      `Cuotas pendientes: ${state.collections.length}`,
      `Dinero inicial: ${money(totals.opening_cash)}`,
      `Total recogido hoy: ${money(totals.collected)}`,
      `Papelería hoy: ${money(totals.paperwork)}`,
      `Gastos del día: ${money(totals.expenses)}`,
      `Capital prestado hoy: ${money(totals.principal_lent)}`,
      `*Saldo esperado a entregar: ${money(totals.expected_cash)}*`,
      `Efectivo físico contado: ${counted}`,
      `Observaciones: ${notes}`,
    ].join("\n");
  }

  ["open-day-close-button", "collector-close-day-inline", "cashflow-day-close-button"].forEach((id) => {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener("click", openDayCloseDialog);
  });
  const closeDayCloseBtn = document.getElementById("close-day-close-dialog");
  if (closeDayCloseBtn && dayCloseDialog) {
    closeDayCloseBtn.addEventListener("click", () => dayCloseDialog.close());
    dayCloseDialog.addEventListener("click", (event) => {
      if (event.target === dayCloseDialog) dayCloseDialog.close();
    });
  }
  const dayCloseWaBtn = document.getElementById("day-close-whatsapp-btn");
  if (dayCloseWaBtn) {
    dayCloseWaBtn.addEventListener("click", () => {
      window.open(whatsappUrl("", buildDayCloseReportText()), "_blank", "noopener");
    });
  }
  const dayCloseForm = document.getElementById("day-close-form");
  if (dayCloseForm) {
    dayCloseForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const todayStr = localDateValue();
      sessionStorage.setItem(`day_closed_${todayStr}`, "1");
      const labelEl = document.getElementById("open-day-close-label");
      if (labelEl) labelEl.textContent = "Día cerrado ✓";
      if (dayCloseDialog && dayCloseDialog.open) dayCloseDialog.close();
      showToast("Cierre del día confirmado correctamente.");
    });
  }

  toggleRegistration(false);
  restoreSession();
})();
