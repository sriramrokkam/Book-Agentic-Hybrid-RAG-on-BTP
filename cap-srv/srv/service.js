"use strict";
/**
 * cap-srv/srv/service.js
 *
 * CAP service handler for MSDSService.
 * Proxies OData actions to the Python FastAPI agent service.
 *
 * The AGENT_URL environment variable must point to the running Python service:
 *   - Local development: http://localhost:8000
 *   - BTP CF:            https://hybrid-rag-agent.<cf-domain>
 */

const cds = require("@sap/cds");

const AGENT_URL = process.env.AGENT_URL || "http://localhost:8000";

// ── Helper: POST JSON to the agent service ──────────────────────────────────

async function agentPost(path, body) {
  const fetch = (await import("node-fetch")).default;
  const response = await fetch(`${AGENT_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    timeout: 60_000, // 60 s — allow time for parallel chains
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Agent returned ${response.status}: ${text}`);
  }
  return response.json();
}

async function agentDelete(path) {
  const fetch = (await import("node-fetch")).default;
  const response = await fetch(`${AGENT_URL}${path}`, {
    method: "DELETE",
    timeout: 30_000,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Agent returned ${response.status}: ${text}`);
  }
  return response.json();
}
  const fetch = (await import("node-fetch")).default;
  const response = await fetch(`${AGENT_URL}${path}`, { timeout: 15_000 });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Agent returned ${response.status}: ${text}`);
  }
  return response.json();
}

// ── Service handler ─────────────────────────────────────────────────────────

module.exports = cds.service.impl(async function (srv) {

  // ── query action ───────────────────────────────────────────────────────────
  srv.on("query", async (req) => {
    const { question, materialNumber, history } = req.data;

    let parsedHistory = [];
    try {
      parsedHistory = history ? JSON.parse(history) : [];
    } catch {
      // ignore malformed history
    }

    const result = await agentPost("/query", {
      question,
      material_number: materialNumber,
      history: parsedHistory,
    });

    return {
      answer: result.answer || "",
      kgSparql: result.kg_sparql || "",
      kgFacts: JSON.stringify(result.kg_facts || []),
      vectorChunks: JSON.stringify(result.vector_chunks || []),
      sources: JSON.stringify(result.sources || []),
    };
  });

  // ── queryAdvanced action ───────────────────────────────────────────────────
  srv.on("queryAdvanced", async (req) => {
    const { question, materialNumber, history, useSupervisor } = req.data;

    let parsedHistory = [];
    try {
      parsedHistory = history ? JSON.parse(history) : [];
    } catch {
      // ignore
    }

    const result = await agentPost("/query-advanced", {
      question,
      material_number: materialNumber,
      history: parsedHistory,
      use_supervisor: useSupervisor || false,
    });

    return {
      answer: result.answer || "",
      sources: JSON.stringify(result.sources || []),
    };
  });

  // ── ingestionStatus function ───────────────────────────────────────────────
  srv.on("ingestionStatus", async (req) => {
    const { materialNumber } = req.data;
    const result = await agentGet(`/status/${materialNumber}`);
    return {
      materialNumber: result.materialNumber,
      kgStatus: result.kgStatus,
      vectorStatus: result.vectorStatus,
      kgError: result.kgError || "",
      vectorError: result.vectorError || "",
      complete: result.complete,
    };
  });

  // ── ingestDocument action ──────────────────────────────────────────────────
  srv.on("ingestDocument", "Documents", async (req) => {
    const { materialName, fileContent, fileName } = req.data;
    const { materialNumber } = req.params[0];

    // Build multipart form-data for the Python /process-upload endpoint
    const fetch = (await import("node-fetch")).default;
    const FormData = (await import("form-data")).default;
    const form = new FormData();
    form.append("file", Buffer.from(fileContent, "base64"), {
      filename: fileName || "upload.pdf",
      contentType: "application/pdf",
    });
    form.append("materialNumber", materialNumber);
    form.append("materialName", materialName || materialNumber);

    const response = await fetch(`${AGENT_URL}/process-upload`, {
      method: "POST",
      body: form,
      headers: form.getHeaders(),
      timeout: 30_000,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Upload failed: ${response.status} — ${text}`);
    }

    const result = await response.json();
    return {
      status: result.status,
      materialNumber: result.materialNumber,
    };
  });

  // ── deleteDocument action ──────────────────────────────────────────────────
  srv.on("deleteDocument", "Documents", async (req) => {
    const { materialNumber } = req.params[0];
    const result = await agentDelete(`/delete/${materialNumber}`);
    return {
      materialNumber: result.materialNumber,
      vectorsDeleted: result.vectorsDeleted,
      kgDeleted: result.kgDeleted,
    };
  });

  // ── Auto-update Documents timestamps ──────────────────────────────────────
  srv.before("CREATE", "Documents", (req) => {
    req.data.createdAt = new Date().toISOString();
    req.data.updatedAt = new Date().toISOString();
  });

  srv.before("UPDATE", "Documents", (req) => {
    req.data.updatedAt = new Date().toISOString();
  });
});
