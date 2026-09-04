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
  # This rule encodes an assumption that turns out to be false. It fails 9
  # times on the current vintage: four confidentiality cells in 2012 (Nelson
  # and Chatham Islands) and five quality-suppressed cells in 2017 and 2022,
  # all Nelson. It is kept because the falsification is the finding —
  # withholding is keyed to confidentiality and imputation level, not to
  # coverage. Written as an implication: FALSE <= TRUE, so it holds unless a
  # census-year cell is withheld.
  census_year_reported = is_census_year <= !suppressed
)

results <- summary(confront(livestock, rules)) |>
  select(rule = name, items, passes, fails, nNA)

# A rule that cannot fail is not evidence. The same five rules are confronted
# with a deliberately corrupted copy of the table, so a reader can see which
# corruption each rule catches rather than taking an all-green table on trust.
corrupt <- function(x) {
  broken <- x

  # Each corruption targets one rule, and each lands on a different row, so a
  # rule that moves can only have moved for its own reason. The row indices are
  # asserted to be distinct rather than assumed: an earlier version of this
  # function put the census-year corruption on row 1 and then duplicated row 1,
  # which made one corruption count twice.
  i_neg    <- which(!is.na(broken$head) & !broken$suppressed)[3]
  i_zero   <- which(broken$suppressed)[1]
  # A census-year cell that IS withheld. This is the direction the rule tests:
  # clearing the flag instead would only satisfy it further.
  i_census <- which(broken$is_census_year & !is.na(broken$head) &
                      !broken$suppressed)[200]
  i_label  <- which(!is.na(broken$head) & !broken$suppressed)[500]
  i_dup    <- which(!broken$suppressed & !is.na(broken$head) &
                      !is.na(broken$region))[900]

  stopifnot(!anyDuplicated(c(i_neg, i_zero, i_census, i_label, i_dup)),
            !anyNA(c(i_neg, i_zero, i_census, i_label, i_dup)))

  broken$head[i_neg]         <- -1              # negative count
  broken$head[i_zero]        <- 0               # withheld cell filled with zero
  broken$head[i_census]      <- NA              # census-year cell withheld
  broken$suppressed[i_census] <- TRUE
  broken$region[i_label]     <- NA_character_   # lost label

  rbind(broken, broken[i_dup, ])                # duplicated cell
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
