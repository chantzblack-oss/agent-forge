(function () {
  "use strict";

  const DATA_URL = "../wonderlab_money_episode.json";
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const state = {
    run: null,
    claimById: new Map(),
    sourceById: new Map(),
  };

  const els = {
    runMeta: document.getElementById("runMeta"),
    sceneNav: document.getElementById("sceneNav"),
    studioTrack: document.getElementById("studioTrack"),
    sceneStack: document.getElementById("sceneStack"),
    title: document.getElementById("episodeTitle"),
    subtitle: document.getElementById("episodeSubtitle"),
    artifactLine: document.getElementById("artifactLine"),
    drawer: document.getElementById("sourceDrawer"),
    openSources: document.getElementById("openSources"),
    closeSources: document.getElementById("closeSources"),
    studioDrawer: document.getElementById("studioDrawer"),
    openStudio: document.getElementById("openStudio"),
    closeStudio: document.getElementById("closeStudio"),
    studioForm: document.getElementById("studioForm"),
    studioStatus: document.getElementById("studioStatus"),
    publishGate: document.getElementById("publishGate"),
    studioDossier: document.getElementById("studioDossier"),
    focusBlockers: document.getElementById("focusBlockers"),
    downloadArtifact: document.getElementById("downloadArtifact"),
    claimsPanel: document.getElementById("claimsPanel"),
    sourcesPanel: document.getElementById("sourcesPanel"),
    evalPanel: document.getElementById("evalPanel"),
    canvas: document.getElementById("heroCanvas"),
  };

  init();

  async function init() {
    const run = await loadRun();
    state.run = run;
    state.claimById = new Map(run.episode.claim_ledger.map((claim) => [claim.id, claim]));
    state.sourceById = new Map(run.episode.source_graph.map((source) => [source.id, source]));

    renderShell(run);
    renderScenes(run);
    renderDrawer(run);
    renderStudio(run);
    wireDrawer();
    wireStudio();
    startHeroCanvas();
  }

  async function loadRun() {
    const response = await fetch(DATA_URL);
    if (!response.ok) {
      throw new Error("Could not load Wonderlab episode artifact.");
    }
    return response.json();
  }

  function renderShell(run) {
    const episode = run.episode;
    els.title.textContent = episode.title;
    els.subtitle.textContent = episode.subtitle;
    els.artifactLine.textContent = `${run.run_id} / ${run.mode} mode`;

    const counts = [
      ["Scenes", episode.scenes.length],
      ["Claims", episode.claim_ledger.length],
      ["Sources", episode.source_graph.length],
      ["Verified", episode.source_graph.filter((source) => isVerifiedStatus(source.verification_status)).length],
      ["Disputes", episode.disagreements.length],
    ];
    els.runMeta.innerHTML = counts
      .map(([label, value]) => `<div class="metric-row"><span>${label}</span><strong>${value}</strong></div>`)
      .join("");

    els.sceneNav.innerHTML = episode.scenes
      .map((scene, index) => {
        const number = String(index + 1).padStart(2, "0");
        return `<a class="scene-link" href="#${scene.id}"><span>${number}</span><span>${escapeHtml(scene.title)}</span></a>`;
      })
      .join("");

    els.studioTrack.innerHTML = run.stages
      .map((stage) => {
        return `
          <article class="stage-tile">
            <strong>${escapeHtml(stage.agent_role)}</strong>
            <p>${escapeHtml(stage.summary)}</p>
          </article>
        `;
      })
      .join("");
  }

  function renderScenes(run) {
    els.sceneStack.innerHTML = run.episode.scenes.map((scene) => renderScene(scene, run)).join("");
    wireSimulators();
    wireChallenge();
  }

  function renderScene(scene, run) {
    const claims = scene.claims_used
      .map((id) => state.claimById.get(id))
      .filter(Boolean);
    const claimChips = claims
      .map((claim) => {
        return `<button class="claim-chip" type="button" data-open-source="${claim.id}">${escapeHtml(shortId(claim.id))}</button>`;
      })
      .join("");

    return `
      <section class="episode-scene" id="${scene.id}">
        <div class="scene-copy">
          <div class="scene-type">${formatSceneType(scene.scene_type)}</div>
          <h2>${escapeHtml(scene.title)}</h2>
          <p class="hook">${escapeHtml(scene.hook)}</p>
          <div class="narration">
            ${scene.narration.map((text) => `<p>${escapeHtml(text)}</p>`).join("")}
          </div>
          <div class="claim-row">${claimChips}</div>
        </div>
        <div class="scene-visual">
          ${renderVisual(scene, run)}
        </div>
      </section>
    `;
  }

  function renderVisual(scene, run) {
    if (scene.interaction) {
      return renderSimulator(scene);
    }
    if (scene.scene_type === "timeline") {
      return renderTimeline(run);
    }
    if (scene.scene_type === "systems-diagram") {
      return renderBalanceSheet();
    }
    if (scene.scene_type === "debate") {
      return renderDebate(scene, run);
    }
    if (scene.scene_type === "source-gallery") {
      return `<div class="visual-inner source-gallery">${renderSourceTiles(run.episode.source_graph)}</div>`;
    }
    if (scene.scene_type === "synthesis-challenge") {
      return renderChallenge();
    }
    if (scene.id === "scene-intro" || scene.id === "scene-debt-ledgers") {
      return renderLedgerWall(scene);
    }
    return renderAbstractStage(scene);
  }

  function renderSimulator(scene) {
    const variables = scene.interaction.variables;
    const sliders = variables
      .map((variable) => {
        const step = sliderStep(variable.min, variable.max);
        return `
          <div class="slider-row">
            <label for="${scene.id}-${variable.id}">${escapeHtml(variable.label)}</label>
            <input
              id="${scene.id}-${variable.id}"
              type="range"
              min="${variable.min}"
              max="${variable.max}"
              value="${variable.default}"
              step="${step}"
              data-sim="${scene.interaction.type}"
              data-var="${variable.id}"
              data-scene="${scene.id}"
            >
            <span class="slider-value" id="${scene.id}-${variable.id}-value">${formatNumber(variable.default)}</span>
          </div>
        `;
      })
      .join("");

    return `
      <div class="simulator" data-sim-root="${scene.id}" data-sim-type="${scene.interaction.type}">
        <div class="sim-output" aria-live="polite">
          <div>
            <div class="output-label" id="${scene.id}-label">${escapeHtml(scene.interaction.outputs.label)}</div>
            <div class="output-value" id="${scene.id}-value">${escapeHtml(String(scene.interaction.outputs.value))}</div>
            <div class="output-label" id="${scene.id}-unit">${escapeHtml(scene.interaction.outputs.unit)}</div>
            <p class="output-explain" id="${scene.id}-explain">${escapeHtml(scene.interaction.outputs.explanation)}</p>
          </div>
        </div>
        <div class="slider-grid">${sliders}</div>
        <p class="sim-reveal">${escapeHtml(scene.interaction.learning_reveal)}</p>
      </div>
    `;
  }

  function wireSimulators() {
    document.querySelectorAll("[data-sim-root]").forEach((root) => {
      updateSimulation(root);
      root.querySelectorAll("input[type='range']").forEach((input) => {
        input.addEventListener("input", () => {
          const valueEl = document.getElementById(`${input.id}-value`);
          if (valueEl) valueEl.textContent = formatNumber(Number(input.value));
          updateSimulation(root);
        });
      });
    });
  }

  function updateSimulation(root) {
    const sceneId = root.dataset.simRoot;
    const type = root.dataset.simType;
    const values = {};
    root.querySelectorAll("input[type='range']").forEach((input) => {
      values[input.dataset.var] = Number(input.value);
    });

    let result;
    if (type === "barter-mini-game") {
      const sizeScore = clamp((values.market_size - 2) / 98, 0, 1);
      result = {
        label: "Trade success",
        value: `${formatNumber((0.48 * values.wants_overlap + 0.32 * values.trust + 0.20 * sizeScore) * 100)}%`,
        unit: "clearing probability",
        explanation: "Trade clears when wants overlap, trust holds, and the market has enough possible paths.",
      };
    } else if (type === "bank-run-model") {
      const days = values.reserve_ratio / Math.max(0.01, values.daily_withdrawal_rate * (1 + values.confidence_shock));
      result = {
        label: "Reserve runway",
        value: formatNumber(days),
        unit: "days",
        explanation: "Liquid reserves buy time; a confidence shock spends that time faster.",
      };
    } else {
      const pressure =
        values.money_growth -
        values.goods_growth +
        0.65 * values.velocity_change +
        0.85 * values.expectations_shock;
      result = {
        label: "Inflation pressure",
        value: formatNumber(pressure),
        unit: "index",
        explanation: "The pressure rises when money, spending speed, and expectations outrun goods supply.",
      };
    }

    setText(`${sceneId}-label`, result.label);
    setText(`${sceneId}-value`, result.value);
    setText(`${sceneId}-unit`, result.unit);
    setText(`${sceneId}-explain`, result.explanation);
  }

  function renderTimeline(run) {
    const events = run.dossier.timeline
      .map((event) => {
        return `
          <div class="timeline-event">
            <strong>${escapeHtml(event.period)}</strong>
            <div>
              <h3>${escapeHtml(event.label)}</h3>
              <p>${escapeHtml(event.description)}</p>
            </div>
          </div>
        `;
      })
      .join("");
    return `<div class="visual-inner timeline-visual">${events}</div>`;
  }

  function renderBalanceSheet() {
    return `
      <div class="visual-inner balance-sheet">
        <div class="balance-column">
          <h3>Assets</h3>
          <div class="balance-entry"><span>Loan to borrower</span><span>+100</span></div>
          <div class="balance-entry"><span>Reserves</span><span>+12</span></div>
          <div class="balance-entry"><span>Long-term securities</span><span>+58</span></div>
        </div>
        <div class="balance-column">
          <h3>Liabilities</h3>
          <div class="balance-entry"><span>New deposit</span><span>+100</span></div>
          <div class="balance-entry"><span>Customer withdrawals</span><span>-8/day</span></div>
          <div class="balance-entry"><span>Trust buffer</span><span>fragile</span></div>
        </div>
      </div>
    `;
  }

  function renderDebate(scene, run) {
    const claimSet = new Set(scene.claims_used);
    const disputes = run.episode.disagreements.filter((item) => claimSet.has(item.claim_id));

    if (!disputes.length) {
      return `
        <div class="debate-board">
          <div class="position-row"><strong>Institutional trust</strong><p>Courts, regulators, banks, and states stabilize money by making obligations enforceable.</p></div>
          <div class="position-row"><strong>Protocol trust</strong><p>Code, incentives, and network consensus can move trust away from legacy institutions.</p></div>
          <div class="resolution"><strong>Resolution</strong><p>Trust moves. It does not disappear.</p></div>
        </div>
      `;
    }

    const rows = disputes
      .flatMap((dispute) => dispute.model_positions.map((position) => ({ dispute, position })))
      .map(({ dispute, position }) => {
        return `
          <div class="position-row">
            <strong>${escapeHtml(position.model)} / ${escapeHtml(dispute.disagreement_type)}</strong>
            <p>${escapeHtml(position.position)}</p>
          </div>
        `;
      })
      .join("");
    const resolutions = disputes
      .map((dispute) => `<div class="resolution"><strong>${escapeHtml(dispute.resolution)}</strong><p>${escapeHtml(dispute.summary)}</p></div>`)
      .join("");
    return `<div class="debate-board">${rows}${resolutions}</div>`;
  }

  function renderSourceTiles(sources) {
    return sources
      .map((source) => {
        const href = source.url ? `<a class="source-chip" href="${escapeAttr(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.publisher || "Source")}</a>` : "";
        const status = source.verification_status || "unknown";
        const excerpt = source.verification_excerpt
          ? `<p class="verification-excerpt">${escapeHtml(source.verification_excerpt)}</p>`
          : "";
        const error = source.verification_error
          ? `<p class="verification-error">${escapeHtml(source.verification_error)}</p>`
          : "";
        return `
          <article class="source-tile">
            <span class="status-pill ${statusClass(status)}">${escapeHtml(statusLabel(status))}</span>
            <h3>${escapeHtml(source.title)}</h3>
            <p>${escapeHtml([source.publisher, source.year].filter(Boolean).join(" / "))}</p>
            <p>${escapeHtml(source.notes)}</p>
            ${excerpt}
            ${error}
            ${href}
          </article>
        `;
      })
      .join("");
  }

  function renderLedgerWall(scene) {
    const entries = [
      "ledger: trust",
      "unit: account",
      "store: value",
      "medium: exchange",
      "debt: memory",
      "state: tax",
      "bank: deposit",
      "protocol: consensus",
      "risk: panic",
      "shock: prices",
      "claim: audited",
      "source: pending",
    ];
    return `
      <div class="visual-inner ledger-wall" aria-label="${escapeAttr(scene.visual_direction)}">
        ${entries.map((entry) => `<div class="ledger-cell">${entry}</div>`).join("")}
      </div>
    `;
  }

  function renderAbstractStage(scene) {
    return `
      <div class="visual-inner ledger-wall" aria-label="${escapeAttr(scene.visual_direction)}">
        <div class="ledger-cell">scene</div>
        <div class="ledger-cell">${escapeHtml(scene.scene_type)}</div>
        <div class="ledger-cell">claims</div>
        <div class="ledger-cell">${scene.claims_used.length}</div>
        <div class="ledger-cell">sources</div>
        <div class="ledger-cell">${scene.source_refs.length}</div>
        <div class="ledger-cell">time</div>
        <div class="ledger-cell">${scene.estimated_reading_time_seconds}s</div>
      </div>
    `;
  }

  function renderChallenge() {
    const options = [
      ["Liquidity", "Can people spend it when pressure hits?"],
      ["Authority", "Who settles disputes and reverses damage?"],
      ["Scarcity", "Who controls supply and issuance?"],
      ["Consensus", "Why does anyone else accept it?"],
    ];
    return `
      <div class="visual-inner challenge-board">
        ${options
          .map(([label, copy], index) => {
            const active = index === 0 ? " active" : "";
            return `<button class="challenge-choice${active}" type="button"><span>${label}</span>${copy}</button>`;
          })
          .join("")}
      </div>
    `;
  }

  function wireChallenge() {
    document.querySelectorAll(".challenge-choice").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".challenge-choice").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
      });
    });
  }

  function renderDrawer(run) {
    els.claimsPanel.innerHTML = run.episode.claim_ledger
      .map((claim) => {
        const sourceChips = claim.sources
          .map((sourceId) => state.sourceById.get(sourceId))
          .filter(Boolean)
          .map((source) => {
            const status = source.verification_status || "unknown";
            return `
              <span class="source-chip">
                ${escapeHtml(source.title)}
                <span class="mini-status ${statusClass(status)}">${escapeHtml(statusLabel(status))}</span>
              </span>
            `;
          })
          .join("");
        const evidenceRows = (claim.evidence || [])
          .map((evidence) => {
            const source = state.sourceById.get(evidence.source_id);
            const status = evidence.verification_status || source?.verification_status || "seeded";
            const quote = evidence.quote
              ? `<blockquote>${escapeHtml(evidence.quote)}</blockquote>`
              : "";
            const locator = evidence.locator
              ? `<span class="evidence-locator">${escapeHtml(evidence.locator)}</span>`
              : "";
            return `
              <div class="evidence-row">
                <div class="evidence-source">
                  <strong>${escapeHtml(source?.title || evidence.source_id)}</strong>
                  <span class="mini-status ${statusClass(status)}">${escapeHtml(statusLabel(status))}</span>
                </div>
                <p>${escapeHtml(evidence.summary)}</p>
                ${quote}
                ${locator}
              </div>
            `;
          })
          .join("");
        return `
          <article class="claim-card" id="drawer-${claim.id}">
            <span class="confidence-pill ${claim.confidence}">${escapeHtml(claim.confidence)}</span>
            <p>${escapeHtml(claim.text)}</p>
            <div class="evidence-stack">${evidenceRows}</div>
            <footer>${sourceChips}</footer>
          </article>
        `;
      })
      .join("");

    els.sourcesPanel.innerHTML = renderSourceTiles(run.episode.source_graph);

    const evalEntries = Object.entries(run.eval_report).filter(([, value]) => typeof value === "number");
    const meters = evalEntries
      .map(([key, value]) => {
        return `
          <div class="eval-meter">
            <span>${formatMetric(key)}</span>
            <span class="meter-track"><span class="meter-fill" style="width: ${value}%"></span></span>
            <strong>${value}</strong>
          </div>
        `;
      })
      .join("");
    const fixes = run.eval_report.required_fixes.map((fix) => `<p>${escapeHtml(fix)}</p>`).join("");
    els.evalPanel.innerHTML = `
      <div class="eval-grid">${meters}</div>
      <article class="claim-card">
        <span class="confidence-pill medium">${escapeHtml(run.eval_report.publish_decision)}</span>
        ${fixes}
      </article>
    `;
  }

  function wireDrawer() {
    els.openSources.addEventListener("click", () => openDrawer());
    els.closeSources.addEventListener("click", () => closeDrawer());

    document.querySelectorAll(".drawer-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".drawer-tab").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".drawer-panel").forEach((item) => item.classList.remove("active"));
        tab.classList.add("active");
        document.getElementById(`${tab.dataset.tab}Panel`).classList.add("active");
      });
    });

    document.addEventListener("click", (event) => {
      const target = event.target.closest("[data-open-source]");
      if (!target) return;
      openDrawer();
      showDrawerTab("claims");
      const claim = document.getElementById(`drawer-${target.dataset.openSource}`);
      if (claim) claim.scrollIntoView({ block: "center" });
    });
  }

  function renderStudio(run) {
    const episode = run.episode;
    const evalReport = run.eval_report;
    const verified = episode.source_graph.filter((source) => isVerifiedStatus(source.verification_status)).length;
    const evidenceRows = episode.claim_ledger.reduce((total, claim) => total + (claim.evidence || []).length, 0);
    const blockers = evalReport.required_fixes || [];

    els.studioStatus.innerHTML = `
      <div class="run-progress" id="runProgress">
        ${run.stages.map((stage, index) => renderStageStep(stage, index, true)).join("")}
      </div>
    `;

    els.publishGate.innerHTML = `
      <article class="gate-card ${evalReport.publish_decision}">
        <div>
          <p class="eyebrow">Publish Gate</p>
          <h3>${escapeHtml(statusLabel(evalReport.publish_decision))}</h3>
        </div>
        <div class="gate-metrics">
          <span><strong>${verified}/${episode.source_graph.length}</strong> verified sources</span>
          <span><strong>${evidenceRows}</strong> evidence links</span>
          <span><strong>${evalReport.citation_coverage}%</strong> citation coverage</span>
        </div>
      </article>
      <div class="blocker-list" id="blockerList">
        ${blockers.length ? blockers.map((fix) => `<p>${escapeHtml(fix)}</p>`).join("") : "<p>No publish blockers.</p>"}
      </div>
    `;

    els.studioDossier.innerHTML = `
      <div class="studio-section-head">
        <p class="eyebrow">Dossier Preview</p>
        <h3>${escapeHtml(episode.central_mystery)}</h3>
      </div>
      <div class="dossier-grid">
        <article>
          <strong>Key Questions</strong>
          ${run.dossier.key_questions.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
        </article>
        <article>
          <strong>Scene Plan</strong>
          ${episode.scenes.map((scene, index) => `<p>${String(index + 1).padStart(2, "0")} / ${escapeHtml(scene.title)}</p>`).join("")}
        </article>
        <article>
          <strong>Misconceptions</strong>
          ${run.dossier.misconceptions.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
        </article>
        <article>
          <strong>Controversies</strong>
          ${run.dossier.controversies.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
        </article>
      </div>
    `;
  }

  function renderStageStep(stage, index, complete) {
    const number = String(index + 1).padStart(2, "0");
    const state = complete ? "complete" : "pending";
    return `
      <article class="run-step ${state}" data-stage-index="${index}">
        <span>${number}</span>
        <div>
          <strong>${escapeHtml(stage.stage)}</strong>
          <p>${escapeHtml(stage.summary)}</p>
        </div>
      </article>
    `;
  }

  function wireStudio() {
    if (!els.openStudio) return;
    els.openStudio.addEventListener("click", () => openStudio());
    els.closeStudio.addEventListener("click", () => closeStudio());
    els.focusBlockers.addEventListener("click", () => {
      openStudio();
      document.getElementById("blockerList")?.scrollIntoView({ block: "center" });
    });
    els.downloadArtifact.addEventListener("click", () => {
      const payload = JSON.stringify(state.run, null, 2);
      const blob = new Blob([payload], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${state.run.episode.id}.json`;
      link.click();
      URL.revokeObjectURL(url);
    });
    els.studioForm.addEventListener("submit", (event) => {
      event.preventDefault();
      simulateStudioRun(new FormData(els.studioForm));
    });
  }

  function openStudio() {
    els.studioDrawer.classList.add("open");
  }

  function closeStudio() {
    els.studioDrawer.classList.remove("open");
  }

  function simulateStudioRun(formData) {
    const topic = String(formData.get("topic") || state.run.episode.title).trim();
    const mode = String(formData.get("mode") || state.run.mode);
    const stages = state.run.stages.map((stage) => ({
      ...stage,
      summary: stage.stage === "topic-intake"
        ? `Accepted topic: ${topic}. Mode set to ${mode}.`
        : stage.summary,
    }));

    els.studioStatus.innerHTML = `
      <div class="run-progress" id="runProgress">
        ${stages.map((stage, index) => renderStageStep(stage, index, false)).join("")}
      </div>
    `;
    openStudio();

    const steps = Array.from(document.querySelectorAll("#runProgress .run-step"));
    steps.forEach((step, index) => {
      setTimeout(() => {
        step.classList.remove("pending");
        step.classList.add("complete");
      }, reducedMotion ? 0 : 280 * (index + 1));
    });
  }

  function openDrawer() {
    els.drawer.classList.add("open");
  }

  function closeDrawer() {
    els.drawer.classList.remove("open");
  }

  function showDrawerTab(name) {
    document.querySelectorAll(".drawer-tab").forEach((item) => item.classList.toggle("active", item.dataset.tab === name));
    document.querySelectorAll(".drawer-panel").forEach((item) => item.classList.toggle("active", item.id === `${name}Panel`));
  }

  function startHeroCanvas() {
    const canvas = els.canvas;
    const ctx = canvas.getContext("2d");
    let width = 0;
    let height = 0;
    let frame = 0;

    const nodes = Array.from({ length: 34 }, (_, index) => ({
      x: Math.random(),
      y: Math.random(),
      r: 2 + Math.random() * 4,
      phase: Math.random() * Math.PI * 2,
      kind: index % 4,
    }));

    function resize() {
      const ratio = window.devicePixelRatio || 1;
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    function draw() {
      frame += reducedMotion ? 0 : 0.012;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#111417";
      ctx.fillRect(0, 0, width, height);

      drawGrid(ctx, width, height, frame);
      drawLinks(ctx, nodes, width, height, frame);
      drawNodes(ctx, nodes, width, height, frame);
      if (!reducedMotion) requestAnimationFrame(draw);
    }

    resize();
    draw();
    window.addEventListener("resize", () => {
      resize();
      if (reducedMotion) draw();
    });
  }

  function drawGrid(ctx, width, height, frame) {
    ctx.save();
    ctx.globalAlpha = 0.26;
    ctx.strokeStyle = "#d9ad58";
    ctx.lineWidth = 1;
    const gap = 72;
    for (let x = -gap; x < width + gap; x += gap) {
      ctx.beginPath();
      ctx.moveTo(x + Math.sin(frame + x * 0.01) * 4, 0);
      ctx.lineTo(x - 60, height);
      ctx.stroke();
    }
    ctx.strokeStyle = "#62d2c2";
    ctx.globalAlpha = 0.16;
    for (let y = 0; y < height; y += gap) {
      ctx.beginPath();
      ctx.moveTo(0, y + Math.cos(frame + y * 0.01) * 3);
      ctx.lineTo(width, y - 40);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawLinks(ctx, nodes, width, height, frame) {
    ctx.save();
    ctx.lineWidth = 1;
    nodes.forEach((node, index) => {
      const next = nodes[(index + 5) % nodes.length];
      const ax = node.x * width;
      const ay = node.y * height + Math.sin(frame + node.phase) * 18;
      const bx = next.x * width;
      const by = next.y * height + Math.cos(frame + next.phase) * 18;
      ctx.globalAlpha = 0.16;
      ctx.strokeStyle = index % 3 === 0 ? "#62d2c2" : "#d9ad58";
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.stroke();
    });
    ctx.restore();
  }

  function drawNodes(ctx, nodes, width, height, frame) {
    ctx.save();
    nodes.forEach((node) => {
      const x = node.x * width;
      const y = node.y * height + Math.sin(frame + node.phase) * 18;
      ctx.globalAlpha = 0.72;
      ctx.fillStyle = ["#d9ad58", "#62d2c2", "#d86f6f", "#8fb4d8"][node.kind];
      ctx.beginPath();
      ctx.arc(x, y, node.r, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.restore();
  }

  function sliderStep(min, max) {
    if (max - min <= 1) return 0.01;
    if (max - min <= 2) return 0.05;
    return 1;
  }

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function formatNumber(value) {
    if (Math.abs(value) >= 10) return Number(value).toFixed(0);
    return Number(value).toFixed(2).replace(/\.?0+$/, "");
  }

  function formatSceneType(value) {
    return value.replaceAll("-", " ");
  }

  function formatMetric(value) {
    return value.replace(/_/g, " ");
  }

  function statusClass(value) {
    return `status-${String(value).replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
  }

  function isVerifiedStatus(value) {
    return ["verified", "verified-pdf", "verified-manual"].includes(value);
  }

  function statusLabel(value) {
    const labels = {
      "verified": "Verified",
      "verified-pdf": "Verified PDF",
      "verified-manual": "Verified manual",
      "manual-packet": "Manual packet",
      "human-review": "Human review",
      "seeded-not-fetched": "Seeded",
      "needs-human-review": "Human review",
      "access-blocked": "Access blocked",
      "fetch-error": "Fetch error",
      "not-found": "Not found",
      "reachable-title-mismatch": "Mismatch",
    };
    return labels[value] || value;
  }

  function shortId(value) {
    return value.replace(/^claim-/, "").replaceAll("-", " ");
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }
})();
