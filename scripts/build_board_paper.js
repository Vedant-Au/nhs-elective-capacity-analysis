/*
 * NHS Cheshire and Merseyside ICB: Phase 6 executive board paper.
 *
 * Answer-first: the recommendation and the decision sought sit on page one,
 * the diagnosis that supports them follows. Figures are read from
 * docs/figures/ and embedded at their true aspect ratio.
 *
 * Run:  node scripts/build_board_paper.js
 */
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  ImageRun, PageBreak, Footer, PageNumber, convertInchesToTwip,
} = require('docx');

const FIG = '/tmp/figures';
const OUT = '/tmp/NHS_CM_Elective_Capacity_Board_Paper.docx';

const NAVY = '1F3864';
const GREY = '595959';
const RED = 'C00000';
const FONT = 'Arial';
const CONTENT_W = 600; // px at the document's rendering scale

/* ---------- helpers ---------- */

function pngSize(path) {
  const b = fs.readFileSync(path);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}

function figure(file, caption, source) {
  const p = `${FIG}/${file}`;
  const { w, h } = pngSize(p);
  const height = Math.round((CONTENT_W * h) / w);
  const out = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 160, after: 60 },
      children: [new ImageRun({
        type: 'png',
        data: fs.readFileSync(p),
        transformation: { width: CONTENT_W, height },
      })],
    }),
    new Paragraph({
      spacing: { after: 200 },
      children: [
        new TextRun({ text: caption, font: FONT, size: 16, bold: true, color: GREY }),
        new TextRun({ text: '  ' + source, font: FONT, size: 16, italics: true, color: GREY }),
      ],
    }),
  ];
  return out;
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 320, after: 140 },
    children: [new TextRun({ text, font: FONT, size: 26, bold: true, color: NAVY })],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 220, after: 100 },
    children: [new TextRun({ text, font: FONT, size: 22, bold: true, color: NAVY })],
  });
}

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after === undefined ? 140 : opts.after },
    alignment: opts.align,
    children: [new TextRun({
      text, font: FONT, size: 20,
      bold: opts.bold, italics: opts.italics, color: opts.color,
    })],
  });
}

function rich(runs, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after === undefined ? 140 : opts.after },
    children: runs.map(r => new TextRun({
      text: r.t, font: FONT, size: 20, bold: r.b, italics: r.i, color: r.c,
    })),
  });
}

function bullet(text, opts = {}) {
  return new Paragraph({
    bullet: { level: opts.level || 0 },
    spacing: { after: 80 },
    children: [new TextRun({ text, font: FONT, size: 20, bold: opts.bold })],
  });
}

function cell(text, { bold, fill, width, align, color, size } = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: fill ? { type: ShadingType.CLEAR, fill } : undefined,
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({
        text: String(text), font: FONT, size: size || 18, bold,
        color: color || (fill === NAVY ? 'FFFFFF' : '000000'),
      })],
    })],
  });
}

function table(headers, rows, widths) {
  return new Table({
    columnWidths: widths,
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' },
      left: { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' },
      right: { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: 'D9D9D9' },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: 'D9D9D9' },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((hd, i) => cell(hd, { bold: true, fill: NAVY, width: widths[i] })),
      }),
      ...rows.map(r => new TableRow({
        children: r.map((c, i) => cell(c, {
          width: widths[i],
          align: i === 0 ? undefined : AlignmentType.RIGHT,
          fill: i === 0 ? 'F2F2F2' : undefined,
          bold: i === 0,
        })),
      })),
    ],
  });
}

/* Metadata table: no header band, left-aligned values. */
function plainTable(rows, widths) {
  return new Table({
    columnWidths: widths,
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' },
      left: { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' },
      right: { style: BorderStyle.SINGLE, size: 2, color: 'BFBFBF' },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: 'D9D9D9' },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: 'D9D9D9' },
    },
    rows: rows.map(r => new TableRow({
      children: r.map((c, i) => cell(c, {
        width: widths[i],
        bold: i === 0,
        fill: i === 0 ? 'F2F2F2' : undefined,
      })),
    })),
  });
}

