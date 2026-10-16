"""Part 5: analytics runs, unit metrics, scenario results, public benchmarks, price indices and adjustments.

Additive only; no existing table is altered. Decimal columns use the exact
decimal-string type (``DecimalText``, VARCHAR(64)).

Revision ID: 0007_part5_analytics
Revises: 0006_part4_full_costs
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007_part5_analytics"
down_revision: str | None = "0006_part4_full_costs"
branch_labels = None
depends_on = None

DEC = sa.String(64)


def upgrade() -> None:
    op.create_table('benchmark_observation',
    sa.Column('benchmark_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('traffic_source_id', sa.Integer(), nullable=True),
    sa.Column('benchmark_source', sa.String(length=40), nullable=False),
    sa.Column('source_table', sa.String(length=100), nullable=False),
    sa.Column('carrier_code', sa.String(length=10), nullable=False),
    sa.Column('carrier_name', sa.String(length=200), nullable=True),
    sa.Column('carrier_group', sa.String(length=10), nullable=True),
    sa.Column('operation_scope', sa.String(length=40), nullable=False),
    sa.Column('aircraft_type_code', sa.String(length=10), nullable=False),
    sa.Column('aircraft_type_description', sa.String(length=200), nullable=True),
    sa.Column('aircraft_config', sa.String(length=5), nullable=False),
    sa.Column('region', sa.String(length=5), nullable=False),
    sa.Column('period_label', sa.String(length=20), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('cost_category', sa.String(length=40), nullable=False),
    sa.Column('amount', DEC, nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('block_hours', DEC, nullable=True),
    sa.Column('airborne_hours', DEC, nullable=True),
    sa.Column('departures', DEC, nullable=True),
    sa.Column('revenue_tonne_nm', DEC, nullable=True),
    sa.Column('available_tonne_nm', DEC, nullable=True),
    sa.Column('aircraft_miles_nm', DEC, nullable=True),
    sa.Column('source_fields', sa.Text(), nullable=False),
    sa.Column('methodology', sa.Text(), nullable=False),
    sa.Column('quality_status', sa.String(length=30), nullable=False),
    sa.Column('quality_notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['data_source.source_id'], ),
    sa.ForeignKeyConstraint(['traffic_source_id'], ['data_source.source_id'], ),
    sa.PrimaryKeyConstraint('benchmark_id'),
    sa.UniqueConstraint('source_id', 'benchmark_source', 'carrier_code', 'aircraft_type_code', 'aircraft_config', 'region', 'period_label', 'cost_category', name='uq_benchmark_observation_key')
    )
    op.create_index(op.f('ix_benchmark_observation_source_id'), 'benchmark_observation', ['source_id'], unique=False)
    op.create_table('price_index_observation',
    sa.Column('index_observation_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('series_id', sa.String(length=40), nullable=False),
    sa.Column('series_title', sa.String(length=300), nullable=True),
    sa.Column('period', sa.String(length=10), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('value', DEC, nullable=False),
    sa.Column('preliminary', sa.Boolean(), nullable=False),
    sa.Column('footnotes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['source_id'], ['data_source.source_id'], ),
    sa.PrimaryKeyConstraint('index_observation_id'),
    sa.UniqueConstraint('source_id', 'series_id', 'period', name='uq_price_index_observation')
    )
    op.create_index(op.f('ix_price_index_observation_series_id'), 'price_index_observation', ['series_id'], unique=False)
    op.create_index(op.f('ix_price_index_observation_source_id'), 'price_index_observation', ['source_id'], unique=False)
    op.create_table('benchmark_adjustment',
    sa.Column('adjustment_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('benchmark_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('original_amount', DEC, nullable=True),
    sa.Column('original_currency', sa.String(length=3), nullable=False),
    sa.Column('original_period', sa.String(length=40), nullable=False),
    sa.Column('index_series_id', sa.String(length=40), nullable=False),
    sa.Column('index_source_id', sa.Integer(), nullable=True),
    sa.Column('base_period', sa.String(length=60), nullable=True),
    sa.Column('base_index', DEC, nullable=True),
    sa.Column('target_period', sa.String(length=60), nullable=True),
    sa.Column('target_date', sa.Date(), nullable=False),
    sa.Column('target_index', DEC, nullable=True),
    sa.Column('factor', DEC, nullable=True),
    sa.Column('adjusted_amount', DEC, nullable=True),
    sa.Column('methodology', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['benchmark_id'], ['benchmark_observation.benchmark_id'], ),
    sa.ForeignKeyConstraint(['index_source_id'], ['data_source.source_id'], ),
    sa.PrimaryKeyConstraint('adjustment_id'),
    sa.UniqueConstraint('benchmark_id', 'index_series_id', 'target_date', 'index_source_id', name='uq_benchmark_adjustment')
    )
    op.create_index(op.f('ix_benchmark_adjustment_benchmark_id'), 'benchmark_adjustment', ['benchmark_id'], unique=False)
    op.create_table('analytics_run',
    sa.Column('analytics_run_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('analysis_type', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('flight_estimate_id', sa.Integer(), nullable=True),
    sa.Column('variable_cost_estimate_id', sa.Integer(), nullable=True),
    sa.Column('full_cost_estimate_id', sa.Integer(), nullable=True),
    sa.Column('base_scenario_id', sa.Integer(), nullable=True),
    sa.Column('pricing_date', sa.Date(), nullable=True),
    sa.Column('reporting_currency', sa.String(length=3), nullable=True),
    sa.Column('distance_basis', sa.String(length=30), nullable=True),
    sa.Column('payload_basis', sa.Text(), nullable=True),
    sa.Column('coverage_status', sa.String(length=30), nullable=False),
    sa.Column('operational_validity', sa.String(length=50), nullable=True),
    sa.Column('source_quality_summary', sa.String(length=200), nullable=False),
    sa.Column('parameters_json', sa.Text(), nullable=False),
    sa.Column('result_json', sa.Text(), nullable=False),
    sa.Column('warnings_json', sa.Text(), nullable=False),
    sa.Column('calculation_version', sa.String(length=100), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['base_scenario_id'], ['cost_scenario.scenario_id'], ),
    sa.ForeignKeyConstraint(['flight_estimate_id'], ['flight_estimate.flight_estimate_id'], ),
    sa.ForeignKeyConstraint(['full_cost_estimate_id'], ['full_cost_estimate.full_cost_estimate_id'], ),
    sa.ForeignKeyConstraint(['variable_cost_estimate_id'], ['variable_cost_estimate.variable_cost_estimate_id'], ),
    sa.PrimaryKeyConstraint('analytics_run_id'),
    sa.UniqueConstraint('input_hash', name='uq_analytics_run_input_hash')
    )
    op.create_index(op.f('ix_analytics_run_flight_estimate_id'), 'analytics_run', ['flight_estimate_id'], unique=False)
    op.create_index(op.f('ix_analytics_run_full_cost_estimate_id'), 'analytics_run', ['full_cost_estimate_id'], unique=False)
    op.create_table('benchmark_comparison',
    sa.Column('comparison_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('analytics_run_id', sa.Integer(), nullable=False),
    sa.Column('model_metric', sa.String(length=80), nullable=False),
    sa.Column('model_value', DEC, nullable=True),
    sa.Column('model_unit', sa.String(length=40), nullable=False),
    sa.Column('benchmark_metric', sa.String(length=80), nullable=False),
    sa.Column('benchmark_value', DEC, nullable=True),
    sa.Column('benchmark_value_converted', DEC, nullable=True),
    sa.Column('benchmark_unit', sa.String(length=40), nullable=False),
    sa.Column('benchmark_selection_json', sa.Text(), nullable=False),
    sa.Column('comparability', sa.String(length=30), nullable=False),
    sa.Column('checks_json', sa.Text(), nullable=False),
    sa.Column('reasons_json', sa.Text(), nullable=False),
    sa.Column('absolute_difference', DEC, nullable=True),
    sa.Column('percentage_difference', DEC, nullable=True),
    sa.Column('fx_basis', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['analytics_run_id'], ['analytics_run.analytics_run_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('comparison_id')
    )
    op.create_index(op.f('ix_benchmark_comparison_analytics_run_id'), 'benchmark_comparison', ['analytics_run_id'], unique=False)
    op.create_table('scenario_result',
    sa.Column('scenario_result_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('analytics_run_id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=300), nullable=False),
    sa.Column('variations_json', sa.Text(), nullable=False),
    sa.Column('modified_values_json', sa.Text(), nullable=False),
    sa.Column('variant_scenario_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('fuel_cost', DEC, nullable=True),
    sa.Column('direct_variable_subtotal', DEC, nullable=True),
    sa.Column('cash_operating_subtotal', DEC, nullable=True),
    sa.Column('total_operating_subtotal', DEC, nullable=True),
    sa.Column('total_cost_subtotal', DEC, nullable=True),
    sa.Column('complete_coc', DEC, nullable=True),
    sa.Column('complete_toc', DEC, nullable=True),
    sa.Column('complete_total_costs', DEC, nullable=True),
    sa.Column('components_json', sa.Text(), nullable=False),
    sa.Column('deltas_json', sa.Text(), nullable=False),
    sa.Column('coverage_status', sa.String(length=30), nullable=False),
    sa.Column('operational_validity', sa.String(length=50), nullable=True),
    sa.Column('source_quality', sa.String(length=200), nullable=True),
    sa.Column('calculated_at', sa.String(length=40), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('warnings_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['analytics_run_id'], ['analytics_run.analytics_run_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['variant_scenario_id'], ['cost_scenario.scenario_id'], ),
    sa.PrimaryKeyConstraint('scenario_result_id')
    )
    op.create_index(op.f('ix_scenario_result_analytics_run_id'), 'scenario_result', ['analytics_run_id'], unique=False)
    op.create_table('unit_cost_metric',
    sa.Column('metric_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('analytics_run_id', sa.Integer(), nullable=False),
    sa.Column('case_label', sa.String(length=200), nullable=False),
    sa.Column('flight_estimate_id', sa.Integer(), nullable=True),
    sa.Column('metric_name', sa.String(length=60), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('cost_basis', sa.String(length=30), nullable=False),
    sa.Column('cost_measure', sa.String(length=30), nullable=False),
    sa.Column('numerator_amount', DEC, nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('denominator_value', DEC, nullable=True),
    sa.Column('denominator_unit', sa.String(length=30), nullable=False),
    sa.Column('denominator_basis', sa.Text(), nullable=False),
    sa.Column('metric_value', DEC, nullable=True),
    sa.Column('metric_unit', sa.String(length=40), nullable=False),
    sa.Column('metric_status', sa.String(length=20), nullable=False),
    sa.Column('coverage_status', sa.String(length=30), nullable=False),
    sa.Column('operational_validity', sa.String(length=50), nullable=False),
    sa.Column('source_quality', sa.String(length=200), nullable=False),
    sa.Column('pricing_date', sa.Date(), nullable=False),
    sa.Column('fx_basis', sa.Text(), nullable=False),
    sa.Column('payload_basis', sa.Text(), nullable=True),
    sa.Column('calculation_method', sa.Text(), nullable=False),
    sa.Column('components_json', sa.Text(), nullable=False),
    sa.Column('warnings_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['analytics_run_id'], ['analytics_run.analytics_run_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['flight_estimate_id'], ['flight_estimate.flight_estimate_id'], ),
    sa.PrimaryKeyConstraint('metric_id')
    )
    op.create_index(op.f('ix_unit_cost_metric_analytics_run_id'), 'unit_cost_metric', ['analytics_run_id'], unique=False)


def downgrade() -> None:

    op.drop_index(op.f('ix_unit_cost_metric_analytics_run_id'), table_name='unit_cost_metric')
    op.drop_table('unit_cost_metric')
    op.drop_index(op.f('ix_scenario_result_analytics_run_id'), table_name='scenario_result')
    op.drop_table('scenario_result')
    op.drop_index(op.f('ix_benchmark_comparison_analytics_run_id'), table_name='benchmark_comparison')
    op.drop_table('benchmark_comparison')
    op.drop_index(op.f('ix_analytics_run_full_cost_estimate_id'), table_name='analytics_run')
    op.drop_index(op.f('ix_analytics_run_flight_estimate_id'), table_name='analytics_run')
    op.drop_table('analytics_run')
    op.drop_index(op.f('ix_benchmark_adjustment_benchmark_id'), table_name='benchmark_adjustment')
    op.drop_table('benchmark_adjustment')
    op.drop_index(op.f('ix_price_index_observation_source_id'), table_name='price_index_observation')
    op.drop_index(op.f('ix_price_index_observation_series_id'), table_name='price_index_observation')
    op.drop_table('price_index_observation')
    op.drop_index(op.f('ix_benchmark_observation_source_id'), table_name='benchmark_observation')
    op.drop_table('benchmark_observation')
