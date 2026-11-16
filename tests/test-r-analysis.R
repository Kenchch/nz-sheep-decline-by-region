# Run from the repository root: Rscript tests/test-r-analysis.R
# Unit tests for the pure helpers in R/analysis.R, on small hand-built
# fixtures whose answers can be checked by eye. The byte comparison of
# outputs/*.csv never reaches the figures or the prose, so these helpers need
# their own tests.
if (!file.exists("renv.lock")) {
  stop("Run from the repository root: Rscript tests/test-r-analysis.R", call. = FALSE)
}
source("R/analysis.R")

failures <- character()
test <- function(name, code) {
  result <- tryCatch({ force(code); NULL }, error = conditionMessage)
  if (!is.null(result)) failures <<- c(failures, paste0(name, ": ", result))
}

test("fmt keeps trailing zeros", stopifnot(identical(fmt(2.5, 2), "2.50")))
test("fmt keeps every digit of a large number",
     stopifnot(identical(fmt(1234567.891, 1), "1,234,567.9")))
test("fmt never prints negative zero",
     stopifnot(identical(fmt(-0.0004, 3), "0.000")))
test("fmt groups thousands",
     stopifnot(identical(fmt(c(-16319374, 588281)), c("-16,319,374", "588,281"))))

# Five regions. E is withheld at the end; D gains.
fixture <- data.frame(
  region = rep(c("A", "B", "C", "D", "E"), each = 2),
  livestock_class = "Sheep",
  year = rep(c(2002L, 2025L), 5),
  head = c(100, 40,   # A: -60
           80, 50,    # B: -30
           60, 40,    # C: -20
           10, 15,    # D: +5
           50, NA)    # E: withheld in 2025
)

test("endpoint_change keeps unmeasurable regions as NA", {
  ch <- endpoint_change(fixture, "Sheep", 2002L, 2025L)
  stopifnot(nrow(ch) == 5L, is.na(ch$change[ch$region == "E"]),
            identical(ch$region[1:4], c("A", "B", "C", "D")))
})

test("top3_for shares and base shares", {
  t3 <- top3_for(fixture, 2002L, 2025L)
  # Gross fall 110, top three are all of it; the three held 240 of 250 at start.
  stopifnot(t3$regions == 4L, t3$fall == 110, t3$net_fall == 105,
            isTRUE(all.equal(t3$share, 100)),
            isTRUE(all.equal(t3$base_share, 100 * 240 / 250)),
            is.na(t3$third_gap),
            identical(t3$top3, "A, B, C"))
})

test("top3_for refuses fewer than three declines", {
  few <- fixture
  few$head[few$region == "C" & few$year == 2025L] <- 70
  err <- tryCatch(top3_for(few, 2002L, 2025L), error = conditionMessage)
  stopifnot(is.character(err), grepl("Fewer than three", err))
})

test("dairy_window_counts counts falls and zero herds", {
  both <- rbind(
    fixture,
    data.frame(region = rep(c("A", "B", "C", "D", "E"), each = 2),
               livestock_class = "Dairy cattle",
               year = rep(c(2002L, 2025L), 5),
               head = c(5, 3,  0, 0,  1, 4,  2, 1,  3, 3))
  )
  w <- dairy_window_counts(both, 2002L, 2025L)
  stopifnot(w$n == 4L, w$fell == 2L, w$zero_both == 1L,
            identical(w$regions, c("A", "B", "C", "D")))
})

test("stock_unit_offset break-even and offset range", {
  # 100 sheep lost, 20 dairy gained: 5 sheep per dairy animal. With sheep at
  # 0.5-1 and dairy at 2-8, break-even is 2.5-5 and the offset 40%-320%.
  s <- stock_unit_offset(-100, 20, sheep_su = c(0.5, 1), dairy_su = c(2, 8))
  stopifnot(s$sheep_lost == 100, s$dairy_gained == 20, s$sheep_per_dairy == 5,
            isTRUE(all.equal(s$breakeven_low, 2.5)),
            isTRUE(all.equal(s$breakeven_high, 5)),
            isTRUE(all.equal(s$offset_low, 40)),
            isTRUE(all.equal(s$offset_high, 320)))
})

test("stock_unit_offset is NA unless sheep fell and dairy rose", {
  # both fell; sheep rose; dairy flat; a withheld endpoint
  s <- stock_unit_offset(c(-100, 10, -100, NA), c(-5, 5, 0, 5),
                         sheep_su = c(0.7, 1), dairy_su = c(2, 8.5))
  stopifnot(nrow(s) == 4L, all(is.na(as.matrix(s))))
})

test("stock_unit_offset refuses a reversed or non-positive range", {
  for (bad in list(c(1, 0.7), c(0, 1), c(1, Inf), 1)) {
    err <- tryCatch(stock_unit_offset(-1, 1, sheep_su = bad, dairy_su = c(2, 8.5)),
                    error = conditionMessage)
    stopifnot(is.character(err), grepl("lowest, highest", err))
  }
})

test("count_in_top3 matches whole names only", {
  stopifnot(count_in_top3(c("Otago, Southland, Canterbury",
                            "Central Otago, Southland, Tasman"), "Otago") == 1L)
})

test("cell_status_grid marks absent cells", {
  g <- cell_status_grid(
    data.frame(year = 2002L, livestock_class = "Sheep", region = c("A", "B"),
               head = c(1, NA), suppression_code = c(NA, "s")),
    years = 2002L, classes = "Sheep", region_names = c("A", "B", "C"))
  stopifnot(identical(g$status, c("Published", "S", "Absent")))
})

test("recent_above", {
  # The first four and the last four differ (2 and 1 above ten), so taking
  # the head instead of the tail fails.
  r <- recent_above(c(20, 5.9, 5.9, 11.8, 5.9), 10, 4)
  stopifnot(r$above == 1L, r$of == 4L)
})

if (length(failures)) {
  cat("FAILED", length(failures), "analysis helper test(s):\n",
      paste0("  - ", failures, collapse = "\n"), "\n")
  quit(status = 1)
}
cat("R analysis helpers passed.\n")
