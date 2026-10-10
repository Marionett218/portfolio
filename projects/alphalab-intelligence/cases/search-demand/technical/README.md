# Technical evidence — AlphaLab Search Demand
>Find Russian text below

[← Back to Search Demand case](../README.md)

## 1. Purpose of this folder

This folder contains a small, curated set of real technical files from the working AlphaLab Intelligence repository. It is not the full project source code and is not intended to reproduce the working repository inside the portfolio.

The files were selected as technical evidence for decisions described in the Search Demand materials: aggregation semantics, growth calculations, redesign of the `mart` layer due to performance issues, generation of the synthetic DEV fixture, and automated checks. Each file demonstrates a different aspect of the implementation and is not included merely for completeness.

## 2. How the technical implementation was created

Most of the SQL, Python, and tests in this project were created with the help of ChatGPT, Codex, and other LLM tools. My role was to define the business and analytical task, determine data and metric semantics, choose architectural solutions, formulate constraints and acceptance criteria, run the implementation locally, and verify the results. I did not usually perform a full traditional line-by-line code review of the SQL/Python; quality was controlled through checks of the data structure, actual outputs, tests, independent reconciliations, and PostgreSQL/Tableau behavior.

## 3. Technical evidence

### `db/migrations/07_add_keyword_area_aggregation_flag.sql`

**What it implements:**  
Adds `include_in_area_aggregate` to the M:N relationship `keyword ↔ diagnostic_area` and updates area-level aggregation. The relationship can remain in the model while a specific keyword does not necessarily contribute to the aggregate for that diagnostic area. Keyword-level data are not removed.

**Why this file is included:**  
This is compact technical evidence of one of the key semantic boundaries in Search Demand: relationships between keywords and diagnostic areas are not a simple mutually exclusive classification. A full `query_count` may belong to several included areas, so diagnostic-area totals cannot be summed as components of a single market total.

**Role of AI:**  
The SQL implementation was prepared with LLM/Codex based on the agreed analytical rules and was then checked in the working database.

---

### `db/migrations/12_add_search_demand_keyword_growth_mv.sql`

**What it implements:**  
Creates `mart.search_demand_keyword_growth` — a `MATERIALIZED VIEW` for country-level keyword analysis. Regional values are first aggregated into a `country × keyword × month` series, after which three fixed horizons are calculated: the latest 3 months versus the previous 3 months, the latest 12 months versus the previous 12 months, and long-term CAGR between the first and latest 12-month levels.

Result grain: `source × country × diagnostic_area × keyword × period_type`.

**Why this file is included:**  
This is the most substantive example of Search Demand calculation logic. It demonstrates an important project rule: country-level growth must not be calculated as an average of regional growth percentages. The same object was used for the “demand level × growth rate” analysis in Tableau. A separate full reconciliation was performed for all 498 rows against an independent recalculation from staging; no discrepancies were found in the key calculated fields.

**Role of AI:**  
The SQL was created by LLM/Codex; the analytical specification, interpretation of the metrics, verification criteria, and acceptance of the result were performed by the author.

---

### `db/migrations/08_add_search_demand_area_mart_view.sql`

**What it implements:**  
Creates the Tableau-oriented `mart.search_demand_area` with grain `source × region × period × diagnostic_area`. The mart is built directly from `staging.keywords_monthly` and the reference mapping rather than through a more general aggregation chain.

**Why this file is included:**  
This file confirms a real architectural redesign triggered by Tableau performance problems. Direct access to staging allowed PostgreSQL to apply filters by source and diagnostic area before expensive aggregation. For one control query, `yandex + Helminthiases`, execution time improved from approximately 819 ms to 86.8 ms. This is the result of one specific local measurement, not a claim that the entire system became nine times faster.

**Role of AI:**  
ChatGPT participated in investigating the cause and comparing architectural options; LLM/Codex prepared the SQL implementation. The author initiated the investigation after observing the issue in Tableau and verified the effect in the working system.

---

### `src/alphalab/synthetic/search_demand.py`

**What it implements:**  
The main Python module for the temporary DEV synthetic Search Demand fixture. It reads controlled inputs, uses reference geography/population/diagnostic areas, creates canonical keywords and mappings, deterministically distributes national Yandex Wordstat anchors across 83 regions, generates a related but distinct synthetic Google signal, and creates monthly facts in `staging.keywords_monthly`.

