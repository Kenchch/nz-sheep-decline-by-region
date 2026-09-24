# Run from the repository root: Rscript tests/test-r-tables.R
# The table builders in R/tables.R each assert their own completeness. These
# tests hand them the real analysis table with a piece removed and check that
# the assertion fires, so deleting an assertion turns this file red.
if (!file.exists("renv.lock")) {
  stop("Run from the repository root: Rscript tests/test-r-tables.R", call. = FALSE)
}
source("R/load.R")
source("R/tables.R")

failures <- character()
test <- function(name, code) {
  result <- tryCatch({ force(code); NULL }, error = conditionMessage)
  if (!is.null(result)) failures <<- c(failures, paste0(name, ": ", result))
}
expect_error <- function(expr, message) {
  error <- tryCatch({ force(expr); NULL }, error = identity)
  if (!inherits(error, "error")) {
    stop("expected an error containing '", message, "', got none", call. = FALSE)
  }
  if (!grepl(message, conditionMessage(error), fixed = TRUE)) {
    stop("expected an error containing '", message, "', got: ",
         conditionMessage(error), call. = FALSE)
  }
}

livestock <- load_livestock()
no_regions <- function(class, y) {
  livestock[!(livestock$livestock_class == class & livestock$year == y &
                !livestock$is_aggregate), ]
}

test("the builders accept the real table", {
  recon <- build_reconciliation(livestock)
  stopifnot(nrow(build_coverage(livestock)) == length(EXPECTED_YEARS),
            nrow(build_residual_tiers(livestock, recon)) ==
              length(EXPECTED_YEARS) * length(LIVESTOCK),
            nrow(build_island_reconciliation(livestock)) ==
              length(EXPECTED_YEARS) * length(LIVESTOCK))
})

test("one_published refuses none, two, or a withheld total", {
  expect_error(one_published(numeric(0)), "exactly one published national total")
  expect_error(one_published(c(1, 2)), "exactly one published national total")
  expect_error(one_published(NA_real_), "exactly one published national total")
  stopifnot(one_published(5) == 5)
})

test("reconciliation refuses a class-year without its national total", {
  x <- livestock[!(livestock$area_code == "20" & livestock$year == 2016L &
                     livestock$livestock_class == "Beef cattle"), ]
  expect_error(build_reconciliation(x), "exactly one published national total")
})

test("coverage refuses a year with no regional sheep rows", {
  expect_error(build_coverage(no_regions("Sheep", 2010L)), "Missing: 2010")
})

test("residual tiers refuse a class-year with no regional rows", {
  x <- no_regions("Beef cattle", 2016L)
  expect_error(build_residual_tiers(x, build_reconciliation(x)),
               "residual_tiers does not cover exactly the expected keys. Missing: 2016 Beef cattle")
})

test("class windows refuse a missing class", {
  x <- livestock[!(livestock$area_code == "20" & livestock$year == 2014L &
                     livestock$livestock_class == "Sheep"), ]
  expect_error(build_class_windows(x, list(c(2002L, 2014L))), "a window endpoint is missing")
})

test("island reconciliation refuses a missing island total", {
  x <- livestock[!(livestock$area_code == "10" & livestock$year == 2016L &
                     livestock$livestock_class == "Sheep"), ]
  expect_error(build_island_reconciliation(x), "all three aggregates")
})

test("assert_covers names duplicates", {
  expect_error(assert_covers(c("a", "a", "b"), c("a", "b"), "x"), "duplicated: a")
})

if (length(failures)) {
  cat("FAILED", length(failures), "table builder test(s):\n",
      paste0("  - ", failures, collapse = "\n"), "\n")
  quit(status = 1)
}
cat("R table builders passed.\n")
