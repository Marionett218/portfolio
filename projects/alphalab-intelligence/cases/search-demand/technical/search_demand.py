"""Build and safely insert a deterministic Search Demand DEV fixture.

The generator intentionally keeps source parsing, deterministic allocation, database
planning, and database writes separate.  Merely importing this module never connects
to PostgreSQL, and database writes are possible only through ``run_fixture(...,
apply=True)``.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import math
import posixpath
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import islice
from pathlib import Path
from typing import Iterable, Iterator, Literal, Mapping, NoReturn, Sequence
from xml.etree import ElementTree

from psycopg import Connection

from alphalab.config import EXPECTED_DB_USER, PROJECT_ROOT


EXPECTED_DATABASE_NAME = "alphalabs"
EXPECTED_REGION_COUNT = 83
EXPECTED_AREA_COUNT = 7
GLOBAL_SEED = 20260925
SOURCES = ("google", "yandex")
GOOGLE_REGION_LOG_AMPLITUDE = math.log(1.60)
GOOGLE_KEYWORD_REGION_LOG_AMPLITUDE = math.log(1.18)
REGIONAL_LIFT_CORRELATION_MIN = 0.50
REGIONAL_LIFT_CORRELATION_MAX = 0.80
DEFAULT_WORKBOOK_PATH = (
    PROJECT_ROOT
    / "data"
    / "fixtures"
    / "search_demand"
    / "wordstat_manual_2020-2026.xlsx"
)
DEFAULT_REGION_PROFILES_PATH = (
    PROJECT_ROOT
    / "data"
    / "fixtures"
    / "search_demand"
    / "synthetic_region_profiles.csv"
)

EXPECTED_AREA_NAMES_RU = (
    "Урогенитальные инфекции",
    "Гельминтозы",
    "Протозойные инфекции",
    "Микробиота кишечника",
    "Инфекции мочевыводящих путей",
    "Поверхностные микозы",
    "Ветеринарная диагностика",
)

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REFERENCE = re.compile(r"([A-Z]+)([1-9][0-9]*)\Z")
_REQUIRED_PROFILE_COLUMNS = (
    "region_name",
    "diagnostic_area_name_ru",
    "regional_affinity",
)


class SearchDemandSourceError(ValueError):
    """Raised when a fixture input violates its declared contract."""


class SearchDemandValidationError(ValueError):
    """Raised when generated values fail deterministic QC."""


class SearchDemandDatabaseError(RuntimeError):
    """Raised when database state is unsafe, incomplete, or conflicting."""


@dataclass(frozen=True, slots=True)
class KeywordAnchor:
    keyword_key: str
    keyword: str
    month: date
    query_count: int


@dataclass(frozen=True, slots=True)
class WorkbookData:
    anchors: tuple[KeywordAnchor, ...]
    keyword_area_mappings: tuple[tuple[str, str], ...]
    months: tuple[date, ...]
    areas: tuple[str, ...]

    @property
    def keyword_by_key(self) -> dict[str, str]:
        return {anchor.keyword_key: anchor.keyword for anchor in self.anchors}

    @property
    def keyword_count(self) -> int:
        return len(self.keyword_by_key)


@dataclass(frozen=True, slots=True)
class RegionProfile:
    region_name: str
    diagnostic_area_name_ru: str
    regional_affinity: float


@dataclass(frozen=True, slots=True)
class RegionReference:
    region_id: int
    region_name: str
    population: int
    population_as_of_date: date


@dataclass(frozen=True, slots=True)
class DiagnosticAreaReference:
    diagnostic_area_id: int
    name_ru: str


@dataclass(frozen=True, slots=True)
class KeywordReference:
    keyword_id: int
    keyword: str


@dataclass(frozen=True, slots=True)
class DatabaseState:
    regions: tuple[RegionReference, ...]
    diagnostic_areas: tuple[DiagnosticAreaReference, ...]
    keywords: tuple[KeywordReference, ...]
    keyword_area_mappings: frozenset[tuple[int, int]]


@dataclass(frozen=True, slots=True)
class PlannedKeyword:
    keyword_key: str
    keyword: str
    keyword_id: int | None


@dataclass(frozen=True, slots=True)
class ReferencePlan:
    keywords: tuple[PlannedKeyword, ...]
    missing_mappings: tuple[tuple[str, int], ...]

    @property
    def missing_keywords(self) -> tuple[PlannedKeyword, ...]:
        return tuple(item for item in self.keywords if item.keyword_id is None)

    @property
    def keyword_id_by_key(self) -> dict[str, int]:
        if self.missing_keywords:
            raise SearchDemandDatabaseError(
                "Cannot resolve fixture rows before all missing keywords are inserted"
            )
        return {
            item.keyword_key: int(item.keyword_id)
            for item in self.keywords
            if item.keyword_id is not None
        }


@dataclass(frozen=True, slots=True)
class SyntheticGroup:
    keyword_key: str
    keyword: str
    real_month: date
    start_date: date
    end_date: date
    yandex_total: int
    google_total: int
    yandex_counts: tuple[int, ...]
    google_counts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SyntheticRow:
    source: str
    keyword_key: str
    keyword: str
    region_id: int
    start_date: date
    end_date: date
    query_count: int


@dataclass(frozen=True, slots=True)
class ResolvedSyntheticRow:
    source: str
    keyword_id: int
    region_id: int
    start_date: date
    end_date: date
    query_count: int


@dataclass(frozen=True, slots=True)
class RegionalSourceMetrics:
    regional_lift_corr_median: float
    regional_lift_corr_p10: float
    regional_lift_corr_p90: float
    leader_same_share: float
    leader_different_share: float
    evaluated_groups: int


@dataclass(frozen=True, slots=True)
class SyntheticDataset:
    regions: tuple[RegionReference, ...]
    groups: tuple[SyntheticGroup, ...]
    keyword_count: int
    area_count: int
    google_yandex_correlation: float
    regional_lift_corr_median: float
    regional_lift_corr_p10: float
    regional_lift_corr_p90: float
    leader_same_share: float
    leader_different_share: float

    @property
    def row_count(self) -> int:
        return len(self.groups) * len(self.regions) * len(SOURCES)

    @property
    def start_date(self) -> date:
        return min(group.start_date for group in self.groups)

    @property
    def end_date(self) -> date:
        return max(group.end_date for group in self.groups)

    def iter_rows(self) -> Iterator[SyntheticRow]:
        """Yield rows in a stable order independent of source input ordering."""
        groups_by_keyword: dict[str, list[SyntheticGroup]] = defaultdict(list)
        for group in self.groups:
            groups_by_keyword[group.keyword_key].append(group)

        for source in sorted(SOURCES):
            for keyword_key in sorted(groups_by_keyword):
                groups = sorted(
                    groups_by_keyword[keyword_key], key=lambda item: item.start_date
                )
                for region_index, region in enumerate(self.regions):
                    for group in groups:
                        counts = (
                            group.google_counts
                            if source == "google"
                            else group.yandex_counts
                        )
                        yield SyntheticRow(
                            source=source,
                            keyword_key=keyword_key,
                            keyword=group.keyword,
                            region_id=region.region_id,
                            start_date=group.start_date,
                            end_date=group.end_date,
                            query_count=counts[region_index],
                        )

    def iter_resolved_rows(
        self, keyword_id_by_key: Mapping[str, int]
    ) -> Iterator[ResolvedSyntheticRow]:
        """Yield rows ordered like the database reconciliation query."""
        missing = sorted(
            {group.keyword_key for group in self.groups}.difference(keyword_id_by_key)
        )
        if missing:
            raise SearchDemandDatabaseError(
                f"Missing keyword IDs for generated rows: {missing}"
            )

        groups_by_keyword: dict[str, list[SyntheticGroup]] = defaultdict(list)
        for group in self.groups:
            groups_by_keyword[group.keyword_key].append(group)

        keyword_keys = sorted(
            groups_by_keyword,
            key=lambda key: (int(keyword_id_by_key[key]), key),
        )
        for source in sorted(SOURCES):
            for keyword_key in keyword_keys:
                keyword_id = int(keyword_id_by_key[keyword_key])
                groups = sorted(
                    groups_by_keyword[keyword_key], key=lambda item: item.start_date
                )
                for region_index, region in enumerate(self.regions):
                    for group in groups:
                        counts = (
                            group.google_counts
                            if source == "google"
                            else group.yandex_counts
                        )
                        yield ResolvedSyntheticRow(
                            source=source,
                            keyword_id=keyword_id,
                            region_id=region.region_id,
                            start_date=group.start_date,
                            end_date=group.end_date,
                            query_count=counts[region_index],
                        )


@dataclass(frozen=True, slots=True)
class FixtureRunSummary:
    mode: Literal["dry-run", "apply"]
    action: Literal["insert", "noop", "reference_insert"]
    synthetic_start_date: date
    synthetic_end_date: date
    sources: tuple[str, ...]
    regions: int
    diagnostic_areas: int
    keywords: int
    generated_rows: int
    inserted_rows: int
    inserted_keywords: int
    inserted_keyword_area_mappings: int
    google_yandex_correlation: float
    regional_lift_corr_median: float
    regional_lift_corr_p10: float
    regional_lift_corr_p90: float
    leader_same_share: float
    leader_different_share: float


def _display_text(value: str, *, field: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized:
        raise SearchDemandSourceError(f"{field} must not be blank")
    return normalized


def canonical_key(value: str, *, field: str = "text") -> str:
    """Return a stable comparison key while retaining a separate display value."""
    return _display_text(value, field=field).casefold()


_EXPECTED_AREA_BY_KEY = {
    canonical_key(name, field="diagnostic area"): name
    for name in EXPECTED_AREA_NAMES_RU
}


def _column_index(cell_reference: str) -> int:
    match = _CELL_REFERENCE.fullmatch(cell_reference)
    if match is None:
        raise SearchDemandSourceError(
            f"Invalid XLSX cell reference: {cell_reference!r}"
        )
    result = 0
    for character in match.group(1):
        result = result * 26 + (ord(character) - ord("A") + 1)
    return result - 1


def _shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    try:
        document = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return ()
    except ElementTree.ParseError as exc:
        raise SearchDemandSourceError("XLSX sharedStrings.xml is invalid") from exc
    return tuple(
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in document.findall(f"{{{_MAIN_NS}}}si")
    )


def _cell_value(cell: ElementTree.Element, shared: Sequence[str]) -> str | None:
    reference = cell.attrib.get("r", "<unknown>")
    if cell.find(f"{{{_MAIN_NS}}}f") is not None:
        raise SearchDemandSourceError(
            f"Formula cells are not allowed in the source workbook: {reference}"
        )
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{_MAIN_NS}}}is")
        if inline is None:
            return None
        return "".join(node.text or "" for node in inline.iter(f"{{{_MAIN_NS}}}t"))

    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return None
    raw_value = value_node.text
    if cell_type == "s":
        try:
            return shared[int(raw_value)]
        except (ValueError, IndexError) as exc:
            raise SearchDemandSourceError(
                f"Invalid shared-string index at XLSX cell {reference}"
            ) from exc
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return raw_value


def _worksheet_rows(
    archive: zipfile.ZipFile,
    target: str,
    shared: Sequence[str],
) -> list[tuple[int, dict[int, str]]]:
    normalized_target = target.lstrip("/")
    if not normalized_target.startswith("xl/"):
        normalized_target = posixpath.normpath(posixpath.join("xl", normalized_target))
    if not normalized_target.startswith("xl/") or ".." in normalized_target.split("/"):
        raise SearchDemandSourceError(f"Unsafe XLSX worksheet target: {target!r}")
    try:
        document = ElementTree.fromstring(archive.read(normalized_target))
    except (KeyError, ElementTree.ParseError) as exc:
        raise SearchDemandSourceError(
            f"Cannot read XLSX worksheet part {normalized_target!r}"
        ) from exc

    result: list[tuple[int, dict[int, str]]] = []
    for row in document.findall(
        f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row"
    ):
        row_number = int(row.attrib.get("r", len(result) + 1))
        values: dict[int, str] = {}
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            reference = cell.attrib.get("r")
            if reference is None:
                raise SearchDemandSourceError(
                    f"XLSX row {row_number} contains a cell without a reference"
                )
            value = _cell_value(cell, shared)
            if value is not None and value != "":
                values[_column_index(reference)] = value
        if values:
            result.append((row_number, values))
    return result


def _parse_excel_month(raw_value: str, *, date_1904: bool, location: str) -> date:
    try:
        serial = Decimal(raw_value)
    except InvalidOperation:
        try:
            parsed = datetime.fromisoformat(raw_value).date()
        except ValueError:
            try:
                parsed = date.fromisoformat(raw_value)
            except ValueError as exc:
                raise SearchDemandSourceError(
                    f"{location} has an invalid month value: {raw_value!r}"
                ) from exc
    else:
        if not serial.is_finite() or serial < 0:
            raise SearchDemandSourceError(
                f"{location} has an invalid Excel date serial: {raw_value!r}"
            )
        whole_days = int(serial // 1)
        base = date(1904, 1, 1) if date_1904 else date(1899, 12, 30)
        parsed = base + timedelta(days=whole_days)
    if parsed.day != 1:
        raise SearchDemandSourceError(
            f"{location} must be the first day of a month, got {parsed.isoformat()}"
        )
    return parsed


def _parse_query_count(raw_value: str, *, location: str) -> int:
    try:
        number = Decimal(raw_value)
    except InvalidOperation as exc:
        raise SearchDemandSourceError(
            f"{location} query_count is not numeric: {raw_value!r}"
        ) from exc
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise SearchDemandSourceError(
            f"{location} query_count must be an integer >= 0, got {raw_value!r}"
        )
    return int(number)


def load_workbook(path: Path = DEFAULT_WORKBOOK_PATH) -> WorkbookData:
    """Parse the seven working sheets of the real Wordstat XLSX source."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SearchDemandSourceError(f"Cannot read XLSX workbook {path}: {exc}") from exc

    with archive:
        try:
            workbook_document = ElementTree.fromstring(
                archive.read("xl/workbook.xml")
            )
            relationships_document = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
        except (KeyError, ElementTree.ParseError) as exc:
            raise SearchDemandSourceError(
                f"XLSX workbook structure is invalid: {path}"
            ) from exc

        workbook_properties = workbook_document.find(
            f"{{{_MAIN_NS}}}workbookPr"
        )
        date_1904 = bool(
            workbook_properties is not None
            and workbook_properties.attrib.get("date1904", "0").lower()
            in {"1", "true"}
        )
        targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships_document.findall(
                f"{{{_PACKAGE_REL_NS}}}Relationship"
            )
        }
        shared = _shared_strings(archive)

        area_timelines: dict[str, tuple[date, ...]] = {}
        keyword_variants: dict[str, set[str]] = defaultdict(set)
        anchor_values: dict[tuple[str, date], int] = {}
        mappings: set[tuple[str, str]] = set()

        for sheet in workbook_document.findall(
            f".//{{{_MAIN_NS}}}sheet"
        ):
            sheet_name = sheet.attrib.get("name", "")
            sheet_key = canonical_key(sheet_name, field="worksheet name")
            if sheet_key == canonical_key("Лист8", field="ignored worksheet"):
                continue
            if sheet_key not in _EXPECTED_AREA_BY_KEY:
                raise SearchDemandSourceError(
                    f"Unexpected working worksheet: {sheet_name!r}"
                )
            area_name = _EXPECTED_AREA_BY_KEY[sheet_key]
            if area_name in area_timelines:
                raise SearchDemandSourceError(
                    f"Duplicate worksheet for diagnostic area {area_name!r}"
                )

            relationship_id = sheet.attrib.get(f"{{{_OFFICE_REL_NS}}}id")
            if relationship_id is None or relationship_id not in targets:
                raise SearchDemandSourceError(
                    f"Worksheet {sheet_name!r} has no valid XLSX relationship"
                )
            rows = _worksheet_rows(archive, targets[relationship_id], shared)
            if len(rows) < 2:
                raise SearchDemandSourceError(
                    f"Worksheet {sheet_name!r} must contain a header and data rows"
                )

            header_row_number, header = rows[0]
            period_header = header.get(0)
            if period_header is None or canonical_key(
                period_header, field="period header"
            ) != canonical_key("Период", field="expected period header"):
                raise SearchDemandSourceError(
                    f"Worksheet {sheet_name!r} cell A{header_row_number} must be 'Период'"
                )
            keyword_columns: dict[int, tuple[str, str]] = {}
            seen_sheet_keywords: set[str] = set()
            for column_index, raw_keyword in sorted(header.items()):
                if column_index == 0:
                    continue
                keyword = _display_text(
                    raw_keyword,
                    field=f"worksheet {sheet_name!r} keyword header",
                )
                keyword_key = canonical_key(keyword, field="keyword")
                if keyword_key in seen_sheet_keywords:
                    raise SearchDemandSourceError(
                        f"Worksheet {sheet_name!r} contains duplicate keyword {keyword!r}"
                    )
                seen_sheet_keywords.add(keyword_key)
                keyword_columns[column_index] = (keyword_key, keyword)
                keyword_variants[keyword_key].add(keyword)
                mappings.add((keyword_key, area_name))
            if not keyword_columns:
                raise SearchDemandSourceError(
                    f"Worksheet {sheet_name!r} contains no keyword columns"
                )

            months: list[date] = []
            for row_number, row in rows[1:]:
                unexpected_columns = sorted(
                    column
                    for column in row
                    if column != 0 and column not in keyword_columns
                )
                if unexpected_columns:
                    raise SearchDemandSourceError(
                        f"Worksheet {sheet_name!r} row {row_number} contains data "
                        f"under blank header columns: {unexpected_columns}"
                    )
                raw_month = row.get(0)
                if raw_month is None:
                    raise SearchDemandSourceError(
                        f"Worksheet {sheet_name!r} row {row_number} has no month"
                    )
                month = _parse_excel_month(
                    raw_month,
                    date_1904=date_1904,
                    location=f"worksheet {sheet_name!r} A{row_number}",
                )
                months.append(month)
                for column_index, (keyword_key, _keyword) in keyword_columns.items():
                    raw_count = row.get(column_index)
                    if raw_count is None:
                        raise SearchDemandSourceError(
                            f"Worksheet {sheet_name!r} row {row_number} has an empty "
                            f"anchor for keyword {_keyword!r}"
                        )
                    count = _parse_query_count(
                        raw_count,
                        location=(
                            f"worksheet {sheet_name!r} row {row_number}, "
                            f"keyword {_keyword!r}"
                        ),
                    )
                    anchor_key = (keyword_key, month)
                    previous = anchor_values.get(anchor_key)
                    if previous is not None and previous != count:
                        raise SearchDemandSourceError(
                            f"Conflicting duplicate keyword-month anchor for "
                            f"{_keyword!r}, {month.isoformat()}: {previous} vs {count}"
                        )
                    anchor_values[anchor_key] = count

            if len(months) != len(set(months)):
                raise SearchDemandSourceError(
                    f"Worksheet {sheet_name!r} contains duplicate months"
                )
            if months != sorted(months):
                raise SearchDemandSourceError(
                    f"Worksheet {sheet_name!r} months must be strictly increasing"
                )
            area_timelines[area_name] = tuple(months)

    if set(area_timelines) != set(EXPECTED_AREA_NAMES_RU):
        missing = sorted(set(EXPECTED_AREA_NAMES_RU).difference(area_timelines))
        raise SearchDemandSourceError(
            f"Workbook must contain exactly seven working diagnostic areas; missing={missing}"
        )
    distinct_timelines = set(area_timelines.values())
    if len(distinct_timelines) != 1:
        raise SearchDemandSourceError(
            "All working worksheets must contain the same exact monthly timeline"
        )
    timeline = next(iter(distinct_timelines))

    keyword_by_key = {
        key: min(variants) for key, variants in keyword_variants.items()
    }
    expected_anchor_keys = {
        (keyword_key, month)
        for keyword_key in keyword_by_key
        for month in timeline
    }
    if set(anchor_values) != expected_anchor_keys:
        missing = sorted(expected_anchor_keys.difference(anchor_values))
        raise SearchDemandSourceError(
            f"Workbook has missing keyword-month anchors: {missing[:5]}"
        )

    anchors = tuple(
        KeywordAnchor(
            keyword_key=keyword_key,
            keyword=keyword_by_key[keyword_key],
            month=month,
            query_count=anchor_values[(keyword_key, month)],
        )
        for keyword_key in sorted(keyword_by_key)
        for month in timeline
    )
    return WorkbookData(
        anchors=anchors,
        keyword_area_mappings=tuple(sorted(mappings)),
        months=timeline,
        areas=tuple(EXPECTED_AREA_NAMES_RU),
    )