The implementation supports dry-run by default, explicit `--apply`, checks for conflicting/partial state, and reconciliation of the result.

**Why this file is included:**  
This file shows how the project continued BI development in the absence of production regional Search Demand data without presenting synthetic data as measured market data. The current DEV fixture contains 1,128,800 rows and uses an artificially shifted 1920–1926 period to visually distinguish it from future live data.

**Role of AI:**  
The main Python code was created with LLM/Codex based on the author’s requirements for reproducibility, separation of real and synthetic data, and result verification.

---

### `tests/test_synthetic_search_demand.py`

**What it implements:**  
A dedicated test module accompanying the synthetic Search Demand generator.

**Why this file is included:**  
It confirms that the generator has a separate automated testing layer rather than relying only on visual inspection of the generated data. At the same time, this README does not attribute all project checks to this file: part of the control was performed separately through dry-run, reconciliation, and direct analysis of results in PostgreSQL/Tableau. In the final state, the overall Python test suite passed successfully; the generator was also rechecked with a dry-run returning `action=noop` and the expected 1,128,800 rows.

**Role of AI:**  
The tests were mostly created with LLM/Codex. The author defined the acceptance criteria, ran the checks locally, and analyzed the actual output.

## 4. What this set does not demonstrate

These five files are a curated sample of technical evidence, not the full AlphaLab Intelligence repository. They do not imply that the author manually wrote the presented SQL/Python or performed traditional line-by-line code review of the entire implementation.

The complete analytical methodology, architecture, and AI-assisted development process are described separately in the portfolio materials. These files serve a narrower purpose: to demonstrate that the documented decisions have a real technical implementation and that the implementation was verified in the working project.

# Technical evidence — AlphaLab Search Demand

## 1. Назначение этой папки

Эта папка содержит небольшой отобранный набор реальных технических файлов из рабочего репозитория AlphaLab Intelligence. Это не полный исходный код проекта и не попытка воспроизвести рабочий репозиторий внутри портфолио.

Файлы выбраны как технические подтверждения решений, описанных в материалах Search Demand: семантики агрегации, расчёта growth, переработки слоя `mart` из-за производительности, генерации synthetic DEV fixture и автоматизированных проверок. Каждый файл показывает отдельную сторону реализации и не дублирует остальные только ради полноты.

## 2. Как создавалась техническая реализация

Основная часть SQL, Python и tests в этом проекте создавалась с помощью ChatGPT, Codex и других LLM-инструментов. Моя роль состояла в постановке бизнес- и аналитической задачи, определении семантики данных и метрик, выборе архитектурного решения, формулировании ограничений и критериев приёмки, локальном запуске и проверке результата. Полноценного традиционного построчного ручного code review SQL/Python с моей стороны обычно не выполнялось; качество контролировалось через проверку структуры данных, фактических результатов, тестов, независимых сверок и поведения PostgreSQL/Tableau.

## 3. Technical evidence

### `db/migrations/07_add_keyword_area_aggregation_flag.sql`

**Что реализует:**  
Добавляет `include_in_area_aggregate` в M:N-связь `keyword ↔ diagnostic_area` и обновляет area-level aggregation. Связь может сохраняться в модели, а конкретный keyword при этом не обязан входить в агрегат данного диагностического направления. Keyword-level данные не удаляются.

**Почему файл здесь:**  
Это компактное техническое подтверждение одной из ключевых семантических границ Search Demand: связи между keywords и diagnostic areas не являются простой взаимоисключающей классификацией. Полный `query_count` может относиться к нескольким включённым направлениям, поэтому totals diagnostic areas нельзя суммировать как части единого рынка.

**Роль AI:**  
SQL-реализация была подготовлена с помощью LLM/Codex по согласованным аналитическим правилам и затем проверялась в рабочей БД.

---

### `db/migrations/12_add_search_demand_keyword_growth_mv.sql`

**Что реализует:**  
Создаёт `mart.search_demand_keyword_growth` — `MATERIALIZED VIEW` для country-level анализа keywords. Региональные значения сначала суммируются до ряда `country × keyword × month`, после чего рассчитываются три фиксированных горизонта: последние 3 месяца против предыдущих 3, последние 12 против предыдущих 12 и долгосрочный CAGR между первым и последним 12-месячными уровнями.

