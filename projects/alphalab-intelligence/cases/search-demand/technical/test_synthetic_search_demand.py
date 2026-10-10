from __future__ import annotations

import html
import importlib.util
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from alphalab.synthetic import search_demand as search_demand_module
from alphalab.synthetic.search_demand import (
    DEFAULT_REGION_PROFILES_PATH,
    DEFAULT_WORKBOOK_PATH,
    EXPECTED_AREA_NAMES_RU,
    EXPECTED_REGION_COUNT,
    DatabaseState,
    DiagnosticAreaReference,
    KeywordAnchor,
    KeywordReference,
    RegionProfile,
    RegionReference,
    SyntheticGroup,
    ResolvedSyntheticRow,
    SearchDemandDatabaseError,
    SearchDemandSourceError,
    WorkbookData,
    canonical_key,
    calculate_regional_source_metrics,
    classify_fixture_rows,
    generate_synthetic_dataset,
    google_keyword_region_effect,
    google_region_preference,
    largest_remainder,
    load_region_profiles,
    load_workbook,
    plan_reference_changes,
    shift_year,
    stable_uniform,
    validate_region_profiles,
)


def _inline_cell(reference: str, value: str) -> str:
    return (
        f'<c r="{reference}" t="inlineStr"><is><t>{html.escape(value)}</t></is></c>'
    )


def _numeric_cell(reference: str, value: int) -> str:
    return f'<c r="{reference}"><v>{value}</v></c>'


def _write_workbook(
    path: Path,
    *,
    months: tuple[date, ...] = (date(2020, 1, 1), date(2020, 3, 1)),
    include_ignored_sheet: bool = True,
    conflicting_shared_keyword: bool = False,
) -> None:
    sheet_specs: list[tuple[str, str, tuple[int, ...]]] = []
    for index, area in enumerate(EXPECTED_AREA_NAMES_RU, start=1):
        keyword = "общий запрос" if index <= 2 else f"запрос {index}"
        counts = tuple(100 + month_index for month_index, _month in enumerate(months))
        if conflicting_shared_keyword and index == 2:
            counts = tuple(value + 1 for value in counts)
        sheet_specs.append((area.lower(), keyword, counts))
    if include_ignored_sheet:
        sheet_specs.append(("Лист8", "игнорировать", tuple(1 for _ in months)))

    workbook_sheets = []
    relationships = []
    worksheets: dict[str, str] = {}
    for index, (sheet_name, keyword, counts) in enumerate(sheet_specs, start=1):
        relationship_id = f"rId{index}"
        workbook_sheets.append(
            f'<sheet name="{html.escape(sheet_name)}" sheetId="{index}" '
            f'r:id="{relationship_id}"/>'
        )
        relationships.append(
            f'<Relationship Id="{relationship_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f' relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        )
        rows = [
            f'<row r="1">{_inline_cell("A1", "Период")}'
            f'{_inline_cell("B1", keyword)}</row>'
        ]
        for row_number, (month, count) in enumerate(zip(months, counts, strict=True), start=2):
            serial = (month - date(1899, 12, 30)).days
            rows.append(
                f'<row r="{row_number}">{_numeric_cell(f"A{row_number}", serial)}'
                f'{_numeric_cell(f"B{row_number}", count)}</row>'
            )
        worksheets[f"xl/worksheets/sheet{index}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheetData>'
            + "".join(rows)
            + "</sheetData></worksheet>"
        )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships"><workbookPr/><sheets>'
        + "".join(workbook_sheets)
        + "</sheets></workbook>"
    )
    relationships_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">'
        + "".join(relationships).replace("  relationships", "relationships")
        + "</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships_xml)
        for name, content in worksheets.items():
            archive.writestr(name, content)


def _small_workbook() -> WorkbookData:
    months = (date(2020, 1, 1), date(2020, 3, 1))
    keyword_values = (("keyword a", 1200), ("keyword b", 750))
    anchors = tuple(
        KeywordAnchor(
            keyword_key=canonical_key(keyword),
            keyword=keyword,
            month=month,
            query_count=base_count + month_index * 100,
        )
        for keyword, base_count in keyword_values
        for month_index, month in enumerate(months)
    )
    return WorkbookData(
        anchors=anchors,
        keyword_area_mappings=tuple(
            (canonical_key(keyword), "Area A") for keyword, _count in keyword_values
        ),
        months=months,
        areas=("Area A",),
    )


def _small_regions() -> tuple[RegionReference, ...]:
    return (
        RegionReference(30, "Region C", 800, date(2025, 1, 1)),
        RegionReference(10, "Region A", 1000, date(2025, 1, 1)),
        RegionReference(20, "Region B", 1200, date(2025, 1, 1)),
    )


def _small_profiles() -> tuple[RegionProfile, ...]:
    return (
        RegionProfile("Region B", "Area A", 1.30),
        RegionProfile("Region C", "Area A", 0.75),
        RegionProfile("Region A", "Area A", 1.05),
    )


