-- 12_add_search_demand_keyword_growth_mv.sql
-- Creates a materialized mart for keyword-level Search Demand growth.
--
-- Intended Tableau use:
--   scatter plot of demand level vs growth for keywords within a
--   diagnostic area.
--
-- Grain:
--   source × country_id × diagnostic_area_id × keyword_id × period_type
--
-- period_type:
--   quarter  = latest 3 complete months vs preceding 3 complete months
--   year     = latest 12 complete months vs preceding 12 complete months
--   all_time = CAGR between the first 12-month average and the latest
--              12-month average
--
-- Country-level monthly keyword demand is calculated correctly:
--   region rows are summed within each country first,
--   then growth metrics are calculated from that country monthly series.
--
-- Only keyword_diagnostic_areas rows with
-- include_in_area_aggregate = TRUE are included.
--
-- growth_pct is stored as percentage change:
--   12.5 means +12.5%
--  -7.0 means -7.0%
--
-- Refresh after a newly completed month has been loaded and validated.

BEGIN;

DO $$
BEGIN
    IF to_regclass('staging.keywords_monthly') IS NULL THEN
        RAISE EXCEPTION
            'Expected table staging.keywords_monthly does not exist';
    END IF;

    IF to_regclass('reference.regions') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.regions does not exist';
    END IF;

    IF to_regclass('reference.countries') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.countries does not exist';
    END IF;

    IF to_regclass('reference.keywords') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.keywords does not exist';
    END IF;

    IF to_regclass('reference.keyword_diagnostic_areas') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.keyword_diagnostic_areas does not exist';
    END IF;

    IF to_regclass('reference.diagnostic_areas') IS NULL THEN
        RAISE EXCEPTION
            'Expected table reference.diagnostic_areas does not exist';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM staging.keywords_monthly
        WHERE start_date = date_trunc('month', start_date)::date
          AND end_date = (
              date_trunc('month', start_date)
              + interval '1 month'
              - interval '1 day'
          )::date
    ) THEN
        RAISE EXCEPTION
            'No complete monthly period found in staging.keywords_monthly';
    END IF;
END
$$;

DROP MATERIALIZED VIEW IF EXISTS mart.search_demand_keyword_growth;

