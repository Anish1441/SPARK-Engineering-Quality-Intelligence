const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

/* =========================================================
   APPLICATION STATE
========================================================= */

const S = {
    datasets: [],
    active: null,
    analysis: null,
    modelHealth: null,
    lotIntelligence: null,
    signal: "",
    record: 0,
    assessment: null,
    qaResponse: "AGREE",
    qaAction: ""
};


/* =========================================================
   API
========================================================= */

const api = async (p, o = {}) => {
    const r = await fetch("/api" + p, {
        cache: "no-store",
        ...o
    });

    const b = await r.json().catch(() => ({
        detail: "Invalid server response"
    }));

    if (!r.ok) {
        throw Error(b.detail || `Request failed (${r.status})`);
    }

    return b;
};


/* =========================================================
   GENERAL HELPERS
========================================================= */

const esc = s =>
    String(s ?? "").replace(
        /[&<>"']/g,
        m => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;"
        }[m])
    );


const fmt = x => {
    if (x == null || x === "") return "—";

    const n = Number(x);

    if (!Number.isFinite(n)) return "—";

    return n.toLocaleString(undefined, {
        maximumFractionDigits: 4
    });
};


const fmtPct = x => {
    if (x == null || x === "") return "—";

    const n = Number(x);

    if (!Number.isFinite(n)) return "—";

    return `${(n * 100).toFixed(1)}%`;
};


const toast = s => {
    const e = $("#toast");

    if (!e) return;

    e.textContent = s;
    e.style.display = "block";

    clearTimeout(window.__toast);

    window.__toast = setTimeout(() => {
        e.style.display = "none";
    }, 2400);
};


/* =========================================================
   THEME
========================================================= */

function getTheme() {
    return document.body.dataset.theme === "night"
        ? "night"
        : "dark";
}


function applyTheme(theme, persist = true) {
    const selected = theme === "night"
        ? "night"
        : "dark";

    document.body.dataset.theme = selected;

    const toggle = $("#themeToggle");

    if (toggle) {
        toggle.setAttribute(
            "aria-pressed",
            selected === "night" ? "true" : "false"
        );

        toggle.title =
            selected === "night"
                ? "Switch to Dark mode"
                : "Switch to Night mode";
    }

    if (persist) {
        try {
            localStorage.setItem(
                "spark-theme",
                selected
            );
        } catch (_) {
            /* localStorage is optional */
        }
    }

    /*
     * Plotly charts use transparent backgrounds.
     * Re-render visible charts so their text/grid colours
     * follow the selected theme.
     */
    setTimeout(refreshVisibleVisuals, 0);
}


function initTheme() {
    let saved = "dark";

    try {
        saved = localStorage.getItem("spark-theme") || "dark";
    } catch (_) {
        saved = "dark";
    }

    applyTheme(saved, false);

    const toggle = $("#themeToggle");

    if (toggle) {
        toggle.onclick = () => {
            applyTheme(
                getTheme() === "dark"
                    ? "night"
                    : "dark"
            );
        };
    }
}


function themeColors() {
    const root = getComputedStyle(document.body);

    return {
        text:
            root.getPropertyValue("--text").trim()
            || "#f2ede4",

        muted:
            root.getPropertyValue("--muted").trim()
            || "#aaa095",

        line:
            root.getPropertyValue("--line").trim()
            || "#3b362e",

        panel:
            root.getPropertyValue("--panel").trim()
            || "#1b1916",

        panel2:
            root.getPropertyValue("--panel2").trim()
            || "#25221e",

        accent:
            root.getPropertyValue("--accent").trim()
            || "#d2bd95"
    };
}


function refreshVisibleVisuals() {
    if (S.active) {
        renderOverview();
    }

    const activeView =
        document.querySelector(".view.active")?.id;

    if (activeView === "monitor" && S.signal) {
        drawSignal();
    }

    if (activeView === "analysis" && S.analysis) {
        renderAnalysis();
    }
}


/* =========================================================
   NAVIGATION
========================================================= */

function go(v) {
    $$(".view").forEach(e =>
        e.classList.toggle(
            "active",
            e.id === v
        )
    );

    $$("nav button").forEach(e =>
        e.classList.toggle(
            "active",
            e.dataset.view === v
        )
    );

    if (v === "datasets") {
        renderDatasets();
    }

    if (v === "monitor") {
        loadSignal();
    }

    if (v === "analysis") {
        renderAnalysis();
    }

    if (v === "model-health") {
        loadModelHealth();
    }

    if (v === "lot-intelligence") {
        loadLotIntelligence();
    }

    if (v === "qa") {
        loadAssessment();
    }

    if (v === "history") {
        loadHistory();
    }
}


/* =========================================================
   OVERVIEW
========================================================= */

function card(a, b) {
    return `
        <div class="card">
            <span>${esc(a)}</span>
            <strong>${esc(b)}</strong>
        </div>
    `;
}


async function load() {
    S.datasets =
        (await api("/datasets")).datasets || [];

    S.active =
        S.datasets.find(x => x.active) || null;

    if (!S.active && S.datasets.length) {
        S.active = S.datasets[0];
    }

    if (S.active) {
        await loadAnalysis();
    } else {
        S.analysis = null;
        renderOverview();
    }
}


async function loadAnalysis() {
    try {
        S.analysis = await api(
            `/datasets/${S.active.dataset_id}/analysis`
        );
    } catch (e) {
        S.analysis = null;
        toast(e.message);
    }

    renderOverview();
}


function renderOverview() {
    const d = S.active;

    const cards = $("#cards");

    if (!cards) return;

    cards.innerHTML = d
        ? [
            card(
                d.inspection_mode === "component"
                    ? "COMPONENTS"
                    : "RECORDS",
                (d.inspection_count ?? d.rows)?.toLocaleString() ?? "—"
            ),
            card(
                "FIELDS",
                d.columns ?? "—"
            ),
            card(
                "NUMERIC SIGNALS",
                d.numeric_columns ?? "—"
            ),
            card(
                "MISSING CELLS",
                d.missing_cells ?? "—"
            )
        ].join("")
        : card("DATASET", "NONE");

    if (!d) {
        $("#overviewPlot").innerHTML = "";
        $("#overviewTable").innerHTML =
            "No active dataset.";
        return;
    }

    const x =
        S.analysis?.stability || [];

    const tc = themeColors();

    Plotly.newPlot(
        "overviewPlot",
        [{
            x: x.map(v => v.signal),
            y: x.map(v => v.std),
            type: "bar",
            marker: {
                color: x.map(v => {
                    const value =
                        Number(v.outliers) || 0;

                    if (value >= 10) return "#c96b63";
                    if (value >= 5) return "#d2aa63";
                    return "#79a982";
                })
            },
            hovertemplate:
                "<b>%{x}</b><br>" +
                "Standard deviation: %{y}<extra></extra>"
        }],
        {
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",

            font: {
                color: tc.text,
                size: 11
            },

            margin: {
                l: 45,
                r: 15,
                t: 15,
                b: 80
            },

            xaxis: {
                automargin: true,
                tickangle: -45,
                gridcolor:
                    "rgba(150,150,150,0.10)"
            },

            yaxis: {
                automargin: true,
                gridcolor:
                    "rgba(150,150,150,0.10)"
            }
        },
        {
            displayModeBar: false,
            responsive: true
        }
    );

    $("#overviewTable").innerHTML = `
        <table class="table">
            <tr>
                <th>SIGNAL</th>
                <th>MEAN</th>
                <th>STD</th>
                <th>OUTLIERS</th>
            </tr>

            ${x.map(v => `
                <tr>
                    <td>${esc(v.signal)}</td>
                    <td>${fmt(v.mean)}</td>
                    <td>${fmt(v.std)}</td>
                    <td>${fmt(v.outliers)}</td>
                </tr>
            `).join("")}
        </table>
    `;
}


/* =========================================================
   DATASETS
========================================================= */

function renderDatasets() {
    const container = $("#datasetList");

    if (!container) return;

    container.innerHTML = S.datasets.length
        ? S.datasets.map(d => `
            <div class="dataset">

                <div>
                    <h3>
                        ${esc(d.filename)}
                        ${d.active ? " · ACTIVE" : ""}
                    </h3>

                    <small>
                        ${d.rows?.toLocaleString() ?? "—"} rows ·
                        ${d.inspection_mode === "component"
                            ? `${(d.inspection_count || 0).toLocaleString()} components · `
                            : ""}
                        ${d.columns ?? "—"} fields ·
                        ${d.numeric_columns ?? "—"} numeric ·
                        ${d.missing_cells ?? "—"} missing
                    </small>
                </div>

                <div>

                    <button
                        onclick="activate('${esc(d.dataset_id)}')">
                        Activate
                    </button>

                    ${
                        d.read_only
                            ? `<button class="danger" disabled title="Managed read-only dataset">Read-only</button>`
                            : `<button class="danger" onclick="removeD('${esc(d.dataset_id)}')">Remove</button>`
                    }

                </div>

            </div>
        `).join("")
        : '<div class="panel">No datasets loaded.</div>';
}


window.activate = async id => {
    try {
        await api(`/datasets/${id}/activate`, {
            method: "POST"
        });

        S.record = 0;
        S.assessment = null;
        S.qaAction = "";
        S.qaResponse = "AGREE";

        await load();

        go("qa");

        toast(
            "Dataset activated; inspection reset to the first item"
        );
    } catch (e) {
        toast(e.message);
    }
};


window.removeD = async id => {
    if (!confirm(
        "Remove this dataset and its QA history?"
    )) {
        return;
    }

    try {
        await api(`/datasets/${id}`, {
            method: "DELETE"
        });

        if (S.active?.dataset_id === id) {
            S.active = null;
            S.analysis = null;
            S.assessment = null;
            S.record = 0;
            S.qaAction = "";
        }

        await load();
        renderDatasets();

        toast("Dataset removed");
    } catch (e) {
        toast(e.message);
    }
};


/* =========================================================
   PROCESS MONITOR
========================================================= */

