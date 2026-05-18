# ---------------------------------------------------------------------------
# DETools — Phase 1 Check Catalog
# Each entry defines a built-in check type that can be applied to any table
# or column without writing code.
# ---------------------------------------------------------------------------

CHECK_CATALOG = {

    # ── Table-level checks ──────────────────────────────────────────────────

    'row_count': {
        'level': 'table',
        'dimension': 'Completeness',
        'label': 'Row Count',
        'description': 'Total rows in the table. Alert when count falls below (min) or exceeds (max) thresholds.',
        'direction': 'max',
        'extra_params': [],
        'unit': 'rows',
        'threshold_hints': {
            'warning': 'Max rows before warning (leave blank to skip)',
            'error':   'Max rows before error   (leave blank to skip)',
            'fatal':   'Max rows before fatal   (leave blank to skip)',
        },
    },

    'row_count_min': {
        'level': 'table',
        'dimension': 'Completeness',
        'label': 'Row Count (min expected)',
        'description': 'Alert when the table has fewer rows than the expected minimum.',
        'direction': 'min',
        'extra_params': [],
        'unit': 'rows',
        'threshold_hints': {
            'warning': 'Min rows expected (warning if below)',
            'error':   'Min rows expected (error if below)',
            'fatal':   'Min rows expected (fatal if below — table may be empty)',
        },
    },

    'freshness_hours': {
        'level': 'table',
        'dimension': 'Freshness',
        'label': 'Freshness (hours since latest record)',
        'description': 'Hours elapsed since the most recent value in a timestamp column. Alert when data becomes stale.',
        'direction': 'max',
        'extra_params': ['freshness_column'],
        'unit': 'hours',
        'threshold_hints': {
            'warning': 'Hours before warning (e.g. 25 = warn if no data in 25h)',
            'error':   'Hours before error',
            'fatal':   'Hours before fatal',
        },
    },

    # ── Column-level checks ─────────────────────────────────────────────────

    'nulls_percent': {
        'level': 'column',
        'dimension': 'Completeness',
        'label': 'Null %',
        'description': 'Percentage of null values in the column. Alert when too many nulls.',
        'direction': 'max',
        'extra_params': [],
        'unit': '%',
        'threshold_hints': {
            'warning': 'Max null % before warning (e.g. 1.0)',
            'error':   'Max null % before error   (e.g. 5.0)',
            'fatal':   'Max null % before fatal   (e.g. 30.0)',
        },
    },

    'nulls_count': {
        'level': 'column',
        'dimension': 'Completeness',
        'label': 'Null Count',
        'description': 'Absolute count of null values. Alert when count exceeds threshold.',
        'direction': 'max',
        'extra_params': [],
        'unit': 'rows',
        'threshold_hints': {
            'warning': 'Max nulls before warning',
            'error':   'Max nulls before error',
            'fatal':   'Max nulls before fatal',
        },
    },

    'unique_percent': {
        'level': 'column',
        'dimension': 'Uniqueness',
        'label': 'Unique %',
        'description': 'Percentage of distinct non-null values. Alert when uniqueness drops below threshold.',
        'direction': 'min',
        'extra_params': [],
        'unit': '%',
        'threshold_hints': {
            'warning': 'Min unique % before warning (e.g. 99.0)',
            'error':   'Min unique % before error',
            'fatal':   'Min unique % before fatal',
        },
    },

    'accepted_values': {
        'level': 'column',
        'dimension': 'Validity',
        'label': 'Accepted Values (invalid count)',
        'description': 'Count of rows whose value is NOT in the accepted list. Alert when invalid values are found.',
        'direction': 'max',
        'extra_params': ['accepted_values'],
        'unit': 'rows',
        'threshold_hints': {
            'warning': 'Max invalid rows before warning (usually 0)',
            'error':   'Max invalid rows before error',
            'fatal':   'Max invalid rows before fatal',
        },
    },

    'regex_pattern': {
        'level': 'column',
        'dimension': 'Validity',
        'label': 'Regex Pattern (non-matching count)',
        'description': 'Count of rows that do NOT match the regular expression. Alert when pattern violations are found.',
        'direction': 'max',
        'extra_params': ['pattern'],
        'unit': 'rows',
        'threshold_hints': {
            'warning': 'Max non-matching rows before warning (usually 0)',
            'error':   'Max non-matching rows before error',
            'fatal':   'Max non-matching rows before fatal',
        },
    },

    'min_value': {
        'level': 'column',
        'dimension': 'Accuracy',
        'label': 'Minimum Value',
        'description': 'Minimum numeric value in the column. Alert when min drops below threshold.',
        'direction': 'min',
        'extra_params': [],
        'unit': '',
        'threshold_hints': {
            'warning': 'Min acceptable value (warning if below)',
            'error':   'Min acceptable value (error if below)',
            'fatal':   'Min acceptable value (fatal if below)',
        },
    },

    'max_value': {
        'level': 'column',
        'dimension': 'Accuracy',
        'label': 'Maximum Value',
        'description': 'Maximum numeric value in the column. Alert when max exceeds threshold.',
        'direction': 'max',
        'extra_params': [],
        'unit': '',
        'threshold_hints': {
            'warning': 'Max acceptable value (warning if exceeded)',
            'error':   'Max acceptable value (error if exceeded)',
            'fatal':   'Max acceptable value (fatal if exceeded)',
        },
    },

    'min_length': {
        'level': 'column',
        'dimension': 'Validity',
        'label': 'Minimum Text Length',
        'description': 'Minimum text length across all non-null values. Alert when any value is too short.',
        'direction': 'min',
        'extra_params': [],
        'unit': 'chars',
        'threshold_hints': {
            'warning': 'Min length expected (warning if shorter)',
            'error':   'Min length expected (error if shorter)',
            'fatal':   'Min length expected (fatal if shorter)',
        },
    },

    'max_length': {
        'level': 'column',
        'dimension': 'Validity',
        'label': 'Maximum Text Length',
        'description': 'Maximum text length across all values. Alert when any value is too long.',
        'direction': 'max',
        'extra_params': [],
        'unit': 'chars',
        'threshold_hints': {
            'warning': 'Max length allowed (warning if exceeded)',
            'error':   'Max length allowed (error if exceeded)',
            'fatal':   'Max length allowed (fatal if exceeded)',
        },
    },

    'custom_sql': {
        'level': 'both',
        'dimension': 'Consistency',
        'label': 'Custom SQL',
        'description': 'User-defined SQL returning a single numeric value. Alert when value exceeds threshold.',
        'direction': 'max',
        'extra_params': ['custom_sql'],
        'unit': '',
        'threshold_hints': {
            'warning': 'Max value before warning',
            'error':   'Max value before error',
            'fatal':   'Max value before fatal',
        },
    },
}
