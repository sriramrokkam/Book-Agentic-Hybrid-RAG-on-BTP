// cap-srv/srv/service.cds
//
// OData V4 service definition for the Hybrid RAG CAP frontend.
// Exposes MSDS document management and proxies queries to the Python agent service.

using { msds } from '../db/schema';

service MSDSService @(path: '/api') {

    // ── Document management ────────────────────────────────────────────────

    entity Documents as projection on msds.Documents
        actions {
            // Trigger ingestion of an uploaded PDF (calls Python /process-upload)
            action ingestDocument(
                materialName : String(500),
                fileContent  : LargeBinary,
                fileName     : String(500)
            ) returns {
                status         : String(20);
                materialNumber : String(100);
            };
        };

    // ── Query actions ──────────────────────────────────────────────────────

    // Direct parallel hybrid RAG query
    action query(
        question       : String(2000),
        materialNumber : String(100),
        history        : String(10000)   // JSON-serialised array
    ) returns {
        answer         : String(10000);
        kgSparql       : String(5000);
        kgFacts        : String(10000);  // JSON-serialised array
        vectorChunks   : String(10000);  // JSON-serialised array
        sources        : String(2000);
    };

    // Advanced query — multi-agent supervisor (use_supervisor flag)
    action queryAdvanced(
        question       : String(2000),
        materialNumber : String(100),
        history        : String(10000),
        useSupervisor  : Boolean default false
    ) returns {
        answer   : String(10000);
        sources  : String(2000);
    };

    // ── Status check ───────────────────────────────────────────────────────

    function ingestionStatus(
        materialNumber : String(100)
    ) returns {
        materialNumber : String(100);
        kgStatus       : String(20);
        vectorStatus   : String(20);
        kgError        : String(1000);
        vectorError    : String(1000);
        complete       : Boolean;
    };

    // ── Query log ──────────────────────────────────────────────────────────

    @readonly
    entity QueryLog as projection on msds.QueryLog;
}