def validate_region_profiles(
    profiles: Sequence[RegionProfile],
    *,
    expected_region_count: int = EXPECTED_REGION_COUNT,
    expected_areas: Sequence[str] = EXPECTED_AREA_NAMES_RU,
) -> None:
    """Validate the complete region x diagnostic-area helper matrix."""
    region_names = {profile.region_name for profile in profiles}
    area_names = {profile.diagnostic_area_name_ru for profile in profiles}
    pairs = {
        (profile.region_name, profile.diagnostic_area_name_ru)
        for profile in profiles
    }
    if len(region_names) != expected_region_count:
        raise SearchDemandSourceError(
            f"Region profile helper must contain {expected_region_count} unique regions, "
            f"got {len(region_names)}"
        )
    expected_area_set = set(expected_areas)
    if area_names != expected_area_set:
        raise SearchDemandSourceError(
            "Region profile diagnostic-area set differs from the workbook contract; "
            f"missing={sorted(expected_area_set - area_names)}, "
            f"unexpected={sorted(area_names - expected_area_set)}"
        )
    expected_pair_count = expected_region_count * len(expected_area_set)
    if len(profiles) != expected_pair_count or len(pairs) != expected_pair_count:
        raise SearchDemandSourceError(
            f"Region profile helper must contain exactly {expected_pair_count} unique "
            f"region-area pairs, got rows={len(profiles)}, unique_pairs={len(pairs)}"
        )
    invalid = [
        profile
        for profile in profiles
        if not math.isfinite(profile.regional_affinity)
        or profile.regional_affinity <= 0
    ]
    if invalid:
        raise SearchDemandSourceError("All regional_affinity values must be > 0")