function calloutBox(title, body) {
  return new Table({
    columnWidths: [9026],
    width: { size: 9026, type: WidthType.DXA },
    // A rule above and below rather than a shaded box. The emphasis should
    // come from position on the page, not from decoration.
    borders: {
      top: { style: BorderStyle.SINGLE, size: 8, color: NAVY },
      bottom: { style: BorderStyle.SINGLE, size: 8, color: NAVY },
      left: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
      right: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
    },
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: 9026, type: WidthType.DXA },
        margins: { top: 200, bottom: 200, left: 0, right: 60 },
        children: [
          new Paragraph({
            spacing: { after: 100 },
            children: [new TextRun({ text: title, font: FONT, size: 22, bold: true, color: NAVY })],
          }),
          ...body.map(t => new Paragraph({
            spacing: { after: 90 },
            children: [new TextRun({ text: t, font: FONT, size: 20 })],
          })),
        ],
      })],
    })],
  });
}

/* ---------- document ---------- */

const children = [];

// Title block
children.push(new Paragraph({
  spacing: { after: 60 },
  children: [new TextRun({
    text: 'NHS Cheshire and Merseyside Integrated Care Board',
    font: FONT, size: 20, bold: true, color: GREY,
  })],
}));
children.push(new Paragraph({
  spacing: { after: 40 },
  children: [new TextRun({
    text: 'Elective Recovery: Where to Commit Capacity Funding',
    font: FONT, size: 40, bold: true, color: NAVY,
  })],
}));
children.push(new Paragraph({
  spacing: { after: 240 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: NAVY } },
  children: [new TextRun({
    text: '18 months to September 2027, across 12 core acute and specialist trusts',
    font: FONT, size: 22, color: GREY,
  })],
}));

children.push(plainTable(
  [
    ['Paper for', 'Elective Recovery Programme Board'],
    ['Purpose', 'Decision'],
    ['Date', '11 August 2026'],
    ['Author', 'Strategy and Analytics'],
  ],
  [1800, 7226],
));

children.push(new Paragraph({ spacing: { after: 260 }, children: [] }));

children.push(calloutBox('Decision sought', [
  'The Board is asked to approve Strategy S2, delivering elective recovery entirely through NHS providers and weighted to diagnostic capacity, as the committed programme strategy for the 18 months to September 2027.',
  'This is a decision about risk appetite, not a calculation. The analysis narrows the field to three commitments the model cannot distinguish between, and one genuine alternative (S7) that clears roughly half as many breaches but carries no exposure to the programme\'s weakest assumption. The Board is asked to make that trade-off explicitly.',
  'The Board is further asked to note that the funding envelope, not delivery capacity, is the binding constraint on what this programme can achieve, and to agree the monitoring triggers at paragraph 9.2.',
]));

/* 1. Recommendation */
children.push(h1('1. Recommendation'));

children.push(rich([
  { t: 'Commit to Strategy S2: deliver the elective recovery programme entirely through NHS providers, ', b: false },
  { t: 'weighted to diagnostic capacity while the diagnostic conversion assumption holds', b: true },
  { t: ', with no independent-sector outsourcing.' },
]));

children.push(p('Eight candidate strategies were tested against four scenarios on four objectives: breaches cleared, breaches cleared in higher-deprivation trusts, value for money, and exposure to unsourced delivery assumptions. The analysis produces two findings the Board should hold separately.'));

children.push(rich([
  { t: 'First, three of the eight are the same commitment. ', b: true },
  { t: 'S1 (unconstrained optimisation), S2 (NHS delivery only) and S5 (equity-first) return identical results on every objective in every scenario. Neither the outsourcing lock nor the equity floor ever binds, so the model is genuinely indifferent between them and cannot pick one. The tie has to be broken on grounds the model does not capture. S2 is recommended because it is the most defensible of the three to provider boards and staff side, and it commits to nothing the other two would not also do.' },
]));

