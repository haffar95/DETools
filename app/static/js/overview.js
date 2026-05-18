// DETools - Overview Page JS
// Handles: connection health cards, schema scanner dropdowns, scan results table.
(function () {
    'use strict';

    let _scanData = null;   // last API scan result
    let _sortCol  = 'row_count';
    let _sortAsc  = false;

    // â”€â”€ Init â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    document.addEventListener('DOMContentLoaded', function () {
        loadConnectionHealth();

        // Event delegation for the "Checks" button in the table body
        const tbody = document.getElementById('ovTableBody');
        if (tbody) {
            tbody.addEventListener('click', function (e) {
                const btn = e.target.closest('.ov-checks-btn');
                if (!btn) return;
                const d = btn.dataset;
                if (typeof window.openChecksPanel === 'function') {
                    window.openChecksPanel(d.conn, d.db, d.schema, d.table);
                }
            });
        }
    });

    // â”€â”€ Connection health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    window.loadConnectionHealth = function () {
        const cardsEl  = document.getElementById('ovConnectionCards');
        const statusEl = document.getElementById('ovConnStatus');
        cardsEl.innerHTML  = '<div class="ov-skeleton"></div><div class="ov-skeleton mt-2"></div>';
        statusEl.textContent = 'Loading-';

        fetch('/api/overview/connections')
            .then(r => r.json())
            .then(data => {
                const conns   = data.connections || [];
                const healthy = conns.filter(c => c.reachable).length;

                _setText('kpiConnTotal',   conns.length);
                _setText('kpiConnHealthy', healthy);
                statusEl.textContent = `${conns.length} configured · ${healthy} reachable`;

                cardsEl.innerHTML = '';
                if (conns.length === 0) {
                    cardsEl.innerHTML =
                        '<div class="ov-empty"><i class="bi bi-plug me-1"></i>' +
                        'No connections yet. <a href="/database-config">Add one &rarr;</a></div>';
                } else {
                    conns.forEach(c => cardsEl.appendChild(_buildConnCard(c)));
                }

                // Populate scanner connection dropdown (reachable only)
                const sel = document.getElementById('ovConnSelect');
                sel.innerHTML = '<option value="">- select connection -</option>';
                conns.filter(c => c.reachable).forEach(c => {
                    const opt = document.createElement('option');
                    opt.value       = c.key;
                    opt.textContent = c.label + ' (' + c.type.toUpperCase() + ')';
                    sel.appendChild(opt);
                });
            })
            .catch(err => {
                cardsEl.innerHTML =
                    '<div class="ov-empty text-danger"><i class="bi bi-exclamation-circle me-1"></i>' +
                    _esc(err.message) + '</div>';
                statusEl.textContent = 'Error';
            });
    };

    function _buildConnCard(conn) {
        const card = document.createElement('div');
        card.className = 'ov-conn-card' + (conn.reachable ? '' : ' ov-conn-card--down');

        const typeColor = conn.type === 'snowflake' ? '#29b5e8' : '#336791';
        const dot = conn.reachable
            ? '<span class="ov-dot ov-dot--up"></span>'
            : '<span class="ov-dot ov-dot--down"></span>';

        const meta = conn.reachable
            ? `<i class="bi bi-layers me-1"></i>${conn.schema_count} schema${conn.schema_count !== 1 ? 's' : ''}`
            : `<span class="text-danger"><i class="bi bi-exclamation-circle me-1"></i>${_esc(conn.error || 'Unreachable')}</span>`;

        card.innerHTML = `
            <div class="d-flex align-items-center justify-content-between gap-2">
                <div class="d-flex align-items-center gap-2 ov-conn-name-wrap">
                    ${dot}
                    <span class="ov-conn-name">${_esc(conn.label)}</span>
                </div>
                <span class="ov-type-badge" style="background:${typeColor}">${conn.type.toUpperCase()}</span>
            </div>
            <div class="ov-conn-meta">${meta}</div>`;
        return card;
    }

    // â”€â”€ Scanner dropdowns â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    window.onScannerConnChange = function () {
        const connKey   = document.getElementById('ovConnSelect').value;
        const dbSel     = document.getElementById('ovDbSelect');
        const schemaSel = document.getElementById('ovSchemaSelect');

        dbSel.innerHTML     = '<option value="">- select database -</option>';
        dbSel.disabled      = true;
        schemaSel.innerHTML = '<option value="">- select schema -</option>';
        schemaSel.disabled  = true;
        document.getElementById('ovRunBtn').disabled = true;

        if (!connKey) return;

        dbSel.innerHTML = '<option value="">Loading-</option>';
        dbSel.disabled  = false;

        fetch('/api/tree/databases?conn=' + encodeURIComponent(connKey))
            .then(r => r.json())
            .then(data => {
                dbSel.innerHTML = '<option value="">- select database -</option>';
                (data.databases || []).forEach(db => {
                    const opt = document.createElement('option');
                    opt.value = opt.textContent = db;
                    dbSel.appendChild(opt);
                });
            })
            .catch(() => {
                dbSel.innerHTML = '<option value="">Error loading databases</option>';
            });
    };

    window.onScannerDbChange = function () {
        const connKey   = document.getElementById('ovConnSelect').value;
        const database  = document.getElementById('ovDbSelect').value;
        const schemaSel = document.getElementById('ovSchemaSelect');

        schemaSel.innerHTML = '<option value="">- select schema -</option>';
        schemaSel.disabled  = true;
        document.getElementById('ovRunBtn').disabled = true;

        if (!database) return;

        schemaSel.innerHTML = '<option value="">Loading-</option>';
        schemaSel.disabled  = false;

        fetch('/api/tree/schemas?conn=' + encodeURIComponent(connKey) + '&db=' + encodeURIComponent(database))
            .then(r => r.json())
            .then(data => {
                schemaSel.innerHTML = '<option value="">- select schema -</option>';
                (data.schemas || []).forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = opt.textContent = s;
                    schemaSel.appendChild(opt);
                });
            })
            .catch(() => {
                schemaSel.innerHTML = '<option value="">Error loading schemas</option>';
            });
    };

    window.onScannerSchemaChange = function () {
        const schema = document.getElementById('ovSchemaSelect').value;
        document.getElementById('ovRunBtn').disabled = !schema;
    };

    // â”€â”€ Scan â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    window.runOverviewScan = function () {
        const connKey  = document.getElementById('ovConnSelect').value;
        const database = document.getElementById('ovDbSelect').value;
        const schema   = document.getElementById('ovSchemaSelect').value;
        if (!connKey || !schema) return;

        const btn = document.getElementById('ovRunBtn');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Scanning-';

        document.getElementById('ovTableSection').style.display  = 'none';
        document.getElementById('ovScanSummary').style.display   = 'none';

        const url = '/api/overview/scan'
            + '?conn='   + encodeURIComponent(connKey)
            + '&db='     + encodeURIComponent(database)
            + '&schema=' + encodeURIComponent(schema);

        fetch(url)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    alert('Scan error: ' + data.error);
                    return;
                }

                _scanData = data;
                _sortCol  = 'row_count';
                _sortAsc  = false;

                // Update KPI tiles
                _setText('kpiTables', data.total_tables.toLocaleString());
                _setText('kpiRows',   data.total_rows.toLocaleString());

                // DQ dimension circles
                const dq = data.dq_scores || {};
                ['Completeness','Accuracy','Consistency','Uniqueness','Freshness','Validity'].forEach(function(dim) {
                    _setDqCircle(dim, dq[dim] !== undefined ? dq[dim] : null);
                });

                // Summary strip
                _setText('ovStatTables', data.total_tables.toLocaleString());
                _setText('ovStatRows',   data.total_rows.toLocaleString());
                _setText('ovStatErrors', data.scan_errors);
                document.getElementById('ovScanSummary').style.display = '';

                // Table section
                document.getElementById('ovTableMeta').textContent =
                    schema + ' · ' + (database || connKey) + ' · ' + data.total_tables + ' tables';
                _renderTableResults();
                document.getElementById('ovTableSection').style.display = '';
            })
            .catch(err => alert('Scan failed: ' + err.message))
            .finally(() => {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Run Scan';
            });
    };

    // â”€â”€ Table results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    window.sortTableResults = function (col) {
        _sortAsc = (_sortCol === col) ? !_sortAsc : (col === 'name');
        _sortCol = col;
        _renderTableResults();

        // Update sort icons
        document.querySelectorAll('.ov-sort-icon').forEach(el => {
            el.className = 'bi bi-chevron-expand ms-1 ov-sort-icon';
        });
        const icon = document.querySelector(`.ov-th-sort[data-col="${col}"] .ov-sort-icon`);
        if (icon) icon.className = `bi bi-chevron-${_sortAsc ? 'up' : 'down'} ms-1 ov-sort-icon`;
    };

    function _renderTableResults() {
        if (!_scanData) return;

        const connKey  = document.getElementById('ovConnSelect').value;
        const database = document.getElementById('ovDbSelect').value;
        const schema   = document.getElementById('ovSchemaSelect').value;

        const rows   = [..._scanData.tables];
        const maxRow = Math.max(...rows.map(r => r.row_count || 0), 1);

        rows.sort((a, b) => {
            let va = a[_sortCol], vb = b[_sortCol];
            if (va == null) va = _sortAsc ? Infinity : -Infinity;
            if (vb == null) vb = _sortAsc ? Infinity : -Infinity;
            if (typeof va === 'string') return _sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
            return _sortAsc ? va - vb : vb - va;
        });

        document.getElementById('ovTableBody').innerHTML = rows.map(row => {
            const hasErr = !!row.error;
            const pct    = (_scanData.total_rows > 0 && row.row_count != null)
                ? (row.row_count / _scanData.total_rows * 100).toFixed(1)
                : null;
            const barW   = row.row_count != null
                ? (row.row_count / maxRow * 100).toFixed(1)
                : 0;

            const barCell = hasErr
                ? `<span class="text-danger small">${_esc(row.error)}</span>`
                : `<div class="ov-bar-wrap">
                       <div class="ov-bar" style="width:${barW}%"></div>
                       <span class="ov-bar-label">${pct}%</span>
                   </div>`;

            const checksBtn = !hasErr
                ? `<button class="btn btn-xs ov-checks-btn"
                           data-conn="${_esc(connKey)}"
                           data-db="${_esc(database)}"
                           data-schema="${_esc(schema)}"
                           data-table="${_esc(row.name)}"
                           title="Open Checks Panel">
                       <i class="bi bi-shield-check me-1"></i>Checks
                   </button>`
                : '';

            const dq = row.dq || {};
            function _dqCell(val) {
                if (val == null) return '<td class="text-center text-muted" style="font-size:0.75rem">—</td>';
                const v = parseFloat(val);
                const color = v >= 90 ? '#16a34a' : v >= 70 ? '#d97706' : '#dc2626';
                return `<td class="text-center" style="font-size:0.75rem;font-weight:600;color:${color}">${v.toFixed(0)}%</td>`;
            }

            return `<tr class="${hasErr ? 'table-danger' : ''}">
                <td class="fw-medium">${_esc(row.name)}</td>
                <td class="text-end text-muted">${row.col_count != null ? row.col_count : '-'}</td>
                <td class="text-end">${row.row_count != null ? Number(row.row_count).toLocaleString() : '-'}</td>
                <td>${barCell}</td>
                ${_dqCell(dq.Completeness)}
                ${_dqCell(dq.Uniqueness)}
                ${_dqCell(dq.Freshness)}
                ${_dqCell(dq.Validity)}
                ${_dqCell(dq.Accuracy)}
                ${_dqCell(dq.Consistency)}
                <td>${hasErr
                    ? '<span class="badge bg-danger">Error</span>'
                    : '<span class="badge bg-success">OK</span>'}</td>
                <td class="text-end">${checksBtn}</td>
            </tr>`;
        }).join('');
    }

    // â”€â”€ Utilities â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    function _setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    // C = 2 * pi * 28 (radius of the DQ circles)
    var _DQ_C = 175.9;

    function _setDqCircle(dim, score) {
        var pctEl  = document.getElementById('dqPct'  + dim);
        var arcEl  = document.getElementById('dqArc'  + dim);
        var hintEl = document.getElementById('dqHint' + dim);
        if (!pctEl || !arcEl) return;
        if (score === null || score === undefined) {
            pctEl.textContent = 'N/A';
            arcEl.style.strokeDashoffset = _DQ_C;
            if (hintEl) hintEl.textContent = 'Configure checks';
            return;
        }
        pctEl.textContent = score.toFixed(0) + '%';
        arcEl.style.strokeDashoffset = (_DQ_C * (1 - score / 100)).toFixed(2);
        if (hintEl) hintEl.textContent = score >= 90 ? 'Good' : score >= 70 ? 'Fair' : 'Needs attention';
    }

    function _esc(str) {
        if (str == null) return '';
        const d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }

})();