def load_region_profiles(
    path: Path = DEFAULT_REGION_PROFILES_PATH,
) -> tuple[RegionProfile, ...]:
    """Read and strictly validate the 83 x 7 regional profile helper."""
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise SearchDemandSourceError(f"Cannot read region profiles {path}: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SearchDemandSourceError(f"Region profile CSV has no header: {path}")
        missing_columns = sorted(set(_REQUIRED_PROFILE_COLUMNS) - set(reader.fieldnames))
        if missing_columns:
            raise SearchDemandSourceError(
                f"Region profile CSV is missing columns: {missing_columns}"
            )
        profiles: list[RegionProfile] = []
        for line_number, row in enumerate(reader, start=2):
            raw_region = row.get("region_name")
            raw_area = row.get("diagnostic_area_name_ru")
            raw_affinity = row.get("regional_affinity")
            if not isinstance(raw_region, str) or not raw_region:
                raise SearchDemandSourceError(
                    f"Region profile line {line_number} has a blank region_name"
                )
            if raw_region != raw_region.strip():
                raise SearchDemandSourceError(
                    f"Region profile line {line_number} region_name has whitespace"
                )
            if not isinstance(raw_area, str) or not raw_area:
                raise SearchDemandSourceError(
                    f"Region profile line {line_number} has a blank diagnostic area"
                )
            area_key = canonical_key(raw_area, field="profile diagnostic area")
            if area_key not in _EXPECTED_AREA_BY_KEY:
                raise SearchDemandSourceError(
                    f"Region profile line {line_number} has unexpected diagnostic area "
                    f"{raw_area!r}"
                )
            try:
                affinity = float(str(raw_affinity))
            except (TypeError, ValueError) as exc:
                raise SearchDemandSourceError(
                    f"Region profile line {line_number} has invalid regional_affinity "
                    f"{raw_affinity!r}"
                ) from exc
            if not math.isfinite(affinity) or affinity <= 0:
                raise SearchDemandSourceError(
                    f"Region profile line {line_number} regional_affinity must be > 0"
                )
            profiles.append(
                RegionProfile(
                    region_name=raw_region,
                    diagnostic_area_name_ru=_EXPECTED_AREA_BY_KEY[area_key],
                    regional_affinity=affinity,
                )
            )
    validate_region_profiles(profiles)
    return tuple(
        sorted(
            profiles,
            key=lambda item: (item.region_name, item.diagnostic_area_name_ru),
        )
    )


def shift_year(month: date, years: int = -100) -> date:
    """Shift a first-of-month date by a whole number of calendar years."""
    if month.day != 1:
        raise SearchDemandValidationError(
            f"Only first-of-month dates can be shifted, got {month.isoformat()}"
        )
    try:
        return month.replace(year=month.year + years)
    except ValueError as exc:
        raise SearchDemandValidationError(
            f"Cannot shift {month.isoformat()} by {years} years"
        ) from exc


def stable_uniform(*parts: object, seed: int = GLOBAL_SEED) -> float:
    """Map named components to a deterministic uniform value in [0, 1)."""
    digest = hashlib.sha256()
    for part in (seed, *parts):
        encoded = str(part).encode("utf-8")
        digest.update(len(encoded).to_bytes(4, byteorder="big", signed=False))
        digest.update(encoded)
    return int.from_bytes(digest.digest()[:8], "big") / 2**64


def google_region_preference(
    region_id: int,
    *,
    seed: int = GLOBAL_SEED,
) -> float:
    """Return a time- and topic-invariant Google propensity for one region."""
    centered = 2.0 * stable_uniform(
        "google_region_preference", region_id, seed=seed
    ) - 1.0
    return math.exp(centered * GOOGLE_REGION_LOG_AMPLITUDE)


def google_keyword_region_effect(
    keyword: str,
    region_id: int,
    *,
    seed: int = GLOBAL_SEED,
) -> float:
    """Return the weaker time-invariant Google effect for a keyword-region pair."""
    centered = 2.0 * stable_uniform(
        "google_keyword_region_effect", keyword, region_id, seed=seed
    ) - 1.0
    return math.exp(centered * GOOGLE_KEYWORD_REGION_LOG_AMPLITUDE)


def largest_remainder(total: int, weighted_ids: Sequence[tuple[int, float]]) -> dict[int, int]:
    """Allocate an integer total exactly, breaking remainder ties by stable ID."""
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise SearchDemandValidationError("Allocation total must be an integer >= 0")
    if not weighted_ids:
        raise SearchDemandValidationError("Allocation requires at least one weight")
    ids = [identifier for identifier, _weight in weighted_ids]
    if len(ids) != len(set(ids)):
        raise SearchDemandValidationError("Allocation IDs must be unique")
    if any(not math.isfinite(weight) or weight <= 0 for _identifier, weight in weighted_ids):
        raise SearchDemandValidationError("Allocation weights must be finite and > 0")

    weight_sum = math.fsum(weight for _identifier, weight in weighted_ids)
    expected = [total * weight / weight_sum for _identifier, weight in weighted_ids]
    floors = [math.floor(value) for value in expected]
    remaining = total - sum(floors)
    ranked_indexes = sorted(
        range(len(weighted_ids)),
        key=lambda index: (
            -(expected[index] - floors[index]),
            weighted_ids[index][0],
        ),
    )
    remainder_winners = set(ranked_indexes[:remaining])
    result = {
        weighted_ids[index][0]: floors[index]
        + (1 if index in remainder_winners else 0)
        for index in range(len(weighted_ids))
    }
    if sum(result.values()) != total:
        raise SearchDemandValidationError("Largest-remainder reconciliation failed")
    return result


def _round_nonnegative(value: float) -> int:
    if not math.isfinite(value) or value < 0:
        raise SearchDemandValidationError(
            f"Cannot round invalid non-negative count {value!r}"
        )
    return math.floor(value + 0.5)


def _pearson_from_pairs(
    pairs: Iterable[tuple[float | int, float | int]],
) -> tuple[float, bool]:
    count = 0
    sum_x = sum_y = sum_x2 = sum_y2 = sum_xy = 0.0
    identical = True
    for x_value, y_value in pairs:
        x = float(x_value)
        y = float(y_value)
        count += 1
        sum_x += x
        sum_y += y
        sum_x2 += x * x
        sum_y2 += y * y
        sum_xy += x * y
        identical = identical and x_value == y_value
    numerator = count * sum_xy - sum_x * sum_y
    denominator = math.sqrt(
        max(0.0, count * sum_x2 - sum_x * sum_x)
        * max(0.0, count * sum_y2 - sum_y * sum_y)
    )
    correlation = numerator / denominator if denominator else 0.0
    return correlation, identical


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise SearchDemandValidationError("Cannot calculate a percentile without values")
    if not 0.0 <= probability <= 1.0:
        raise SearchDemandValidationError(
            f"Percentile probability must be within [0, 1], got {probability}"
        )
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return (
        ordered[lower_index] * (1.0 - fraction)
        + ordered[upper_index] * fraction
    )


def calculate_regional_source_metrics(
    groups: Sequence[SyntheticGroup],
    regions: Sequence[RegionReference],
) -> RegionalSourceMetrics:
    """Compare Google/Yandex regional lifts within every keyword-month group."""
    ordered_regions = tuple(sorted(regions, key=lambda item: item.region_id))
    if not ordered_regions:
        raise SearchDemandValidationError(
            "Regional source QC requires at least one region"
        )
    if any(region.population <= 0 for region in ordered_regions):
        raise SearchDemandValidationError(
            "Regional source QC requires positive region populations"
        )
    national_population = math.fsum(
        region.population for region in ordered_regions
    )
    correlations: list[float] = []
    same_leaders = 0
    for group in groups:
        if len(group.yandex_counts) != len(ordered_regions) or len(
            group.google_counts
        ) != len(ordered_regions):
            raise SearchDemandValidationError(
                "Regional source QC count vectors do not match the region set"
            )
        if group.yandex_total <= 0 or group.google_total <= 0:
            continue
        yandex_lifts: list[float] = []
        google_lifts: list[float] = []
        for index, region in enumerate(ordered_regions):
            population_share = region.population / national_population
            yandex_lifts.append(
                (group.yandex_counts[index] / group.yandex_total)
                / population_share
            )
            google_lifts.append(
                (group.google_counts[index] / group.google_total)
                / population_share
            )
        correlation, _identical = _pearson_from_pairs(
            zip(yandex_lifts, google_lifts, strict=True)
        )
        correlations.append(correlation)

        yandex_leader = max(
            range(len(ordered_regions)),
            key=lambda index: (
                group.yandex_counts[index],
                -ordered_regions[index].region_id,
            ),
        )
        google_leader = max(
            range(len(ordered_regions)),
            key=lambda index: (
                group.google_counts[index],
                -ordered_regions[index].region_id,
            ),
        )
        same_leaders += yandex_leader == google_leader

    if not correlations:
        raise SearchDemandValidationError(
            "Regional source QC has no positive-total keyword-month groups"
        )
    leader_same_share = same_leaders / len(correlations)
    return RegionalSourceMetrics(
        regional_lift_corr_median=_percentile(correlations, 0.50),
        regional_lift_corr_p10=_percentile(correlations, 0.10),
        regional_lift_corr_p90=_percentile(correlations, 0.90),
        leader_same_share=leader_same_share,
        leader_different_share=1.0 - leader_same_share,
        evaluated_groups=len(correlations),
    )


def generate_synthetic_dataset(
    workbook: WorkbookData,
    profiles: Sequence[RegionProfile],
    regions: Sequence[RegionReference],
    *,
    seed: int = GLOBAL_SEED,
) -> SyntheticDataset:
    """Generate regional Yandex/Google values without external APIs or LLM calls."""
    ordered_regions = tuple(sorted(regions, key=lambda item: item.region_id))
    if not ordered_regions:
        raise SearchDemandValidationError("At least one region is required")
    if len({region.region_id for region in ordered_regions}) != len(ordered_regions):
        raise SearchDemandValidationError("Database region IDs must be unique")
    if len({region.region_name for region in ordered_regions}) != len(ordered_regions):
        raise SearchDemandValidationError("Database region names must be unique")
    if any(region.population <= 0 for region in ordered_regions):
        raise SearchDemandValidationError("Every region population must be > 0")

    profile_by_pair = {
        (profile.region_name, profile.diagnostic_area_name_ru): profile.regional_affinity
        for profile in profiles
    }
    if len(profile_by_pair) != len(profiles):
        raise SearchDemandValidationError(
            "Regional profiles contain duplicate region-area business keys"
        )
    if any(
        not math.isfinite(value) or value <= 0
        for value in profile_by_pair.values()
    ):
        raise SearchDemandValidationError(
            "Every regional profile affinity must be finite and > 0"
        )
    profile_regions = {profile.region_name for profile in profiles}
    database_regions = {region.region_name for region in ordered_regions}
    if profile_regions != database_regions:
        raise SearchDemandValidationError(
            "Helper region names must exactly match database RU region names; "
            f"helper_only={sorted(profile_regions - database_regions)}, "
            f"database_only={sorted(database_regions - profile_regions)}"
        )

    expected_profile_pairs = {
        (region.region_name, area_name)
        for region in ordered_regions
        for area_name in workbook.areas
    }
    if set(profile_by_pair) != expected_profile_pairs:
        raise SearchDemandValidationError(
            "Regional profiles must exactly cover database regions x workbook areas; "
            f"missing={sorted(expected_profile_pairs - set(profile_by_pair))[:5]}, "
            f"unexpected={sorted(set(profile_by_pair) - expected_profile_pairs)[:5]}"
        )

    keyword_areas: dict[str, list[str]] = defaultdict(list)
    for keyword_key, area_name in workbook.keyword_area_mappings:
        keyword_areas[keyword_key].append(area_name)
    anchors_by_key_month = {
        (anchor.keyword_key, anchor.month): anchor for anchor in workbook.anchors
    }
    if len(anchors_by_key_month) != len(workbook.anchors):
        raise SearchDemandValidationError(
            "Workbook data contains duplicate keyword-month anchors"
        )
    expected_anchor_keys = {
        (keyword_key, month)
        for keyword_key in workbook.keyword_by_key
        for month in workbook.months
    }
    if set(anchors_by_key_month) != expected_anchor_keys:
        raise SearchDemandValidationError(
            "Workbook data does not contain one anchor for every keyword-month"
        )

    groups: list[SyntheticGroup] = []
    differs_from_population_only = False
    google_region_preferences = {
        region.region_id: google_region_preference(region.region_id, seed=seed)
        for region in ordered_regions
    }
    for keyword_key in sorted(workbook.keyword_by_key):
        keyword = workbook.keyword_by_key[keyword_key]
        areas = tuple(sorted(set(keyword_areas[keyword_key])))
        if not areas:
            raise SearchDemandValidationError(
                f"Keyword {keyword!r} has no diagnostic-area mapping"
            )
        area_component = "|".join(areas)
        keyword_affinity = {
            region.region_id: 0.70
            + 0.75
            * stable_uniform(
                "keyword_region_affinity",
                keyword_key,
                region.region_name,
                seed=seed,
            )
            for region in ordered_regions
        }
        google_source_multiplier = 0.80 + 0.45 * stable_uniform(
            "google_source_multiplier", keyword_key, seed=seed
        )
        google_keyword_effects = {
            region.region_id: google_keyword_region_effect(
                keyword_key,
                region.region_id,
                seed=seed,
            )
            for region in ordered_regions
        }

        for real_month in workbook.months:
            anchor = anchors_by_key_month[(keyword_key, real_month)]
            month_text = real_month.isoformat()
            raw_weights: list[tuple[int, float]] = []
            google_weights: list[tuple[int, float]] = []
            for region in ordered_regions:
                affinities = [
                    profile_by_pair[(region.region_name, area)] for area in areas
                ]
                area_affinity = math.exp(
                    math.fsum(math.log(value) for value in affinities)
                    / len(affinities)
                )
                month_noise = 0.88 + 0.26 * stable_uniform(
                    "latent_month_region_noise",
                    area_component,
                    keyword_key,
                    region.region_name,
                    month_text,
                    seed=seed,
                )
                spike_uniform = stable_uniform(
                    "latent_local_spike_event",
                    area_component,
                    keyword_key,
                    region.region_name,
                    month_text,
                    seed=seed,
                )
                local_spike = 1.0
                if spike_uniform < 0.015:
                    local_spike = 1.35 + 0.55 * stable_uniform(
                        "latent_local_spike_factor",
                        area_component,
                        keyword_key,
                        region.region_name,
                        month_text,
                        seed=seed,
                    )
                weight = (
                    region.population
                    * area_affinity
                    * keyword_affinity[region.region_id]
                    * month_noise
                    * local_spike
                )
                raw_weights.append((region.region_id, weight))
                google_deviation = 0.92 + 0.16 * stable_uniform(
                    "google_regional_deviation",
                    "google",
                    area_component,
                    keyword_key,
                    region.region_name,
                    month_text,
                    seed=seed,
                )
                google_weights.append(
                    (
                        region.region_id,
                        weight
                        * google_region_preferences[region.region_id]
                        * google_keyword_effects[region.region_id]
                        * google_deviation,
                    )
                )

            google_month_multiplier = 0.90 + 0.20 * stable_uniform(
                "google_month_multiplier", keyword_key, month_text, seed=seed
            )
            google_total = _round_nonnegative(
                anchor.query_count
                * google_source_multiplier
                * google_month_multiplier
            )
            yandex_allocation = largest_remainder(anchor.query_count, raw_weights)
            google_allocation = largest_remainder(google_total, google_weights)
            population_allocation = largest_remainder(
                anchor.query_count,
                [
                    (region.region_id, float(region.population))
                    for region in ordered_regions
                ],
            )
            differs_from_population_only = differs_from_population_only or any(
                yandex_allocation[region.region_id]
                != population_allocation[region.region_id]
                for region in ordered_regions
            )
            shifted_start = shift_year(real_month, -100)
            shifted_end = date(
                shifted_start.year,
                shifted_start.month,
                calendar.monthrange(shifted_start.year, shifted_start.month)[1],
            )
            groups.append(
                SyntheticGroup(
                    keyword_key=keyword_key,
                    keyword=keyword,
                    real_month=real_month,
                    start_date=shifted_start,
                    end_date=shifted_end,
                    yandex_total=anchor.query_count,
                    google_total=google_total,
                    yandex_counts=tuple(
                        yandex_allocation[region.region_id]
                        for region in ordered_regions
                    ),
                    google_counts=tuple(
                        google_allocation[region.region_id]
                        for region in ordered_regions
                    ),
                )
            )

    groups_tuple = tuple(
        sorted(groups, key=lambda item: (item.keyword_key, item.real_month))
    )
    correlation, _identical = _pearson_from_pairs(
        (yandex, google)
        for group in groups_tuple
        for yandex, google in zip(group.yandex_counts, group.google_counts, strict=True)
    )
    regional_metrics = calculate_regional_source_metrics(
        groups_tuple,
        ordered_regions,
    )
    dataset = SyntheticDataset(
        regions=ordered_regions,
        groups=groups_tuple,
        keyword_count=workbook.keyword_count,
        area_count=len(workbook.areas),
        google_yandex_correlation=correlation,
        regional_lift_corr_median=(
            regional_metrics.regional_lift_corr_median
        ),
        regional_lift_corr_p10=regional_metrics.regional_lift_corr_p10,
        regional_lift_corr_p90=regional_metrics.regional_lift_corr_p90,
        leader_same_share=regional_metrics.leader_same_share,
        leader_different_share=regional_metrics.leader_different_share,
    )
    validate_synthetic_dataset(
        dataset,
        workbook,
        differs_from_population_only=differs_from_population_only,
    )
    return dataset


def validate_synthetic_dataset(
    dataset: SyntheticDataset,
    workbook: WorkbookData,
    *,
    differs_from_population_only: bool,
) -> None:
    """Run generation QC before any database write is permitted."""
    expected_group_count = workbook.keyword_count * len(workbook.months)
    if len(dataset.groups) != expected_group_count:
        raise SearchDemandValidationError(
            f"Expected {expected_group_count} keyword-month groups, got {len(dataset.groups)}"
        )
    group_keys = {
        (group.keyword_key, group.start_date, group.end_date)
        for group in dataset.groups
    }
    if len(group_keys) != len(dataset.groups):
        raise SearchDemandValidationError("Generated staging grain is not unique")
    region_count = len(dataset.regions)
    for group in dataset.groups:
        if len(group.yandex_counts) != region_count or len(group.google_counts) != region_count:
            raise SearchDemandValidationError(
                "Every source-keyword-month group must contain every region"
            )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (*group.yandex_counts, *group.google_counts)
        ):
            raise SearchDemandValidationError(
                "Every generated query_count must be an integer >= 0"
            )
        if sum(group.yandex_counts) != group.yandex_total:
            raise SearchDemandValidationError(
                f"Yandex national reconciliation failed for {group.keyword!r}, "
                f"{group.real_month.isoformat()}"
            )
        if sum(group.google_counts) != group.google_total:
            raise SearchDemandValidationError(
                f"Google national reconciliation failed for {group.keyword!r}, "
                f"{group.real_month.isoformat()}"
            )
        if group.start_date != shift_year(group.real_month, -100):
            raise SearchDemandValidationError("Synthetic date shift is not exactly -100 years")
        if group.start_date.day != 1:
            raise SearchDemandValidationError("Synthetic start_date is not first of month")
        if group.end_date.day != calendar.monthrange(
            group.end_date.year, group.end_date.month
        )[1]:
            raise SearchDemandValidationError("Synthetic end_date is not last of month")
    if not differs_from_population_only:
        raise SearchDemandValidationError(
            "Generated regional values collapse to simple population allocation"
        )
    if len(dataset.regions) == EXPECTED_REGION_COUNT and not (
        REGIONAL_LIFT_CORRELATION_MIN
        <= dataset.regional_lift_corr_median
        <= REGIONAL_LIFT_CORRELATION_MAX
    ):
        raise SearchDemandValidationError(
            "Median Google/Yandex regional-lift correlation is outside the DEV "
            f"fixture target [{REGIONAL_LIFT_CORRELATION_MIN:.2f}, "
            f"{REGIONAL_LIFT_CORRELATION_MAX:.2f}]: "
            f"{dataset.regional_lift_corr_median:.6f}"
        )


