/**
 * ==========================================================================
 * PROFESSIONAL FLOWCHART DESIGNER - CORE APPLICATION ENGINE
 * High-performance vector diagramming, port-to-port connections,
 * automatic layout, code-to-flowchart, AI generation, and report exports.
 * ==========================================================================
 */

(function () {
  'use strict';

  // --- AUTHENTICATION & ACCESS CONTROL ---
  const token = localStorage.getItem('token');
  if (!token) {
    window.location.replace('login.html');
    return;
  }

  let currentUser = { name: 'Student', email: '', usn: '', team_name: '' };
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    const payload = JSON.parse(jsonPayload);
    const role = (payload.role || '').toLowerCase();
    if (role === 'faculty' || role === 'guide') {
      window.location.replace('faculty-dashboard.html');
      return;
    } else if (role === 'coordinator' || role === 'project_coordinator') {
      window.location.replace('project_coordinator-dashboard.html');
      return;
    }
    currentUser = {
      name: payload.name || 'Student',
      email: payload.email || '',
      usn: payload.usn || '',
      team_name: payload.team_name || ''
    };
  } catch (e) {
    console.warn('Token parse error:', e);
  }

  // --- CONSTANTS ---
  const DEFAULT_NODE_WIDTH = 160;
  const DEFAULT_NODE_HEIGHT = 70;
  const GRID_SIZE = 20;

  // --- STATE ---
  const state = {
    diagramId: null,
    title: 'My Project Flowchart',
    description: '',
    nodes: [],
    edges: [],
    viewport: { x: 80, y: 80, zoom: 1.0 },
    layout: { direction: 'TB', grid: 'dots', gridSize: GRID_SIZE },
    isDirty: false,

    // Selections
    selectedNodeIds: new Set(),
    selectedEdgeId: null,

    // Interaction Modes
    mode: 'select', // 'select', 'panning', 'connecting', 'resizing', 'marquee', 'dragging-nodes', 'dragging-bend'
    panStart: { x: 0, y: 0, vpX: 0, vpY: 0 },
    spacePressed: false,

    // Connecting
    connectingSourceNodeId: null,
    connectingSourcePort: null,
    connectingCurrentPoint: { x: 0, y: 0 },
    snappedTargetNodeId: null,
    snappedTargetPortId: null,

    // Dragging Bend Point
    dragBend: {
      edgeId: null,
      pointIndex: -1,
      startX: 0,
      startY: 0,
      initialPoint: { x: 0, y: 0 }
    },

    // Dragging Nodes
    dragNodesStart: new Map(), // id -> { x, y }
    dragPointerStart: { x: 0, y: 0 },
    isDraggingNodes: false,

    // Resizing Node
    resizeNodeId: null,
    resizeHandle: null,
    resizeInitialRect: { x: 0, y: 0, width: 0, height: 0 },
    resizePointerStart: { x: 0, y: 0 },

    // Marquee Box
    marqueeStart: { x: 0, y: 0 },
    marqueeCurrent: { x: 0, y: 0 },

    // History (Undo / Redo)
    history: [],
    historyIndex: -1,
    maxHistory: 50,

    // Clipboard
    clipboard: null
  };

  // --- DOM ELEMENT REFERENCES ---
  const dom = {
    canvasContainer: document.getElementById('fcCanvasContainer'),
    svg: document.getElementById('fcDiagramSvg'),
    viewportGroup: document.getElementById('fcViewportGroup'),
    gridPattern: document.getElementById('fcGridPattern'),
    edgesLayer: document.getElementById('fcEdgesLayer'),
    nodesLayer: document.getElementById('fcNodesLayer'),
    guidesLayer: document.getElementById('fcGuidesLayer'),
    tempLayer: document.getElementById('fcTempLayer'),

    // Topbar
    titleInput: document.getElementById('fcDiagramTitleInput'),
    statusBadge: document.getElementById('fcStatusBadge'),
    statusText: document.getElementById('fcStatusText'),
    btnSave: document.getElementById('fcBtnSave'),
    btnNew: document.getElementById('fcBtnNew'),
    btnUndo: document.getElementById('fcBtnUndo'),
    btnRedo: document.getElementById('fcBtnRedo'),
    btnAutoArrange: document.getElementById('fcBtnAutoArrange'),
    zoomText: document.getElementById('fcZoomText'),

    // Properties Panel
    rightPanel: document.getElementById('fcRightPanel'),
    propHeaderTitle: document.getElementById('fcPropHeaderTitle'),
    propContentNode: document.getElementById('fcPropContentNode'),
    propContentEdge: document.getElementById('fcPropContentEdge'),
    propContentCanvas: document.getElementById('fcPropContentCanvas'),

    // Minimap
    minimap: document.getElementById('fcMinimap'),
    minimapSvg: document.getElementById('fcMinimapSvg'),
    minimapViewport: document.getElementById('fcMinimapViewport'),

    // Inline Editor
    inlineEditor: document.getElementById('fcInlineEditor'),

    // Modals
    codeModal: document.getElementById('fcCodeModal'),
    aiModal: document.getElementById('fcAiModal'),
    templateModal: document.getElementById('fcTemplateModal'),
    confirmModal: document.getElementById('fcConfirmModal'),
    toastContainer: document.getElementById('fcToastContainer')
  };

  // --- INITIALIZATION ---
  function init() {
    setupEventListeners();
    setupTemplates();
    setupSavedDiagramsList();
    loadInitialDiagram();
    renderMinimap();
    updateUIState();

    // Auto-save draft locally every 20 seconds
    setInterval(saveDraftLocally, 20000);
  }

  // --- TEMPLATES DEFINITION (8 Academic & Project Templates) ---
  const TEMPLATES = [
    {
      id: 'tmpl_login',
      title: 'Login & Authentication Flow',
      category: 'Authentication',
      desc: 'Standard credentials verification, password hashing check, role dispatch & session token grant.',
      nodes: [
        { id: 'n1', type: 'start', label: 'Start: User Login', x: 200, y: 50 },
        { id: 'n2', type: 'inputoutput', label: 'Input: Email & Password', x: 200, y: 150 },
        { id: 'n3', type: 'process', label: 'Query Database for User', x: 200, y: 250 },
        { id: 'n4', type: 'decision', label: 'User Found & Password Matches?', x: 200, y: 350 },
        { id: 'n5', type: 'process', label: 'Generate Signed JWT Token', x: 100, y: 470 },
        { id: 'n6', type: 'inputoutput', label: 'Display: Invalid Credentials Error', x: 340, y: 470 },
        { id: 'n7', type: 'process', label: 'Redirect to Role Dashboard', x: 100, y: 570 },
        { id: 'n8', type: 'end', label: 'End: Session Active', x: 200, y: 670 }
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n3' },
        { id: 'e3', source: 'n3', target: 'n4' },
        { id: 'e4', source: 'n4', target: 'n5', label: 'Yes' },
        { id: 'e5', source: 'n4', target: 'n6', label: 'No' },
        { id: 'e6', source: 'n5', target: 'n7' },
        { id: 'e7', source: 'n7', target: 'n8' },
        { id: 'e8', source: 'n6', target: 'n8' }
      ]
    },
    {
      id: 'tmpl_registration',
      title: 'Student Registration Flow',
      category: 'Onboarding',
      desc: 'Validates university USN, email uniqueness, hashes password & creates team profile.',
      nodes: [
        { id: 'n1', type: 'start', label: 'Start: Registration', x: 220, y: 50 },
        { id: 'n2', type: 'inputoutput', label: 'Input: Team Name, Leader USN, Email, Password', x: 220, y: 150 },
        { id: 'n3', type: 'decision', label: 'USN or Email Already Exists?', x: 220, y: 260 },
        { id: 'n4', type: 'inputoutput', label: 'Show "Already Registered" Error', x: 420, y: 370 },
        { id: 'n5', type: 'process', label: 'Hash Password (PBKDF2 / Bcrypt)', x: 120, y: 370 },
        { id: 'n6', type: 'database', label: 'Insert Team into DB', x: 120, y: 470 },
        { id: 'n7', type: 'inputoutput', label: 'Send Welcome Notification', x: 120, y: 570 },
        { id: 'n8', type: 'end', label: 'End: Account Ready', x: 220, y: 670 }
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n3' },
        { id: 'e3', source: 'n3', target: 'n4', label: 'Yes' },
        { id: 'e4', source: 'n3', target: 'n5', label: 'No' },
        { id: 'e5', source: 'n5', target: 'n6' },
        { id: 'e6', source: 'n6', target: 'n7' },
        { id: 'e7', source: 'n7', target: 'n8' },
        { id: 'e8', source: 'n4', target: 'n8' }
      ]
    },
    {
      id: 'tmpl_project_submission',
      title: 'Project Submission & Faculty Approval',
      category: 'Academic Workflow',
      desc: 'Project synopsis submission, coordinator guide allocation, faculty review & stage approvals.',
      nodes: [
        { id: 'n1', type: 'start', label: 'Start: Synopsis Submission', x: 240, y: 50 },
        { id: 'n2', type: 'document', label: 'Upload Project Synopsis & Objectives', x: 240, y: 150 },
        { id: 'n3', type: 'process', label: 'Coordinator Assigns Faculty Guide', x: 240, y: 250 },
        { id: 'n4', type: 'process', label: 'Faculty Guide Evaluates Proposal', x: 240, y: 350 },
        { id: 'n5', type: 'decision', label: 'Proposal Approved?', x: 240, y: 460 },
        { id: 'n6', type: 'process', label: 'Provide Constructive Feedback', x: 450, y: 560 },
        { id: 'n7', type: 'process', label: 'Approve Phase 1 & Unlock Task Board', x: 120, y: 560 },
        { id: 'n8', type: 'end', label: 'End: Development In Progress', x: 240, y: 670 }
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n3' },
        { id: 'e3', source: 'n3', target: 'n4' },
        { id: 'e4', source: 'n4', target: 'n5' },
        { id: 'e5', source: 'n5', target: 'n6', label: 'No (Revisions Required)' },
        { id: 'e6', source: 'n5', target: 'n7', label: 'Yes (Accepted)' },
        { id: 'e7', source: 'n6', target: 'n2', label: 'Resubmit' },
        { id: 'e8', source: 'n7', target: 'n8' }
      ]
    },
    {
      id: 'tmpl_originality',
      title: 'AI Originality-Checking Workflow',
      category: 'AI System',
      desc: 'Extracts report text, embeds with SentenceTransformer, computes cosine similarity against repository.',
      nodes: [
        { id: 'n1', type: 'start', label: 'Start: Originality Check', x: 230, y: 50 },
        { id: 'n2', type: 'document', label: 'Extract Text from Submitted PDF', x: 230, y: 150 },
        { id: 'n3', type: 'process', label: 'Generate MiniLM Sentence Embeddings', x: 230, y: 250 },
        { id: 'n4', type: 'database', label: 'Query Past Projects Vector Corpus', x: 230, y: 350 },
        { id: 'n5', type: 'process', label: 'Compute Cosine Similarity Score', x: 230, y: 450 },
        { id: 'n6', type: 'decision', label: 'Similarity Score > 30% Threshold?', x: 230, y: 560 },
        { id: 'n7', type: 'process', label: 'Flag for Manual Plagiarism Review', x: 430, y: 670 },
        { id: 'n8', type: 'process', label: 'Certify Originality Clearance', x: 110, y: 670 },
        { id: 'n9', type: 'end', label: 'End: Report Evaluated', x: 230, y: 770 }
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n3' },
        { id: 'e3', source: 'n3', target: 'n4' },
        { id: 'e4', source: 'n4', target: 'n5' },
        { id: 'e5', source: 'n5', target: 'n6' },
        { id: 'e6', source: 'n6', target: 'n7', label: 'Yes (High Similarity)' },
        { id: 'e7', source: 'n6', target: 'n8', label: 'No (Original)' },
        { id: 'e8', source: 'n7', target: 'n9' },
        { id: 'e9', source: 'n8', target: 'n9' }
      ]
    },
    {
      id: 'tmpl_ifelse',
      title: 'If / Else Decision Algorithm',
      category: 'Algorithm',
      desc: 'Classic branching control structure demonstrating binary conditions and convergence.',
      nodes: [
        { id: 'n1', type: 'start', label: 'Start: Evaluate Number', x: 200, y: 50 },
        { id: 'n2', type: 'inputoutput', label: 'Read Integer N', x: 200, y: 150 },
        { id: 'n3', type: 'decision', label: 'Is N % 2 == 0 ?', x: 200, y: 260 },
        { id: 'n4', type: 'inputoutput', label: 'Print "Number is Even"', x: 90, y: 380 },
        { id: 'n5', type: 'inputoutput', label: 'Print "Number is Odd"', x: 310, y: 380 },
        { id: 'n6', type: 'end', label: 'End', x: 200, y: 490 }
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n3' },
        { id: 'e3', source: 'n3', target: 'n4', label: 'Yes' },
        { id: 'e4', source: 'n3', target: 'n5', label: 'No' },
        { id: 'e5', source: 'n4', target: 'n6' },
        { id: 'e6', source: 'n5', target: 'n6' }
      ]
    },
    {
      id: 'tmpl_loop',
      title: 'Loop & Iteration Algorithm',
      category: 'Algorithm',
      desc: 'Standard counter-controlled loop computing running summation with back-edge loop path.',
      nodes: [
        { id: 'n1', type: 'start', label: 'Start: Sum Array', x: 200, y: 50 },
        { id: 'n2', type: 'process', label: 'Initialize sum = 0, i = 0', x: 200, y: 150 },
        { id: 'n3', type: 'decision', label: 'Is i < Array.Length ?', x: 200, y: 260 },
        { id: 'n4', type: 'process', label: 'sum += Array[i]\ni++', x: 90, y: 380 },
        { id: 'n5', type: 'inputoutput', label: 'Print "Total: " + sum', x: 320, y: 380 },
        { id: 'n6', type: 'end', label: 'End', x: 200, y: 490 }
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n3' },
        { id: 'e3', source: 'n3', target: 'n4', label: 'True (Continue)' },
        { id: 'e4', source: 'n4', target: 'n3', label: 'Next Loop' },
        { id: 'e5', source: 'n3', target: 'n5', label: 'False (Done)' },
        { id: 'e6', source: 'n5', target: 'n6' }
      ]
    },
    {
      id: 'tmpl_bubble_sort',
      title: 'Bubble Sort Algorithm',
      category: 'Sorting Algorithm',
      desc: 'Complete nested loop sorting algorithm with comparison, element swap & termination condition.',
      nodes: [
        { id: 'n1', type: 'start', label: 'Start: Bubble Sort', x: 240, y: 50 },
        { id: 'n2', type: 'process', label: 'Initialize n = arr.length, i = 0', x: 240, y: 150 },
        { id: 'n3', type: 'decision', label: 'Is i < n - 1 ?', x: 240, y: 250 },
        { id: 'n4', type: 'process', label: 'Initialize j = 0', x: 120, y: 360 },
        { id: 'n5', type: 'decision', label: 'Is j < n - i - 1 ?', x: 120, y: 460 },
        { id: 'n6', type: 'decision', label: 'arr[j] > arr[j+1] ?', x: 120, y: 570 },
        { id: 'n7', type: 'process', label: 'Swap arr[j] and arr[j+1]', x: 20, y: 680 },
        { id: 'n8', type: 'process', label: 'j++', x: 120, y: 790 },
        { id: 'n9', type: 'process', label: 'i++', x: 340, y: 460 },
        { id: 'n10', type: 'inputoutput', label: 'Return Sorted Array', x: 440, y: 360 },
        { id: 'n11', type: 'end', label: 'End', x: 440, y: 470 }
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n3' },
        { id: 'e3', source: 'n3', target: 'n4', label: 'Yes' },
        { id: 'e4', source: 'n3', target: 'n10', label: 'No' },
        { id: 'e5', source: 'n4', target: 'n5' },
        { id: 'e6', source: 'n5', target: 'n6', label: 'Yes' },
        { id: 'e7', source: 'n5', target: 'n9', label: 'No' },
        { id: 'e8', source: 'n6', target: 'n7', label: 'Yes' },
        { id: 'e9', source: 'n6', target: 'n8', label: 'No' },
        { id: 'e10', source: 'n7', target: 'n8' },
        { id: 'e11', source: 'n8', target: 'n5', label: 'Next j' },
        { id: 'e12', source: 'n9', target: 'n3', label: 'Next i' },
        { id: 'e13', source: 'n10', target: 'n11' }
      ]
    },
    {
      id: 'tmpl_lifecycle',
      title: 'Project Lifecycle & Evaluation',
      category: 'Academic Workflow',
      desc: 'End-to-end semester engineering project cycle from synopsis to final marks publication.',
      nodes: [
        { id: 'n1', type: 'start', label: 'Project Inception & Team Formation', x: 200, y: 50 },
        { id: 'n2', type: 'process', label: 'Phase 1: Synopsis & Objective Definition', x: 200, y: 150 },
        { id: 'n3', type: 'process', label: 'Phase 2: Architectural & Database Design', x: 200, y: 250 },
        { id: 'n4', type: 'process', label: 'Review 1: Preliminary Presentation', x: 200, y: 350 },
        { id: 'n5', type: 'process', label: 'Phase 3: Implementation & Module Coding', x: 200, y: 450 },
        { id: 'n6', type: 'process', label: 'Review 2: Progress & Working Demo', x: 200, y: 550 },
        { id: 'n7', type: 'document', label: 'Plagiarism & Originality Verification', x: 200, y: 650 },
        { id: 'n8', type: 'subroutine', label: 'Final External Viva & Defense', x: 200, y: 750 },
        { id: 'n9', type: 'inputoutput', label: 'Final Marks Published to Portal', x: 200, y: 850 },
        { id: 'n10', type: 'end', label: 'End: Project Completed', x: 200, y: 950 }
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n3' },
        { id: 'e3', source: 'n3', target: 'n4' },
        { id: 'e4', source: 'n4', target: 'n5' },
        { id: 'e5', source: 'n5', target: 'n6' },
        { id: 'e6', source: 'n6', target: 'n7' },
        { id: 'e7', source: 'n7', target: 'n8' },
        { id: 'e8', source: 'n8', target: 'n9' },
        { id: 'e9', source: 'n9', target: 'n10' }
      ]
    }
  ];

  // --- LOCAL DRAFT PERSISTENCE ---
  function saveDraftLocally() {
    try {
      const draft = {
        title: state.title,
        nodes: state.nodes,
        edges: state.edges,
        viewport: state.viewport,
        layout: state.layout,
        timestamp: new Date().toISOString()
      };
      localStorage.setItem('fc_student_draft', JSON.stringify(draft));
    } catch (e) {
      console.warn('Draft save error:', e);
    }
  }

  function loadInitialDiagram() {
    // 1. Check if URL has ?id=<diagramId>
    const urlParams = new URLSearchParams(window.location.search);
    const diagramId = urlParams.get('id');

    if (diagramId) {
      loadDiagramFromBackend(diagramId);
      return;
    }

    // 2. Check local draft
    const savedDraft = localStorage.getItem('fc_student_draft');
    if (savedDraft) {
      try {
        const draft = JSON.parse(savedDraft);
        if (draft && draft.nodes && draft.nodes.length > 0) {
          state.title = draft.title || 'My Project Flowchart';
          state.nodes = draft.nodes;
          state.edges = draft.edges || [];
          if (draft.viewport) state.viewport = draft.viewport;
          if (draft.layout) state.layout = draft.layout;
          dom.titleInput.value = state.title;
          renderDiagram();
          fitToScreen();
          pushHistory();
          return;
        }
      } catch (e) {
        console.warn('Failed parsing local draft', e);
      }
    }

    // 3. Fallback: load Project Submission template as pleasant starter
    loadTemplate('tmpl_project_submission');
  }

  // --- GRAPH RENDERING ENGINE ---
  function renderDiagram() {
    renderGrid();
    renderEdges();
    renderNodes();
    updateViewportTransform();
    renderMinimap();
    updatePropertiesPanel();
  }

  function updateViewportTransform() {
    const { x, y, zoom } = state.viewport;
    dom.viewportGroup.setAttribute('transform', `translate(${x}, ${y}) scale(${zoom})`);
    dom.zoomText.textContent = `${Math.round(zoom * 100)}%`;
  }

  function renderGrid() {
    const size = state.layout.gridSize || GRID_SIZE;
    const gridType = state.layout.grid || 'dots';

    dom.gridPattern.setAttribute('width', size);
    dom.gridPattern.setAttribute('height', size);

    if (gridType === 'none') {
      dom.gridPattern.innerHTML = '';
    } else if (gridType === 'lines') {
      dom.gridPattern.innerHTML = `
        <path d="M ${size} 0 L 0 0 0 ${size}" fill="none" class="fc-grid-lines" />
      `;
    } else {
      // Default: dots
      dom.gridPattern.innerHTML = `
        <circle cx="${size / 2}" cy="${size / 2}" r="1.2" class="fc-grid-dots" />
      `;
    }
  }

  // --- SVG SHAPE GENERATOR ---
  function getNodeShapeSvg(node) {
    const w = node.width || DEFAULT_NODE_WIDTH;
    const h = node.height || DEFAULT_NODE_HEIGHT;
    const type = node.type || 'process';
    const style = node.style || {};
    const fill = style.fill || '#ffffff';
    const stroke = style.stroke || '#3b82f6';
    const strokeWidth = style.strokeWidth || 2;
    const strokeDash = style.borderStyle === 'dashed' ? '6,4' : (style.borderStyle === 'dotted' ? '2,3' : 'none');

    const commonAttr = `class="fc-node-shape" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-dasharray="${strokeDash}"`;

    switch (type) {
      case 'start':
      case 'end':
        // Rounded terminator pill
        const rx = Math.min(w, h) / 2;
        return `<rect x="0" y="0" width="${w}" height="${h}" rx="${rx}" ry="${rx}" ${commonAttr} />`;

      case 'decision':
        // Rhombus / Diamond
        const pts = `${w / 2},0 ${w},${h / 2} ${w / 2},${h} 0,${h / 2}`;
        return `<polygon points="${pts}" ${commonAttr} />`;

      case 'inputoutput':
        // Parallelogram (slanted 18px)
        const slant = Math.min(22, w * 0.15);
        const ioPts = `${slant},0 ${w},0 ${w - slant},${h} 0,${h}`;
        return `<polygon points="${ioPts}" ${commonAttr} />`;

      case 'document':
        // Curved bottom wave
        const waveH = 14;
        const dDoc = `M 0,0 L ${w},0 L ${w},${h - waveH} Q ${w * 0.75},${h} ${w * 0.5},${h - waveH * 0.7} Q ${w * 0.25},${h - waveH * 1.4} 0,${h - waveH * 0.7} Z`;
        return `<path d="${dDoc}" ${commonAttr} />`;

      case 'subroutine':
        // Rectangle with inner double vertical lines
        const pad = 16;
        return `
          <rect x="0" y="0" width="${w}" height="${h}" rx="4" ry="4" ${commonAttr} />
          <line x1="${pad}" y1="0" x2="${pad}" y2="${h}" stroke="${stroke}" stroke-width="${strokeWidth}" />
          <line x1="${w - pad}" y1="0" x2="${w - pad}" y2="${h}" stroke="${stroke}" stroke-width="${strokeWidth}" />
        `;

      case 'connector':
        // Circular on-page connector
        const r = Math.min(w, h) / 2;
        return `<circle cx="${w / 2}" cy="${h / 2}" r="${r}" ${commonAttr} />`;

      case 'database':
        // 3D Cylinder
        const topH = 12;
        const dCyl = `
          M 0,${topH} 
          L 0,${h - topH} 
          A ${w / 2},${topH} 0 0,0 ${w},${h - topH} 
          L ${w},${topH} 
          A ${w / 2},${topH} 0 0,0 0,${topH} 
          Z
        `;
        return `
          <path d="${dCyl}" ${commonAttr} />
          <ellipse cx="${w / 2}" cy="${topH}" rx="${w / 2}" ry="${topH}" ${commonAttr} />
        `;

      case 'note':
        // Folded corner sticky note
        const fold = 16;
        const dNote = `M 0,0 L ${w - fold},0 L ${w},${fold} L ${w},${h} L 0,${h} Z`;
        const dFold = `M ${w - fold},0 L ${w - fold},${fold} L ${w},${fold}`;
        return `
          <path d="${dNote}" ${commonAttr} />
          <path d="${dFold}" fill="none" stroke="${stroke}" stroke-width="${strokeWidth}" />
        `;

      case 'process':
      default:
        // Standard process rectangle
        return `<rect x="0" y="0" width="${w}" height="${h}" rx="6" ry="6" ${commonAttr} />`;
    }
  }

  // --- CONNECTION PORTS ---
  function getNodePorts(node) {
    const w = node.width || DEFAULT_NODE_WIDTH;
    const h = node.height || DEFAULT_NODE_HEIGHT;
    return [
      { id: 'top', x: w / 2, y: 0 },
      { id: 'right', x: w, y: h / 2 },
      { id: 'bottom', x: w / 2, y: h },
      { id: 'left', x: 0, y: h / 2 }
    ];
  }

  function getPortAbsoluteCoordinate(nodeId, portId) {
    const node = state.nodes.find(n => n.id === nodeId);
    if (!node) return { x: 0, y: 0 };
    const ports = getNodePorts(node);
    const port = ports.find(p => p.id === portId) || ports[2]; // default bottom
    return {
      x: node.x + port.x,
      y: node.y + port.y
    };
  }

  // --- NODES RENDERING ---
  function renderNodes() {
    dom.nodesLayer.innerHTML = '';

    state.nodes.forEach(node => {
      const isSelected = state.selectedNodeIds.has(node.id);
      const w = node.width || DEFAULT_NODE_WIDTH;
      const h = node.height || DEFAULT_NODE_HEIGHT;
      const style = node.style || {};
      const fontSize = style.fontSize || 13;
      const textColor = style.textColor || '#1e293b';
      const textAlign = style.textAlign || 'center';

      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('class', `fc-node ${isSelected ? 'selected' : ''}`);
      g.setAttribute('id', `fc_node_${node.id}`);
      g.setAttribute('transform', `translate(${node.x}, ${node.y})`);
      g.dataset.nodeId = node.id;

      // Shape geometry
      let innerHtml = getNodeShapeSvg(node);

      // Multiline text wrapping
      const lines = wrapTextLines(node.label || '', w - 24, fontSize);
      const lineHeight = fontSize * 1.25;
      const totalTextH = lines.length * lineHeight;
      const startY = (h - totalTextH) / 2 + lineHeight / 2;

      let textAnchor = 'middle';
      let textX = w / 2;
      if (textAlign === 'left') {
        textAnchor = 'start';
        textX = 14;
      } else if (textAlign === 'right') {
        textAnchor = 'end';
        textX = w - 14;
      }

      let textTspans = lines
        .map((line, idx) => `<tspan x="${textX}" y="${startY + idx * lineHeight}">${escapeXml(line)}</tspan>`)
        .join('');

      innerHtml += `
        <text class="fc-node-text" fill="${textColor}" font-size="${fontSize}" font-weight="500" text-anchor="${textAnchor}">
          ${textTspans}
        </text>
      `;

      // 4 Connection Ports (Two-tier: stable outer hit target + inner visual indicator)
      const ports = getNodePorts(node);
      ports.forEach(p => {
        innerHtml += `
          <g class="fc-port-group" data-port="${p.id}" data-node-id="${node.id}">
            <circle 
              class="fc-port-hit" 
              cx="${p.x}" 
              cy="${p.y}" 
              r="12" 
              data-port="${p.id}" 
              data-node-id="${node.id}"
            />
            <circle 
              class="fc-port-visible" 
              cx="${p.x}" 
              cy="${p.y}" 
              r="5" 
              data-port="${p.id}" 
              data-node-id="${node.id}"
            />
          </g>
        `;
      });

      // Resize handles if single selection
      if (isSelected && state.selectedNodeIds.size === 1) {
        innerHtml += getResizeHandlesSvg(w, h);
      }

      g.innerHTML = innerHtml;
      dom.nodesLayer.appendChild(g);
    });
  }

  function getResizeHandlesSvg(w, h) {
    const s = 7;
    return `
      <rect class="fc-resize-handle nw" x="${-s/2}" y="${-s/2}" width="${s}" height="${s}" data-handle="nw" />
      <rect class="fc-resize-handle n"  x="${w/2 - s/2}" y="${-s/2}" width="${s}" height="${s}" data-handle="n" />
      <rect class="fc-resize-handle ne" x="${w - s/2}" y="${-s/2}" width="${s}" height="${s}" data-handle="ne" />
      <rect class="fc-resize-handle e"  x="${w - s/2}" y="${h/2 - s/2}" width="${s}" height="${s}" data-handle="e" />
      <rect class="fc-resize-handle se" x="${w - s/2}" y="${h - s/2}" width="${s}" height="${s}" data-handle="se" />
      <rect class="fc-resize-handle s"  x="${w/2 - s/2}" y="${h - s/2}" width="${s}" height="${s}" data-handle="s" />
      <rect class="fc-resize-handle sw" x="${-s/2}" y="${h - s/2}" width="${s}" height="${s}" data-handle="sw" />
      <rect class="fc-resize-handle w"  x="${-s/2}" y="${h/2 - s/2}" width="${s}" height="${s}" data-handle="w" />
    `;
  }

  // --- TEXT WRAPPING HELPER ---
  function wrapTextLines(text, maxWidth, fontSize) {
    if (!text) return [''];
    const words = text.split(/\s+/);
    const approxCharWidth = fontSize * 0.58;
    const maxCharsPerLine = Math.max(6, Math.floor(maxWidth / approxCharWidth));

    const lines = [];
    let currentLine = '';

    words.forEach(word => {
      if ((currentLine + ' ' + word).trim().length <= maxCharsPerLine) {
        currentLine = (currentLine + ' ' + word).trim();
      } else {
        if (currentLine) lines.push(currentLine);
        // Break long words if necessary
        while (word.length > maxCharsPerLine) {
          lines.push(word.slice(0, maxCharsPerLine));
          word = word.slice(maxCharsPerLine);
        }
        currentLine = word;
      }
    });
    if (currentLine) lines.push(currentLine);
    return lines.length > 0 ? lines : [text];
  }

  function escapeXml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // --- CONNECTOR ROUTING ALGORITHMS ---
  function getBestPorts(srcNode, tgtNode) {
    if (!srcNode || !tgtNode) return { srcPort: 'bottom', tgtPort: 'top' };
    const dx = (tgtNode.x + (tgtNode.width || DEFAULT_NODE_WIDTH) / 2) - (srcNode.x + (srcNode.width || DEFAULT_NODE_WIDTH) / 2);
    const dy = (tgtNode.y + (tgtNode.height || DEFAULT_NODE_HEIGHT) / 2) - (srcNode.y + (srcNode.height || DEFAULT_NODE_HEIGHT) / 2);

    if (Math.abs(dy) > Math.abs(dx)) {
      if (dy > 0) return { srcPort: 'bottom', tgtPort: 'top' };
      else return { srcPort: 'top', tgtPort: 'bottom' };
    } else {
      if (dx > 0) return { srcPort: 'right', tgtPort: 'left' };
      else return { srcPort: 'left', tgtPort: 'right' };
    }
  }

  function simplifyOrthogonalVertices(vertices) {
    if (vertices.length <= 2) return vertices;
    const result = [vertices[0]];

    for (let i = 1; i < vertices.length - 1; i++) {
      const prev = result[result.length - 1];
      const curr = vertices[i];
      const next = vertices[i + 1];

      // If duplicate to prev, skip
      if (Math.abs(curr.x - prev.x) < 0.5 && Math.abs(curr.y - prev.y) < 0.5) continue;

      // Collinear checks
      const isHorizontalCollinear = Math.abs(prev.y - curr.y) < 0.5 && Math.abs(curr.y - next.y) < 0.5;
      const isVerticalCollinear = Math.abs(prev.x - curr.x) < 0.5 && Math.abs(curr.x - next.x) < 0.5;

      if (!isHorizontalCollinear && !isVerticalCollinear) {
        result.push(curr);
      }
    }

    const last = vertices[vertices.length - 1];
    const prev = result[result.length - 1];
    if (Math.abs(last.x - prev.x) >= 0.5 || Math.abs(last.y - prev.y) >= 0.5) {
      result.push(last);
    }
    return result;
  }

  function getOrthogonalVertices(srcPt, tgtPt, points = [], sPort = 'bottom', tPort = 'top') {
    const pts = points && Array.isArray(points) ? points : [];

    // 1. When custom bend points exist: route through each point orthogonally
    if (pts.length > 0) {
      const waypoints = [srcPt, ...pts, tgtPt];
      const vertices = [srcPt];

      for (let i = 0; i < waypoints.length - 1; i++) {
        const A = vertices[vertices.length - 1];
        const B = waypoints[i + 1];

        // If A and B already align horizontally or vertically, connect directly
        if (Math.abs(A.x - B.x) < 0.5 || Math.abs(A.y - B.y) < 0.5) {
          vertices.push(B);
          continue;
        }

        // Determine departure orientation from A
        let departVertical = true;
        if (i === 0) {
          departVertical = (sPort === 'top' || sPort === 'bottom');
        } else if (i === waypoints.length - 2) {
          // Arriving into tgtPt: arrive in direction of tPort
          departVertical = (tPort !== 'top' && tPort !== 'bottom');
        } else {
          // Intermediate point: alternate from preceding segment direction
          const prev = vertices[vertices.length - 2] || srcPt;
          const prevWasVertical = Math.abs(prev.x - A.x) < 0.5;
          departVertical = !prevWasVertical;
        }

        if (departVertical) {
          vertices.push({ x: A.x, y: B.y });
          vertices.push(B);
        } else {
          vertices.push({ x: B.x, y: A.y });
          vertices.push(B);
        }
      }

      return simplifyOrthogonalVertices(vertices);
    }

    // 2. Default: Clean automatic orthogonal routing with port clearances
    const vertices = [srcPt];
    const isExitVertical = (sPort === 'top' || sPort === 'bottom');
    const isEnterVertical = (tPort === 'top' || tPort === 'bottom');

    if (isExitVertical && isEnterVertical) {
      if ((sPort === 'bottom' && tPort === 'top' && tgtPt.y >= srcPt.y + 16) ||
          (sPort === 'top' && tPort === 'bottom' && srcPt.y >= tgtPt.y + 16)) {
        const midY = (srcPt.y + tgtPt.y) / 2;
        vertices.push({ x: srcPt.x, y: midY });
        vertices.push({ x: tgtPt.x, y: midY });
      } else if (sPort === 'bottom' && tPort === 'bottom') {
        const detourY = Math.max(srcPt.y, tgtPt.y) + 30;
        vertices.push({ x: srcPt.x, y: detourY });
        vertices.push({ x: tgtPt.x, y: detourY });
      } else if (sPort === 'top' && tPort === 'top') {
        const detourY = Math.min(srcPt.y, tgtPt.y) - 30;
        vertices.push({ x: srcPt.x, y: detourY });
        vertices.push({ x: tgtPt.x, y: detourY });
      } else {
        const dy1 = sPort === 'bottom' ? srcPt.y + 24 : srcPt.y - 24;
        const dy2 = tPort === 'top' ? tgtPt.y - 24 : tgtPt.y + 24;
        const detourX = (tgtPt.x >= srcPt.x) ? Math.max(srcPt.x, tgtPt.x) + 60 : Math.min(srcPt.x, tgtPt.x) - 60;
        vertices.push({ x: srcPt.x, y: dy1 });
        vertices.push({ x: detourX, y: dy1 });
        vertices.push({ x: detourX, y: dy2 });
        vertices.push({ x: tgtPt.x, y: dy2 });
      }
    } else if (!isExitVertical && !isEnterVertical) {
      if ((sPort === 'right' && tPort === 'left' && tgtPt.x >= srcPt.x + 16) ||
          (sPort === 'left' && tPort === 'right' && srcPt.x >= tgtPt.x + 16)) {
        const midX = (srcPt.x + tgtPt.x) / 2;
        vertices.push({ x: midX, y: srcPt.y });
        vertices.push({ x: midX, y: tgtPt.y });
      } else if (sPort === 'right' && tPort === 'right') {
        const detourX = Math.max(srcPt.x, tgtPt.x) + 30;
        vertices.push({ x: detourX, y: srcPt.y });
        vertices.push({ x: detourX, y: tgtPt.y });
      } else if (sPort === 'left' && tPort === 'left') {
        const detourX = Math.min(srcPt.x, tgtPt.x) - 30;
        vertices.push({ x: detourX, y: srcPt.y });
        vertices.push({ x: detourX, y: tgtPt.y });
      } else {
        const dx1 = sPort === 'right' ? srcPt.x + 24 : srcPt.x - 24;
        const dx2 = tPort === 'left' ? tgtPt.x - 24 : tgtPt.x + 24;
        const detourY = (tgtPt.y >= srcPt.y) ? Math.max(srcPt.y, tgtPt.y) + 50 : Math.min(srcPt.y, tgtPt.y) - 50;
        vertices.push({ x: dx1, y: srcPt.y });
        vertices.push({ x: dx1, y: detourY });
        vertices.push({ x: dx2, y: detourY });
        vertices.push({ x: dx2, y: tgtPt.y });
      }
    } else if (isExitVertical && !isEnterVertical) {
      vertices.push({ x: srcPt.x, y: tgtPt.y });
    } else {
      vertices.push({ x: tgtPt.x, y: srcPt.y });
    }

    vertices.push(tgtPt);
    return simplifyOrthogonalVertices(vertices);
  }

  function polylineToPath(vertices) {
    if (!vertices || vertices.length === 0) return '';
    return 'M ' + vertices.map(v => `${v.x},${v.y}`).join(' L ');
  }

  function calculateCurvedPath(srcPt, tgtPt, points = []) {
    if (points && points.length > 0) {
      let d = `M ${srcPt.x},${srcPt.y}`;
      const allPts = [srcPt, ...points, tgtPt];
      for (let i = 0; i < allPts.length - 1; i++) {
        const p1 = allPts[i];
        const p2 = allPts[i + 1];
        const cx = (p1.x + p2.x) / 2;
        d += ` Q ${p1.x},${p1.y} ${cx},${(p1.y + p2.y) / 2}`;
      }
      d += ` L ${tgtPt.x},${tgtPt.y}`;
      return d;
    }
    const dx = tgtPt.x - srcPt.x;
    const cx1 = srcPt.x + dx * 0.5;
    const cy1 = srcPt.y;
    const cx2 = srcPt.x + dx * 0.5;
    const cy2 = tgtPt.y;
    return `M ${srcPt.x},${srcPt.y} C ${cx1},${cy1} ${cx2},${cy2} ${tgtPt.x},${tgtPt.y}`;
  }

  function calculateEdgePath(srcPt, tgtPt, routeType = 'orthogonal', points = [], sPort = 'bottom', tPort = 'top') {
    if (routeType === 'straight') {
      const pts = points && Array.isArray(points) ? points : [];
      let d = `M ${srcPt.x},${srcPt.y}`;
      pts.forEach(p => { d += ` L ${p.x},${p.y}`; });
      d += ` L ${tgtPt.x},${tgtPt.y}`;
      return d;
    }

    if (routeType === 'curved') {
      return calculateCurvedPath(srcPt, tgtPt, points);
    }

    // Default: Orthogonal with bend points
    const vertices = getOrthogonalVertices(srcPt, tgtPt, points, sPort, tPort);
    return polylineToPath(vertices);
  }

  function getEdgeMidpoint(srcPt, tgtPt, routeType = 'orthogonal', points = [], sPort = 'bottom', tPort = 'top') {
    if (routeType === 'straight') {
      const pts = points && Array.isArray(points) ? points : [];
      if (pts.length > 0) {
        const midIdx = Math.floor(pts.length / 2);
        return { x: pts[midIdx].x, y: pts[midIdx].y };
      }
      return { x: (srcPt.x + tgtPt.x) / 2, y: (srcPt.y + tgtPt.y) / 2 };
    }

    const vertices = getOrthogonalVertices(srcPt, tgtPt, points, sPort, tPort);
    if (vertices.length < 2) {
      return { x: (srcPt.x + tgtPt.x) / 2, y: (srcPt.y + tgtPt.y) / 2 };
    }

    // Place label along the longest segment of the route
    let longestLen = -1;
    let bestMid = { x: (srcPt.x + tgtPt.x) / 2, y: (srcPt.y + tgtPt.y) / 2 };

    for (let i = 0; i < vertices.length - 1; i++) {
      const v1 = vertices[i];
      const v2 = vertices[i + 1];
      const len = Math.hypot(v2.x - v1.x, v2.y - v1.y);
      if (len > longestLen) {
        longestLen = len;
        bestMid = { x: (v1.x + v2.x) / 2, y: (v1.y + v2.y) / 2 };
      }
    }

    return bestMid;
  }

  function distanceToSegment(px, py, x1, y1, x2, y2) {
    const l2 = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1);
    if (l2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
  }

  function findBestPointInsertIndex(edge, x, y) {
    const pts = edge.points || [];
    if (pts.length === 0) return 0;

    const srcNode = state.nodes.find(n => n.id === edge.source);
    const tgtNode = state.nodes.find(n => n.id === edge.target);
    const ports = getBestPorts(srcNode, tgtNode);
    const sPort = edge.sourcePort || ports.srcPort;
    const tPort = edge.targetPort || ports.tgtPort;
    const srcPt = getPortAbsoluteCoordinate(edge.source, sPort);
    const tgtPt = getPortAbsoluteCoordinate(edge.target, tPort);

    const waypoints = [srcPt, ...pts, tgtPt];
    let bestDist = Infinity;
    let bestIdx = pts.length;

    for (let i = 0; i < waypoints.length - 1; i++) {
      const p1 = waypoints[i];
      const p2 = waypoints[i + 1];
      const dist = distanceToSegment(x, y, p1.x, p1.y, p2.x, p2.y);
      if (dist < bestDist) {
        bestDist = dist;
        bestIdx = i;
      }
    }
    return Math.max(0, Math.min(pts.length, bestIdx));
  }

  // --- FAST DOM EDGE UPDATERS (Flicker-Free Dragging) ---
  function updateSingleEdgeDOM(edge) {
    const edgeGroup = document.getElementById(`fc_edge_${edge.id}`);
    if (!edgeGroup) return;

    const srcNode = state.nodes.find(n => n.id === edge.source);
    const tgtNode = state.nodes.find(n => n.id === edge.target);
    if (!srcNode || !tgtNode) return;

    const ports = getBestPorts(srcNode, tgtNode);
    const sPort = edge.sourcePort || ports.srcPort;
    const tPort = edge.targetPort || ports.tgtPort;
    const srcPt = getPortAbsoluteCoordinate(edge.source, sPort);
    const tgtPt = getPortAbsoluteCoordinate(edge.target, tPort);

    const routeType = edge.type || 'orthogonal';
    const pathData = calculateEdgePath(srcPt, tgtPt, routeType, edge.points || [], sPort, tPort);

    const hitPath = edgeGroup.querySelector('.fc-edge-hit');
    if (hitPath) hitPath.setAttribute('d', pathData);

    const edgePath = edgeGroup.querySelector('.fc-edge');
    if (edgePath) edgePath.setAttribute('d', pathData);

    const labelGroup = edgeGroup.querySelector('.fc-edge-label-group');
    if (labelGroup) {
      const mid = getEdgeMidpoint(srcPt, tgtPt, routeType, edge.points || [], sPort, tPort);
      labelGroup.setAttribute('transform', `translate(${mid.x}, ${mid.y})`);
    }

    const pts = edge.points || [];
    pts.forEach((pt, pIdx) => {
      const handle = edgeGroup.querySelector(`.fc-bend-handle[data-point-index="${pIdx}"]`);
      if (handle) {
        handle.setAttribute('cx', pt.x);
        handle.setAttribute('cy', pt.y);
      }
    });
  }

  function updateAttachedEdges(nodeIds) {
    state.edges.forEach(edge => {
      if (nodeIds.has(edge.source) || nodeIds.has(edge.target)) {
        updateSingleEdgeDOM(edge);
      }
    });
  }

  // --- EDGES RENDERING ---
  function renderEdges() {
    dom.edgesLayer.innerHTML = '';

    state.edges.forEach(edge => {
      const srcNode = state.nodes.find(n => n.id === edge.source);
      const tgtNode = state.nodes.find(n => n.id === edge.target);
      if (!srcNode || !tgtNode) return;

      const isSelected = state.selectedEdgeId === edge.id;
      const routeType = edge.type || 'orthogonal';
      const style = edge.style || {};
      const stroke = isSelected ? '#3b82f6' : (style.stroke || '#64748b');
      const strokeWidth = isSelected ? 3 : (style.strokeWidth || 2);
      const isDashed = style.strokeDash === 'dashed';

      const ports = getBestPorts(srcNode, tgtNode);
      const sPort = edge.sourcePort || ports.srcPort;
      const tPort = edge.targetPort || ports.tgtPort;

      const srcPt = getPortAbsoluteCoordinate(edge.source, sPort);
      const tgtPt = getPortAbsoluteCoordinate(edge.target, tPort);

      const vertices = getOrthogonalVertices(srcPt, tgtPt, edge.points || [], sPort, tPort);
      const pathData = (routeType === 'straight')
        ? `M ${srcPt.x},${srcPt.y} ` + (edge.points || []).map(p => `L ${p.x},${p.y}`).join(' ') + ` L ${tgtPt.x},${tgtPt.y}`
        : (routeType === 'curved' && (!edge.points || edge.points.length === 0))
          ? calculateCurvedPath(srcPt, tgtPt)
          : polylineToPath(vertices);

      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('class', `fc-edge-group ${isSelected ? 'selected' : ''}`);
      g.setAttribute('id', `fc_edge_${edge.id}`);
      g.dataset.edgeId = edge.id;

      // Transparent thick hit-test path for easy clicking and stable cursor
      let edgeHtml = `
        <path 
          class="fc-edge-hit"
          d="${pathData}" 
          fill="none" 
          stroke="transparent" 
          stroke-width="14" 
        />
        <path 
          class="fc-edge ${isSelected ? 'selected' : ''}" 
          d="${pathData}" 
          stroke="${stroke}" 
          stroke-width="${strokeWidth}" 
          stroke-dasharray="${isDashed ? '5,5' : 'none'}" 
          marker-end="url(#marker-arrow)"
        />
      `;

      // Label badge
      if (edge.label && edge.label.trim()) {
        const mid = getEdgeMidpoint(srcPt, tgtPt, routeType, edge.points || [], sPort, tPort);
        const lbl = edge.label.trim();
        const badgeW = Math.max(34, lbl.length * 8 + 14);
        const badgeH = 20;

        edgeHtml += `
          <g class="fc-edge-label-group" transform="translate(${mid.x}, ${mid.y})">
            <rect 
              class="fc-edge-label-bg" 
              x="${-badgeW / 2}" 
              y="${-badgeH / 2}" 
              width="${badgeW}" 
              height="${badgeH}" 
            />
            <text class="fc-edge-label-text">${escapeXml(lbl)}</text>
          </g>
        `;
      }

      // If selected: render interactive bend handles and segment split handles
      if (isSelected) {
        // 1. Existing Bend Point Handles
        const pts = edge.points || [];
        pts.forEach((pt, pIdx) => {
          edgeHtml += `
            <circle
              class="fc-bend-handle"
              cx="${pt.x}"
              cy="${pt.y}"
              r="6"
              data-edge-id="${edge.id}"
              data-point-index="${pIdx}"
            />
          `;
        });

        // 2. Segment Midpoint '+' handles to add bends
        for (let j = 0; j < vertices.length - 1; j++) {
          const v1 = vertices[j];
          const v2 = vertices[j + 1];
          const segLen = Math.hypot(v2.x - v1.x, v2.y - v1.y);
          if (segLen >= 28) {
            const smX = Math.round((v1.x + v2.x) / 2);
            const smY = Math.round((v1.y + v2.y) / 2);
            edgeHtml += `
              <g class="fc-segment-handle" data-edge-id="${edge.id}" data-seg-x="${smX}" data-seg-y="${smY}">
                <circle cx="${smX}" cy="${smY}" r="7" class="fc-segment-handle-circle" />
                <line x1="${smX - 3.5}" y1="${smY}" x2="${smX + 3.5}" y2="${smY}" class="fc-segment-handle-plus" />
                <line x1="${smX}" y1="${smY - 3.5}" x2="${smX}" y2="${smY + 3.5}" class="fc-segment-handle-plus" />
              </g>
            `;
          }
        }
      }

      g.innerHTML = edgeHtml;
      dom.edgesLayer.appendChild(g);
    });
  }

  // --- MINIMAP RENDERING ---
  function renderMinimap() {
    if (!dom.minimapSvg) return;

    if (state.nodes.length === 0) {
      dom.minimapSvg.innerHTML = '';
      return;
    }

    // Compute diagram bounding box
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    state.nodes.forEach(n => {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + (n.width || DEFAULT_NODE_WIDTH));
      maxY = Math.max(maxY, n.y + (n.height || DEFAULT_NODE_HEIGHT));
    });

    const pad = 120;
    minX -= pad; minY -= pad;
    maxX += pad; maxY += pad;
    const diagW = Math.max(400, maxX - minX);
    const diagH = Math.max(300, maxY - minY);

    dom.minimapSvg.setAttribute('viewBox', `${minX} ${minY} ${diagW} ${diagH}`);

    // Render miniature nodes
    let svgContent = '';
    state.nodes.forEach(n => {
      const w = n.width || DEFAULT_NODE_WIDTH;
      const h = n.height || DEFAULT_NODE_HEIGHT;
      const fill = n.type === 'decision' ? '#f59e0b' : (n.type === 'start' || n.type === 'end' ? '#10b981' : '#3b82f6');
      svgContent += `<rect x="${n.x}" y="${n.y}" width="${w}" height="${h}" rx="4" fill="${fill}" opacity="0.65" />`;
    });

    // Render viewport rectangle
    const vpW = dom.canvasContainer.clientWidth / state.viewport.zoom;
    const vpH = dom.canvasContainer.clientHeight / state.viewport.zoom;
    const vpX = -state.viewport.x / state.viewport.zoom;
    const vpY = -state.viewport.y / state.viewport.zoom;

    svgContent += `
      <rect 
        id="fcMinimapViewport" 
        class="fc-minimap-viewport" 
        x="${vpX}" 
        y="${vpY}" 
        width="${vpW}" 
        height="${vpH}" 
      />
    `;

    dom.minimapSvg.innerHTML = svgContent;
  }

  // --- DYNAMIC ALIGNMENT GUIDES ---
  function updateAlignmentGuides(movingNode, allOtherNodes) {
    dom.guidesLayer.innerHTML = '';
    const snapThreshold = 6;
    const mw = movingNode.width || DEFAULT_NODE_WIDTH;
    const mh = movingNode.height || DEFAULT_NODE_HEIGHT;
    const mLeft = movingNode.x;
    const mCenter = movingNode.x + mw / 2;
    const mRight = movingNode.x + mw;
    const mTop = movingNode.y;
    const mMiddle = movingNode.y + mh / 2;
    const mBottom = movingNode.y + mh;

    let guideLines = '';

    allOtherNodes.forEach(other => {
      const ow = other.width || DEFAULT_NODE_WIDTH;
      const oh = other.height || DEFAULT_NODE_HEIGHT;
      const oLeft = other.x;
      const oCenter = other.x + ow / 2;
      const oRight = other.x + ow;
      const oTop = other.y;
      const oMiddle = other.y + oh / 2;
      const oBottom = other.y + oh;

      // Vertical alignment checks (X axis)
      if (Math.abs(mCenter - oCenter) < snapThreshold) {
        movingNode.x = oCenter - mw / 2;
        const yMin = Math.min(mTop, oTop) - 50;
        const yMax = Math.max(mBottom, oBottom) + 50;
        guideLines += `<line class="fc-guide-line" x1="${oCenter}" y1="${yMin}" x2="${oCenter}" y2="${yMax}" />`;
      } else if (Math.abs(mLeft - oLeft) < snapThreshold) {
        movingNode.x = oLeft;
        const yMin = Math.min(mTop, oTop) - 50;
        const yMax = Math.max(mBottom, oBottom) + 50;
        guideLines += `<line class="fc-guide-line" x1="${oLeft}" y1="${yMin}" x2="${oLeft}" y2="${yMax}" />`;
      }

      // Horizontal alignment checks (Y axis)
      if (Math.abs(mMiddle - oMiddle) < snapThreshold) {
        movingNode.y = oMiddle - mh / 2;
        const xMin = Math.min(mLeft, oLeft) - 50;
        const xMax = Math.max(mRight, oRight) + 50;
        guideLines += `<line class="fc-guide-line" x1="${xMin}" y1="${oMiddle}" x2="${xMax}" y2="${oMiddle}" />`;
      } else if (Math.abs(mTop - oTop) < snapThreshold) {
        movingNode.y = oTop;
        const xMin = Math.min(mLeft, oLeft) - 50;
        const xMax = Math.max(mRight, oRight) + 50;
        guideLines += `<line class="fc-guide-line" x1="${xMin}" y1="${oTop}" x2="${xMax}" y2="${oTop}" />`;
      }
    });

    dom.guidesLayer.innerHTML = guideLines;
  }

  function clearAlignmentGuides() {
    dom.guidesLayer.innerHTML = '';
  }

  // --- AUTOMATIC HIERARCHICAL LAYOUT (Sugiyama Client Implementation) ---
  function autoArrange(direction = 'TB') {
    state.layout.direction = direction;
    pushHistory();

    const nodes = state.nodes;
    const edges = state.edges;
    if (nodes.length === 0) return;

    // Node maps
    const nodeMap = new Map();
    const inEdges = new Map();
    const outEdges = new Map();

    nodes.forEach(n => {
      nodeMap.set(n.id, n);
      inEdges.set(n.id, []);
      outEdges.set(n.id, []);
    });

    edges.forEach(e => {
      if (nodeMap.has(e.source) && nodeMap.has(e.target) && e.source !== e.target) {
        outEdges.get(e.source).push(e.target);
        inEdges.get(e.target).push(e.source);
      }
    });

    // Cycle breaking DFS
    const visited = new Set();
    const acyclicOut = new Map();
    nodes.forEach(n => acyclicOut.set(n.id, []));

    function dfsCycle(curr, pathSet) {
      visited.add(curr);
      pathSet.add(curr);
      outEdges.get(curr).forEach(nxt => {
        if (!pathSet.has(nxt)) {
          acyclicOut.get(curr).push(nxt);
          if (!visited.has(nxt)) dfsCycle(nxt, pathSet);
        }
      });
      pathSet.delete(curr);
    }

    const roots = nodes.filter(n => n.type === 'start' || inEdges.get(n.id).length === 0).map(n => n.id);
    (roots.length > 0 ? roots : [nodes[0].id]).forEach(r => {
      if (!visited.has(r)) dfsCycle(r, new Set());
    });
    nodes.forEach(n => {
      if (!visited.has(n.id)) dfsCycle(n.id, new Set());
    });

    // Topological sort & Rank Assignment
    const inDegree = new Map();
    nodes.forEach(n => inDegree.set(n.id, 0));
    nodes.forEach(n => {
      acyclicOut.get(n.id).forEach(nxt => {
        inDegree.set(nxt, inDegree.get(nxt) + 1);
      });
    });

    const queue = nodes.filter(n => inDegree.get(n.id) === 0).map(n => n.id);
    if (queue.length === 0) queue.push(nodes[0].id);

    const topoOrder = [];
    while (queue.length > 0) {
      const curr = queue.shift();
      topoOrder.push(curr);
      acyclicOut.get(curr).forEach(nxt => {
        inDegree.set(nxt, inDegree.get(nxt) - 1);
        if (inDegree.get(nxt) === 0) queue.push(nxt);
      });
    }
    nodes.forEach(n => {
      if (!topoOrder.includes(n.id)) topoOrder.push(n.id);
    });

    const ranks = new Map();
    nodes.forEach(n => ranks.set(n.id, 0));

    topoOrder.forEach(u => {
      const currR = ranks.get(u);
      acyclicOut.get(u).forEach(v => {
        if (ranks.get(v) < currR + 1) {
          ranks.set(v, currR + 1);
        }
      });
    });

    // Align 'end' nodes at deepest rank
    let maxR = 0;
    ranks.forEach(r => { maxR = Math.max(maxR, r); });
    nodes.forEach(n => {
      if (n.type === 'end') ranks.set(n.id, maxR);
    });

    // Group by rank
    const rankGroups = new Map();
    ranks.forEach((r, nId) => {
      if (!rankGroups.has(r)) rankGroups.set(r, []);
      rankGroups.get(r).push(nId);
    });

    const sortedRanks = Array.from(rankGroups.keys()).sort((a, b) => a - b);

    // Spacing
    const nodeW = DEFAULT_NODE_WIDTH;
    const nodeH = DEFAULT_NODE_HEIGHT;
    const gapX = 75;
    const gapY = 85;
    const startX = 100;
    const startY = 80;

    let maxSpan = 0;
    sortedRanks.forEach(r => {
      const count = rankGroups.get(r).length;
      maxSpan = Math.max(maxSpan, count * nodeW + (count - 1) * gapX);
    });

    sortedRanks.forEach((r, rIdx) => {
      const group = rankGroups.get(r);
      const count = group.length;
      const layerSpan = count * nodeW + (count - 1) * gapX;
      const centerOffset = (maxSpan - layerSpan) / 2;

      group.forEach((nId, idx) => {
        const node = nodeMap.get(nId);
        if (direction === 'TB') {
          node.x = Math.round(startX + centerOffset + idx * (nodeW + gapX));
          node.y = Math.round(startY + rIdx * (nodeH + gapY));
        } else {
          node.x = Math.round(startX + rIdx * (nodeW + gapX + 30));
          node.y = Math.round(startY + centerOffset + idx * (nodeH + gapY));
        }
      });
    });

    setDirty(true);
    renderDiagram();
    fitToScreen();
    showToast(`Diagram auto-arranged (${direction === 'TB' ? 'Top to Bottom' : 'Left to Right'})`, 'success');
  }

  // --- ZOOM & PAN ---
  function setZoom(newZoom, centerX, centerY) {
    const clamped = Math.max(0.15, Math.min(3.0, newZoom));
    const container = dom.canvasContainer;
    const rect = container.getBoundingClientRect();

    const cx = centerX !== undefined ? centerX - rect.left : container.clientWidth / 2;
    const cy = centerY !== undefined ? centerY - rect.top : container.clientHeight / 2;

    const oldZoom = state.viewport.zoom;
    const scaleFactor = clamped / oldZoom;

    state.viewport.x = cx - (cx - state.viewport.x) * scaleFactor;
    state.viewport.y = cy - (cy - state.viewport.y) * scaleFactor;
    state.viewport.zoom = clamped;

    updateViewportTransform();
    renderMinimap();
  }

  function fitToScreen() {
    if (state.nodes.length === 0) {
      state.viewport = { x: 80, y: 80, zoom: 1.0 };
      updateViewportTransform();
      renderMinimap();
      return;
    }

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    state.nodes.forEach(n => {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + (n.width || DEFAULT_NODE_WIDTH));
      maxY = Math.max(maxY, n.y + (n.height || DEFAULT_NODE_HEIGHT));
    });

    const pad = 80;
    const diagW = (maxX - minX) + pad * 2;
    const diagH = (maxY - minY) + pad * 2;

    const containerW = dom.canvasContainer.clientWidth;
    const containerH = dom.canvasContainer.clientHeight;

    const zoomX = containerW / diagW;
    const zoomY = containerH / diagH;
    const newZoom = Math.max(0.2, Math.min(1.4, Math.min(zoomX, zoomY)));

    state.viewport.zoom = newZoom;
    state.viewport.x = (containerW - (maxX - minX) * newZoom) / 2 - minX * newZoom;
    state.viewport.y = (containerH - (maxY - minY) * newZoom) / 2 - minY * newZoom;

    updateViewportTransform();
    renderMinimap();
  }

  function screenToSvgCoords(screenX, screenY) {
    const rect = dom.canvasContainer.getBoundingClientRect();
    const relX = screenX - rect.left;
    const relY = screenY - rect.top;
    return {
      x: (relX - state.viewport.x) / state.viewport.zoom,
      y: (relY - state.viewport.y) / state.viewport.zoom
    };
  }

  // --- SELECTION & MANIPULATION ---
  function selectNode(nodeId, isMulti = false) {
    if (!isMulti) {
      state.selectedNodeIds.clear();
      state.selectedEdgeId = null;
    }
    state.selectedNodeIds.add(nodeId);
    renderNodes();
    renderEdges();
    updatePropertiesPanel();
  }

  function selectEdge(edgeId) {
    state.selectedNodeIds.clear();
    state.selectedEdgeId = edgeId;
    renderNodes();
    renderEdges();
    updatePropertiesPanel();
  }

  function clearSelection() {
    if (state.selectedNodeIds.size > 0 || state.selectedEdgeId !== null) {
      state.selectedNodeIds.clear();
      state.selectedEdgeId = null;
      renderNodes();
      renderEdges();
      updatePropertiesPanel();
    }
  }

  function deleteSelected() {
    if (state.selectedNodeIds.size === 0 && !state.selectedEdgeId) return;

    pushHistory();
    if (state.selectedNodeIds.size > 0) {
      const toDelete = new Set(state.selectedNodeIds);
      state.nodes = state.nodes.filter(n => !toDelete.has(n.id));
      // Delete attached edges
      state.edges = state.edges.filter(e => !toDelete.has(e.source) && !toDelete.has(e.target));
      state.selectedNodeIds.clear();
    }

    if (state.selectedEdgeId) {
      state.edges = state.edges.filter(e => e.id !== state.selectedEdgeId);
      state.selectedEdgeId = null;
    }

    setDirty(true);
    renderDiagram();
    showToast('Deleted selected item(s)', 'info');
  }

  function duplicateSelected() {
    if (state.selectedNodeIds.size === 0) return;
    pushHistory();

    const idMap = new Map();
    const newNodes = [];

    state.selectedNodeIds.forEach(nId => {
      const orig = state.nodes.find(n => n.id === nId);
      if (!orig) return;
      const newId = `node_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`;
      idMap.set(nId, newId);
      const clone = JSON.parse(JSON.stringify(orig));
      clone.id = newId;
      clone.x += 30;
      clone.y += 30;
      newNodes.push(clone);
    });

    state.nodes.push(...newNodes);

    // Duplicate internal edges between selected nodes
    const newEdges = [];
    state.edges.forEach(e => {
      if (idMap.has(e.source) && idMap.has(e.target)) {
        const edgeClone = JSON.parse(JSON.stringify(e));
        edgeClone.id = `edge_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`;
        edgeClone.source = idMap.get(e.source);
        edgeClone.target = idMap.get(e.target);
        newEdges.push(edgeClone);
      }
    });
    state.edges.push(...newEdges);

    // Switch selection to cloned nodes
    state.selectedNodeIds = new Set(newNodes.map(n => n.id));
    setDirty(true);
    renderDiagram();
    showToast('Duplicated selected node(s)', 'info');
  }

  function selectAll() {
    state.selectedNodeIds = new Set(state.nodes.map(n => n.id));
    state.selectedEdgeId = null;
    renderNodes();
    renderEdges();
    updatePropertiesPanel();
  }

  // --- INLINE TEXT EDITING ---
  function startInlineEditing(nodeId) {
    const node = state.nodes.find(n => n.id === nodeId);
    if (!node) return;

    const editor = dom.inlineEditor;
    const { x, y, zoom } = state.viewport;
    const screenX = node.x * zoom + x;
    const screenY = node.y * zoom + y;
    const screenW = (node.width || DEFAULT_NODE_WIDTH) * zoom;
    const screenH = (node.height || DEFAULT_NODE_HEIGHT) * zoom;

    editor.style.left = `${screenX}px`;
    editor.style.top = `${screenY}px`;
    editor.style.width = `${Math.max(120, screenW)}px`;
    editor.style.minHeight = `${Math.max(50, screenH)}px`;
    editor.style.fontSize = `${Math.max(12, (node.style?.fontSize || 13) * zoom)}px`;
    editor.value = node.label || '';
    editor.style.display = 'block';
    editor.focus();
    editor.select();

    function finishInlineEdit() {
      editor.style.display = 'none';
      editor.removeEventListener('blur', finishInlineEdit);
      editor.removeEventListener('keydown', onKeyDown);
      const newText = editor.value.trim();
      if (newText !== node.label) {
        pushHistory();
        node.label = newText;
        setDirty(true);
        renderNodes();
        updatePropertiesPanel();
      }
    }

    function onKeyDown(e) {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        finishInlineEdit();
      } else if (e.key === 'Escape') {
        editor.style.display = 'none';
        editor.removeEventListener('blur', finishInlineEdit);
        editor.removeEventListener('keydown', onKeyDown);
      }
    }

    editor.addEventListener('blur', finishInlineEdit);
    editor.addEventListener('keydown', onKeyDown);
  }

  // --- HISTORY & UNDO / REDO ---
  function pushHistory() {
    const snapshot = {
      title: state.title,
      nodes: JSON.parse(JSON.stringify(state.nodes)),
      edges: JSON.parse(JSON.stringify(state.edges))
    };

    // Truncate any redo steps ahead
    state.history = state.history.slice(0, state.historyIndex + 1);
    state.history.push(snapshot);
    if (state.history.length > state.maxHistory) {
      state.history.shift();
    }
    state.historyIndex = state.history.length - 1;
    updateUndoRedoButtons();
  }

  function undo() {
    if (state.historyIndex > 0) {
      state.historyIndex--;
      const snapshot = state.history[state.historyIndex];
      applySnapshot(snapshot);
      showToast('Undo', 'info');
    }
  }

  function redo() {
    if (state.historyIndex < state.history.length - 1) {
      state.historyIndex++;
      const snapshot = state.history[state.historyIndex];
      applySnapshot(snapshot);
      showToast('Redo', 'info');
    }
  }

  function applySnapshot(snapshot) {
    state.title = snapshot.title;
    state.nodes = JSON.parse(JSON.stringify(snapshot.nodes));
    state.edges = JSON.parse(JSON.stringify(snapshot.edges));
    dom.titleInput.value = state.title;
    state.selectedNodeIds.clear();
    state.selectedEdgeId = null;
    setDirty(true);
    renderDiagram();
    updateUndoRedoButtons();
  }

  function updateUndoRedoButtons() {
    dom.btnUndo.disabled = state.historyIndex <= 0;
    dom.btnRedo.disabled = state.historyIndex >= state.history.length - 1;
    dom.btnUndo.style.opacity = dom.btnUndo.disabled ? '0.4' : '1';
    dom.btnRedo.style.opacity = dom.btnRedo.disabled ? '0.4' : '1';
  }

  // --- DIRTY & SAVE STATUS ---
  function setDirty(isDirty) {
    state.isDirty = isDirty;
    if (isDirty) {
      dom.statusBadge.className = 'fc-status-badge unsaved';
      dom.statusText.textContent = 'Unsaved changes';
    } else {
      dom.statusBadge.className = 'fc-status-badge saved';
      dom.statusText.textContent = 'Saved to cloud';
    }
  }

  // --- PROPERTIES PANEL SYNC ---
  function updatePropertiesPanel() {
    // 1. Single Node Selected
    if (state.selectedNodeIds.size === 1) {
      const nodeId = Array.from(state.selectedNodeIds)[0];
      const node = state.nodes.find(n => n.id === nodeId);
      if (!node) return;

      dom.propHeaderTitle.textContent = `${capitalize(node.type || 'Process')} Node`;
      dom.propContentNode.style.display = 'block';
      dom.propContentEdge.style.display = 'none';
      dom.propContentCanvas.style.display = 'none';

      // Populate fields
      document.getElementById('fcNodeLabelInput').value = node.label || '';
      document.getElementById('fcNodeTypeSelect').value = node.type || 'process';
      document.getElementById('fcNodeFontSize').value = node.style?.fontSize || 13;
      document.getElementById('fcNodeBorderWidth').value = node.style?.strokeWidth || 2;
      document.getElementById('fcNodeBorderStyle').value = node.style?.borderStyle || 'solid';

      // Fill & Border pickers
      document.getElementById('fcNodeFillPicker').value = node.style?.fill || '#ffffff';
      document.getElementById('fcNodeStrokePicker').value = node.style?.stroke || '#3b82f6';
      document.getElementById('fcNodeTextPicker').value = node.style?.textColor || '#1e293b';

      return;
    }

    // 2. Edge Selected
    if (state.selectedEdgeId) {
      const edge = state.edges.find(e => e.id === state.selectedEdgeId);
      if (!edge) return;

      dom.propHeaderTitle.textContent = 'Connector Edge';
      dom.propContentNode.style.display = 'none';
      dom.propContentEdge.style.display = 'block';
      dom.propContentCanvas.style.display = 'none';

      document.getElementById('fcEdgeLabelInput').value = edge.label || '';
      document.getElementById('fcEdgeRouteSelect').value = edge.type || 'orthogonal';
      document.getElementById('fcEdgeStrokePicker').value = edge.style?.stroke || '#64748b';
      document.getElementById('fcEdgeWidthInput').value = edge.style?.strokeWidth || 2;

      const sPortSel = document.getElementById('fcEdgeSourcePortSelect');
      if (sPortSel) sPortSel.value = edge.sourcePort || '';

      const tPortSel = document.getElementById('fcEdgeTargetPortSelect');
      if (tPortSel) tPortSel.value = edge.targetPort || '';

      const bendCountEl = document.getElementById('fcEdgeBendCount');
      if (bendCountEl) {
        const count = (edge.points || []).length;
        bendCountEl.textContent = count === 0 ? 'No custom turns (auto)' : `${count} bend point${count > 1 ? 's' : ''}`;
      }

      return;
    }

    // 3. Canvas Selected (Default)
    dom.propHeaderTitle.textContent = 'Canvas Settings';
    dom.propContentNode.style.display = 'none';
    dom.propContentEdge.style.display = 'none';
    dom.propContentCanvas.style.display = 'block';

    document.getElementById('fcCanvasDirection').value = state.layout.direction || 'TB';
    document.getElementById('fcCanvasGridType').value = state.layout.grid || 'dots';
    document.getElementById('fcCanvasNodeCount').textContent = state.nodes.length;
    document.getElementById('fcCanvasEdgeCount').textContent = state.edges.length;
  }

  function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  // --- SAVE & PERSISTENCE ---
  async function saveDiagramToBackend() {
    setDirty(false);
    dom.btnSave.disabled = true;
    dom.btnSave.innerHTML = `<span class="fc-spinner"></span> Saving...`;

    const payload = {
      id: state.diagramId,
      title: state.title.trim() || 'Untitled Flowchart',
      description: state.description,
      nodes: state.nodes,
      edges: state.edges,
      viewport: state.viewport,
      layout: state.layout
    };

    try {
      const res = await fetch('/api/flowchart/save', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (res.ok && data.success) {
        state.diagramId = data.diagram_id;
        state.title = data.title;
        dom.titleInput.value = state.title;
        setDirty(false);
        saveDraftLocally();
        setupSavedDiagramsList();
        showToast('Diagram saved to cloud successfully!', 'success');
      } else {
        setDirty(true);
        showToast(data.error || 'Failed to save diagram', 'error');
      }
    } catch (err) {
      console.error('Save error:', err);
      setDirty(true);
      showToast('Network error while saving. Draft saved locally.', 'warning');
      saveDraftLocally();
    } finally {
      dom.btnSave.disabled = false;
      dom.btnSave.innerHTML = `<i class="fa-solid fa-floppy-disk"></i> Save`;
    }
  }

  async function loadDiagramFromBackend(diagramId) {
    try {
      const res = await fetch(`/api/flowchart/${diagramId}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.success) {
        const d = data.diagram;
        state.diagramId = d.diagram_id;
        state.title = d.title || 'Untitled Flowchart';
        state.description = d.description || '';
        state.nodes = d.nodes || [];
        state.edges = d.edges || [];
        if (d.viewport) state.viewport = d.viewport;
        if (d.layout) state.layout = d.layout;
        dom.titleInput.value = state.title;
        setDirty(false);
        renderDiagram();
        fitToScreen();
        pushHistory();
        showToast(`Opened "${state.title}"`, 'success');
      } else {
        showToast(data.error || 'Could not load diagram', 'error');
      }
    } catch (e) {
      showToast('Network error loading diagram', 'error');
    }
  }

  async function setupSavedDiagramsList() {
    const listContainer = document.getElementById('fcSavedList');
    if (!listContainer) return;

    try {
      const res = await fetch('/api/flowchart/list', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.success) {
        const diagrams = data.diagrams || [];
        if (diagrams.length === 0) {
          listContainer.innerHTML = `
            <div style="text-align: center; padding: 24px 12px; color: var(--fc-text-muted); font-size: 12px;">
              <i class="fa-solid fa-folder-open" style="font-size: 24px; margin-bottom: 8px; opacity: 0.5;"></i>
              <p>No saved diagrams yet.<br>Click <b>Save</b> to store your work.</p>
            </div>
          `;
          return;
        }

        listContainer.innerHTML = diagrams.map(d => `
          <div class="fc-saved-item">
            <div class="fc-saved-title">
              <span>${escapeXml(d.title)}</span>
              <div class="fc-saved-actions">
                <button class="fc-btn fc-btn-xs" onclick="window.fcApp.duplicateDiagram('${d.id}')" title="Duplicate">
                  <i class="fa-solid fa-copy"></i>
                </button>
                <button class="fc-btn fc-btn-xs" style="color: #ef4444;" onclick="window.fcApp.deleteDiagram('${d.id}')" title="Delete">
                  <i class="fa-solid fa-trash"></i>
                </button>
              </div>
            </div>
            <div class="fc-saved-meta">
              <span>${d.node_count || 0} nodes &bull; ${d.edge_count || 0} edges</span>
              <button class="fc-btn fc-btn-xs fc-btn-primary" onclick="window.fcApp.openDiagram('${d.id}')">
                Open
              </button>
            </div>
          </div>
        `).join('');
      }
    } catch (e) {
      console.warn('Error fetching saved list', e);
    }
  }

  // --- TEMPLATES LOADER ---
  function setupTemplates() {
    const container = document.getElementById('fcTemplatesList');
    if (!container) return;

    container.innerHTML = TEMPLATES.map(tmpl => `
      <div class="fc-template-card">
        <div class="fc-template-title">
          <i class="fa-solid fa-diagram-project" style="color: var(--fc-primary);"></i>
          ${escapeXml(tmpl.title)}
        </div>
        <div class="fc-template-desc">${escapeXml(tmpl.desc)}</div>
        <div class="fc-template-meta">
          <span class="fc-template-badge">${escapeXml(tmpl.category)}</span>
          <button class="fc-btn fc-btn-xs fc-btn-primary" onclick="window.fcApp.loadTemplate('${tmpl.id}')">
            Use Template
          </button>
        </div>
      </div>
    `).join('');
  }

  function loadTemplate(templateId) {
    const tmpl = TEMPLATES.find(t => t.id === templateId);
    if (!tmpl) return;

    if (state.isDirty && state.nodes.length > 0) {
      showConfirmDialog(
        'Discard Current Changes?',
        'Loading a template will replace your current diagram. Make sure to save any unsaved work first.',
        () => applyTemplate(tmpl)
      );
    } else {
      applyTemplate(tmpl);
    }
  }

  function applyTemplate(tmpl) {
    state.diagramId = null;
    state.title = tmpl.title;
    state.description = tmpl.desc;
    state.nodes = JSON.parse(JSON.stringify(tmpl.nodes));
    state.edges = JSON.parse(JSON.stringify(tmpl.edges));
    dom.titleInput.value = state.title;

    setDirty(false);
    renderDiagram();
    fitToScreen();
    pushHistory();
    showToast(`Loaded template: ${tmpl.title}`, 'success');
  }

  // --- CODE TO FLOWCHART ---
  async function generateFromCode() {
    const lang = document.getElementById('fcCodeLanguage').value;
    const code = document.getElementById('fcCodeTextarea').value;
    const errBox = document.getElementById('fcCodeError');
    const btnGen = document.getElementById('fcBtnGenerateCode');

    if (!code || !code.trim()) {
      errBox.textContent = 'Please enter code in the editor.';
      errBox.style.display = 'block';
      return;
    }

    errBox.style.display = 'none';
    btnGen.disabled = true;
    btnGen.innerHTML = `<span class="fc-spinner"></span> Parsing AST...`;

    try {
      const res = await fetch('/api/flowchart/code-to-flowchart', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ language: lang, code: code })
      });

      const data = await res.json();
      if (res.ok && data.success) {
        state.nodes = data.nodes || [];
        state.edges = data.edges || [];
        state.title = data.title || `${capitalize(lang)} Code Flowchart`;
        dom.titleInput.value = state.title;
        setDirty(true);
        closeModal(dom.codeModal);
        renderDiagram();
        fitToScreen();
        pushHistory();
        showToast(`Generated flowchart from ${capitalize(lang)} code!`, 'success');
      } else {
        errBox.textContent = data.error || 'Failed to parse code';
        errBox.style.display = 'block';
      }
    } catch (e) {
      errBox.textContent = 'Network error contacting server.';
      errBox.style.display = 'block';
    } finally {
      btnGen.disabled = false;
      btnGen.innerHTML = `<i class="fa-solid fa-code"></i> Generate Flowchart`;
    }
  }

  // --- AI NATURAL LANGUAGE FLOWCHART GENERATION ---
  async function generateFromAi() {
    const prompt = document.getElementById('fcAiPromptInput').value;
    const errBox = document.getElementById('fcAiError');
    const btnGen = document.getElementById('fcBtnGenerateAi');

    if (!prompt || !prompt.trim() || prompt.trim().length < 5) {
      errBox.textContent = 'Please provide a clear description of the process or workflow.';
      errBox.style.display = 'block';
      return;
    }

    errBox.style.display = 'none';
    btnGen.disabled = true;
    btnGen.innerHTML = `<span class="fc-spinner"></span> Generating with AI...`;

    try {
      const res = await fetch('/api/flowchart/generate-ai', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ prompt: prompt.trim() })
      });

      const data = await res.json();
      if (res.ok && data.success) {
        const d = data.diagram;
        state.nodes = d.nodes || [];
        state.edges = d.edges || [];
        state.title = d.title || 'AI Generated Flowchart';
        state.description = d.description || '';
        dom.titleInput.value = state.title;
        setDirty(true);
        closeModal(dom.aiModal);
        renderDiagram();
        fitToScreen();
        pushHistory();
        showToast('Generated editable flowchart with AI!', 'success');
      } else {
        errBox.textContent = data.error || 'AI generation failed. Please retry with a clearer prompt.';
        errBox.style.display = 'block';
      }
    } catch (e) {
      errBox.textContent = 'Network error contacting AI service.';
      errBox.style.display = 'block';
    } finally {
      btnGen.disabled = false;
      btnGen.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Flowchart`;
    }
  }

  // --- EXPORT SUITE (PNG, SVG, PDF) ---
  function exportSvg() {
    const svgClone = createCleanSvgClone();
    const svgString = new XMLSerializer().serializeToString(svgClone);
    const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
    downloadBlob(blob, `${sanitizeFilename(state.title)}.svg`);
    showToast('Exported SVG successfully', 'success');
  }

  function exportPng() {
    const svgClone = createCleanSvgClone();
    const svgString = new XMLSerializer().serializeToString(svgClone);
    const vb = svgClone.viewBox.baseVal;
    const width = vb.width;
    const height = vb.height;

    const img = new Image();
    const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);

    img.onload = function () {
      const scale = 2.0; // High-DPI 2x resolution
      const canvas = document.createElement('canvas');
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext('2d');

      // Crisp background
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

      URL.revokeObjectURL(url);
      canvas.toBlob(blob => {
        downloadBlob(blob, `${sanitizeFilename(state.title)}.png`);
        showToast('Exported High-Resolution PNG successfully', 'success');
      }, 'image/png');
    };
    img.src = url;
  }

  function exportPdf() {
    // Generate publication-ready academic print PDF
    const svgClone = createCleanSvgClone(true); // with title banner
    const svgString = new XMLSerializer().serializeToString(svgClone);
    const vb = svgClone.viewBox.baseVal;
    const width = vb.width;
    const height = vb.height;

    const isLandscape = width > height;

    // Check if jsPDF is available
    if (window.jspdf && window.jspdf.jsPDF) {
      const img = new Image();
      const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);

      img.onload = function () {
        const canvas = document.createElement('canvas');
        canvas.width = width * 2;
        canvas.height = height * 2;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);

        const imgData = canvas.toDataURL('image/jpeg', 0.95);
        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF({
          orientation: isLandscape ? 'landscape' : 'portrait',
          unit: 'mm',
          format: 'a4'
        });

        const pageW = isLandscape ? 297 : 210;
        const pageH = isLandscape ? 210 : 297;
        const margin = 15;
        const maxW = pageW - margin * 2;
        const maxH = pageH - margin * 2;

        let renderW = maxW;
        let renderH = (height / width) * renderW;
        if (renderH > maxH) {
          renderH = maxH;
          renderW = (width / height) * renderH;
        }

        const x = (pageW - renderW) / 2;
        const y = (pageH - renderH) / 2;

        pdf.addImage(imgData, 'JPEG', x, y, renderW, renderH);
        pdf.save(`${sanitizeFilename(state.title)}.pdf`);
        showToast('Exported Academic Report PDF successfully', 'success');
      };
      img.src = url;
    } else {
      // Fallback: print formatted window
      printDiagramWindow();
    }
  }

  function createCleanSvgClone(includeAcademicHeader = false) {
    if (state.nodes.length === 0) {
      const emptySvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      emptySvg.setAttribute('viewBox', '0 0 400 300');
      return emptySvg;
    }

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    state.nodes.forEach(n => {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + (n.width || DEFAULT_NODE_WIDTH));
      maxY = Math.max(maxY, n.y + (n.height || DEFAULT_NODE_HEIGHT));
    });

    const pad = 50;
    const headerH = includeAcademicHeader ? 70 : 0;
    const bX = minX - pad;
    const bY = minY - pad - headerH;
    const bW = (maxX - minX) + pad * 2;
    const bH = (maxY - minY) + pad * 2 + headerH;

    const clone = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('viewBox', `${bX} ${bY} ${bW} ${bH}`);
    clone.setAttribute('width', bW);
    clone.setAttribute('height', bH);

    // Defs with markers & embedded font styles
    clone.innerHTML = `
      <defs>
        <marker id="marker-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#64748b" />
        </marker>
        <style>
          text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
          .fc-node-text { dominant-baseline: central; text-anchor: middle; font-weight: 500; }
          .fc-edge-label-text { font-size: 11px; font-weight: 600; fill: #475569; text-anchor: middle; dominant-baseline: central; }
          .fc-edge-label-bg { fill: #ffffff; stroke: #cbd5e1; stroke-width: 1; rx: 4; ry: 4; }
        </style>
      </defs>
      <rect x="${bX}" y="${bY}" width="${bW}" height="${bH}" fill="#ffffff" />
    `;

    // Optional Academic Header
    if (includeAcademicHeader) {
      const dateStr = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      clone.innerHTML += `
        <g transform="translate(${bX + pad}, ${bY + pad})">
          <text x="0" y="20" font-size="20" font-weight="700" fill="#0f172a">${escapeXml(state.title)}</text>
          <text x="0" y="40" font-size="12" font-weight="500" fill="#64748b">Student Project Management System &bull; Flowchart Specification &bull; ${dateStr}</text>
          <line x1="0" y1="52" x2="${bW - pad * 2}" y2="52" stroke="#e2e8f0" stroke-width="1.5" />
        </g>
      `;
    }

    // Edges
    const edgesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    state.edges.forEach(edge => {
      const srcNode = state.nodes.find(n => n.id === edge.source);
      const tgtNode = state.nodes.find(n => n.id === edge.target);
      if (!srcNode || !tgtNode) return;

      const ports = getBestPorts(srcNode, tgtNode);
      const sPort = edge.sourcePort || ports.srcPort;
      const tPort = edge.targetPort || ports.tgtPort;
      const srcPt = getPortAbsoluteCoordinate(edge.source, sPort);
      const tgtPt = getPortAbsoluteCoordinate(edge.target, tPort);

      const routeType = edge.type || 'orthogonal';
      const pathData = calculateEdgePath(srcPt, tgtPt, routeType, edge.points || [], sPort, tPort);
      const stroke = edge.style?.stroke || '#64748b';
      const strokeWidth = edge.style?.strokeWidth || 2;

      let edgeMarkup = `
        <path d="${pathData}" fill="none" stroke="${stroke}" stroke-width="${strokeWidth}" marker-end="url(#marker-arrow)" />
      `;

      if (edge.label && edge.label.trim()) {
        const mid = getEdgeMidpoint(srcPt, tgtPt, routeType, edge.points || [], sPort, tPort);
        const lbl = edge.label.trim();
        const badgeW = Math.max(34, lbl.length * 8 + 14);
        const badgeH = 20;
        edgeMarkup += `
          <g transform="translate(${mid.x}, ${mid.y})">
            <rect class="fc-edge-label-bg" x="${-badgeW / 2}" y="${-badgeH / 2}" width="${badgeW}" height="${badgeH}" />
            <text class="fc-edge-label-text">${escapeXml(lbl)}</text>
          </g>
        `;
      }
      edgesGroup.innerHTML += edgeMarkup;
    });
    clone.appendChild(edgesGroup);

    // Nodes
    const nodesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    state.nodes.forEach(node => {
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('transform', `translate(${node.x}, ${node.y})`);

      let shapeSvg = getNodeShapeSvg(node);
      const w = node.width || DEFAULT_NODE_WIDTH;
      const h = node.height || DEFAULT_NODE_HEIGHT;
      const style = node.style || {};
      const fontSize = style.fontSize || 13;
      const textColor = style.textColor || '#1e293b';

      const lines = wrapTextLines(node.label || '', w - 24, fontSize);
      const lineHeight = fontSize * 1.25;
      const totalTextH = lines.length * lineHeight;
      const startY = (h - totalTextH) / 2 + lineHeight / 2;

      let textTspans = lines
        .map((line, idx) => `<tspan x="${w / 2}" y="${startY + idx * lineHeight}">${escapeXml(line)}</tspan>`)
        .join('');

      shapeSvg += `
        <text class="fc-node-text" fill="${textColor}" font-size="${fontSize}" font-weight="500" text-anchor="middle">
          ${textTspans}
        </text>
      `;

      g.innerHTML = shapeSvg;
      nodesGroup.appendChild(g);
    });
    clone.appendChild(nodesGroup);

    return clone;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function sanitizeFilename(title) {
    return (title || 'flowchart').replace(/[^a-z0-9_\-]/gi, '_').toLowerCase();
  }

  function printDiagramWindow() {
    window.print();
  }

  // --- EVENT LISTENERS & DRAG-AND-DROP ---
  function setupEventListeners() {
    // Window Resize
    window.addEventListener('resize', () => {
      updateViewportTransform();
      renderMinimap();
    });

    // Keyboard Shortcuts
    window.addEventListener('keydown', e => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if (e.code === 'Space' && !state.spacePressed) {
        state.spacePressed = true;
        dom.canvasContainer.classList.add('panning');
      }

      // Undo / Redo
      if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || e.key === 'Y')) {
        e.preventDefault();
        redo();
      }

      // Save: Ctrl+S
      if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        saveDiagramToBackend();
      }

      // Select All: Ctrl+A
      if ((e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A')) {
        e.preventDefault();
        selectAll();
      }

      // Duplicate: Ctrl+D
      if ((e.ctrlKey || e.metaKey) && (e.key === 'd' || e.key === 'D')) {
        e.preventDefault();
        duplicateSelected();
      }

      // Delete: Delete / Backspace
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        deleteSelected();
      }

      // Zoom: + / -
      if (e.key === '=' || e.key === '+') {
        e.preventDefault();
        setZoom(state.viewport.zoom + 0.15);
      } else if (e.key === '-' || e.key === '_') {
        e.preventDefault();
        setZoom(state.viewport.zoom - 0.15);
      }

      // Escape
      if (e.key === 'Escape') {
        clearSelection();
        cancelConnecting();
      }
    });

    window.addEventListener('keyup', e => {
      if (e.code === 'Space') {
        state.spacePressed = false;
        if (state.mode !== 'panning') {
          dom.canvasContainer.classList.remove('panning');
        }
      }
    });

    // Mouse Wheel Zoom
    dom.canvasContainer.addEventListener('wheel', e => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
      setZoom(state.viewport.zoom * zoomFactor, e.clientX, e.clientY);
    }, { passive: false });

    // Canvas Pointer Down
    dom.canvasContainer.addEventListener('mousedown', onCanvasMouseDown);
    window.addEventListener('mousemove', onCanvasMouseMove);
    window.addEventListener('mouseup', onCanvasMouseUp);

    // Double click to edit node text
    dom.canvasContainer.addEventListener('dblclick', e => {
      const nodeEl = e.target.closest('.fc-node');
      if (nodeEl) {
        startInlineEditing(nodeEl.dataset.nodeId);
      }
    });

    // Drag from Shapes Library onto Canvas
    setupLibraryDragAndDrop();

    // Topbar & Panel Inputs
    setupControlInputs();
  }

  function onCanvasMouseDown(e) {
    if (e.button === 1 || state.spacePressed) {
      // Middle click or Spacebar Panning
      state.mode = 'panning';
      dom.canvasContainer.classList.add('panning');
      state.panStart = { x: e.clientX, y: e.clientY, vpX: state.viewport.x, vpY: state.viewport.y };
      return;
    }

    if (e.button !== 0) return; // Left click only

    const target = e.target;

    // 0a. Bend Handle clicked (Drag bend point or double click to delete)
    const bendHandle = target.closest('.fc-bend-handle');
    if (bendHandle) {
      const edgeId = bendHandle.dataset.edgeId;
      const pointIndex = parseInt(bendHandle.dataset.pointIndex, 10);
      const edge = state.edges.find(ed => ed.id === edgeId);
      if (edge && edge.points && edge.points[pointIndex]) {
        if (e.detail === 2) {
          // Double click removes bend point
          pushHistory();
          edge.points.splice(pointIndex, 1);
          setDirty(true);
          renderEdges();
          updatePropertiesPanel();
          showToast('Removed bend point', 'info');
          return;
        }

        state.mode = 'dragging-bend';
        state.dragBend = {
          edgeId,
          pointIndex,
          startX: e.clientX,
          startY: e.clientY,
          initialPoint: { ...edge.points[pointIndex] }
        };
        dom.canvasContainer.classList.add('dragging-bend');
        return;
      }
    }

    // 0b. Segment Midpoint Handle clicked (Add bend point and immediately drag)
    const segHandle = target.closest('.fc-segment-handle');
    if (segHandle) {
      const edgeId = segHandle.dataset.edgeId;
      const segX = parseFloat(segHandle.dataset.segX);
      const segY = parseFloat(segHandle.dataset.segY);
      const edge = state.edges.find(ed => ed.id === edgeId);
      if (edge) {
        pushHistory();
        edge.points = edge.points || [];
        const insertIdx = findBestPointInsertIndex(edge, segX, segY);
        edge.points.splice(insertIdx, 0, { x: segX, y: segY });
        setDirty(true);
        renderEdges();
        updatePropertiesPanel();

        state.mode = 'dragging-bend';
        state.dragBend = {
          edgeId,
          pointIndex: insertIdx,
          startX: e.clientX,
          startY: e.clientY,
          initialPoint: { x: segX, y: segY }
        };
        dom.canvasContainer.classList.add('dragging-bend');
        return;
      }
    }

    // 1. Connection Port clicked
    const portEl = target.closest('.fc-port-hit') || target.closest('.fc-port') || target.closest('.fc-port-group');
    if (portEl) {
      const nodeId = portEl.dataset.nodeId;
      const portId = portEl.dataset.port;
      startConnecting(nodeId, portId, e);
      return;
    }

    // 2. Resize Handle clicked
    if (target.classList.contains('fc-resize-handle')) {
      startResizing(target.dataset.handle, e);
      return;
    }

    // 3. Node clicked
    const nodeEl = target.closest('.fc-node');
    if (nodeEl) {
      const nodeId = nodeEl.dataset.nodeId;
      if (!e.shiftKey && !state.selectedNodeIds.has(nodeId)) {
        selectNode(nodeId, false);
      } else if (e.shiftKey) {
        if (state.selectedNodeIds.has(nodeId)) state.selectedNodeIds.delete(nodeId);
        else state.selectedNodeIds.add(nodeId);
        renderNodes();
        updatePropertiesPanel();
      }

      startDraggingNodes(e);
      return;
    }

    // 4. Edge clicked
    const edgeGroup = target.closest('.fc-edge-group');
    if (edgeGroup) {
      selectEdge(edgeGroup.dataset.edgeId);
      return;
    }

    // 5. Empty Canvas clicked
    if (!e.shiftKey) {
      clearSelection();
    }
    startMarqueeSelection(e);
  }

  function onCanvasMouseMove(e) {
    // 1. Panning
    if (state.mode === 'panning') {
      const dx = e.clientX - state.panStart.x;
      const dy = e.clientY - state.panStart.y;
      state.viewport.x = state.panStart.vpX + dx;
      state.viewport.y = state.panStart.vpY + dy;
      updateViewportTransform();
      renderMinimap();
      return;
    }

    // 2. Dragging Bend Point
    if (state.mode === 'dragging-bend') {
      const dx = (e.clientX - state.dragBend.startX) / state.viewport.zoom;
      const dy = (e.clientY - state.dragBend.startY) / state.viewport.zoom;
      const edge = state.edges.find(ed => ed.id === state.dragBend.edgeId);
      if (edge && edge.points && edge.points[state.dragBend.pointIndex]) {
        const snap = (state.layout.grid === 'lines' || state.layout.grid === 'dots') ? (state.layout.gridSize / 2) : 1;
        const newX = Math.round((state.dragBend.initialPoint.x + dx) / snap) * snap;
        const newY = Math.round((state.dragBend.initialPoint.y + dy) / snap) * snap;
        edge.points[state.dragBend.pointIndex].x = newX;
        edge.points[state.dragBend.pointIndex].y = newY;
        updateSingleEdgeDOM(edge);
      }
      return;
    }

    // 3. Connecting Wire
    if (state.mode === 'connecting') {
      updateConnectingWire(e);
      return;
    }

    // 4. Dragging Nodes
    if (state.mode === 'dragging-nodes') {
      dragNodes(e);
      return;
    }

    // 5. Resizing Node
    if (state.mode === 'resizing') {
      resizeNode(e);
      return;
    }

    // 6. Marquee Selection
    if (state.mode === 'marquee') {
      updateMarquee(e);
      return;
    }
  }

  function onCanvasMouseUp(e) {
    if (state.mode === 'panning') {
      state.mode = 'select';
      if (!state.spacePressed) dom.canvasContainer.classList.remove('panning');
      return;
    }

    if (state.mode === 'dragging-bend') {
      dom.canvasContainer.classList.remove('dragging-bend');
      state.mode = 'select';
      pushHistory();
      setDirty(true);
      renderEdges();
      updatePropertiesPanel();
      return;
    }

    if (state.mode === 'connecting') {
      finishConnecting(e);
      return;
    }

    if (state.mode === 'dragging-nodes') {
      finishDraggingNodes();
      return;
    }

    if (state.mode === 'resizing') {
      finishResizing();
      return;
    }

    if (state.mode === 'marquee') {
      finishMarquee();
      return;
    }
  }

  // --- CONNECTING ACTIONS ---
  function startConnecting(nodeId, portId, e) {
    state.mode = 'connecting';
    state.connectingSourceNodeId = nodeId;
    state.connectingSourcePort = portId;
    state.snappedTargetNodeId = null;
    state.snappedTargetPortId = null;
    dom.canvasContainer.classList.add('connecting');

    const srcPt = getPortAbsoluteCoordinate(nodeId, portId);
    state.connectingCurrentPoint = { x: srcPt.x, y: srcPt.y };
    updateConnectingWire(e);
  }

  function updateConnectingWire(e) {
    const mouseCoords = screenToSvgCoords(e.clientX, e.clientY);
    const srcPt = getPortAbsoluteCoordinate(state.connectingSourceNodeId, state.connectingSourcePort);

    // Proximity target port snapping (within 24px)
    let nearestPort = null;
    let nearestDist = 24;
    let nearestNode = null;

    state.nodes.forEach(node => {
      if (node.id === state.connectingSourceNodeId) return;
      const ports = getNodePorts(node);
      ports.forEach(p => {
        const absPt = { x: node.x + p.x, y: node.y + p.y };
        const dist = Math.hypot(mouseCoords.x - absPt.x, mouseCoords.y - absPt.y);
        if (dist < nearestDist) {
          nearestDist = dist;
          nearestPort = p;
          nearestNode = node;
        }
      });
    });

    let tgtPt = mouseCoords;
    let snapHighlightSvg = '';

    if (nearestPort && nearestNode) {
      tgtPt = { x: nearestNode.x + nearestPort.x, y: nearestNode.y + nearestPort.y };
      state.snappedTargetNodeId = nearestNode.id;
      state.snappedTargetPortId = nearestPort.id;
      snapHighlightSvg = `
        <circle cx="${tgtPt.x}" cy="${tgtPt.y}" r="8" fill="none" stroke="#2563eb" stroke-width="2.5" class="fc-port-snap-ring" />
      `;
    } else {
      state.snappedTargetNodeId = null;
      state.snappedTargetPortId = null;
    }

    const pathData = calculateEdgePath(srcPt, tgtPt, 'orthogonal', [], state.connectingSourcePort, state.snappedTargetPortId || 'top');

    dom.tempLayer.innerHTML = `
      <path 
        d="${pathData}" 
        fill="none" 
        stroke="#3b82f6" 
        stroke-width="2.5" 
        stroke-dasharray="4,4" 
        marker-end="url(#marker-arrow)"
      />
      ${snapHighlightSvg}
    `;
  }

  function finishConnecting(e) {
    dom.tempLayer.innerHTML = '';
    dom.canvasContainer.classList.remove('connecting');
    state.mode = 'select';

    let targetNodeId = state.snappedTargetNodeId;
    let targetPortId = state.snappedTargetPortId;

    if (!targetNodeId) {
      const target = e.target;
      const portEl = target.closest('.fc-port-hit') || target.closest('.fc-port') || target.closest('.fc-port-group');
      if (portEl) {
        targetNodeId = portEl.dataset.nodeId;
        targetPortId = portEl.dataset.port;
      } else {
        const nodeEl = target.closest('.fc-node');
        if (nodeEl) {
          targetNodeId = nodeEl.dataset.nodeId;
          const best = getBestPorts(
            state.nodes.find(n => n.id === state.connectingSourceNodeId),
            state.nodes.find(n => n.id === targetNodeId)
          );
          targetPortId = best.tgtPort || 'top';
        }
      }
    }

    if (targetNodeId && targetNodeId !== state.connectingSourceNodeId) {
      pushHistory();
      const newEdge = {
        id: `edge_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
        source: state.connectingSourceNodeId,
        target: targetNodeId,
        sourcePort: state.connectingSourcePort,
        targetPort: targetPortId,
        points: [],
        label: '',
        type: 'orthogonal',
        style: {
          stroke: '#64748b',
          strokeWidth: 2,
          markerEnd: 'arrow'
        }
      };

      const srcNode = state.nodes.find(n => n.id === state.connectingSourceNodeId);
      if (srcNode && srcNode.type === 'decision') {
        const outEdgesCount = state.edges.filter(ed => ed.source === srcNode.id).length;
        if (outEdgesCount === 0) newEdge.label = 'Yes';
        else if (outEdgesCount === 1) newEdge.label = 'No';
      }

      state.edges.push(newEdge);
      selectEdge(newEdge.id);
      setDirty(true);
      renderEdges();
      showToast('Connected nodes', 'success');
    } else {
      cancelConnecting();
    }

    state.connectingSourceNodeId = null;
    state.connectingSourcePort = null;
    state.snappedTargetNodeId = null;
    state.snappedTargetPortId = null;
  }

  function cancelConnecting() {
    dom.tempLayer.innerHTML = '';
    dom.canvasContainer.classList.remove('connecting');
    state.mode = 'select';
    state.connectingSourceNodeId = null;
    state.connectingSourcePort = null;
    state.snappedTargetNodeId = null;
    state.snappedTargetPortId = null;
  }

  // --- DRAGGING NODES ---
  function startDraggingNodes(e) {
    state.mode = 'dragging-nodes';
    state.dragPointerStart = { x: e.clientX, y: e.clientY };
    state.dragNodesStart.clear();
    state.selectedNodeIds.forEach(nId => {
      const node = state.nodes.find(n => n.id === nId);
      if (node) {
        state.dragNodesStart.set(nId, { x: node.x, y: node.y });
      }
    });
    dom.canvasContainer.classList.add('dragging-nodes');
  }

  function dragNodes(e) {
    const dx = (e.clientX - state.dragPointerStart.x) / state.viewport.zoom;
    const dy = (e.clientY - state.dragPointerStart.y) / state.viewport.zoom;

    const snap = state.layout.grid === 'lines' || state.layout.grid === 'dots' ? state.layout.gridSize : 1;

    state.selectedNodeIds.forEach(nId => {
      const initPos = state.dragNodesStart.get(nId);
      const node = state.nodes.find(n => n.id === nId);
      if (initPos && node) {
        node.x = Math.round((initPos.x + dx) / snap) * snap;
        node.y = Math.round((initPos.y + dy) / snap) * snap;
      }
    });

    // Dynamic Alignment Guides for single node drag
    if (state.selectedNodeIds.size === 1) {
      const singleId = Array.from(state.selectedNodeIds)[0];
      const singleNode = state.nodes.find(n => n.id === singleId);
      const otherNodes = state.nodes.filter(n => n.id !== singleId);
      if (singleNode) {
        updateAlignmentGuides(singleNode, otherNodes);
      }
    }

    // Direct DOM transform update for smooth 60fps drag
    state.selectedNodeIds.forEach(nId => {
      const node = state.nodes.find(n => n.id === nId);
      const el = document.getElementById(`fc_node_${nId}`);
      if (el && node) {
        el.setAttribute('transform', `translate(${node.x}, ${node.y})`);
      }
    });

    // Fast edge update without destroying/recreating DOM (eliminates flicker)
    updateAttachedEdges(state.selectedNodeIds);
  }

  function finishDraggingNodes() {
    dom.canvasContainer.classList.remove('dragging-nodes');
    clearAlignmentGuides();
    state.mode = 'select';
    pushHistory();
    setDirty(true);
    renderDiagram();
  }

  // --- RESIZING NODES ---
  function startResizing(handle, e) {
    if (state.selectedNodeIds.size !== 1) return;
    const nodeId = Array.from(state.selectedNodeIds)[0];
    const node = state.nodes.find(n => n.id === nodeId);
    if (!node) return;

    state.mode = 'resizing';
    state.resizeNodeId = nodeId;
    state.resizeHandle = handle;
    state.resizePointerStart = { x: e.clientX, y: e.clientY };
    state.resizeInitialRect = {
      x: node.x,
      y: node.y,
      width: node.width || DEFAULT_NODE_WIDTH,
      height: node.height || DEFAULT_NODE_HEIGHT
    };
  }

  function resizeNode(e) {
    const node = state.nodes.find(n => n.id === state.resizeNodeId);
    if (!node) return;

    const dx = (e.clientX - state.resizePointerStart.x) / state.viewport.zoom;
    const dy = (e.clientY - state.resizePointerStart.y) / state.viewport.zoom;
    const init = state.resizeInitialRect;
    const handle = state.resizeHandle;

    const minW = 80;
    const minH = 40;

    let newX = init.x;
    let newY = init.y;
    let newW = init.width;
    let newH = init.height;

    if (handle.includes('e')) newW = Math.max(minW, init.width + dx);
    if (handle.includes('s')) newH = Math.max(minH, init.height + dy);
    if (handle.includes('w')) {
      const potentialW = init.width - dx;
      if (potentialW >= minW) {
        newW = potentialW;
        newX = init.x + dx;
      }
    }
    if (handle.includes('n')) {
      const potentialH = init.height - dy;
      if (potentialH >= minH) {
        newH = potentialH;
        newY = init.y + dy;
      }
    }

    node.x = Math.round(newX);
    node.y = Math.round(newY);
    node.width = Math.round(newW);
    node.height = Math.round(newH);

    renderNodes();
    renderEdges();
  }

  function finishResizing() {
    state.mode = 'select';
    state.resizeNodeId = null;
    pushHistory();
    setDirty(true);
    renderDiagram();
  }

  // --- MARQUEE SELECTION ---
  function startMarqueeSelection(e) {
    state.mode = 'marquee';
    const coords = screenToSvgCoords(e.clientX, e.clientY);
    state.marqueeStart = coords;
    state.marqueeCurrent = coords;
  }

  function updateMarquee(e) {
    const coords = screenToSvgCoords(e.clientX, e.clientY);
    state.marqueeCurrent = coords;

    const x = Math.min(state.marqueeStart.x, coords.x);
    const y = Math.min(state.marqueeStart.y, coords.y);
    const w = Math.abs(coords.x - state.marqueeStart.x);
    const h = Math.abs(coords.y - state.marqueeStart.y);

    dom.tempLayer.innerHTML = `
      <rect class="fc-marquee-rect" x="${x}" y="${y}" width="${w}" height="${h}" />
    `;

    // Highlight enclosed nodes
    state.nodes.forEach(n => {
      const nw = n.width || DEFAULT_NODE_WIDTH;
      const nh = n.height || DEFAULT_NODE_HEIGHT;
      const isEnclosed = n.x >= x && n.x + nw <= x + w && n.y >= y && n.y + nh <= y + h;
      if (isEnclosed) state.selectedNodeIds.add(n.id);
      else if (!e.shiftKey) state.selectedNodeIds.delete(n.id);
    });

    renderNodes();
  }

  function finishMarquee() {
    dom.tempLayer.innerHTML = '';
    state.mode = 'select';
    renderNodes();
    updatePropertiesPanel();
  }

  // --- DRAG FROM LIBRARY ONTO CANVAS ---
  function setupLibraryDragAndDrop() {
    const shapeCards = document.querySelectorAll('.fc-shape-card');
    shapeCards.forEach(card => {
      card.addEventListener('dragstart', e => {
        e.dataTransfer.setData('text/plain', card.dataset.shapeType);
        e.dataTransfer.effectAllowed = 'copy';
      });
    });

    dom.canvasContainer.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });

    dom.canvasContainer.addEventListener('drop', e => {
      e.preventDefault();
      const shapeType = e.dataTransfer.getData('text/plain');
      if (!shapeType) return;

      const coords = screenToSvgCoords(e.clientX, e.clientY);
      addNode(shapeType, coords.x, coords.y);
    });
  }

  function addNode(type, x, y) {
    pushHistory();
    const w = type === 'decision' ? 170 : DEFAULT_NODE_WIDTH;
    const h = type === 'decision' ? 75 : DEFAULT_NODE_HEIGHT;

    const labels = {
      start: 'Start',
      end: 'End',
      process: 'Action Step',
      decision: 'Condition ?',
      inputoutput: 'Read / Write Data',
      document: 'Report Document',
      subroutine: 'Subroutine / Function',
      connector: 'A',
      database: 'Database Entity',
      note: 'Note / Annotation'
    };

    const strokeColors = {
      start: '#10b981',
      end: '#10b981',
      decision: '#f59e0b',
      inputoutput: '#3b82f6',
      subroutine: '#8b5cf6',
      database: '#6366f1'
    };

    const fillColors = {
      start: '#ecfdf5',
      end: '#ecfdf5',
      decision: '#fffbeb',
      inputoutput: '#eff6ff'
    };

    const newNode = {
      id: `node_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
      type: type,
      label: labels[type] || 'Step',
      x: Math.round(x - w / 2),
      y: Math.round(y - h / 2),
      width: w,
      height: h,
      style: {
        fill: fillColors[type] || '#ffffff',
        stroke: strokeColors[type] || '#3b82f6',
        strokeWidth: 2,
        textColor: '#1e293b',
        fontSize: 13,
        textAlign: 'center'
      }
    };

    state.nodes.push(newNode);
    selectNode(newNode.id, false);
    setDirty(true);
    renderDiagram();
    showToast(`Added ${capitalize(type)} shape`, 'success');
  }

  // --- CONTROL INPUTS & UI WIRING ---
  function setupControlInputs() {
    // Editable Title
    dom.titleInput.addEventListener('input', e => {
      state.title = e.target.value;
      setDirty(true);
    });

    // Save
    dom.btnSave.addEventListener('click', saveDiagramToBackend);

    // New
    dom.btnNew.addEventListener('click', () => {
      if (state.isDirty && state.nodes.length > 0) {
        showConfirmDialog(
          'Create New Diagram?',
          'Starting a new diagram will clear the canvas. Make sure to save your work first.',
          createNewDiagram
        );
      } else {
        createNewDiagram();
      }
    });

    function createNewDiagram() {
      state.diagramId = null;
      state.title = 'Untitled Flowchart';
      state.description = '';
      state.nodes = [
        { id: 'n_start', type: 'start', label: 'Start', x: 250, y: 80, width: 160, height: 70, style: { fill: '#ecfdf5', stroke: '#10b981', strokeWidth: 2, textColor: '#1e293b' } },
        { id: 'n_step', type: 'process', label: 'Action Process', x: 250, y: 220, width: 160, height: 70, style: { fill: '#ffffff', stroke: '#3b82f6', strokeWidth: 2, textColor: '#1e293b' } },
        { id: 'n_end', type: 'end', label: 'End', x: 250, y: 360, width: 160, height: 70, style: { fill: '#ecfdf5', stroke: '#10b981', strokeWidth: 2, textColor: '#1e293b' } }
      ];
      state.edges = [
        { id: 'e1', source: 'n_start', target: 'n_step', label: '', type: 'orthogonal', style: { stroke: '#64748b', strokeWidth: 2 } },
        { id: 'e2', source: 'n_step', target: 'n_end', label: '', type: 'orthogonal', style: { stroke: '#64748b', strokeWidth: 2 } }
      ];
      dom.titleInput.value = state.title;
      setDirty(false);
      renderDiagram();
      fitToScreen();
      pushHistory();
      showToast('Created new blank diagram', 'info');
    }

    // Undo / Redo
    dom.btnUndo.addEventListener('click', undo);
    dom.btnRedo.addEventListener('click', redo);

    // Zoom Buttons
    document.getElementById('fcBtnZoomIn').addEventListener('click', () => setZoom(state.viewport.zoom + 0.15));
    document.getElementById('fcBtnZoomOut').addEventListener('click', () => setZoom(state.viewport.zoom - 0.15));
    document.getElementById('fcBtnZoomFit').addEventListener('click', fitToScreen);
    document.getElementById('fcBtnZoomReset').addEventListener('click', () => setZoom(1.0));

    // Auto Arrange
    dom.btnAutoArrange.addEventListener('click', () => autoArrange(state.layout.direction || 'TB'));

    // Export Dropdown
    const exportBtn = document.getElementById('fcBtnExport');
    const exportMenu = document.getElementById('fcExportMenu');
    exportBtn.addEventListener('click', e => {
      e.stopPropagation();
      exportMenu.classList.toggle('active');
    });

    document.addEventListener('click', () => exportMenu.classList.remove('active'));

    document.getElementById('fcExportPng').addEventListener('click', () => {
      exportMenu.classList.remove('active');
      exportPng();
    });
    document.getElementById('fcExportSvg').addEventListener('click', () => {
      exportMenu.classList.remove('active');
      exportSvg();
    });
    document.getElementById('fcExportPdf').addEventListener('click', () => {
      exportMenu.classList.remove('active');
      exportPdf();
    });

    // Fullscreen Toggle
    document.getElementById('fcBtnFullscreen').addEventListener('click', () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    });

    // Panel Collapses
    document.getElementById('fcToggleLeftPanel').addEventListener('click', () => {
      document.querySelector('.fc-left-panel').classList.toggle('collapsed');
    });
    document.getElementById('fcToggleRightPanel').addEventListener('click', () => {
      dom.rightPanel.classList.toggle('collapsed');
    });

    // Left Panel Tabs
    const tabs = document.querySelectorAll('.fc-panel-tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.fc-tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        const targetId = tab.dataset.tab;
        document.getElementById(targetId).classList.add('active');
      });
    });

    // Shape Library Search
    const searchInput = document.getElementById('fcShapeSearch');
    if (searchInput) {
      searchInput.addEventListener('input', e => {
        const q = e.target.value.toLowerCase().trim();
        document.querySelectorAll('.fc-shape-card').forEach(card => {
          const name = card.querySelector('span').textContent.toLowerCase();
          card.style.display = name.includes(q) ? 'flex' : 'none';
        });
      });
    }

    // Properties Inputs - Node
    document.getElementById('fcNodeLabelInput').addEventListener('input', e => {
      if (state.selectedNodeIds.size === 1) {
        const node = state.nodes.find(n => n.id === Array.from(state.selectedNodeIds)[0]);
        if (node) {
          node.label = e.target.value;
          setDirty(true);
          renderNodes();
        }
      }
    });

    document.getElementById('fcNodeTypeSelect').addEventListener('change', e => {
      if (state.selectedNodeIds.size === 1) {
        pushHistory();
        const node = state.nodes.find(n => n.id === Array.from(state.selectedNodeIds)[0]);
        if (node) {
          node.type = e.target.value;
          setDirty(true);
          renderNodes();
          renderEdges();
          updatePropertiesPanel();
        }
      }
    });

    document.getElementById('fcNodeFontSize').addEventListener('change', e => {
      state.selectedNodeIds.forEach(nId => {
        const node = state.nodes.find(n => n.id === nId);
        if (node) {
          node.style = node.style || {};
          node.style.fontSize = parseInt(e.target.value, 10);
        }
      });
      setDirty(true);
      renderNodes();
    });

    document.getElementById('fcNodeBorderWidth').addEventListener('change', e => {
      state.selectedNodeIds.forEach(nId => {
        const node = state.nodes.find(n => n.id === nId);
        if (node) {
          node.style = node.style || {};
          node.style.strokeWidth = parseInt(e.target.value, 10);
        }
      });
      setDirty(true);
      renderNodes();
    });

    document.getElementById('fcNodeBorderStyle').addEventListener('change', e => {
      state.selectedNodeIds.forEach(nId => {
        const node = state.nodes.find(n => n.id === nId);
        if (node) {
          node.style = node.style || {};
          node.style.borderStyle = e.target.value;
        }
      });
      setDirty(true);
      renderNodes();
    });

    // Color Pickers
    document.getElementById('fcNodeFillPicker').addEventListener('input', e => {
      state.selectedNodeIds.forEach(nId => {
        const node = state.nodes.find(n => n.id === nId);
        if (node) {
          node.style = node.style || {};
          node.style.fill = e.target.value;
        }
      });
      setDirty(true);
      renderNodes();
    });

    document.getElementById('fcNodeStrokePicker').addEventListener('input', e => {
      state.selectedNodeIds.forEach(nId => {
        const node = state.nodes.find(n => n.id === nId);
        if (node) {
          node.style = node.style || {};
          node.style.stroke = e.target.value;
        }
      });
      setDirty(true);
      renderNodes();
    });

    document.getElementById('fcNodeTextPicker').addEventListener('input', e => {
      state.selectedNodeIds.forEach(nId => {
        const node = state.nodes.find(n => n.id === nId);
        if (node) {
          node.style = node.style || {};
          node.style.textColor = e.target.value;
        }
      });
      setDirty(true);
      renderNodes();
    });

    // Layer Controls
    document.getElementById('fcBtnBringForward').addEventListener('click', () => {
      if (state.selectedNodeIds.size === 1) {
        pushHistory();
        const nId = Array.from(state.selectedNodeIds)[0];
        const idx = state.nodes.findIndex(n => n.id === nId);
        if (idx !== -1 && idx < state.nodes.length - 1) {
          const [node] = state.nodes.splice(idx, 1);
          state.nodes.push(node);
          setDirty(true);
          renderNodes();
        }
      }
    });

    document.getElementById('fcBtnSendBackward').addEventListener('click', () => {
      if (state.selectedNodeIds.size === 1) {
        pushHistory();
        const nId = Array.from(state.selectedNodeIds)[0];
        const idx = state.nodes.findIndex(n => n.id === nId);
        if (idx > 0) {
          const [node] = state.nodes.splice(idx, 1);
          state.nodes.unshift(node);
          setDirty(true);
          renderNodes();
        }
      }
    });

    document.getElementById('fcBtnDuplicateNode').addEventListener('click', duplicateSelected);
    document.getElementById('fcBtnDeleteNode').addEventListener('click', deleteSelected);

    // Edge Properties
    document.getElementById('fcEdgeLabelInput').addEventListener('input', e => {
      if (state.selectedEdgeId) {
        const edge = state.edges.find(ed => ed.id === state.selectedEdgeId);
        if (edge) {
          edge.label = e.target.value;
          setDirty(true);
          renderEdges();
        }
      }
    });

    document.getElementById('fcEdgeRouteSelect').addEventListener('change', e => {
      if (state.selectedEdgeId) {
        pushHistory();
        const edge = state.edges.find(ed => ed.id === state.selectedEdgeId);
        if (edge) {
          edge.type = e.target.value;
          setDirty(true);
          renderEdges();
        }
      }
    });

    document.getElementById('fcEdgeStrokePicker').addEventListener('input', e => {
      if (state.selectedEdgeId) {
        const edge = state.edges.find(ed => ed.id === state.selectedEdgeId);
        if (edge) {
          edge.style = edge.style || {};
          edge.style.stroke = e.target.value;
          setDirty(true);
          renderEdges();
        }
      }
    });

    document.getElementById('fcEdgeWidthInput').addEventListener('change', e => {
      if (state.selectedEdgeId) {
        const edge = state.edges.find(ed => ed.id === state.selectedEdgeId);
        if (edge) {
          edge.style = edge.style || {};
          edge.style.strokeWidth = parseInt(e.target.value, 10);
          setDirty(true);
          renderEdges();
        }
      }
    });

    document.getElementById('fcBtnDeleteEdge').addEventListener('click', deleteSelected);

    // Edge Source / Target Port overrides
    const edgeSrcPortSelect = document.getElementById('fcEdgeSourcePortSelect');
    if (edgeSrcPortSelect) {
      edgeSrcPortSelect.addEventListener('change', e => {
        if (state.selectedEdgeId) {
          pushHistory();
          const edge = state.edges.find(ed => ed.id === state.selectedEdgeId);
          if (edge) {
            edge.sourcePort = (!e.target.value || e.target.value === 'auto') ? null : e.target.value;
            setDirty(true);
            renderEdges();
            updatePropertiesPanel();
          }
        }
      });
    }

    const edgeTgtPortSelect = document.getElementById('fcEdgeTargetPortSelect');
    if (edgeTgtPortSelect) {
      edgeTgtPortSelect.addEventListener('change', e => {
        if (state.selectedEdgeId) {
          pushHistory();
          const edge = state.edges.find(ed => ed.id === state.selectedEdgeId);
          if (edge) {
            edge.targetPort = (!e.target.value || e.target.value === 'auto') ? null : e.target.value;
            setDirty(true);
            renderEdges();
            updatePropertiesPanel();
          }
        }
      });
    }

    // Add Bend Point at edge midpoint
    const btnAddBendPoint = document.getElementById('fcBtnAddBendPoint');
    if (btnAddBendPoint) {
      btnAddBendPoint.addEventListener('click', () => {
        if (state.selectedEdgeId) {
          const edge = state.edges.find(ed => ed.id === state.selectedEdgeId);
          if (edge) {
            const srcNode = state.nodes.find(n => n.id === edge.source);
            const tgtNode = state.nodes.find(n => n.id === edge.target);
            if (!srcNode || !tgtNode) return;

            pushHistory();
            edge.points = edge.points || [];

            const ports = getBestPorts(srcNode, tgtNode);
            const sPort = edge.sourcePort || ports.srcPort;
            const tPort = edge.targetPort || ports.tgtPort;
            const srcPt = getPortAbsoluteCoordinate(edge.source, sPort);
            const tgtPt = getPortAbsoluteCoordinate(edge.target, tPort);

            const mid = getEdgeMidpoint(srcPt, tgtPt, edge.type || 'orthogonal', edge.points, sPort, tPort);
            const snap = (state.layout.grid === 'lines' || state.layout.grid === 'dots') ? (state.layout.gridSize / 2) : 10;
            const newPt = {
              x: Math.round(mid.x / snap) * snap,
              y: Math.round(mid.y / snap) * snap
            };

            const insertIdx = findBestPointInsertIndex(edge, newPt.x, newPt.y);
            edge.points.splice(insertIdx, 0, newPt);

            setDirty(true);
            renderEdges();
            updatePropertiesPanel();
            showToast('Added bend point. Drag handle on canvas to reposition.', 'info');
          }
        }
      });
    }

    // Reset Edge Route to default
    const btnResetRoute = document.getElementById('fcBtnResetEdgeRoute');
    if (btnResetRoute) {
      btnResetRoute.addEventListener('click', () => {
        if (state.selectedEdgeId) {
          const edge = state.edges.find(ed => ed.id === state.selectedEdgeId);
          if (edge) {
            pushHistory();
            edge.points = [];
            setDirty(true);
            renderEdges();
            updatePropertiesPanel();
            showToast('Reset edge route to automatic', 'info');
          }
        }
      });
    }

    // Canvas Properties
    document.getElementById('fcCanvasDirection').addEventListener('change', e => {
      autoArrange(e.target.value);
    });

    document.getElementById('fcCanvasGridType').addEventListener('change', e => {
      state.layout.grid = e.target.value;
      renderGrid();
    });

    // Modals Launchers
    document.getElementById('fcBtnOpenCodeModal').addEventListener('click', () => openModal(dom.codeModal));
    document.getElementById('fcBtnOpenAiModal').addEventListener('click', () => openModal(dom.aiModal));

    // Modal Close Buttons
    document.querySelectorAll('.fc-modal-close').forEach(btn => {
      btn.addEventListener('click', e => {
        const modal = e.target.closest('.fc-modal-backdrop');
        if (modal) closeModal(modal);
      });
    });

    // Generate Code Button
    document.getElementById('fcBtnGenerateCode').addEventListener('click', generateFromCode);

    // Generate AI Button
    document.getElementById('fcBtnGenerateAi').addEventListener('click', generateFromAi);
  }

  function openModal(modal) {
    if (modal) modal.classList.add('active');
  }

  function closeModal(modal) {
    if (modal) modal.classList.remove('active');
  }

  function showConfirmDialog(title, message, onConfirm) {
    const modal = dom.confirmModal;
    document.getElementById('fcConfirmTitle').textContent = title;
    document.getElementById('fcConfirmMessage').textContent = message;

    const btnConfirm = document.getElementById('fcBtnConfirmAction');
    const newBtn = btnConfirm.cloneNode(true);
    btnConfirm.parentNode.replaceChild(newBtn, btnConfirm);

    newBtn.addEventListener('click', () => {
      closeModal(modal);
      if (typeof onConfirm === 'function') onConfirm();
    });

    openModal(modal);
  }

  // --- TOAST NOTIFICATIONS ---
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `fc-toast ${type}`;
    let icon = 'info-circle';
    if (type === 'success') icon = 'circle-check';
    if (type === 'error') icon = 'triangle-exclamation';
    if (type === 'warning') icon = 'circle-exclamation';

    toast.innerHTML = `<i class="fa-solid fa-${icon}"></i> <span>${escapeXml(message)}</span>`;
    dom.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.25s ease';
      setTimeout(() => toast.remove(), 250);
    }, 3200);
  }

  function updateUIState() {
    dom.titleInput.value = state.title;
    setDirty(false);
  }

  // --- EXPOSE GLOBAL API FOR BUTTONS & MODALS ---
  window.fcApp = {
    loadTemplate,
    openDiagram: loadDiagramFromBackend,
    duplicateDiagram: async function (id) {
      try {
        const res = await fetch(`/api/flowchart/duplicate/${id}`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (res.ok && data.success) {
          setupSavedDiagramsList();
          showToast('Diagram duplicated', 'success');
        }
      } catch (e) {
        showToast('Error duplicating diagram', 'error');
      }
    },
    deleteDiagram: function (id) {
      showConfirmDialog(
        'Delete Flowchart?',
        'Are you sure you want to permanently delete this saved diagram? This action cannot be undone.',
        async () => {
          try {
            const res = await fetch(`/api/flowchart/${id}`, {
              method: 'DELETE',
              headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            if (res.ok && data.success) {
              if (state.diagramId === id) {
                state.diagramId = null;
              }
              setupSavedDiagramsList();
              showToast('Diagram deleted successfully', 'success');
            }
          } catch (e) {
            showToast('Error deleting diagram', 'error');
          }
        }
      );
    },
    insertSampleCode: function (type) {
      const lang = document.getElementById('fcCodeLanguage').value;
      const editor = document.getElementById('fcCodeTextarea');
      if (lang === 'python') {
        if (type === 'condition') {
          editor.value = "score = int(input('Enter score: '))\nif score >= 50:\n    print('Passed')\nelse:\n    print('Failed')";
        } else if (type === 'loop') {
          editor.value = "total = 0\nfor i in range(1, 11):\n    total += i\nprint('Sum is', total)";
        } else if (type === 'function') {
          editor.value = "def calculate_discount(price, is_member):\n    if is_member:\n        discount = price * 0.2\n    else:\n        discount = 0\n    return price - discount";
        }
      } else {
        if (type === 'condition') {
          editor.value = "int score = 85;\nif (score >= 50) {\n    System.out.println(\"Passed\");\n} else {\n    System.out.println(\"Failed\");\n}";
        } else if (type === 'loop') {
          editor.value = "int sum = 0;\nfor (int i = 0; i < 10; i++) {\n    sum += i;\n}\nSystem.out.println(sum);";
        } else if (type === 'function') {
          editor.value = "int x = 15;\nwhile (x > 0) {\n    x -= 2;\n}\nreturn x;";
        }
      }
    },
    insertSampleAiPrompt: function (promptText) {
      document.getElementById('fcAiPromptInput').value = promptText;
    }
  };

  // Launch application
  window.addEventListener('DOMContentLoaded', init);
})();
