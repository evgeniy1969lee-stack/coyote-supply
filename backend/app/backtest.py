"""Compare the weekday median with the previous week's usage on a demo holdout."""

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .demo_data import load_demo
from .forecast import aggregate_consumption, forecast_demand
from .replenishment import next_schedule


@dataclass
class Metrics:
    observed: int = 0
    median_available: int = 0
    last_week_available: int = 0
    paired: int = 0
    paired_usage: int = 0
    median_error: int = 0
    last_week_error: int = 0

    def add(self, actual: int, median: int | None, last_week: int | None) -> None:
        self.observed += 1
        self.median_available += median is not None
        self.last_week_available += last_week is not None
        if median is not None and last_week is not None:
            self.paired += 1
            self.paired_usage += actual
            self.median_error += abs(actual - median)
            self.last_week_error += abs(actual - last_week)

    def report(self) -> list[int | str]:
        def ratio(numerator: int, denominator: int) -> str:
            return f"{numerator / denominator:.3f}" if denominator else ""

        return [
            self.observed, self.median_available, self.last_week_available, self.paired,
            ratio(self.median_error, self.paired), ratio(self.last_week_error, self.paired),
            ratio(self.median_error, self.paired_usage), ratio(self.last_week_error, self.paired_usage),
        ]


def main() -> None:
    demo = load_demo()
    report = csv.writer(sys.stdout, lineterminator="\n")
    report.writerow([
        "store_id", "ingredient_id", "unit", "lead_days", "observed", "median_available",
        "last_week_available", "paired", "median_mae", "last_week_mae", "median_wape", "last_week_wape",
    ])
    for store in demo.stores:
        end = store.as_of_date
        history = aggregate_consumption(store, demo.recipes)
        metrics: dict[tuple[str, int], Metrics] = defaultdict(Metrics)
        for days_ago in range(14, 0, -1):
            origin = end - timedelta(days=days_ago)
            info = store.info.model_copy(update={
                "asOf": datetime.combine(origin, store.info.asOf.timetz()),
            })
            schedule = next_schedule(store.model_copy(update={"info": info}))
            if schedule is None:
                continue
            horizon = (min(schedule.nextArrivalDate, end) - origin).days
            dates = [origin + timedelta(days=lead) for lead in range(horizon)]
            for key, series in history.items():
                for lead, estimate in enumerate(forecast_demand(series, origin, dates)):
                    previous = estimate.date - timedelta(weeks=1)
                    baseline = series.quantities.get(previous) if previous < origin else None
                    actual = series.quantities.get(estimate.date)
                    if actual is not None:
                        median = estimate.quantity if not estimate.missing_recipe else None
                        metrics[key, lead].add(actual, median, baseline)
        for (key, lead), result in sorted(metrics.items()):
            report.writerow([store.info.storeId, key, demo.catalog[key].unit, lead, *result.report()])


if __name__ == "__main__":
    main()