def test_real_input_files_parse_programmatically() -> None:
    if not DEFAULT_WORKBOOK_PATH.is_file() or not DEFAULT_REGION_PROFILES_PATH.is_file():
        pytest.skip("repository-local raw fixture inputs are not present")

    workbook = load_workbook(DEFAULT_WORKBOOK_PATH)
    profiles = load_region_profiles(DEFAULT_REGION_PROFILES_PATH)

    assert workbook.months[0] == date(2020, 1, 1)
    assert workbook.months[-1] == date(2026, 8, 1)
    assert len(workbook.months) == 80
    assert len(workbook.areas) == 7
    assert len(workbook.anchors) == workbook.keyword_count * len(workbook.months)
    assert len({profile.region_name for profile in profiles}) == EXPECTED_REGION_COUNT
    assert len(profiles) == 83 * 7


def test_workbook_ignores_list8_preserves_actual_months_and_many_to_many(
    tmp_path: Path,
) -> None:
    workbook_path = tmp_path / "fixture.xlsx"
    _write_workbook(workbook_path)

    workbook = load_workbook(workbook_path)

    assert workbook.months == (date(2020, 1, 1), date(2020, 3, 1))
    shared_key = canonical_key("общий запрос")
    assert workbook.keyword_count == 6
    assert sum(
        keyword_key == shared_key
        for keyword_key, _area in workbook.keyword_area_mappings
    ) == 2
    assert all(anchor.keyword != "игнорировать" for anchor in workbook.anchors)


def test_workbook_rejects_conflicting_duplicate_keyword_month_anchor(
    tmp_path: Path,
) -> None:
    workbook_path = tmp_path / "conflict.xlsx"
    _write_workbook(workbook_path, conflicting_shared_keyword=True)

    with pytest.raises(SearchDemandSourceError, match="Conflicting duplicate"):
        load_workbook(workbook_path)


def test_shift_year_is_exactly_minus_100() -> None:
    assert shift_year(date(2020, 2, 1), -100) == date(1920, 2, 1)


def test_stable_uniform_is_repeatable_and_component_sensitive() -> None:
    first = stable_uniform("component", "keyword", "region", "2020-01")
    second = stable_uniform("component", "keyword", "region", "2020-01")
    changed = stable_uniform("component", "keyword", "other region", "2020-01")

    assert first == second
    assert 0 <= first < 1
    assert first != changed


def test_google_region_preference_is_deterministic_and_region_specific() -> None:
    first = google_region_preference(10)
    repeated = google_region_preference(10)
    other_region = google_region_preference(20)

    assert first == repeated
    assert first != other_region
    assert 0.60 <= first <= 1.60
    assert 0.60 <= other_region <= 1.60


def test_google_keyword_region_effect_is_deterministic_and_pair_specific() -> None:
    first = google_keyword_region_effect("keyword a", 10)
    repeated = google_keyword_region_effect("keyword a", 10)
    other_keyword = google_keyword_region_effect("keyword b", 10)
    other_region = google_keyword_region_effect("keyword a", 20)

    assert first == repeated
    assert first != other_keyword
    assert first != other_region
    assert 0.84 <= first <= 1.18


def test_largest_remainder_reconciles_exactly_with_stable_tie_break() -> None:
    allocation = largest_remainder(10, [(2, 1.0), (1, 1.0), (3, 1.0)])

    assert allocation == {2: 3, 1: 4, 3: 3}
    assert sum(allocation.values()) == 10


def test_generation_is_reproducible_and_input_order_independent() -> None:
    workbook = _small_workbook()

    first = generate_synthetic_dataset(
        workbook,
        _small_profiles(),
        _small_regions(),
    )
    reordered_workbook = replace(
        workbook,
        anchors=tuple(reversed(workbook.anchors)),
        keyword_area_mappings=tuple(reversed(workbook.keyword_area_mappings)),
    )
    second = generate_synthetic_dataset(
        reordered_workbook,
        tuple(reversed(_small_profiles())),
        tuple(reversed(_small_regions())),
    )

    assert first.groups == second.groups
    assert list(first.iter_rows()) == list(second.iter_rows())
    assert first.regional_lift_corr_median == second.regional_lift_corr_median
    assert first.regional_lift_corr_p10 == second.regional_lift_corr_p10
    assert first.regional_lift_corr_p90 == second.regional_lift_corr_p90
    assert first.leader_same_share == second.leader_same_share
    assert first.leader_different_share == second.leader_different_share


def test_google_source_effects_do_not_change_yandex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook = _small_workbook()
    baseline = generate_synthetic_dataset(
        workbook,
        _small_profiles(),
        _small_regions(),
    )
    monkeypatch.setattr(
        search_demand_module,
        "google_region_preference",
        lambda _region_id, *, seed: 1.0,
    )
    monkeypatch.setattr(
        search_demand_module,
        "google_keyword_region_effect",
        lambda _keyword, _region_id, *, seed: 1.0,
    )
    neutral_google_effects = generate_synthetic_dataset(
        workbook,
        _small_profiles(),
        _small_regions(),
    )

    assert [group.yandex_counts for group in baseline.groups] == [
        group.yandex_counts for group in neutral_google_effects.groups
    ]
    assert any(
        baseline_group.google_counts != neutral_group.google_counts
        for baseline_group, neutral_group in zip(
            baseline.groups,
            neutral_google_effects.groups,
            strict=True,
        )
    )