def validate_database_state(
    workbook: WorkbookData,
    profiles: Sequence[RegionProfile],
    state: DatabaseState,
) -> None:
    """Validate reference entities before planning generation or writes."""
    if len(state.regions) != EXPECTED_REGION_COUNT:
        raise SearchDemandDatabaseError(
            f"Expected exactly {EXPECTED_REGION_COUNT} RU regions, got {len(state.regions)}"
        )
    if len({region.region_id for region in state.regions}) != len(state.regions):
        raise SearchDemandDatabaseError("Database contains duplicate RU region IDs")
    if len({region.region_name for region in state.regions}) != len(state.regions):
        raise SearchDemandDatabaseError("Database contains duplicate RU region names")
    if any(region.population <= 0 for region in state.regions):
        raise SearchDemandDatabaseError(
            "Every RU region must have a positive latest population snapshot"
        )
    helper_names = {profile.region_name for profile in profiles}
    database_names = {region.region_name for region in state.regions}
    if helper_names != database_names:
        raise SearchDemandDatabaseError(
            "Helper region names do not exactly match RU reference regions; "
            f"helper_only={sorted(helper_names - database_names)}, "
            f"database_only={sorted(database_names - helper_names)}"
        )

    areas_by_key: dict[str, DiagnosticAreaReference] = {}
    for area in state.diagnostic_areas:
        key = canonical_key(area.name_ru, field="database diagnostic area")
        if key in areas_by_key:
            raise SearchDemandDatabaseError(
                f"Ambiguous database diagnostic-area name {area.name_ru!r}"
            )
        areas_by_key[key] = area
    missing_areas = sorted(
        area
        for area in workbook.areas
        if canonical_key(area, field="workbook diagnostic area") not in areas_by_key
    )
    if missing_areas:
        raise SearchDemandDatabaseError(
            f"Workbook diagnostic areas are missing from reference: {missing_areas}"
        )


