# Analytical Design — Search Demand
>Find Russian text below

## Document purpose

Search Demand was designed as an analytical system, not simply as a set of visualizations:

- business questions were translated into specific analytical grains and entities;
- ambiguous keyword semantics were formalized explicitly;
- interpretation limitations are stated rather than hidden;
- heavy calculations were moved out of Tableau after a real performance problem emerged;
- synthetic data were separated from factual data;
- correctness was checked at several levels, including independent recalculation of results;
- the role of AI in the technical implementation is stated separately from the author’s analytical decisions.

## 1. Problem definition

Search Demand is one of the analytical streams within AlphaLab Intelligence, a market intelligence system for a company operating in laboratory diagnostics. In this stream, search behavior is treated as an additional signal of potential interest from both professional customers and end users.

The goal of Search Demand is to answer three applied questions:

1. **Regional representation** — where search interest is concentrated and how it differs across regions.
2. **Trends** — which diagnostic areas are growing or declining and which changes require further investigation.
3. **Keywords comparison** — which search queries shape interest within a diagnostic area and how they differ in volume and dynamics.

These three scenarios determined the data structure, required aggregation levels, and the composition of Tableau marts.

A search query is used as an indicator of interest from potential users and customers: both businesses (diagnostic laboratories using AlphaLabs products) and patients looking for a way to address a health problem.

---

## 2. Minimal analytical model

Search Demand is built around a small set of entities:

- `keyword` — a canonical search query (a search term entered by a business user and/or patient);
- `diagnostic_area` — an analytical diagnostic area;
- `region` — a region;
- `period` — a calendar period;
- `source` — a source of search data;
- `query_count` — the number of queries reported by the corresponding source.

### Base grain

The core fact is stored at the following level:

`source × keyword × region × period`

One row answers the question:

> how many queries for a specific keyword were recorded in a specific search engine, in a specific region, during a specific period (month).

### Grain of the diagnostic-area aggregate

For diagnostic-area analysis, the following level is used:

`source × region × period × diagnostic_area`

At this level, individual keywords are grouped into an analytical area according to the rules described below.

The full set of technical tables and fields is intentionally excluded from this document: its purpose is to explain the analytical design logic, not to duplicate the database model.

---

## 3. Key semantic decision: `keyword ↔ diagnostic_area`

A single search query may meaningfully belong to more than one diagnostic area. Therefore, the relationship between `keyword` and `diagnostic_area` was designed as many-to-many.

For example, if a keyword genuinely reflects interest in two areas, its value is not artificially split 60/40 or according to any other proportion for which there is no factual basis. The full `query_count` is attributed to each relevant area.

The consequence of this decision is essential for interpretation:

> totals for different `diagnostic_area` values are not mutually exclusive parts of one overall market and must not be summed together.

The model also uses `include_in_area_aggregate`. It allows the `keyword ↔ diagnostic_area` relationship itself to be preserved while excluding a specific keyword from the area aggregate if the search wording is too broad or distorts the meaning of the overall indicator. The keyword remains available for separate analysis.

### Decision ownership

**Author:** defined the M:N semantics and rejected arbitrary splitting of demand across diagnostic areas.

**LLM:** assisted with technical formalization of the rule and implementation of the corresponding logic in the data model and SQL.

---

## 4. Key analytical decisions

### 4.1. Meaning first, frequency second

The keyword list was not built simply from the most frequent queries. Instead, it started from the question:

> which search formulations meaningfully reflect interest in a specific diagnostic problem?

Keywords were selected based on domain reasoning and manual analysis of queries in Yandex Wordstat.

**Author:** defined the semantic principle and selected the domain logic.

**LLM:** assisted with data structuring and technical implementation.

---

### 4.2. Three horizons for demand dynamics

Three different horizons are used to assess changes in demand because they answer different management questions.

**Short horizon (`quarter`)**  
The average level of the latest 3 complete months is compared with the average of the previous 3 months.

Purpose: identify recent movement that may be related to short-term changes or seasonality.

**Medium horizon (`year`)**  
The average level of the latest 12 complete months is compared with the average of the previous 12 months.

