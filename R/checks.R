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

# Read once: the analysis table and the all-codes flag check share the bytes.
raw       <- read_raw()
livestock <- load_livestock(raw = raw)

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
  #
  # It sees flagged cells only. A row that is absent from the export — the
  # way cells were withheld before 2012 — is invisible to it, so 9 is a lower
  # bound on census-year withholding, not a count of it.
  census_year_reported = is_census_year <= !suppressed
)

# validate does not raise by default: a rule that errors is recorded with
# error = TRUE and fails = 0, which would print as a clean pass. The same goes
# for a rule that evaluates to NA. Both are refused here rather than trusted.
summarise_rules <- function(data) {
  s <- summary(confront(data, rules))
  stopifnot("a validation rule errored or warned" = !any(s$error | s$warning),
            "a validation rule evaluated to NA" = all(s$nNA == 0))
  select(s, rule = name, items, passes, fails, nNA)
}

results <- summarise_rules(livestock)

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

results_corrupted <- summarise_rules(corrupt(livestock))

# Keyed by rule name, not by position, so reordering the validator cannot
# silently pair a delta with the wrong rule.
expected_delta <- c(head_non_negative = 1L, value_iff_suppressed = 1L,
                    region_label_present = 1L, no_duplicate_cells = 2L,
                    census_year_reported = 1L)
observed_delta <- setNames(as.integer(results_corrupted$fails - results$fails),
                           results$rule)
stopifnot(
  "real and corrupted summaries must list the same rules in the same order" =
    identical(results$rule, results_corrupted$rule),
  "each corruption must move exactly its own rule" =
    identical(observed_delta[names(expected_delta)], expected_delta),
  "only census_year_reported may fail on the real data" =
    all(results$fails[results$rule != "census_year_reported"] == 0)
)

# Three of the five rules cannot fail on anything load_livestock() returns,
# because ingestion already stops on a negative count, a value/flag mismatch
# or an unmapped code. On the real data their zeroes restate the ingestion
# contract; the corrupted copy is what shows the rules themselves can fire.

# Coverage is deliberately reported rather than asserted, because it is
# genuinely incomplete: for sheep, 2003-2006, 2008 and 2009 carry fewer region
# codes than the rest of the series (2007 is complete), and a test that failed
# in each of those years would be noise, not information.
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
  mutate(
    regions_expected = N_REGIONS,
    regions_absent = regions_expected - regions_present,
    suppression_rate = regions_suppressed / regions_present,
    suppression_rate_all_regions = regions_suppressed / regions_expected
  )

# The identity below cannot fail: load.R already guarantees
# is.na(head) == suppressed rowwise, so regions_with_value + regions_suppressed
# is regions_present by construction, and regions_absent is 17 - regions_present.
# It is kept as documentation of the decomposition, but the check that can
# actually fail is the one on the grid: group_by(year) emits no row for a year
# with no regional cells at all, which would drop that year from the coverage
# table silently rather than reporting it as wholly absent.
stopifnot("coverage must have a row for every expected year" =
            identical(sort(coverage$year), EXPECTED_YEARS),
          "no year can have more regions than AREA defines" =
            all(coverage$regions_absent >= 0),
          all(coverage$regions_with_value + coverage$regions_suppressed +
                coverage$regions_absent == coverage$regions_expected))

# National totals avoid treating absent/suppressed regional cells as zero.
# All classes are headcounts, not feed-equivalent stock units.
#
# 2014 is where the national dairy herd peaks in this sample. It was chosen
# after looking at the series, so a split there maximises the before/after
# contrast by construction; the report says so.
DAIRY_PEAK_YEAR <- 2014L
# The most recent census, for the design-matched census-to-census window.
LAST_CENSUS <- max(CENSUS_YEARS[CENSUS_YEARS <= END_YEAR])
COMPARISON_WINDOWS <- list(c(START_YEAR, DAIRY_PEAK_YEAR),
                           c(DAIRY_PEAK_YEAR, END_YEAR),
                           c(START_YEAR, LAST_CENSUS))