async function loadSignal() {
    if (!S.active) return;

    const signals =
        (S.analysis?.stability || [])
            .filter(x => x.eligible)
            .map(x => x.signal);

    const select = $("#signalSelect");

    if (!select) return;

    select.innerHTML = signals
        .map(x => `
            <option value="${esc(x)}">
                ${esc(x)}
            </option>
        `)
        .join("");

    S.signal =
        signals.includes(S.signal)
            ? S.signal
            : (signals[0] || "");

    if (S.signal) {
        select.value = S.signal;
        drawSignal();
    }
}


async function drawSignal() {
    if (!S.active || !S.signal) return;

    try {
        const x = await api(
            `/datasets/${S.active.dataset_id}/signals/${encodeURIComponent(S.signal)}/control`
        );

        if (!x || !Array.isArray(x.values)) {
            throw Error(
                "Signal control data is unavailable."
            );
        }

        const n = x.values.length;
        const tc = themeColors();
        const observationX = Array.isArray(x.observation_indices)
            && x.observation_indices.length === n
            ? x.observation_indices.map(i => Number(i) + 1)
            : x.values.map((_, i) => i + 1);

        Plotly.newPlot(
            "controlPlot",
            [
                {
                    x: observationX,
                    y: x.values,
                    mode: "lines+markers",
                    name: "Observed",
                    line: {
                        width: 2
                    },
                    marker: {
                        size: 5
                    },
                    hovertemplate:
                        "Record %{x}<br>" +
                        "Value %{y}<extra></extra>"
                },
                {
                    x: [observationX[0] ?? 1, observationX[n - 1] ?? n],
                    y: [x.ucl, x.ucl],
                    mode: "lines",
                    name: "UCL",
                    line: {
                        dash: "dash",
                        width: 1.5
                    }
                },
                {
                    x: [observationX[0] ?? 1, observationX[n - 1] ?? n],
                    y: [x.center, x.center],
                    mode: "lines",
                    name: "Center",
                    line: {
                        width: 1.5
                    }
                },
                {
                    x: [observationX[0] ?? 1, observationX[n - 1] ?? n],
                    y: [x.lcl, x.lcl],
                    mode: "lines",
                    name: "LCL",
                    line: {
                        dash: "dash",
                        width: 1.5
                    }
                }
            ],
            {
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",

                font: {
                    color: tc.text,
                    size: 11
                },

                margin: {
                    l: 55,
                    r: 15,
                    t: 15,
                    b: 45
                },

                xaxis: {
                    title: "Observation",
                    automargin: true,
                    gridcolor:
                        "rgba(150,150,150,0.10)"
                },

                yaxis: {
                    title: S.signal,
                    automargin: true,
                    gridcolor:
                        "rgba(150,150,150,0.10)"
                },

                legend: {
                    orientation: "h",
                    y: 1.08
                }
            },
            {
                displayModeBar: false,
                responsive: true
            }
        );


        Plotly.newPlot(
            "histPlot",
            [{
                x: x.values,
                type: "histogram",
                nbinsx: 30,
                marker: {
                    color: "#8e9f91"
                },
                hovertemplate:
                    "Value: %{x}<br>" +
                    "Count: %{y}<extra></extra>"
            }],
            {
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",

                font: {
                    color: tc.text,
                    size: 11
                },

                margin: {
                    l: 55,
                    r: 15,
                    t: 15,
                    b: 45
                },

                xaxis: {
                    title: S.signal,
                    automargin: true,
                    gridcolor:
                        "rgba(150,150,150,0.10)"
                },

                yaxis: {
                    title: "Count",
                    automargin: true,
                    gridcolor:
                        "rgba(150,150,150,0.10)"
                }
            },
            {
                displayModeBar: false,
                responsive: true
            }
        );

    } catch (e) {
        toast(e.message);
    }
}


/* =========================================================
   ANALYSIS
========================================================= */

function analysisNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}


function analysisColor(score) {
    const n =
        Math.max(
            0,
            Math.min(100, Number(score) || 0)
        );

    if (n >= 75) {
        return "#d95f59";
    }

    if (n >= 45) {
        return "#d6a84f";
    }

    return "#5fbf8f";
}


function analysisRiskLabel(score) {
    const n = Number(score) || 0;

    if (n >= 75) {
        return "HIGH";
    }

    if (n >= 45) {
        return "WATCH";
    }

    return "STABLE";
}


function analysisPlotLayout(title = "") {
    const tc = themeColors();

    return {
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",

        margin: {
            l: 60,
            r: 25,
            t: title ? 35 : 15,
            b: 80
        },

        title: title
            ? {
                text: title,
                x: 0.02,
                xanchor: "left",
                font: {
                    size: 13,
                    color: tc.text
                }
            }
            : undefined,

        font: {
            color: tc.text,
            size: 11
        },

        hoverlabel: {
            bgcolor: tc.panel2,
            font: {
                color: tc.text
            }
        },

        xaxis: {
            automargin: true,
            gridcolor:
                "rgba(150,150,150,0.12)",
            zerolinecolor:
                "rgba(150,150,150,0.18)"
        },

        yaxis: {
            automargin: true,
            gridcolor:
                "rgba(150,150,150,0.12)",
            zerolinecolor:
                "rgba(150,150,150,0.18)"
        }
    };
}


function analysisPlotConfig() {
    return {
        displayModeBar: false,
        responsive: true
    };
}


/* ---------------------------------------------------------
   EXTENDED ANALYSIS WORKSPACE
--------------------------------------------------------- */

function ensureAnalysisWorkspace() {
    const section = $("#analysis");

    if (!section) {
        return false;
    }

    if ($("#analysisExtendedWorkspace")) {
        return true;
    }

    const workspace =
        document.createElement("div");

    workspace.id =
        "analysisExtendedWorkspace";

    workspace.innerHTML = `
        <div
            class="analysis-kpis"
            id="analysisKPIs">
        </div>

        <div class="analysis-grid">

            <div class="panel analysis-panel">
                <b>OUTLIER PROFILE</b>
                <div
                    id="outlierPlot"
                    class="plot">
                </div>
            </div>

            <div class="panel analysis-panel">
                <b>SIGNAL RANGE / MEDIAN</b>
                <div
                    id="rangePlot"
                    class="plot">
                </div>
            </div>

            <div class="panel analysis-panel">
                <b>CORRELATION HEATMAP</b>
                <div
                    id="correlationHeatmap"
                    class="plot tall">
                </div>
            </div>

            <div class="panel analysis-panel">
                <b>SIGNAL QUALITY PROFILE</b>
                <div
                    id="qualityTable">
                </div>
            </div>

        </div>
    `;

    /*
     * Preserve the existing Analysis section and place
     * the additional professional analytical views below it.
     */
    const existingTwo =
        section.querySelector(".two");

    if (existingTwo) {
        existingTwo.insertAdjacentElement(
            "afterend",
            workspace
        );
    } else {
        section.appendChild(workspace);
    }

    return true;
}


function renderAnalysis() {
    const a = S.analysis;

    if (!a) {
        return;
    }

    if (!ensureAnalysisWorkspace()) {
        return;
    }

    const stability =
        Array.isArray(a.stability)
            ? a.stability
            : [];

    const distributions =
        Array.isArray(a.distributions)
            ? a.distributions
            : [];

    const correlations =
        Array.isArray(a.correlations)
            ? a.correlations
            : [];

    const health = a.health || {};


    /* ---------------------------------------------------------
       EXISTING SIGNAL STABILITY TABLE
    --------------------------------------------------------- */

    const stabilityContainer =
        $("#stability");

    if (stabilityContainer) {
        stabilityContainer.innerHTML = `
            <table class="table">

                <tr>
                    <th>SIGNAL</th>
                    <th>MEAN</th>
                    <th>STD</th>
                    <th>OUTLIERS</th>
                </tr>

                ${
                    stability.length
                        ? stability.map(v => `
                            <tr>
                                <td>
                                    ${esc(v.signal)}
                                </td>

                                <td>
                                    ${fmt(v.mean)}
                                </td>

                                <td>
                                    ${fmt(v.std)}
                                </td>

                                <td>
                                    ${fmt(v.outliers)}
                                </td>
                            </tr>
                        `).join("")
                        : `
                            <tr>
                                <td colspan="4">
                                    No stability data available.
                                </td>
                            </tr>
                        `
                }

            </table>
        `;
    }


    /* ---------------------------------------------------------
       EXISTING CORRELATION VIEW
    --------------------------------------------------------- */

    drawCorrelationOverview(correlations);


    /* ---------------------------------------------------------
       DATASET HEALTH
    --------------------------------------------------------- */

    renderAnalysisKPIs(
        health,
        stability
    );


    /* ---------------------------------------------------------
       OUTLIER PROFILE
    --------------------------------------------------------- */

    drawOutlierProfile(stability);


    /* ---------------------------------------------------------
       SIGNAL RANGE / MEDIAN
    --------------------------------------------------------- */

    drawSignalRange(distributions);


    /* ---------------------------------------------------------
       CORRELATION HEATMAP
    --------------------------------------------------------- */

    drawCorrelationHeatmap(correlations);


    /* ---------------------------------------------------------
       SIGNAL QUALITY
    --------------------------------------------------------- */

    renderSignalQualityTable(
        stability,
        distributions
    );
}


/* =========================================================
   CORRELATION OVERVIEW
========================================================= */

function drawCorrelationOverview(
    correlations
) {
    const c = correlations || [];

    const tc = themeColors();

    Plotly.newPlot(
        "corrPlot",

        [
            {
                x: c.map(v => v.x),
                y: c.map(v => v.y),

                mode: "markers",

                marker: {
                    size: c.map(v =>
                        8 +
                        Math.abs(
                            Number(
                                v.correlation || 0
                            )
                        ) * 18
                    ),

                    color: c.map(v =>
                        Number(
                            v.correlation || 0
                        )
                    ),

                    colorscale: [
                        [0, "#5f78b8"],
                        [0.5, "#777777"],
                        [1, "#c65f59"]
                    ],

                    cmin: -1,
                    cmax: 1,

                    showscale: true,

                    colorbar: {
                        title: "r",
                        thickness: 10
                    }
                },

                text: c.map(v =>
                    `${esc(v.x)} ↔ ${esc(v.y)}<br>` +
                    `Correlation: ${
                        Number(
                            v.correlation
                        ).toFixed(3)
                    }`
                ),

                hovertemplate:
                    "%{text}<extra></extra>"
            }
        ],

        {
            ...analysisPlotLayout(),

            font: {
                color: tc.text,
                size: 11
            },

            margin: {
                l: 55,
                r: 15,
                t: 15,
                b: 80
            },

            xaxis: {
                automargin: true,
                tickangle: -45
            },

            yaxis: {
                automargin: true
            }
        },

        analysisPlotConfig()
    );
}


