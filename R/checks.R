# checks.R ---------------------------------------------------------------
# Five rules, and one reconciliation. The point is not to assert that the data
# are perfect; it is to report, in a form a reader can audit, exactly where and
# by how much they are not.

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(tidyr)
  library(validate)
})

source("R/load.R")

livestock <- load_livestock()

rules <- validator(
  head_non_negative     = is.na(head) | head >= 0,
  value_iff_suppressed  = is.na(head) == suppressed,
  region_label_present  = !is.na(region),
  no_duplicate_cells    = is_unique(year, area_code, livestock_class),
  year_in_series_window = in_range(year, min = 2002, max = 2025)
)

results <- summary(confront(livestock, rules)) |>
  select(rule = name, items, passes, fails, nNA)

# Coverage is deliberately reported rather than asserted, because it is
# genuinely incomplete: 2003-2009 carry fewer region
# codes than the rest of the series, and a test that failed every year from
# 2003 to 2009 would be noise, not information.
coverage <- livestock |>
  regions_only() |>
  filter(livestock_class == "Sheep") |>
  group_by(year) |>
  summarise(
    regions_present    = n(),
    regions_with_value = sum(!is.na(head)),
    regions_suppressed = sum(suppressed),
    .groups = "drop"
  ) |>
  mutate(suppression_rate = regions_suppressed / regions_present)

# Reconciliation: sum of non-aggregate regions against the published national
# total, reported as a residual per year. No fixed tolerance is asserted; the
# residual is the finding.
reconciliation <- livestock |>
  group_by(year, livestock_class) |>
  summarise(
    region_sum = sum(head[!is_aggregate], na.rm = TRUE),
    published  = sum(head[area_code == "20"], na.rm = TRUE),
    .groups    = "drop"
  ) |>
  mutate(
    residual     = published - region_sum,
    residual_pct = 100 * residual / published
  )

if (sys.nframe() == 0) {
  dir.create("outputs", showWarnings = FALSE)
  write_csv(results,        "outputs/validation-summary.csv")
  write_csv(coverage,       "outputs/coverage-and-suppression.csv")
  write_csv(reconciliation, "outputs/reconciliation.csv")

  print(results)
  cat("\nSheep: reconciliation residual by year (% of published national total)\n")
  reconciliation |>
    filter(livestock_class == "Sheep") |>
    left_join(select(coverage, year, suppression_rate), by = "year") |>
    mutate(across(c(residual_pct, suppression_rate), ~ round(.x, 4))) |>
    as.data.frame() |>
    print(row.names = FALSE)
}
