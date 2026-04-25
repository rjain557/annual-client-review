# Personalized Tech Training — R. Mohamed

**Period:** 2026 (all clients)  
**Total entries logged:** 331  
**Total hours logged:** 214.38  
**Flagged entries:** 2 (0.6%)  
**Flagged hours:** 5.25 (2.4%)  

## Flags breakdown

| Code | Count | Meaning |
|---|---:|---|
| H1 | 2 | Routine work with hours exceeding category cap |

## Flagged entries by client

| Client | # flagged | Flagged hours |
|---|---:|---:|
| BWH | 2 | 5.25 |

## Most-flagged work categories

| Category | # flagged | Flagged hours |
|---|---:|---:|
| Routine: Server/DC issue | 1 | 4.00 |
| Routine: Admin / meetings / approvals | 1 | 1.25 |

## Your 10 most-flagged individual entries

| Client | Date | Hours | Cap | Title | Reason |
|---|---|---:|---:|---|---|
| BWH | 2026-01-25 | 4.00 | 3.0 | Server down | routine > 3.0h cap (Server/DC issue) |
| BWH | 2026-02-09 | 1.25 | 1.0 | BWH meeting with new star | routine > 1.0h cap (Admin / meetings / approvals) |

## Coaching — what your titles should look like

For each of your top flagged entries below, you'll see what you wrote, the expected normal time for that work, what the title should have included, and two model rewrites: one that fits within the cap and one that justifies the higher hours you actually logged.

### BWH 2026-01-25 — 4.00h logged on "Server down"

- **Category:** Routine: Server/DC issue  
- **Expected time for this category:** ≤ 3.0 hours  
- **Why flagged:** Your 4.00h is above the 3.0h normal cap for this category — title needs more detail.  
- **A good title must include:** what specifically broke (services, AD replication, GPO), root cause, verification

**You wrote:** _Server down_  

**Model title within 3.0h:**  
> RA01 DC issue — restarted Netlogon service, replication healthy

**Model title to justify 4.00h:**  
> RA01 DC issue — AD replication broken (USN rollback), seized FSMO to RA02, demoted/repromoted RA01, verified replication for 2h (~5h)

### BWH 2026-02-09 — 1.25h logged on "BWH meeting with new star"

- **Category:** Routine: Admin / meetings / approvals  
- **Expected time for this category:** ≤ 1.0 hours  
- **Why flagged:** Your 1.25h is above the 1.0h normal cap for this category — title needs more detail.  
- **A good title must include:** meeting subject, decisions made, action items assigned

**You wrote:** _BWH meeting with new star_  

**Model title within 1.0h:**  
> Weekly client standup with K. Stickel — 30 min, agenda + action items

**Model title to justify 1.25h:**  
> Quarterly review — ran agenda, captured 8 decisions, drafted next-quarter plan (~2h)


## Personalized training focus

**Your most common issue is over-claiming time on routine work.** For patch-management alerts, agent version updates (CrowdStrike, ScreenConnect, MyRMM), CPU/memory/disk threshold alerts, and similar auto-generated monitoring tickets, the expected resolution time is 0.25–1.0 hours. If an alert genuinely takes longer, your title must explain why (e.g. "Critical CPU — investigated runaway SQL process" instead of just "Critical - CPU Utilization").

### General time-entry rules

1. **Descriptive titles required** — no standalone "Help", "Test", "Fix", "Issue".
2. **One entry per ticket per day** — consolidate all work on the same ticket into one entry.
3. **Cap routine alerts at 1 hour** — if it takes longer, the title must explain why.
4. **Weekly Maintenance Window time must be split** across the covered clients, not wholesale logged to one.
5. **Agent updates are ~0.25 hr/machine** — if your update ticket goes over, describe the problem.
6. **Spot-check your own week** before submitting. If a title would confuse a client, rewrite it.
