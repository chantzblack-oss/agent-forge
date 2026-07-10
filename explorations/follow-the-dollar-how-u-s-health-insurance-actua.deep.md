<!-- deep: Teach an MHA (Master of Health Administration) student how health insurance works in the United States and, specifically, how it works in behavioral health — and walk through the ENTIRE healthcare revenue cycle in detail. Cover: how insurance is structured (commercial, Medicare, Medicaid, managed care, self-funded ERISA plans), how money actually flows from premium to provider payment; behavioral-health specifics — mental health parity law and its enforcement gaps, carve-outs and MBHOs, medical necessity and utilization review, network adequacy and ghost networks, reimbursement rates vs medical, CPT codes used in psychotherapy/psychiatry (90837, 90791, etc.); and the full revenue cycle step by step: patient access/scheduling, eligibility and benefits verification, prior authorization, charge capture, coding (CPT/ICD-10/modifiers), claim scrubbing and submission (837/835, clearinghouses), adjudication, denials and the denial management/appeals process, patient billing and collections, payment posting, AR management and the metrics that matter (days in AR, clean claim rate, denial rate, net collection rate). Include where behavioral-health revenue cycles break down most, and what a future administrator should actually watch. -->

# Follow the Dollar: How U.S. Health Insurance Actually Works, and the Four Places Behavioral Health Bleeds

## The verdict

American health insurance is a machine for moving a premium dollar from an employer or a government, through a risk-bearing middleman legally permitted to keep **15–20 cents of it**, and back out to a clinician. Behavioral health — the umbrella term for mental-health and substance-use-disorder (SUD) care — rides the same rails as the rest of medicine but pays a structural toll at every junction. My central claim, **~85% confidence:** behavioral-health revenue cycles do not break because psychiatric billers are worse at their jobs; they break because behavioral health is reimbursed roughly **20–25% below comparable medical care** (RTI International, 22 million lives, 2019–21 data), and nearly every downstream failure — providers quitting insurance networks, patients pushed out-of-network, uncollectable balances, denial pile-ups — is that single upstream fact wearing a different costume. Second claim, **~80%:** the *carve-out* — a plan delegating its mental-health benefit to a separate company — does not create the risk so much as **relocate** it, concentrating eligibility errors, denials, and legal exposure at an organizational "seam" most front desks don't know they're crossing. Third, **~75%:** the federal law meant to force fairness here — mental-health parity — is now **litigated far more than it is enforced**; the 2024 rule that would have given it teeth is, as of early 2026, being abandoned by the very agencies that wrote it. The revenue-cycle *mechanics* — eligibility, prior authorization, coding, the electronic claim, adjudication, remittance, denials, accounts receivable — are well understood, and I describe them with high confidence. The contested question, the one an administrator is paid to answer, is *why behavioral health specifically hemorrhages money as it flows through them.*

---

## 1. Orientation: what "health insurance" even is here

Before any mechanics, the shape of the thing. U.S. health insurance is not one system but four overlapping ones, financed and regulated by different governments. Roughly **66% of Americans have private coverage, ~26% public, and 8.3% — about 28 million people — are uninsured** as of 2025 (CDC/National Health Interview Survey). The categories overlap: a person can hold both Medicare and Medicaid ("dual eligibles"), or employer coverage plus a spouse's plan.

The vocabulary you must own before the money moves:

- **Premium** — the fixed monthly amount paid to *have* coverage, whether or not you use care; an employer usually pays most of it.
- **Deductible** — what the patient pays out of pocket *before* insurance starts paying (say, the first $2,000/year).
- **Copay** — a flat per-visit charge ($30 to see a therapist).
- **Coinsurance** — a percentage the patient owes *after* the deductible (plan pays 80%, patient 20%).
- **Out-of-pocket maximum** — the annual ceiling on patient cost-sharing; above it, the plan pays 100%.
- **In-network** vs **out-of-network (OON)** — whether the provider has signed a contract with the plan agreeing to a discounted rate. This distinction is the hinge on which the entire behavioral-health story turns.

> **The load-bearing fact of the whole document:** for an *in-network* claim, the provider's "charge" is largely fiction. Payment equals the contractually **allowed amount**; the difference between the billed charge and the allowed amount is erased as a **contractual adjustment** — a write-off the provider agreed to in advance. Charges do not drive payment. Contracts do.

## 2. The five structures you must be able to tell apart

An administrator-in-training — an MHA (Master of Health Administration) student — who confuses these will misdiagnose every problem downstream. Note the last row especially: it is the one most people get wrong about their own coverage.

| Structure | Who bears the risk / runs it | Who's covered | Governing rule | The behavioral-health catch |
|---|---|---|---|---|
| **Commercial (fully insured)** | A private insurer takes the premium and the risk | Employees at firms that "buy" insurance; individual ACA marketplace | State insurance law + ACA | Subject to state parity mandates and network-adequacy rules |
| **Medicare** | Federal government | People 65+ and some disabled | Federal (CMS) | **The parity law does *not* apply to traditional Medicare** |
| **Medicaid** | Federal + state jointly | Low-income; ~72–75% now in managed care | Federal floor + state design | Where most BH carve-outs live; rules vary wildly by state |
| **Managed care (MCO/MA)** | An insurer paid a fixed per-member fee to manage care | Medicare Advantage = **54% of Medicare (34.1M, 2025)**; most Medicaid | Contract + federal rules | Uses networks, prior auth, utilization review — the friction machinery |
| **Self-funded (ERISA)** | **The employer** pays claims from its own money; hires an insurer only to *administer* | **61% of covered workers (2025)**; ~8 in 10 at large firms | Federal **ERISA / Dept. of Labor** — *exempt from state mandates* | The single biggest blind spot in parity enforcement |