children.push(rich([
  { t: 'Second, there is one real alternative, and it is a judgement call. ', b: true },
  { t: 'S7 (treatment capacity only) never touches the two levers whose capacity assumptions are unsourced. It carries zero exposure in every scenario and matches S2 on volume in two of the four. But where diagnostics are efficient it gives up a great deal. It clears 26,581 fewer breaches in the lean-money case, and 106,324 fewer in the funded case. S7 takes first place whenever delivery risk is weighted at twice or three times the other objectives, and S2 leads on every weighting of the three outcome objectives.' },
]));

children.push(rich([
  { t: 'The recommendation is therefore not weight-stable, and that is reported rather than smoothed over. ', b: true },
  { t: 'A Board that regards the diagnostic conversion assumption as unacceptably weak should choose S7 and accept clearing roughly half as many breaches. A Board that accepts the assumption, and the evidence at paragraph 5.1 supports accepting it, should choose S2.' },
]));

children.push(rich([
  { t: 'What it delivers on current planning assumptions: ' },
  { t: '60,649 fewer over-52-week breaches over 18 months, at a cost of £15m. That is around 20% of the projected backlog of 296,284.', b: true },
  { t: ' The figure scales close to linearly with the envelope, because funding rather than capacity is what limits it.' },
]));

/* 2. What this rules out */
children.push(h1('2. What this analysis rules out'));

children.push(p('Three questions that have absorbed significant discussion are not, on this analysis, live decisions at the funding levels under consideration. Each was tested and each moves the outcome by nothing.'));

children.push(bullet('Whether the independent sector can scale. It does not matter. The independent-sector capacity ceiling does not begin to bind until the envelope exceeds £31.9m.'));
children.push(bullet('Whether NHS in-house productivity can be lifted by 5% or 25%. It does not matter within this envelope. That ceiling does not bind below £107.1m.'));
children.push(bullet('Whether the backlog turns out at the optimistic or pessimistic end of the forecast. It does not change the allocation. The budget clears roughly a fifth of the backlog either way, so the backlog is never the constraint.'));

children.push(rich([
  { t: 'The reason is structural and is set out at Figure 2: ', },
  { t: 'within the funding range under consideration this is not a capacity-constrained problem at all. It is a money-constrained one.', b: true },
]));

children.push(new Paragraph({ children: [new PageBreak()] }));

/* 3. Diagnosis */
children.push(h1('3. The position we are starting from'));

children.push(p('The waiting list across the 12 core trusts stands at 686,298, having grown 110% since April 2019. It has never returned to its pre-pandemic level of 382,688, and the central forecast does not bring it back within the planning horizon.'));

children.push(...figure('fig1_backlog.png',
  'Figure 1. The waiting list has not recovered and is not forecast to.',
  'Source: NHS England RTT, 12 core trusts, Apr-2019 to Mar-2026. Forecast is the project Monte Carlo model, p5–p95.'));

children.push(p('The longest waits have improved markedly from their peak: over-52-week waits are 7,836, down from 31,032 in March 2024. But 35.5% of the list is still waiting beyond 18 weeks, against 15.0% before the pandemic. The improvement is real and is not in dispute. What is in dispute is what to do next with a constrained recovery budget.'));

children.push(h2('3.1 Pressure is not evenly distributed, and deprivation does not explain it'));

children.push(p('Provider-level pressure varies substantially across the ICB, but the relationship with catchment deprivation is weaker than expected and does not survive scrutiny. The correlation between deprivation and composite pressure is positive but not statistically significant (Spearman rho 0.49, p = 0.11, n = 12), and it weakens further once the five regional specialist centres are excluded (rho 0.31, p = 0.50, n = 7).'));

