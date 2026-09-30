# REPORT CLARIFICATIONS — HISTORICAL Y0 BASELINE V1

Дата составления: 2026-09-30.

Это дополнение после review к существующему final run, а не новый эксперимент. Оно не изменяет [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md), исходный отчёт, predictions, metrics, bootstrap, samples, модель или методику.

## A. Directional accuracy

В коде применяется точная формула `mean(sign(actual_log_return) == sign(predicted_log_return))` через `numpy.sign`. Tolerance, порог или отдельная direction-модель отсутствуют.

На test из 484 наблюдений actual returns: 249 положительных, 231 отрицательный и 4 нулевых. Ridge predictions: 240 положительных, 244 отрицательных и 0 нулевых. No-change predictions: 484 нулевых.

- no-change directional accuracy: `4 / 484 = 0.0083`;
- Ridge directional accuracy: `0.5083`;
- actual zero share: `0.0083`;
- no-change predicted zero share: `1.0000`.

Следовательно, no-change получает верный знак только в четырёх случаях нулевого actual return. Разница 50.83% против 0.83% не является доказательством преимущества прогнозирования направления: исходная sign-метрика асимметрично штрафует постоянный нулевой baseline. В freeze не добавляются пороги, новые direction-модели или альтернативные метрики.

## B. MAE, RMSE и единицы

На общем test Ridge хуже no-change по MAE log-return (`0.00720524` против `0.00719484`) и RMSE log-return (`0.00964411` против `0.00961992`). В 2025 Ridge немного лучше по MAE (`0.00620313` против `0.00621327`), но хуже по RMSE (`0.00840164` против `0.00837372`). Поэтому фраза «модель победила в 2025» без указания метрики некорректна.

Price-space MAE следует читать только как ошибку **в единицах исходного ряда**. Валюта и единица в сохранённых входных материалах не подтверждены и остаются `UNKNOWN`; CNY/тонна или иная единица сюда не подставляется. MAE skill — относительная разница MAE log-return, а не процент ошибки цены.

Bootstrap использует парный moving block (20 последовательных test-записей, 2,000 повторов, seed `20260930`): mean loss delta `+0.0000104033`, 95% CI `[-0.0000410812, +0.0000662772]`. Интервал включает ноль: устойчивое преимущество не установлено. Это не доказывает равенство моделей и не доказывает принципиальную непредсказуемость цены.

## C. Published bars и continuous series

Сохранённый target: `log(close_next_published_session / close_t)`.

Следующий опубликованный бар не равен независимо подтверждённой следующей торговой сессии. Lag и rolling windows считаются по опубликованной последовательности при текущих ограничениях. Отсутствие invalid bars в supervised period не доказывает полноту календаря. Методика выбора основного контракта, roll и adjustment continuous series остаётся `UNKNOWN`.

Итог относится только к retrospective EOD experiment по опубликованному ряду Sina Y0; это не strict point-in-time торговая воспроизводимость и не утверждение о другом ценовом инструменте.

## D. Warm-up и исключённые candidate dates

В 2015–2025 имеется 2,674 валидных баров. Для sample требуется 21 последовательный валидный исходный бар. Для первого sample `feature_date=2015-01-05` были использованы 21 бар warm-up от `2014-12-04` до `2015-01-05` включительно; данные до 2015 года не стали supervised samples.

Три candidate feature dates исключены ровно один раз:

| feature date | target date | reason |
| --- | --- | --- |
| 2021-12-31 | 2022-01-04 | target_crosses_split_boundary |
| 2023-12-29 | 2024-01-02 | target_crosses_split_boundary |
| 2025-12-31 | 2026-01-05 | target_outside_experiment_period |

Проверяемая сверка: `2,674 candidates − 3 exclusions = 2,671 supervised samples`; `1,704 train + 483 validation + 484 test = 2,671`.

OHLC issues `2007-05-30` и `2007-07-18` находятся до warm-up периода и не затронули ни supervised period, ни 2014-12-04..2015-01-05 warm-up.