**ERISA** — the Employee Retirement Income Security Act of 1974 — is the term to learn cold. When a large employer "self-funds," it isn't buying insurance; it pays its workers' medical bills directly and rents an insurer's network and paperwork (an "administrative services only," or ASO, arrangement). Because ERISA governs these plans federally, **state insurance mandates and many consumer protections simply do not apply.** The average family premium hit **~$26,993 in 2025** (KFF Employer Health Benefits Survey), of which the worker paid about a quarter — but for most workers that "premium" is really a budgeting fiction over the employer's self-insured pool. Hold onto this: the parity battles later in this document are fought precisely over these plans.

## 3. How the money actually flows: premium to provider

The macro-constraint on the whole flow is a single ratio. Under the ACA's **Medical Loss Ratio (MLR)** rule — the "80/20 rule" — an insurer must spend **at least 80%** of premium (individual and small-group) or **85%** (large-group) on medical care and quality improvement, or **rebate the difference**. Those rebates ran roughly **$1.1–1.6 billion in 2024**, and about **$12.7 billion cumulatively since 2012**. The rule caps what the middleman keeps: **15–20 cents of every premium dollar** for administration and profit; the rest must become care.

<svg viewBox="0 0 800 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="How a premium dollar splits: insurers keep up to 15-20 cents, at least 80-85 cents must go to care, and the provider receives the allowed amount after a contractual write-off">
  <defs>
    <marker id="ah1" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#6b8893"/></marker>
  </defs>
  <text x="20" y="40" font-size="24" font-weight="700" fill="#1d3038">The premium dollar, split</text>
  <rect x="20" y="150" width="150" height="90" rx="10" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="95" y="188" font-size="21" fill="#1d3038" text-anchor="middle">Premium</text>
  <text x="95" y="214" font-size="24" font-weight="700" fill="#1d3038" text-anchor="middle">$1.00</text>
  <line x1="170" y1="195" x2="255" y2="195" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah1)"/>
  <rect x="258" y="150" width="170" height="90" rx="10" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="343" y="188" font-size="21" fill="#1d3038" text-anchor="middle">Insurer /</text>
  <text x="343" y="214" font-size="21" fill="#1d3038" text-anchor="middle">health plan</text>
  <line x1="428" y1="170" x2="520" y2="95" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah1)"/>
  <rect x="523" y="55" width="257" height="80" rx="10" fill="#ff7a5e" stroke="#ff7a5e"/>
  <text x="651" y="90" font-size="20" font-weight="700" fill="#ffffff" text-anchor="middle">Retention: admin + profit</text>
  <text x="651" y="116" font-size="20" font-weight="700" fill="#ffffff" text-anchor="middle">≤ 15–20¢  (the MLR cap)</text>
  <line x1="428" y1="220" x2="520" y2="290" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah1)"/>
  <rect x="523" y="255" width="257" height="80" rx="10" fill="#ffffff" stroke="#0e8ea3" stroke-width="2.5"/>
  <text x="651" y="290" font-size="20" font-weight="700" fill="#0e8ea3" text-anchor="middle">Care + quality</text>
  <text x="651" y="316" font-size="20" font-weight="700" fill="#0e8ea3" text-anchor="middle">≥ 80–85¢  → provider</text>
  <text x="523" y="375" font-size="18" fill="#6b8893">Provider is paid the </text>
  <text x="523" y="396" font-size="18" fill="#6b8893">allowed amount; the rest is written off.</text>
</svg>

So the flow is: **employer/government → premium → insurer (keeps ≤15–20¢) → claims pool → provider paid the allowed amount → the gap between billed and allowed vanishes as a contractual adjustment.** The rest of this document — the revenue cycle — is the machinery for getting that allowed amount out of the insurer and into the practice's account, and for chasing the patient's share (deductible, copay, coinsurance) separately.

## 4. The revenue cycle, end to end

The **revenue cycle** is the full lifecycle of a patient encounter as a financial event — from the call to schedule to the moment the last dollar is collected or written off. Think of it as a relay race: drop the baton at any leg and the money never arrives. The plumbing is standardized — HIPAA mandates a set of **EDI (Electronic Data Interchange)** transactions, numbered by the X12 standards body, that carry each step.