children.push(rich([
  { t: 'One inequality relationship is significant, and it runs against the intuitive direction: more-deprived catchments have ' },
  { t: 'more', b: true },
  { t: ' consultants per 1,000 FTE, not fewer (rho −0.59, p = 0.044). This should not be read as evidence that deprivation is being adequately served. It more likely reflects the concentration of specialist and teaching capacity in Liverpool and Knowsley. It does mean that a simple "under-resourced deprived areas" framing is not supported by this data.' },
]));

/* 4. Money not capacity */
children.push(h1('4. Funding, not capacity, is the binding constraint'));

children.push(p('Each of the three delivery levers has a capacity ceiling, meaning how much additional activity it could physically absorb over 18 months. Converting those ceilings into the funding required to reach them shows that all three sit far above the range under discussion.'));

children.push(...figure('fig2_money_not_capacity.png',
  'Figure 2. Every capacity ceiling lies beyond the funding range under consideration.',
  'Source: Phase 3 capacity model; ceilings derived from trust activity, bed headroom (KH03) and independent-sector activity.'));

children.push(p('This has a direct consequence for how the Board should spend its time. Debates about deliverability, whether providers could absorb more or whether the independent sector could flex, are not what limits this programme. The size of the settlement is. Every additional £1m buys roughly 4,000 further breaches cleared on current assumptions, and continues to do so well past £30m.'));

/* 5. The real decision */
children.push(h1('5. The decision that actually matters'));

children.push(p('With capacity ruled out as a constraint, the allocation reduces to a single question: which lever clears a pathway most cheaply. In-house treatment and independent-sector outsourcing are priced identically under the 2025/26 NHS Payment Scheme, at £472.49 per completed pathway. The diagnostic lever is priced at £247.32, but that figure depends on an assumption that one unlocked pathway requires 1.75 diagnostic tests.'));

children.push(rich([
  { t: 'That figure has no published source. It is the only number of its kind left in the model, and the entire allocation turns on it.', b: true },
]));

children.push(...figure('fig3_tipping_point.png',
  'Figure 3. The allocation is decided by one unsourced parameter.',
  'Source: Phase 5 scenario model. Tipping point verified two ways, closed form and bisection, agreeing to four significant figures.'));

children.push(p('Below 3.34 tests per pathway, diagnostics are the cheapest route to a cleared pathway and the programme should be diagnostic-led. Above 3.34, the diagnostic lever is dominated and the programme should buy treatment capacity instead. The working assumption of 1.75 sits below that threshold, but not so far below that it can be taken on trust.'));

children.push(h2('5.1 What our own data says about that parameter'));

children.push(p('The warehouse can bound the question, though not settle it. Dividing total DM01 diagnostic activity by completed RTT pathways across the 12 trusts gives an observed ratio of 0.84 over the last 12 months and 0.76 across the full 84-month window. It has never exceeded 0.92 in any single month.'));

children.push(...figure('fig5_conversion.png',
  'Figure 4. Observed diagnostic conversion has never approached the level that would reverse the recommendation.',
  'Source: NHS England DM01 and RTT, 12 core trusts, 84 months.'));

children.push(rich([
  { t: 'This must be read carefully, and it is not proof. ', b: true },
  { t: 'DM01 excludes pathology entirely, so it understates diagnostic input per pathway. It also includes direct-access and GP-requested tests that sit on no RTT pathway, so it overstates the tests attributable to completions. These two biases run in opposite directions and neither has been quantified. More fundamentally, the model parameter is a marginal ratio, the tests needed to unlock one additional pathway, while the observed figure is an average across all activity. They are different quantities.' },
]));

children.push(rich([
  { t: 'What the Board can reasonably conclude is narrower but still decision-relevant: ' },
  { t: 'the direction of the recommendation is better evidenced than the size of the benefit it produces.', b: true },
  { t: ' A diagnostic-weighted programme is very likely the right call; the 60,649 figure attached to it should be treated as indicative.' },
]));

