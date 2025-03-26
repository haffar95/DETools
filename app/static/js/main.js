document.addEventListener('DOMContentLoaded', function() {
    const schemaSelect = document.getElementById('schemaSelect');
    const tableSelect = document.getElementById('tableSelect');
    const dateSelect = document.getElementById('dateSelect');
    const validateBtn = document.getElementById('validateBtn');
    const resultsDiv = document.getElementById('validationResults');
    const validateQueryBtn = document.getElementById('validateQueryBtn');

    // Tab switching functionality
    document.querySelectorAll('.nav-item[data-tab]').forEach(button => {
        button.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('.nav-item').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.mode-content').forEach(content => content.classList.remove('active'));
            
            button.classList.add('active');
            const tabId = button.getAttribute('data-tab');
            document.getElementById(`${tabId}-mode`).classList.add('active');
            
            resultsDiv.innerHTML = '';
        });
    });

    // Initialize select2 on selects
    $(document).ready(function() {
        $('#schemaSelect').select2({
            placeholder: 'Search or select a schema',
            allowClear: true,
            width: '400px',
            minimumResultsForSearch: 0,
            dropdownAutoWidth: true,
            closeOnSelect: true,
            search: true
        });

        $('#tableSelect').select2({
            placeholder: 'Search or select a table',
            allowClear: true,
            width: '400px',
            minimumResultsForSearch: 0,
            dropdownAutoWidth: true,
            closeOnSelect: true,
            search: true
        });
    });

    function showLoading(message = 'Loading...') {
        const overlay = document.createElement('div');
        overlay.className = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-container">
                <div class="loading-spinner"></div>
                <div class="loading-text">${message}</div>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    function hideLoading() {
        const overlay = document.querySelector('.loading-overlay');
        if (overlay) {
            overlay.remove();
        }
    }

    function disableControls() {
        document.querySelectorAll('select, button').forEach(el => {
            el.classList.add('disabled');
        });
    }

    function enableControls() {
        document.querySelectorAll('select, button').forEach(el => {
            el.classList.remove('disabled');
        });
    }

    $('#tableSelect').on('change', async function() {
        if (this.value) {
            console.log('Selected table:', this.value);
            showLoading('Loading table information...');
            disableControls();
            try {
                const response = await fetch(`/api/columns/${this.value}`);
                const data = await response.json();
                
                console.log('Received data:', data); // Debug log
                
                // Populate all dropdowns with columns
                if (data.columns && data.columns.length > 0) {
                    const keySelect = document.getElementById('keySelect');
                    const foreignKeySelect = document.getElementById('foreignKeySelect');
                    const dateSelect = document.getElementById('dateSelect');
                    
                    // Create options HTML
                    const optionsHtml = '<option value="">Select a column</option>' +
                        data.columns.map(col => 
                            `<option value="${col[0]}" data-type="${col[1]}">${col[0]}</option>`
                        ).join('');
                    
                    // Set options for all dropdowns
                    keySelect.innerHTML = optionsHtml;
                    foreignKeySelect.innerHTML = optionsHtml;
                    dateSelect.innerHTML = '<option value="">Select a date column</option>' +
                        data.columns.filter(col => col[1].includes('timestamp') || col[1].includes('date'))
                        .map(col => `<option value="${col[0]}">${col[0]}</option>`).join('');
                    
                    document.getElementById('keyColumnGroup').style.display = 'block';
                    document.getElementById('foreignKeyGroup').style.display = 'block';
                    document.getElementById('dateColumnGroup').style.display = 'block';
                    validateBtn.style.display = 'inline-block';
                } else {
                    document.getElementById('keyColumnGroup').style.display = 'none';
                    document.getElementById('foreignKeyGroup').style.display = 'none';
                    document.getElementById('dateColumnGroup').style.display = 'none';
                    document.getElementById('dateValueGroup').style.display = 'none';
                    validateBtn.style.display = 'none';
                }

            } catch (error) {
                console.error('Error:', error);
                resultsDiv.innerHTML = `
                    <div class="validation-section error">
                        <h3>Error</h3>
                        <p>Failed to load table information: ${error.message}</p>
                    </div>
                `;
            } finally {
                hideLoading();
                enableControls();
            }
        } else {
            document.getElementById('keyColumnGroup').style.display = 'none';
            document.getElementById('foreignKeyGroup').style.display = 'none';
            document.getElementById('dateColumnGroup').style.display = 'none';
            document.getElementById('dateValueGroup').style.display = 'none';
            validateBtn.style.display = 'none';
        }
    });

    // Show validate button when key is selected
    $('#keySelect').on('change', function() {
        validateBtn.style.display = this.value ? 'inline-block' : 'none';
    });

    validateBtn.addEventListener('click', async function() {
        const table = tableSelect.value;
        const schema = schemaSelect.value;
        const keyColumn = document.getElementById('keySelect').value;
        const foreignKey = document.getElementById('foreignKeySelect').value;
        const dateColumn = document.getElementById('dateSelect').value;
        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;
        
        showLoading('Validating data...');
        disableControls();
        
        try {
            const response = await fetch(
                `/api/validate?table=${table}` +
                `&schema=${schema}` +
                `${keyColumn ? `&key_column=${keyColumn}` : ''}` +
                `${foreignKey ? `&foreign_key=${foreignKey}` : ''}` +
                `${dateColumn && startDate && endDate ? 
                    `&date_column=${dateColumn}&start_date=${startDate}&end_date=${endDate}` : ''}`
            );

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const results = await response.json();
            
            if (results.error) {
                resultsDiv.innerHTML = `
                    <div class="validation-section error">
                        <h3>Error</h3>
                        <p>${results.error}</p>
                    </div>
                `;
                return;
            }
            
            resultsDiv.innerHTML = displayResults(results);
        } catch (error) {
            let errorMessage = error.message;
            resultsDiv.innerHTML = `
                <div class="validation-section error">
                    <h3>Error</h3>
                    <p>An error occurred while validating the data: ${errorMessage}</p>
                </div>
            `;
        } finally {
            hideLoading();
            enableControls();
        }
    });

    function displayResults(results) {
        let html = '';
        
        // Display basic info
        html += `
            <div class="validation-section">
                <h3>Overview</h3>
                <table class="results-table">
                    <tr>
                        <th>Total Rows Analyzed</th>
                        <td><span class="status-badge">${results.row_count}</span></td>
                    </tr>
                </table>
            </div>
        `;
        
        // Display duplicates
        html += `
            <div class="validation-section">
                <h3>Duplicates</h3>
                ${results.duplicates && results.duplicates.details && Object.entries(results.duplicates.details).length > 0 ? `
                    <table class="results-table">
                        ${Object.entries(results.duplicates.details).map(([type, data]) => `
                        <tr>
                            <th style="background-color: var(--primary-color); color: white;">
                                ${type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                            </th>
                            <td>
                                <span class="status-badge">${data.total_records || data.count}</span>
                                ${data.records ? `
                                    <details>
                                        <summary>View duplicate records</summary>
                                        <div class="nested-table-container">
                                            <table class="nested-table">
                                                <thead>
                                                    <tr>
                                                        ${Object.keys(data.records[0] || {}).map(key => 
                                                            `<th>${key}</th>`
                                                        ).join('')}
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    ${data.records.map(record => `
                                                        <tr>
                                                            ${Object.values(record).map(value => 
                                                                `<td>${value !== null ? value : 'NULL'}</td>`
                                                            ).join('')}
                                                        </tr>
                                                    `).join('')}
                                                </tbody>
                                            </table>
                                        </div>
                                        ${data.total_records > 100 ? 
                                            `<p class="note">Showing 100 of ${data.total_records} records</p>` 
                                            : ''}
                                    </details>
                                ` : ''}
                            </td>
                        </tr>
                        `).join('')}
                    </table>
                ` : `
                    <table class="results-table">
                        <tr>
                            <th style="background-color: var(--primary-color); color: white;">Duplicates Found</th>
                            <td>
                                <span class="status-badge">${results.duplicates ? results.duplicates.count : 0}</span>
                            </td>
                        </tr>
                    </table>
                `}
            </div>
        `;

        // Display date validation issues
        html += `
            <div class="validation-section">
                <h3>Date Issues</h3>
                ${results.date_issues && Object.keys(results.date_issues).length > 0 ? `
                    <table class="results-table">
                        <thead>
                            <tr>
                                <th style="background-color: var(--primary-color); color: white;">Column</th>
                                <th style="background-color: var(--primary-color); color: white;">Issue Type</th>
                                <th style="background-color: var(--primary-color); color: white;">Count</th>
                                <th style="background-color: var(--primary-color); color: white;">Details</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${Object.entries(results.date_issues).map(([key, data]) => {
                                const [column, issue] = key.split('_');
                                const issueType = {
                                    'invalid': 'Invalid Format',
                                    'future': 'Future Date',
                                    'old': 'Too Old'
                                }[issue] || issue;
                                return `
                                    <tr>
                                        <td>${column}</td>
                                        <td>${issueType}</td>
                                        <td>${data.count}</td>
                                        <td>
                                            ${data.values ? `
                                                <details>
                                                    <summary>View Examples</summary>
                                                    <div class="nested-table-container">
                                                        <table class="nested-table">
                                                            <thead>
                                                                <tr>
                                                                    <th>Value</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody>
                                                                ${data.values.map(value => `
                                                                    <tr>
                                                                        <td>${value}</td>
                                                                    </tr>
                                                                `).join('')}
                                                            </tbody>
                                                        </table>
                                                    </div>
                                                    ${data.values.length < data.count ? 
                                                        `<p class="note">Showing first 100 of ${data.count} values</p>` 
                                                        : ''}
                                                </details>
                                            ` : 'No examples available'}
                                        </td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                ` : `
                    <table class="results-table">
                        <tr>
                            <th style="background-color: var(--primary-color); color: white;">Status</th>
                            <td>
                                <span class="status-badge">✓ No date issues found</span>
                            </td>
                        </tr>
                    </table>
                `}
            </div>
        `;

        // Display anomalies
        html += `
            <div class="validation-section">
                <h3>Anomalies</h3>
                ${results.anomalies && Object.keys(results.anomalies).length > 0 ? `
                    <table class="results-table">
                        <thead>
                            <tr>
                                <th style="background-color: var(--primary-color); color: white;">Column</th>
                                <th style="background-color: var(--primary-color); color: white;">Count</th>
                                <th style="background-color: var(--primary-color); color: white;">Statistics</th>
                                <th style="background-color: var(--primary-color); color: white;">Details</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${Object.entries(results.anomalies).map(([column, data]) => `
                                <tr>
                                    <td>${column}</td>
                                    <td>${data.count}</td>
                                    <td>
                                        <small>
                                            Median: ${data.stats.median.toLocaleString()}<br>
                                            Mean: ${data.stats.mean.toLocaleString()}<br>
                                            Expected Range:<br>
                                            ${data.bounds.lower.toLocaleString()} - ${data.bounds.upper.toLocaleString()}
                                        </small>
                                    </td>
                                    <td>
                                        ${data.values ? `
                                            <details>
                                                <summary>View Outliers</summary>
                                                <div class="nested-table-container">
                                                    <table class="nested-table">
                                                        <thead>
                                                            <tr>
                                                                <th>Value</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            ${data.values.map(value => `
                                                                <tr>
                                                                    <td>${value.toLocaleString()}</td>
                                                                </tr>
                                                            `).join('')}
                                                        </tbody>
                                                    </table>
                                                </div>
                                                ${data.values.length < data.count ? 
                                                    `<p class="note">Showing first 100 of ${data.count} outliers</p>` 
                                                    : ''}
                                            </details>
                                        ` : 'No examples available'}
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                ` : `
                    <table class="results-table">
                        <tr>
                            <th style="background-color: var(--primary-color); color: white;">Status</th>
                            <td>
                                <span class="status-badge">✓ No anomalies found</span>
                            </td>
                        </tr>
                    </table>
                `}
            </div>
        `;

        // Display null values
        html += `
            <div class="validation-section">
                <h3>Null Values</h3>
                <table class="results-table">
                    <thead>
                        <tr>
                            <th style="background-color: var(--primary-color); color: white;">Column</th>
                            <th style="background-color: var(--primary-color); color: white;">Null Count</th>
                            <th style="background-color: var(--primary-color); color: white;">Details</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${results.null_values && results.null_values.details && Object.entries(results.null_values.details)
                            .filter(([_, data]) => data.count > 0)
                            .map(([col, data]) => `
                                <tr>
                                    <td>${col}</td>
                                    <td>${data.total_rows || data.count}</td>
                                    <td>
                                        ${data.rows ? `
                                            <details>
                                                <summary>View Details</summary>
                                                <div class="table-wrapper">
                                                    <table class="nested-table">
                                                        <thead>
                                                            <tr>
                                                                ${Object.keys(data.rows[0]).map(key => 
                                                                    `<th>${key}</th>`
                                                                ).join('')}
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            ${data.rows.map(row => `
                                                                <tr>
                                                                    ${Object.values(row).map(value => 
                                                                        `<td>${value !== null ? value : 'NULL'}</td>`
                                                                    ).join('')}
                                                                </tr>
                                                            `).join('')}
                                                        </tbody>
                                                    </table>
                                                </div>
                                                ${data.total_rows > 100 ? 
                                                    `<p class="note">Showing 100 of ${data.total_rows} records</p>` 
                                                    : ''}
                                            </details>
                                        ` : 'No details available'}
                                    </td>
                                </tr>
                            `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Display timeliness issues
        html += `
            <div class="validation-section">
                <h3>Data Timeliness</h3>
                ${results.timeliness && (results.timeliness.freshness || results.timeliness.frequency) ? `
                    <table class="results-table">
                        <tr>
                            <th style="background-color: var(--primary-color); color: white;">Summary</th>
                            <td>
                                <div class="timeliness-summary">
                                    Total Issues: ${results.timeliness.summary.total_issues}<br>
                                    Stale Records: ${results.timeliness.summary.stale_records}<br>
                                    Frequency Issues: ${results.timeliness.summary.frequency_issues}
                                </div>
                            </td>
                        </tr>
                        ${Object.entries(results.timeliness.freshness).map(([column, data]) => `
                            <tr>
                                <th style="background-color: var(--primary-color); color: white;">
                                    ${column} Freshness
                                </th>
                                <td>
                                    <div class="timeliness-details">
                                        <p>${data.count} records older than ${data.max_age_days} days</p>
                                        <p>Date Range: ${data.oldest_record} to ${data.newest_record}</p>
                                        ${data.examples ? `
                                            <details>
                                                <summary>View Stale Records</summary>
                                                <div class="nested-table-container">
                                                    <table class="nested-table">
                                                        <thead>
                                                            <tr>
                                                                <th>${column}</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            ${data.examples.map(record => `
                                                                <tr>
                                                                    <td>${record[column]}</td>
                                                                </tr>
                                                            `).join('')}
                                                        </tbody>
                                                    </table>
                                                </div>
                                            </details>
                                        ` : ''}
                                    </div>
                                </td>
                            </tr>
                        `).join('')}
                        ${Object.entries(results.timeliness.frequency).map(([column, data]) => `
                            <tr>
                                <th style="background-color: var(--primary-color); color: white;">
                                    ${column} Frequency
                                </th>
                                <td>
                                    <div class="timeliness-details">
                                        <p>${data.count} days below expected daily records (${data.expected_daily})</p>
                                        <details>
                                            <summary>View Details</summary>
                                            <div class="nested-table-container">
                                                <table class="nested-table">
                                                    <thead>
                                                        <tr>
                                                            <th>Date</th>
                                                            <th>Records</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        ${Object.entries(data.details).map(([date, count]) => `
                                                            <tr>
                                                                <td>${date}</td>
                                                                <td>${count}</td>
                                                            </tr>
                                                        `).join('')}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </details>
                                    </div>
                                </td>
                            </tr>
                        `).join('')}
                    </table>
                ` : `
                    <table class="results-table">
                        <tr>
                            <th style="background-color: var(--primary-color); color: white;">Status</th>
                            <td>
                                <span class="status-badge">✓ No timeliness issues found</span>
                            </td>
                        </tr>
                    </table>
                `}
            </div>
        `;

        return html;
    }

    // Add event listener for key column selection
    $('#keySelect').on('change', function() {
        const selectedOption = this.options[this.selectedIndex];
        if (selectedOption.value) {
            const type = selectedOption.getAttribute('data-type');
            this.parentElement.querySelector('.field-info').innerHTML = 
                `Type: ${type}`;
            validateBtn.style.display = 'inline-block';
        } else {
            this.parentElement.querySelector('.field-info').innerHTML = '';
            validateBtn.style.display = 'none';
        }
    });

    // Add event listener for foreign key selection
    $('#foreignKeySelect').on('change', function() {
        const selectedOption = this.options[this.selectedIndex];
        if (selectedOption.value) {
            const type = selectedOption.getAttribute('data-type');
            this.parentElement.querySelector('.field-info').innerHTML = 
                `Type: ${type}`;
        } else {
            this.parentElement.querySelector('.field-info').innerHTML = '';
        }
    });

    // Add event listener for date column selection
    $('#dateSelect').on('change', function() {
        const dateValueGroup = document.getElementById('dateValueGroup');
        dateValueGroup.style.display = this.value ? 'block' : 'none';
    });

    // Load tables when schema is selected
    $('#schemaSelect').on('change', async function() {
        const schema = this.value;
        tableSelect.innerHTML = '<option value="">Select a table</option>';
        
        if (schema) {
            showLoading('Loading tables...');
            disableControls();
            
            try {
                const response = await fetch(`/api/tables/${schema}`);
                const data = await response.json();
                
                if (data.tables && data.tables.length > 0) {
                    data.tables.forEach(table => {
                        const option = document.createElement('option');
                        option.value = table;
                        option.textContent = table;
                        tableSelect.appendChild(option);
                    });
                    tableSelect.disabled = false;
                }
            } catch (error) {
                console.error('Error:', error);
                resultsDiv.innerHTML = `
                    <div class="validation-section error">
                        <h3>Error</h3>
                        <p>Failed to load tables: ${error.message}</p>
                    </div>
                `;
            } finally {
                hideLoading();
                enableControls();
                $(tableSelect).trigger('change');
            }
        } else {
            tableSelect.disabled = true;
            $(tableSelect).trigger('change');
        }
    });

    validateQueryBtn.addEventListener('click', async function() {
        const query = document.getElementById('sqlQuery').value;
        const queryResultsDiv = document.getElementById('queryValidationResults');

        if (!query) {
            alert('Please enter a SQL query');
            return;
        }

        showLoading('Validating query...');
        try {
            const response = await fetch('/api/validate-query', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: query
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const results = await response.json();
            if (results.error) {
                throw new Error(results.error);
            }

            queryResultsDiv.innerHTML = displayResults(results);
        } catch (error) {
            console.error('Full error:', error);
            queryResultsDiv.innerHTML = `
                <div class="validation-section error">
                    <h3>Error</h3>
                    <p>An error occurred while validating the query: ${error.message}</p>
                </div>
            `;
        } finally {
            hideLoading();
        }
    });

    // Overview page functionality
    const runValidationBtn = document.getElementById('runValidation');
    const schemaSelectOverview = document.getElementById('schemaSelect');

    if (schemaSelectOverview && runValidationBtn) {
        schemaSelectOverview.addEventListener('change', function() {
            runValidationBtn.disabled = !this.value;
        });
    
        runValidationBtn.addEventListener('click', async function() {
            const selectedSchema = schemaSelectOverview.value;
            if (!selectedSchema) return;
    
            // Show loading state
            const spinner = runValidationBtn.querySelector('.spinner-border');
            spinner.classList.remove('d-none');
            runValidationBtn.disabled = true;
    
            try {
                const response = await fetch('/api/validate-schema', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ schema: selectedSchema })
                });
    
                const data = await response.json();
    
                // Update metrics
                document.querySelector('.metric-card:nth-child(1) .score').textContent = 
                    `${(data.overall_score || 0).toFixed(2)}%`;
                document.querySelector('.metric-card:nth-child(2) .score').textContent = 
                    data.total_rows?.toLocaleString() || '0';
                document.querySelector('.metric-card:nth-child(3) .score').textContent = 
                    data.failed_rows?.toLocaleString() || '0';
    
                // Update quality indicators
                const indicators = data.quality_indicators || {};
                document.querySelector('.indicator-card:nth-child(1) .indicator-circle').textContent = 
                    `${(indicators.completeness || 0).toFixed(2)}%`;
                document.querySelector('.indicator-card:nth-child(2) .indicator-circle').textContent = 
                    `${(indicators.timeliness || 0).toFixed(2)}%`;
                document.querySelector('.indicator-card:nth-child(3) .indicator-circle').textContent = 
                    `${(indicators.accuracy || 0).toFixed(2)}%`;
                document.querySelector('.indicator-card:nth-child(4) .indicator-circle').textContent = 
                    `${(indicators.consistency || 0).toFixed(2)}%`;
                document.querySelector('.indicator-card:nth-child(5) .indicator-circle').textContent = 
                    `${(indicators.uniqueness || 0).toFixed(2)}%`;
                document.querySelector('.indicator-card:nth-child(6) .indicator-circle').textContent = 
                    `${(indicators.validity || 0).toFixed(2)}%`;
    
            } catch (error) {
                console.error('Validation error:', error);
                alert('An error occurred during validation. Please try again.');
            } finally {
                // Reset button state
                spinner.classList.add('d-none');
                runValidationBtn.disabled = false;
            }
        });
    }
});