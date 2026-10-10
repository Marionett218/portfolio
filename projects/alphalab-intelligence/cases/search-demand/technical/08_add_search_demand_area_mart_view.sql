-- 08_add_search_demand_area_mart_view.sql
-- Creates a Tableau-oriented mart VIEW containing diagnostic_area rows
-- for the full available history.
--
-- Grain:
--   source × region × period × diagnostic_area
--
-- Performance principle:
--   build directly from staging.keywords_monthly and the keyword→area mapping,
--   rather than from analysis.search_demand_area_monthly.
--   This lets PostgreSQL push Tableau filters such as source and
--   diagnostic_area down before the expensive aggregation.
--
-- Only keyword_diagnostic_areas rows with
-- include_in_area_aggregate = TRUE contribute to area totals.

BEGIN;

DO $$
BEGIN
    IF to_regclass('staging.keywords_monthly') IS NULL THEN
        RAISE EXCEPTION
            'Expected table staging.keywords_monthly does not exist';
    END IF;

    IF to_regclass('reference.keyword_diagnostic_areas') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.keyword_diagnostic_areas does not exist';
    END IF;

    IF to_regclass('reference.diagnostic_areas') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.diagnostic_areas does not exist';
    END IF;
END
$$;

CREATE OR REPLACE VIEW mart.search_demand_area AS
SELECT
    km.source,
    km.region_id,
    km.start_date,
    km.end_date,
    'diagnostic_area'::text AS level,
    kda.diagnostic_area_id AS entity_id,
    da.name_ru AS entity_name_ru,
    SUM(km.query_count)::bigint AS query_count,
    COUNT(DISTINCT km.keyword_id) AS keyword_count
FROM staging.keywords_monthly AS km
JOIN reference.keyword_diagnostic_areas AS kda
    ON kda.keyword_id = km.keyword_id
   AND kda.include_in_area_aggregate IS TRUE
JOIN reference.diagnostic_areas AS da
    ON da.diagnostic_area_id = kda.diagnostic_area_id
GROUP BY
    km.source,
    km.region_id,
    km.start_date,
    km.end_date,
    kda.diagnostic_area_id,
    da.name_ru;

COMMENT ON VIEW mart.search_demand_area IS
'Tableau-oriented Search Demand view containing diagnostic_area rows for the full available history. Grain: source × region × period × diagnostic_area. Built directly from staging so source and diagnostic_area predicates can be pushed down before aggregation.';

COMMENT ON COLUMN mart.search_demand_area.level IS
'Constant entity level: diagnostic_area.';

COMMENT ON COLUMN mart.search_demand_area.entity_id IS
'Diagnostic area identifier: reference.diagnostic_areas.diagnostic_area_id.';

COMMENT ON COLUMN mart.search_demand_area.entity_name_ru IS
'Russian/display label from reference.diagnostic_areas.name_ru.';

COMMENT ON COLUMN mart.search_demand_area.query_count IS
'Sum of query_count for keywords included in the diagnostic-area aggregate.';

COMMENT ON COLUMN mart.search_demand_area.keyword_count IS
'Number of distinct included keywords contributing to the diagnostic-area aggregate.';

COMMIT;
