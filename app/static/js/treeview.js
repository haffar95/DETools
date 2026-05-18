// Database Tree View � DataGrip-style: Connection ? Database ? Schema ? Table ? Column
(function () {
    'use strict';

    // -- Init -----------------------------------------------------------------

    function init() { loadConnections(); }

    window.refreshDbTree = function () {
        const c = document.getElementById('dbTreeContent');
        if (c) c.innerHTML = '';
        loadConnections();
    };

    // -- Level 0 � Connections -------------------------------------------------

    function loadConnections() {
        const container = document.getElementById('dbTreeContent');
        if (!container) return;
        container.innerHTML = '<div class="tree-loading"><i class="bi bi-hourglass-split me-1"></i>Loading...</div>';

        fetch('/api/tree/connections')
            .then(r => r.json())
            .then(data => {
                if (!data.connections || data.connections.length === 0) {
                    container.innerHTML =
                        '<div class="tree-no-connection"><i class="bi bi-database-slash me-1"></i>No connections configured</div>';
                    return;
                }
                renderConnections(container, data.connections);
            })
            .catch(() => {
                container.innerHTML = '<div class="tree-error"><i class="bi bi-exclamation-circle me-1"></i>Failed to load</div>';
            });
    }

    function renderConnections(container, connections) {
        const ul = document.createElement('ul');
        ul.className = 'db-tree';

        connections.forEach(conn => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            const typeIcon  = conn.type === 'snowflake' ? 'bi-snow' : 'bi-server';
            const activeCls = conn.active ? ' conn-active' : '';
            const activeBadge = conn.active ? '<span class="active-conn-badge">active</span>' : '';

            li.innerHTML = `
                <div class="tree-node-content conn-node${activeCls}"
                     data-conn-key="${escapeAttr(conn.key)}"
                     data-conn-type="${escapeAttr(conn.type)}"
                     onclick="treeToggleConnection(this)">
                    <span class="tree-toggle"><i class="bi bi-chevron-right"></i></span>
                    <span class="tree-icon conn-icon"><i class="bi ${typeIcon}"></i></span>
                    <span class="tree-label">${escapeHtml(conn.label)}</span>
                    ${activeBadge}
                    <button class="set-active-btn" title="Set as active connection"
                            onclick="treeSetActive(event,'${escapeAttr(conn.key)}')">
                        <i class="bi bi-lightning-charge-fill"></i>
                    </button>
                </div>
                <div class="tree-children" id="${escapeAttr(nodeKey(conn.key))}"></div>`;
            ul.appendChild(li);
        });

        container.innerHTML = '';
        container.appendChild(ul);
    }

    window.treeToggleConnection = function (el) {
        const key = el.dataset.connKey;
        const childrenDiv = document.getElementById(nodeKey(key));
        const toggle = el.querySelector('.tree-toggle');

        if (childrenDiv.classList.contains('expanded')) {
            childrenDiv.classList.remove('expanded');
            toggle.classList.remove('expanded');
        } else {
            childrenDiv.classList.add('expanded');
            toggle.classList.add('expanded');
            if (!childrenDiv.dataset.loaded) loadDatabases(key, childrenDiv);
        }
    };

    window.treeSetActive = function (event, connKey) {
        event.stopPropagation();
        if (typeof selectDatabase === 'function') selectDatabase(connKey);
    };

    // -- Level 1 � Databases ---------------------------------------------------

    function loadDatabases(connKey, container) {
        container.innerHTML = '<div class="tree-loading">Loading databases...</div>';

        fetch('/api/tree/databases?conn=' + encodeURIComponent(connKey))
            .then(r => r.json())
            .then(data => {
                container.dataset.loaded = 'true';
                if (data.error && (!data.databases || data.databases.length === 0)) {
                    container.innerHTML = '<div class="tree-error">' + escapeHtml(data.error) + '</div>';
                    return;
                }
                if (!data.databases || data.databases.length === 0) {
                    container.innerHTML = '<div class="tree-empty">No databases found</div>';
                    return;
                }
                renderDatabases(container, connKey, data.databases);
            })
            .catch(() => {
                container.innerHTML = '<div class="tree-error">Failed to load databases</div>';
            });
    }

    function renderDatabases(container, connKey, databases) {
        const ul = document.createElement('ul');

        databases.forEach(dbName => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            const id = nodeKey(connKey, dbName);

            li.innerHTML = `
                <div class="tree-node-content db-node"
                     data-conn-key="${escapeAttr(connKey)}"
                     data-database="${escapeAttr(dbName)}"
                     onclick="treeToggleDatabase(this)">
                    <span class="tree-toggle"><i class="bi bi-chevron-right"></i></span>
                    <span class="tree-icon db-icon"><i class="bi bi-database"></i></span>
                    <span class="tree-label">${escapeHtml(dbName)}</span>
                </div>
                <div class="tree-children" id="${escapeAttr(id)}"></div>`;
            ul.appendChild(li);
        });

        container.innerHTML = '';
        container.appendChild(ul);
    }

    window.treeToggleDatabase = function (el) {
        const connKey  = el.dataset.connKey;
        const database = el.dataset.database;
        const id = nodeKey(connKey, database);
        const childrenDiv = document.getElementById(id);
        const toggle = el.querySelector('.tree-toggle');

        if (childrenDiv.classList.contains('expanded')) {
            childrenDiv.classList.remove('expanded');
            toggle.classList.remove('expanded');
        } else {
            childrenDiv.classList.add('expanded');
            toggle.classList.add('expanded');
            if (!childrenDiv.dataset.loaded) loadSchemas(connKey, database, childrenDiv);
        }
    };

    // -- Level 2 � Schemas -----------------------------------------------------

    function loadSchemas(connKey, database, container) {
        container.innerHTML = '<div class="tree-loading">Loading schemas...</div>';

        fetch('/api/tree/schemas?conn=' + encodeURIComponent(connKey) +
              '&db=' + encodeURIComponent(database))
            .then(r => r.json())
            .then(data => {
                container.dataset.loaded = 'true';
                if (data.error && (!data.schemas || data.schemas.length === 0)) {
                    container.innerHTML = '<div class="tree-error">' + escapeHtml(data.error) + '</div>';
                    return;
                }
                if (!data.schemas || data.schemas.length === 0) {
                    container.innerHTML = '<div class="tree-empty">No schemas found</div>';
                    return;
                }
                renderSchemas(container, connKey, database, data.schemas);
            })
            .catch(() => {
                container.innerHTML = '<div class="tree-error">Failed to load schemas</div>';
            });
    }

    function renderSchemas(container, connKey, database, schemas) {
        const ul = document.createElement('ul');

        schemas.forEach(schema => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            const id = nodeKey(connKey, database, schema);

            li.innerHTML = `
                <div class="tree-node-content"
                     data-conn-key="${escapeAttr(connKey)}"
                     data-database="${escapeAttr(database)}"
                     data-schema="${escapeAttr(schema)}"
                     onclick="treeToggleSchema(this)">
                    <span class="tree-toggle"><i class="bi bi-chevron-right"></i></span>
                    <span class="tree-icon schema-icon"><i class="bi bi-folder-fill"></i></span>
                    <span class="tree-label">${escapeHtml(schema)}</span>
                </div>
                <div class="tree-children" id="${escapeAttr(id)}"></div>`;
            ul.appendChild(li);
        });

        container.innerHTML = '';
        container.appendChild(ul);
    }

    window.treeToggleSchema = function (el) {
        const connKey  = el.dataset.connKey;
        const database = el.dataset.database;
        const schema   = el.dataset.schema;
        const id = nodeKey(connKey, database, schema);
        const childrenDiv = document.getElementById(id);
        const toggle = el.querySelector('.tree-toggle');

        if (childrenDiv.classList.contains('expanded')) {
            childrenDiv.classList.remove('expanded');
            toggle.classList.remove('expanded');
        } else {
            childrenDiv.classList.add('expanded');
            toggle.classList.add('expanded');
            if (!childrenDiv.dataset.loaded) renderCategoryFolders(childrenDiv, connKey, database, schema);
        }
    };

    // -- Level 3 – Category folders (Tables / Routines / Sequences) -----------

    function renderCategoryFolders(container, connKey, database, schema) {
        container.dataset.loaded = 'true';
        const ul = document.createElement('ul');

        const categories = [
            { key: 'tables',    label: 'Tables',    icon: 'bi-table',             iconCls: 'cat-tables-icon' },
            { key: 'routines',  label: 'Routines',  icon: 'bi-braces-asterisk',   iconCls: 'cat-routines-icon' },
            { key: 'sequences', label: 'Sequences', icon: 'bi-sort-numeric-up-alt', iconCls: 'cat-sequences-icon' },
        ];

        categories.forEach(cat => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            const id = nodeKey(connKey, database, schema, '__cat_' + cat.key);

            li.innerHTML = `
                <div class="tree-node-content cat-folder-node"
                     data-conn-key="${escapeAttr(connKey)}"
                     data-database="${escapeAttr(database)}"
                     data-schema="${escapeAttr(schema)}"
                     data-category="${cat.key}"
                     onclick="treeToggleCategoryFolder(this)">
                    <span class="tree-toggle"><i class="bi bi-chevron-right"></i></span>
                    <span class="tree-icon ${cat.iconCls}"><i class="bi ${cat.icon}"></i></span>
                    <span class="tree-label">${cat.label}</span>
                </div>
                <div class="tree-children" id="${escapeAttr(id)}"></div>`;
            ul.appendChild(li);
        });

        container.innerHTML = '';
        container.appendChild(ul);
    }

    window.treeToggleCategoryFolder = function (el) {
        const connKey  = el.dataset.connKey;
        const database = el.dataset.database;
        const schema   = el.dataset.schema;
        const category = el.dataset.category;
        const id = nodeKey(connKey, database, schema, '__cat_' + category);
        const childrenDiv = document.getElementById(id);
        const toggle = el.querySelector('.tree-toggle');

        if (childrenDiv.classList.contains('expanded')) {
            childrenDiv.classList.remove('expanded');
            toggle.classList.remove('expanded');
        } else {
            childrenDiv.classList.add('expanded');
            toggle.classList.add('expanded');
            if (!childrenDiv.dataset.loaded) {
                if      (category === 'tables')    loadTables(connKey, database, schema, childrenDiv);
                else if (category === 'routines')  loadRoutines(connKey, database, schema, childrenDiv);
                else if (category === 'sequences') loadSequences(connKey, database, schema, childrenDiv);
            }
        }
    };

    // -- Level 4a – Tables -----------------------------------------------------

    function loadTables(connKey, database, schema, container) {
        container.innerHTML = '<div class="tree-loading">Loading tables...</div>';

        fetch('/api/tree/tables?conn=' + encodeURIComponent(connKey) +
              '&db='     + encodeURIComponent(database) +
              '&schema=' + encodeURIComponent(schema))
            .then(r => r.json())
            .then(data => {
                container.dataset.loaded = 'true';
                if (!data.tables || data.tables.length === 0) {
                    container.innerHTML = '<div class="tree-empty">No tables</div>';
                    return;
                }
                renderTables(container, connKey, database, schema, data.tables);
            })
            .catch(() => {
                container.innerHTML = '<div class="tree-error">Failed to load tables</div>';
            });
    }

    function renderTables(container, connKey, database, schema, tables) {
        const ul = document.createElement('ul');

        tables.forEach(table => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            const id = nodeKey(connKey, database, schema, table);

            // Build the row div
            const rowDiv = document.createElement('div');
            rowDiv.className = 'tree-node-content';
            rowDiv.dataset.connKey  = connKey;
            rowDiv.dataset.database = database;
            rowDiv.dataset.schema   = schema;
            rowDiv.dataset.table    = table;
            rowDiv.innerHTML = `
                <span class="tree-toggle"><i class="bi bi-chevron-right"></i></span>
                <span class="tree-icon table-icon"><i class="bi bi-table"></i></span>
                <span class="tree-label">${escapeHtml(table)}</span>`;
            rowDiv.addEventListener('click', function () { treeToggleTable(this); });

            // Shield button — created via DOM API to avoid attribute-escaping issues
            const shieldBtn = document.createElement('button');
            shieldBtn.className = 'tree-checks-btn';
            shieldBtn.title     = 'Open Checks panel';
            shieldBtn.innerHTML = '<i class="bi bi-shield-check"></i>';
            shieldBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                openChecksPanel(connKey, database, schema, table);
            });
            rowDiv.appendChild(shieldBtn);

            // Children container
            const childrenDiv = document.createElement('div');
            childrenDiv.className = 'tree-children';
            childrenDiv.id = id;

            li.appendChild(rowDiv);
            li.appendChild(childrenDiv);
            ul.appendChild(li);
        });

        container.innerHTML = '';
        container.appendChild(ul);
    }

    window.treeToggleTable = function (el) {
        const connKey  = el.dataset.connKey;
        const database = el.dataset.database;
        const schema   = el.dataset.schema;
        const table    = el.dataset.table;
        const id = nodeKey(connKey, database, schema, table);
        const childrenDiv = document.getElementById(id);
        const toggle = el.querySelector('.tree-toggle');

        if (childrenDiv.classList.contains('expanded')) {
            childrenDiv.classList.remove('expanded');
            toggle.classList.remove('expanded');
        } else {
            childrenDiv.classList.add('expanded');
            toggle.classList.add('expanded');
            if (!childrenDiv.dataset.loaded) loadColumns(connKey, database, schema, table, childrenDiv);
        }
    };

    // -- Level 4b – Routines ---------------------------------------------------

    function loadRoutines(connKey, database, schema, container) {
        container.innerHTML = '<div class="tree-loading">Loading routines...</div>';

        fetch('/api/tree/routines?conn=' + encodeURIComponent(connKey) +
              '&db='     + encodeURIComponent(database) +
              '&schema=' + encodeURIComponent(schema))
            .then(r => r.json())
            .then(data => {
                container.dataset.loaded = 'true';
                if (!data.routines || data.routines.length === 0) {
                    container.innerHTML = '<div class="tree-empty">No routines</div>';
                    return;
                }
                renderRoutines(container, data.routines);
            })
            .catch(() => {
                container.innerHTML = '<div class="tree-error">Failed to load routines</div>';
            });
    }

    function renderRoutines(container, routines) {
        const ul = document.createElement('ul');
        routines.forEach(r => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            li.innerHTML = `
                <div class="tree-node-content leaf-node">
                    <span class="tree-toggle empty"></span>
                    <span class="tree-icon routine-icon"><i class="bi bi-braces-asterisk"></i></span>
                    <span class="tree-label">${escapeHtml(r.name)}</span>
                    <span class="col-type">${escapeHtml((r.type || 'function').toLowerCase())}</span>
                </div>`;
            ul.appendChild(li);
        });
        container.innerHTML = '';
        container.appendChild(ul);
    }

    // -- Level 4c – Sequences --------------------------------------------------

    function loadSequences(connKey, database, schema, container) {
        container.innerHTML = '<div class="tree-loading">Loading sequences...</div>';

        fetch('/api/tree/sequences?conn=' + encodeURIComponent(connKey) +
              '&db='     + encodeURIComponent(database) +
              '&schema=' + encodeURIComponent(schema))
            .then(r => r.json())
            .then(data => {
                container.dataset.loaded = 'true';
                if (!data.sequences || data.sequences.length === 0) {
                    container.innerHTML = '<div class="tree-empty">No sequences</div>';
                    return;
                }
                renderSequences(container, data.sequences);
            })
            .catch(() => {
                container.innerHTML = '<div class="tree-error">Failed to load sequences</div>';
            });
    }

    function renderSequences(container, sequences) {
        const ul = document.createElement('ul');
        sequences.forEach(seq => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            li.innerHTML = `
                <div class="tree-node-content leaf-node">
                    <span class="tree-toggle empty"></span>
                    <span class="tree-icon sequence-icon"><i class="bi bi-hash"></i></span>
                    <span class="tree-label">${escapeHtml(seq)}</span>
                </div>`;
            ul.appendChild(li);
        });
        container.innerHTML = '';
        container.appendChild(ul);
    }

    // -- Level 5 -- Columns (leaf) ----------------------------------------------

    function loadColumns(connKey, database, schema, table, container) {
        container.innerHTML = '<div class="tree-loading">Loading columns...</div>';

        fetch('/api/tree/columns?conn='   + encodeURIComponent(connKey) +
              '&db='     + encodeURIComponent(database) +
              '&schema=' + encodeURIComponent(schema) +
              '&table='  + encodeURIComponent(table))
            .then(r => r.json())
            .then(data => {
                container.dataset.loaded = 'true';
                if (!data.columns || data.columns.length === 0) {
                    container.innerHTML = '<div class="tree-empty">No columns</div>';
                    return;
                }
                renderColumns(container, data.columns);
            })
            .catch(() => {
                container.innerHTML = '<div class="tree-error">Failed to load columns</div>';
            });
    }

    function renderColumns(container, columns) {
        const ul = document.createElement('ul');
        columns.forEach(col => {
            const li = document.createElement('li');
            li.className = 'tree-node';
            li.innerHTML = `
                <div class="tree-node-content leaf-node"
                     title="${escapeAttr(col.name)} (${escapeAttr(col.type)})">
                    <span class="tree-toggle empty"></span>
                    <span class="tree-icon column-icon"><i class="bi bi-columns-gap"></i></span>
                    <span class="tree-label">${escapeHtml(col.name)}</span>
                    <span class="col-type">${escapeHtml(abbreviateType(col.type))}</span>
                </div>`;
            ul.appendChild(li);
        });
        container.innerHTML = '';
        container.appendChild(ul);
    }

    // -- Helpers ---------------------------------------------------------------

    function nodeKey(...parts) {
        return 'nd-' + parts
            .map(p => btoa(unescape(encodeURIComponent(p))).replace(/[^a-zA-Z0-9]/g, '_'))
            .join('-');
    }

    function abbreviateType(type) {
        const map = {
            'character varying': 'varchar', 'timestamp without time zone': 'timestamp',
            'timestamp with time zone': 'timestamptz', 'double precision': 'float8',
            'boolean': 'bool', 'integer': 'int4', 'bigint': 'int8',
            'smallint': 'int2', 'real': 'float4',
            'TIMESTAMP_NTZ': 'timestamp', 'TIMESTAMP_LTZ': 'timestamptz',
            'NUMBER': 'number', 'VARCHAR': 'varchar', 'BOOLEAN': 'bool', 'VARIANT': 'variant',
        };
        return map[type] || type;
    }

    function escapeHtml(str) {
        if (str == null) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function escapeAttr(str) {
        if (str == null) return '';
        return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // -- Boot ------------------------------------------------------------------

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
