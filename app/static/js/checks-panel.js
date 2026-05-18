// DETools â€” Checks Panel (Phase 2, v2)
// Right drawer with two tabs:
//   Configure â€” add/manage checks for the selected table
//   Run & Results â€” execute checks and view results
(function () {
    'use strict';

    // â”€â”€ State â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    let currentTarget = null;  // { connKey, database, schema, table }
    let catalog       = null;  // fetched once from /api/checks/catalog
    let columns       = [];    // fetched per-table from /api/tree/columns
    let checks        = [];    // client-side list of configured checks
    let nextId        = 1;     // local ID for deletion

    // â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    window.openChecksPanel = function (connKey, database, schema, table) {
        currentTarget = { connKey, database, schema, table };
        checks = [];

        _setText('cpTableName',    schema + '.' + table);
        _setText('cpDatabaseName', connKey + ' / ' + database);

        _renderChecksList();
        _clearResults();
        _hideSummary();

        // Reset to Configure tab
        const configBtn = document.querySelector('[data-bs-target="#cpTabConfig"]');
        if (configBtn && typeof bootstrap !== 'undefined') {
            bootstrap.Tab.getOrCreateInstance(configBtn).show();
        }

        // Fetch catalog (once) + columns (per table) in parallel
        const p1 = catalog
            ? Promise.resolve()
            : fetch('/api/checks/catalog').then(r => r.json()).then(d => { catalog = d.catalog; });

        const p2 = fetch(
            '/api/tree/columns?conn=' + encodeURIComponent(connKey) +
            '&db='     + encodeURIComponent(database) +
            '&schema=' + encodeURIComponent(schema) +
            '&table='  + encodeURIComponent(table)
        ).then(r => r.json()).then(d => { columns = d.columns || []; });

        Promise.all([p1, p2]).then(() => {
            _populateCatalogDropdown();
            _populateColumnDropdown();
        });

        document.getElementById('checksPanel').classList.add('open');
        document.body.classList.add('checks-panel-open');
    };

    window.closeChecksPanel = function () {
        document.getElementById('checksPanel').classList.remove('open');
        document.body.classList.remove('checks-panel-open');
        currentTarget = null;
    };

    // Switch to Run & Results tab (called by the "Run" shortcut in the checks list)
    window.cpSwitchToRun = function () {
        const runBtn = document.getElementById('cpTabRunBtn');
        if (runBtn && typeof bootstrap !== 'undefined') {
            bootstrap.Tab.getOrCreateInstance(runBtn).show();
        }
    };

    window.cpAddCheck = function () {
        const checkType = document.getElementById('cpCheckType').value;
        if (!checkType || !catalog) return;

        const entry     = catalog[checkType];
        const level     = entry.level;
        const colSelect = document.getElementById('cpColumn');
        const colName   = (level !== 'table') ? (colSelect.value || null) : null;

        // Extra params
        const params = {};
        (entry.extra_params || []).forEach(p => {
            const el = document.getElementById('cpParam_' + p);
            if (el) params[p] = el.value;
        });

        const parseThresh = id => {
            const v = parseFloat(document.getElementById(id).value);
            return isNaN(v) ? null : v;
        };
        const readOp = id => document.getElementById(id).value || '>';

        checks.push({
            _id:    nextId++,
            _label: entry.label,
            _unit:  entry.unit,
            check_type:        checkType,
            column_name:       colName,
            params,
            warning_op:        readOp('cpWarningOp'),
            warning_threshold: parseThresh('cpWarning'),
            error_op:          readOp('cpErrorOp'),
            error_threshold:   parseThresh('cpError'),
            fatal_op:          readOp('cpFatalOp'),
            fatal_threshold:   parseThresh('cpFatal'),
        });

        _renderChecksList();

        // Clear values only (keep check type + operators for quick repeat adds)
        ['cpWarning', 'cpError', 'cpFatal'].forEach(id => {
            document.getElementById(id).value = '';
        });
        (entry.extra_params || []).forEach(p => {
            const el = document.getElementById('cpParam_' + p);
            if (el) el.value = '';
        });
    };

    window.cpRemoveCheck = function (id) {
        checks = checks.filter(c => c._id !== id);
        _renderChecksList();
    };

    window.cpRunChecks = function () {
        if (!currentTarget || checks.length === 0) return;

        const btn = document.getElementById('cpRunBtn');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Runningâ€¦';
        _clearResults();
        _hideSummary();

        const payload = {
            conn_key:   currentTarget.connKey,
            database:   currentTarget.database,
            schema:     currentTarget.schema,
            table_name: currentTarget.table,
            checks: checks.map(c => ({
                check_type:        c.check_type,
                column_name:       c.column_name,
                params:            c.params,
                warning_op:        c.warning_op,
                warning_threshold: c.warning_threshold,
                error_op:          c.error_op,
                error_threshold:   c.error_threshold,
                fatal_op:          c.fatal_op,
                fatal_threshold:   c.fatal_threshold,
            })),
        };

        fetch('/api/checks/run', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                _renderError(data.error);
            } else {
                _renderResults(data.results);
                _renderSummary(data.summary);
            }
        })
        .catch(err => _renderError(err.message))
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Run All Checks';
        });
    };

    // â”€â”€ Catalog & column dropdowns â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    function _populateCatalogDropdown() {
        const sel = document.getElementById('cpCheckType');
        sel.innerHTML = '<option value="">— select check type —</option>';

        const DQ_DIMENSIONS = ['Completeness', 'Accuracy', 'Consistency', 'Uniqueness', 'Freshness', 'Validity'];
        const grouped = {};
        DQ_DIMENSIONS.forEach(d => { grouped[d] = []; });

        Object.entries(catalog).forEach(([key, meta]) => {
            const dim = meta.dimension || 'Validity';
            if (!grouped[dim]) grouped[dim] = [];
            grouped[dim].push({ key, ...meta });
        });

        DQ_DIMENSIONS.forEach(dim => {
            if (!grouped[dim] || !grouped[dim].length) return;
            const og = document.createElement('optgroup');
            og.label = dim;
            grouped[dim].forEach(({ key: ck, label: cl, level }) => {
                const opt = document.createElement('option');
                opt.value       = ck;
                opt.textContent = cl + (level === 'table' ? ' — table' : level === 'column' ? ' — column' : '');
                og.appendChild(opt);
            });
            sel.appendChild(og);
        });

        _onCheckTypeChange();
    }

    function _populateColumnDropdown() {
        const sel = document.getElementById('cpColumn');
        sel.innerHTML = '<option value="">â€” table level (no column) â€”</option>';
        columns.forEach(col => {
            const opt = document.createElement('option');
            opt.value       = col.name;
            opt.textContent = col.name + '  (' + col.type + ')';
            sel.appendChild(opt);
        });
    }

    function _onCheckTypeChange() {
        const checkType = document.getElementById('cpCheckType').value;
        const colRow    = document.getElementById('cpColumnRow');
        const descEl    = document.getElementById('cpDescription');
        const extraEl   = document.getElementById('cpExtraParams');

        if (!checkType || !catalog) {
            colRow.style.display = 'none';
            descEl.textContent   = '';
            extraEl.innerHTML    = '';
            return;
        }

        const entry = catalog[checkType];
        descEl.textContent   = entry.description || '';
        colRow.style.display = (entry.level !== 'table') ? '' : 'none';

        // Pre-select default operator based on check direction
        const defaultOp = (entry.direction === 'min') ? '<' : '>';
        ['cpWarningOp', 'cpErrorOp', 'cpFatalOp'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = defaultOp;
        });

        // Extra params
        extraEl.innerHTML = '';
        (entry.extra_params || []).forEach(p => {
            const div   = document.createElement('div');
            div.className = 'cp-extra-param';

            const label = document.createElement('label');
            label.htmlFor     = 'cpParam_' + p;
            label.textContent = _extraParamLabel(p);

            let input;
            if (p === 'custom_sql') {
                input = document.createElement('textarea');
                input.rows      = 3;
                input.className = 'form-control form-control-sm font-monospace';
                input.style.fontSize = '0.75rem';
                input.placeholder = 'SELECT COUNT(*) FROM â€¦';
            } else {
                input = document.createElement('input');
                input.type      = 'text';
                input.className = 'form-control form-control-sm';
                input.placeholder = _extraParamPlaceholder(p);
            }
            input.id = 'cpParam_' + p;
            div.appendChild(label);
            div.appendChild(input);
            extraEl.appendChild(div);
        });
    }

    function _extraParamLabel(p) {
        return { freshness_column: 'Timestamp column name',
                 accepted_values:  'Accepted values (comma-separated)',
                 pattern:          'Regex pattern',
                 custom_sql:       'Custom SQL (must return one numeric value)' }[p] || p;
    }

    function _extraParamPlaceholder(p) {
        return { freshness_column: 'e.g. updated_at',
                 accepted_values:  'e.g. active, inactive, pending',
                 pattern:          'e.g. ^[A-Z]{2}\\d{4}$' }[p] || '';
    }

    // â”€â”€ Render checks list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    function _renderChecksList() {
        const container = document.getElementById('cpChecksList');
        const countEl   = document.getElementById('cpCheckCount');
        const runBtn    = document.getElementById('cpRunBtn');
        const goRunBtn  = document.getElementById('cpGoRunBtn');

        countEl.textContent = checks.length;
        if (runBtn)   runBtn.disabled   = checks.length === 0;
        if (goRunBtn) goRunBtn.disabled = checks.length === 0;

        if (checks.length === 0) {
            container.innerHTML = '<div class="cp-empty"><i class="bi bi-clipboard me-1"></i>No checks added yet</div>';
            return;
        }

        container.innerHTML = checks.map(chk => {
            const pills = [
                chk.warning_threshold !== null
                    ? `<span class="badge bg-warning text-dark">W: ${chk.warning_op} ${chk.warning_threshold}</span>` : '',
                chk.error_threshold !== null
                    ? `<span class="badge bg-danger">E: ${chk.error_op} ${chk.error_threshold}</span>` : '',
                chk.fatal_threshold !== null
                    ? `<span class="badge" style="background:#7c3aed">F: ${chk.fatal_op} ${chk.fatal_threshold}</span>` : '',
            ].join('');

            return `
            <div class="cp-check-card">
                <div class="d-flex align-items-start justify-content-between gap-2">
                    <div style="min-width:0">
                        <div class="cp-check-label">${_esc(chk._label)}</div>
                        <div class="cp-check-col">
                            ${chk.column_name
                                ? '<i class="bi bi-columns-gap me-1"></i>' + _esc(chk.column_name)
                                : '<i class="bi bi-table me-1"></i>table-level'}
                        </div>
                    </div>
                    <button class="btn-close" style="font-size:0.65rem;flex-shrink:0"
                            onclick="cpRemoveCheck(${chk._id})" title="Remove"></button>
                </div>
                <div class="cp-threshold-pills">
                    ${pills || '<span style="font-size:0.72rem;color:#94a3b8">no thresholds â€” always passes</span>'}
                </div>
            </div>`;
        }).join('');
    }

    // â”€â”€ Results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    function _renderResults(results) {
        const container = document.getElementById('cpResults');
        if (!results || results.length === 0) {
            container.innerHTML = '<div class="cp-empty">No results</div>';
            return;
        }

        container.innerHTML = results.map(r => {
            const sev  = r.severity || 'passed';
            const icon = { passed: 'bi-check-circle-fill', warning: 'bi-exclamation-triangle-fill',
                           error:  'bi-x-circle-fill',     fatal:   'bi-x-octagon-fill' }[sev] || 'bi-circle';

            const val = (r.actual_value !== null && r.actual_value !== undefined)
                ? Number(r.actual_value).toLocaleString(undefined, { maximumFractionDigits: 4 })
                    + (r.unit ? ' ' + r.unit : '')
                : (r.error_message || 'â€”');

            const threshParts = [];
            if (r.warning_threshold !== null && r.warning_threshold !== undefined)
                threshParts.push(`W: ${r.warning_op} ${r.warning_threshold}`);
            if (r.error_threshold !== null && r.error_threshold !== undefined)
                threshParts.push(`E: ${r.error_op} ${r.error_threshold}`);
            if (r.fatal_threshold !== null && r.fatal_threshold !== undefined)
                threshParts.push(`F: ${r.fatal_op} ${r.fatal_threshold}`);

            return `
            <div class="cp-result-card severity-${_esc(sev)}">
                <div class="d-flex align-items-center justify-content-between gap-2">
                    <div class="cp-result-label">
                        <i class="bi ${icon} me-1"></i>${_esc(r.check_label || r.check_type)}
                    </div>
                    <span class="cp-sev-badge cp-sev-${_esc(sev)}">${_esc(sev)}</span>
                </div>
                ${r.column_name
                    ? `<div class="cp-result-col"><i class="bi bi-columns-gap me-1"></i>${_esc(r.column_name)}</div>`
                    : ''}
                <div class="cp-result-value text-muted mt-1">
                    <strong>Value:</strong> ${_esc(String(val))}
                    ${threshParts.length
                        ? `<span class="ms-2 text-secondary" style="font-size:0.72rem">(${threshParts.join(' Â· ')})</span>`
                        : ''}
                </div>
                ${r.error_message
                    ? `<div class="text-danger mt-1" style="font-size:0.72rem">${_esc(r.error_message)}</div>`
                    : ''}
            </div>`;
        }).join('');
    }

    function _renderSummary(summary) {
        const bar = document.getElementById('cpSummaryBar');
        if (!summary || !bar) return;
        const kpi    = summary.kpi_score !== null ? summary.kpi_score + '%' : 'â€”';
        const kpiCls = summary.kpi_score >= 90 ? 'text-bg-success'
                     : summary.kpi_score >= 70 ? 'text-bg-warning'
                     : 'text-bg-danger';
        bar.innerHTML = `
            <div class="cp-summary-inner">
                <span class="cp-kpi-badge ${kpiCls}">${kpi}</span>
                <span class="text-muted" style="font-size:0.8rem">
                    ${summary.total} checks &nbsp;Â·&nbsp;
                    <span class="text-success fw-semibold">${summary.passed} passed</span>
                    ${summary.errors > 0
                        ? '&nbsp;Â·&nbsp;<span class="text-danger fw-semibold">' + summary.errors + ' failed</span>'
                        : ''}
                </span>
            </div>`;
        bar.style.display = 'block';
    }

    function _renderError(msg) {
        document.getElementById('cpResults').innerHTML =
            `<div class="alert alert-danger py-2 small"><i class="bi bi-exclamation-circle me-1"></i>${_esc(msg)}</div>`;
    }

    function _clearResults() {
        const el = document.getElementById('cpResults');
        if (el) el.innerHTML = '';
    }

    function _hideSummary() {
        const bar = document.getElementById('cpSummaryBar');
        if (bar) { bar.style.display = 'none'; bar.innerHTML = ''; }
    }

    // â”€â”€ Utilities â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    function _setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function _esc(str) {
        if (str == null) return '';
        const d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }

    // â”€â”€ Wire check-type change event â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    document.addEventListener('DOMContentLoaded', function () {
        const sel = document.getElementById('cpCheckType');
        if (sel) sel.addEventListener('change', _onCheckTypeChange);
    });

})();

