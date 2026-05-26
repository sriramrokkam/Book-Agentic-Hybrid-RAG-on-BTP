# Joule A2A Integration

> **Enterprise prerequisite** — requires SAP S/4HANA Cloud Public Edition or
> SuccessFactors. Not available on BTP free trial.

This directory contains the Joule A2A capability package that wraps the Hybrid
RAG Agent as a Joule skill. It is covered in **Appendix D** of the book.

## What is covered in Appendix D

- Joule A2A protocol overview
- `da.sapdas.yaml` — root agent declaration
- Capability YAML and function handler structure
- Scenario routing and SpEL expressions
- The 15-second timeout constraint
- Deploying a `.daar` package to SAP Joule
- Testing in the Joule sandbox

## Why it is empty here

The Joule A2A SDK and deployment tooling require an active enterprise SAP
subscription. The implementation is documented step-by-step in Appendix D so
readers with the required subscription can follow along.

## Files you will create in Appendix D

```
joule/
├── da.sapdas.yaml              Root agent declaration
├── capabilities/
│   └── msds-query/
│       ├── capability.yaml     Capability definition
│       └── handler.js          Function handler (calls /query endpoint)
└── scenarios/
    └── msds-scenario.yaml      Scenario routing
```
