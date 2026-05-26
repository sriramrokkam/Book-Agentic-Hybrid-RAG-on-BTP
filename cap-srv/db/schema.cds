// cap-srv/db/schema.cds
//
// CDS data model for the Hybrid RAG CAP service.
// Tracks MSDS documents and their dual-pipeline ingestion status.

namespace msds;

using { cuid, managed } from '@sap/cds/common';

// ── MSDS document registry ──────────────────────────────────────────────────

entity Documents {
    key materialNumber : String(100);
        materialName   : String(500);
        // Knowledge graph pipeline status
        status         : String(20) default 'PENDING';
        kgError        : String(1000);
        // Vector pipeline status
        vectorStatus   : String(20) default 'PENDING';
        vectorError    : String(1000);
        // Timestamps
        createdAt      : Timestamp;
        updatedAt      : Timestamp;
}

// ── Query log (optional audit trail) ───────────────────────────────────────

entity QueryLog {
    key ID             : UUID;
        materialNumber : String(100);
        question       : String(2000);
        answer         : String(10000);
        kgFacts        : Integer default 0;
        vectorChunks   : Integer default 0;
        createdAt      : Timestamp;
}
