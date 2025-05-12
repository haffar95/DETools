document.addEventListener('DOMContentLoaded', function() {
    const schemaSelect = document.getElementById('schemaSelect');
    const runValidationBtn = document.getElementById('runValidation');
    const overallScoreElement = document.querySelector('.metric-card:nth-child(1) .score');
    const processedRowsElement = document.querySelector('.metric-card:nth-child(2) .score');
    const failedRowsElement = document.querySelector('.metric-card:nth-child(3) .score');
    const qualityIndicators = {
        completeness: document.querySelector('.indicator-card:nth-child(1) .indicator-circle'),
        timeliness: document.querySelector('.indicator-card:nth-child(2) .indicator-circle'),
        accuracy: document.querySelector('.indicator-card:nth-child(3) .indicator-circle'),
        consistency: document.querySelector('.indicator-card:nth-child(4) .indicator-circle'),
        uniqueness: document.querySelector('.indicator-card:nth-child(5) .indicator-circle'),
        validity: document.querySelector('.indicator-card:nth-child(6) .indicator-circle')
    };

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

    schemaSelect.addEventListener('change', function() {
        runValidationBtn.disabled = !this.value;
    });

    runValidationBtn.addEventListener('click', async function() {
        const selectedSchema = schemaSelect.value;
        if (!selectedSchema) return;

        // Show loading state and overlay
        runValidationBtn.innerHTML = 'Running Validation...';
        showLoading('Validating schema...');

        try {
            const response = await fetch('/api/validate-schema', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ schema: selectedSchema })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            console.log('Validation response data:', data);

            if (!data || typeof data !== 'object') {
                throw new Error('Invalid response data format');
            }

            if (data.error) {
                throw new Error(data.error);
            }

            // Ensure required data properties exist
            if (typeof data.overall_score === 'undefined' || !data.metrics) {
                throw new Error('Missing required validation data');
            }

            // Update metrics
            document.querySelector('.metric-card:nth-child(1) .score').textContent = 
                `${(data.overall_score || 0).toFixed(2)}%`;
            document.querySelector('.metric-card:nth-child(2) .score').textContent = 
                data.total_rows?.toLocaleString() || '0';
            document.querySelector('.metric-card:nth-child(3) .score').textContent = 
                data.failed_rows?.toLocaleString() || '0';
            document.querySelector('.metric-card:nth-child(4) .score').textContent = 
                `${(data.processing_info?.processing_time || 0).toFixed(2)} s`;

            // Update table metrics
            document.querySelector('.table-metrics .metric-card:nth-child(1) .score').textContent = 
                data.processing_info?.total_tables?.toLocaleString() || '0';
            document.querySelector('.table-metrics .metric-card:nth-child(2) .score').textContent = 
                data.processing_info?.processed_tables?.toLocaleString() || '0';
            document.querySelector('.table-metrics .metric-card:nth-child(3) .score').textContent = 
                data.processing_info?.skipped_tables?.toLocaleString() || '0';

            // Update skipped tables list
            const skippedTablesList = document.querySelector('.skipped-tables-list');
            const failedTables = data.processing_info?.failed_tables || [];
            
            if (failedTables.length > 0) {
                skippedTablesList.innerHTML = failedTables.map(table => `
                    <div class="skipped-table-item">
                        <strong>${table.table}</strong>
                        <p class="error-message">${table.error}</p>
                    </div>
                `).join('');
            } else {
                skippedTablesList.innerHTML = '<p class="no-data">No skipped tables to display</p>';
            }

            // Update quality indicators
            const metrics = data.metrics || {};
            Object.entries(metrics).forEach(([key, value]) => {
                const indicator = qualityIndicators[key.toLowerCase()];
                if (indicator) {
                    const score = value.score || 0;
                    indicator.textContent = `${score.toFixed(2)}`;
                    indicator.style.setProperty('--percentage', score);
                    indicator.classList.add('animated');
                    updateIndicatorStyle(indicator, score);
                }
            });

        } catch (error) {
            console.error('Validation error:', error);
            let errorMessage = error.message;
            if (error.response) {
                try {
                    const errorData = await error.response.json();
                    errorMessage = errorData.error || errorMessage;
                } catch {}
            }
            alert(`Validation Error: ${errorMessage}`);
        } finally {
            // Reset button state and hide loading overlay
            runValidationBtn.innerHTML = 'Run Validation';
            runValidationBtn.disabled = false;
            hideLoading();
        }
    });

    function updateDashboard(data) {
        // Update overall metrics
        overallScoreElement.textContent = `${data.overall_score.toFixed(2)}%`;
        processedRowsElement.textContent = data.total_rows.toLocaleString();
        failedRowsElement.textContent = data.failed_rows.toLocaleString();

        // Update quality indicators
        const metrics = data.metrics || {};
        for (const [indicator, element] of Object.entries(qualityIndicators)) {
            const metricData = metrics[indicator] || {};
            const score = metricData.score || 0;
            element.textContent = `${score.toFixed(2)}%`;
            updateIndicatorStyle(element, score);
        }
    }

    function updateIndicatorStyle(element, score) {
        let color;
        if (score >= 90) color = '#28a745';
        else if (score >= 70) color = '#ffc107';
        else color = '#dc3545';
    
        element.style.color = color;
        element.classList.remove('animated');
        
        // Force a reflow to ensure the animation triggers
        void element.offsetWidth;
        
        const rotation = (score / 100) * 360;
        element.style.setProperty('--rotation', `${rotation}deg`);
        element.classList.add('animated');
    }

    function resetMetrics() {
        overallScoreElement.textContent = '-- %';
        processedRowsElement.textContent = '--';
        failedRowsElement.textContent = '--';

        for (const element of Object.values(qualityIndicators)) {
            element.textContent = '-- %';
            element.style.borderColor = '';
        }
    }
});