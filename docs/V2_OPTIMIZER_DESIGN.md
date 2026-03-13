# F1 Fantasy V2 Optimizer — Design Doc

## Status: DESIGN PHASE (not implemented)

## Goal

Replace the current "pick max points" combinatorial search with a proper constraint
satisfaction optimizer that accounts for transfers, chips, budget growth, and multi-week
planning.

## Current V1 (what we have)

- Fetches expected points + prices from f1fantasytools.com
- Brute-force: tries all (302 C 5) × (10 C 2) × 7 boost combos ≈ 2.7B evaluations
- No transfer modeling (assumes free rebuild each week)
- No chip strategy
- No budget projection
- Single-week horizon

## V2 Architecture

### Module 1: `optimizer_v2.py` — Core CSP Solver

**Solver:** Google OR-Tools CP-SAT (fast, handles mixed integer/boolean constraints)

**Decision Variables:**
```
pick_driver[d]     ∈ {0,1}  for each driver d
pick_constructor[c] ∈ {0,1}  for each constructor c
boost_driver[d]    ∈ {0,1}  for each driver d (exactly 1)
transfer_in[p]     ∈ {0,1}  for each player p (new to team)
transfer_out[p]    ∈ {0,1}  for each player p (leaving team)
use_wildcard       ∈ {0,1}
use_limitless      ∈ {0,1}
use_final_fix      ∈ {0,1}
use_extra_drs      ∈ {0,1}
```

**Objective:**
```
maximize:
  Σ (expected_pts[p] × pick[p])                           # base points
  + Σ (expected_pts[d] × boost_driver[d])                 # boost (2x or 3x)
  - 10 × max(0, transfers_used - free_transfers)          # transfer penalty
  + λ × Σ (price_change[p] × pick[p])                     # budget growth (optional)
```

Where `λ` is a season-phase-dependent weight:
- Early season (races 1-8): λ = 0.3 (prioritize budget growth)
- Mid season (races 9-16): λ = 0.15 (balanced)
- Late season (races 17-24): λ = 0.0 (maximize points only)

**Constraints:**
1. `Σ pick_driver = 5`
2. `Σ pick_constructor = 2`
3. `Σ pick × price ≤ budget` (∞ if Limitless active)
4. `Σ boost_driver = 1`
5. `boost_driver[d] ≤ pick_driver[d]` (can only boost a picked driver)
6. `transfer_in[p] = pick[p] ∧ ¬current[p]` (new picks = transfers in)
7. `transfer_out[p] = current[p] ∧ ¬pick[p]` (dropped = transfers out)
8. `transfers_used = Σ transfer_in = Σ transfer_out`
9. If `use_wildcard`: transfers_used unconstrained, penalty = 0
10. If `use_limitless`: budget = ∞, transfers unconstrained, penalty = 0
11. Chips are mutually exclusive (at most 1 active per week)

### Module 2: `chip_planner.py` — Chip Strategy

**Available chips** (1 use each, across 24 races):
| Chip | Effect |
|------|--------|
| Wildcard | Unlimited transfers, no penalty |
| Limitless | Unlimited transfers + unlimited budget (1 week) |
| Final Fix | Swap 1 driver after qualifying |
| Extra DRS | 3x boost instead of 2x |

**Strategy model (greedy + lookahead):**

For each remaining chip, simulate using it this week:
1. Run optimizer with chip active → `pts_with_chip`
2. Run optimizer without chip → `pts_without_chip`
3. `chip_value[race] = pts_with_chip - pts_without_chip`
4. Track `chip_value` across future races using projected expected points
5. Use chip when `chip_value` exceeds threshold:
   - Wildcard: use when ≥40 pts gain (≈ 4 transfers worth)
   - Limitless: use when ≥60 pts gain (high-budget team pays off big)
   - Final Fix: use when qualifying creates ≥20 pts swing opportunity
   - Extra DRS: use when boost target has ≥50 pts expected

**Multi-week chip planning:**
- Simulate remaining season with each chip allocation
- Use dynamic programming or greedy with diminishing returns
- Account for: remaining races, expected future value, chip expiry rules