<svg viewBox="0 0 800 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The revenue cycle as an S-shaped pipeline of twelve stages with EDI transaction codes">
  <defs>
    <marker id="ah2" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#6b8893"/></marker>
  </defs>
  <!-- Row 1 -->
  <rect x="20" y="30" width="170" height="74" rx="9" fill="#ffffff" stroke="#0e8ea3" stroke-width="2.5"/>
  <text x="105" y="62" font-size="20" fill="#1d3038" text-anchor="middle">Patient access</text>
  <text x="105" y="85" font-size="20" fill="#1d3038" text-anchor="middle">&amp; scheduling</text>
  <rect x="210" y="30" width="170" height="74" rx="9" fill="#ffffff" stroke="#0e8ea3" stroke-width="2.5"/>
  <text x="295" y="62" font-size="20" fill="#1d3038" text-anchor="middle">Eligibility</text>
  <text x="295" y="85" font-size="19" fill="#0e8ea3" text-anchor="middle">270 / 271</text>
  <rect x="400" y="30" width="170" height="74" rx="9" fill="#ffffff" stroke="#0e8ea3" stroke-width="2.5"/>
  <text x="485" y="62" font-size="20" fill="#1d3038" text-anchor="middle">Prior auth</text>
  <text x="485" y="85" font-size="19" fill="#0e8ea3" text-anchor="middle">278</text>
  <rect x="590" y="30" width="170" height="74" rx="9" fill="#ffffff" stroke="#0e8ea3" stroke-width="2.5"/>
  <text x="675" y="62" font-size="20" fill="#1d3038" text-anchor="middle">Charge</text>
  <text x="675" y="85" font-size="20" fill="#1d3038" text-anchor="middle">capture</text>
  <line x1="190" y1="67" x2="208" y2="67" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <line x1="380" y1="67" x2="398" y2="67" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <line x1="570" y1="67" x2="588" y2="67" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <line x1="675" y1="104" x2="675" y2="161" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <!-- Row 2 -->
  <rect x="590" y="163" width="170" height="74" rx="9" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="675" y="195" font-size="20" fill="#1d3038" text-anchor="middle">Coding</text>
  <text x="675" y="218" font-size="18" fill="#6b8893" text-anchor="middle">CPT · ICD-10</text>
  <rect x="400" y="163" width="170" height="74" rx="9" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="485" y="195" font-size="20" fill="#1d3038" text-anchor="middle">Claim scrub</text>
  <text x="485" y="218" font-size="18" fill="#6b8893" text-anchor="middle">clearinghouse</text>
  <rect x="210" y="163" width="170" height="74" rx="9" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="295" y="195" font-size="20" fill="#1d3038" text-anchor="middle">Submit claim</text>
  <text x="295" y="218" font-size="19" fill="#0e8ea3" text-anchor="middle">837</text>
  <rect x="20" y="163" width="170" height="74" rx="9" fill="#ff7a5e" stroke="#ff7a5e"/>
  <text x="105" y="195" font-size="20" font-weight="700" fill="#ffffff" text-anchor="middle">PAYER</text>
  <text x="105" y="218" font-size="19" fill="#ffffff" text-anchor="middle">adjudication</text>
  <line x1="588" y1="200" x2="572" y2="200" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <line x1="398" y1="200" x2="382" y2="200" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <line x1="208" y1="200" x2="192" y2="200" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <line x1="105" y1="237" x2="105" y2="294" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <!-- Row 3 -->
  <rect x="20" y="296" width="170" height="74" rx="9" fill="#ffffff" stroke="#6b8893" stroke-width="2.5"/>
  <text x="105" y="328" font-size="20" fill="#1d3038" text-anchor="middle">Remittance</text>
  <text x="105" y="351" font-size="18" fill="#0e8ea3" text-anchor="middle">835 · CARC</text>
  <rect x="210" y="296" width="170" height="74" rx="9" fill="#ffffff" stroke="#6b8893" stroke-width="2.5"/>
  <text x="295" y="328" font-size="20" fill="#1d3038" text-anchor="middle">Denials &amp;</text>
  <text x="295" y="351" font-size="20" fill="#1d3038" text-anchor="middle">appeals</text>
  <rect x="400" y="296" width="170" height="74" rx="9" fill="#ffffff" stroke="#6b8893" stroke-width="2.5"/>
  <text x="485" y="328" font-size="20" fill="#1d3038" text-anchor="middle">Patient</text>
  <text x="485" y="351" font-size="20" fill="#1d3038" text-anchor="middle">billing</text>
  <rect x="590" y="296" width="170" height="74" rx="9" fill="#ffffff" stroke="#6b8893" stroke-width="2.5"/>
  <text x="675" y="328" font-size="20" fill="#1d3038" text-anchor="middle">Posting &amp;</text>
  <text x="675" y="351" font-size="20" fill="#1d3038" text-anchor="middle">A/R</text>
  <line x1="190" y1="333" x2="208" y2="333" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <line x1="380" y1="333" x2="398" y2="333" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
  <line x1="570" y1="333" x2="588" y2="333" stroke="#6b8893" stroke-width="2.5" marker-end="url(#ah2)"/>
</svg>

**The front end (where most money is lost, quietly):**

- **Patient access & scheduling** — capturing demographics and insurance at first contact. A mistyped member ID or a stale plan surfaces weeks later as a denial.
- **Eligibility & benefits verification** — an automated **270** inquiry to the payer returns a **271** confirming active coverage, deductible status, copay, and — critically for behavioral health — *whether this benefit is even administered by the plan on the card.*
- **Prior authorization** — for many services the payer must pre-approve care, requested via a **278**. This is where **utilization review (UR)** — the payer's judgment of whether care is warranted — first bites.

**The middle (turning care into a claim):**

- **Charge capture** — recording what was done so it can be billed.
- **Coding** — translating the encounter into standardized codes: **CPT** (Current Procedural Terminology — *what* was done, e.g., a 45-minute therapy session), **ICD-10** (International Classification of Diseases, 10th revision — the diagnosis, the *why*), and **modifiers** (two-character suffixes adding context: telehealth, an unusual circumstance, place of service).
- **Claim scrubbing & submission** — the coded claim becomes an **837** electronic file, routed through a **clearinghouse** — a middleman that validates ("scrubs") the 837 against format and payer rules and bounces errors back *before* the payer sees it. A claim that passes cleanly on the first try is a **clean claim.**

**The payer and the back end (getting paid, or fighting for it):**

- **Adjudication** — the payer decides: pay, reduce, or deny, applying the contract and its medical-necessity criteria.
- **Remittance** — the payer returns an **835** (electronic remittance advice, or ERA) explaining what was paid and why. Adjustments carry **CARC/RARC** codes (Claim/Remittance Adjustment Reason Codes) — the terse reason strings ("CO-197: authorization absent") a good biller reads like a doctor reads a chart.
- **Denial management & appeals** — reworking and resubmitting denied claims. Much denied revenue is *recoverable*, but a large share is **never reworked** for lack of staff time — so the loss is operational, not inevitable.
- **Patient billing & collections** — chasing the patient's share (deductible/copay/coinsurance).
- **Payment posting & A/R management** — recording payments and working the **accounts receivable (A/R)**: money owed but not yet collected.