def plan_reference_changes(
    workbook: WorkbookData,
    state: DatabaseState,
) -> ReferencePlan:
    """Plan insert-only keyword and mapping changes; never reassign existing mappings."""
    existing_by_key: dict[str, KeywordReference] = {}
    for keyword in state.keywords:
        key = canonical_key(keyword.keyword, field="database keyword")
        if key in existing_by_key:
            raise SearchDemandDatabaseError(
                "Database has multiple keyword rows for one canonical value: "
                f"{keyword.keyword!r}"
            )
        existing_by_key[key] = keyword

    planned_keywords = tuple(
        PlannedKeyword(
            keyword_key=keyword_key,
            keyword=(
                existing_by_key[keyword_key].keyword
                if keyword_key in existing_by_key
                else workbook.keyword_by_key[keyword_key]
            ),
            keyword_id=(
                existing_by_key[keyword_key].keyword_id
                if keyword_key in existing_by_key
                else None
            ),
        )
        for keyword_key in sorted(workbook.keyword_by_key)
    )

    area_id_by_key = {
        canonical_key(area.name_ru, field="database diagnostic area"):
        area.diagnostic_area_id
        for area in state.diagnostic_areas
    }
    keyword_id_by_key = {
        keyword.keyword_key: keyword.keyword_id
        for keyword in planned_keywords
        if keyword.keyword_id is not None
    }
    missing_mappings: list[tuple[str, int]] = []
    for keyword_key, area_name in workbook.keyword_area_mappings:
        area_id = area_id_by_key[canonical_key(area_name, field="workbook area")]
        keyword_id = keyword_id_by_key.get(keyword_key)
        if keyword_id is None or (keyword_id, area_id) not in state.keyword_area_mappings:
            missing_mappings.append((keyword_key, area_id))
    return ReferencePlan(
        keywords=planned_keywords,
        missing_mappings=tuple(sorted(set(missing_mappings))),
    )


