---
phase: 11
slug: metrics-the-mission-promises
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-20
---

# Phase 11 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Verified from the plan-time STRIDE registers (register_authored_at_plan_time: true)
> at ASVS L1 grep-depth; corroborated by the phase code review (11-REVIEW.md, CLEAN)
> and goal verifier (11-VERIFICATION.md, 8/8), plus a live browse check confirming the
> `@ifo_required` gate (unauth `/ifo/dashboard` → `/login`).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Browser → IFO views | Authenticated IFO admin requesting institution-wide reporting | Range params (`from`/`to`), faculty_id |
| Aggregate → CSV/spreadsheet | Server-generated CSV opened in Excel/Sheets/LibreOffice | Room codes/names/building (user-controllable text) |
| Aggregate → HR payroll CSV | Derived lateness column added beside raw timestamp | Faculty display name, minutes-late |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-11-01 | Tampering | `session_minutes_late` drift between faculty fold and HR CSV | medium | mitigate | ONE shared helper; `web/hr.py:38` imports it (`:249` uses it); named FacultyRow/Scorecard parity test | closed |
| T-11-02 | Information Disclosure | ABSENT/CANCELLED leaking into lateness numerator | low | mitigate | Fold filters HELD + `actual_start__isnull=False`; dedicated exclusion tests | closed |
| T-11-03 | Repudiation | Read-only aggregate is not a domain state change | low | accept | No AuditLog for a computation (module convention) — documented accepted risk | closed |
| T-11-04 | Tampering | CSV formula injection in weekly/HR exports | high | mitigate | Existing `csv_safe` on text cells untouched; new lateness cells numeric | closed |
| T-11-05 | Denial of Service | DB query inside HR streaming generator | medium | mitigate | Derived cell uses already-loaded session fields; no DB access added in `rows()` | closed |
| T-11-06 | Information Disclosure | Chronic verdict on statistically-insufficient data | low | mitigate | Chronic pill gated at `held >= 5` in `templates/reports/scorecard.html` (D-02 floor) | closed |
| T-11-07 | Elevation of Privilege | Unauthorized access to institution-wide coverage | high | mitigate | `@ifo_required` on `dashboard` (`web/ifo.py:1354`); live browse: unauth → `/login` | closed |
| T-11-08 | Information Disclosure | Raising coverage aggregate surfaces a raw exception | medium | mitigate | `safe_card(_coverage_card…)` / `safe_card(zero_coverage_floors…)` (`web/ifo.py:1389-1391`); per-card isolation test | closed |
| T-11-09 | Tampering | Reverse-join inflating the held denominator (dishonest coverage) | medium | mitigate | Verified is a SEPARATE `Count("id", distinct=True)` query (`reporting.py:589,636`); MERGED-lowers-coverage test | closed |
| T-11-10 | Tampering | CSV/formula injection in the per-room utilization export | high | mitigate | `csv_safe` on every text cell; `test_utilization_csv_formula_neutralized` | closed |
| T-11-11 | Tampering | Path traversal / header injection via export filename | medium | mitigate | Server-built filename only (`web/ifo.py:1630` → `utilization-{start}.csv`); never request-derived | closed |
| T-11-12 | Elevation of Privilege | Non-IFO access to per-room CSV / ghost list | high | mitigate | `@ifo_required` + `@require_http_methods(["GET"])` on `utilization_csv` (`web/ifo.py:1585-1587`); 403/405 tests | closed |
| T-11-13 | Information Disclosure | Raising ghost aggregate leaks an exception / blanks the page | medium | mitigate | `safe_card`-wrapped sections in the utilization view (`web/ifo.py:1357` docstring + wrapping); isolation test | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Only open threats at or above `workflow.security_block_on` (high) count toward threats_open.*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-11-01 | T-11-03 | A read-only reporting computation produces no domain state change, so no AuditLog entry is written (existing module convention for all aggregates). | plan-time threat model (disposition: accept) | 2026-07-20 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-20 | 13 | 13 | 0 | /gsd-secure-phase (L1, short-circuit; corroborated by code review + goal verifier + live browse) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-20
