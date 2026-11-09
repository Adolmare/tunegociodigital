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
    const isEmployee = state.role === "employee";
    document.getElementById("business-code-panel").hidden = !isOwner;
    document.getElementById("business-join-code").textContent = membership.tenant_join_code || "—";
    document.getElementById("ledger-nav").hidden = !isOwner;
    document.getElementById("mobile-ledger-nav").hidden = !isOwner;
    document.getElementById("employee-requests-nav").hidden = !isOwner;
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
    document.getElementById("new-loan-nav").hidden = isEmployee;
    document.getElementById("mobile-add-button").hidden = isEmployee;
    document.getElementById("desktop-new-button").hidden = isEmployee;
    document.getElementById("home-portfolio-card").hidden = isEmployee;
    document.getElementById("home-loans-section").hidden = isEmployee;
    document.getElementById("home-collections-section").hidden = !isEmployee;
    document.getElementById("cash-opening-section").hidden = isEmployee;
    document.getElementById("expense-collector-field").hidden = isEmployee;
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

  async function loadDashboard() {
    clearMessages();
    try {
      const [loanData, collectionData] = await Promise.all([
        api("/loans/"),
        api("/loans/collection-today/"),
      ]);
      state.loans = getRows(loanData);
      state.collections = getRows(collectionData);
      populateExistingCustomers();
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
      const manageBtnHtml =
        `<button class="loan-action-secondary" type="button" data-manage-loan="${escapeHtml(loan.id)}">` +
        `🧾 Gestionar / Abonos (${paymentsCount})</button>`;
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
        `<div class="loan-row-actions">${manageBtnHtml}${renewBtnHtml}</div>`;
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
          `<div class="loan-detail"><strong>${money(pending)}</strong><span>Saldo de cuota</span></div>` +
          `<div class="loan-detail"><strong>${money(installment.amount_due)}</strong><span>Cuota completa</span></div>` +
          `<button class="loan-action" type="button" data-payment-loan="${escapeHtml(installment.loan)}" ` +
          `data-payment-name="${escapeHtml(name)}" data-payment-phone="${escapeHtml(phone)}" data-payment-suggested="${escapeHtml(pending)}">Cobrar</button>` +
          `<span class="status-pill ${overdue ? "status-delinquent" : "status-active"}">` +
          `${overdue ? "Vencida" : "Pendiente"}</span>`;
        list.append(row);
      });
    });
    const homePill = document.getElementById("home-collection-pill");
    if (homePill) {
      homePill.textContent = `${state.collections.length} ${state.collections.length === 1 ? "pendiente" : "pendientes"}`;
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
        return `<tr><td><strong>${escapeHtml(customer.customer_name)}</strong>` +
          (contactChips ? `<div class="customer-cell-meta">${contactChips}</div>` : "") +
          `</td><td>${escapeHtml(customer.loan_count)}</td>` +
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
    state.view = view;
    const isEmployee = state.role === "employee";
    const titles = {
      home: [isEmployee ? "Mi ruta de hoy" : "Resumen", isEmployee ? "Tu ruta de cobro diaria y saldo activo en calle." : "Una mirada clara a tus préstamos."],
      collections: ["Cobros de hoy", "Cuotas pendientes de tu cartera."],
      ledger: ["Libro de cartera", "Consulta el formato del Excel por período y frecuencia."],
      cashflow: ["Caja y gastos", isEmployee ? "Registra tus gastos diarios y consulta tu balance de caja." : "Controla el dinero inicial, los cobros, los préstamos y los gastos."],
      "customer-summary": ["Resumen por cliente", "Consulta la cartera consolidada y el detalle de amortización."],
      "employee-requests": ["Solicitudes de empleados", "Aprueba o rechaza las solicitudes de acceso al negocio."],
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
    if (view === "cashflow") loadCashSummary();
    if (view === "customer-summary") loadCustomerSummary();
    if (view === "employee-requests") loadEmployeeRequests();
    clearMessages();
  }

  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");
  const registerToggle = document.getElementById("show-register");
  const authTabLogin = document.getElementById("auth-tab-login");
  const authTabRegister = document.getElementById("auth-tab-register");

  function syncRegisterRoleFields() {
    const roleInput = document.getElementById("register-role");
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
  }

  if (registerToggle) registerToggle.addEventListener("click", () => toggleRegistration(true));
  if (authTabLogin) authTabLogin.addEventListener("click", () => toggleRegistration(false));
  if (authTabRegister) authTabRegister.addEventListener("click", () => toggleRegistration(true));
  document.getElementById("cancel-register").addEventListener("click", () => toggleRegistration(false));
  document.querySelectorAll("[data-register-role]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const roleInput = document.getElementById("register-role");
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

  async function createLendingBusiness(businessName) {
    const response = await rawRequest("/tenants/", {
      method: "POST",
      body: JSON.stringify({
        name: businessName,
        slug: buildBusinessSlug(businessName),
        business_type: "prestamista",
      }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(errorMessage(data, "No se pudo crear el negocio."));
    return data;
  }

  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearMessages();
    const button = registerForm.querySelector('button[type="submit"]');
    const form = new FormData(registerForm);
    const username = String(form.get("username") || "").trim();
    const password = String(form.get("password") || "");
    const registerRole = String(form.get("register_role") || "collector");
    const joinCode = String(form.get("join_code") || "").trim().toUpperCase();
    const businessName = String(form.get("business_name") || "").trim();
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

      if (registerRole === "owner") {
        await createLendingBusiness(businessName || `Cartera de ${username}`);
        registerForm.reset();
        loginForm.reset();
        toggleRegistration(false);
        const memberships = getRows(await api("/auth/me/tenants/"));
        if (memberships.length) {
          await openWorkspace(memberships[0]);
          showToast("¡Cuenta y negocio creados! Ya puedes operar.");
          return;
        }
        await loadTenants();
        return;
      }

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
        const memberships = getRows(await api("/auth/me/tenants/"));
        if (memberships.length) {
          await openWorkspace(memberships[memberships.length - 1]);
          showToast("Negocio creado correctamente.");
          return;
        }
        await loadTenants();
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
      await loadCashSummary();
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
    if (state.view === "cashflow") loadCashSummary();
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

  toggleRegistration(false);
  restoreSession();
})();