Purpose: separate more persistent dynamics from within-year fluctuations.

**Long-term horizon (`all_time`)**  
CAGR is calculated between the average of the first 12 months of available history and the average of the latest 12 complete months.

Purpose: show structural long-term change without excessive dependence on a single starting or ending month.

**Author:** defined the business meaning of the three horizons.

**LLM:** proposed and technically formalized the specific calculation windows and CAGR.

---

### 4.3. Country-level growth is calculated after aggregating regions

Country-level growth should not be calculated as the average of regional growth percentages.

The correct sequence is:

1. sum `query_count` across all regions of the country for each month;
2. obtain a single monthly time series for the country;
3. only then calculate the growth rate.

This preserves the economic meaning of the metric: it answers the question of how the **total volume of demand in the country** is changing, rather than the average behavior of its regions.

**LLM:** raised the issue and proposed the correct approach.

**Author:** checked the meaning of the solution and accepted it as a model rule.

---

### 4.4. Separation of calculations between PostgreSQL and Tableau

Initially, part of the heavy calculations was performed within Tableau’s interactive path. At the actual data volume, this made the dashboard too slow to work with.

The problem was identified not because “the SQL looked complex,” but through the actual behavior of the system: visualizations refreshed unacceptably slowly and free disk space was decreasing rapidly. Control measurements were then performed and the calculation architecture was redesigned.

The resulting decision was:

- perform fixed and heavy calculations in advance in PostgreSQL;
- create specialized `VIEW` and `MATERIALIZED VIEW` objects for reusable scenarios;
- leave in Tableau only the logic that genuinely depends on interactive user choices: filters, ranking, TOP-N, and visual presentation.

As an illustrative example, for one control query the execution time decreased from approximately **819 ms to 86.8 ms** after moving the heavy logic into a specialized mart.

**Author:** identified the performance problem, initiated the investigation, and proposed moving heavy calculations out of Tableau’s interactive path into specialized marts.

**LLM:** assisted with the technical analysis and with selecting an implementation based on `VIEW` / `MATERIALIZED VIEW`.

---

### 4.5. Synthetic DEV data are separated from factual data

To configure Tableau before live regional data became available, a reproducible synthetic dataset was created for regions and, entirely, for the Google search source.

Clear boundaries were established:

- national monthly Yandex Wordstat anchors are factual;
- Yandex regional distribution is synthetic;
- Google is a fully synthetic source;
- the timeline is shifted 100 years into the past so that DEV data cannot be mistaken for future live data;
- the synthetic fixture is intended for development and analytical testing, not for claims about the actual regional market.

**Author:** defined the fixture requirements, the rule for preserving factual control totals, the level of randomization required so that regional data would not differ only proportionally across diagnostic areas, and the 100-year time shift.

**LLM:** implemented the Python generator, checks, and technical data loading.

---

## 5. How correctness was checked

Validation was not limited to whether SQL or Python completed without errors.

### 5.1. Reconciliation with source Yandex anchors

For every `keyword × month`, the sum of synthetic regional Yandex values must exactly match the original national Wordstat value.

This verifies that regional allocation neither creates nor loses total demand volume.

### 5.2. Grain and data integrity

The following were checked:

- expected row counts;
- grain uniqueness;
- required values;
- foreign-key relationships;
- temporal coverage;
- source → target reconciliation;
- absence of partially loaded fixture data.

Successful code execution alone is not treated as sufficient evidence of correctness.

### 5.3. Independent recalculation of growth metrics

For `mart.search_demand_keyword_growth`, all **498 rows** were independently recalculated directly from the source staging layer.

The following values were compared:

- `latest_month_query_count`;
- `current_level`;
- `previous_level`;
- `growth_pct`.

No mismatches were found.

This is particularly important because the validation does not use the mart itself as the source of truth.

### 5.4. Validation of synthetic regional pattern diversity

A separate check verified that synthetic regional profiles were not simple proportional copies of a single template.

Regional-profile correlations and the coincidence of leading regions across different series were analyzed.

