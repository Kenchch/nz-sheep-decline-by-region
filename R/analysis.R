# analysis.R -------------------------------------------------------------
# Pure helpers for the report. Each takes a table and returns a value, reads
# no files and no globals, so tests/test-r-analysis.R can check it on a small
# fixture instead of relying only on the byte comparison of outputs/*.csv, which
# the figures and the prose never reach.

suppressPackageStartupMessages({
  library(dplyr)
  library(tidyr)
})

# Numbers for prose. Keeps trailing zeros ("2.50", not "2.5"), never switches
# to scientific notation or drops digits past the seventh significant one, and
# adds 0 so that a value rounding to zero prints as "0.000" rather than "-0.000".
fmt <- function(x, digits = 0) {
  formatC(round(x, digits) + 0, format = "f", digits = digits, big.mark = ",")
}

# Change in one livestock class between two years, one row per region. Regions
# missing either endpoint stay in the table with change = NA, so they can be
# counted and named, never read as a fall to zero.
endpoint_change <- function(regions, class, y0, y1) {
  regions |>
    filter(livestock_class == class, year %in% c(y0, y1)) |>
    select(region, year, head) |>
    pivot_wider(names_from = year, values_from = head, names_prefix = "y") |>
    transmute(region,
              start  = .data[[paste0("y", y0)]],
              end    = .data[[paste0("y", y1)]],
              change = end - start,
              pct    = 100 * change / start) |>
    arrange(change)
}

# The headline statistic for one window: the share of the gross regional fall
# taken by the three largest declines, next to the share of the starting flock
# those three regions held. Without the second number the first cannot say
# whether the decline is concentrated or merely proportional to size.
top3_for <- function(regions, y0, y1, class = "Sheep") {
  ch <- endpoint_change(regions, class, y0, y1) |> filter(!is.na(change))
  falls <- ch |> filter(change < 0)
  if (nrow(falls) < 3L) {
    stop("Fewer than three measurable regions declined over ", y0, "-", y1,
         "; a top-three share would include gains.", call. = FALSE)
  }
  top <- head(falls, 3)
  data.frame(
    start      = y0,
    end        = y1,
    regions    = nrow(ch),
    fall       = -sum(falls$change),
    net_fall   = -sum(ch$change),
    share      = 100 * sum(top$change) / sum(falls$change),
    base_share = 100 * sum(top$start) / sum(ch$start),
    third_gap  = falls$change[4] - falls$change[3],
    top3       = paste(top$region, collapse = ", ")
  )
}

# How many regions lost dairy cattle over a window, among regions where both
# sheep and dairy are published at both ends. zero_both counts regions with no
# dairy cattle at either end, which sit in the denominator without being able
# to move in either direction.
dairy_window_counts <- function(regions, y0, y1) {
  sheep <- endpoint_change(regions, "Sheep", y0, y1) |>
    filter(!is.na(change)) |> select(region, sheep = change)
  dairy <- endpoint_change(regions, "Dairy cattle", y0, y1) |>
    filter(!is.na(change)) |> select(region, dairy = change, dairy_start = start,
                                     dairy_end = end)
  both <- inner_join(sheep, dairy, by = "region")
  list(n = nrow(both),
       fell = sum(both$dairy < 0),
       zero_both = sum(both$dairy_start == 0 & both$dairy_end == 0),
       regions = sort(both$region))
}

# Number of windows in which a region is among the top three. Splits on the
# separator rather than substring-matching, so a region whose name is part of
# another's could never be over-counted.
count_in_top3 <- function(top3, name) {
  sum(vapply(strsplit(top3, ", ", fixed = TRUE),
             function(x) name %in% x, logical(1)))
}

# Every expected region-class-year cell, marked as published, withheld (with
# its flag) or absent from the export. Before 2012 the export omits cells
# instead of flagging them, so a chart of flags alone reads the change of
# export format as a change in withholding.
cell_status_grid <- function(regions, years, classes, region_names) {
  tidyr::expand_grid(year = years, livestock_class = classes,
                     region = region_names) |>
    left_join(regions |> select(year, livestock_class, region, head,
                                suppression_code),
              by = c("year", "livestock_class", "region")) |>
    mutate(status = case_when(
      suppression_code == "c" ~ "C",
      suppression_code == "s" ~ "S",
      !is.na(head)            ~ "Published",
      TRUE                    ~ "Absent"
    ))
}

# Share of values above a threshold among the last n, for statements such as
# "has exceeded ten percent in 2 of the last 4 years".
recent_above <- function(values, threshold, n) {
  recent <- utils::tail(values, n)
  list(above = sum(recent > threshold), of = length(recent))
}
