/**
 * ApplyKit Vanilla JS Frontend Engine (`/static/app.js`)
 * Powers:
 * - Universal "⚡ Ask ApplyKit..." Command Palette (`/api/router`) + On-the-Fly Hidden Vault Runner (`/api/execute`)
 * - All 4 AI Showcase Tools (`ats-score`, `cover-letter`, `scam-check`, `interview-qs`) + PDF/DOCX CV upload
 * - All 3 Pure-JS Instant Tools (Freelance Rate Calculator, PAYE 2026 Kenya/Nigeria/Ghana, Printable Invoice)
 * - Kanban Drag-and-Drop Dashboard + WhatsApp Interview Reminders + CSV Export
 * - Google OAuth (Supabase) + Login Wall + UpgradeModal + Safaricom Daraja STK Push 3s Polling
 */

(function () {
  "use strict";

  let routerDebounce = null;
  let lastVaultCopyText = "";
  let lastAtsScoreData = null;
  let activePayeCountry = "kenya";
  let stkPollTimer = null;
  let supabaseBrowser = null;

  function getAuthToken() {
    return localStorage.getItem("applykit_jwt") || "";
  }

  function authHeaders(extra = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, extra);
    const tok = getAuthToken();
    if (tok) headers["Authorization"] = `Bearer ${tok}`;
    return headers;
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function toast(msg) {
    const el = document.createElement("div");
    el.className =
      "fixed bottom-5 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl bg-slate-900 text-white text-xs font-semibold shadow-xl border border-slate-700";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2800);
  }

  async function apiJson(url, options = {}) {
    const res = await fetch(url, {
      method: options.method || "POST",
      headers: authHeaders(options.headers || {}),
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || {};
      const code = typeof detail === "object" ? detail.code : "";
      const message =
        typeof detail === "object"
          ? detail.message
          : detail || "Request failed. Please try again.";
      if (res.status === 401 && (code === "LOGIN_REQUIRED" || !getAuthToken())) {
        openLoginModal(message);
        throw new Error(message);
      }
      if (res.status === 402 || code === "UPGRADE_REQUIRED") {
        openUpgradeModal(message);
        throw new Error(message);
      }
      toast(message);
      throw new Error(message);
    }
    return data;
  }

  // -------------------------------------------------------------------------
  // Auth: Google OAuth via Supabase + Local Dev Quick Session
  // -------------------------------------------------------------------------
  function initSupabaseAuth() {
    const sbUrl = document.body.dataset.supabaseUrl;
    const sbAnon = document.body.dataset.supabaseAnon;
    if (sbUrl && sbAnon && window.supabase) {
      supabaseBrowser = window.supabase.createClient(sbUrl, sbAnon);
      supabaseBrowser.auth.onAuthStateChange((_event, session) => {
        if (session && session.access_token) {
          localStorage.setItem("applykit_jwt", session.access_token);
          document.cookie = `applykit_token=${session.access_token}; path=/; max-age=604800; SameSite=Lax`;
        }
      });
    }
  }

  async function signInWithGoogle() {
    if (supabaseBrowser) {
      const { error } = await supabaseBrowser.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: window.location.origin + "/dashboard" },
      });
      if (error) toast(error.message || "Enable Google OAuth in Supabase Dashboard -> Auth -> Providers.");
      return;
    }
    toast("Set SUPABASE_URL & SUPABASE_ANON_KEY in .env for Google OAuth, or use Local Dev Sign-In below.");
  }

  async function signInWithGitHub() {
    if (supabaseBrowser) {
      const { error } = await supabaseBrowser.auth.signInWithOAuth({
        provider: "github",
        options: { redirectTo: window.location.origin + "/dashboard" },
      });
      if (error) toast(error.message);
      return;
    }
    toast("Supabase not configured.");
  }

  async function signInWithEmailPassword(e) {
    e.preventDefault();
    if (!supabaseBrowser) return;
    const email = document.getElementById("sbAuthEmail").value.trim();
    const password = document.getElementById("sbAuthPassword").value;
    let { data, error } = await supabaseBrowser.auth.signInWithPassword({ email, password });
    if (error) {
      const signUpRes = await supabaseBrowser.auth.signUp({ email, password });
      if (signUpRes.error) {
        toast(signUpRes.error.message);
        return;
      }
      data = signUpRes.data;
      if (!data.session) {
        toast("Check your email inbox to confirm your new ApplyKit account!");
        return;
      }
    }
    if (data && data.session && data.session.access_token) {
      localStorage.setItem("applykit_jwt", data.session.access_token);
      document.cookie = `applykit_token=${data.session.access_token}; path=/; max-age=604800; SameSite=Lax`;
      window.location.href = "/dashboard";
    }
  }

  async function devQuickLogin(e) {
    e.preventDefault();
    const email = document.getElementById("devLoginEmail").value.trim();
    const data = await apiJson("/api/auth/demo-session", { body: { email } });
    if (data.token) {
      localStorage.setItem("applykit_jwt", data.token);
      window.location.reload();
    }
  }

  async function logout() {
    localStorage.removeItem("applykit_jwt");
    if (supabaseBrowser) await supabaseBrowser.auth.signOut().catch(() => {});
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/";
  }

  async function deleteMyData() {
    if (!confirm("Permanently delete your profile, saved applications, logs, and CVs? This cannot be undone.")) return;
    await apiJson("/api/account/delete-my-data", { method: "DELETE" });
    localStorage.removeItem("applykit_jwt");
    alert("All your ApplyKit data has been permanently erased.");
    window.location.href = "/";
  }

  // -------------------------------------------------------------------------
  // Modals & Universal Command Palette ("⚡ Ask ApplyKit...")
  // -------------------------------------------------------------------------
  function closeModals() {
    document.getElementById("loginWallModal")?.classList.add("hidden");
    document.getElementById("upgradeProModal")?.classList.add("hidden");
  }

  function openLoginModal(customMsg) {
    closePalette();
    if (customMsg) {
      const msgEl = document.getElementById("loginWallMessage");
      if (msgEl) msgEl.textContent = customMsg;
    }
    document.getElementById("loginWallModal")?.classList.remove("hidden");
  }

  function openUpgradeModal(customMsg) {
    closePalette();
    if (customMsg) {
      const msgEl = document.getElementById("upgradeModalMessage");
      if (msgEl) msgEl.textContent = customMsg;
    }
    document.getElementById("upgradeProModal")?.classList.remove("hidden");
  }

  function openPalette(initialQuery = "") {
    const modal = document.getElementById("vaultPaletteModal");
    const input = document.getElementById("paletteSearchInput");
    if (!modal || !input) return;
    modal.classList.remove("hidden");
    backToPaletteList();
    input.value = initialQuery || "";
    input.focus();
    fetchRouterResults(input.value);
  }

  function closePalette() {
    document.getElementById("vaultPaletteModal")?.classList.add("hidden");
  }

  function backToPaletteList() {
    document.getElementById("paletteResultsPane")?.classList.remove("hidden");
    document.getElementById("paletteRunnerPane")?.classList.add("hidden");
    document.getElementById("runnerOutputBox")?.classList.add("hidden");
  }

  function quickQuery(q) {
    const input = document.getElementById("paletteSearchInput");
    if (input) {
      input.value = q;
      fetchRouterResults(q);
    }
  }

  async function fetchRouterResults(query) {
    const container = document.getElementById("paletteCardsContainer");
    const label = document.getElementById("paletteStrategyLabel");
    if (!container) return;

    try {
      const res = await fetch("/api/router", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          query: query || "",
          context: "web",
          url: window.location.href,
        }),
      });
      const data = await res.json();
      const tools = data.tools || [];
      if (label) {
        label.textContent = query
          ? `Matched ${tools.length} tools across ${data.vault_total || 60}+ Vault`
          : "Recommended ApplyKit Tools — type 'resign', 'NDA', 'negotiate' to unlock Vault";
      }

      container.innerHTML = tools
        .map((t) => {
          const badge = t.visible
            ? `<span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 font-bold">Showcase Page</span>`
            : `<span class="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-900 font-bold">⚡ Hidden Vault</span>`;
          const encoded = encodeURIComponent(JSON.stringify(t));
          return `
            <button type="button" onclick="window.ApplyKit.selectRoutedTool('${encoded}')"
              class="w-full text-left p-3.5 rounded-xl border border-slate-200 hover:border-emerald-500 hover:bg-emerald-50/30 transition flex items-start justify-between gap-3">
              <div class="flex items-start gap-3">
                <span class="text-2xl bg-slate-100 w-10 h-10 rounded-xl flex items-center justify-center shrink-0">${escapeHtml(t.icon)}</span>
                <div>
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="font-bold text-sm text-slate-900">${escapeHtml(t.name)}</span>
                    ${badge}
                  </div>
                  <p class="text-xs text-slate-600 mt-0.5">${escapeHtml(t.description)}</p>
                </div>
              </div>
              <span class="text-emerald-600 font-bold text-sm shrink-0">${t.visible ? "Open →" : "Run ⚡"}</span>
            </button>
          `;
        })
        .join("");
    } catch (_err) {
      container.innerHTML = `<p class="text-xs text-rose-600 p-2">Could not reach router. Check connection.</p>`;
    }
  }

  function selectRoutedTool(encodedTool) {
    const tool = JSON.parse(decodeURIComponent(encodedTool));
    if (tool.visible && tool.url) {
      window.location.href = tool.url;
      return;
    }
    // Hidden Vault tool -> open on-the-fly runner inside Command Palette!
    document.getElementById("paletteResultsPane").classList.add("hidden");
    document.getElementById("paletteRunnerPane").classList.remove("hidden");
    document.getElementById("runnerOutputBox").classList.add("hidden");

    document.getElementById("runnerToolId").value = tool.id;
    document.getElementById("runnerToolIcon").textContent = tool.icon || "⚡";
    document.getElementById("vaultModalTitle").textContent = tool.name;
    document.getElementById("runnerToolDesc").textContent = tool.description || "";
    document.getElementById("runnerInputLabel").textContent = tool.input_label || "Your Details";
    const ta = document.getElementById("runnerUserInput");
    ta.placeholder = tool.input_placeholder || "Paste details here...";
    ta.focus();
  }

  async function submitVaultTool(e) {
    e.preventDefault();
    const btn = document.getElementById("runnerSubmitBtn");
    const toolId = document.getElementById("runnerToolId").value;
    const userInput = document.getElementById("runnerUserInput").value.trim();
    btn.disabled = true;
    btn.textContent = "⚡ Running ApplyKit AI...";

    try {
      const data = await apiJson("/api/execute", {
        body: { tool_id: toolId, input: userInput },
      });
      const r = data.result || {};
      document.getElementById("runnerOutTitle").textContent = r.title || data.tool?.name || "Result";
      document.getElementById("runnerOutSummary").textContent = r.summary || "";
      const rem = data.quota?.remaining;
      document.getElementById("runnerQuotaBadge").textContent = data.quota?.is_pro
        ? "PRO Unlimited · 70B"
        : `Free Remaining: ${rem ?? 0}`;

      const sections = Array.isArray(r.sections) ? r.sections : [];
      document.getElementById("runnerOutSections").innerHTML = sections
        .map(
          (sec) => `
          <div class="bg-slate-50 rounded-xl p-3.5 border border-slate-200">
            <div class="font-bold text-xs uppercase text-slate-500 mb-1.5">${escapeHtml(sec.heading)}</div>
            <div class="space-y-1.5 text-xs sm:text-sm whitespace-pre-line">${(sec.items || [])
              .map((it) => `<div>• ${escapeHtml(it)}</div>`)
              .join("")}</div>
          </div>`
        )
        .join("");

      lastVaultCopyText =
        r.copy_text ||
        sections.map((s) => `${s.heading}\n${(s.items || []).join("\n")}`).join("\n\n");
      document.getElementById("runnerWhatsappBtn").href = data.whatsapp_share_url || "https://wa.me/";
      document.getElementById("runnerOutputBox").classList.remove("hidden");
    } catch (_err) {
      // Login/Upgrade modal handled inside apiJson
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ Run Vault Tool Instantly";
    }
  }

  function copyVaultOutput() {
    navigator.clipboard.writeText(lastVaultCopyText || "");
    toast("Copied to clipboard!");
  }

  function copyElementText(id) {
    const el = document.getElementById(id);
    if (el) {
      navigator.clipboard.writeText(el.innerText);
      toast("Copied to clipboard!");
    }
  }

  function downloadTextAsPdf() {
    window.print();
  }

  // -------------------------------------------------------------------------
  // CV Upload Helper (PDF / DOCX <= 2 MB)
  // -------------------------------------------------------------------------
  async function uploadCvFile(inputEl, targetTextareaId) {
    const file = inputEl.files && inputEl.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      toast("File exceeds 2 MB limit.");
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    toast("Extracting CV text...");
    try {
      const res = await fetch("/api/ai/extract-cv", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      document.getElementById(targetTextareaId).value = data.cv_text;
      toast(`Loaded ${file.name} (${data.char_count} chars)`);
    } catch (err) {
      toast(err.message || "Could not parse CV file");
    }
  }

  // -------------------------------------------------------------------------
  // Showcase AI Tools (#1 ATS, #2 Cover Letter, #5 Scam, #7 Interview Qs)
  // -------------------------------------------------------------------------
  function loadSampleAts() {
    document.getElementById("atsCvText").value =
      "Backend Software Engineer with 4 years building Python, FastAPI, PostgreSQL, and REST microservices in Nairobi. Integrated Safaricom Daraja M-Pesa APIs processing 40,000 monthly transactions with 99.9% uptime. Experienced with Docker, GitHub Actions CI/CD, and unit testing.";
    document.getElementById("atsJdText").value =
      "Seeking a Senior Remote Backend Engineer proficient in Python, FastAPI, PostgreSQL, Redis caching, AWS Lambda, Kubernetes, and webhook security to scale fintech payment APIs across Africa and Europe.";
  }

  async function runAtsChecker(e) {
    e.preventDefault();
    const btn = document.getElementById("atsSubmitBtn");
    const cv_text = document.getElementById("atsCvText").value.trim();
    const jd_text = document.getElementById("atsJdText").value.trim();
    btn.disabled = true;
    btn.textContent = "🎯 Analyzing CV vs Job Description...";

    try {
      const data = await apiJson("/api/ai/ats-score", { body: { cv_text, jd_text } });
      const r = data.result;
      lastAtsScoreData = r;
      const score = Math.max(0, Math.min(100, Number(r.score) || 0));

      document.getElementById("atsScoreNum").textContent = String(score);
      const arc = document.getElementById("atsGaugeArc");
      const offset = 314 - (314 * score) / 100;
      arc.style.strokeDashoffset = String(offset);
      arc.style.stroke = score >= 75 ? "#059669" : score >= 50 ? "#d97706" : "#e11d48";

      document.getElementById("atsVerdictPill").textContent = r.verdict || "Analyzed";
      document.getElementById("atsSummaryText").textContent = r.summary || "";
      document.getElementById("atsWhatsappBtn").href = data.whatsapp_share_url || "https://wa.me/";

      document.getElementById("atsMatchedList").innerHTML = (r.matched_keywords || [])
        .map((k) => `<span class="px-2.5 py-1 rounded-lg bg-emerald-100 text-emerald-900 text-xs font-semibold">✓ ${escapeHtml(k)}</span>`)
        .join("");
      document.getElementById("atsMissingList").innerHTML = (r.missing_keywords || [])
        .map((k) => `<span class="px-2.5 py-1 rounded-lg bg-rose-100 text-rose-900 text-xs font-semibold">✗ ${escapeHtml(k)}</span>`)
        .join("");
      document.getElementById("atsFixesContainer").innerHTML = (r.ai_fixes || [])
        .map((b) => `<div class="p-2.5 bg-white rounded-lg border border-slate-200">• ${escapeHtml(b)}</div>`)
        .join("");

      const sec = document.getElementById("atsResultSection");
      sec.classList.remove("hidden");
      sec.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (_err) {
    } finally {
      btn.disabled = false;
      btn.textContent = "🎯 Check ATS Match Score Now";
    }
  }

  function downloadScoreBadgeImage() {
    const score = lastAtsScoreData?.score ?? 82;
    const verdict = lastAtsScoreData?.verdict ?? "Strong Match";
    const canvas = document.createElement("canvas");
    canvas.width = 800;
    canvas.height = 420;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#064e3b";
    ctx.fillRect(0, 0, 800, 420);
    ctx.fillStyle = "#10b981";
    ctx.font = "bold 26px sans-serif";
    ctx.fillText("⚡ ApplyKit ATS Match Report", 50, 70);
    ctx.fillStyle = "#ffffff";
    ctx.font = "900 110px sans-serif";
    ctx.fillText(`${score}/100`, 50, 215);
    ctx.font = "bold 34px sans-serif";
    ctx.fillStyle = "#a7f3d0";
    ctx.fillText(verdict, 50, 275);
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "20px sans-serif";
    ctx.fillText("Check your CV match score free at ApplyKit", 50, 355);

    const a = document.createElement("a");
    a.download = `applykit-ats-score-${score}.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  }

  async function runCoverLetter(e) {
    e.preventDefault();
    const btn = document.getElementById("clSubmitBtn");
    btn.disabled = true;
    btn.textContent = "✍️ Writing 150-Word Pitch...";
    try {
      const data = await apiJson("/api/ai/cover-letter", {
        body: {
          cv_text: document.getElementById("clCvText").value.trim(),
          jd_text: document.getElementById("clJdText").value.trim(),
          tone: document.getElementById("clTone").value,
        },
      });
      const r = data.result;
      document.getElementById("clOutputText").textContent = r.cover_letter || "";
      document.getElementById("clWordCountBadge").textContent = `${r.word_count || 150} words`;
      document.getElementById("clWhatsappBtn").href = data.whatsapp_share_url || "https://wa.me/";
      document.getElementById("clResultSection").classList.remove("hidden");
    } catch (_err) {
    } finally {
      btn.disabled = false;
      btn.textContent = "✍️ Generate 150-Word Letter";
    }
  }

  function loadSampleScam() {
    document.getElementById("scamJobText").value =
      "URGENT REMOTE DATA ENTRY CLERK ($65/hr, No Experience Needed!). Message our HR Director immediately on Telegram @GlobalHR_Desk. Applicants in Kenya must pay KES 1,850 refundable laptop clearance & training fee via Till before onboarding.";
    document.getElementById("scamClientMeta").value = "Payment unverified, 22 jobs posted, 0 hired";
  }

  async function runScamDetector(e) {
    e.preventDefault();
    const btn = document.getElementById("scamSubmitBtn");
    btn.disabled = true;
    btn.textContent = "🛡️ Scanning for Fraud Patterns...";
    try {
      const data = await apiJson("/api/ai/scam-check", {
        body: {
          job_text: document.getElementById("scamJobText").value.trim(),
          client_meta: document.getElementById("scamClientMeta").value.trim(),
        },
      });
      const r = data.result;
      const badge = document.getElementById("scamRiskBadge");
      const level = r.risk_level || "Medium";
      badge.textContent = `${level} Risk`;
      badge.className =
        "inline-block px-3 py-1 rounded-full text-xs font-extrabold uppercase " +
        (level === "High"
          ? "bg-rose-100 text-rose-800"
          : level === "Medium"
          ? "bg-amber-100 text-amber-900"
          : "bg-emerald-100 text-emerald-800");
      document.getElementById("scamHeadline").textContent = r.verdict_headline || "";
      document.getElementById("scamScoreNum").textContent = `${r.risk_score ?? 50}/100`;
      document.getElementById("scamRedFlags").innerHTML = (r.red_flags || [])
        .map((f) => `<li>${escapeHtml(f)}</li>`)
        .join("");
      document.getElementById("scamSafetyAdvice").textContent = r.safety_advice || "";
      document.getElementById("scamWhatsappBtn").href = data.whatsapp_share_url || "https://wa.me/";
      document.getElementById("scamResultSection").classList.remove("hidden");
    } catch (_err) {
    } finally {
      btn.disabled = false;
      btn.textContent = "🛡️ Scan Job for Scam Red Flags";
    }
  }

  async function runInterviewQuestions(e) {
    e.preventDefault();
    const btn = document.getElementById("iqSubmitBtn");
    btn.disabled = true;
    btn.textContent = "🎤 Building 10 STAR Q&As...";
    try {
      const data = await apiJson("/api/ai/interview-qs", {
        body: {
          jd_text: document.getElementById("iqJdText").value.trim(),
          cv_text: document.getElementById("iqCvText").value.trim(),
        },
      });
      const r = data.result;
      document.getElementById("iqRoleSummary").textContent = r.role_summary || "10 Tailored Interview Questions";
      document.getElementById("iqWhatsappBtn").href = data.whatsapp_share_url || "https://wa.me/";
      document.getElementById("iqListContainer").innerHTML = (r.questions || [])
        .map(
          (q) => `
          <details class="bg-white rounded-2xl border border-slate-200 p-4 group" ${q.number <= 2 ? "open" : ""}>
            <summary class="cursor-pointer font-bold text-sm text-slate-900 flex items-center justify-between gap-2">
              <span>Q${q.number}. ${escapeHtml(q.question)}</span>
              <span class="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 shrink-0">${escapeHtml(q.category)}</span>
            </summary>
            <div class="mt-3 pt-3 border-t border-slate-100 space-y-2 text-xs sm:text-sm">
              <div class="text-slate-500"><strong>Why recruiters ask:</strong> ${escapeHtml(q.why_they_ask)}</div>
              <div class="p-3 rounded-xl bg-slate-50 text-slate-800"><strong>Sample STAR Answer:</strong> ${escapeHtml(q.sample_answer)}</div>
            </div>
          </details>`
        )
        .join("");
      document.getElementById("iqResultSection").classList.remove("hidden");
    } catch (_err) {
    } finally {
      btn.disabled = false;
      btn.textContent = "🎤 Generate 10 Interview Q&As";
    }
  }

  // -------------------------------------------------------------------------
  // Pure-JS Tool #3: Freelance Hourly Rate Calculator
  // -------------------------------------------------------------------------
  function calcFreelanceRate() {
    const netKes = Number(document.getElementById("rcNetKes")?.value || 180000);
    const fx = Math.max(1, Number(document.getElementById("rcFxRate")?.value || 129.5));
    const hrsWeek = Math.max(1, Number(document.getElementById("rcHoursWeek")?.value || 25));
    const platformPct = Math.min(90, Math.max(0, Number(document.getElementById("rcPlatformFee")?.value || 10))) / 100;
    const withdrawPct = Math.min(50, Math.max(0, Number(document.getElementById("rcWithdrawFee")?.value || 2))) / 100;
    const taxPct = Math.min(70, Math.max(0, Number(document.getElementById("rcTaxRate")?.value || 15))) / 100;
    const overheadKes = Math.max(0, Number(document.getElementById("rcOverheadKes")?.value || 12000));

    const monthlyHours = hrsWeek * 4.2; // 4.2 billable weeks/month accounting for holidays/sick days
    const preTaxKes = (netKes + overheadKes) / Math.max(0.1, 1 - taxPct);
    const grossKesNeeded = preTaxKes / Math.max(0.1, (1 - platformPct) * (1 - withdrawPct));
    const grossUsdNeeded = grossKesNeeded / fx;
    const usdPerHr = grossUsdNeeded / monthlyHours;
    const kesPerHr = usdPerHr * fx;

    const feeUsd = grossUsdNeeded * platformPct;
    const withdrawUsd = (grossUsdNeeded - feeUsd) * withdrawPct;
    const taxAndOverheadKes = preTaxKes - netKes;

    const setTxt = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    setTxt("rcOutUsdHr", `$${usdPerHr.toFixed(2)}`);
    setTxt("rcOutKesHr", `≈ KES ${Math.round(kesPerHr).toLocaleString()} / billable hour`);
    setTxt("rcGrossUsd", `$${Math.round(grossUsdNeeded).toLocaleString()}/mo`);
    setTxt("rcFeeUsd", `-$${Math.round(feeUsd).toLocaleString()}`);
    setTxt("rcWithdrawUsd", `-$${Math.round(withdrawUsd).toLocaleString()}`);
    setTxt("rcTaxKes", `KES ${Math.round(taxAndOverheadKes).toLocaleString()}`);
    setTxt("rcCleanNetKes", `KES ${Math.round(netKes).toLocaleString()}`);

    const wa = document.getElementById("rcWhatsappShare");
    if (wa) {
      const msg = `💰 To take home KES ${Math.round(netKes).toLocaleString()}/mo on Upwork (${hrsWeek} hrs/wk), my minimum freelance rate is $${usdPerHr.toFixed(2)}/hr! Calculate yours free on ApplyKit: ${window.location.href}`;
      wa.href = `https://wa.me/?text=${encodeURIComponent(msg)}`;
    }
  }

  // -------------------------------------------------------------------------
  // Pure-JS Tool #4: 2026 PAYE Tax Calculator (Kenya + Nigeria + Ghana)
  // -------------------------------------------------------------------------
  function setPayeCountry(country) {
    activePayeCountry = ["kenya", "nigeria", "ghana"].includes(country) ? country : "kenya";
    const map = {
      kenya: { curr: "KES", sampleGross: 120000, btn: "tabCountryKenya" },
      nigeria: { curr: "NGN", sampleGross: 650000, btn: "tabCountryNigeria" },
      ghana: { curr: "GHS", sampleGross: 12000, btn: "tabCountryGhana" },
    };
    ["kenya", "nigeria", "ghana"].forEach((c) => {
      const b = document.getElementById(map[c].btn);
      if (!b) return;
      if (c === activePayeCountry) {
        b.className = "px-4 py-2 rounded-xl text-xs font-bold border border-emerald-600 bg-emerald-600 text-white";
      } else {
        b.className = "px-4 py-2 rounded-xl text-xs font-bold border border-slate-300 bg-white text-slate-700 hover:bg-slate-50";
      }
    });
    const curr = map[activePayeCountry].curr;
    const lbl = document.getElementById("payeCurrencyLabel");
    if (lbl) lbl.textContent = curr;
    document.querySelectorAll(".payeCurr").forEach((el) => (el.textContent = curr));

    const grossInput = document.getElementById("payeGross");
    if (grossInput && grossInput.dataset.lastCountry !== activePayeCountry) {
      if (grossInput.dataset.lastCountry) grossInput.value = map[activePayeCountry].sampleGross;
      grossInput.dataset.lastCountry = activePayeCountry;
    }
    calcPaye();
  }

  function calcPaye() {
    const grossBase = Math.max(0, Number(document.getElementById("payeGross")?.value || 0));
    const allow = Math.max(0, Number(document.getElementById("payeAllowances")?.value || 0));
    const volRelief = Math.max(0, Number(document.getElementById("payeVoluntaryPension")?.value || 0));
    const gross = grossBase + allow;

    let curr = "KES";
    let lines = [];
    let net = 0;
    let notes = "";

    if (activePayeCountry === "kenya") {
      curr = "KES";
      // 2026 Kenya Statutory: NSSF 6% capped at KES 4,320 (Tier I+II KES 72,000 upper limit), SHIF 2.75% (min 300), Housing Levy 1.5%
      const nssf = Math.min(gross * 0.06, 4320);
      const shif = gross > 0 ? Math.max(300, gross * 0.0275) : 0;
      const housing = gross * 0.015;
      const pensionDed = Math.min(volRelief, 30000);
      const taxable = Math.max(0, gross - nssf - shif - housing - pensionDed);

      // KRA Progressive Monthly Bands
      let tax = 0;
      const bands = [
        [24000, 0.1],
        [8333, 0.25],
        [467667, 0.3],
        [300000, 0.325],
        [Infinity, 0.35],
      ];
      let rem = taxable;
      for (const [width, rate] of bands) {
        if (rem <= 0) break;
        const slice = Math.min(rem, width);
        tax += slice * rate;
        rem -= slice;
      }
      const personalRelief = taxable > 0 ? 2400 : 0;
      const paye = Math.max(0, tax - personalRelief);
      const totalDed = nssf + shif + housing + paye;
      net = Math.max(0, gross - totalDed);
      lines = [
        ["Gross Pay", gross],
        ["NSSF (Tier I & II 6%)", -nssf],
        ["SHIF (2.75%)", -shif],
        ["Affordable Housing Levy (1.5%)", -housing],
        ["Taxable Income", taxable],
        ["Gross Tax Before Relief", tax],
        ["Personal Relief", -personalRelief],
        ["Net PAYE Tax (KRA)", -paye],
      ];
      notes = "Kenya 2026 KRA rules: NSSF (6% up to KES 4,320), SHIF (2.75%), and Housing Levy (1.5%) are deducted before computing PAYE, with KES 2,400 monthly personal relief.";
    } else if (activePayeCountry === "nigeria") {
      curr = "NGN";
      const pension = gross * 0.08;
      const nhf = gross * 0.025;
      const annualGross = gross * 12;
      const craMonthly = (Math.max(200000, 0.01 * annualGross) + 0.2 * annualGross) / 12;
      const taxable = Math.max(0, gross - pension - nhf - craMonthly - volRelief);
      const annualTaxable = taxable * 12;
      const ngBands = [
        [300000, 0.07],
        [300000, 0.11],
        [500000, 0.15],
        [500000, 0.19],
        [1600000, 0.21],
        [Infinity, 0.24],
      ];
      let rem = annualTaxable;
      let annualTax = 0;
      for (const [w, r] of ngBands) {
        if (rem <= 0) break;
        const s = Math.min(rem, w);
        annualTax += s * r;
        rem -= s;
      }
      const paye = annualTax / 12;
      net = Math.max(0, gross - pension - nhf - paye);
      lines = [
        ["Monthly Gross", gross],
        ["Pension (8%)", -pension],
        ["NHF (2.5%)", -nhf],
        ["CRA Tax-Free Allowance", -craMonthly],
        ["PAYE Tax (FIRS/SIRS)", -paye],
      ];
      notes = "Nigeria PAYE: Includes 8% employee Pension, 2.5% NHF, Consolidated Relief Allowance (CRA), and 7%–24% progressive annual bands.";
    } else {
      curr = "GHS";
      const ssnit = gross * 0.055;
      const taxable = Math.max(0, gross - ssnit - volRelief);
      const ghBands = [
        [490, 0.0],
        [110, 0.05],
        [130, 0.1],
        [3166.67, 0.175],
        [16000, 0.25],
        [30520, 0.3],
        [Infinity, 0.35],
      ];
      let rem = taxable;
      let paye = 0;
      for (const [w, r] of ghBands) {
        if (rem <= 0) break;
        const s = Math.min(rem, w);
        paye += s * r;
        rem -= s;
      }
      net = Math.max(0, gross - ssnit - paye);
      lines = [
        ["Monthly Gross", gross],
        ["SSNIT Tier 1 & 2 (5.5%)", -ssnit],
        ["Chargeable Income", taxable],
        ["GRA PAYE Tax", -paye],
      ];
      notes = "Ghana GRA PAYE: Deducts 5.5% employee SSNIT contribution first, then applies 0%–35% monthly progressive GRA bands.";
    }

    const fmt = (n) => `${curr} ${Math.round(Math.abs(n)).toLocaleString()}`;
    const netEl = document.getElementById("payeNetPay");
    if (netEl) netEl.textContent = `${curr} ${Math.round(net).toLocaleString()}`;
    const eff = gross > 0 ? (((gross - net) / gross) * 100).toFixed(1) : "0.0";
    const effEl = document.getElementById("payeEffectiveRate");
    if (effEl) effEl.textContent = `Total Deductions: ${eff}% of gross`;
    const notesEl = document.getElementById("payeBandsNotes");
    if (notesEl) notesEl.textContent = notes;

    const box = document.getElementById("payeLinesContainer");
    if (box) {
      box.innerHTML = lines
        .map(
          ([label, val]) => `
          <div class="flex justify-between">
            <span class="text-slate-400">${escapeHtml(label)}</span>
            <span class="${val < 0 ? "text-rose-300" : "text-white font-semibold"}">${val < 0 ? "-" : ""}${fmt(val)}</span>
          </div>`
        )
        .join("");
    }
    const wa = document.getElementById("payeWhatsappBtn");
    if (wa) {
      wa.href = `https://wa.me/?text=${encodeURIComponent(
        `🧮 Gross ${curr} ${Math.round(gross).toLocaleString()} → Net Pay ${curr} ${Math.round(net).toLocaleString()} (${activePayeCountry.toUpperCase()} 2026 PAYE Calculator on ApplyKit): ${window.location.href}`
      )}`;
    }
  }

  // -------------------------------------------------------------------------
  // Pure-JS Tool #6: Printable Freelance Invoice Generator
  // -------------------------------------------------------------------------
  function renderInvoice() {
    const curr = document.getElementById("invCurrency")?.value || "KES";
    const qty = Math.max(1, Number(document.getElementById("invQty")?.value || 1));
    const rate = Math.max(0, Number(document.getElementById("invRate")?.value || 0));
    const taxPct = Math.max(0, Number(document.getElementById("invTax")?.value || 0));
    const sub = qty * rate;
    const taxAmt = (sub * taxPct) / 100;
    const total = sub + taxAmt;

    const set = (id, v) => {
      const el = document.getElementById(id);
      if (el) el.textContent = v;
    };
    set("prevInvNumber", document.getElementById("invNumber")?.value || "INV-001");
    set("prevInvDate", new Date().toISOString().slice(0, 10));
    set("prevInvFrom", document.getElementById("invFrom")?.value || "");
    set("prevInvTo", document.getElementById("invTo")?.value || "");
    set("prevInvDesc", document.getElementById("invDesc")?.value || "");
    set("prevInvQty", String(qty));
    set("prevInvSubtotal", `${curr} ${sub.toLocaleString()}`);
    set("prevInvTaxAmt", `${curr} ${taxAmt.toLocaleString()}`);
    set("prevInvTotal", `${curr} ${total.toLocaleString()}`);
    set("prevInvPayment", document.getElementById("invPaymentDetails")?.value || "");
  }

  // -------------------------------------------------------------------------
  // Dashboard Kanban + Drag-Drop + CSV + WhatsApp Interview Reminder
  // -------------------------------------------------------------------------
  async function loadDashboard() {
    const q = document.getElementById("dashSearchInput")?.value || "";
    const statusFilter = document.getElementById("dashStatusFilter")?.value || "";
    try {
      const res = await fetch(
        `/api/applications/list?q=${encodeURIComponent(q)}&status_filter=${encodeURIComponent(statusFilter)}`,
        { headers: authHeaders() }
      );
      if (!res.ok) return;
      const data = await res.json();
      const stats = data.stats || {};
      const apps = data.applications || [];

      document.getElementById("statTotalApps").textContent = String(stats.total || 0);
      document.getElementById("statInterviewRate").textContent = `${stats.interview_rate_pct || 0}%`;
      document.getElementById("statInterviewBar").style.width = `${Math.min(100, stats.interview_rate_pct || 0)}%`;
      document.getElementById("statWeeklyLabel").textContent = `${stats.applied_this_week || 0} / ${stats.weekly_goal || 10}`;
      document.getElementById("statWeeklyBar").style.width = `${stats.weekly_goal_pct || 0}%`;
      document.getElementById("statFollowupsCount").textContent = String(stats.followups_due_count || 0);

      const stages = ["Applied", "Interview", "Offer", "Rejected"];
      stages.forEach((stage) => {
        const stageApps = apps.filter((a) => (a.status === "Saved" ? "Applied" : a.status) === stage);
        const countEl = document.getElementById(`countStage${stage}`);
        if (countEl) countEl.textContent = String(stageApps.length);
        const col = document.getElementById(`colStage${stage}`);
        if (!col) return;

        col.innerHTML = stageApps
          .map((a) => {
            const waReminder = a.interview_at
              ? `<a href="https://wa.me/?text=${encodeURIComponent(
                  `📅 Interview Reminder: ${a.job_title} at ${a.company} scheduled for ${a.interview_at}`
                )}" target="_blank" rel="noopener" class="text-[11px] text-green-700 font-semibold hover:underline block mt-1">💬 WhatsApp Interview Reminder</a>`
              : "";
            return `
              <div draggable="true" ondragstart="event.dataTransfer.setData('text/plain', '${a.id}')"
                class="bg-white rounded-xl p-3 border border-slate-200 shadow-sm cursor-grab active:cursor-grabbing space-y-1.5">
                <div class="flex items-start justify-between gap-2">
                  <div class="font-bold text-xs text-slate-900 leading-snug">${escapeHtml(a.job_title)}</div>
                  <button type="button" onclick="window.ApplyKit.deleteApp('${a.id}')" class="text-slate-300 hover:text-rose-600 text-xs">✕</button>
                </div>
                <div class="text-[11px] text-slate-500">${escapeHtml(a.company)} · <span class="font-semibold">${escapeHtml(a.platform)}</span></div>
                ${a.salary ? `<div class="text-[11px] text-emerald-700 font-semibold">${escapeHtml(a.salary)}</div>` : ""}
                ${a.match_score != null ? `<span class="inline-block text-[10px] px-2 py-0.5 rounded bg-emerald-50 text-emerald-800 font-bold">Match ${a.match_score}%</span>` : ""}
                ${a.private_notes ? `<p class="text-[11px] text-slate-500 bg-slate-50 p-1.5 rounded">${escapeHtml(a.private_notes)}</p>` : ""}
                ${waReminder}
              </div>`;
          })
          .join("");
      });
    } catch (_err) {}
  }

  function openAddAppModal() {
    document.getElementById("addAppModal")?.classList.remove("hidden");
  }

  async function saveNewApp(e) {
    e.preventDefault();
    await apiJson("/api/applications/save", {
      body: {
        job_title: document.getElementById("appTitle").value.trim(),
        company: document.getElementById("appCompany").value.trim() || "Unknown Client",
        platform: document.getElementById("appPlatform").value,
        salary: document.getElementById("appSalary").value.trim(),
        status: document.getElementById("appStatus").value,
        interview_at: document.getElementById("appInterviewAt").value || null,
        private_notes: document.getElementById("appNotes").value.trim(),
      },
    });
    document.getElementById("addAppModal")?.classList.add("hidden");
    e.target.reset();
    loadDashboard();
    toast("Application saved!");
  }

  async function handleKanbanDrop(e, newStage) {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/plain");
    if (!id) return;
    await apiJson("/api/applications/update", { body: { id, status: newStage } });
    loadDashboard();
  }

  async function deleteApp(id) {
    await apiJson("/api/applications/delete", { body: { id } });
    loadDashboard();
  }

  async function exportAppsCsv() {
    const res = await fetch("/api/applications/export.csv", { headers: authHeaders() });
    if (res.status === 402) {
      openUpgradeModal("CSV Export is an ApplyKit Pro feature. Upgrade via M-Pesa (750 KES) or Lemon Squeezy ($6/mo)!");
      return;
    }
    if (!res.ok) {
      toast("Sign in first to export applications.");
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "applykit_applications.csv";
    a.click();
  }

  // -------------------------------------------------------------------------
  // M-Pesa STK Push + 3-Second Verification Polling + Manual Till + Admin
  // -------------------------------------------------------------------------
  function startPollingCheckout(checkoutId, statusEl) {
    if (stkPollTimer) clearInterval(stkPollTimer);
    let attempts = 0;
    stkPollTimer = setInterval(async () => {
      attempts += 1;
      if (attempts > 30) {
        clearInterval(stkPollTimer);
        return;
      }
      const res = await fetch(`/api/payments/verify?checkout_id=${encodeURIComponent(checkoutId)}`);
      const data = await res.json().catch(() => ({}));
      if (data.status === "success") {
        clearInterval(stkPollTimer);
        statusEl.textContent = "🎉 M-Pesa Payment Confirmed! ApplyKit Pro is now active — reloading...";
        setTimeout(() => window.location.reload(), 1400);
      } else if (data.status === "failed") {
        clearInterval(stkPollTimer);
        statusEl.textContent = "Payment cancelled or timed out on handset. Try again or use Manual Till below.";
      }
    }, 3000);
  }

  async function triggerQuickMpesa(e) {
    e.preventDefault();
    const phone = document.getElementById("modalMpesaPhone").value.trim();
    const statusEl = document.getElementById("modalMpesaStatus");
    statusEl.classList.remove("hidden");
    statusEl.textContent = "Sending Safaricom STK Push to your phone...";
    try {
      const data = await apiJson("/api/payments/mpesa/stk-push", { body: { phone, plan: "monthly" } });
      statusEl.textContent = `${data.customer_message} (Ref: ${data.checkout_request_id}) — Polling confirmation every 3s...`;
      startPollingCheckout(data.checkout_request_id, statusEl);
    } catch (err) {
      statusEl.textContent = err.message;
    }
  }

  async function startPricingMpesa(e, plan = "monthly") {
    e.preventDefault();
    const phone = document.getElementById("pricingMpesaPhone").value.trim();
    const box = document.getElementById("pricingMpesaPollBox");
    box.classList.remove("hidden");
    box.textContent = "Contacting Safaricom Daraja STK Push...";
    try {
      const data = await apiJson("/api/payments/mpesa/stk-push", { body: { phone, plan } });
      box.textContent = `📲 ${data.customer_message} Waiting for M-Pesa PIN...`;
      startPollingCheckout(data.checkout_request_id, box);
    } catch (err) {
      box.textContent = err.message;
    }
  }

  function startLifetimeMpesa() {
    const phoneInput = document.getElementById("pricingMpesaPhone");
    if (!phoneInput || !phoneInput.value.trim()) {
      phoneInput?.focus();
      toast("Enter your Safaricom phone number in the M-Pesa box first!");
      return;
    }
    startPricingMpesa({ preventDefault: () => {} }, "lifetime");
  }

  async function submitManualTillForm(e) {
    e.preventDefault();
    const msg = document.getElementById("tillSubmitMsg");
    const data = await apiJson("/api/payments/mpesa/manual-till", {
      body: {
        mpesa_code: document.getElementById("tillCode").value.trim(),
        phone: document.getElementById("tillPhone").value.trim(),
        email: document.getElementById("tillEmail").value.trim(),
        plan: "monthly",
      },
    });
    msg.textContent = data.message;
    msg.classList.remove("hidden");
    e.target.reset();
  }

  async function adminTogglePro(e) {
    e.preventDefault();
    const email = document.getElementById("adminTargetEmail").value.trim();
    const sel = document.getElementById("adminTargetPlan").value;
    const is_pro = sel !== "revoke";
    const plan = sel === "lifetime" ? "lifetime" : "monthly";
    const data = await apiJson("/api/payments/admin/toggle-pro", { body: { email, is_pro, plan } });
    const out = document.getElementById("adminToggleResult");
    out.textContent = data.message;
    out.classList.remove("hidden");
  }

  async function adminQuickApprove(email, plan, checkoutId) {
    await apiJson("/api/payments/admin/toggle-pro", {
      body: { email, is_pro: true, plan: plan || "monthly", checkout_id: checkoutId },
    });
    toast(`Approved Pro for ${email}`);
    setTimeout(() => window.location.reload(), 800);
  }

  // -------------------------------------------------------------------------
  // Cookie Consent (GDPR & Kenya DPA) + Global Keyboard Shortcuts (Cmd/Ctrl+K)
  // -------------------------------------------------------------------------
  function acceptCookies(choice) {
    localStorage.setItem("applykit_cookie_consent", choice);
    document.getElementById("cookieConsentBanner")?.classList.add("hidden");
  }

  document.addEventListener("DOMContentLoaded", () => {
    initSupabaseAuth();

    if (!localStorage.getItem("applykit_cookie_consent")) {
      document.getElementById("cookieConsentBanner")?.classList.remove("hidden");
    }

    const paletteInput = document.getElementById("paletteSearchInput");
    if (paletteInput) {
      paletteInput.addEventListener("input", (ev) => {
        clearTimeout(routerDebounce);
        routerDebounce = setTimeout(() => fetchRouterResults(ev.target.value), 160);
      });
    }

    document.addEventListener("keydown", (ev) => {
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        openPalette();
      } else if (ev.key === "Escape") {
        closePalette();
        closeModals();
      }
    });

    // Initialize AdSense slots if script present
    try {
      document.querySelectorAll("ins.adsbygoogle").forEach(() => {
        (window.adsbygoogle = window.adsbygoogle || []).push({});
      });
    } catch (_e) {}
  });

  window.ApplyKit = {
    openPalette,
    closePalette,
    backToPaletteList,
    quickQuery,
    selectRoutedTool,
    submitVaultTool,
    copyVaultOutput,
    copyElementText,
    downloadTextAsPdf,
    uploadCvFile,
    loadSampleAts,
    runAtsChecker,
    downloadScoreBadgeImage,
    runCoverLetter,
    loadSampleScam,
    runScamDetector,
    runInterviewQuestions,
    calcFreelanceRate,
    setPayeCountry,
    calcPaye,
    renderInvoice,
    loadDashboard,
    openAddAppModal,
    saveNewApp,
    handleKanbanDrop,
    deleteApp,
    exportAppsCsv,
    openLoginModal,
    openUpgradeModal,
    closeModals,
    signInWithGoogle,
    signInWithGitHub,
    signInWithEmailPassword,
    devQuickLogin,
    logout,
    deleteMyData,
    triggerQuickMpesa,
    startPricingMpesa,
    startLifetimeMpesa,
    submitManualTillForm,
    adminTogglePro,
    adminQuickApprove,
    acceptCookies,
  };
})();