The purpose of this check was to confirm the **diversity and internal consistency of the DEV dataset**, while not implying that the synthetic regional distribution is realistic.

### 5.5. Performance validation after the architectural change

After specialized mart objects were introduced, control queries were run again.

The tests confirmed that moving heavy logic out of Tableau’s interactive path produced a practical improvement and made continued work with the dashboard realistic.

---

## 6. Responsibility boundary between the author and AI

The project was developed with the assistance of ChatGPT/Codex. SQL, Python, and a significant share of the tests were created by LLMs based on the author’s technical specifications and clarifications. The human author defined the business problem, semantics, criteria, and accepted the results; the LLMs wrote most of the SQL/Python/tests and helped technically formalize the decisions. Conventional manual code review was not performed.

## 7. Known limitations

- Search Demand currently runs on a DEV synthetic fixture rather than live regional data.
- National Yandex anchors are factual, but the regional distribution is synthetic.
- Google data are fully synthetic and are not an estimate of actual Google search volume.
- Search demand is a proxy for interest, not sales, revenue, or market size.
- Data and visualization updates through an API/raw layer are not implemented.
- Automatic monthly refresh of materialized views is not implemented; refresh is performed manually.


>Russian version

## Назначение документа: 

Search Demand спроектирован как аналитическая система, а не просто набор визуализаций:

- бизнес-вопросы переведены в конкретные аналитические grain и сущности;
- неоднозначная семантика keywords формализована явно;
- ограничения интерпретации не скрываются;
- тяжёлые расчёты вынесены из Tableau после фактической проблемы производительности;
- synthetic data отделены от фактических данных;
- корректность проверялась на нескольких уровнях, включая независимый пересчёт результатов;
- роль AI в технической реализации указана отдельно от авторских аналитических решений.

## 1. Постановка задачи

Search Demand — один из аналитических контуров AlphaLab Intelligence, системы рыночной аналитики для компании в области лабораторной диагностики. В этом контуре поисковое поведение рассматривается как дополнительный сигнал потенциального интереса со стороны профессиональных клиентов и конечных пользователей.

Цель Search Demand — дать ответы на три прикладных вопроса:

1. **Regional representation** — где сосредоточен поисковый интерес и как он различается между регионами.
2. **Trends** — какие диагностические направления растут или снижаются и какие изменения требуют дальнейшего исследования.
3. **Keywords comparison** — какие поисковые запросы формируют интерес внутри направления и как они отличаются по объёму и динамике.

Эти три сценария определили структуру данных, нужные уровни агрегации и состав витрин для Tableau.

Поисковый запрос используется как индикатор интереса потенциальных пользователей и клиентов, как бизнеса (диагностических лабораторий, использующих препараты компании AlphaLabs), так и пациентов, ищущих способ решить проблему со здоровьем. 

---

## 2. Минимальная аналитическая модель

В основе Search Demand лежит небольшой набор сущностей:

- `keyword` — канонический поисковый запрос (ключевое слово, вводимое в поисковике бизнесом и/или пациентом);
- `diagnostic_area` — аналитическое диагностическое направление;
- `region` — регион;
- `period` — календарный период;
- `source` — источник поисковых данных;
- `query_count` — число запросов, сообщённое соответствующим источником.

### Базовый grain

Основной факт хранится на уровне:

`source × keyword × region × period`

Одна строка отвечает на вопрос:

> сколько запросов по конкретному keyword было зафиксировано в конкретном поисковике в конкретном регионе за конкретный период (месяц).

### Grain агрегата по диагностическому направлению

Для анализа направлений используется уровень:

`source × region × period × diagnostic_area`

Здесь отдельные keywords уже объединяются в аналитическое направление по правилам, описанным ниже.

Полный набор технических таблиц и полей в этот документ намеренно не включён: его задача — показать логику аналитического проектирования, а не дублировать модель БД.

---

## 3. Ключевое семантическое решение: `keyword ↔ diagnostic_area`

Один поисковый запрос может содержательно относиться более чем к одному диагностическому направлению. Поэтому связь между `keyword` и `diagnostic_area` спроектирована как many-to-many.