## 5. The metrics that matter

You cannot manage what you don't instrument. The HFMA (Healthcare Financial Management Association) publishes the industry-standard **MAP Keys — 29 KPIs (key performance indicators) across five groups** (Patient Access, Pre-Billing, Claims, Account Resolution, Financial Management). Five numbers carry most of the diagnostic weight. Treat the benchmarks as *commonly cited targets that vary by source and specialty*, not gospel.

| KPI | What it measures | Good | Excellent | The catch |
|---|---|---|---|---|
| **Days in A/R** | Avg days a claim stays unpaid | 30–40 | < 30 | Rises when denials or patient balances clog the pipe |
| **A/R > 90 days** | Share of receivables aging out | < 10% | < 5% | Old A/R rarely collects; it's a leading indicator of write-offs |
| **Clean claim rate** | Claims accepted on first pass | 95%+ | 98%+ | Front-end quality shows up here first |
| **Denial rate** | Claims denied by payers | 5–10% (avg) | < 5% | The single most actionable BH lever |
| **Net collection rate** | Collected ÷ *collectable* (after contractual write-offs) | 95%+ | 97%+ | Isolates what you failed to collect from what you agreed to forgo |

The **net collection rate** is the honest one: it strips out the contractual adjustments you agreed to and asks how much of the *actually owed* money you captured. In behavioral health, that is where the story lands — because, as we'll see, an ever-larger slice of BH revenue is owed by *patients*, and patient dollars are the least collectable money in medicine.

## 6. Now behavioral health: the codes and the coding traps

Behavioral health has its own CPT vocabulary, and mis-picking a code is a top denial cause. The core set every MHA student should recognize:

| CPT code | What it is | Rule / time | Watch |
|---|---|---|---|
| **90791** | Psychiatric diagnostic evaluation, *no* medical services | The intake; any licensed clinician | Often limited to one per episode |
| **90792** | Diagnostic evaluation *with* medical services | MD / NP / PA only | Intake that includes medication assessment |
| **90832 / 90834 / 90837** | Individual psychotherapy | 30 / 45 / 60 min (16–37 / 38–52 / **53+**) | **90837 is the most-audited psych code** |
| **90833 / 90836 / 90838** | Psychotherapy *add-on* to a med-management visit | Same times, billed *with* an E/M code | For psychiatrists doing therapy + meds |
| **90846 / 90847** | Family psychotherapy *without* / *with* patient present | ~50 min | Payers scrutinize which one |
| **90853** | Group psychotherapy | Per session | Lower per-head reimbursement |
| **90785** | Interactive complexity | Add-on only | Extra work (e.g., interpreter, high conflict) |
| **99202–99215** | Evaluation & Management (E/M) | By complexity or time | Psychiatrist "med checks" |

> **The 90837 trap:** the 60-minute therapy code (**90837**) pays more than the 45-minute code (**90834**) — so payers flag, audit, and *downcode* it. A provider whose 90837 use runs above roughly **65–70%** of sessions draws scrutiny; **Cigna** has automatically downcoded 90837 to 90834. The defense is documentation of time and medical necessity. This isn't a billing footnote — it's a payer using the coding layer to quietly cut the rate.