CREATE MATERIALIZED VIEW mart.search_demand_keyword_growth AS
WITH country_keyword_monthly AS MATERIALIZED (
    SELECT
        km.source,
        r.country_id,
        kda.diagnostic_area_id,
        km.keyword_id,
        km.start_date,
        km.end_date,
        SUM(km.query_count)::numeric AS query_count
    FROM staging.keywords_monthly AS km
    JOIN reference.regions AS r
        ON r.region_id = km.region_id
    JOIN reference.keyword_diagnostic_areas AS kda
        ON kda.keyword_id = km.keyword_id
       AND kda.include_in_area_aggregate IS TRUE
    WHERE km.start_date = date_trunc('month', km.start_date)::date
      AND km.end_date = (
          date_trunc('month', km.start_date)
          + interval '1 month'
          - interval '1 day'
      )::date
    GROUP BY
        km.source,
        r.country_id,
        kda.diagnostic_area_id,
        km.keyword_id,
        km.start_date,
        km.end_date
),
latest_complete_month AS MATERIALIZED (
    SELECT
        source,
        country_id,
        MAX(start_date) AS as_of_month
    FROM country_keyword_monthly
    GROUP BY
        source,
        country_id
),
entity_bounds AS (
    SELECT
        source,
        country_id,
        diagnostic_area_id,
        keyword_id,
        MIN(start_date) AS first_month
    FROM country_keyword_monthly
    GROUP BY
        source,
        country_id,
        diagnostic_area_id,
        keyword_id
),
stats AS (
    SELECT
        s.source,
        s.country_id,
        s.diagnostic_area_id,
        s.keyword_id,
        b.first_month,
        lm.as_of_month,

        MAX(s.query_count) FILTER (
            WHERE s.start_date = lm.as_of_month
        ) AS latest_month_query_count,

        AVG(s.query_count) FILTER (
            WHERE s.start_date BETWEEN
                (lm.as_of_month - interval '2 months')::date
                AND lm.as_of_month
        ) AS current_3m_level,
        COUNT(*) FILTER (
            WHERE s.start_date BETWEEN
                (lm.as_of_month - interval '2 months')::date
                AND lm.as_of_month
        ) AS current_3m_count,

        AVG(s.query_count) FILTER (
            WHERE s.start_date BETWEEN
                (lm.as_of_month - interval '5 months')::date
                AND (lm.as_of_month - interval '3 months')::date
        ) AS previous_3m_level,
        COUNT(*) FILTER (
            WHERE s.start_date BETWEEN
                (lm.as_of_month - interval '5 months')::date
                AND (lm.as_of_month - interval '3 months')::date
        ) AS previous_3m_count,

        AVG(s.query_count) FILTER (
            WHERE s.start_date BETWEEN
                (lm.as_of_month - interval '11 months')::date
                AND lm.as_of_month
        ) AS current_12m_level,
        COUNT(*) FILTER (
            WHERE s.start_date BETWEEN
                (lm.as_of_month - interval '11 months')::date
                AND lm.as_of_month
        ) AS current_12m_count,

        AVG(s.query_count) FILTER (
            WHERE s.start_date BETWEEN
                (lm.as_of_month - interval '23 months')::date
                AND (lm.as_of_month - interval '12 months')::date
        ) AS previous_12m_level,
        COUNT(*) FILTER (
            WHERE s.start_date BETWEEN
                (lm.as_of_month - interval '23 months')::date
                AND (lm.as_of_month - interval '12 months')::date
        ) AS previous_12m_count,

        AVG(s.query_count) FILTER (
            WHERE s.start_date BETWEEN
                b.first_month
                AND (b.first_month + interval '11 months')::date
        ) AS first_12m_level,
        COUNT(*) FILTER (
            WHERE s.start_date BETWEEN
                b.first_month
                AND (b.first_month + interval '11 months')::date
        ) AS first_12m_count

    FROM country_keyword_monthly AS s
    JOIN entity_bounds AS b
        ON b.source = s.source
       AND b.country_id = s.country_id
       AND b.diagnostic_area_id = s.diagnostic_area_id
       AND b.keyword_id = s.keyword_id
    JOIN latest_complete_month AS lm
        ON lm.source = s.source
       AND lm.country_id = s.country_id
    GROUP BY
        s.source,
        s.country_id,
        s.diagnostic_area_id,
        s.keyword_id,
        b.first_month,
        lm.as_of_month
),
metrics AS (
    SELECT
        source,
        country_id,
        diagnostic_area_id,
        keyword_id,
        as_of_month,
        latest_month_query_count,
        'quarter'::text AS period_type,
        (as_of_month - interval '2 months')::date AS current_period_start,
        as_of_month AS current_period_end,
        (as_of_month - interval '5 months')::date AS previous_period_start,
        (as_of_month - interval '3 months')::date AS previous_period_end,
        current_3m_level AS current_level,
        previous_3m_level AS previous_level,
        current_3m_count AS current_month_count,
        previous_3m_count AS previous_month_count,
        CASE
            WHEN current_3m_count = 3
             AND previous_3m_count = 3
             AND previous_3m_level > 0
            THEN ROUND(
                ((current_3m_level / previous_3m_level) - 1) * 100,
                4
            )
            ELSE NULL::numeric
        END AS growth_pct
    FROM stats

    UNION ALL

    SELECT
        source,
        country_id,
        diagnostic_area_id,
        keyword_id,
        as_of_month,
        latest_month_query_count,
        'year'::text AS period_type,
        (as_of_month - interval '11 months')::date AS current_period_start,
        as_of_month AS current_period_end,
        (as_of_month - interval '23 months')::date AS previous_period_start,
        (as_of_month - interval '12 months')::date AS previous_period_end,
        current_12m_level AS current_level,
        previous_12m_level AS previous_level,
        current_12m_count AS current_month_count,
        previous_12m_count AS previous_month_count,
        CASE
            WHEN current_12m_count = 12
             AND previous_12m_count = 12
             AND previous_12m_level > 0
            THEN ROUND(
                ((current_12m_level / previous_12m_level) - 1) * 100,
                4
            )
            ELSE NULL::numeric
        END AS growth_pct
    FROM stats

    UNION ALL

    SELECT
        source,
        country_id,
        diagnostic_area_id,
        keyword_id,
        as_of_month,
        latest_month_query_count,
        'all_time'::text AS period_type,
        (as_of_month - interval '11 months')::date AS current_period_start,
        as_of_month AS current_period_end,
        first_month AS previous_period_start,
        (first_month + interval '11 months')::date AS previous_period_end,
        current_12m_level AS current_level,
        first_12m_level AS previous_level,
        current_12m_count AS current_month_count,
        first_12m_count AS previous_month_count,
        CASE
            WHEN current_12m_count = 12
             AND first_12m_count = 12
             AND first_12m_level > 0
             AND (
                    (
                        EXTRACT(YEAR FROM (as_of_month - interval '11 months'))::int
                        - EXTRACT(YEAR FROM first_month)::int
                    ) * 12
                    +
                    (
                        EXTRACT(MONTH FROM (as_of_month - interval '11 months'))::int
                        - EXTRACT(MONTH FROM first_month)::int
                    )
                 ) >= 12
            THEN ROUND(
                (
                    POWER(
                        current_12m_level / first_12m_level,
                        12.0 / (
                            (
                                EXTRACT(YEAR FROM (as_of_month - interval '11 months'))::int
                                - EXTRACT(YEAR FROM first_month)::int
                            ) * 12
                            +
                            (
                                EXTRACT(MONTH FROM (as_of_month - interval '11 months'))::int
                                - EXTRACT(MONTH FROM first_month)::int
                            )
                        )
                    ) - 1
                ) * 100,
                4
            )
            ELSE NULL::numeric
        END AS growth_pct
    FROM stats
)
SELECT
    m.source,
    m.country_id,
    c.country_name,
    m.diagnostic_area_id,
    da.name_ru AS diagnostic_area_name_ru,
    m.keyword_id,
    k.keyword,
    m.as_of_month,
    m.period_type,
    m.latest_month_query_count,
    m.current_period_start,
    m.current_period_end,
    m.previous_period_start,
    m.previous_period_end,
    m.current_level,
    m.previous_level,
    m.current_month_count,
    m.previous_month_count,
    m.growth_pct