Например, если один keyword действительно отражает интерес сразу к двум направлениям, его значение не делится искусственно в пропорции 60/40 или иной доле, для которой нет фактического основания. Полный `query_count` относится к каждому релевантному направлению.

Следствие этого решения принципиально важно для интерпретации:

> суммы разных `diagnostic_area` не являются взаимно исключающими частями одного общего рынка и не должны складываться между собой.

Дополнительно используется `include_in_area_aggregate`. Он позволяет сохранить саму связь `keyword ↔ diagnostic_area`, но исключить конкретный keyword из агрегата направления, если поисковая формулировка слишком широкая или искажает смысл общего показателя. При этом keyword остаётся доступен для отдельного анализа.

### Авторство решения

**Автор:** определение M:N-семантики и отказ от произвольного дробления спроса между направлениями.

**LLM:** помощь в технической формализации правила и реализации соответствующей логики в модели данных и SQL.

---

## 4. Ключевые аналитические решения

### 4.1. Сначала смысл запроса, потом частотность

Список keywords формировался не от самых частотных запросов самих по себе, а от вопроса:

> какие поисковые формулировки содержательно отражают интерес к конкретной диагностической задаче?

Подбор ключевых слов производился на основании здравого смысла и ручного анализа запросов в сервисе Yandex WordStat.


**Автор:** постановка семантического принципа и отбор предметной логики.

**LLM:** помощь в структурировании данных и технической реализации.

---

### 4.2. Три горизонта динамики

Для оценки изменения спроса используются три разных горизонта, потому что они отвечают на разные управленческие вопросы.

**Короткий горизонт (`quarter`)**  
Средний уровень последних 3 полных месяцев сравнивается со средним предыдущих 3 месяцев.

Назначение: увидеть недавнее движение, которое может быть связано с краткосрочными изменениями или сезонностью.

**Средний горизонт (`year`)**  
Средний уровень последних 12 полных месяцев сравнивается со средним предыдущих 12 месяцев.

Назначение: отделить более устойчивую динамику от внутригoдовых колебаний.

**Долгосрочный горизонт (`all_time`)**  
Используется CAGR между средним первых 12 месяцев доступной истории и средним последних 12 полных месяцев.

Назначение: показать структурное долгосрочное изменение без чрезмерной зависимости от одного стартового и одного конечного месяца.

**Автор:** определение бизнес-смысла трёх горизонтов.

**LLM:** предложение и техническая формализация конкретных окон расчёта и CAGR.

---

### 4.3. Рост по стране считается после агрегации регионов

Country-level рост нельзя получать как среднее процентов роста отдельных регионов.

Правильная последовательность:

1. для каждого месяца суммировать `query_count` всех регионов страны;
2. получить единый месячный ряд страны;
3. только после этого рассчитывать темп роста.

Так сохраняется экономический смысл показателя: он отвечает на вопрос об изменении **совокупного объёма спроса страны**, а не среднего поведения регионов.

**LLM:** подняла проблему и предложила корректный подход.

**Автор:** проверил смысл решения и принял его как правило модели.

---

### 4.4. Разделение расчётов между PostgreSQL и Tableau

Первоначально часть тяжёлых расчётов выполнялась в интерактивном контуре Tableau. На реальном объёме данных это сделало работу с дашбордом слишком медленной.

Проблема была замечена не на уровне «SQL выглядит сложным», а по фактическому поведению системы: визуализации обновлялись неприемлемо долго, быстро уменьшалось свободное место на жестком диске. После этого были проведены контрольные измерения и пересмотрена архитектура расчётов.

Принято решение:

- фиксированные и тяжёлые расчёты выполнять заранее в PostgreSQL;
- для повторно используемых сценариев создать специализированные `VIEW` и `MATERIALIZED VIEW`;
- в Tableau оставить только логику, которая действительно зависит от интерактивного выбора пользователя: фильтры, ranking, TOP-N и визуальное представление.