/* 6. Options */
children.push(h1('6. Options considered'));

children.push(p('Eight strategies were tested, each expressed as an explicit constraint on the same optimisation model so that all were evaluated on identical terms, across four scenarios framed from the two most critical uncertainties: the funding settlement and the diagnostic conversion ratio.'));

children.push(...figure('fig4_strategies.png',
  'Figure 5. Performance of each candidate strategy across the four scenarios.',
  'Source: Phase 5 scenario model, 40 separate optimisation solves.'));

children.push(table(
  ['Strategy', 'Score', 'Worst-case regret'],
  [
    ['S1  Unconstrained optimisation', '274', '0'],
    ['S2  NHS delivery only (recommended)', '274', '0'],
    ['S5  Equity-first', '274', '0'],
    ['S7  Treatment capacity only', '295', '106,324'],
    ['S3  No in-house expansion', '339', '0'],
    ['S4  Diagnostic-led (50% floor)', '361', '1,422'],
    ['S6  Diversified hedge', '374', '53,162'],
    ['S0  Hold position', '545', '169,817'],
  ],
  [5426, 1600, 2000],
));

children.push(new Paragraph({ spacing: { after: 160 }, children: [] }));

children.push(p('Lower scores are better. Three points in that table warrant comment.'));

children.push(bullet('S1, S2 and S5 do not merely score the same. They are provably the same commitment, returning identical values on all four objectives in all five scenarios. Neither the outsourcing lock nor the equity floor binds anywhere in the range examined.'));

children.push(bullet('S6, the diversified hedge, performs poorly. Spreading spend across levers to reduce exposure costs 53,162 breaches in the best scenario and buys little protection, because the levers do not fail independently. They share the same funding constraint.'));

children.push(bullet('S4, the diagnostic-led strategy with a hard 50% floor, is dominated by S2. Forcing spend into diagnostics when they are expensive is worse than letting the optimisation decide, which is what S2 already does.'));

/* 7. Equity */
children.push(h1('7. Equity: an unusual finding'));

children.push(rich([
  { t: 'The equity tolerance built into the capacity model never binds at any funding level examined. At every envelope tested, ' },
  { t: 'the entire reduction can be directed to higher-deprivation providers at no cost whatsoever to the total number of breaches cleared.', b: true },
]));

children.push(p('The reason is arithmetic rather than virtuous: the budget clears far less than the higher-deprivation trusts are carrying on their own, so there is no point at which directing effort towards them requires giving anything up elsewhere.'));

children.push(p('The implication for the Board is straightforward. Equity here is not a trade-off to be managed against efficiency, and it should not be presented as one. It is available at zero cost, and the programme should be explicitly designed to take it rather than allowing it to arrive incidentally.'));

/* 8. Risks */
children.push(h1('8. Risks and what would change this view'));

children.push(h2('8.1 The funding envelope is the largest uncertainty and we cannot see it'));

children.push(p('The single highest-impact parameter in the model is the size of the settlement, and it is the only one with no internal data source. No ICB-level elective recovery budget is published at any level. It must be tracked through the finance route rather than through analytics, and the model should be re-run against the confirmed figure as soon as it is known.'));

children.push(h2('8.2 Diagnostic headroom is worth watching, but should not be overstated'));

children.push(p('The recommended strategy assumes roughly 10% headroom for additional diagnostic activity. The share of the diagnostic waiting list waiting over six weeks averaged 10.2% over the last 12 months, against 8.1% over the preceding 12, a step up of around two percentage points.'));

children.push(...figure('fig6_diagnostic_pressure.png',
  'Figure 6. Diagnostic waiting times in context.',
  'Source: NHS England DM01, 12 core trusts, 84 months.'));

