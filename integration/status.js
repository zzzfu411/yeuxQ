(function statusProjectionModule(globalScope) {
  "use strict";

  const STATUS_SOURCE = "./integration_status.json";
  const SUPPORTED_SCHEMA = "1.0.0";
  const MAX_STATUS_BYTES = 1024 * 1024;
  const REFRESH_INTERVAL_MS = 60_000;

  const STATUS_ENUMS = Object.freeze({
    overall: Object.freeze(["not_started", "in_progress", "completed", "blocked"]),
    phase: Object.freeze(["not_started", "in_progress", "completed", "blocked"]),
    readiness: Object.freeze(["PASS", "WATCH", "BLOCK"]),
    risk: Object.freeze(["open", "mitigated", "closed"]),
    priority: Object.freeze(["P0", "P1"]),
    verification: Object.freeze(["PASS", "WATCH", "BLOCK", "NOT_RUN"]),
    frontendAvailability: Object.freeze([
      "file_only",
      "static_read_only_projection",
      "api_and_static_projection",
    ]),
    observationBoundary: Object.freeze([
      "not_started",
      "contract_completed",
      "implemented",
      "verified",
      "blocked",
    ]),
    researchBoundary: Object.freeze([
      "canonical_existing_core",
      "integrating",
      "verified",
      "blocked",
    ]),
  });

  const STATUS_LABELS = Object.freeze({
    not_started: "NOT STARTED",
    in_progress: "IN PROGRESS",
    completed: "COMPLETED",
    blocked: "BLOCKED",
    open: "OPEN",
    mitigated: "MITIGATED",
    closed: "CLOSED",
  });

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function validateStatusPayload(payload) {
    const errors = [];

    if (!isRecord(payload)) {
      return { ok: false, errors: ["root 必须是 JSON 对象"] };
    }

    requireExactString(payload, "schema_version", SUPPORTED_SCHEMA, errors, "root");
    requireIsoDateTime(payload, "updated_at", errors, "root");

    const project = requireRecord(payload, "project", errors, "root");
    if (project) {
      requireString(project, "name", errors, "project");
      requireString(project, "canonical_repo_id", errors, "project");
      requireString(project, "canonical_remote", errors, "project");
    }

    const overall = requireRecord(payload, "overall", errors, "root");
    if (overall) {
      requireEnum(overall, "status", STATUS_ENUMS.overall, errors, "overall");
      requireString(overall, "active_phase", errors, "overall");
      requireInteger(overall, "completed_phases", 0, Number.MAX_SAFE_INTEGER, errors, "overall");
      requireInteger(overall, "total_phases", 1, Number.MAX_SAFE_INTEGER, errors, "overall");
      requireInteger(overall, "progress_percent", 0, 100, errors, "overall");
      requireEnum(overall, "release_readiness", STATUS_ENUMS.readiness, errors, "overall");
      requireString(overall, "release_block_reason", errors, "overall", true);
      requireExactString(
        overall,
        "operating_boundary",
        "research_only_advisory_only",
        errors,
        "overall",
      );
    }

    const frontendSync = requireRecord(payload, "frontend_sync", errors, "root");
    if (frontendSync) {
      requireExactBoolean(frontendSync, "required", true, errors, "frontend_sync");
      requireEnum(
        frontendSync,
        "current_availability",
        STATUS_ENUMS.frontendAvailability,
        errors,
        "frontend_sync",
      );
      requireExactString(
        frontendSync,
        "source_of_truth",
        "integration/integration_status.json",
        errors,
        "frontend_sync",
      );
      requireExactBoolean(frontendSync, "ui_mutation_allowed", false, errors, "frontend_sync");
      requireExactString(
        frontendSync,
        "unknown_or_invalid_state",
        "BLOCK",
        errors,
        "frontend_sync",
      );
    }

    validateVerification(payload, errors);
    validateBoundaries(payload, errors);
    const phases = validatePhases(payload, errors);
    const risks = validateRisks(payload, errors);

    if (overall && phases) {
      const completed = phases.filter((phase) => phase.status === "completed").length;
      if (overall.total_phases !== phases.length) {
        errors.push("overall.total_phases 必须与 phases 数量一致");
      }
      if (overall.completed_phases !== completed) {
        errors.push("overall.completed_phases 必须与已完成阶段数量一致");
      }
      if (!phases.some((phase) => phase.id === overall.active_phase)) {
        errors.push("overall.active_phase 必须引用一个已声明阶段");
      }
    }

    if (overall && risks) {
      const hasBlockingRisk = risks.some(
        (risk) => risk.release_blocking === true && risk.status !== "closed",
      );
      if (hasBlockingRisk && overall.release_readiness !== "BLOCK") {
        errors.push("存在未关闭的发布阻断风险时 release_readiness 必须为 BLOCK");
      }
    }

    return { ok: errors.length === 0, errors };
  }

  function validateVerification(payload, errors) {
    const verification = requireRecord(payload, "verification", errors, "root");
    if (!verification) {
      return;
    }
    requireIsoDateTime(verification, "verified_at", errors, "verification");
    requireEnum(
      verification,
      "status_contract",
      STATUS_ENUMS.verification,
      errors,
      "verification",
    );
    requireEnum(
      verification,
      "json_parser",
      STATUS_ENUMS.verification,
      errors,
      "verification",
    );
    requireEnum(
      verification,
      "diff_check",
      STATUS_ENUMS.verification,
      errors,
      "verification",
    );

    const targetedTests = requireRecord(
      verification,
      "targeted_tests",
      errors,
      "verification",
    );
    if (targetedTests) {
      requireEnum(
        targetedTests,
        "status",
        STATUS_ENUMS.verification,
        errors,
        "verification.targeted_tests",
      );
      requireInteger(
        targetedTests,
        "passed",
        0,
        Number.MAX_SAFE_INTEGER,
        errors,
        "verification.targeted_tests",
      );
      requireInteger(
        targetedTests,
        "failed",
        0,
        Number.MAX_SAFE_INTEGER,
        errors,
        "verification.targeted_tests",
      );
    }

    const fullTests = requireRecord(verification, "full_tests", errors, "verification");
    if (fullTests) {
      requireEnum(
        fullTests,
        "status",
        STATUS_ENUMS.verification,
        errors,
        "verification.full_tests",
      );
      requireInteger(
        fullTests,
        "passed",
        0,
        Number.MAX_SAFE_INTEGER,
        errors,
        "verification.full_tests",
      );
      requireInteger(
        fullTests,
        "failed",
        0,
        Number.MAX_SAFE_INTEGER,
        errors,
        "verification.full_tests",
      );
    }

    const secretScan = requireRecord(verification, "secret_scan", errors, "verification");
    if (secretScan) {
      requireEnum(
        secretScan,
        "status",
        STATUS_ENUMS.verification,
        errors,
        "verification.secret_scan",
      );
      requireInteger(
        secretScan,
        "candidate_files",
        0,
        Number.MAX_SAFE_INTEGER,
        errors,
        "verification.secret_scan",
      );
    }

    const distributionBuild = requireRecord(
      verification,
      "distribution_build",
      errors,
      "verification",
    );
    if (distributionBuild) {
      requireEnum(
        distributionBuild,
        "status",
        STATUS_ENUMS.verification,
        errors,
        "verification.distribution_build",
      );
      requireExactBoolean(
        distributionBuild,
        "contains_quantify",
        true,
        errors,
        "verification.distribution_build",
      );
      requireExactBoolean(
        distributionBuild,
        "contains_yeuxq",
        true,
        errors,
        "verification.distribution_build",
      );
    }
  }

  function validateBoundaries(payload, errors) {
    const boundaries = requireRecord(payload, "boundaries", errors, "root");
    if (!boundaries) {
      return;
    }

    const liveObservation = requireRecord(
      boundaries,
      "live_observation",
      errors,
      "boundaries",
    );
    if (liveObservation) {
      requireEnum(
        liveObservation,
        "status",
        STATUS_ENUMS.observationBoundary,
        errors,
        "boundaries.live_observation",
      );
      requireExactBoolean(
        liveObservation,
        "research_eligible_by_default",
        false,
        errors,
        "boundaries.live_observation",
      );
      const safety = requireRecord(
        liveObservation,
        "fixed_safety_fields",
        errors,
        "boundaries.live_observation",
      );
      if (safety) {
        requireExactBoolean(
          safety,
          "prohibited_live_use",
          true,
          errors,
          "boundaries.live_observation.fixed_safety_fields",
        );
        requireExactBoolean(
          safety,
          "broker_access",
          false,
          errors,
          "boundaries.live_observation.fixed_safety_fields",
        );
        requireExactBoolean(
          safety,
          "live_trading_allowed",
          false,
          errors,
          "boundaries.live_observation.fixed_safety_fields",
        );
      }
    }

    const research = requireRecord(boundaries, "research", errors, "boundaries");
    if (research) {
      requireEnum(
        research,
        "status",
        STATUS_ENUMS.researchBoundary,
        errors,
        "boundaries.research",
      );
      requireExactString(research, "mode", "research_only", errors, "boundaries.research");
      requireExactBoolean(
        research,
        "implicit_observation_promotion",
        false,
        errors,
        "boundaries.research",
      );
    }

    const execution = requireRecord(boundaries, "execution", errors, "boundaries");
    if (execution) {
      ["broker_integration", "account_access", "live_orders", "automatic_trading"].forEach(
        (key) => requireExactBoolean(execution, key, false, errors, "boundaries.execution"),
      );
      requireExactBoolean(
        execution,
        "paper_simulation_only",
        true,
        errors,
        "boundaries.execution",
      );
    }
  }

  function validatePhases(payload, errors) {
    if (!Array.isArray(payload.phases) || payload.phases.length === 0) {
      errors.push("root.phases 必须是非空数组");
      return null;
    }

    const ids = new Set();
    const orders = new Set();
    payload.phases.forEach((phase, index) => {
      const path = `phases[${index}]`;
      if (!isRecord(phase)) {
        errors.push(`${path} 必须是对象`);
        return;
      }
      requireString(phase, "id", errors, path);
      requireInteger(phase, "order", 0, Number.MAX_SAFE_INTEGER, errors, path);
      requireString(phase, "name", errors, path);
      requireEnum(phase, "status", STATUS_ENUMS.phase, errors, path);
      requireInteger(phase, "progress_percent", 0, 100, errors, path);
      requireString(phase, "owner", errors, path);

      if (typeof phase.id === "string") {
        if (!/^[a-z][a-z0-9_]*$/.test(phase.id)) {
          errors.push(`${path}.id 必须使用小写 snake_case`);
        }
        if (ids.has(phase.id)) {
          errors.push(`${path}.id 不得重复`);
        }
        ids.add(phase.id);
      }
      if (Number.isInteger(phase.order)) {
        if (orders.has(phase.order)) {
          errors.push(`${path}.order 不得重复`);
        }
        orders.add(phase.order);
      }
      if (phase.status === "completed" && phase.progress_percent !== 100) {
        errors.push(`${path} completed 阶段的进度必须为 100`);
      }
      if (phase.status === "not_started" && phase.progress_percent !== 0) {
        errors.push(`${path} not_started 阶段的进度必须为 0`);
      }
    });
    return payload.phases;
  }

  function validateRisks(payload, errors) {
    if (!Array.isArray(payload.risks)) {
      errors.push("root.risks 必须是数组");
      return null;
    }

    const ids = new Set();
    payload.risks.forEach((risk, index) => {
      const path = `risks[${index}]`;
      if (!isRecord(risk)) {
        errors.push(`${path} 必须是对象`);
        return;
      }
      requireString(risk, "id", errors, path);
      requireEnum(risk, "priority", STATUS_ENUMS.priority, errors, path);
      requireString(risk, "title", errors, path);
      requireEnum(risk, "status", STATUS_ENUMS.risk, errors, path);
      requireString(risk, "owner", errors, path);
      requireBoolean(risk, "release_blocking", errors, path);
      requireString(risk, "closure", errors, path);
      if (typeof risk.id === "string") {
        if (ids.has(risk.id)) {
          errors.push(`${path}.id 不得重复`);
        }
        ids.add(risk.id);
      }
    });
    return payload.risks;
  }

  function requireRecord(parent, key, errors, path) {
    if (!isRecord(parent[key])) {
      errors.push(`${path}.${key} 必须是对象`);
      return null;
    }
    return parent[key];
  }

  function requireString(parent, key, errors, path, allowEmpty) {
    if (typeof parent[key] !== "string" || (!allowEmpty && parent[key].trim() === "")) {
      errors.push(`${path}.${key} 必须是${allowEmpty ? "" : "非空"}字符串`);
    }
  }

  function requireBoolean(parent, key, errors, path) {
    if (typeof parent[key] !== "boolean") {
      errors.push(`${path}.${key} 必须是布尔值`);
    }
  }

  function requireExactBoolean(parent, key, expected, errors, path) {
    if (parent[key] !== expected) {
      errors.push(`${path}.${key} 必须保持为 ${String(expected)}`);
    }
  }

  function requireExactString(parent, key, expected, errors, path) {
    if (parent[key] !== expected) {
      errors.push(`${path}.${key} 必须使用受支持值`);
    }
  }

  function requireInteger(parent, key, minimum, maximum, errors, path) {
    const value = parent[key];
    if (!Number.isInteger(value) || value < minimum || value > maximum) {
      errors.push(`${path}.${key} 必须是 ${minimum}–${maximum} 范围内的整数`);
    }
  }

  function requireEnum(parent, key, allowed, errors, path) {
    if (!allowed.includes(parent[key])) {
      errors.push(`${path}.${key} 包含未知状态枚举`);
    }
  }

  function requireIsoDateTime(parent, key, errors, path) {
    const value = parent[key];
    if (
      typeof value !== "string" ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) ||
      Number.isNaN(Date.parse(value))
    ) {
      errors.push(`${path}.${key} 必须是带时区的 ISO 8601 时间`);
    }
  }

  function deriveDisplayState(payload) {
    const validation = validateStatusPayload(payload);
    if (!validation.ok) {
      return {
        status: "BLOCK",
        reason: "状态源缺失、未知或未通过严格校验。",
        validation,
      };
    }
    return {
      status: payload.overall.release_readiness,
      reason: payload.overall.release_block_reason,
      validation,
    };
  }

  const exportedApi = Object.freeze({
    STATUS_ENUMS,
    STATUS_SOURCE,
    SUPPORTED_SCHEMA,
    deriveDisplayState,
    validateStatusPayload,
  });

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportedApi;
  }
  globalScope.YeuxQIntegrationStatus = exportedApi;

  if (typeof document === "undefined") {
    return;
  }

  const elements = {};

  function captureElements() {
    [
      "active-phase",
      "block-message",
      "block-notice",
      "block-title",
      "connection-state",
      "overall-progress",
      "overall-progress-fill",
      "overall-progress-track",
      "phase-count",
      "phase-list",
      "readiness-caption",
      "readiness-value",
      "refresh-status",
      "risk-list",
      "risk-summary",
      "source-ref",
      "updated-at",
      "verification-list",
    ].forEach((id) => {
      elements[id] = document.getElementById(id);
    });
  }

  function makeElement(tagName, className, content) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (content !== undefined) {
      element.textContent = String(content);
    }
    return element;
  }

  function formatShanghaiTime(value) {
    return new Intl.DateTimeFormat("zh-CN", {
      dateStyle: "medium",
      timeStyle: "medium",
      timeZone: "Asia/Shanghai",
    }).format(new Date(value));
  }

  function setBlockState(message) {
    elements["connection-state"].textContent = "FAIL-CLOSED";
    elements["readiness-value"].textContent = "BLOCK";
    elements["readiness-value"].className = "readiness-value is-block";
    elements["readiness-caption"].textContent = message;
    elements["block-notice"].className = "block-notice";
    elements["block-title"].textContent = "BLOCK — 状态源不可用";
    elements["block-message"].textContent = message;
    elements["updated-at"].textContent = "未通过验证";
    elements["active-phase"].textContent = "UNKNOWN / BLOCK";
    setProgress(0, 0, 0);
    renderEmptyBlockedCollections();
  }

  function renderEmptyBlockedCollections() {
    elements["phase-list"].replaceChildren(
      makeElement("li", "empty-state", "BLOCK：没有可安全显示的阶段记录。"),
    );
    elements["risk-list"].replaceChildren(
      makeElement("p", "empty-state", "BLOCK：风险记录未知，按全部未关闭处理。"),
    );
    elements["risk-summary"].textContent = "状态无效；所有风险按未关闭处理。";
    renderVerificationItems([
      ["STATUS CONTRACT", "BLOCK", "状态源未通过校验"],
      ["JSON PARSER", "BLOCK", "无可信 JSON 证据"],
      ["TARGETED TESTS", "BLOCK", "结果不可用"],
      ["FULL REGRESSION", "BLOCK", "结果不可用"],
      ["SECRET SCAN", "BLOCK", "结果不可用"],
      ["PACKAGE BUILD", "BLOCK", "结果不可用"],
      ["DIFF CHECK", "BLOCK", "结果不可用"],
    ]);
  }

  function renderPayload(payload) {
    const overall = payload.overall;
    elements["connection-state"].textContent = "VALID / READ-ONLY";
    elements["source-ref"].textContent = payload.frontend_sync.source_of_truth;
    elements["updated-at"].textContent = formatShanghaiTime(payload.updated_at);
    elements["active-phase"].textContent = overall.active_phase;
    elements["readiness-value"].textContent = overall.release_readiness;
    elements["readiness-value"].className =
      `readiness-value is-${overall.release_readiness.toLowerCase()}`;
    elements["readiness-caption"].textContent =
      overall.release_block_reason || "当前状态源未提供额外说明。";
    setProgress(
      overall.progress_percent,
      overall.completed_phases,
      overall.total_phases,
    );
    renderNotice(overall);
    renderPhases(payload.phases);
    renderRisks(payload.risks);
    renderVerification(payload.verification);
  }

  function setProgress(percent, completed, total) {
    elements["overall-progress-fill"].style.width = `${percent}%`;
    elements["overall-progress"].textContent = `${percent}%`;
    elements["phase-count"].textContent = `${completed} / ${total} PHASES`;
    elements["overall-progress-track"].setAttribute("aria-valuenow", String(percent));
    elements["overall-progress-track"].setAttribute("aria-valuetext", `${percent}%`);
  }

  function renderNotice(overall) {
    const readiness = overall.release_readiness;
    const classSuffix = readiness === "PASS" ? " is-pass" : readiness === "WATCH" ? " is-watch" : "";
    elements["block-notice"].className = `block-notice${classSuffix}`;
    elements["block-title"].textContent = `${readiness} — ${STATUS_LABELS[overall.status]}`;
    elements["block-message"].textContent =
      overall.release_block_reason || "已通过结构校验；未提供状态说明。";
  }

  function renderPhases(phases) {
    const fragment = document.createDocumentFragment();
    [...phases]
      .sort((left, right) => left.order - right.order)
      .forEach((phase) => {
        const item = makeElement("li", "phase-item");
        item.dataset.status = phase.status;
        item.append(
          makeElement("p", "phase-order", `PHASE ${String(phase.order).padStart(2, "0")}`),
          makeElement("h3", "phase-name", phase.name),
          makeElement("span", "phase-state", STATUS_LABELS[phase.status]),
        );
        const progress = makeElement("progress", "phase-meter");
        progress.max = 100;
        progress.value = phase.progress_percent;
        progress.setAttribute("aria-label", `${phase.name} 进度`);
        item.append(
          progress,
          makeElement("p", "phase-percent", `${phase.progress_percent}%`),
          makeElement("p", "phase-owner", `OWNER / ${phase.owner}`),
        );
        fragment.append(item);
      });
    elements["phase-list"].replaceChildren(fragment);
  }

  function renderRisks(risks) {
    if (risks.length === 0) {
      elements["risk-list"].replaceChildren(
        makeElement("p", "empty-state", "风险清单为空；这不等同于风险审查通过。"),
      );
      elements["risk-summary"].textContent = "0 条已登记风险；仍需独立审查证据。";
      return;
    }

    const fragment = document.createDocumentFragment();
    [...risks]
      .sort((left, right) => left.priority.localeCompare(right.priority) || left.id.localeCompare(right.id))
      .forEach((risk) => {
        const row = makeElement("article", "risk-row");
        row.dataset.priority = risk.priority;
        row.append(
          makeElement("p", "risk-id", `${risk.priority} / ${risk.id}`),
          makeElement("h3", "risk-title", risk.title),
          makeElement("p", "risk-closure", risk.closure),
        );
        const meta = makeElement("p", "risk-meta");
        meta.append(
          makeElement("strong", "", STATUS_LABELS[risk.status]),
          document.createTextNode(
            `${risk.release_blocking ? " RELEASE BLOCK" : " TRACKED"} · ${risk.owner}`,
          ),
        );
        row.append(meta);
        fragment.append(row);
      });
    elements["risk-list"].replaceChildren(fragment);

    const open = risks.filter((risk) => risk.status !== "closed").length;
    const p0 = risks.filter((risk) => risk.priority === "P0" && risk.status !== "closed").length;
    const releaseBlocks = risks.filter(
      (risk) => risk.release_blocking && risk.status !== "closed",
    ).length;
    elements["risk-summary"].textContent =
      `${open} 条未关闭 · ${p0} 条 P0 · ${releaseBlocks} 条阻断发布`;
  }

  function renderVerification(verification) {
    const testDetail =
      `${verification.targeted_tests.passed} passed / ${verification.targeted_tests.failed} failed`;
    const fullTestDetail =
      `${verification.full_tests.passed} passed / ${verification.full_tests.failed} failed`;
    const scanDetail = `${verification.secret_scan.candidate_files} candidate files`;
    const packageDetail = verification.distribution_build.contains_yeuxq
      ? "quantify + yeuxq"
      : "package boundary failed";
    renderVerificationItems([
      ["STATUS CONTRACT", verification.status_contract, "结构与枚举校验"],
      ["JSON PARSER", verification.json_parser, "单一状态源解析"],
      ["TARGETED TESTS", verification.targeted_tests.status, testDetail],
      ["FULL REGRESSION", verification.full_tests.status, fullTestDetail],
      ["SECRET SCAN", verification.secret_scan.status, scanDetail],
      ["PACKAGE BUILD", verification.distribution_build.status, packageDetail],
      ["DIFF CHECK", verification.diff_check, formatShanghaiTime(verification.verified_at)],
    ]);
  }

  function renderVerificationItems(items) {
    const fragment = document.createDocumentFragment();
    items.forEach(([label, status, detail]) => {
      const group = makeElement("div");
      const term = makeElement("dt", "", label);
      const description = makeElement("dd", `gate gate-${status.toLowerCase().replace("_", "-")}`);
      description.append(
        document.createTextNode(status),
        makeElement("span", "gate-detail", detail),
      );
      group.append(term, description);
      fragment.append(group);
    });
    elements["verification-list"].replaceChildren(fragment);
  }

  async function loadStatus() {
    elements["refresh-status"].disabled = true;
    elements["connection-state"].textContent = "VALIDATING";
    const controller = new AbortController();
    const timeout = globalScope.setTimeout(() => controller.abort(), 8_000);

    try {
      const response = await fetch(STATUS_SOURCE, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const body = await response.text();
      if (new TextEncoder().encode(body).byteLength > MAX_STATUS_BYTES) {
        throw new Error("状态文件超过安全大小上限");
      }
      const payload = JSON.parse(body);
      const validation = validateStatusPayload(payload);
      if (!validation.ok) {
        throw new Error(`严格校验失败：${validation.errors.slice(0, 3).join("；")}`);
      }
      renderPayload(payload);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "未知读取错误";
      setBlockState(`状态源请求或校验失败：${reason}`);
    } finally {
      globalScope.clearTimeout(timeout);
      elements["refresh-status"].disabled = false;
    }
  }

  function bootstrap() {
    captureElements();
    elements["source-ref"].textContent = `integration/${STATUS_SOURCE.replace("./", "")}`;
    elements["refresh-status"].addEventListener("click", loadStatus);
    setBlockState("状态正在读取；验证完成前保持 BLOCK。 ");
    loadStatus();
    globalScope.setInterval(loadStatus, REFRESH_INTERVAL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  } else {
    bootstrap();
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
