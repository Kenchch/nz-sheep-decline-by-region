# tables.R ---------------------------------------------------------------
# The derived tables R/checks.R writes to outputs/, each built by a function
# that takes the analysis table and asserts its own completeness. They are
# functions, not top-level code, so tests/test-r-tables.R can hand them a
# broken fixture and check that each assertion fires: removing one makes a
# test fail instead of passing silently.
#
# Requires R/load.R (EXPECTED_YEARS, LIVESTOCK, N_REGIONS, CENSUS_YEARS,
# regions_only()).

suppressPackageStartupMessages({
  library(dplyr)
  library(tidyr)
})

# Stop unless `got` holds exactly the keys in `expected`, naming what differs.
assert_covers <- function(got, expected, what) {
  missing <- setdiff(expected, got)
  extra   <- setdiff(got, expected)
  if (length(missing) || length(extra) || anyDuplicated(got)) {
    stop(what, " does not cover exactly the expected keys. Missing: ",
         paste(utils::head(missing, 5), collapse = "; "),
         "; unexpected: ", paste(utils::head(extra, 5), collapse = "; "),
         "; duplicated: ", paste(utils::head(got[duplicated(got)], 5), collapse = "; "),
         call. = FALSE)
  }
  invisible(TRUE)
}

class_year_keys <- function(years = EXPECTED_YEARS, classes = unname(LIVESTOCK)) {
  as.vector(outer(years, classes, paste))
}

# Coverage is reported rather than asserted, because it is genuinely
# incomplete: for sheep, 2003-2006, 2008 and 2009 carry fewer region codes than
# the rest of the series. What is asserted is the grid: group_by(year) emits no
# row for a year with no regional cells at all, which would drop that year from
# the table that exists to report incompleteness.
build_coverage <- function(livestock) {
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
  assert_covers(coverage$year, EXPECTED_YEARS, "coverage")
  # load.R guarantees is.na(head) == suppressed rowwise, so the decomposition
  # below holds by construction; it documents the table rather than tests it.
  stopifnot("no year can have more regions than AREA defines" =
              all(coverage$regions_absent >= 0),
            "present regions split into published and withheld" =
              all(coverage$regions_with_value + coverage$regions_suppressed +
                    coverage$regions_absent == coverage$regions_expected))
  coverage
}

# Published national totals for each class over each window. Headcounts, not
# feed-equivalent stock units.
build_class_windows <- function(livestock, windows) {
  out <- bind_rows(lapply(windows, function(window) {
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
  assert_covers(paste(out$start_year, out$end_year, out$livestock_class),
                as.vector(outer(vapply(windows, paste, "", collapse = " "),
                                unname(LIVESTOCK), paste)),
                "class_windows")
  stopifnot("a window endpoint is missing" = !anyNA(out),
            "a window starts from a zero herd, so its percentage is undefined" =
              all(out$start_head > 0))
  out
}

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

# Sum of the regions against the published national total, per class-year.
# No tolerance is asserted; the residual is the finding.
build_reconciliation <- function(livestock) {
  out <- livestock |>
    group_by(year, livestock_class) |>
    summarise(
      # na.rm on the regional sum is load-bearing: withheld cells are meant to
      # drop out and surface as residual.
      region_sum = sum(head[!is_aggregate], na.rm = TRUE),
      published  = one_published(head[area_code == "20"]),
      .groups    = "drop"
    ) |>
    mutate(
      residual     = published - region_sum,
      residual_pct = if_else(published > 0, 100 * residual / published, NA_real_)
    )
  assert_covers(paste(out$year, out$livestock_class), class_year_keys(),
                "reconciliation")
  out
}

# The two published island totals against the published national total: three
# aggregates this analysis never sums, so a difference is the source table's.
build_island_reconciliation <- function(livestock) {
  out <- livestock |>
    filter(area_code %in% c("10", "19", "20")) |>
    select(year, livestock_class, area_code, head) |>
    pivot_wider(names_from = area_code, values_from = head, names_prefix = "a") |>
    mutate(residual = a20 - (a10 + a19))
  stopifnot("every island reconciliation needs all three aggregates" =
              !anyNA(out$residual))
  out
}

# Every class-year classified by whether its region row is complete, so the
# residual is reported in tiers rather than as one over-general claim.
build_residual_tiers <- function(livestock, reconciliation) {
  out <- livestock |>
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
  # group_by() emits no row for a class-year with no regional rows at all,
  # which would shrink every "N of the 72 class-years" statement silently.
  assert_covers(paste(out$year, out$livestock_class), class_year_keys(),
                "residual_tiers")
  stopifnot("every class-year must be tiered" = !anyNA(out$tier))
  out
}
