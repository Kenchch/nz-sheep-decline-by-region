# checks.R ---------------------------------------------------------------
# Five rules, one reconciliation, and a demonstration that the rules can fail.
# The point is not to assert that the data are perfect; it is to report, in a
# form a reader can audit, exactly where and by how much they are not.

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(tidyr)
  library(validate)
})

source("R/load.R")

livestock <- load_livestock()

rules <- validator(
  head_non_negative    = is.na(head) | head >= 0,
  value_iff_suppressed = is.na(head) == suppressed,
  region_label_present = !is.na(region),
  no_duplicate_cells   = is_unique(year, area_code, livestock_class),
  # Census years are full-coverage collections, so a census-year cell should
  # not be suppressed. Written as an implication: FALSE <= TRUE, so this holds
  # unless a census-year cell is suppressed. It can genuinely fail — it is the
  # rule that would fire if a future vintage suppressed a census-year cell.
  census_year_reported = is_census_year <= !suppressed
)

results <- summary(confront(livestock, rules)) |>
  select(rule = name, items, passes, fails, nNA)

# A rule that cannot fail is not evidence. The same five rules are confronted
# with a deliberately corrupted copy of the table, so a reader can see which
# corruption each rule catches rather than taking an all-green table on trust.
corrupt <- function(x) {
  broken <- x
  broken$head[which(!is.na(broken$head))[3]] <- -1          # negative count
  i <- which(broken$suppressed)[1]
  broken$head[i] <- 0                                       # suppressed -> zero
  j <- which(broken$is_census_year & !is.na(broken$head))[1]
  broken$head[j] <- NA                                      # census gap
  broken$suppressed[j] <- FALSE
  broken$region[5] <- NA_character_                          # lost label
  rbind(broken, broken[1, ])                                # duplicate cell
}

results_corrupted <- summary(confront(corrupt(livestock), rules)) |>
  select(rule = name, items, passes, fails, nNA)

# Coverage is deliberately reported rather than asserted, because it is
# genuinely incomplete: 2003-2009 carry fewer region codes than the rest of the
# series, and a test that failed every year from 2003 to 2009 would be noise,
# not information.
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

# A second reconciliation that this analysis does no summing for: the two
# published island totals against the published national total. All three are
# aggregates, always published, never suppressed. If they disagree, the
# disagreement is in the source table rather than in anything done here.
island_reconciliation <- livestock |>
  filter(area_code %in% c("10", "19", "20")) |>
  select(year, livestock_class, area_code, head) |>
  pivot_wider(names_from = area_code, values_from = head, names_prefix = "a") |>
  mutate(residual = a20 - (a10 + a19))

# Every class-year, not just sheep, classified by whether the region row is
# complete. This is what lets the report state the residual in tiers instead of
# as a single over-general claim.
residual_tiers <- livestock |>
  regions_only() |>
  group_by(year, livestock_class) |>
  summarise(regions_present = n(), regions_suppressed = sum(suppressed),
            .groups = "drop") |>
  left_join(reconciliation, by = c("year", "livestock_class")) |>
  mutate(
    fully_published = regions_present == 17 & regions_suppressed == 0,
    tier = case_when(
      fully_published & residual == 0 ~ "Exact",
      fully_published                 ~ "Fully published, off by a few head",
      TRUE                            ~ "Incomplete region row"
    )
  )

if (sys.nframe() == 0) {
  dir.create("outputs", showWarnings = FALSE)
  write_csv(livestock,         "outputs/livestock_regional.csv")
  write_csv(results,           "outputs/validation-summary.csv")
  write_csv(results_corrupted, "outputs/validation-summary-corrupted.csv")
  write_csv(coverage,          "outputs/coverage-and-suppression.csv")
  write_csv(reconciliation,    "outputs/reconciliation.csv")
  write_csv(residual_tiers,    "outputs/residual-tiers.csv")
  write_csv(island_reconciliation, "outputs/island-reconciliation.csv")

  print(results)
  cat("\nSame rules against a deliberately corrupted copy:\n")
  print(results_corrupted)
  cat("\nResidual tiers, all three livestock classes:\n")
  residual_tiers |>
    count(tier) |>
    as.data.frame() |>
    print(row.names = FALSE)
  cat("\nLargest absolute residual among fully published class-years:",
      max(abs(residual_tiers$residual[residual_tiers$fully_published])), "head\n")
}