children.push(rich([
  { t: 'The longer view matters here. Over the full window the series trends significantly ' },
  { t: 'downward', b: true },
  { t: ' (−0.14 percentage points per month, p = 0.009), and over the last 24 months there is no statistically significant trend in either direction (p = 0.21) on a series with a standard deviation of about two points. An earlier draft of this analysis described diagnostic waits as deteriorating on the basis of a point-to-point comparison; that did not survive a trend test and has been corrected. What is true is that performance plateaued around 8–10%, roughly three times the pre-pandemic level of 3%, and that the most recent 12 months sit at the upper end of that plateau.' },
]));

children.push(h2('8.3 Other risks'));

children.push(bullet('Provider-level allocations from the model are not unique. The optimisation has multiple equally good solutions, so the totals and the constraint satisfaction can be relied on but a specific trust-by-trust split cannot. The model should not be used as a distribution plan without further work.'));
children.push(bullet('The delivery-risk measure used in the ranking is a construction of this analysis rather than a standard NHS metric, and the choice between S2 and S7 turns entirely on how much weight it is given. This is the single most consequential judgement in the paper and the Board should treat it as its own to make.'));
children.push(bullet('Scenarios carry no probabilities. They test plausibility, not likelihood, and no expected value across them should be inferred.'));

/* 9. Decision */
children.push(h1('9. Decision sought and next steps'));

children.push(h2('9.1 Decisions'));
children.push(bullet('Approve Strategy S2 as the committed programme strategy for the period to September 2027, accepting that this is a judgement to tolerate exposure to the diagnostic conversion assumption in exchange for roughly double the breaches cleared. The alternative, S7, is set out at paragraph 1 and remains available.'));
children.push(bullet('Note that the funding settlement, not delivery capacity, determines what this programme can achieve, and that the three deliverability debates at paragraph 2 can be closed.'));
children.push(bullet('Agree that equity is to be designed in explicitly rather than treated as a trade-off, given that it is available at zero cost.'));

children.push(h2('9.2 Triggers that would require this strategy to be revisited'));
children.push(bullet('Diagnostic conversion rising above 2.00 tests per completed pathway for three consecutive months triggers a review. Above 3.34 the lever choice reverses and the programme must shift to treatment capacity.'));
children.push(bullet('The 12-month mean share of the diagnostic waiting list beyond six weeks exceeding 15%, or a statistically significant upward trend sustained over two quarters, meaning the assumed diagnostic headroom is not there.'));

children.push(h2('9.3 Next steps'));
children.push(bullet('Re-run the model against the confirmed funding envelope once notified (Strategy and Analytics, within two weeks of notification).'));
children.push(bullet('Establish monthly reporting of the Annex A indicators through the existing programme dashboard.'));
children.push(bullet('Develop the trust-level distribution plan separately, since the model does not determine it.'));

children.push(new Paragraph({ children: [new PageBreak()] }));

/* Annex A */
children.push(h1('Annex A: Monitoring indicators'));

children.push(p('Restricted to quantities the data warehouse already holds and can refresh monthly, with one exception recorded explicitly as a gap.'));

children.push(table(
  ['Flag', 'Indicator', 'Current', 'Status'],
  [
    ['F1', 'Confirmed funding envelope', 'Not observable', 'Gap, finance route'],
    ['F2', 'DM01 tests per completed pathway', '0.84', 'Active'],
    ['F3', 'Diagnostic list over 6 weeks (12m mean)', '10.2%', 'Active'],
    ['F4', 'Waiting list vs forecast band', '686,298', 'Monitor only'],
    ['F5', 'Independent-sector activity', '7,510 / month', 'Dormant below £31.9m'],
    ['F6', 'Bed and workforce headroom', 'Tracked in model', 'Dormant below £107.1m'],
  ],
  [800, 3800, 2126, 2300],
));

children.push(new Paragraph({ spacing: { after: 200 }, children: [] }));
children.push(p('F5 and F6 are recorded as dormant rather than omitted, so that their absence from routine monitoring is a deliberate decision with a stated threshold rather than an oversight.', { italics: true }));