# All three classes, per window: named for what it holds, not only dairy.
class_windows <- bind_rows(lapply(COMPARISON_WINDOWS, function(window) {
  livestock |>
    filter(area_code == "20", year %in% window) |>
    select(livestock_class, year, head) |>
    pivot_wider(names_from = year, values_from = head) |>
    transmute(start_year = window[1], end_year = window[2], livestock_class,
              start_head = .data[[as.character(window[1])]],
              end_head = .data[[as.character(window[2])]],
              change_head = end_head - start_head,
              change_pct = 100 * change_head / start_head,
              start_design = ifelse(window[1] %in% CENSUS_YEARS, "census", "survey"),
              end_design = ifelse(window[2] %in% CENSUS_YEARS, "census", "survey"))
}))
stopifnot("every window must have every class" =
            nrow(class_windows) == length(COMPARISON_WINDOWS) * length(LIVESTOCK),
          "a window endpoint is missing" = !anyNA(class_windows),
          all(class_windows$start_head > 0))

# Reconciliation: sum of non-aggregate regions against the published national
# total, reported as a residual per year. No fixed tolerance is asserted; the
# residual is the finding.
# The one published national cell of a class-year, asserted rather than
# summed. load.R already requires it, but sum() would hide a breach: sum() of
# an empty selection is 0, and with na.rm a suppressed total would also become
# 0, so either failure would be reported as a rounding discrepancy.
one_published <- function(x) {
  if (length(x) != 1L || is.na(x)) {
    stop("A class-year does not have exactly one published national total.",
         call. = FALSE)
  }
  x
}

reconciliation <- livestock |>
  group_by(year, livestock_class) |>
  summarise(
    # na.rm on the regional sum is load-bearing: suppressed cells are meant to
    # drop out and surface as residual.
    region_sum = sum(head[!is_aggregate], na.rm = TRUE),
    published  = one_published(head[area_code == "20"]),
    .groups    = "drop"
  ) |>
  mutate(
    residual     = published - region_sum,
    residual_pct = if_else(published > 0, 100 * residual / published, NA_real_)
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
    # Derived, not a literal 17: a hardcoded copy here would silently mis-tier
    # every class-year if AREA ever gained or lost a region code.
    fully_published = regions_present == N_REGIONS & regions_suppressed == 0,
    tier = case_when(
      fully_published & residual == 0 ~ "Exact",
      fully_published                 ~ "Fully published, off by a few head",
      TRUE                            ~ "Incomplete region row"
    )
  )

# group_by() emits no row for a class-year with no regional rows at all, which
# would shrink every "N of the 72 class-years" statement without an error.
stopifnot("residual_tiers must cover every class-year" =
            nrow(residual_tiers) == length(EXPECTED_YEARS) * length(LIVESTOCK),
          "every class-year must be tiered" = !anyNA(residual_tiers$tier))

# Every livestock code in the extract, not only the three analysed: the years
# in which the confidentiality flag appears. Computed here so the report does
# not read and hash the extract a second time.
all_c_years <- all_suppression_years("c", raw)

if (sys.nframe() == 0) {
  dir.create("outputs", showWarnings = FALSE)
  write_csv(livestock,         "outputs/livestock_regional.csv")
  write_csv(results,           "outputs/validation-summary.csv")
  write_csv(results_corrupted, "outputs/validation-summary-corrupted.csv")
  write_csv(class_windows,     "outputs/dairy-comparison-windows.csv")
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
  # max() of an empty selection is -Inf with a warning, so the empty case is
  # named rather than printed as a number.
  fp_residual <- abs(residual_tiers$residual[residual_tiers$fully_published])
  cat("\nLargest absolute residual among fully published class-years:",
      if (length(fp_residual)) paste(max(fp_residual), "head") else "none", "\n")
}
