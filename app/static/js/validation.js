/* ── Validation Page JS ─────────────────────────────────────────────────── */
(function () {
    'use strict';

    // ── State ─────────────────────────────────────────────────────────────
    var _connKey = '';   // active session connection key
    var _std = { db: '', schema: '', table: '' };

    // ── Init ──────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        _loadFromSessionConn();
        if (location.hash === '#query-mode') switchValMode('query');
    });

    // Load databases for the currently active session connection.
    function _loadFromSessionConn() {
        fetch('/api/current-database')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _connKey = data.selected_db && data.selected_db.name ? data.selected_db.name : '';
                if (!_connKey) {
                    var noConn = '<option value="">— no active connection —</option>';
                    document.getElementById('valDbSelect').innerHTML  = noConn;
                    document.getElementById('qryDbSelect').innerHTML  = noConn;
                    return;
                }
                // Load databases for Standard mode
                _fillDatabases('valDbSelect', _connKey);
                // Load databases for Query mode
                _fillDatabases('qryDbSelect', _connKey);
            })
            .catch(function () {
                document.getElementById('valDbSelect').innerHTML = '<option value="">— error —</option>';
                document.getElementById('qryDbSelect').innerHTML = '<option value="">— error —</option>';
            });
    }

    function _fillDatabases(selectId, connKey) {
        var el = document.getElementById(selectId);
        if (!el) return;
        el.innerHTML = '<option value="">Loading…</option>';
        fetch('/api/tree/databases?conn=' + encodeURIComponent(connKey))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _fillSelect(selectId, data.databases || [], null, '— select database —');
            })
            .catch(function () {
                el.innerHTML = '<option value="">— error loading —</option>';
            });
    }

    // ── Mode switching ────────────────────────────────────────────────────
    window.switchValMode = function (mode) {
        document.getElementById('modeStandard').style.display = mode === 'standard' ? '' : 'none';
        document.getElementById('modeQuery').style.display    = mode === 'query'    ? '' : 'none';
        document.getElementById('tabStandard').classList.toggle('active', mode === 'standard');
        document.getElementById('tabQuery').classList.toggle('active',    mode === 'query');
    };

    // ── Standard mode: database change ────────────────────────────────────
    window.onValDbChange = function () {
        _std.db = document.getElementById('valDbSelect').value;
        _std.schema = _std.table = '';
        _reset('valSchemaSelect', '— select schema —', false);
        _reset('valTableSelect',  '— select table —',  true);
        document.getElementById('valOptions').style.display = 'none';
        if (!_std.db) return;

        document.getElementById('valSchemaSelect').innerHTML = '<option value="">Loading…</option>';
        fetch('/api/tree/schemas?conn=' + encodeURIComponent(_connKey) + '&db=' + encodeURIComponent(_std.db))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _fillSelect('valSchemaSelect', data.schemas || [], null, '— select schema —');
            })
            .catch(function () {
                _reset('valSchemaSelect', '— error loading —', false);
            });
    };

    // ── Standard mode: schema change ──────────────────────────────────────
    window.onValSchemaChange = function () {
        _std.schema = document.getElementById('valSchemaSelect').value;
        _std.table = '';
        _reset('valTableSelect', '— select table —', false);
        document.getElementById('valOptions').style.display = 'none';
        if (!_std.schema) return;

        document.getElementById('valTableSelect').innerHTML = '<option value="">Loading…</option>';
        fetch('/api/tree/tables?conn=' + encodeURIComponent(_connKey) +
              '&db=' + encodeURIComponent(_std.db) +
              '&schema=' + encodeURIComponent(_std.schema))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _fillSelect('valTableSelect', data.tables || [], null, '— select table —');
            })
            .catch(function () {
                _reset('valTableSelect', '— error loading —', false);
            });
    };

    // ── Standard mode: table change ───────────────────────────────────────
    window.onValTableChange = function () {
        _std.table = document.getElementById('valTableSelect').value;
        document.getElementById('valOptions').style.display = 'none';
        document.getElementById('valResults').innerHTML = '';
        if (!_std.table) return;

        var metaEl = document.getElementById('valSourceMeta');
        metaEl.textContent = 'Loading columns…';

        fetch('/api/tree/columns?conn=' + encodeURIComponent(_connKey) +
              '&db='     + encodeURIComponent(_std.db) +
              '&schema=' + encodeURIComponent(_std.schema) +
              '&table='  + encodeURIComponent(_std.table))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var cols = data.columns || [];
                metaEl.textContent = cols.length + ' column' + (cols.length !== 1 ? 's' : '');

                var allOpts = '<option value="">— none —</option>' +
                    cols.map(function (c) {
                        return '<option value="' + _esc(c.name) + '" data-type="' + _esc(c.type || '') + '">' +
                            _esc(c.name) + ' (' + _esc(c.type || '') + ')</option>';
                    }).join('');

                var dateTypes = ['timestamp', 'date', 'time'];
                var dateOpts = '<option value="">— none —</option>' +
                    cols.filter(function (c) {
                        return c.type && dateTypes.some(function (k) { return c.type.toLowerCase().includes(k); });
                    }).map(function (c) {
                        return '<option value="' + _esc(c.name) + '">' + _esc(c.name) + '</option>';
                    }).join('');

                document.getElementById('valKeySelect').innerHTML     = allOpts;
                document.getElementById('valFkSelect').innerHTML      = allOpts;
                document.getElementById('valDateColSelect').innerHTML = dateOpts;
                document.getElementById('valOptions').style.display = '';
            })
            .catch(function () {
                metaEl.textContent = '';
                document.getElementById('valOptions').style.display = '';
            });
    };

    window.onValDateColChange = function () {
        var val = document.getElementById('valDateColSelect').value;
        document.getElementById('valDateRange').style.display = val ? '' : 'none';
    };

    // ── Standard validation run ───────────────────────────────────────────
    window.runStandardValidation = function () {
        if (!_std.schema || !_std.table) return;

        var btn = document.getElementById('valRunBtn');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Validating…';

        var resultsDiv = document.getElementById('valResults');
        resultsDiv.innerHTML = '';

        var keyCol   = document.getElementById('valKeySelect').value;
        var fkCol    = document.getElementById('valFkSelect').value;
        var dateCol  = document.getElementById('valDateColSelect').value;
        var startDate = document.getElementById('valStartDate').value;
        var endDate   = document.getElementById('valEndDate').value;

        var url = '/api/validate?table='  + encodeURIComponent(_std.table) +
                  '&schema='  + encodeURIComponent(_std.schema) +
                  '&db='      + encodeURIComponent(_std.db);
        if (keyCol)                           url += '&key_column=' + encodeURIComponent(keyCol);
        if (fkCol)                            url += '&foreign_key=' + encodeURIComponent(fkCol);
        if (dateCol && startDate && endDate)  url += '&date_column=' + encodeURIComponent(dateCol) +
                                                     '&start_date=' + encodeURIComponent(startDate) +
                                                     '&end_date='   + encodeURIComponent(endDate);

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                resultsDiv.innerHTML = data.error ? _errorCard(data.error) : displayResults(data);
            })
            .catch(function (err) { resultsDiv.innerHTML = _errorCard(err.message); })
            .finally(function () {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-play-fill"></i>Run Validation';
            });
    };

    // ── Query mode ────────────────────────────────────────────────────────
    window.runQueryValidation = function (btn) {
        var query    = document.getElementById('sqlQuery').value.trim();
        var database = document.getElementById('qryDbSelect').value || null;
        if (!query) { alert('Please enter a SQL query'); return; }

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Validating…';

        var resultsDiv = document.getElementById('qryResults');
        resultsDiv.innerHTML = '';

        fetch('/api/validate-query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query, database: database }),
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            resultsDiv.innerHTML = data.error ? _errorCard(data.error) : displayResults(data);
        })
        .catch(function (err) { resultsDiv.innerHTML = _errorCard(err.message); })
        .finally(function () {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-play-fill"></i>Validate Query';
        });
    };

    // ── DOM helpers ───────────────────────────────────────────────────────
    function _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _reset(id, placeholder, disabled) {
        var el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = '<option value="">' + placeholder + '</option>';
        el.disabled  = disabled;
    }

    function _fillSelect(id, items, valueKey, placeholder) {
        var el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = '<option value="">' + (placeholder || '— select —') + '</option>' +
            items.map(function (item) {
                var v = valueKey ? item[valueKey] : item;
                return '<option value="' + _esc(v) + '">' + _esc(v) + '</option>';
            }).join('');
    }

    function _errorCard(msg) {
        return '<div class="ov-card mt-3 p-3" style="border-color:#fca5a5">' +
               '<span class="text-danger"><i class="bi bi-exclamation-circle me-2"></i>' +
               _esc(String(msg)) + '</span></div>';
    }

    function _resultSection(title, icon, content) {
        return '<div class="ov-card mt-3">' +
               '<div class="ov-card-header"><span class="fw-semibold">' +
               '<i class="bi bi-' + icon + ' me-2 text-primary"></i>' + title +
               '</span></div>' +
               '<div class="p-3">' + content + '</div>' +
               '</div>';
    }

    function _pill(val, cls) {
        return '<span class="badge ' + (cls || 'bg-secondary') + '">' + _esc(String(val)) + '</span>';
    }

    // ── displayResults ────────────────────────────────────────────────────
    function displayResults(results) {
        var html = '';

        // Overview
        html += _resultSection('Overview', 'info-circle', [
            '<table class="table table-sm mb-0">',
            '<tr><th style="width:220px">Total Rows Analysed</th>',
            '<td>' + _pill(results.row_count, 'bg-primary') + '</td></tr>',
            '</table>',
        ].join(''));

        // Duplicates
        var dupBody = '';
        if (results.duplicates && results.duplicates.details && Object.keys(results.duplicates.details).length > 0) {
            dupBody = '<table class="table table-sm mb-0"><thead class="table-light"><tr>' +
                '<th>Type</th><th>Count</th><th>Details</th></tr></thead><tbody>' +
                Object.entries(results.duplicates.details).map(function (entry) {
                    var type = entry[0], data = entry[1];
                    var label = type.replace(/_/g, ' ').replace(/\b\w/g, function (l) { return l.toUpperCase(); });
                    var detail = '';
                    if (data.records && data.records.length) {
                        var headers = Object.keys(data.records[0]).map(function (k) { return '<th>' + _esc(k) + '</th>'; }).join('');
                        var rows = data.records.map(function (r) {
                            return '<tr>' + Object.values(r).map(function (v) {
                                return '<td>' + (v !== null ? _esc(String(v)) : '<em class="text-muted">NULL</em>') + '</td>';
                            }).join('') + '</tr>';
                        }).join('');
                        detail = '<details><summary class="text-primary small">View records</summary>' +
                            '<div class="table-responsive mt-2"><table class="table table-sm table-bordered mb-0">' +
                            '<thead class="table-dark"><tr>' + headers + '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
                            (data.total_records > 100 ? '<p class="text-muted small mt-1">Showing 100 of ' + data.total_records + ' records</p>' : '') +
                            '</details>';
                    }
                    return '<tr><td>' + _esc(label) + '</td><td>' +
                        _pill(data.total_records || data.count, 'bg-warning text-dark') +
                        '</td><td>' + (detail || '—') + '</td></tr>';
                }).join('') + '</tbody></table>';
        } else {
            dupBody = '<p class="text-success mb-0"><i class="bi bi-check-circle me-1"></i>No duplicates found</p>';
        }
        html += _resultSection('Duplicates', 'copy', dupBody);

        // Date issues
        var dateBody = '';
        if (results.date_issues && Object.keys(results.date_issues).length > 0) {
            dateBody = '<table class="table table-sm mb-0"><thead class="table-light"><tr>' +
                '<th>Column</th><th>Issue</th><th>Count</th><th>Examples</th></tr></thead><tbody>' +
                Object.entries(results.date_issues).map(function (entry) {
                    var key = entry[0], data = entry[1];
                    var parts    = key.split('_');
                    var column   = parts[0];
                    var issueMap = { invalid: 'Invalid Format', future: 'Future Date', old: 'Too Old' };
                    var issue    = issueMap[parts[1]] || parts[1];
                    var examples = '';
                    if (data.values && data.values.length) {
                        examples = '<details><summary class="text-primary small">View examples</summary>' +
                            '<ul class="mb-0 mt-1 small">' +
                            data.values.map(function (v) { return '<li>' + _esc(String(v)) + '</li>'; }).join('') +
                            '</ul></details>';
                    }
                    return '<tr><td>' + _esc(column) + '</td><td>' + _esc(issue) + '</td><td>' +
                        _pill(data.count, 'bg-warning text-dark') + '</td><td>' + (examples || '—') + '</td></tr>';
                }).join('') + '</tbody></table>';
        } else {
            dateBody = '<p class="text-success mb-0"><i class="bi bi-check-circle me-1"></i>No date issues found</p>';
        }
        html += _resultSection('Date Issues', 'calendar-x', dateBody);

        // Anomalies / outliers
        var anomalyBody = '';
        if (results.anomalies && Object.keys(results.anomalies).length > 0) {
            anomalyBody = '<table class="table table-sm mb-0"><thead class="table-light"><tr>' +
                '<th>Column</th><th>Count</th><th>Statistics</th><th>Outliers</th></tr></thead><tbody>' +
                Object.entries(results.anomalies).map(function (entry) {
                    var col = entry[0], data = entry[1];
                    var stats = data.stats
                        ? 'Median: ' + Number(data.stats.median).toLocaleString() +
                          '<br>Mean: ' + Number(data.stats.mean).toLocaleString() +
                          (data.bounds ? '<br>Range: ' + Number(data.bounds.lower).toLocaleString() +
                                         ' – ' + Number(data.bounds.upper).toLocaleString() : '')
                        : '—';
                    var outliers = '';
                    if (data.values && data.values.length) {
                        outliers = '<details><summary class="text-primary small">View outliers</summary>' +
                            '<ul class="mb-0 mt-1 small">' +
                            data.values.map(function (v) { return '<li>' + _esc(String(v).toLocaleString ? Number(v).toLocaleString() : v) + '</li>'; }).join('') +
                            '</ul></details>';
                    }
                    return '<tr><td>' + _esc(col) + '</td><td>' +
                        _pill(data.count, 'bg-danger') + '</td><td><small>' + stats + '</small></td><td>' +
                        (outliers || '—') + '</td></tr>';
                }).join('') + '</tbody></table>';
        } else {
            anomalyBody = '<p class="text-success mb-0"><i class="bi bi-check-circle me-1"></i>No anomalies found</p>';
        }
        html += _resultSection('Anomalies', 'graph-up-arrow', anomalyBody);

        // Null values
        var nullDetails = results.null_values && results.null_values.details
            ? Object.entries(results.null_values.details).filter(function (e) { return e[1].count > 0; })
            : [];
        var nullBody = '';
        if (nullDetails.length > 0) {
            nullBody = '<table class="table table-sm mb-0"><thead class="table-light"><tr>' +
                '<th>Column</th><th>Null Count</th><th>Details</th></tr></thead><tbody>' +
                nullDetails.map(function (entry) {
                    var col = entry[0], data = entry[1];
                    var detail = '';
                    if (data.rows && data.rows.length) {
                        var ks = Object.keys(data.rows[0]);
                        detail = '<details><summary class="text-primary small">View rows</summary>' +
                            '<div class="table-responsive mt-2"><table class="table table-sm table-bordered mb-0">' +
                            '<thead class="table-dark"><tr>' + ks.map(function (k) { return '<th>' + _esc(k) + '</th>'; }).join('') + '</tr></thead><tbody>' +
                            data.rows.map(function (r) {
                                return '<tr>' + Object.values(r).map(function (v) {
                                    return '<td>' + (v !== null ? _esc(String(v)) : '<em class="text-muted">NULL</em>') + '</td>';
                                }).join('') + '</tr>';
                            }).join('') + '</tbody></table></div>' +
                            (data.total_rows > 100 ? '<p class="text-muted small mt-1">Showing 100 of ' + data.total_rows + ' records</p>' : '') +
                            '</details>';
                    }
                    return '<tr><td>' + _esc(col) + '</td><td>' +
                        _pill(data.total_rows || data.count, 'bg-warning text-dark') +
                        '</td><td>' + (detail || '—') + '</td></tr>';
                }).join('') + '</tbody></table>';
        } else {
            nullBody = '<p class="text-success mb-0"><i class="bi bi-check-circle me-1"></i>No null values found</p>';
        }
        html += _resultSection('Null Values', 'dash-circle', nullBody);

        // Timeliness
        var tlBody = '';
        var tl = results.timeliness;
        if (tl && (tl.freshness || tl.frequency)) {
            var summary = tl.summary
                ? '<div class="mb-3 p-2 bg-light rounded small">' +
                  'Total issues: <strong>' + tl.summary.total_issues + '</strong> &nbsp;|&nbsp; ' +
                  'Stale records: <strong>' + tl.summary.stale_records + '</strong> &nbsp;|&nbsp; ' +
                  'Frequency issues: <strong>' + tl.summary.frequency_issues + '</strong></div>'
                : '';
            tlBody = summary;
            if (tl.freshness) {
                tlBody += Object.entries(tl.freshness).map(function (entry) {
                    var col = entry[0], data = entry[1];
                    return '<div class="mb-2 p-2 border rounded"><strong>' + _esc(col) + ' freshness</strong> — ' +
                        data.count + ' record(s) older than ' + data.max_age_days + ' days ' +
                        '(range: ' + _esc(data.oldest_record || '') + ' → ' + _esc(data.newest_record || '') + ')</div>';
                }).join('');
            }
            if (tl.frequency) {
                tlBody += Object.entries(tl.frequency).map(function (entry) {
                    var col = entry[0], data = entry[1];
                    return '<div class="mb-2 p-2 border rounded"><strong>' + _esc(col) + ' frequency</strong> — ' +
                        data.count + ' day(s) below expected daily records (' + data.expected_daily + ')</div>';
                }).join('');
            }
        } else {
            tlBody = '<p class="text-success mb-0"><i class="bi bi-check-circle me-1"></i>No timeliness issues found</p>';
        }
        html += _resultSection('Data Timeliness', 'clock-history', tlBody);

        return html;
    }

})();