В качестве показательного примера, на одном контрольном запросе после переноса тяжёлой логики в специализированную витрину время выполнения снизилось примерно с **819 ms до 86.8 ms**.

**Автор:** заметил проблему производительности, инициировал проверку и предложил вынести тяжёлые расчёты из интерактивного Tableau-контура в специализированные витрины.

**LLM:** помогла провести технический анализ и подобрать реализацию через `VIEW` / `MATERIALIZED VIEW`.

---

### 4.5. Синтетический DEV-набор отделён от реальных данных

Для настройки Tableau до появления живых региональных данных был создан воспроизводимый синтетический набор данных по регионам и (полностью) для поисковика Google.

При этом были введены явные границы:

- национальные месячные Yandex Wordstat anchors — фактические;
- региональное распределение Yandex — синтетическое;
- Google — полностью синтетический источник;
- временная шкала сдвинута на 100 лет назад, чтобы DEV-данные нельзя было случайно принять за будущие живые данные;
- synthetic fixture предназначен для разработки и проверки аналитики, а не для утверждений о фактическом региональном рынке.

**Автор:** определил требования к fixture, правило сохранения реальных контрольных сумм, а также уровня рандомизации, чтобы данные по регионам не отличались просто пропорционально для разных направлений, и 100-летний временной сдвиг.

**LLM:** реализовала Python-генератор, проверки и техническую загрузку данных.

---

## 5. Как проверялась корректность

Проверка не ограничивалась тем, что SQL или Python завершились без ошибки.

### 5.1. Согласование с исходными Yandex anchors

Для каждого `keyword × month` сумма синтетических региональных значений Yandex должна точно совпадать с исходным общероссийским значением Wordstat.

Это проверяет, что региональное распределение не создаёт и не теряет общий объём спроса.

### 5.2. Grain и целостность данных

Проверялись:

- ожидаемое число строк;
- уникальность grain;
- обязательные значения;
- внешние связи;
- временной охват;
- согласование source → target;
- отсутствие частично загруженного fixture.

Сам факт успешного выполнения кода не считается достаточным доказательством корректности.

### 5.3. Независимый пересчёт growth-метрик

Для `mart.search_demand_keyword_growth` все **498 строк** были независимо пересчитаны непосредственно из исходного staging-уровня.

Сравнивались:

- `latest_month_query_count`;
- `current_level`;
- `previous_level`;
- `growth_pct`.

Расхождений не обнаружено.

Это особенно важно, потому что такая проверка не использует саму витрину как источник истины.

### 5.4. Проверка разнообразия synthetic regional patterns

Отдельно проверялось, что синтетические региональные профили не являются простыми пропорциональными копиями одного шаблона.

Для этого анализировались корреляции региональных профилей и совпадение регионов-лидеров между разными рядами.

Цель этой проверки — подтвердить **разнообразие и непротиворечивость DEV-набора**, что, впрочем, не предполагает реалистичного распределения по регионам.

### 5.5. Проверка производительности после архитектурного изменения

После появления специализированных mart-объектов повторно выполнялись контрольные запросы.

Тесты подтвердили, что перенос тяжёлой логики из интерактивного пути Tableau действительно дал практический эффект и сделал дальнейшую работу с дашбордом реалистичной.

---

## 6. Граница ответственности автора и AI

Проект разрабатывался с помощью ChatGPT/Codex. SQL, Python и значительная часть тестов создавались LLM по техническим заданиям и уточнениям автора. Человек определял бизнес-задачу, семантику, критерии и принимал результат; LLM писала основную часть SQL/Python/tests и помогала технически формализовать решения; обычного ручного code review не было.

## 7. Известные ограничения

- Search Demand в текущем виде работает на DEV synthetic fixture, а не на живых региональных данных.
- Yandex national anchors фактические, но региональное распределение синтетическое.
- Google-данные полностью синтетические и не являются оценкой реального Google search volume.
- Поисковый спрос — proxy интереса, а не продажи, выручка или размер рынка.
- Обновление данных и визуализации через API/raw слой не реализованы.
- Автоматическое ежемесячное обновление materialized views не реализовано; refresh выполняется вручную.