### Module 3: `budget_model.py` — Budget Projection

**Price change formula** (reverse-engineered from F1 Fantasy):
```
delta_price ≈ 0.1 × (actual_pts - expected_pts) / expected_pts
clamped to [-0.6, +0.6] per week
```

**Budget optimization:**
- Early season: sometimes pick "value" drivers (underpriced, likely to rise)
- Track each driver's:
  - `form`: rolling 3-race average
  - `value_score`: (expected_pts / price) × (1 + price_momentum)
  - `upside`: probability of exceeding expected points
- Objective includes budget growth term with season-phase weight

**Budget growth scenarios:**
- Conservative: pick stable performers, steady ~$0.3M/week growth
- Aggressive: pick undervalued drivers, higher variance but ~$0.5M/week potential
- The optimizer can balance based on λ parameter

### Module 4: `simulator.py` — Scenario Testing

Run Monte Carlo simulations:
- Sample actual points from distributions (mean=expected, std=historical_variance)
- Run optimizer 1000× with different point outcomes
- Output:
  - Expected total season points
  - 10th/50th/90th percentile outcomes
  - Optimal chip allocation confidence
  - Risk assessment for each strategy

### Module 5: `multi_week_planner.py` — Season Horizon

For each remaining race:
1. Project expected points (using historical track data + current form)
2. Simulate budget trajectory
3. Identify high-leverage weeks for chip usage
4. Output: recommended chip schedule + transfer strategy

## Implementation Plan (future)

### Phase 1: Core optimizer
- [ ] Install OR-Tools (`pip install ortools`)
- [ ] Implement `optimizer_v2.py` with transfer-aware CSP
- [ ] Add chip constraints (single-week)
- [ ] Benchmark against V1 (should find same team when no transfers needed)

### Phase 2: Chip strategy
- [ ] Implement `chip_planner.py`
- [ ] Add chip value simulation
- [ ] Integrate with meta-scheduler

### Phase 3: Budget model
- [ ] Implement `budget_model.py`
- [ ] Calibrate price change formula against historical data
- [ ] Add season-phase λ to optimizer

### Phase 4: Multi-week
- [ ] Implement `multi_week_planner.py`
- [ ] Add Monte Carlo simulator
- [ ] End-to-end season planning

### Phase 5: Integration
- [ ] Replace V1 call in meta-scheduler with V2
- [ ] Add V2 report format (include chip recommendations, budget outlook)
- [ ] Add A/B testing: run both V1 and V2, compare recommendations

## Dependencies

- `ortools` (Google OR-Tools) — CSP solver
- `numpy` — Monte Carlo sampling
- Existing: `f1fantasytools.py` data source (no changes needed)

## Key Design Decisions

1. **Why CP-SAT over LP?** Mixed integer constraints (binary picks + integer transfers), CP-SAT handles this natively and is very fast for this problem size.

2. **Why not just use f1fantasytools optimal?** Their optimizer doesn't model transfers, chips, or budget growth. It's a "build from scratch" optimizer.

3. **Why Monte Carlo?** Expected points are estimates. Sampling from distributions gives us confidence intervals and risk assessment.

4. **Why multi-week?** Chips are season-limited. Using Wildcard in week 3 might be suboptimal if week 15 has a bigger opportunity. Planning ahead captures this.

## Data We Already Have (from f1fantasytools)

- `drv_pts[driver_id]` — expected points per driver (per sim)
- `con_pts[constructor_abbr]` — expected points per constructor
- `drv_prices[abbr]` — current price per driver
- `con_prices[abbr]` — current price per constructor
- `analystSims[0]` — latest sim metadata (raceweek, season, name)

## Open Questions

- [ ] What's the exact F1 Fantasy price change formula? (Need historical data to calibrate)
- [ ] Are there limits on chips per season? (Need to verify rules)
- [ ] Does Final Fix cost a transfer or is it free?
- [ ] Can chips be stacked? (e.g., Extra DRS + Wildcard)