def classify_fixture_rows(
    expected: Sequence[ResolvedSyntheticRow],
    existing: Sequence[ResolvedSyntheticRow],
) -> Literal["insert", "noop"]:
    """Pure exact/no-op/conflict reconciliation used by tests and DB logic."""
    if not existing:
        return "insert"
    expected_sorted = sorted(
        expected,
        key=lambda row: (
            row.source,
            row.keyword_id,
            row.region_id,
            row.start_date,
            row.end_date,
        ),
    )
    existing_sorted = sorted(
        existing,
        key=lambda row: (
            row.source,
            row.keyword_id,
            row.region_id,
            row.start_date,
            row.end_date,
        ),
    )
    if existing_sorted == expected_sorted:
        return "noop"
    raise SearchDemandDatabaseError(
        "Synthetic fixture window contains partial, unexpected, or conflicting rows"
    )


def _assert_database_identity(connection: Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, current_database()")
        current_user, current_database = cursor.fetchone()
    if str(current_user) != EXPECTED_DB_USER:
        raise SearchDemandDatabaseError(
            f"PostgreSQL user must be {EXPECTED_DB_USER!r}, got {current_user!r}"
        )
    if str(current_database) != EXPECTED_DATABASE_NAME:
        raise SearchDemandDatabaseError(
            f"PostgreSQL database must be {EXPECTED_DATABASE_NAME!r}, "
            f"got {current_database!r}"
        )


def _database_preflight(connection: Connection, *, apply: bool) -> None:
    object_names = (
        "reference.countries",
        "reference.regions",
        "reference.region_info",
        "reference.diagnostic_areas",
        "reference.keywords",
        "reference.keyword_diagnostic_areas",
        "staging.keywords_monthly",
        "analysis.search_demand_area_monthly",
        "mart.search_demand",
    )
    with connection.cursor() as cursor:
        for object_name in object_names:
            cursor.execute("SELECT to_regclass(%s)", (object_name,))
            if cursor.fetchone()[0] is None:
                raise SearchDemandDatabaseError(
                    f"Required database object does not exist: {object_name}"
                )

        select_objects = object_names
        for object_name in select_objects:
            cursor.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT')",
                (object_name,),
            )
            if not bool(cursor.fetchone()[0]):
                raise SearchDemandDatabaseError(
                    f"{EXPECTED_DB_USER} lacks SELECT on {object_name}"
                )
        if apply:
            for object_name in (
                "reference.keywords",
                "reference.keyword_diagnostic_areas",
                "staging.keywords_monthly",
            ):
                cursor.execute(
                    "SELECT has_table_privilege(current_user, %s, 'INSERT')",
                    (object_name,),
                )
                if not bool(cursor.fetchone()[0]):
                    raise SearchDemandDatabaseError(
                        f"{EXPECTED_DB_USER} lacks INSERT on {object_name}; "
                        "do not bypass the permission error"
                    )