Grain результата: `source × country × diagnostic_area × keyword × period_type`.

**Почему файл здесь:**  
Это наиболее содержательный пример расчётной логики Search Demand. Он показывает важное правило проекта: country-level growth нельзя получать как среднее региональных процентов роста. Этот же объект использовался для анализа «уровень спроса × темп роста» в Tableau. Для него была выполнена отдельная полная сверка всех 498 строк с независимым пересчётом из staging; расхождений по ключевым расчётным полям обнаружено не было.

**Роль AI:**  
SQL был создан LLM/Codex; аналитическая постановка, интерпретация показателей, критерии проверки и приёмка результата выполнялись автором.

---

### `db/migrations/08_add_search_demand_area_mart_view.sql`

**Что реализует:**  
Создаёт Tableau-oriented `mart.search_demand_area` с grain `source × region × period × diagnostic_area`. Витрина строится напрямую из `staging.keywords_monthly` и reference mapping, а не через более общую цепочку агрегаций.

**Почему файл здесь:**  
Файл подтверждает реальную архитектурную переработку, вызванную проблемой производительности Tableau. Прямой доступ к staging позволил PostgreSQL применять фильтры по source и diagnostic area до тяжёлой агрегации. Для одного контрольного запроса `yandex + Helminthiases` зафиксировано улучшение примерно с 819 ms до 86.8 ms. Это результат конкретного локального измерения, а не утверждение о девятикратном ускорении всей системы.

**Роль AI:**  
ChatGPT участвовал в разборе причины и вариантов архитектуры; LLM/Codex подготовил SQL-реализацию. Автор инициировал исследование после фактической проблемы в Tableau и проверял эффект на рабочей системе.

---

### `src/alphalab/synthetic/search_demand.py`

**Что реализует:**  
Основной Python-модуль временного DEV synthetic Search Demand fixture. Он читает контролируемые inputs, использует reference geography/population/diagnostic areas, создаёт canonical keywords и mappings, детерминированно распределяет национальные Yandex Wordstat anchors по 83 регионам, создаёт связанный, но отдельный synthetic Google signal и формирует месячные факты в `staging.keywords_monthly`.

Реализация поддерживает dry-run по умолчанию, явный `--apply`, проверку конфликтного/частичного состояния и reconciliation результата.

**Почему файл здесь:**  
Этот файл показывает, как проект продолжил BI-разработку при отсутствии production regional Search Demand, не выдавая synthetic данные за измеренный рынок. Текущий DEV fixture содержит 1 128 800 строк и использует искусственно сдвинутый период 1920–1926, чтобы визуально отделить его от будущих live data.

**Роль AI:**  
Основной Python-код создан с помощью LLM/Codex по требованиям автора к воспроизводимости, разграничению real/synthetic данных и проверкам результата.

---

### `tests/test_synthetic_search_demand.py`

**Что реализует:**  
Отдельный test-модуль, сопровождающий synthetic Search Demand generator.

**Почему файл здесь:**  
Он подтверждает, что для генератора существует отдельный автоматизированный слой проверок, а не только визуальная оценка получившихся данных. При этом README не приписывает этому файлу все проверки проекта: часть контроля выполнялась отдельно через dry-run, reconciliation и фактический анализ результата в PostgreSQL/Tableau. В финальном состоянии общий Python test suite проекта проходил успешно; generator также повторно проверялся dry-run с `action=noop` и ожидаемыми 1 128 800 строками.

**Роль AI:**  
Tests в основном создавались LLM/Codex. Автор задавал критерии приёмки, запускал проверки локально и анализировал фактический вывод.

## 4. Что этот набор не доказывает

Эти пять файлов — выборка технических доказательств, а не полный AlphaLab Intelligence repository. Они не означают, что автор вручную написал представленный SQL/Python или выполнял традиционный построчный code review всей реализации.

Полная аналитическая методология, архитектура и процесс AI-assisted development описаны отдельно в материалах портфолио. Эти файлы нужны для более узкой цели: показать, что описанные решения действительно имеют техническую реализацию и что она проверялась на рабочем проекте.