Two more coding facts to know. First, **place-of-service and telehealth modifiers** (POS 10 for the patient's home, POS 02 elsewhere, modifier 95 for synchronous telehealth) are a live denial source as pandemic-era flexibilities expire and payer rules shift. Second, **"incident-to" billing** — a therapist's services billed under a supervising physician's higher rate — carries strict supervision rules and is a favorite audit target.

## 7. The rate → network → collection loop

This is the mechanism behind my verdict, documented end to end — a single self-reinforcing cycle:

<svg viewBox="0 0 800 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="A four-stage self-reinforcing loop: low rates cause network exit, which pushes patients out of network, which shifts revenue to uncollectable patient balances">
  <defs>
    <marker id="ah3" markerWidth="11" markerHeight="11" refX="8" refY="3.2" orient="auto"><path d="M0,0 L8,3.2 L0,6.4 Z" fill="#ff7a5e"/></marker>
  </defs>
  <rect x="250" y="18" width="300" height="76" rx="12" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="400" y="50" font-size="20" font-weight="700" fill="#1d3038" text-anchor="middle">1. Low in-network rates</text>
  <text x="400" y="76" font-size="19" fill="#6b8893" text-anchor="middle">BH ~20–25% below medical</text>
  <rect x="540" y="162" width="248" height="76" rx="12" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="664" y="194" font-size="20" font-weight="700" fill="#1d3038" text-anchor="middle">2. Providers exit</text>
  <text x="664" y="220" font-size="19" fill="#6b8893" text-anchor="middle">55% psychiatrists accept</text>
  <rect x="250" y="306" width="300" height="76" rx="12" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="400" y="338" font-size="20" font-weight="700" fill="#1d3038" text-anchor="middle">3. Patients pushed OON</text>
  <text x="400" y="364" font-size="19" fill="#6b8893" text-anchor="middle">3.5–10.6× more than medical</text>
  <rect x="12" y="162" width="248" height="76" rx="12" fill="#ffffff" stroke="#1d3038" stroke-width="2.5"/>
  <text x="136" y="194" font-size="20" font-weight="700" fill="#1d3038" text-anchor="middle">4. Patient A/R + cash</text>
  <text x="136" y="220" font-size="19" fill="#6b8893" text-anchor="middle">collect &lt; 50%</text>
  <path d="M550,66 Q680,90 690,158" fill="none" stroke="#ff7a5e" stroke-width="3" marker-end="url(#ah3)"/>
  <path d="M640,240 Q560,300 470,304" fill="none" stroke="#ff7a5e" stroke-width="3" marker-end="url(#ah3)"/>
  <path d="M250,344 Q120,300 128,240" fill="none" stroke="#ff7a5e" stroke-width="3" marker-end="url(#ah3)"/>
  <path d="M150,160 Q230,92 320,82" fill="none" stroke="#ff7a5e" stroke-width="3" marker-end="url(#ah3)"/>
  <text x="400" y="205" font-size="18" font-style="italic" fill="#0e8ea3" text-anchor="middle">self-reinforcing</text>
</svg>

**Link 1 — the rate gap (root cause).** The best source is **Mark & Parish, "Behavioral Health Parity: Pervasive Disparities in Access to In-Network Care Continue," RTI International (2024)**, peer-reviewed in *Psychiatric Services* — claims on **>22 million lives, all 50 states, 2019–21.** For the *same office-visit codes*, in-network reimbursement ran **22% lower for behavioral clinicians on average, 48% lower at the 75th percentile, 70% lower at the 95th.** The kicker: **physician assistants were paid 19% more, and nurse practitioners 8% more, than psychiatrists** for the same office visits — a mid-level medical provider out-earning an MD psychiatrist per visit. The trend anchor, **Milliman (2019)**, found primary-care visits reimbursed **23.8% higher** than behavioral in 2017. Two studies, same method, five years apart: **23.8% → 22%** — flat, despite parity law on the books since 2008. *(Carry this disclosure: both studies were funded by mental-health advocacy organizations. The methods are robust and the direction is corroborated elsewhere — but disclose the funding.)*

**Link 2 — network exit (the mechanism).** Low rates make in-network participation bad business. **Bishop et al., JAMA Psychiatry (2014):** only **55.3% of psychiatrists accepted commercial insurance vs. 88.7% of other physicians** — down from **72.3%** in 2005–06, a 17-point collapse. Psychiatry is the specialty *least* likely to take insurance, and the gap hasn't closed.

**Link 3 — the out-of-network shift (the consequence).** RTI (2024): patients went out-of-network **3.5× more** for a behavioral clinician, **8.9× for a psychiatrist, and 10.6× for a psychologist** than for medical/surgical care. And the network is often *fake even when it exists* — see ghost networks in §9.

**Link 4 — the collection shift (cost exported to the patient).** Here is the misdirection: the plan advertises "coverage," but the low in-network rate pushes the patient out-of-network — and *the patient ends up paying.* The **No Surprises Act does not cover office-based mental health** — a therapist's or psychiatrist's office sits explicitly outside its balance-billing protections — so cash-pay, superbills (an itemized receipt the patient submits for OON reimbursement), and balance billing stay legal. That revenue lands as **patient A/R**, where money goes to die: patient responsibility has risen from **1–2% to over 10%** of provider revenue in a decade, average patient collection runs about **47.6%**, and only about **12% of practices collect at the time of service.** A behavioral-health practice is the worst case — recurring low-dollar visits, patients in financial distress, high no-show rates. The shift from clean payer A/R (95%+ collectable) to patient A/R (<50%) *is* the revenue-cycle crisis.

| Disparity metric | Behavioral | Medical/surgical | Source |
|---|---|---|---|
| In-network office-visit rate | baseline | **+22%** avg / +48% (75th) / +70% (95th) | RTI 2024 |
| Out-of-network use | **3.5–10.6×** higher | baseline | RTI 2024 |
| Insurance acceptance (psychiatry) | **55.3%** | 88.7% | Bishop 2014 |
| Prior-auth problems reported | **26%** | 13% | KFF consumer survey |
| Directory listings unavailable | **up to 72–80%** | — | Senate Finance / HHS-OIG 2025 |

## 8. Parity law and the enforcement gap

**MHPAEA** — the Mental Health Parity and Addiction Equity Act of 2008 — is the law everyone invokes and most people misunderstand. Three corrections up front:

- Parity does **not** mean equal coverage or equal pay. It governs the *comparability of limits*, not reimbursement rates directly, and doesn't require a plan to offer mental-health benefits at all.
- It does **not** apply to traditional Medicare.
- A listing in a provider directory is **not** proof of an available network.

The law's teeth are the **NQTLs — Non-Quantitative Treatment Limitations:** the non-numeric ways a plan restricts care — prior-authorization rules, medical-necessity criteria, network composition, reimbursement methodology. Under MHPAEA these must be applied **"no more stringently"** to mental-health/SUD care than to medical/surgical care. Prior authorization is the cleanest example: KFF's consumer survey found **26% of people seeking mental-health care hit prior-auth problems versus 13%** for other care — roughly **2×.**

> **A number you'll see everywhere and should not repeat:** industry blogs claim behavioral health "requires prior authorization 5.4× more often." That figure is unsourceable and looks like a transcription error — 5.4 is the ratio of Milliman's *out-of-network* rates (17.2% ÷ 3.2%), which migrated into a prior-auth sentence and propagated. Use the defensible **~2×** instead: a number that spreads because everyone repeats it is not one anyone has verified.

**How enforcement actually works — through courts, not rulebooks.** Two landmark actions define the real check on payer behavior:

- ***Wit v. United Behavioral Health*** — the archetype. In 2019, Judge Joseph Spero (N.D. Cal.) found UBH's internal **Level of Care Guidelines inconsistent with generally accepted standards of care (GASC)** — biased toward covering only acute, crisis-level care rather than chronic and co-occurring conditions — in breach of ERISA fiduciary duty. State the posture precisely, because it's easy to get wrong: the Ninth Circuit **vacated the retrospective remedy**, **rejecting "reprocessing" of ~67,000 claims as an available ERISA remedy**, and the district court confirmed in August 2025 that reprocessing is off the table. But the **fiduciary-breach finding and prospective relief survived and were reaffirmed:** on **February 3, 2026, the court extended the injunction five years, to February 3, 2031**, requiring GASC-consistent criteria. The lesson is *stronger*, not weaker, than a hedge implies — the parity failure lived inside the carve-out's own criteria, and a court is now supervising them into 2031.
- **The Optum/UBH $15.6M settlement (2021)** — DOL and the New York Attorney General jointly found UBH had **cut out-of-network mental-health reimbursement rates** (a penalty not applied to medical/surgical) and run an **algorithm ("ALERT")** to trigger utilization review on outpatient mental-health care specifically. Payout: **$13.6M to members plus ~$2M in penalties**; the state cited ~20,000 denied New Yorkers.

**And the federal rulemaking meant to systematize all this is being abandoned.** The **2024 MHPAEA Final Rule** (effective November 22, 2024) for the first time named network composition, reimbursement rates, and network adequacy as explicit NQTLs and demanded comparative analyses. Then: large ERISA employers (via **ERIC**, the ERISA Industry Committee) sued in January 2025; the agencies issued a **non-enforcement statement on May 15, 2025**; and by **March 30, 2026 they told the court they would no longer defend the rule**, targeting a rescission proposal by December 31, 2026. The rule is functionally dead.

The honest balance: this is **not** the same as "parity is unenforced." The underlying **2013 rule and the CAA-2021 (Consolidated Appropriations Act) NQTL comparative-analysis requirement remain fully in force**, and mental-health parity is still a stated FY2026 enforcement priority for **EBSA** (the Labor Department's Employee Benefits Security Administration, which polices these plans). But EBSA is thin: a DOL-OIG report (September 2025) found NQTL reviews take **up to three years**, the supplemental enforcement funding **lapsed at the end of 2024**, and in one reporting period EBSA issued **zero final determinations of noncompliance**, preferring voluntary correction. So the real check is litigation and state AGs — and it reaches everyone *except* the self-funded ERISA plans that dominate the market, precisely the segment the 2024 rule was meant to reach.

## 9. Carve-outs, MBHOs, and ghost networks: where the risk actually lives

Here is the structural choice that relocates everything. A **carve-out** is when a health plan, employer, or state Medicaid agency **delegates** its mental-health/SUD benefit to a separate company — an **MBHO (Managed Behavioral Health Organization)** — which runs its own network, prior-authorization rules, medical-necessity criteria, and claims adjudication, while the parent plan keeps medical/surgical. A **carve-in** folds behavioral health into the same organization that manages the rest. The **"Big Three" MBHOs**: **Optum Behavioral Health** (UnitedHealth; home of the UBH in *Wit*), **Carelon Behavioral Health** (Elevance; formerly Beacon), and **Magellan Health** (heavy in Medicaid, federal, and specialty).

> **The operational seam — the crux mechanic:** each MBHO maintains its **own payer ID, its own EDI enrollment, its own eligibility (270/271) path, and its own 835 remittance stream.** So behind a single member ID card sit **two separate 837→835 loops** — one for the body, one for the mind. The card usually shows the *medical* plan; calling that plan's eligibility line does *not* surface the carved-out behavioral benefit.

That seam is where three specific failures concentrate:

- **Eligibility errors** — verification becomes a *two-payer* task. The front desk must first *detect* the carve-out, then route the 270/271 and the auth request to the MBHO, not the medical carrier. Miss it and you've billed the wrong payer.
- **Denials** — a large share of behavioral denials trace to causes that exist *only because of the seam*: authorization from the wrong entity, claims sent to the parent instead of the MBHO, stale MBHO payer IDs after a contract change. *(Industry-reported denial ranges — commonly 15–25% for BH vs. 5–10% for medical — come from billing-vendor blogs that cite each other and are mutually inconsistent; treat them as illustrative. The rigorously sourced disparities are the KFF prior-auth 2× and the RTI rate/OON gaps.)*
- **Parity exposure** — the MBHO is the entity that *designs and applies* the UM criteria, the network, and the reimbursement methodology. That is exactly why *Wit* and the Optum settlement both landed inside the carve-out. The parity risk lives where the NQTLs are set.

**Ghost networks** make the network NQTL concrete. A **ghost network** is a directory padded with providers who are unreachable, not accepting patients, or not actually in-network — the listing exists; the access doesn't. The **Senate Finance Committee's 2023 secret-shopper study** booked an appointment only **18% of the time** (>80% "ghosts"). The **HHS Office of Inspector General (October 2025)** found plans **inaccurately listed 72% of in-network behavioral providers as available, 55% did not serve a single enrollee, and the average Medicare Advantage plan contracted only 16% of the behavioral providers in its area.** Enforcement is live: the **New York AG–EmblemHealth settlement (2026)** — $2.5M, an independent monitor, and a two-day directory-correction rule — followed a finding that **over 80% of listed behavioral providers were effectively unavailable.** In a carve-out, the MBHO owns that thin network.

Prevalence is a moving target — and definitional. At the commercial peak around 2000, roughly **two-thirds of the insured** got behavioral care via carve-out. Today in Medicaid, **OPEN MINDS counts ~8–9 states** with primary behavioral carve-outs to specialty organizations, **down from 15 in 2011** — a clear drift toward carve-in — even as **"vertical carve-outs"** for specific populations (serious mental illness, SUD, autism) grow. California is the teaching case: **Medi-Cal (California's Medicaid)** still carves out *specialty* mental health to county plans while non-specialty sits in the MCO, creating a mild-vs-severe routing seam of its own.

## 10. Where the behavioral-health cycle breaks first

Four candidate failure points compete for "breaks first." My ranking, and the KPI each lights up:

1. **Front-end eligibility at the carve-out seam** *(cheapest to fix, most common).* Wrong-payer routing seeds denials weeks downstream. **Instrument: clean claim rate.** The highest-leverage control in behavioral-health RCM (revenue-cycle management) is a carve-out-detection step *before* scheduling.
2. **Prior authorization and medical necessity** *(most persistent).* Behavioral care is pre-authed roughly 2× as often, and medical necessity is **payer-defined** through proprietary criteria (**MCG, InterQual**; **ASAM** for SUD) — contestable, and the exact lever *Wit* was fought over. **Instrument: denial rate.**
3. **Coding pitfalls** *(most self-inflicted).* 90837 downcoding, missing add-ons, telehealth/POS modifiers, incident-to, time documentation. **Instrument: denial rate + downcoding audit.**
4. **Patient-A/R capacity in small practices** *(most lethal, least visible).* Once revenue shifts OON/cash, a two-person practice simply cannot work the collections. **Instrument: days in A/R and net collection rate.**

## 11. The steelman against my verdict

My verdict says the fragility is *upstream reimbursement adequacy.* The honest opposite — which a smart skeptic would press — is: **"It's operational competence and structure, not rates, and the evidence for the rate thesis is softer than it looks."** The steelman:

- **The cleanest carve-out study cuts the *other* way on integration.** Charlesworth et al., *Health Services Research* (2021), studying Portland-area Medicaid, found carve-*in* enrollees only **+2.39 percentage points more likely** to access outpatient behavioral care — a *small* effect, concentrated in mild/moderate cases and Black enrollees, and carve-in actually produced *less* psychiatrist use. If integration barely moves access, maybe structure isn't the crux.
- **Integrated plans don't clearly outperform.** A January 2024 analysis found **integrated MCOs failed to beat carve-outs** on behavioral access overall — because "carve-in" is often *nominal*: the MCO wins both contracts, then quietly sub-delegates behavioral health to an MBHO anyway. The seam survives inside the org.
- **Where public payers control the dial, rates are *already* rising** — undercutting "the system won't fix rates." **49 states raised Medicaid behavioral rates from 2020–2025** (North Carolina to 100% of Medicare, New Mexico to 150%, Oregon +30%, Washington MCOs mandated +15%), and **Medicare let marriage-and-family therapists and mental-health counselors bill for the first time on January 1, 2024**, with psychotherapy work RVUs (relative value units, the basis of Medicare payment) up **19.1% over four years.** A skeptic says: give it time; the market is correcting.
- **The rate studies are advocacy-funded**, and the denial-rate statistics I lean against are vendor blogs. A disciplined reader discounts both.

Where the steelman lands, honestly: it is strong on *carve-in-doesn't-help* (I concede structure is a *relocator*, not a *cure*) and on *public payers are moving.* It is weak where it matters most — **the commercial/ERISA book, where the working-age dollars sit, hasn't moved in a decade** (23.8% → 22%), and the platforms superficially fixing access are being used to cut rates further. That's why my confidence sits at ~85%, not 95%.

## 12. What would change this answer

Concrete, watchable events — not vibes — that would move the verdict:

- **The commercial rate gap closes.** A third RTI-style study showing the in-network behavioral-vs-medical gap below ~15% would falsify the "flat for a decade" claim and pull the root cause out from under the thesis.
- **The 2024 MHPAEA rule is revived or replaced with teeth.** If the ERIC litigation fails and the network-adequacy/reimbursement NQTLs become enforceable — or a future administration re-proposes them — commercial plans face real pressure and the "litigated-not-enforced" claim weakens.
- **The platforms reverse.** If the therapist-network platforms — Headway, Alma, Rula, Grow — are shown to be *raising* net per-session pay rather than serving as Optum/Cigna rate-suppression channels (the November 2024 cuts, the reported ~$19–41 loss per session, the Cigna 90837 downcoding), the "cost-export" reading softens.
- **Medicaid raises propagate to commercial.** If state rate floors or a federal benchmark drag commercial rates up, the public-payer exception becomes the rule.
- **Carve-in is shown to *operationally* integrate.** Rigorous evidence that carve-in collapses the eligibility/denial seam (not just merges balance sheets) would upgrade integration from "relocator" to "fix."

## 13. What a future administrator should actually watch

- **Identify the structure on day one, per payer:** carve-out or carve-in — and if carve-in, *is behavioral health sub-delegated to an MBHO behind the scenes?* This one fact designs your entire behavioral-health RCM.
- **Build carve-out detection into eligibility.** Maintain a live MBHO payer-ID and clearinghouse-routing table; a silent contract change breaks 837 routing and 835 posting overnight.
- **Segment every KPI by payer *and* by carve-out vs. parent.** The carve-out line will be your worst-performing cohort — and you cannot manage what you don't split out.
- **Track commercial in-network rate as a percent of Medicare, by CPT (90791/90834/90837/90847), over time.** This is the leading indicator of whether your network holds; flat or declining predicts provider attrition → OON → a patient-A/R blowout.
- **Audit your own directory before a regulator or plaintiff does.** Effective access ≠ listed access. The Senate Finance 18%, the HHS-OIG 72%, and the EmblemHealth monitor are your warning.
- **Model per-session net *after* the platform's cut** when contracting through Headway/Alma/Rula — "in-network access" can mask year-over-year rate cuts and downcoding.

**The bottom line:** behavioral-health revenue-cycle fragility is a *reimbursement-adequacy* problem wearing a *revenue-cycle* costume. Fix the commercial rate and the out-of-network → patient-A/R → bad-debt cascade shrinks on its own. Absent that, every downstream RCM improvement — cleaner claims, slicker collections tooling — just optimizes the collection of the least-collectable dollars in medicine.

## Sources, annotated

- [**RTI International / Mark & Parish (2024)**, "Behavioral Health Parity: Pervasive Disparities in Access to In-Network Care Continue"](https://www.rti.org/publication/behavioral-health-parity-pervasive-disparities-access-network-care-continue) — the single best source: peer-reviewed (*Psychiatric Services*), 22M lives, quantifies the rate gap *and* the OON consequence *and* the worsening trend. High trust; disclose advocacy funding.
- [**Milliman / Melek et al. (2019)**, disparity analysis](https://www.ncpsychiatry.org/assets/docs/IntegratedCare/nqtldisparityanalysis%20-%20millman%202017.pdf) — the 2017-data trend anchor (PC paid 23.8% more than BH). Pairs with RTI to show a flat decade. High trust on method; same funder family.
- [**Bishop et al., JAMA Psychiatry (2014)**](https://jamanetwork.com/journals/jamapsychiatry/fullarticle/1785174) — the canonical "55% of psychiatrists accept insurance vs. 89%" finding. Peer-reviewed; the mechanism link.
- [**Senate Finance Committee secret-shopper study (2023)**](https://www.finance.senate.gov/imo/media/doc/050323%20Ghost%20Network%20Hearing%20-%20Secret%20Shopper%20Study%20Report.pdf) — 18% appointment-booking rate; the ghost-network primary document. Congressional staff, direct evidence.
- [**HHS-OIG (October 2025)**, behavioral-health network report](https://oig.hhs.gov/reports/all/2025/many-medicare-advantage-and-medicaid-managed-care-plans-have-limited-behavioral-health-provider-networks-and-inactive-providers/) — the hardest ghost-network data (72% inaccurately listed, 16% contracted). Federal watchdog; newest and most rigorous.
- [**NY AG–EmblemHealth settlement (2026)**](https://ag.ny.gov/press-release/2026/attorney-general-james-secures-sweeping-reforms-improving-access-mental-health) — live enforcement: $2.5M, monitor, 2-day correction rule. Shows AGs, not federal rules, doing the work.
- [**DOL non-enforcement statement (May 2025)**](https://www.dol.gov/agencies/ebsa/laws-and-regulations/laws/mental-health-parity/statement-regarding-enforcement-of-the-final-rule-on-requirements-related-to-mhpaea) — the primary document pausing the 2024 rule. Authoritative; read alongside the 2013-rule caveat.
- [**DOL-OIG (September 2025)**, EBSA parity-enforcement audit](https://www.oig.dol.gov/public/reports/oa/2025/09-25-001-12-001.pdf) — documents 3-year reviews, funding lapse, zero final noncompliance determinations. The enforcement-capacity source.
- [**Wit v. UBH — Ninth Circuit rejects reprocessing (Miller & Chevalier)**](https://www.millerchevalier.com/publication/ninth-circuit-rejects-reprocessing-health-claims-erisa-remedy) and [**BHBusiness on the district-court injunction (2025–26)**](https://bhbusiness.com/2025/08/11/district-court-sides-with-plaintiffs-in-wit-v-united-behavioral-health-after-years-of-appeals/) — together give the *correct* posture: remedy vacated, fiduciary finding and injunction-to-2031 survive.
- [**Optum/UBH $15.6M parity settlement (BHBusiness, 2021)**](https://bhbusiness.com/2021/08/12/unitedhealthcare-to-pay-15-6m-in-parity-settlement-as-dol-picks-up-mhpaea-enforcement/) — the ALERT-algorithm and OON-rate-cut case; the reimbursement-methodology NQTL made concrete.
- [**KFF 2025 Employer Health Benefits Survey**](https://www.kff.org/health-costs/2025-employer-health-benefits-survey/) — premiums (~$26,993 family) and self-funded share (61%). The gold-standard employer-coverage source, updated annually.
- [**KFF Survey of Consumer Experiences with Health Insurance**](https://www.kff.org/affordable-care-act/kff-survey-of-consumer-experiences-with-health-insurance/) — the defensible prior-auth disparity (26% vs. 13%); use this, not the phantom "5.4×."
- [**Charlesworth et al., *Health Services Research* (2021)**](https://onlinelibrary.wiley.com/doi/10.1111/1475-6773.13703) — the cleanest carve-in-vs-carve-out study (+2.39 pp access); anchors the steelman. Peer-reviewed but Medicaid-specific and small-effect.
- [**OPEN MINDS Medicaid carve-out analysis**](https://openminds.com/press/nine-states-with-behavioral-health-carve-outs-to-cmos-remainopen-minds-releases-annual-analysis-on-state-medicaid-behavioral-health-carve-outs/) — the authoritative prevalence tracker (~8–9 states, down from 15). Industry analyst; counts are definitional, so state the rule.
- [**HFMA MAP Keys**](https://www.hfma.org/data-and-insights/map-initiative/map-keys/) and [**APA Services psychotherapy CPT guide**](https://www.apaservices.org/practice/reimbursement/health-codes/psychotherapy) — the standard references for the 29 revenue-cycle KPIs and the behavioral CPT set, respectively.