def _fetch_database_state(
    connection: Connection,
    workbook: WorkbookData,
) -> DatabaseState:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT country_id
            FROM reference.countries
            WHERE country_code = 'RU'
            """
        )
        country_rows = cursor.fetchall()
        if len(country_rows) != 1:
            raise SearchDemandDatabaseError(
                f"Expected exactly one reference.countries row for RU, got {len(country_rows)}"
            )
        country_id = int(country_rows[0][0])

        cursor.execute(
            """
            SELECT
                r.region_id,
                r.region_name,
                latest.population,
                latest.as_of_date
            FROM reference.regions AS r
            LEFT JOIN LATERAL (
                SELECT ri.population, ri.as_of_date
                FROM reference.region_info AS ri
                WHERE ri.region_id = r.region_id
                ORDER BY ri.as_of_date DESC
                LIMIT 1
            ) AS latest ON TRUE
            WHERE r.country_id = %s
            ORDER BY r.region_id
            """,
            (country_id,),
        )
        regions = tuple(
            RegionReference(
                region_id=int(region_id),
                region_name=str(region_name),
                population=(
                    int(population)
                    if population is not None
                    else _raise_missing_population(str(region_name))
                ),
                population_as_of_date=(
                    as_of_date
                    if isinstance(as_of_date, date)
                    else _raise_missing_population(str(region_name))
                ),
            )
            for region_id, region_name, population, as_of_date in cursor.fetchall()
        )

        cursor.execute(
            """
            SELECT diagnostic_area_id, name_ru
            FROM reference.diagnostic_areas
            ORDER BY diagnostic_area_id
            """
        )
        diagnostic_areas = tuple(
            DiagnosticAreaReference(int(identifier), str(name_ru))
            for identifier, name_ru in cursor.fetchall()
        )

        cursor.execute(
            """
            SELECT keyword_id, keyword
            FROM reference.keywords
            ORDER BY keyword_id
            """
        )
        all_keywords = tuple(
            KeywordReference(int(identifier), str(keyword))
            for identifier, keyword in cursor.fetchall()
        )
        workbook_keys = set(workbook.keyword_by_key)
        relevant_keywords = tuple(
            keyword
            for keyword in all_keywords
            if canonical_key(keyword.keyword, field="database keyword") in workbook_keys
        )
        relevant_ids = [keyword.keyword_id for keyword in relevant_keywords]
        if relevant_ids:
            cursor.execute(
                """
                SELECT keyword_id, diagnostic_area_id
                FROM reference.keyword_diagnostic_areas
                WHERE keyword_id = ANY(%s)
                ORDER BY keyword_id, diagnostic_area_id
                """,
                (relevant_ids,),
            )
            mappings = frozenset(
                (int(keyword_id), int(area_id))
                for keyword_id, area_id in cursor.fetchall()
            )
        else:
            mappings = frozenset()
    return DatabaseState(
        regions=regions,
        diagnostic_areas=diagnostic_areas,
        keywords=relevant_keywords,
        keyword_area_mappings=mappings,
    )


def _raise_missing_population(region_name: str) -> NoReturn:
    raise SearchDemandDatabaseError(
        f"RU region {region_name!r} has no available population snapshot"
    )


def _fixture_row_count(connection: Connection, dataset: SyntheticDataset) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM staging.keywords_monthly
            WHERE source = ANY(%s)
              AND start_date BETWEEN %s AND %s
            """,
            (list(SOURCES), dataset.start_date, max(group.start_date for group in dataset.groups)),
        )
        return int(cursor.fetchone()[0])


def _inspect_fixture_state(
    connection: Connection,
    dataset: SyntheticDataset,
    plan: ReferencePlan,
) -> Literal["insert", "noop"]:
    existing_count = _fixture_row_count(connection, dataset)
    if existing_count == 0:
        return "insert"
    if existing_count != dataset.row_count:
        raise SearchDemandDatabaseError(
            "Synthetic fixture window contains a partial or unexpected row set: "
            f"database={existing_count}, expected={dataset.row_count}"
        )
    if plan.missing_keywords:
        raise SearchDemandDatabaseError(
            "Synthetic fixture rows exist but expected reference keywords are missing"
        )

    expected_rows = dataset.iter_resolved_rows(plan.keyword_id_by_key)
    cursor_name = "search_demand_fixture_compare"
    with connection.cursor(name=cursor_name) as cursor:
        cursor.execute(
            """
            SELECT source, keyword_id, region_id, start_date, end_date, query_count
            FROM staging.keywords_monthly
            WHERE source = ANY(%s)
              AND start_date BETWEEN %s AND %s
            ORDER BY source, keyword_id, region_id, start_date, end_date
            """,
            (
                list(SOURCES),
                dataset.start_date,
                max(group.start_date for group in dataset.groups),
            ),
        )
        compared = 0
        for expected, stored in zip(expected_rows, cursor, strict=True):
            stored_row = ResolvedSyntheticRow(
                source=str(stored[0]),
                keyword_id=int(stored[1]),
                region_id=int(stored[2]),
                start_date=stored[3],
                end_date=stored[4],
                query_count=int(stored[5]),
            )
            if stored_row != expected:
                raise SearchDemandDatabaseError(
                    "Synthetic fixture window conflicts with deterministic output; "
                    f"stored={stored_row}, expected={expected}"
                )
            compared += 1
    if compared != dataset.row_count:
        raise SearchDemandDatabaseError(
            f"Compared {compared} fixture rows, expected {dataset.row_count}"
        )
    return "noop"