FROM metrics AS m
JOIN reference.countries AS c
    ON c.country_id = m.country_id
JOIN reference.diagnostic_areas AS da
    ON da.diagnostic_area_id = m.diagnostic_area_id
JOIN reference.keywords AS k
    ON k.keyword_id = m.keyword_id
WITH DATA;

CREATE UNIQUE INDEX ux_search_demand_keyword_growth_grain
ON mart.search_demand_keyword_growth (
    source,
    country_id,
    diagnostic_area_id,
    period_type,
    keyword_id
);

COMMENT ON MATERIALIZED VIEW mart.search_demand_keyword_growth IS
'Precomputed country-level keyword Search Demand growth metrics for Tableau scatter plots. Grain: source × country × diagnostic_area × keyword × period_type. Regional rows are summed to country monthly keyword totals before growth is calculated. Refresh after a new complete month is loaded and validated.';

COMMENT ON COLUMN mart.search_demand_keyword_growth.latest_month_query_count IS
'Country-level query_count for the latest complete month. Useful as an alternative scatter X-axis or tooltip measure.';

COMMENT ON COLUMN mart.search_demand_keyword_growth.current_level IS
'Average monthly country-level keyword query_count in the current comparison window. Recommended default scatter X-axis because it uses the same time horizon as growth_pct. For all_time: latest 12-month average.';

COMMENT ON COLUMN mart.search_demand_keyword_growth.previous_level IS
'Average monthly country-level keyword query_count in the baseline comparison window. For all_time: first 12-month average.';

COMMENT ON COLUMN mart.search_demand_keyword_growth.current_month_count IS
'Number of monthly observations in the current window. growth_pct is NULL when the expected complete window is unavailable.';

COMMENT ON COLUMN mart.search_demand_keyword_growth.previous_month_count IS
'Number of monthly observations in the baseline window. growth_pct is NULL when the expected complete window is unavailable.';

COMMENT ON COLUMN mart.search_demand_keyword_growth.growth_pct IS
'Growth as a percentage change. Example: 12.5 means +12.5 percent. NULL when required comparison windows are incomplete or the baseline level is zero/non-positive.';

COMMIT;