def test_generation_reconciles_sources_and_produces_distinct_correlated_google() -> None:
    workbook = _small_workbook()
    dataset = generate_synthetic_dataset(
        workbook,
        _small_profiles(),
        _small_regions(),
    )

    assert dataset.row_count == 2 * 2 * 3 * 2
    assert dataset.google_yandex_correlation > 0.5
    assert any(group.google_counts != group.yandex_counts for group in dataset.groups)
    rows = list(dataset.iter_rows())
    grains = {
        (row.source, row.keyword_key, row.region_id, row.start_date, row.end_date)
        for row in rows
    }
    assert len(grains) == len(rows) == dataset.row_count
    for group in dataset.groups:
        anchor = next(
            item
            for item in workbook.anchors
            if item.keyword_key == group.keyword_key and item.month == group.real_month
        )
        assert sum(group.yandex_counts) == anchor.query_count
        assert sum(group.google_counts) == group.google_total
        assert all(isinstance(value, int) and value >= 0 for value in group.yandex_counts)
        assert all(isinstance(value, int) and value >= 0 for value in group.google_counts)
        assert group.start_date.year == group.real_month.year - 100
        assert group.start_date.day == 1


def test_validate_region_profiles_requires_complete_unique_matrix() -> None:
    profiles = _small_profiles()
    validate_region_profiles(
        profiles,
        expected_region_count=3,
        expected_areas=("Area A",),
    )

    with pytest.raises(SearchDemandSourceError, match="unique region-area pairs"):
        validate_region_profiles(
            (*profiles, profiles[0]),
            expected_region_count=3,
            expected_areas=("Area A",),
        )


def test_regional_lift_qc_and_leader_metrics_are_calculated_per_group() -> None:
    regions = (
        RegionReference(1, "A", 100, date(2025, 1, 1)),
        RegionReference(2, "B", 100, date(2025, 1, 1)),
        RegionReference(3, "C", 100, date(2025, 1, 1)),
    )
    group = SyntheticGroup(
        keyword_key="keyword",
        keyword="keyword",
        real_month=date(2020, 1, 1),
        start_date=date(1920, 1, 1),
        end_date=date(1920, 1, 31),
        yandex_total=60,
        google_total=60,
        yandex_counts=(10, 20, 30),
        google_counts=(30, 20, 10),
    )

    metrics = calculate_regional_source_metrics((group,), regions)

    assert metrics.regional_lift_corr_median == pytest.approx(-1.0)
    assert metrics.regional_lift_corr_p10 == pytest.approx(-1.0)
    assert metrics.regional_lift_corr_p90 == pytest.approx(-1.0)
    assert metrics.leader_same_share == 0.0
    assert metrics.leader_different_share == 1.0
    assert metrics.evaluated_groups == 1


def test_plan_reference_changes_keeps_existing_mapping_and_adds_missing_ones() -> None:
    keyword_key = canonical_key("shared keyword")
    workbook = WorkbookData(
        anchors=(
            KeywordAnchor(keyword_key, "shared keyword", date(2020, 1, 1), 100),
        ),
        keyword_area_mappings=((keyword_key, "Area A"), (keyword_key, "Area B")),
        months=(date(2020, 1, 1),),
        areas=("Area A", "Area B"),
    )
    state = DatabaseState(
        regions=(),
        diagnostic_areas=(
            DiagnosticAreaReference(1, "Area A"),
            DiagnosticAreaReference(2, "Area B"),
        ),
        keywords=(KeywordReference(10, "shared keyword"),),
        keyword_area_mappings=frozenset({(10, 1)}),
    )

    plan = plan_reference_changes(workbook, state)

    assert plan.missing_keywords == ()
    assert plan.missing_mappings == ((keyword_key, 2),)


def test_exact_noop_and_conflict_reconciliation() -> None:
    row = ResolvedSyntheticRow(
        "yandex",
        1,
        2,
        date(1920, 1, 1),
        date(1920, 1, 31),
        5,
    )

    assert classify_fixture_rows([row], []) == "insert"
    assert classify_fixture_rows([row], [row]) == "noop"
    with pytest.raises(SearchDemandDatabaseError, match="partial.*conflicting"):
        classify_fixture_rows([row], [replace(row, query_count=6)])


def test_cli_requires_explicit_apply_flag() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / (
        "03_generate_synthetic_search_demand.py"
    )
    spec = importlib.util.spec_from_file_location("search_demand_cli", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._parse_args([]).apply is False
    assert module._parse_args(["--apply"]).apply is True
