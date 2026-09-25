const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

/* =========================================================
   APPLICATION STATE
========================================================= */

const S = {
    datasets: [],
    active: null,
    analysis: null,
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
                "RECORDS",
                d.rows?.toLocaleString() ?? "—"
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
                        ${d.rows?.toLocaleString() ?? "—"} records ·
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

                    <button
                        class="danger"
                        onclick="removeD('${esc(d.dataset_id)}')">
                        Remove
                    </button>

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
            "Dataset activated; inspection reset to record 1"
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

        Plotly.newPlot(
            "controlPlot",
            [
                {
                    x: x.values.map(
                        (_, i) => i + 1
                    ),
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
                    x: [1, n],
                    y: [x.ucl, x.ucl],
                    mode: "lines",
                    name: "UCL",
                    line: {
                        dash: "dash",
                        width: 1.5
                    }
                },
                {
                    x: [1, n],
                    y: [x.center, x.center],
                    mode: "lines",
                    name: "Center",
                    line: {
                        width: 1.5
                    }
                },
                {
                    x: [1, n],
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


/* =========================================================
   QA INSPECTOR
========================================================= */

async function loadAssessment() {
    if (!S.active) return;

    try {
        const a = await api(
            `/datasets/${S.active.dataset_id}/records/${S.record}/assessment`
        );

        S.assessment = a;

        $("#record").textContent =
            `Record ${a.record_index + 1} of ${S.active.rows.toLocaleString()}`;


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
           ORIGINAL SPARK MODULE-B ML
        ----------------------------------------------------- */

        const m = a.model || {};

        const modelName =
            mlModelName(m);

        const prediction =
            mlPrediction(m);

        const lower =
            mlLower(m);

        const median =
            mlMedian(m);

        const upper =
            mlUpper(m);

        const interval =
            mlInterval(m);

        const slope =
            mlSlope(m);

        const safety =
            mlSafetyMargin(m);

        const conformal =
            mlConformalUpper(m);

        const actual =
            mlActual(m);

        const error =
            mlError(m);

        const mlAvailable =
            m.available === true ||
            prediction != null ||
            median != null;


        $("#comparisonPanel").innerHTML = `
            <div class="compare">

                <div>

                    <span>
                        ANALYTICAL
                    </span>

                    <strong>
                        ${fmt(a.score)}
                        <small>/100</small>
                    </strong>

                    <em>
                        ${esc(a.state)}
                    </em>

                </div>


                <div>

                    <span>
                        ORIGINAL SPARK ML
                    </span>

                    <strong>
                        ${fmt(prediction)}
                        <small> µA @ 168h</small>
                    </strong>

                    <em>
                        ${esc(
                            modelName ||
                            "No inference"
                        )}
                    </em>

                </div>

            </div>


            <div class="model-status">

                <b>
                    ${
                        mlAvailable
                            ? "ORIGINAL SPARK MODULE-B ML PIPELINE"
                            : "ML INFERENCE UNAVAILABLE"
                    }
                </b>

                <p>
                    ${esc(
                        m.message ||
                        "No validated ML inference was returned for this record."
                    )}
                </p>

            </div>


            <div class="ml-details">

                <div class="eitem">
                    <b>168h PREDICTION</b>
                    <span>
                        ${fmt(prediction)} µA
                    </span>
                </div>

                <div class="eitem">
                    <b>5% LOWER</b>
                    <span>
                        ${fmt(lower)} µA
                    </span>
                </div>

                <div class="eitem">
                    <b>50% MEDIAN</b>
                    <span>
                        ${fmt(median)} µA
                    </span>
                </div>

                <div class="eitem">
                    <b>95% UPPER</b>
                    <span>
                        ${fmt(upper)} µA
                    </span>
                </div>

                <div class="eitem">
                    <b>INTERVAL WIDTH</b>
                    <span>
                        ${fmt(interval)} µA
                    </span>
                </div>

                <div class="eitem">
                    <b>PREDICTED SLOPE</b>
                    <span>
                        ${fmt(slope)} µA/h
                    </span>
                </div>

                <div class="eitem">
                    <b>SAFETY MARGIN</b>
                    <span>
                        ${fmt(safety)} µA
                    </span>
                </div>

                <div class="eitem">
                    <b>CONFORMAL UPPER</b>
                    <span>
                        ${fmt(conformal)} µA
                    </span>
                </div>

                <div class="eitem">
                    <b>ACTUAL 168h</b>
                    <span>
                        ${fmt(actual)} µA
                    </span>
                </div>

                <div class="eitem">
                    <b>ABS. ERROR</b>
                    <span>
                        ${fmt(error)} µA
                    </span>
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
                Record ${a.record_index + 1}
                is ready for human disposition.
                The inspector may agree with the machine
                evidence or override it with a documented reason.
            </p>

            <p class="muted">
                Statistical evidence and the original SPARK
                ML pipeline are presented as decision-support
                evidence only.
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
                    "QUARANTINE"
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

            $("#overrideAction").style.display =
                e.target.value === "OVERRIDE"
                    ? "block"
                    : "none";
        };
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

                    record_index:
                        S.record,

                    action:
                        S.qaAction,

                    response,

                    override_action:
                        overrideAction,

                    comment:
                        $("#comment").value,

                    analytical_score:
                        S.assessment.score,

                    analytical_state:
                        S.assessment.state,

                    ai_score:
                        S.assessment.ai_score,

                    ai_prediction:
                        S.assessment.ai_prediction,

                    ai_confidence:
                        S.assessment.ai_confidence,

                    ai_comment:
                        S.assessment.qa_comment

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

/*
 * Important:
 * The HTML currently contains:
 *
 * <section id="history">
 *     <div class="panel" id="history"></div>
 * </section>
 *
 * Both elements therefore have the same ID.
 *
 * We intentionally resolve the INNER panel here rather than
 * changing your existing HTML again. This prevents the
 * history section itself from being accidentally overwritten.
 */

function getHistoryContainer() {
    return $("#historyTable");
}

async function loadHistory() {
    if (!S.active) return;

    try {
        const x = await api(
            `/qa/${S.active.dataset_id}`
        );

        const container =
            getHistoryContainer();

        if (!container) {
            return;
        }

        container.innerHTML =
            x.items.length
                ? `
                    <table class="table">

                        <tr>
                            <th>TIME</th>
                            <th>RECORD</th>
                            <th>ANALYTICAL</th>
                            <th>AI</th>
                            <th>ACTION</th>
                            <th>RESPONSE</th>
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
                                                Number(
                                                    i.record_index
                                                ) + 1
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
                                                fmt(
                                                    i.ai_score
                                                )
                                            }
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
                S.active.rows - 1
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