/* =========================================================
   DATASET HEALTH KPI CARDS
========================================================= */

function renderAnalysisKPIs(
    health,
    stability
) {
    const container =
        $("#analysisKPIs");

    if (!container) {
        return;
    }

    const rows =
        Number(health.rows) || 0;

    const columns =
        Number(health.columns) || 0;

    const numericSignals =
        Number(health.numeric_signals) || 0;

    const missing =
        Number(health.missing_cells) || 0;

    const duplicates =
        Number(health.duplicate_rows) || 0;

    const completeness =
        Number(health.completeness_pct) || 0;

    const usable =
        Number(
            health.usable_numeric_signals
        ) || 0;

    const usablePct =
        numericSignals
            ? (usable / numericSignals) * 100
            : 0;

    container.innerHTML = `
        <div class="card">
            <span>DATA COMPLETENESS</span>
            <strong>
                ${fmt(completeness)}%
            </strong>
            <small>
                ${rows.toLocaleString()} records
            </small>
        </div>

        <div class="card">
            <span>NUMERIC COVERAGE</span>
            <strong>
                ${fmt(usablePct)}%
            </strong>
            <small>
                ${usable}/${numericSignals}
                signals usable
            </small>
        </div>

        <div class="card">
            <span>MISSING CELLS</span>
            <strong>
                ${missing.toLocaleString()}
            </strong>
            <small>
                ${columns} total fields
            </small>
        </div>

        <div class="card">
            <span>DUPLICATE ROWS</span>
            <strong>
                ${duplicates.toLocaleString()}
            </strong>
            <small>
                Dataset integrity check
            </small>
        </div>

        <div class="card">
            <span>ANALYZED SIGNALS</span>
            <strong>
                ${stability.length}
            </strong>
            <small>
                Statistical profiles
            </small>
        </div>
    `;
}


/* =========================================================
   OUTLIER PROFILE
========================================================= */

function drawOutlierProfile(
    stability
) {
    const signals =
        stability.map(
            v => String(v.signal)
        );

    const counts =
        stability.map(
            v => Number(v.outliers) || 0
        );

    const maxOutlier =
        Math.max(1, ...counts);

    const colors =
        counts.map(value => {
            const ratio =
                value / maxOutlier;

            if (ratio >= 0.75) {
                return "#d95f59";
            }

            if (ratio >= 0.45) {
                return "#d6a84f";
            }

            return "#5fbf8f";
        });

    Plotly.newPlot(
        "outlierPlot",

        [{
            x: signals,
            y: counts,

            type: "bar",

            marker: {
                color: colors
            },

            text:
                counts.map(
                    v => String(v)
                ),

            textposition: "auto",

            hovertemplate:
                "<b>%{x}</b><br>" +
                "Outliers: %{y}<extra></extra>"
        }],

        {
            ...analysisPlotLayout(),

            xaxis: {
                automargin: true,
                tickangle: -45
            },

            yaxis: {
                title: "Count",
                rangemode: "tozero"
            }
        },

        analysisPlotConfig()
    );
}


/* =========================================================
   SIGNAL RANGE / MEDIAN
========================================================= */

function drawSignalRange(
    distributions
) {
    const usable =
        distributions.filter(v => {
            const stats =
                v.stats || {};

            return (
                analysisNumber(
                    stats.min
                ) !== null &&

                analysisNumber(
                    stats.max
                ) !== null &&

                analysisNumber(
                    stats.median
                ) !== null
            );
        });

    const signals =
        usable.map(
            v => String(v.signal)
        );

    const mins =
        usable.map(
            v => Number(v.stats.min)
        );

    const medians =
        usable.map(
            v => Number(v.stats.median)
        );

    const maxs =
        usable.map(
            v => Number(v.stats.max)
        );

    Plotly.newPlot(
        "rangePlot",

        [
            {
                x: signals,
                y: mins,
                type: "scatter",
                mode: "markers",
                name: "Minimum",

                marker: {
                    size: 8,
                    symbol: "triangle-down"
                }
            },

            {
                x: signals,
                y: medians,
                type: "scatter",
                mode: "markers",
                name: "Median",

                marker: {
                    size: 10,
                    symbol: "diamond"
                }
            },

            {
                x: signals,
                y: maxs,
                type: "scatter",
                mode: "markers",
                name: "Maximum",

                marker: {
                    size: 8,
                    symbol: "triangle-up"
                }
            }
        ],

        {
            ...analysisPlotLayout(),

            xaxis: {
                automargin: true,
                tickangle: -45
            },

            yaxis: {
                title: "Observed value"
            },

            legend: {
                orientation: "h",
                y: 1.08
            }
        },

        analysisPlotConfig()
    );
}


/* =========================================================
   CORRELATION HEATMAP
========================================================= */

function drawCorrelationHeatmap(
    correlations
) {
    const pairs =
        correlations || [];

    const signals =
        new Set();

    pairs.forEach(item => {
        if (item.x != null) {
            signals.add(
                String(item.x)
            );
        }

        if (item.y != null) {
            signals.add(
                String(item.y)
            );
        }
    });

    const labels =
        [...signals];

    const container =
        $("#correlationHeatmap");

    if (!container) {
        return;
    }

    if (!labels.length) {
        Plotly.purge(
            "correlationHeatmap"
        );

        container.innerHTML =
            '<div class="muted">No correlation data available.</div>';

        return;
    }

    const index =
        new Map(
            labels.map(
                (name, i) => [name, i]
            )
        );

    const matrix =
        labels.map(() =>
            labels.map(() => 0)
        );

    labels.forEach((_, i) => {
        matrix[i][i] = 1;
    });

    pairs.forEach(item => {
        const x = String(item.x);
        const y = String(item.y);
        const value =
            Number(item.correlation);

        if (
            !index.has(x) ||
            !index.has(y) ||
            !Number.isFinite(value)
        ) {
            return;
        }

        const xi = index.get(x);
        const yi = index.get(y);

        matrix[xi][yi] = value;
        matrix[yi][xi] = value;
    });

    Plotly.newPlot(
        "correlationHeatmap",

        [{
            z: matrix,
            x: labels,
            y: labels,

            type: "heatmap",

            zmin: -1,
            zmax: 1,

            colorscale: [
                [0, "#4f6fa8"],
                [0.5, "#777777"],
                [1, "#b95c58"]
            ],

            colorbar: {
                title: "Correlation",
                thickness: 12
            },

            hovertemplate:
                "%{y} ↔ %{x}<br>" +
                "r = %{z:.3f}<extra></extra>"
        }],

        {
            ...analysisPlotLayout(),

            margin: {
                l: 110,
                r: 70,
                t: 20,
                b: 110
            },

            xaxis: {
                tickangle: -45,
                automargin: true
            },

            yaxis: {
                automargin: true,
                autorange: "reversed"
            }
        },

        analysisPlotConfig()
    );
}


/* =========================================================
   SIGNAL QUALITY PROFILE
========================================================= */

function renderSignalQualityTable(
    stability,
    distributions
) {
    const container =
        $("#qualityTable");

    if (!container) {
        return;
    }

    const distributionMap =
        new Map(
            distributions.map(
                item => [
                    String(item.signal),
                    item.stats || {}
                ]
            )
        );

    const rows =
        stability.map(item => {
            const signal =
                String(item.signal);

            const stats =
                distributionMap.get(signal) || {};

            const mean =
                analysisNumber(item.mean);

            const std =
                analysisNumber(item.std);

            const median =
                analysisNumber(stats.median);

            const mad =
                analysisNumber(stats.mad);

            let cv = null;

            if (
                mean !== null &&
                std !== null &&
                Math.abs(mean) > 1e-12
            ) {
                cv =
                    Math.abs(
                        std / mean
                    ) * 100;
            }

            /*
             * Descriptive visual grading only.
             * It is NOT an engineering specification.
             */
            let score = 0;

            if (cv !== null) {
                score += Math.min(
                    60,
                    cv
                );
            }

            score += Math.min(
                40,
                (Number(item.outliers) || 0) * 5
            );

            const grade =
                analysisRiskLabel(score);

            const gradeColor =
                analysisColor(score);

            return `
                <tr>

                    <td>
                        <b>
                            ${esc(signal)}
                        </b>
                    </td>

                    <td>
                        ${fmt(mean)}
                    </td>

                    <td>
                        ${fmt(std)}
                    </td>

                    <td>
                        ${
                            cv == null
                                ? "—"
                                : `${cv.toFixed(2)}%`
                        }
                    </td>

                    <td>
                        ${fmt(median)}
                    </td>

                    <td>
                        ${fmt(mad)}
                    </td>

                    <td>
                        ${fmt(item.outliers)}
                    </td>

                    <td>
                        <span
                            style="
                                display:inline-block;
                                padding:3px 8px;
                                border-radius:10px;
                                border:1px solid ${gradeColor};
                                color:${gradeColor};
                                font-size:10px;
                                font-weight:700;
                            "
                        >
                            ${grade}
                        </span>
                    </td>

                </tr>
            `;
        });

    container.innerHTML = `
        <div style="overflow-x:auto;">

            <table class="table">

                <tr>
                    <th>SIGNAL</th>
                    <th>MEAN</th>
                    <th>STD</th>
                    <th>CV</th>
                    <th>MEDIAN</th>
                    <th>MAD</th>
                    <th>OUTLIERS</th>
                    <th>PROFILE</th>
                </tr>

                ${
                    rows.length
                        ? rows.join("")
                        : `
                            <tr>
                                <td colspan="8">
                                    No signal quality data available.
                                </td>
                            </tr>
                        `
                }

            </table>

        </div>

        <p
            class="muted"
            style="margin-top:10px;"
        >
            Profile grading is a descriptive visual
            prioritization based on variability and observed
            outlier count. It is not an engineering specification
            or automatic disposition decision.
        </p>
    `;
}


