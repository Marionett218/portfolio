-- 07_add_keyword_area_aggregation_flag.sql
-- Adds an explicit inclusion flag to keyword <-> diagnostic_area mappings.
-- The flag controls only diagnostic-area aggregation.
-- Keyword-level source data remain unchanged and available for separate analysis.
--
-- Run manually as database owner/admin after verifying current_user/current_database.

BEGIN;

DO $$
DECLARE
    v_type text;
BEGIN
    IF to_regclass('reference.keyword_diagnostic_areas') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.keyword_diagnostic_areas does not exist';
    END IF;

    IF to_regclass('reference.keywords') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.keywords does not exist';
    END IF;

    IF to_regclass('reference.diagnostic_areas') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.diagnostic_areas does not exist';
    END IF;

    IF to_regclass('analysis.search_demand_area_monthly') IS NULL THEN
        RAISE EXCEPTION
            'Expected view analysis.search_demand_area_monthly does not exist';
    END IF;

    IF to_regclass('mart.search_demand') IS NULL THEN
        RAISE EXCEPTION
            'Expected view mart.search_demand does not exist';
    END IF;

    SELECT format_type(a.atttypid, a.atttypmod)
    INTO v_type
    FROM pg_attribute AS a
    WHERE a.attrelid = 'reference.keyword_diagnostic_areas'::regclass
      AND a.attname = 'include_in_area_aggregate'
      AND a.attnum > 0
      AND NOT a.attisdropped;

    IF v_type IS NOT NULL THEN
        RAISE EXCEPTION
            'Column reference.keyword_diagnostic_areas.include_in_area_aggregate already exists';
    END IF;
END
$$;

ALTER TABLE reference.keyword_diagnostic_areas
ADD COLUMN include_in_area_aggregate BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN reference.keyword_diagnostic_areas.include_in_area_aggregate IS
'Whether this keyword-to-diagnostic-area mapping contributes to diagnostic-area query_count and keyword_count. FALSE keeps the keyword available at keyword level but excludes it from area aggregation.';

DO $$
DECLARE
    v_expected bigint;
BEGIN
    SELECT COUNT(*)
    INTO v_expected
    FROM reference.keyword_diagnostic_areas AS kda
    JOIN reference.keywords AS k
        ON k.keyword_id = kda.keyword_id
    JOIN reference.diagnostic_areas AS da
        ON da.diagnostic_area_id = kda.diagnostic_area_id
    WHERE
        (
            k.keyword IN ('цистит', 'пиелонефрит')
            AND da.name = 'Urinary tract infections'
        )
        OR
        (
            k.keyword = 'грибок ногтей'
            AND da.name = 'Superficial mycoses'
        );

    IF v_expected <> 3 THEN
        RAISE EXCEPTION
            'Expected exactly 3 keyword-area mappings for initial exclusions, found %',
            v_expected;
    END IF;
END
$$;

UPDATE reference.keyword_diagnostic_areas AS kda
SET include_in_area_aggregate = FALSE
FROM reference.keywords AS k,
     reference.diagnostic_areas AS da
WHERE k.keyword_id = kda.keyword_id
  AND da.diagnostic_area_id = kda.diagnostic_area_id
  AND (
        (
            k.keyword IN ('цистит', 'пиелонефрит')
            AND da.name = 'Urinary tract infections'
        )
        OR
        (
            k.keyword = 'грибок ногтей'
            AND da.name = 'Superficial mycoses'
        )
  );

DO $$
DECLARE
    v_false_count bigint;
BEGIN
    SELECT COUNT(*)
    INTO v_false_count
    FROM reference.keyword_diagnostic_areas
    WHERE include_in_area_aggregate IS FALSE;

    IF v_false_count <> 3 THEN
        RAISE EXCEPTION
            'Expected exactly 3 mappings with include_in_area_aggregate = FALSE after migration, found %',
            v_false_count;
    END IF;
END
$$;

CREATE OR REPLACE VIEW analysis.search_demand_area_monthly AS
SELECT
    km.source,
    km.region_id,
    km.start_date,
    km.end_date,
    kda.diagnostic_area_id,
    SUM(km.query_count)::BIGINT AS query_count,
    COUNT(DISTINCT km.keyword_id)::BIGINT AS keyword_count
FROM staging.keywords_monthly AS km
JOIN reference.keyword_diagnostic_areas AS kda
    ON kda.keyword_id = km.keyword_id
WHERE kda.include_in_area_aggregate IS TRUE
GROUP BY
    km.source,
    km.region_id,
    km.start_date,
    km.end_date,
    kda.diagnostic_area_id;

COMMENT ON VIEW analysis.search_demand_area_monthly IS
'Search demand aggregated to diagnostic areas. Grain: source × region × period × diagnostic_area. Only keyword-area mappings with include_in_area_aggregate = TRUE contribute to the aggregate.';

COMMENT ON COLUMN analysis.search_demand_area_monthly.query_count IS
'Sum of query_count for keywords included in the diagnostic-area aggregate for the given source, region and period. Values across diagnostic areas are not additive because keyword mapping is many-to-many.';

COMMENT ON COLUMN analysis.search_demand_area_monthly.keyword_count IS
'Number of distinct keywords included in the diagnostic-area aggregate for the given source, region and period.';

COMMIT;