/* Annex B */
children.push(h1('Annex B: Method, provenance and limitations'));

children.push(h2('Data'));
children.push(p('Seven NHS England and gov.uk sources warehoused and validated across the full 84-month window: RTT waiting times, DM01 diagnostics, A&E attendances, KH03 bed occupancy, GPAD primary care demand, NHS Workforce Statistics, and Index of Multiple Deprivation 2019. Unit costs are from the National Cost Collection 2024/25 and the 2025/26 NHS Payment Scheme.'));

children.push(h2('Method'));
children.push(p('Scenario construction and strategy evaluation follow Cairns and Wright (2018), Scenario Thinking, 2nd edition: the intuitive-logics basic method, sum-of-ranks decision analysis with weighting sensitivity, and minimax regret with early-warning flags. The framing of monitoring as a continuing activity rather than a one-off exercise follows Sminia (2026) on strategic management as wayfinding. The institutional feasibility screen applied to each strategy follows Sminia (2022), chapter 7.'));

children.push(p('Two departures from that method are recorded because they change what the output means. First, the impact axis of the scenario selection matrix is computed. It is the measured swing in breaches cleared as each driver moves across its range, rather than assigned by workshop judgement. Second, the uncertainty axis is graded against a written evidence rubric tied to each parameter\'s documented source, rather than by participant vote.'));

children.push(h2('Assurance'));
children.push(p('All 40 strategy-scenario solves were checked for budget compliance, non-negativity, and constraint satisfaction. Every figure computed in the accompanying workbook was independently reproduced against the analytical engine, covering four rank columns across 40 rows, eight strategy totals and eight regret figures, with zero discrepancies. The tipping point was verified by two independent methods agreeing to four significant figures.'));

children.push(p('Three defects were found and corrected during assurance and are documented in full in the Phase 5 validation report. Two concerned figures that were artefacts of the optimiser rather than properties of the strategies: first the equity figures, then the delivery-risk figures, each resolved by adding a further hierarchical stage to the solve. The third was a divergence between the workbook and the engine caused by rounding applied in two places rather than one.'));

children.push(p('The delivery-risk defect changed the recommendation materially and is worth stating plainly here. Before it was corrected, S2 appeared to lead under every weighting tested, and an earlier draft of this paper said so. Once the measure was properly pinned, S2 was revealed to be identical to two other strategies and no longer weight-stable against S7. The paper now reports a judgement call where it previously reported a robust result. All three defects were caught by systematic cross-checking, not by inspection. None was visible in output that looked entirely reasonable.'));

children.push(h2('Principal limitations'));
children.push(bullet('One parameter, the number of diagnostic tests per unlocked pathway, remains unsourced, and the allocation depends on it. This is stated in the body of the paper rather than confined to this annex.'));
children.push(bullet('Provider-level allocations are not unique and must not be used as a distribution plan.'));
children.push(bullet('The single-anchor mapping of trusts to local authorities is an approximation for regional specialist centres whose catchments extend across and beyond the ICB.'));
children.push(bullet('Over-52-week breach forecasts are derived by applying trailing breach shares to a forecast waiting list, not forecast directly.'));

const doc = new Document({
  creator: 'Strategy and Analytics',
  title: 'Elective Recovery: Where to Commit Capacity Funding',
  description: 'NHS Cheshire and Merseyside ICB, Elective Recovery Programme Board',
  styles: {
    default: {
      document: { run: { font: FONT, size: 20 } },
    },
  },
  sections: [{
    properties: {
      page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
    },
    // Page number only. A board paper needs pagination to be referenced in a
    // meeting; it does not need its own title repeated on every page.
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: GREY }),
          ],
        })],
      }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then(b => {
  fs.writeFileSync(OUT, b);
  console.log('Written', OUT);
});