/* =========================================================
   REAL ML RESULT HELPERS
========================================================= */

function mlValue(model, ...keys) {
    for (const key of keys) {
        if (
            model &&
            Object.prototype.hasOwnProperty.call(
                model,
                key
            ) &&
            model[key] != null
        ) {
            return model[key];
        }
    }

    return null;
}


function mlModelName(model) {
    return mlValue(
        model,
        "model",
        "selected_model"
    );
}


function mlPrediction(model) {
    return mlValue(
        model,
        "prediction_168h_uA",
        "predicted_ir_168h_uA",
        "prediction",
        "ai_prediction_168h_uA"
    );
}


function mlLower(model) {
    return mlValue(
        model,
        "prediction_lower_05_uA",
        "ai_prediction_lower_05_uA"
    );
}


function mlMedian(model) {
    return mlValue(
        model,
        "prediction_median_50_uA",
        "ai_prediction_median_50_uA"
    );
}


function mlUpper(model) {
    return mlValue(
        model,
        "prediction_upper_95_uA",
        "ai_prediction_upper_95_uA"
    );
}


function mlInterval(model) {
    return mlValue(
        model,
        "prediction_interval_width_uA",
        "ai_prediction_interval_width_uA"
    );
}


function mlSlope(model) {
    return mlValue(
        model,
        "predicted_slope_24_168_uA_per_h",
        "ai_predicted_slope_24_168_uA_per_h"
    );
}


function mlSafetyMargin(model) {
    return mlValue(
        model,
        "safety_margin_uA",
        "ai_safety_margin_uA"
    );
}


function mlConformalUpper(model) {
    return mlValue(
        model,
        "conformal_safety_upper_uA",
        "ai_conformal_safety_upper_uA"
    );
}


function mlActual(model) {
    return mlValue(
        model,
        "actual_ir_168h_uA",
        "ai_actual_ir_168h_uA"
    );
}


function mlError(model) {
    return mlValue(
        model,
        "absolute_prediction_error_uA",
        "ai_absolute_prediction_error_uA"
    );
}

function moduleAResult(assessment, model) {
    return (
        assessment?.module_a ||
        model?.module_a ||
        {}
    );
}

function moduleAValue(moduleA, key, fallback = null) {
    if (
        moduleA &&
        Object.prototype.hasOwnProperty.call(moduleA, key) &&
        moduleA[key] != null
    ) {
        return moduleA[key];
    }
    return fallback;
}


/* =========================================================
   MODEL HEALTH · PHASE 8
========================================================= */

async function loadModelHealth() {
    const summary = $("#modelHealthSummary");
    const registryNode = $("#modelRegistry");
    const applicabilityNode = $("#modelApplicability");
    const driftNode = $("#modelDrift");
    const calibrationNode = $("#modelCalibration");

    if (!S.active) {
        if (summary) summary.innerHTML = card("MODEL HEALTH", "No active dataset");
        if (registryNode) registryNode.innerHTML = '<p class="muted">Activate a dataset first.</p>';
        if (applicabilityNode) applicabilityNode.innerHTML = '<p class="muted">No applicability result.</p>';
        if (driftNode) driftNode.innerHTML = '<p class="muted">No drift result.</p>';
        if (calibrationNode) calibrationNode.innerHTML = '<p class="muted">No calibration result.</p>';
        return;
    }

    try {
        const h = await api(`/datasets/${S.active.dataset_id}/model-health`);
        S.modelHealth = h;
        renderModelHealth();
    } catch (e) {
        toast(e.message);
    }
}