def _insert_reference_changes(
    connection: Connection,
    workbook: WorkbookData,
    plan: ReferencePlan,
) -> tuple[DatabaseState, ReferencePlan, int, int]:
    inserted_keywords = 0
    with connection.cursor() as cursor:
        for item in plan.missing_keywords:
            cursor.execute(
                """
                INSERT INTO reference.keywords (keyword)
                VALUES (%s)
                RETURNING keyword_id
                """,
                (item.keyword,),
            )
            returned = cursor.fetchall()
            if len(returned) != 1:
                raise SearchDemandDatabaseError(
                    f"Expected one inserted keyword row for {item.keyword!r}"
                )
            inserted_keywords += 1

    refreshed_state = _fetch_database_state(connection, workbook)
    refreshed_plan = plan_reference_changes(workbook, refreshed_state)
    if refreshed_plan.missing_keywords:
        raise SearchDemandDatabaseError(
            "Keyword IDs did not resolve completely after insert"
        )

    inserted_mappings = 0
    keyword_ids = refreshed_plan.keyword_id_by_key
    with connection.cursor() as cursor:
        for keyword_key, area_id in refreshed_plan.missing_mappings:
            cursor.execute(
                """
                INSERT INTO reference.keyword_diagnostic_areas (
                    keyword_id,
                    diagnostic_area_id
                )
                VALUES (%s, %s)
                """,
                (keyword_ids[keyword_key], area_id),
            )
            if cursor.rowcount != 1:
                raise SearchDemandDatabaseError(
                    "Expected exactly one inserted keyword-diagnostic-area mapping"
                )
            inserted_mappings += 1

    final_state = _fetch_database_state(connection, workbook)
    final_plan = plan_reference_changes(workbook, final_state)
    if final_plan.missing_keywords or final_plan.missing_mappings:
        raise SearchDemandDatabaseError(
            "Reference keyword reconciliation failed after insert"
        )
    return final_state, final_plan, inserted_keywords, inserted_mappings


def _batches(iterable: Iterable[ResolvedSyntheticRow], size: int) -> Iterator[list[ResolvedSyntheticRow]]:
    iterator = iter(iterable)
    while batch := list(islice(iterator, size)):
        yield batch


def _insert_fixture_rows(
    connection: Connection,
    dataset: SyntheticDataset,
    keyword_id_by_key: Mapping[str, int],
) -> int:
    inserted = 0
    statement = """
        INSERT INTO staging.keywords_monthly (
            source,
            keyword_id,
            region_id,
            start_date,
            end_date,
            query_count
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    with connection.cursor() as cursor:
        for batch in _batches(dataset.iter_resolved_rows(keyword_id_by_key), 5_000):
            cursor.executemany(
                statement,
                [
                    (
                        row.source,
                        row.keyword_id,
                        row.region_id,
                        row.start_date,
                        row.end_date,
                        row.query_count,
                    )
                    for row in batch
                ],
            )
            if cursor.rowcount != len(batch):
                raise SearchDemandDatabaseError(
                    "Staging INSERT affected an unexpected number of rows: "
                    f"expected={len(batch)}, affected={cursor.rowcount}"
                )
            inserted += cursor.rowcount
    if inserted != dataset.row_count:
        raise SearchDemandDatabaseError(
            f"Expected {dataset.row_count} inserted rows, got {inserted}"
        )
    return inserted


def _validate_database_views(
    connection: Connection,
    dataset: SyntheticDataset,
) -> None:
    max_start_date = max(group.start_date for group in dataset.groups)
    parameters = (list(SOURCES), dataset.start_date, max_start_date)
    stored_count = _fixture_row_count(connection, dataset)
    if stored_count != dataset.row_count:
        raise SearchDemandDatabaseError(
            f"Post-insert staging count is {stored_count}, expected {dataset.row_count}"
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH staging_rows AS (
                SELECT
                    source,
                    keyword_id AS entity_id,
                    region_id,
                    start_date,
                    end_date,
                    query_count
                FROM staging.keywords_monthly
                WHERE source = ANY(%s)
                  AND start_date BETWEEN %s AND %s
            ),
            mart_rows AS (
                SELECT
                    source,
                    entity_id,
                    region_id,
                    start_date,
                    end_date,
                    query_count
                FROM mart.search_demand
                WHERE level = 'keyword'
                  AND source = ANY(%s)
                  AND start_date BETWEEN %s AND %s
            )
            SELECT EXISTS (
                SELECT 1
                FROM (
                    (SELECT * FROM staging_rows EXCEPT ALL SELECT * FROM mart_rows)
                    UNION ALL
                    (SELECT * FROM mart_rows EXCEPT ALL SELECT * FROM staging_rows)
                ) AS differences
            )
            """,
            (*parameters, *parameters),
        )
        if bool(cursor.fetchone()[0]):
            raise SearchDemandDatabaseError(
                "Keyword-level staging to mart reconciliation failed"
            )

        cursor.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT diagnostic_area_id)
            FROM analysis.search_demand_area_monthly
            WHERE source = ANY(%s)
              AND start_date BETWEEN %s AND %s
            """,
            parameters,
        )
        area_row_count, distinct_areas = (int(value) for value in cursor.fetchone())
    expected_area_rows = (
        len(SOURCES)
        * len(dataset.regions)
        * (len(dataset.groups) // dataset.keyword_count)
        * dataset.area_count
    )
    if area_row_count != expected_area_rows or distinct_areas != dataset.area_count:
        raise SearchDemandDatabaseError(
            "Area-level view reconciliation failed: "
            f"rows={area_row_count}/{expected_area_rows}, "
            f"areas={distinct_areas}/{dataset.area_count}"
        )


def run_fixture(
    connection: Connection,
    workbook: WorkbookData,
    profiles: Sequence[RegionProfile],
    *,
    apply: bool = False,
) -> FixtureRunSummary:
    """Run read-only preflight/QC or atomically insert after explicit opt-in."""
    with connection.transaction():
        with connection.cursor() as cursor:
            if apply:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            else:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
        _assert_database_identity(connection)
        _database_preflight(connection, apply=apply)
        state = _fetch_database_state(connection, workbook)
        validate_database_state(workbook, profiles, state)
        plan = plan_reference_changes(workbook, state)
        dataset = generate_synthetic_dataset(workbook, profiles, state.regions)
        fixture_action = _inspect_fixture_state(connection, dataset, plan)

        action: Literal["insert", "noop", "reference_insert"] = fixture_action
        if fixture_action == "noop" and (
            plan.missing_keywords or plan.missing_mappings
        ):
            action = "reference_insert"

        inserted_rows = 0
        inserted_keywords = 0
        inserted_mappings = 0
        if apply:
            if plan.missing_keywords or plan.missing_mappings:
                state, plan, inserted_keywords, inserted_mappings = (
                    _insert_reference_changes(connection, workbook, plan)
                )
            if fixture_action == "insert":
                inserted_rows = _insert_fixture_rows(
                    connection, dataset, plan.keyword_id_by_key
                )
                if _inspect_fixture_state(connection, dataset, plan) != "noop":
                    raise SearchDemandDatabaseError(
                        "Inserted fixture did not reconcile exactly"
                    )
            _validate_database_views(connection, dataset)

    return FixtureRunSummary(
        mode="apply" if apply else "dry-run",
        action=action,
        synthetic_start_date=dataset.start_date,
        synthetic_end_date=dataset.end_date,
        sources=tuple(sorted(SOURCES)),
        regions=len(dataset.regions),
        diagnostic_areas=dataset.area_count,
        keywords=dataset.keyword_count,
        generated_rows=dataset.row_count,
        inserted_rows=inserted_rows,
        inserted_keywords=inserted_keywords,
        inserted_keyword_area_mappings=inserted_mappings,
        google_yandex_correlation=dataset.google_yandex_correlation,
        regional_lift_corr_median=dataset.regional_lift_corr_median,
        regional_lift_corr_p10=dataset.regional_lift_corr_p10,
        regional_lift_corr_p90=dataset.regional_lift_corr_p90,
        leader_same_share=dataset.leader_same_share,
        leader_different_share=dataset.leader_different_share,
    )
