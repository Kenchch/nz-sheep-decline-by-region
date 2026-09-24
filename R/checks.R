# checks.R ---------------------------------------------------------------
# Five rules, one reconciliation, and a demonstration that the rules can fail.
# The point is not to assert that the data are perfect; it is to report, in a
# form a reader can audit, exactly where and by how much they are not.

# Relative paths throughout: stop with a clear message rather than "cannot
# open the connection" when run from anywhere but the repository root.
if (!file.exists("renv.lock")) {
  stop("Run from the repository root (the directory holding renv.lock).",
       call. = FALSE)
}

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(tidyr)
  library(validate)
})

source("R/load.R")
source("R/tables.R")

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

  stopifnot("each corruption must land on its own row" =
              !anyDuplicated(c(i_neg, i_zero, i_census, i_label, i_dup)),
            "the fixture has too few rows for one of the corruptions" =
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

coverage <- build_coverage(livestock)

# 2014 is where the national dairy herd peaks in this sample. It was chosen
# after looking at the series, so a split there maximises the before/after
# contrast by construction; the report says so, and this asserts it is still
# the peak.
DAIRY_PEAK_YEAR <- 2014L
nat_dairy_series <- livestock |> filter(area_code == "20", livestock_class == "Dairy cattle")
stopifnot("DAIRY_PEAK_YEAR must be the in-sample national dairy peak" =
            nat_dairy_series$year[which.max(nat_dairy_series$head)] == DAIRY_PEAK_YEAR)
# The most recent census, for the design-matched census-to-census window.
LAST_CENSUS <- max(CENSUS_YEARS[CENSUS_YEARS <= END_YEAR])
COMPARISON_WINDOWS <- list(c(START_YEAR, DAIRY_PEAK_YEAR),
                           c(DAIRY_PEAK_YEAR, END_YEAR),
                           c(START_YEAR, LAST_CENSUS))

# All three classes, per window: named for what it holds, not only dairy.
class_windows <- build_class_windows(livestock, COMPARISON_WINDOWS)
reconciliation <- build_reconciliation(livestock)
island_reconciliation <- build_island_reconciliation(livestock)
residual_tiers <- build_residual_tiers(livestock, reconciliation)

# Every livestock code in the extract, not only the three analysed: the years
# in which the confidentiality flag appears. Computed here so the report does
# not read and hash the extract a second time.
all_c_years <- all_suppression_years("c", raw)
N_CODES <- length(unique(raw$livestock_agr_agr_003))

if (sys.nframe() == 0) {
  dir.create("outputs", showWarnings = FALSE)
  # A missing value is written as an empty field, the same way the extract
  # carries one; the loader rejects a literal "NA" on the way in, so the
  # outputs do not use it on the way out either.
  write_out <- function(x, file) write_csv(x, file.path("outputs", file), na = "")
  write_out(livestock,             "livestock_regional.csv")
  write_out(results,               "validation-summary.csv")
  write_out(results_corrupted,     "validation-summary-corrupted.csv")
  write_out(class_windows,         "class-comparison-windows.csv")
  write_out(coverage,              "coverage-and-suppression.csv")
  write_out(reconciliation,        "reconciliation.csv")
  write_out(residual_tiers,        "residual-tiers.csv")
  write_out(island_reconciliation, "island-reconciliation.csv")

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