function renderModelHealth() {
    const h = S.modelHealth || {};
    const registry = h.registry || {};
    const applicability = h.applicability || {};
    const drift = h.drift || {};
    const calibration = h.calibration || {};
    const models = Array.isArray(registry.models) ? registry.models : [];
    const production = models.filter(m => m.status === "PRODUCTION");

    $("#modelHealthSummary").innerHTML = [
        card("PRODUCTION MODELS", production.length),
        card("APPLICABILITY", applicability.status || "UNAVAILABLE"),
        card("DRIFT", drift.status || "UNAVAILABLE"),
        card("CALIBRATION", calibration.status || "UNAVAILABLE"),
        card("96h ML ARTIFACT", registry.discovered_96h_model ? "DISCOVERED" : "NOT PRESENT")
    ].join("");

    $("#modelRegistry").innerHTML = models.length
        ? `
            <div class="model-health-note">
                <b>SCHEMA FINGERPRINT</b>
                <code>${esc((registry.schema?.fingerprint || "").slice(0, 20))}${registry.schema?.fingerprint ? "…" : ""}</code>
                <span>${registry.schema?.base_contract_satisfied ? "Base contract satisfied" : "Base contract incomplete"}</span>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>MODEL</th>
                            <th>STATUS</th>
                            <th>CUTOFF</th>
                            <th>FEATURES</th>
                            <th>ARTIFACT SHA-256</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${models.map(m => `
                            <tr>
                                <td><b>${esc(m.model_id)}</b><br><span class="muted">${esc(m.target || "—")}</span></td>
                                <td>${esc(m.status || "—")}</td>
                                <td>${fmt(m.prediction_cutoff_h)}h</td>
                                <td>${Number((m.feature_set || []).length)}</td>
                                <td><code>${esc((m.artifact_sha256 || "missing").slice(0, 16))}${m.artifact_sha256 ? "…" : ""}</code></td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            </div>
            <p class="muted">${esc(registry.policy || "")}</p>
        `
        : '<p class="muted">No model registry entries available.</p>';

    const counts = applicability.counts || {};
    $("#modelApplicability").innerHTML = `
        <div class="model-health-kpi">
            <strong>${esc(applicability.status || "UNAVAILABLE")}</strong>
            <span>${Number(applicability.evaluated_components || 0).toLocaleString()} component(s) evaluated${applicability.sample_limited ? " · deterministic sample" : ""}</span>
        </div>
        <div class="health-count-grid">
            ${Object.entries(counts).map(([name, value]) => `
                <div><b>${esc(name)}</b><span>${Number(value).toLocaleString()}</span></div>
            `).join("") || '<p class="muted">No applicability counts available.</p>'}
        </div>
        ${(applicability.examples || []).length ? `
            <div class="health-examples">
                <b>REVIEW EXAMPLES</b>
                ${(applicability.examples || []).map(x => `
                    <div><code>${esc(x.component_id)}</code><span>${esc(x.status)}</span><small>${esc(x.reason || "")}</small></div>
                `).join("")}
            </div>
        ` : ""}
        <p class="muted">Applicability checks model-contract compatibility and robust distance from the Phase-1 training reference. It is not a probability.</p>
    `;

    const metrics = Array.isArray(drift.metrics) ? drift.metrics : [];
    $("#modelDrift").innerHTML = `
        <div class="model-health-kpi inline-health-kpi">
            <strong>${esc(drift.status || "UNAVAILABLE")}</strong>
            <span>${esc(drift.comparison || "No comparison")}</span>
        </div>
        <div class="table-wrap">
            <table>
                <thead><tr><th>METRIC</th><th>REFERENCE</th><th>CURRENT</th><th>SHIFT</th><th>STATE</th></tr></thead>
                <tbody>
                    ${metrics.map(m => `
                        <tr>
                            <td>${esc(m.metric || "—")}</td>
                            <td>${fmt(m.reference_median ?? m.reference_pct)}</td>
                            <td>${fmt(m.current_median ?? m.current_pct)}</td>
                            <td>${fmt(m.median_shift_robust_sigma ?? m.delta_percentage_points)}</td>
                            <td><b>${esc(m.severity || (m.available === false ? "UNAVAILABLE" : "—"))}</b></td>
                        </tr>
                    `).join("") || '<tr><td colspan="5">No drift metrics available.</td></tr>'}
                </tbody>
            </table>
        </div>
        <p class="muted">${esc(drift.continuous_semantics || "")}</p>
    `;

    const calMetrics = Array.isArray(calibration.metrics) ? calibration.metrics : [];
    $("#modelCalibration").innerHTML = `
        <div class="model-health-kpi inline-health-kpi">
            <strong>${esc(calibration.status || "UNAVAILABLE")}</strong>
            <span>${Number(calibration.evaluation_components || 0)} evaluation components</span>
        </div>
        <div class="table-wrap">
            <table>
                <thead><tr><th>METRIC</th><th>EXPECTED</th><th>OBSERVED</th><th>GAP</th><th>STATE</th></tr></thead>
                <tbody>
                    ${calMetrics.map(m => `
                        <tr>
                            <td>${esc(m.metric || "—")}</td>
                            <td>${fmt(m.expected_pct)}%</td>
                            <td>${fmt(m.observed_pct)}%</td>
                            <td>${fmt(m.gap_percentage_points)} pp</td>
                            <td><b>${esc(m.state || "—")}</b></td>
                        </tr>
                    `).join("") || '<tr><td colspan="5">No calibration metrics available.</td></tr>'}
                </tbody>
            </table>
        </div>
        <p class="muted">${esc(calibration.semantics || "")}</p>
    `;
}


/* =========================================================
   LOT INTELLIGENCE · PHASE 9
========================================================= */

async function loadLotIntelligence() {
    if (!S.active) return;
    try {
        S.lotIntelligence = await api(`/datasets/${S.active.dataset_id}/lot-intelligence`);
        renderLotIntelligence();
    } catch (e) {
        toast(e.message);
    }
}

function renderLotIntelligence() {
    const payload = S.lotIntelligence || {};
    const health = payload.health || {};
    const common = payload.commonality || {};
    const lots = Array.isArray(health.lots) ? health.lots : [];
    const commonalities = Array.isArray(common.commonalities) ? common.commonalities : [];
    const numeric = Array.isArray(common.numeric_shifts) ? common.numeric_shifts : [];

    const summary = $("#lotHealthSummary");
    if (summary) {
        summary.innerHTML = [
            card("LOT HEALTH", health.status || "UNAVAILABLE"),
            card("LOTS", Number(health.lot_count || 0)),
            card("BATCHES", Number(health.batch_count || 0)),
            card("ESCALATED COMPONENTS", Number(common.risky_components || 0))
        ].join("");
    }

    const table = $("#lotHealthTable");
    if (table) {
        table.innerHTML = `
            <div class="table-wrap"><table>
                <thead><tr><th>LOT</th><th>COMPONENTS</th><th>STATE</th><th>ESCALATED</th><th>REJECT</th><th>24h OUTLIERS</th><th>QA OVERRIDES</th></tr></thead>
                <tbody>
                    ${lots.map(r => `
                        <tr>
                            <td><b>${esc(r.lot_id || "—")}</b></td>
                            <td>${fmt(r.components)}</td>
                            <td><b>${esc(r.health_state || "—")}</b></td>
                            <td>${fmt(r.module_a_escalated_pct)}%</td>
                            <td>${fmt(r.module_a_reject_pct)}%</td>
                            <td>${fmt(r.robust_z_24h_outlier_pct)}%</td>
                            <td>${fmt(r.qa_override_rate_pct || 0)}%</td>
                        </tr>
                    `).join("") || '<tr><td colspan="7">No lot health evidence available.</td></tr>'}
                </tbody>
            </table></div>
            <p class="muted">${esc(health.semantics || "")}</p>
        `;
    }

    const panel = $("#commonalityPanel");
    if (panel) {
        panel.innerHTML = `
            <div class="model-health-kpi inline-health-kpi">
                <strong>${esc(common.status || "UNAVAILABLE")}</strong>
                <span>${Number(common.risky_components || 0)} escalated vs ${Number(common.reference_components || 0)} reference components</span>
            </div>
            <div class="two">
                <div class="table-wrap"><table>
                    <thead><tr><th>FIELD</th><th>VALUE</th><th>RISK SUPPORT</th><th>REFERENCE</th><th>ENRICHMENT</th></tr></thead>
                    <tbody>
                        ${commonalities.map(r => `
                            <tr><td>${esc(r.field)}</td><td>${esc(r.value)}</td><td>${fmt(r.risky_support_pct)}%</td><td>${fmt(r.reference_support_pct)}%</td><td>${fmt(r.enrichment_ratio)}×</td></tr>
                        `).join("") || '<tr><td colspan="5">No strong categorical commonality found.</td></tr>'}
                    </tbody>
                </table></div>
                <div class="table-wrap"><table>
                    <thead><tr><th>FEATURE</th><th>RISK MEDIAN</th><th>REFERENCE MEDIAN</th><th>DELTA</th></tr></thead>
                    <tbody>
                        ${numeric.map(r => `
                            <tr><td>${esc(r.feature)}</td><td>${fmt(r.risky_median)}</td><td>${fmt(r.reference_median)}</td><td>${fmt(r.median_delta)}</td></tr>
                        `).join("") || '<tr><td colspan="4">No numeric commonality evidence.</td></tr>'}
                    </tbody>
                </table></div>
            </div>
            <p class="muted">${esc(common.semantics || "")}</p>
        `;
    }
}


/* =========================================================
   QA INSPECTOR
========================================================= */

async function loadAssessment() {
    if (!S.active) return;

    try {
        const a = await api(
            `/datasets/${S.active.dataset_id}/inspection/${S.record}/assessment`
        );

        S.assessment = a;

        const recommendedAction =
            a.reliability_unified_action ||
            a.explanation?.recommended_action ||
            "";

        if (!S.qaAction && recommendedAction) {
            S.qaAction = recommendedAction;
        }

        const inspectionCount =
            Number(a.inspection_count || S.active.inspection_count || S.active.rows || 0);

        const inspectionLabel =
            a.inspection_mode === "component"
                ? "Component"
                : "Record";

        $("#record").textContent =
            `${inspectionLabel} ${a.inspection_index + 1} of ${inspectionCount.toLocaleString()}`;


        /* -----------------------------------------------------
           STATISTICAL EVIDENCE
        ----------------------------------------------------- */

        $("#evidence").innerHTML = `
            <div class="score-row">

                <div class="score">
                    ${fmt(a.score)}
                    <small>/100</small>
                    <span>ANALYTICAL</span>
                </div>

                <div class="state">
                    ${esc(a.state)}
                </div>

            </div>

            <p class="muted">
                ${esc(a.mode)}
                · Evidence coverage
                ${fmt(a.evidence_coverage)}%
            </p>

            <div class="evidence">

                ${
                    (a.contributors || [])
                        .map(c => `
                            <div class="eitem">

                                <b>
                                    ${esc(c.signal)}
                                </b>

                                <span>
                                    Value
                                    ${fmt(c.value)}
                                </span>

                                <span>
                                    Baseline
                                    ${fmt(c.baseline)}
                                </span>

                                <span>
                                    Robust-z
                                    ${fmt(c.robust_z)}
                                </span>

                            </div>
                        `)
                        .join("")
                    ||
                    "No strong population deviation detected."
                }

            </div>
        `;


        /* -----------------------------------------------------
           ORIGINAL SPARK MODULE-A + MODULE-B EVIDENCE
        ----------------------------------------------------- */

        const m = a.model || {};
        const ma = moduleAResult(a, m);
        const mb = m.module_b || m;

        const modelName =
            mlModelName(mb);

        const prediction =
            mlPrediction(mb);

        const lower =
            mlLower(mb);

        const median =
            mlMedian(mb);

        const upper =
            mlUpper(mb);

        const interval =
            mlInterval(mb);

        const slope =
            mlSlope(mb);

        const safety =
            mlSafetyMargin(mb);

        const conformal =
            mlConformalUpper(mb);

        const actual =
            mlActual(mb);

        const error =
            mlError(mb);

        const mlAvailable =
            mb.available === true ||
            prediction != null ||
            median != null;

        const moduleAAvailable =
            ma.available === true;

        const moduleAAction =
            moduleAValue(
                ma,
                "action",
                "No anomaly result"
            );

        const moduleAReason =
            moduleAValue(
                ma,
                "primary_reason",
                ma.message ||
                "No validated Module-A evidence was returned."
            );

        const withinLot =
            moduleAValue(
                ma,
                "within_lot_risk_score"
            );

        const historicalRisk =
            moduleAValue(
                ma,
                "historical_risk_score"
            );

        const lotShift =
            moduleAValue(
                ma,
                "lot_shift_risk_score"
            );

        const batchShift =
            moduleAValue(
                ma,
                "batch_slope_shift_score"
            );

        const isolationScore =
            moduleAValue(
                ma,
                "isolation_forest_raw_score"
            );

        const isolationOutlier =
            moduleAValue(
                ma,
                "isolation_forest_is_outlier"
            );

        const staticLimitFailed =
            moduleAValue(
                ma,
                "static_limit_failed_at_24h"
            );

        const ir0 =
            moduleAValue(
                ma,
                "ir_0h_uA"
            );

        const ir24 =
            moduleAValue(
                ma,
                "ir_24h_uA"
            );

        const dataConfidence =
            a.data_confidence || {};

        const engineeringSafety =
            a.engineering_safety || {};

        const dataChecks =
            Array.isArray(dataConfidence.checks)
                ? dataConfidence.checks
                : [];

        const safetyFailures =
            Array.isArray(engineeringSafety.failures)
                ? engineeringSafety.failures
                : [];

        const applicability = a.model_applicability || {};
        $("#applicabilityPanel").innerHTML = `
            <div class="phase8-evidence-card applicability-card">
                <div class="phase8-evidence-head">
                    <div>
                        <span>MODEL APPLICABILITY / OOD GATE</span>
                        <strong>${esc(applicability.status || "UNAVAILABLE")}</strong>
                    </div>
                    <em>${applicability.applicable === true ? "MODEL USE AUTHORIZED" : "ABSTAIN / REVIEW"}</em>
                </div>
                <p>${esc(applicability.reason || "No applicability evidence available.")}</p>
                <div class="phase8-evidence-grid">
                    <div><b>POPULATION</b><span>${esc(applicability.population_similarity || "—")}</span></div>
                    <div><b>MAX ROBUST DISTANCE</b><span>${fmt(applicability.max_robust_distance)}</span></div>
                    <div><b>METHOD</b><span>${esc(applicability.method || "—")}</span></div>
                    <div><b>FUTURE DATA</b><span>${applicability.uses_future_measurements === false ? "NOT USED" : "—"}</span></div>
                </div>
            </div>
        `;

        const rolling = a.rolling_forecast || {};
        $("#rollingForecastPanel").innerHTML = `
            <div class="phase8-evidence-card rolling-card">
                <div class="phase8-evidence-head">
                    <div>
                        <span>ROLLING 24h → 96h → 168h UPDATE</span>
                        <strong>${esc(rolling.trajectory || rolling.status || "UNAVAILABLE")}</strong>
                    </div>
                    <em>${rolling.is_trained_96h_ml_model === true ? "96h ML" : "ENGINEERING UPDATE"}</em>
                </div>
                <div class="phase8-evidence-grid">
                    <div><b>24h ML FORECAST</b><span>${fmt(rolling.module_b_24h_forecast_168h_uA)} µA</span></div>
                    <div><b>OBSERVED @ 96h</b><span>${fmt(rolling.observed_ir_96h_uA)} µA</span></div>
                    <div><b>UPDATED 168h</b><span>${fmt(rolling.updated_168h_uA)} µA</span></div>
                    <div><b>FORECAST SHIFT</b><span>${fmt(rolling.forecast_shift_uA)} µA</span></div>
                </div>
                <p>${esc(rolling.message || "Waiting for rolling forecast evidence.")}</p>
                <p class="muted">The 96h update is kept separate from the trained Module-B 24h model unless a validated 96h artifact is explicitly integrated.</p>
            </div>
        `;

        $("#guardrailPanel").innerHTML = `
            <div class="guardrail-grid">

                <div class="guardrail-card">
                    <div class="guardrail-title">
                        <span>DATA TRUST GATE</span>
                        <strong>${esc(dataConfidence.status || "UNAVAILABLE")}</strong>
                    </div>

                    <div class="guardrail-value">
                        ${fmt(dataConfidence.score_pct)}
                        <small>%</small>
                    </div>

                    <p>${esc(dataConfidence.reason || "No data-confidence result available.")}</p>

                    <div class="guardrail-checks">
                        ${
                            dataChecks.map(item => `
                                <span class="${item.passed ? "gate-pass" : "gate-fail"}">
                                    ${item.passed ? "PASS" : "CHECK"} · ${esc(item.name)}
                                </span>
                            `).join("")
                            || '<span class="muted">No quality checks available.</span>'
                        }
                    </div>
                </div>

                <div class="guardrail-card">
                    <div class="guardrail-title">
                        <span>ENGINEERING SAFETY GATE</span>
                        <strong>${esc(engineeringSafety.status || "UNAVAILABLE")}</strong>
                    </div>

                    <div class="guardrail-value">
                        ${fmt(engineeringSafety.minimum_margin_uA)}
                        <small> µA margin</small>
                    </div>

                    <p>${esc(engineeringSafety.reason || "No engineering-limit result available.")}</p>

                    <div class="guardrail-checks">
                        <span class="${engineeringSafety.hard_failure === true ? "gate-fail" : "gate-pass"}">
                            ${engineeringSafety.hard_failure === true ? "HARD FAIL" : "NO HARD LIMIT BREACH"}
                        </span>
                        <span>
                            ${Number(engineeringSafety.observations_checked || 0)} early observation(s) checked
                        </span>
                        ${
                            safetyFailures.length
                                ? `<span class="gate-fail">${safetyFailures.length} hard failure(s)</span>`
                                : ""
                        }
                    </div>
                </div>

            </div>
        `;


        const reliabilityRisk = a.reliability_risk || {};
        const riskScore = reliabilityRisk.reliability_risk_score;
        const riskAction = reliabilityRisk.unified_action || "HOLD";
        const riskBand = reliabilityRisk.risk_band || "INDETERMINATE";
        const evidenceCompleteness = reliabilityRisk.evidence_completeness_pct;
        const forecastUtil = reliabilityRisk.forecast_limit_utilization_pct;

        $("#riskPanel").innerHTML = `
            <div class="risk-engine-card">
                <div class="risk-engine-head">
                    <div>
                        <span>UNIFIED RELIABILITY RISK ENGINE</span>
                        <strong>${esc(riskAction)}</strong>
                    </div>
                    <div class="risk-score">
                        ${riskScore == null ? "—" : fmt(riskScore)}
                        <small>${riskScore == null ? "" : "/100"}</small>
                    </div>
                </div>

                <div class="risk-engine-grid">
                    <div>
                        <b>RISK BAND</b>
                        <span>${esc(riskBand)}</span>
                    </div>
                    <div>
                        <b>EVIDENCE COMPLETENESS</b>
                        <span>${fmt(evidenceCompleteness)}%</span>
                    </div>
                    <div>
                        <b>FORECAST / LIMIT</b>
                        <span>${forecastUtil == null ? "—" : `${fmt(forecastUtil)}%`}</span>
                    </div>
                    <div>
                        <b>SAFETY OVERRIDE</b>
                        <span>${reliabilityRisk.safety_override === true ? "ACTIVE" : "NO"}</span>
                    </div>
                </div>

                <p>${esc(reliabilityRisk.reason || "No unified reliability result available.")}</p>
                <p class="muted">
                    The risk score is a transparent QA prioritisation index, not a calibrated probability of failure.
                    Data-trust and hard engineering limits always take precedence over ML evidence.
                </p>
            </div>
        `;

        const explanation = a.explanation || {};
        const reasonCodes = explanation.reason_codes || [];
        const decisionPath = explanation.decision_path || [];

        $("#explanationPanel").innerHTML = `
            <div class="explainability-card">
                <div class="explainability-head">
                    <div>
                        <span>EXPLAINABLE QA DECISION</span>
                        <strong>${esc(explanation.primary_reason_code || "NO-CODE")}</strong>
                    </div>
                    <div class="explainability-action">
                        ${esc(explanation.recommended_action || riskAction)}
                    </div>
                </div>

                <div class="primary-reason">
                    <b>${esc(explanation.primary_reason_title || "Decision rationale")}</b>
                    <p>${esc(explanation.primary_reason || reliabilityRisk.reason || "No explanation available.")}</p>
                </div>

                <div class="reason-code-list">
                    ${reasonCodes.map(r => `
                        <div class="reason-code-item reason-${String(r.severity || "info").toLowerCase()}">
                            <div class="reason-code-meta">
                                <code>${esc(r.code || "—")}</code>
                                <span>${esc(r.source || "—")}</span>
                                <em>${esc(r.severity || "—")}</em>
                            </div>
                            <b>${esc(r.title || "Reason")}</b>
                            <p>${esc(r.detail || "")}</p>
                        </div>
                    `).join("") || `<p class="muted">No ranked reason codes available.</p>`}
                </div>

                <div class="decision-path">
                    ${decisionPath.map(step => `
                        <div>
                            <span>${esc(step.layer || "—")}</span>
                            <b>${esc(step.status || "—")}</b>
                            <em>${esc(step.action || "—")}</em>
                        </div>
                    `).join("")}
                </div>

                <p class="muted">
                    Deterministic reason-code hierarchy. No LLM is used to create or change the recommendation.
                </p>
            </div>
        `;

        $("#comparisonPanel").innerHTML = `
            <div class="compare">

                <div>
                    <span>GENERIC ANALYTICAL</span>
                    <strong>
                        ${fmt(a.score)}
                        <small>/100</small>
                    </strong>
                    <em>${esc(a.state)}</em>
                </div>

                <div>
                    <span>MODULE A · DYNAMIC ANOMALY</span>
                    <strong class="module-a-action">
                        ${esc(moduleAAction)}
                    </strong>
                    <em>
                        ${
                            moduleAAvailable
                                ? "Original 24h anomaly engine"
                                : "Inference unavailable"
                        }
                    </em>
                </div>

                <div>
                    <span>MODULE B · 168h FORECAST</span>
                    <strong>
                        ${fmt(prediction)}
                        <small> µA</small>
                    </strong>
                    <em>
                        ${esc(
                            modelName ||
                            "No inference"
                        )}
                    </em>
                </div>

            </div>


            <div class="model-status module-a-status">
                <b>
                    ${
                        moduleAAvailable
                            ? "ORIGINAL SPARK MODULE-A DYNAMIC ANOMALY PIPELINE"
                            : "MODULE-A INFERENCE UNAVAILABLE"
                    }
                </b>

                <p>
                    ${esc(moduleAReason)}
                </p>
            </div>


            <div class="ml-details module-a-details">

                <div class="eitem">
                    <b>IR @ 0h</b>
                    <span>${fmt(ir0)} µA</span>
                </div>

                <div class="eitem">
                    <b>IR @ 24h</b>
                    <span>${fmt(ir24)} µA</span>
                </div>

                <div class="eitem">
                    <b>WITHIN-LOT RISK</b>
                    <span>${fmt(withinLot)}</span>
                </div>

                <div class="eitem">
                    <b>HISTORICAL RISK</b>
                    <span>${fmt(historicalRisk)}</span>
                </div>

                <div class="eitem">
                    <b>LOT-SHIFT RISK</b>
                    <span>${fmt(lotShift)}</span>
                </div>

                <div class="eitem">
                    <b>BATCH-SLOPE SHIFT</b>
                    <span>${fmt(batchShift)}</span>
                </div>

                <div class="eitem">
                    <b>ISOLATION FOREST SCORE</b>
                    <span>${fmt(isolationScore)}</span>
                </div>

                <div class="eitem">
                    <b>ISOLATION FOREST</b>
                    <span>
                        ${
                            isolationOutlier == null
                                ? "—"
                                : (isolationOutlier ? "OUTLIER" : "NOMINAL")
                        }
                    </span>
                </div>

                <div class="eitem">
                    <b>STATIC LIMIT @ 24h</b>
                    <span>
                        ${
                            staticLimitFailed == null
                                ? "—"
                                : (staticLimitFailed ? "FAILED" : "PASSED")
                        }
                    </span>
                </div>

            </div>


            <div class="model-status module-b-status">
                <b>
                    ${
                        mlAvailable
                            ? "ORIGINAL SPARK MODULE-B DRIFT FORECAST PIPELINE"
                            : "MODULE-B INFERENCE UNAVAILABLE"
                    }
                </b>

                <p>
                    ${esc(
                        mb.message ||
                        "No validated Module-B inference was returned for this component."
                    )}
                </p>
            </div>


            <div class="ml-details">

                <div class="eitem">
                    <b>168h PREDICTION</b>
                    <span>${fmt(prediction)} µA</span>
                </div>

                <div class="eitem">
                    <b>5% LOWER</b>
                    <span>${fmt(lower)} µA</span>
                </div>

                <div class="eitem">
                    <b>50% MEDIAN</b>
                    <span>${fmt(median)} µA</span>
                </div>

                <div class="eitem">
                    <b>95% UPPER</b>
                    <span>${fmt(upper)} µA</span>
                </div>

                <div class="eitem">
                    <b>INTERVAL WIDTH</b>
                    <span>${fmt(interval)} µA</span>
                </div>

                <div class="eitem">
                    <b>PREDICTED SLOPE</b>
                    <span>${fmt(slope)} µA/h</span>
                </div>

                <div class="eitem">
                    <b>SAFETY MARGIN</b>
                    <span>${fmt(safety)} µA</span>
                </div>

                <div class="eitem">
                    <b>CONFORMAL UPPER</b>
                    <span>${fmt(conformal)} µA</span>
                </div>

                <div class="eitem">
                    <b>ACTUAL 168h (EVAL)</b>
                    <span>${fmt(actual)} µA</span>
                </div>

                <div class="eitem">
                    <b>ABS. ERROR (EVAL)</b>
                    <span>${fmt(error)} µA</span>
                </div>

            </div>
        `;

        /* -----------------------------------------------------
           ENGINEERING COMMENT
        ----------------------------------------------------- */

        $("#aiComment").innerHTML = `
            <b>ENGINEERING ASSESSMENT</b>

            <p>
                ${esc(
                    a.qa_comment ||
                    "No assessment comment available."
                )}
            </p>
        `;


        renderQAPanel();


        /* -----------------------------------------------------
           INSPECTOR RECORD
        ----------------------------------------------------- */

        $("#inspectorPanel").innerHTML = `
            <p class="muted">
                ${a.inspection_mode === "component" ? "Component" : "Record"}
                ${a.inspection_index + 1}
                ${a.component_id ? `· ${esc(a.component_id)}` : ""}
                is ready for human disposition.
                The inspector may agree with the machine
                evidence or override it with a documented reason.
            </p>

            <p class="muted">
                Data Trust, Engineering Safety, statistical evidence,
                original SPARK Module-A anomaly evidence and Module-B drift
                forecasting are presented as decision-support evidence.
                A hard engineering-limit failure is non-negotiable.
            </p>
        `;

    } catch (e) {
        toast(e.message);
    }
}


/* =========================================================
   QA DISPOSITION
========================================================= */

function renderQAPanel() {
    const panel = $("#qaPanel");

    if (!panel) return;

    panel.innerHTML = `
        <div class="qa-actions">

            ${
                [
                    "ACCEPT",
                    "WATCH",
                    "RETEST",
                    "HOLD",
                    "REJECT",
                    "QUARANTINE",
                    "ABSTAIN"
                ]
                .map(x => `
                    <button
                        class="${
                            S.qaAction === x
                                ? "selected"
                                : ""
                        }"
                        onclick="selectQA('${x}')">
                        ${x}
                    </button>
                `)
                .join("")
            }

        </div>


        <div class="response-row">

            <label>
                REVIEW RESPONSE
            </label>

            <select id="response">

                <option>AGREE</option>
                <option>OVERRIDE</option>
                <option>NOTE</option>

            </select>


            <select
                id="overrideAction"
                style="display:none">

                <option value="">
                    Override action
                </option>

                ${
                    [
                        "ACCEPT",
                        "WATCH",
                        "RETEST",
                        "HOLD",
                        "REJECT",
                        "QUARANTINE",
                        "ABSTAIN"
                    ]
                    .map(x => `
                        <option>${x}</option>
                    `)
                    .join("")
                }

            </select>

        </div>

        <div id="overrideGovernance" class="override-governance" style="display:none">
            <label>OVERRIDE REASON CODE</label>
            <select id="overrideReasonCode">
                <option value="">Select controlled reason</option>
                <option value="QA-OVR-001">QA-OVR-001 · Verified measurement context</option>
                <option value="QA-OVR-002">QA-OVR-002 · Tester or instrument evidence</option>
                <option value="QA-OVR-003">QA-OVR-003 · Verified component history</option>
                <option value="QA-OVR-004">QA-OVR-004 · Approved engineering review</option>
                <option value="QA-OVR-005">QA-OVR-005 · Controlled procedure requirement</option>
                <option value="QA-OVR-006">QA-OVR-006 · Suspected model or threshold limitation</option>
                <option value="QA-OVR-007">QA-OVR-007 · Other controlled exception</option>
            </select>
            <textarea
                id="overrideJustification"
                minlength="20"
                placeholder="Mandatory override justification (minimum 20 characters)..."
            ></textarea>
            <p class="muted">Overrides are classified and retained as QA feedback. Hard engineering failures cannot be relaxed below REJECT/QUARANTINE, and Data Trust RETEST cannot become ACCEPT.</p>
        </div>


        <textarea
            id="comment"
            placeholder="Inspector rationale or QA note..."
        ></textarea>


        <button
            class="primary save"
            onclick="saveQA()">
            Record disposition
        </button>
    `;


    $("#response").value =
        S.qaResponse;


    $("#response").onchange =
        e => {
            S.qaResponse =
                e.target.value;

            const isOverride = e.target.value === "OVERRIDE";
            $("#overrideAction").style.display = isOverride ? "block" : "none";
            $("#overrideGovernance").style.display = isOverride ? "grid" : "none";
        };

    const initialOverride = S.qaResponse === "OVERRIDE";
    $("#overrideAction").style.display = initialOverride ? "block" : "none";
    $("#overrideGovernance").style.display = initialOverride ? "grid" : "none";
}


window.selectQA = x => {
    S.qaAction = x;
    renderQAPanel();
};


window.saveQA = async () => {
    if (
        !S.assessment ||
        !S.qaAction
    ) {
        toast(
            "Select a QA disposition first."
        );

        return;
    }

    const response =
        $("#response").value;

    const overrideAction =
        $("#overrideAction").value;

    if (
        response === "OVERRIDE" &&
        !overrideAction
    ) {
        toast(
            "Select the override action."
        );

        return;
    }

    const machineRecommendation =
        S.assessment.reliability_unified_action ||
        S.assessment.explanation?.recommended_action ||
        S.qaAction;

    const overrideReasonCode =
        $("#overrideReasonCode")?.value || "";

    const overrideJustification =
        $("#overrideJustification")?.value.trim() || "";

    if (response === "OVERRIDE" && !overrideReasonCode) {
        toast("Select an override reason code.");
        return;
    }

    if (response === "OVERRIDE" && overrideJustification.length < 20) {
        toast("Override justification must contain at least 20 characters.");
        return;
    }

    if (response !== "OVERRIDE" && S.qaAction !== machineRecommendation) {
        toast("A different QA action requires OVERRIDE governance.");
        return;
    }

    try {
        await api(
            `/qa/${S.active.dataset_id}`,
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({

                    inspection_index:
                        S.record,

                    record_index:
                        S.assessment.record_index,

                    inspection_mode:
                        S.assessment.inspection_mode,

                    action:
                        S.qaAction,

                    response,

                    override_action:
                        overrideAction,

                    machine_recommended_action:
                        machineRecommendation,

                    override_reason_code:
                        overrideReasonCode,

                    override_justification:
                        overrideJustification,

                    comment:
                        $("#comment").value,

                    component_id:
                        S.assessment.component_id,

                    measurement_time_h:
                        S.assessment.measurement_time_h,

                    lot_id:
                        S.assessment.lot_id,

                    burnin_batch_id:
                        S.assessment.burnin_batch_id,

                    analytical_score:
                        S.assessment.score,

                    analytical_state:
                        S.assessment.state,

                    analytical_contributors:
                        S.assessment.contributors || [],

                    data_confidence_status:
                        S.assessment.data_confidence_status,

                    data_confidence_score_pct:
                        S.assessment.data_confidence_score_pct,

                    data_confidence_action:
                        S.assessment.data_confidence_action,

                    data_confidence_snapshot:
                        S.assessment.data_confidence || {},

                    engineering_safety_status:
                        S.assessment.engineering_safety_status,

                    engineering_safety_action:
                        S.assessment.engineering_safety_action,

                    engineering_safety_hard_failure:
                        S.assessment.engineering_safety_hard_failure,

                    engineering_safety_minimum_margin_uA:
                        S.assessment.engineering_safety_minimum_margin_uA,

                    engineering_safety_snapshot:
                        S.assessment.engineering_safety || {},

                    reliability_risk_score:
                        S.assessment.reliability_risk_score,

                    reliability_risk_band:
                        S.assessment.reliability_risk_band,

                    reliability_evidence_completeness_pct:
                        S.assessment.reliability_evidence_completeness_pct,

                    reliability_unified_action:
                        S.assessment.reliability_unified_action,

                    reliability_reason:
                        S.assessment.reliability_reason,

                    reliability_risk_snapshot:
                        S.assessment.reliability_risk || {},

                    primary_reason_code:
                        S.assessment.primary_reason_code,

                    primary_reason_title:
                        S.assessment.primary_reason_title,

                    primary_reason:
                        S.assessment.primary_reason,

                    reason_codes:
                        S.assessment.reason_codes || [],

                    decision_path:
                        S.assessment.decision_path || [],

                    explanation_snapshot:
                        S.assessment.explanation || {},

                    module_a_available:
                        S.assessment.module_a_available,

                    module_a_action:
                        S.assessment.module_a_action,

                    module_a_primary_reason:
                        S.assessment.module_a_primary_reason,

                    module_a_within_lot_risk_score:
                        S.assessment.module_a_within_lot_risk_score,

                    module_a_historical_risk_score:
                        S.assessment.module_a_historical_risk_score,

                    module_a_lot_shift_risk_score:
                        S.assessment.module_a_lot_shift_risk_score,

                    module_a_batch_slope_shift_score:
                        S.assessment.module_a_batch_slope_shift_score,

                    module_a_isolation_forest_raw_score:
                        S.assessment.module_a_isolation_forest_raw_score,

                    module_a_isolation_forest_is_outlier:
                        S.assessment.module_a_isolation_forest_is_outlier,

                    module_a_static_limit_failed_at_24h:
                        S.assessment.module_a_static_limit_failed_at_24h,

                    ai_available:
                        S.assessment.ai_available,

                    ai_model:
                        S.assessment.ai_model,

                    ai_prediction_168h_uA:
                        S.assessment.ai_prediction_168h_uA,

                    ai_prediction_lower_05_uA:
                        S.assessment.ai_prediction_lower_05_uA,

                    ai_prediction_median_50_uA:
                        S.assessment.ai_prediction_median_50_uA,

                    ai_prediction_upper_95_uA:
                        S.assessment.ai_prediction_upper_95_uA,

                    ai_prediction_interval_width_uA:
                        S.assessment.ai_prediction_interval_width_uA,

                    ai_predicted_slope_24_168_uA_per_h:
                        S.assessment.ai_predicted_slope_24_168_uA_per_h,

                    ai_safety_margin_uA:
                        S.assessment.ai_safety_margin_uA,

                    ai_conformal_safety_upper_uA:
                        S.assessment.ai_conformal_safety_upper_uA,

                    ai_actual_ir_168h_uA:
                        S.assessment.ai_actual_ir_168h_uA,

                    ai_absolute_prediction_error_uA:
                        S.assessment.ai_absolute_prediction_error_uA,

                    ai_comment:
                        S.assessment.qa_comment,

                    assessment_source:
                        S.assessment.assessment_source || {},

                    model_snapshot:
                        S.assessment.model || {}

                })
            }
        );

        toast(
            "QA disposition recorded"
        );

        await loadHistory();

    } catch (e) {
        toast(e.message);
    }
};


/* =========================================================
   HISTORY
========================================================= */

/* The traceability table is rendered into #historyTable. */

function getHistoryContainer() {
    return $("#historyTable");
}

async function loadHistory() {
    if (!S.active) return;

    try {
        const [x, integrity, feedback, learning] = await Promise.all([
            api(`/qa/${S.active.dataset_id}`),
            api(`/qa/${S.active.dataset_id}/integrity`),
            api(`/qa/${S.active.dataset_id}/feedback-summary`),
            api(`/qa/${S.active.dataset_id}/feedback-learning`)
        ]);

        const container =
            getHistoryContainer();

        const integrityContainer = $("#ledgerIntegrity");
        if (integrityContainer) {
            const ok = integrity.integrity_ok === true;
            integrityContainer.innerHTML = `
                <div class="ledger-integrity ${ok ? "integrity-ok" : "integrity-fail"}">
                    <div>
                        <b>LEDGER INTEGRITY: ${esc(integrity.status || "UNKNOWN")}</b>
                        <span>${Number(integrity.entries || 0)} entries · ${Number(integrity.verified_v7_entries || 0)} governed v7 · ${Number(integrity.verified_v6_entries || 0)} sealed v6 · ${Number(integrity.legacy_entries || 0)} legacy</span>
                    </div>
                    <code>SHA-256</code>
                </div>
            `;
        }

        const feedbackContainer = $("#qaFeedbackSummary");
        if (feedbackContainer) {
            feedbackContainer.innerHTML = `
                <div class="qa-feedback-summary">
                    <div><b>QA FEEDBACK GOVERNANCE</b><span>${Number(feedback.governed_entries || 0)} governed decisions</span></div>
                    <div><b>${Number(feedback.overrides || 0)}</b><span>Overrides</span></div>
                    <div><b>${fmt(feedback.override_rate_pct || 0)}%</b><span>Override rate</span></div>
                    <div><b>${Number(feedback.model_threshold_review_flags || 0)}</b><span>Model/threshold review flags</span></div>
                </div>
            `;
        }

        const learningContainer = $("#feedbackLearningQueue");
        if (learningContainer) {
            const candidates = Array.isArray(learning.candidates) ? learning.candidates : [];
            learningContainer.innerHTML = `
                <div class="panel feedback-learning-panel">
                    <div class="panel-heading"><div><b>GOVERNED FEEDBACK LEARNING</b><span>Offline review candidates only · no automatic retraining</span></div><span class="panel-index">REVIEW</span></div>
                    <div class="table-wrap"><table>
                        <thead><tr><th>CANDIDATE</th><th>TYPE</th><th>PRIORITY</th><th>EVIDENCE</th><th>NEXT STEP</th></tr></thead>
                        <tbody>
                            ${candidates.map(c => `
                                <tr><td><b>${esc(c.candidate_id)}</b></td><td>${esc(c.type)}</td><td>${esc(c.priority)}</td><td>${fmt(c.evidence_count)}</td><td>${esc(c.recommended_next_step)}</td></tr>
                            `).join("") || '<tr><td colspan="5">No governed review candidates yet.</td></tr>'}
                        </tbody>
                    </table></div>
                </div>
            `;
        }

        if (!container) {
            return;
        }

        container.innerHTML =
            x.items.length
                ? `
                    <table class="table">

                        <tr>
                            <th>TIME</th>
                            <th>INSPECTION</th>
                            <th>SOURCE ROW</th>
                            <th>COMPONENT</th>
                            <th>ANALYTICAL</th>
                            <th>DATA TRUST</th>
                            <th>SAFETY</th>
                            <th>MODULE A</th>
                            <th>168h PRED.</th>
                            <th>RISK</th>
                            <th>RECOMMENDED</th>
                            <th>PRIMARY REASON</th>
                            <th>LEDGER HASH</th>
                            <th>ACTION</th>
                            <th>RESPONSE</th>
                            <th>DISAGREEMENT</th>
                            <th>OVERRIDE REASON</th>
                            <th>COMMENT</th>
                        </tr>

                        ${
                            x.items
                                .slice()
                                .reverse()
                                .map(i => `
                                    <tr>

                                        <td>
                                            ${
                                                new Date(
                                                    i.timestamp
                                                ).toLocaleString()
                                            }
                                        </td>

                                        <td>
                                            ${
                                                Number.isFinite(Number(i.inspection_index))
                                                    ? Number(i.inspection_index) + 1
                                                    : "—"
                                            }
                                        </td>

                                        <td>
                                            ${
                                                Number.isFinite(Number(i.record_index))
                                                    ? Number(i.record_index) + 1
                                                    : "—"
                                            }
                                        </td>

                                        <td>
                                            ${
                                                esc(
                                                    i.component_id ||
                                                    "—"
                                                )
                                            }
                                        </td>

                                        <td>
                                            ${
                                                fmt(
                                                    i.analytical_score
                                                )
                                            }
                                        </td>

                                        <td>
                                            ${
                                                esc(
                                                    i.data_confidence_status ||
                                                    "—"
                                                )
                                            }
                                            ${
                                                i.data_confidence_score_pct != null
                                                    ? ` · ${fmt(i.data_confidence_score_pct)}%`
                                                    : ""
                                            }
                                        </td>

                                        <td>
                                            ${
                                                esc(
                                                    i.engineering_safety_status ||
                                                    "—"
                                                )
                                            }
                                        </td>

                                        <td>
                                            ${
                                                esc(
                                                    i.module_a_action ||
                                                    "—"
                                                )
                                            }
                                        </td>

                                        <td>
                                            ${
                                                fmt(
                                                    i.ai_prediction_168h_uA
                                                )
                                            }
                                        </td>

                                        <td>
                                            ${
                                                i.reliability_risk_score == null
                                                    ? esc(i.reliability_risk_band || "—")
                                                    : `${fmt(i.reliability_risk_score)} · ${esc(i.reliability_risk_band || "—")}`
                                            }
                                        </td>

                                        <td>
                                            ${
                                                esc(
                                                    i.reliability_unified_action ||
                                                    "—"
                                                )
                                            }
                                        </td>

                                        <td>
                                            <code>${esc(i.primary_reason_code || "LEGACY")}</code>
                                        </td>

                                        <td title="${esc(i.entry_hash || "Legacy/unsealed entry")}">
                                            <code>${esc(i.entry_hash ? i.entry_hash.slice(0, 12) : "—")}</code>
                                        </td>

                                        <td>
                                            ${
                                                esc(
                                                    i.action
                                                )
                                            }
                                        </td>

                                        <td>
                                            ${
                                                esc(
                                                    i.response ||
                                                    "—"
                                                )
                                            }
                                        </td>

                                        <td>
                                            ${esc(i.disagreement_class || "LEGACY")}
                                        </td>

                                        <td title="${esc(i.override_justification || "")}">
                                            <code>${esc(i.override_reason_code || "—")}</code>
                                        </td>

                                        <td>
                                            ${
                                                esc(
                                                    i.comment ||
                                                    ""
                                                )
                                            }
                                        </td>

                                    </tr>
                                `)
                                .join("")
                        }

                    </table>
                `
                : "No QA decisions recorded.";

    } catch (e) {
        toast(e.message);
    }
}


/* =========================================================
   EVENT HANDLERS
========================================================= */

$$("nav button").forEach(b => {
    b.onclick = () =>
        go(b.dataset.view);
});


const beginButton =
    $("#begin");

if (beginButton) {
    beginButton.onclick = () =>
        go("qa");
}


const signalSelect =
    $("#signalSelect");

if (signalSelect) {
    signalSelect.onchange = e => {
        S.signal =
            e.target.value;

        drawSignal();
    };
}


const prevButton =
    $("#prev");

if (prevButton) {
    prevButton.onclick = () => {
        if (S.record > 0) {
            S.record--;
            loadAssessment();
        }
    };
}


const nextButton =
    $("#next");

if (nextButton) {
    nextButton.onclick = () => {

        if (
            S.active &&
            S.record <
                (S.active.inspection_count || S.active.rows) - 1
        ) {
            S.record++;
            loadAssessment();
        }
    };
}


/* =========================================================
   DATASET UPLOAD
========================================================= */

const upload =
    $("#upload");

if (upload) {
    upload.onchange =
        async e => {

            const f =
                e.target.files[0];

            if (!f) return;

            const fd =
                new FormData();

            fd.append(
                "file",
                f
            );

            try {

                await api(
                    "/datasets/upload",
                    {
                        method: "POST",
                        body: fd
                    }
                );

                await load();

                go("datasets");

                toast(
                    "Dataset added"
                );

            } catch (err) {
                toast(
                    err.message
                );
            }

            e.target.value = "";
        };
}


/* =========================================================
   APPLICATION START
========================================================= */

addEventListener(
    "load",
    async () => {

        /*
         * Initialize theme first so the first
         * rendered charts use the correct colours.
         */
        initTheme();

        try {

            const h =
                await api("/health");

            const health =
                $("#health");

            if (health) {
                health.textContent =
                    h.status.toUpperCase();
            }

            await load();

        } catch (e) {

            const health =
                $("#health");

            if (health) {
                health.textContent =
                    "OFFLINE";
            }

            toast(
                e.message
            );
        }
    }
);