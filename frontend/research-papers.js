/**
 * ==========================================================================
 * AI RESEARCH PAPER RECOMMENDATION & VALIDATION MODULE
 * Seamlessly integrated into Student and Faculty Dashboards
 * ==========================================================================
 */

(function (window) {
  'use strict';

  let currentTeamData = null;
  let currentUserRole = "team";
  let selectedPaperForReview = null;
  let projectLoadSequence = 0;
  let isInitialized = false;

  function getToken() {
    return localStorage.getItem("token") || new URLSearchParams(window.location.search).get("token") || "";
  }

  function parseUserRole() {
    const token = getToken();
    if (!token) return "team";
    try {
      const base64Url = token.split('.')[1];
      const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      const jsonPayload = decodeURIComponent(
        atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')
      );
      const decoded = JSON.parse(jsonPayload);
      const r = (decoded.role || "").toLowerCase();
      if (r === "faculty") return "faculty";
      if (r === "coordinator") return "coordinator";
      return "team"; // students and teams
    } catch (e) {
      console.warn("Error decoding token payload:", e);
      return "team";
    }
  }

  function initResearchPaperSection(forceReload) {
    if (isInitialized && !forceReload) {
      return;
    }
    isInitialized = true;
    currentUserRole = parseUserRole();

    // Update Back button text based on role
    const backBtnText = document.getElementById("rpBackBtnText");
    if (backBtnText) {
      backBtnText.textContent = (currentUserRole === "faculty" || currentUserRole === "coordinator")
        ? "Back to Teams"
        : "Back to Project Idea";
    }

    // Role-specific initialization
    if (currentUserRole === "team") {
      const facBanner = document.getElementById("facultyTeamBanner");
      if (facBanner) facBanner.classList.add("rp-hidden");
      loadStudentProjectHeader();
    } else {
      const facBanner = document.getElementById("facultyTeamBanner");
      if (facBanner) facBanner.classList.remove("rp-hidden");
      setupFacultySupervisionMode();
    }

    setupDragAndDrop();

    // Auto-Fetch button binding
    const btnAutoFetch = document.getElementById("btnAutoFetch");
    if (btnAutoFetch && !btnAutoFetch._bound) {
      btnAutoFetch.addEventListener("click", autoFetchPapers);
      btnAutoFetch._bound = true;
    }
  }

  function returnFromResearchPapers() {
    if (typeof window.showSection === "function") {
      if (currentUserRole === "faculty" || currentUserRole === "coordinator") {
        window.showSection("teams");
      } else {
        window.showSection("project");
      }
    }
  }

  function setProjectStatus(message, isLoading) {
    currentTeamData = null;
    const titleEl = document.getElementById("projTitle");
    const abstractEl = document.getElementById("projAbstract");
    const teamEl = document.getElementById("projTeamDetails");
    const guideEl = document.getElementById("projGuide");
    const studentsEl = document.getElementById("projStudents");
    const keywordsEl = document.getElementById("projKeywords");
    const loadingEl = document.getElementById("projectLoading");
    const papersGrid = document.getElementById("papersGrid");
    const recLoading = document.getElementById("recLoading");
    const savedList = document.getElementById("savedPapersList");

    if (titleEl) titleEl.textContent = isLoading ? "Loading Project Details..." : "Project Details";
    if (abstractEl) abstractEl.textContent = message;
    if (teamEl) teamEl.textContent = "Not available";
    if (guideEl) guideEl.textContent = "Not available";
    if (studentsEl) studentsEl.textContent = "Not available";
    if (keywordsEl) keywordsEl.replaceChildren();
    if (loadingEl) loadingEl.classList.toggle("rp-hidden", !isLoading);
    if (papersGrid) papersGrid.replaceChildren();
    if (recLoading) recLoading.classList.add("rp-hidden");
    if (savedList) savedList.innerHTML = `<div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center;"><p style="color: var(--text-muted);">${message}</p></div>`;
  }

  function appendProjectTag(label) {
    const keywordsEl = document.getElementById("projKeywords");
    if (!keywordsEl) return;
    const tag = document.createElement("span");
    tag.className = "rp-meta-tag";
    tag.textContent = label;
    keywordsEl.appendChild(tag);
  }

  function renderProjectData(data) {
    currentTeamData = data;
    const project = data.project_info || {};
    const title = project.title || "Untitled Project";
    const teamName = data.team_name || "Team";

    const titleEl = document.getElementById("projTitle");
    if (titleEl) titleEl.textContent = `${teamName} — ${title}`;

    const abstractEl = document.getElementById("projAbstract");
    if (abstractEl) {
      abstractEl.textContent = project.abstract || "No abstract submitted yet.";
    }

    const teamEl = document.getElementById("projTeamDetails");
    if (teamEl) teamEl.textContent = teamName;

    const guideEl = document.getElementById("projGuide");
    if (guideEl) {
      const guide = data.guide || {};
      guideEl.textContent = guide.name || guide.email || "Not assigned";
    }

    const studentsEl = document.getElementById("projStudents");
    if (studentsEl) {
      const students = Array.isArray(data.students) ? data.students : [];
      studentsEl.textContent = students.length
        ? students.map(s => s.display_name || s.name || "Student").join(", ")
        : "Not provided";
    }

    const keywordsEl = document.getElementById("projKeywords");
    if (keywordsEl) {
      keywordsEl.replaceChildren();
      const technologies = Array.isArray(project.technologies)
        ? project.technologies
        : (project.technologies ? [project.technologies] : []);
      const tags = [
        project.domain,
        ...technologies,
        ...(Array.isArray(project.keywords) ? project.keywords : []),
        project.status && `Status: ${project.status}`
      ].filter(Boolean);

      tags.forEach(tag => appendProjectTag(String(tag)));
    }

    const loadingEl = document.getElementById("projectLoading");
    if (loadingEl) loadingEl.classList.add("rp-hidden");

    const papersGrid = document.getElementById("papersGrid");
    if (papersGrid) papersGrid.replaceChildren();

    const savedList = document.getElementById("savedPapersList");
    if (savedList) {
      renderSavedPapers(data.saved_papers || [], savedList);
    }
  }

  async function loadStudentProjectHeader() {
    const loadId = ++projectLoadSequence;
    setProjectStatus("Retrieving your submitted project metadata from database...", true);
    const token = getToken();

    try {
      const res = await fetch("/api/research/team-data", {
        headers: { "Authorization": `Bearer ${token}` }
      });
      await handleProjectResponse(res, loadId);
    } catch (e) {
      console.error("Failed to load student research project data:", e);
      if (loadId === projectLoadSequence) {
        setProjectStatus(`Unable to load project details: ${e.message}`);
      }
    }
  }

  async function handleProjectResponse(res, loadId) {
    if (loadId !== projectLoadSequence) return;
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      data = {};
    }
    if (loadId !== projectLoadSequence) return;
    if (!res.ok) {
      const message = res.status === 404 && data.error && data.error.toLowerCase().includes("project")
        ? "No eligible project details are available for this team."
        : (data.error || `Request failed (${res.status})`);
      setProjectStatus(message);
      return;
    }
    if (!data.project_info) {
      setProjectStatus("No eligible project details are available for this team.");
      return;
    }
    renderProjectData(data);
  }

  async function setupFacultySupervisionMode() {
    const token = getToken();
    const facBanner = document.getElementById("facultyTeamBanner");
    if (facBanner) facBanner.classList.remove("rp-hidden");
    setProjectStatus("Select a team to load its project details.");

    try {
      const dashboardUrl = currentUserRole === "coordinator"
        ? "/api/dashboard/coordinator"
        : "/api/dashboard/faculty";
      const res = await fetch(dashboardUrl, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);

      const select = document.getElementById("facultyTeamSelect");
      if (!select) return;
      select.replaceChildren();

      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "-- Select Team --";
      select.appendChild(placeholder);

      const teams = data.allocated_teams || data.teams || [];
      teams.forEach(team => {
        const option = document.createElement("option");
        option.value = team.team_name || "";
        option.textContent = `${team.team_name || "Unnamed Team"}${team.leader_name ? ` — ${team.leader_name}` : ""}`;
        select.appendChild(option);
      });

      select.onchange = (e) => loadFacultyTeamData(e.target.value);

      if (teams.length === 0) {
        placeholder.textContent = "No teams assigned to you yet";
        setProjectStatus("No eligible teams are assigned to your account.");
      } else if (teams.length === 1 && teams[0].team_name) {
        // Automatically select the single team for smoother experience
        select.value = teams[0].team_name;
        loadFacultyTeamData(teams[0].team_name);
      }
    } catch (e) {
      console.error("Faculty mode error:", e);
      setProjectStatus(`Unable to load your teams: ${e.message}`);
    }
  }

  async function loadFacultyTeamData(teamName) {
    const loadId = ++projectLoadSequence;
    if (!teamName) {
      setProjectStatus("Select a team to load its project details.");
      return;
    }
    setProjectStatus(`Loading project details for ${teamName}...`, true);
    const grid = document.getElementById("savedPapersList");
    if (grid) {
      grid.innerHTML = `<div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center;"><div class="rp-spinner"></div><p style="margin-top:0.75rem;">Loading project details &amp; papers for ${teamName}...</p></div>`;
    }
    const papersGrid = document.getElementById("papersGrid");
    if (papersGrid) papersGrid.replaceChildren();

    const token = getToken();
    try {
      const res = await fetch(`/api/research/team-data/${encodeURIComponent(teamName)}`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      await handleProjectResponse(res, loadId);
    } catch (e) {
      console.error("Error loading team research data:", e);
      if (loadId === projectLoadSequence) {
        setProjectStatus(`Unable to load project details: ${e.message}`);
        if (grid) grid.textContent = `Unable to load saved papers: ${e.message}`;
      }
    }
  }

  function switchResearchTab(tabId) {
    const tabs = ["recommendations", "upload", "saved"];
    tabs.forEach(id => {
      const btn = document.getElementById(`tabBtn-${id}`);
      const content = document.getElementById(`tab-${id}`);
      if (btn) btn.classList.toggle("active", id === tabId);
      if (content) content.classList.toggle("active", id === tabId);
    });

    if (tabId === "recommendations") {
      const grid = document.getElementById("papersGrid");
      if (grid && grid.children.length === 0 && currentTeamData && currentTeamData.project_info) {
        autoFetchPapers();
      }
    } else if (tabId === "saved") {
      loadSavedPapers();
    }
  }

  async function autoFetchPapers() {
    const loading = document.getElementById("recLoading");
    const grid = document.getElementById("papersGrid");
    if (!grid) return;

    if (!currentTeamData || !currentTeamData.project_info) {
      grid.innerHTML = `<div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center;"><p style="color: var(--text-muted);">Please load an eligible project before requesting recommendations.</p></div>`;
      return;
    }

    const requestSequence = projectLoadSequence;
    const expectedTeam = currentTeamData.team_name;
    const expectedTitle = currentTeamData.project_info.title || "Untitled Project";

    if (loading) loading.classList.remove("rp-hidden");
    grid.replaceChildren();

    const token = getToken();
    try {
      const select = document.getElementById("facultyTeamSelect");
      const selectedTeam = select ? select.value : "";
      const url = selectedTeam
        ? `/api/research/recommendations?team_name=${encodeURIComponent(selectedTeam)}`
        : "/api/research/recommendations";

      const res = await fetch(url, {
        headers: { "Authorization": `Bearer ${token}` }
      });

      if (requestSequence !== projectLoadSequence) return;
      if (loading) loading.classList.add("rp-hidden");

      if (res.ok) {
        const data = await res.json();
        if (requestSequence !== projectLoadSequence) return;
        if (data.team_name !== expectedTeam || data.project_title !== expectedTitle) {
          throw new Error("Recommendations were returned for a different project. Please retry.");
        }
        renderPaperCards(data.papers || [], grid);
      } else {
        const errData = await res.json().catch(() => ({}));
        grid.innerHTML = `<div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center;"><p style="color: var(--status-danger);">${errData.error || "Failed to fetch paper recommendations."}</p></div>`;
      }
    } catch (e) {
      if (requestSequence !== projectLoadSequence) return;
      if (loading) loading.classList.add("rp-hidden");
      grid.innerHTML = `<div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center;"><p style="color: var(--status-danger);">${e.message}</p></div>`;
    }
  }

  function renderPaperCards(papers, containerElement) {
    if (!containerElement) return;
    if (!papers || papers.length === 0) {
      containerElement.innerHTML = `
        <div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center; padding: 2.5rem 1rem;">
          <i class="fa-solid fa-file-circle-question" style="font-size: 2.5rem; color: var(--text-muted); margin-bottom: 0.75rem;"></i>
          <p style="color: var(--text-muted); font-size: 0.95rem;">No research papers found matching project keywords.</p>
        </div>
      `;
      return;
    }

    containerElement.replaceChildren();
    papers.forEach(p => {
      const rel = p.relevance_percentage || 70;
      let badgeClass = "rp-relevance-high";
      if (rel < 50) badgeClass = "rp-relevance-low";
      else if (rel < 75) badgeClass = "rp-relevance-medium";

      const card = document.createElement("div");
      card.className = "rp-paper-card";

      const topSection = document.createElement("div");

      const header = document.createElement("div");
      header.className = "rp-paper-header";
      header.innerHTML = `
        <div class="rp-paper-title">${escapeHtml(p.title)}</div>
        <span class="rp-relevance-badge ${badgeClass}"><i class="fa-solid fa-percent"></i> ${rel}% Related</span>
      `;
      topSection.appendChild(header);

      const authors = document.createElement("div");
      authors.className = "rp-paper-authors";
      authors.innerHTML = `<i class="fa-solid fa-users"></i> ${escapeHtml(p.authors || "Unknown Authors")} (${p.year || "N/A"})`;
      topSection.appendChild(authors);

      const abstract = document.createElement("div");
      abstract.className = "rp-paper-abstract";
      abstract.textContent = p.abstract || "No abstract available.";
      topSection.appendChild(abstract);

      const metaRow = document.createElement("div");
      metaRow.className = "rp-paper-meta-row";
      metaRow.innerHTML = `
        <span class="rp-info-pill"><i class="fa-solid fa-quote-left"></i> ${p.citation_count || 0} Citations</span>
        <span class="rp-info-pill">${p.is_open_access ? '🔓 Open Access' : '🔒 Restricted'}</span>
      `;
      topSection.appendChild(metaRow);

      card.appendChild(topSection);

      const actions = document.createElement("div");
      actions.className = "rp-paper-actions";

      const btnAi = document.createElement("button");
      btnAi.type = "button";
      btnAi.className = "rp-btn-sm rp-btn-outline";
      btnAi.innerHTML = `<i class="fa-solid fa-brain"></i> AI Analysis`;
      btnAi.onclick = () => showAlignmentModal(p);
      actions.appendChild(btnAi);

      if (p.pdf_url) {
        const linkPdf = document.createElement("a");
        linkPdf.href = p.pdf_url;
        linkPdf.target = "_blank";
        linkPdf.rel = "noopener noreferrer";
        linkPdf.className = "rp-btn-sm rp-btn-outline";
        linkPdf.innerHTML = `<i class="fa-solid fa-file-pdf"></i> View PDF`;
        actions.appendChild(linkPdf);
      }

      const btnSave = document.createElement("button");
      btnSave.type = "button";
      btnSave.className = "rp-btn-sm rp-btn-success";
      btnSave.innerHTML = `<i class="fa-solid fa-bookmark"></i> Save Paper`;
      btnSave.onclick = () => savePaper(p);
      actions.appendChild(btnSave);

      card.appendChild(actions);
      containerElement.appendChild(card);
    });
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function showAlignmentModal(paper) {
    const ai = paper.ai_analysis || {};
    const modalTitle = document.getElementById("modalPaperTitle");
    const modalRel = document.getElementById("modalRelBadge");
    const modalConf = document.getElementById("modalConfBadge");
    const modalExpl = document.getElementById("modalExplanation");

    if (modalTitle) modalTitle.textContent = paper.title || "Paper Alignment Analysis";
    if (modalRel) modalRel.textContent = `${paper.relevance_percentage || 75}% Related`;
    if (modalConf) modalConf.textContent = `Confidence: ${paper.confidence_score || ai.confidence_score || 85}%`;
    if (modalExpl) modalExpl.textContent = ai.explanation || "Shares structural topic alignment with the student project.";

    // Topics & Tech tags
    const topicsBox = document.getElementById("modalTopics");
    if (topicsBox) {
      topicsBox.replaceChildren();
      const topics = [...(ai.matching_topics || []), ...(ai.matching_technologies || []), ...(ai.matching_keywords || [])];
      if (topics.length > 0) {
        topics.forEach(t => {
          const span = document.createElement("span");
          span.className = "rp-match-tag";
          span.innerHTML = `<i class="fa-solid fa-check"></i> ${escapeHtml(t)}`;
          topicsBox.appendChild(span);
        });
      } else {
        topicsBox.innerHTML = `<em style="color:var(--text-muted); font-size:0.85rem;">No common topics identified</em>`;
      }
    }

    // Objectives tags
    const objBox = document.getElementById("modalObjectives");
    if (objBox) {
      objBox.replaceChildren();
      const objectives = ai.matching_objectives || [];
      if (objectives.length > 0) {
        objectives.forEach(o => {
          const span = document.createElement("span");
          span.className = "rp-match-tag";
          span.innerHTML = `<i class="fa-solid fa-bullseye"></i> ${escapeHtml(o)}`;
          objBox.appendChild(span);
        });
      } else {
        objBox.innerHTML = `<em style="color:var(--text-muted); font-size:0.85rem;">None identified</em>`;
      }
    }

    // Key similarities
    const simList = document.getElementById("modalSimilarities");
    if (simList) {
      simList.replaceChildren();
      const sims = ai.key_similarities || [];
      sims.forEach(s => {
        const li = document.createElement("li");
        li.style.marginBottom = "4px";
        li.textContent = s;
        simList.appendChild(li);
      });
      if (!simList.children.length) {
        simList.innerHTML = `<li style="color:var(--text-muted);">Not available</li>`;
      }
    }

    // Key differences
    const diffList = document.getElementById("modalDifferences");
    if (diffList) {
      diffList.replaceChildren();
      const diffs = ai.key_differences || [];
      diffs.forEach(d => {
        const li = document.createElement("li");
        li.style.marginBottom = "4px";
        li.textContent = d;
        diffList.appendChild(li);
      });
      if (!diffList.children.length) {
        diffList.innerHTML = `<li style="color:var(--text-muted);">Not available</li>`;
      }
    }

    const modal = document.getElementById("alignmentModal");
    if (modal) modal.style.display = "flex";
  }

  function closeAlignmentModal() {
    const modal = document.getElementById("alignmentModal");
    if (modal) modal.style.display = "none";
  }

  async function savePaper(paper) {
    const token = getToken();
    try {
      const select = document.getElementById("facultyTeamSelect");
      const selectedTeam = select ? select.value : "";
      const paperCopy = Object.assign({}, paper);
      if (selectedTeam) {
        paperCopy.team_name = selectedTeam;
      }

      const res = await fetch("/api/research/save-paper", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify(paperCopy)
      });

      if (res.ok) {
        alert("Research paper saved successfully!");
      } else {
        const err = await res.json().catch(() => ({}));
        alert("Error saving paper: " + (err.error || "Failed"));
      }
    } catch (e) {
      alert("Error: " + e.message);
    }
  }

  async function loadSavedPapers() {
    const grid = document.getElementById("savedPapersList");
    if (!grid) return;

    if (!currentTeamData) {
      grid.innerHTML = `<div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center;"><p style="color: var(--text-muted);">Please load an eligible project before viewing saved papers.</p></div>`;
      return;
    }

    const expectedTeam = currentTeamData.team_name;
    const requestSequence = projectLoadSequence;
    grid.innerHTML = `<div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center;"><div class="rp-spinner"></div><p style="margin-top:0.75rem;">Loading saved papers...</p></div>`;

    const token = getToken();
    try {
      const res = await fetch(`/api/research/saved-papers?team_name=${encodeURIComponent(expectedTeam)}`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      const data = await res.json().catch(() => ({}));
      if (requestSequence !== projectLoadSequence) return;
      if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
      if (data.team_name !== expectedTeam) {
        throw new Error("Saved papers were returned for a different team.");
      }
      renderSavedPapers(data.papers || [], grid);
    } catch (e) {
      if (requestSequence === projectLoadSequence) {
        grid.innerHTML = `<div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center;"><p style="color: var(--status-danger);">Unable to load saved papers: ${e.message}</p></div>`;
      }
    }
  }

  function renderSavedPapers(papers, container) {
    if (!container) return;
    if (!papers || papers.length === 0) {
      container.innerHTML = `
        <div class="rp-analysis-box" style="grid-column: 1/-1; text-align: center; padding: 2.5rem 1rem;">
          <i class="fa-solid fa-bookmark" style="font-size: 2.5rem; color: var(--text-muted); margin-bottom: 0.75rem;"></i>
          <p style="color: var(--text-muted); font-size: 0.95rem;">No saved research papers found for this team.</p>
        </div>
      `;
      return;
    }

    container.replaceChildren();
    papers.forEach(p => {
      const card = document.createElement("div");
      card.className = "rp-paper-card";

      const topSection = document.createElement("div");

      let statusBadge = `<span class="rp-relevance-badge rp-relevance-medium"><i class="fa-solid fa-clock"></i> Pending Review</span>`;
      if (p.status === "Approved") {
        statusBadge = `<span class="rp-relevance-badge rp-relevance-high"><i class="fa-solid fa-circle-check"></i> Approved</span>`;
      } else if (p.status === "Rejected") {
        statusBadge = `<span class="rp-relevance-badge rp-relevance-low"><i class="fa-solid fa-circle-xmark"></i> Rejected</span>`;
      }

      const header = document.createElement("div");
      header.className = "rp-paper-header";
      header.innerHTML = `
        <div class="rp-paper-title">${escapeHtml(p.title)}</div>
        ${statusBadge}
      `;
      topSection.appendChild(header);

      const authors = document.createElement("div");
      authors.className = "rp-paper-authors";
      authors.innerHTML = `<i class="fa-solid fa-users"></i> ${escapeHtml(p.authors || "Unknown Authors")} (${p.year || "N/A"})`;
      topSection.appendChild(authors);

      const abstract = document.createElement("div");
      abstract.className = "rp-paper-abstract";
      abstract.textContent = p.abstract || "No abstract available.";
      topSection.appendChild(abstract);

      if (p.faculty_comment) {
        const commentBox = document.createElement("div");
        commentBox.style.cssText = "background: var(--accent-subtle); padding: 0.75rem; border-radius: var(--radius-sm); font-size: 0.85rem; margin-top: 0.75rem; border-left: 3px solid var(--accent-primary);";
        commentBox.innerHTML = `<strong><i class="fa-solid fa-comment-dots"></i> Faculty Comment:</strong> <span style="color: var(--text-secondary);">${escapeHtml(p.faculty_comment)}</span>`;
        topSection.appendChild(commentBox);
      }

      card.appendChild(topSection);

      const actions = document.createElement("div");
      actions.className = "rp-paper-actions";

      if (p.pdf_url) {
        const linkPdf = document.createElement("a");
        linkPdf.href = p.pdf_url;
        linkPdf.target = "_blank";
        linkPdf.rel = "noopener noreferrer";
        linkPdf.className = "rp-btn-sm rp-btn-outline";
        linkPdf.innerHTML = `<i class="fa-solid fa-file-pdf"></i> View PDF`;
        actions.appendChild(linkPdf);
      }

      if (currentUserRole !== "team") {
        const btnReview = document.createElement("button");
        btnReview.type = "button";
        btnReview.className = "rp-btn-sm rp-btn-action";
        btnReview.innerHTML = `<i class="fa-solid fa-clipboard-check"></i> Review Paper`;
        btnReview.onclick = () => openFacultyModal(p);
        actions.appendChild(btnReview);
      } else {
        const btnRemove = document.createElement("button");
        btnRemove.type = "button";
        btnRemove.className = "rp-btn-sm rp-btn-danger-outline";
        btnRemove.innerHTML = `<i class="fa-solid fa-trash"></i> Remove`;
        btnRemove.onclick = () => removeSavedPaper(p.paper_id);
        actions.appendChild(btnRemove);
      }

      card.appendChild(actions);
      container.appendChild(card);
    });
  }

  async function removeSavedPaper(paperId) {
    if (!confirm("Are you sure you want to remove this paper from your saved list?")) return;
    const token = getToken();
    try {
      const res = await fetch(`/api/research/saved-paper/${paperId}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        loadSavedPapers();
      } else {
        alert("Failed to remove paper.");
      }
    } catch (e) {
      alert("Failed to remove paper: " + e.message);
    }
  }

  function openFacultyModal(paper) {
    selectedPaperForReview = paper;
    const titleEl = document.getElementById("reviewPaperTitle");
    if (titleEl) titleEl.textContent = paper.title || "";
    const modal = document.getElementById("facultyReviewModal");
    if (modal) modal.style.display = "flex";
  }

  function closeFacultyModal() {
    const modal = document.getElementById("facultyReviewModal");
    if (modal) modal.style.display = "none";
  }

  async function submitFacultyReview() {
    if (!selectedPaperForReview) return;
    const status = document.getElementById("facultyStatusSelect").value;
    const comment = document.getElementById("facultyCommentText").value;
    const token = getToken();

    try {
      const res = await fetch("/api/research/faculty-review", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          paper_id: selectedPaperForReview.paper_id,
          team_name: selectedPaperForReview.team_name,
          status: status,
          comment: comment
        })
      });

      if (res.ok) {
        closeFacultyModal();
        alert("Review submitted successfully!");
        loadSavedPapers();
      } else {
        const err = await res.json().catch(() => ({}));
        alert("Error: " + (err.error || "Failed to submit review"));
      }
    } catch (e) {
      alert("Error submitting review: " + e.message);
    }
  }

  function setupDragAndDrop() {
    const dropZone = document.getElementById("dropZone");
    if (!dropZone || dropZone._bound) return;
    dropZone._bound = true;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, e => {
        e.preventDefault();
        e.stopPropagation();
      }, false);
    });

    ['dragenter', 'dragover'].forEach(name => {
      dropZone.addEventListener(name, () => dropZone.classList.add('dragover'));
    });

    ['dragleave', 'drop'].forEach(name => {
      dropZone.addEventListener(name, () => dropZone.classList.remove('dragover'));
    });

    dropZone.addEventListener('drop', e => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files[0]) {
        handleFileSelected(dt.files[0]);
      }
    });
  }

  async function handleFileSelected(file) {
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
      alert("Please select a valid PDF file.");
      return;
    }

    const box = document.getElementById("uploadStatusBox");
    const titleEl = document.getElementById("uploadPaperTitle");
    const reasonEl = document.getElementById("uploadReasonText");
    const confEl = document.getElementById("uploadConfidence");
    const badgeEl = document.getElementById("uploadClassBadge");
    const suggPanel = document.getElementById("aiSuggestionsPanel");

    if (box) box.classList.remove("rp-hidden");
    if (titleEl) titleEl.textContent = `Uploading & Analyzing: ${file.name}...`;
    if (reasonEl) reasonEl.textContent = "Extracting text content and requesting Gemini AI validation...";
    if (confEl) confEl.textContent = "--%";
    if (badgeEl) {
      badgeEl.textContent = "Checking...";
      badgeEl.className = "rp-relevance-badge rp-relevance-medium";
    }
    if (suggPanel) suggPanel.classList.add("rp-hidden");

    const formData = new FormData();
    formData.append("file", file);

    const token = getToken();
    try {
      const res = await fetch("/api/research/upload-paper", {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` },
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        if (titleEl) titleEl.textContent = data.title || file.name;
        if (confEl) confEl.textContent = `${data.confidence_score || 85}%`;

        if (badgeEl) {
          badgeEl.textContent = data.classification;
          if (data.classification === "Related") badgeEl.className = "rp-relevance-badge rp-relevance-high";
          else if (data.classification === "Partially Related") badgeEl.className = "rp-relevance-badge rp-relevance-medium";
          else badgeEl.className = "rp-relevance-badge rp-relevance-low";
        }

        const explanation = (data.ai_analysis && data.ai_analysis.explanation) || "Paper processing completed.";
        if (reasonEl) reasonEl.textContent = explanation;

        if (data.classification !== "Related" && data.ai_suggestions && suggPanel) {
          suggPanel.classList.remove("rp-hidden");
          const sug = data.ai_suggestions;

          const whyNot = document.getElementById("whyNotRelated");
          if (whyNot) whyNot.textContent = sug.why_not_related || "The paper has partial domain misalignment.";

          const suggDir = document.getElementById("suggDirectionText");
          if (suggDir) suggDir.textContent = sug.research_direction || "Refine search keywords to target specific project algorithms.";

          const kwList = document.getElementById("suggKeywordsList");
          if (kwList) {
            kwList.replaceChildren();
            (sug.suggested_keywords || []).forEach(k => {
              const span = document.createElement("span");
              span.className = "rp-match-tag";
              span.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i> ${escapeHtml(k)}`;
              kwList.appendChild(span);
            });
          }

          const suggGrid = document.getElementById("suggRecPapersGrid");
          if (suggGrid) {
            renderPaperCards(sug.recommended_papers || [], suggGrid);
          }
        }
      } else {
        const err = await res.json().catch(() => ({}));
        if (reasonEl) reasonEl.textContent = "Error: " + (err.error || "Upload failed");
      }
    } catch (e) {
      if (reasonEl) reasonEl.textContent = "Error: " + e.message;
    }
  }

  // Expose methods globally for dashboard integration
  window.initResearchPaperSection = initResearchPaperSection;
  window.returnFromResearchPapers = returnFromResearchPapers;
  window.switchResearchTab = switchResearchTab;
  window.autoFetchPapers = autoFetchPapers;
  window.showAlignmentModal = showAlignmentModal;
  window.closeAlignmentModal = closeAlignmentModal;
  window.closeFacultyModal = closeFacultyModal;
  window.submitFacultyReview = submitFacultyReview;
  window.handleFileSelected = handleFileSelected;

})(window);
