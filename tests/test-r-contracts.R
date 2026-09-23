# Run from the repository root: Rscript tests/test-r-contracts.R
# Negative fixtures for the ingestion contract in R/load.R. Plain base-R
# assertions, no test framework; the code under test needs readr, dplyr,
# janitor and digest, all pinned in renv.lock.
source("R/load.R")

failures <- character()

# Every test runs, and all failures are reported together at the end, so one
# broken contract does not hide the state of the others.
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

raw_fixture <- read_raw()

# Bypass only the file read: these tests exercise the shape contract on an
# in-memory copy, independently of the hash that protects the real extract.
load_fixture <- function(raw) {
  assert_extract_shape(raw)
  load_livestock(raw = raw)
}

row_of <- function(code, area, year) {
  which(raw_fixture$livestock_agr_agr_003 == code &
          raw_fixture$area_agr_agr_003 == area &
          raw_fixture$year_agr_agr_003 == year)
}
regional_row <- row_of("6731", "1", "2025")
island_row   <- row_of("6731", "10", "2025")
national_row <- row_of("6731", "20", "2025")
suppressed_row <- which(raw_fixture$livestock_agr_agr_003 == "6731" &
                          raw_fixture$year_agr_agr_003 == "2025" &
                          !is.na(raw_fixture$obs_status))[1]
stopifnot(length(regional_row) == 1L, length(island_row) == 1L,
          length(national_row) == 1L, !is.na(suppressed_row))

for (year in c("2025.9", "not-a-year", NA_character_)) {
  test(paste("year", year), {
    raw <- raw_fixture
    raw$year_agr_agr_003[regional_row] <- year
    expect_error(load_fixture(raw), "missing or invalid YEAR")
  })
}

# as.numeric() accepts every one of these; a head count is a whole number.
for (value in c("Inf", "-Inf", "NaN", "1e999", "not-a-number",
                "0x1A", "1.5", "-5", "1e3", " 5")) {
  test(paste("value", value), {
    raw <- raw_fixture
    raw$obs_value[regional_row] <- value
    expect_error(load_fixture(raw), "not a non-negative whole number")
  })
}

test("a 400-digit count cannot be represented", {
  raw <- raw_fixture
  raw$obs_value[regional_row] <- strrep("9", 400)
  expect_error(load_fixture(raw), "too large to represent")
})

# A malformed token must not masquerade as a legitimate suppressed blank.
test("token in a withheld cell", {
  raw <- raw_fixture
  raw$obs_value[suppressed_row] <- "withheld"
  expect_error(load_fixture(raw), "not a non-negative whole number")
})

test("island total absent", {
  expect_error(load_fixture(raw_fixture[-island_row, ]), "published island total")
})
test("island total suppressed", {
  raw <- raw_fixture
  raw$obs_value[island_row] <- NA_character_
  raw$obs_status[island_row] <- "s"
  expect_error(load_fixture(raw), "published island total")
})

test("national total absent", {
  expect_error(load_fixture(raw_fixture[-national_row, ]), "published national total")
})
# Without this, dropping the is.na(head) half of the national guard passed
# every test: the suppressed total would reach checks.R as NA.
test("national total suppressed", {
  raw <- raw_fixture
  raw$obs_value[national_row] <- NA_character_
  raw$obs_status[national_row] <- "s"
  expect_error(load_fixture(raw), "published national total")
})

test("duplicate cell", {
  expect_error(load_fixture(rbind(raw_fixture, raw_fixture[regional_row, ])),
               "duplicate cells: Sheep 1 2025")
})
test("unmapped area", {
  raw <- raw_fixture
  raw$area_agr_agr_003[regional_row] <- "999"
  expect_error(load_fixture(raw), "unmapped AREA code: 999")
})
test("area code with a leading zero", {
  raw <- raw_fixture
  raw$area_agr_agr_003[regional_row] <- "01"
  expect_error(load_fixture(raw), "unmapped AREA code: 01")
})
test("unknown status", {
  raw <- raw_fixture
  raw$obs_status[regional_row] <- "unknown"
  expect_error(load_fixture(raw), "unknown OBS_STATUS")
})
test("flag on a published value", {
  raw <- raw_fixture
  raw$obs_status[regional_row] <- "s"
  expect_error(load_fixture(raw), "every suppressed cell must be missing")
})
test("missing column", {
  expect_error(load_fixture(raw_fixture[, names(raw_fixture) != "obs_value"]),
               "missing required column")
})
test("unexpected column", {
  raw <- raw_fixture
  raw$unit_measure <- "head"
  expect_error(load_fixture(raw), "unexpected column(s): unit_measure")
})
test("other dataflow", {
  raw <- raw_fixture
  raw$dataflow[1] <- "STATSNZ:SOMETHING_ELSE(2.0)"
  expect_error(load_fixture(raw), "DATAFLOW other than")
})
test("livestock class absent", {
  expect_error(load_fixture(raw_fixture[raw_fixture$livestock_agr_agr_003 != "7077", ]),
               "lacks livestock code(s): 7077")
})
test("sheep code with a leading zero", {
  raw <- raw_fixture
  raw$livestock_agr_agr_003[raw$livestock_agr_agr_003 == "6731"] <- "06731"
  expect_error(load_fixture(raw), "lacks livestock code(s): 6731")
})
test("year missing", {
  expect_error(load_fixture(raw_fixture[raw_fixture$year_agr_agr_003 != "2010", ]),
               "Missing: 2010")
})
test("year beyond the window", {
  raw <- raw_fixture[raw_fixture$year_agr_agr_003 == "2025", ]
  raw$year_agr_agr_003 <- "2026"
  expect_error(load_fixture(rbind(raw_fixture, raw)), "unexpected: 2026")
})

test("SOURCE.md must record exactly one hash", {
  md <- tempfile(fileext = ".md")
  on.exit(unlink(md))
  writeLines("| SHA-256 | none |", md)
  expect_error(recorded_sha256(md), "exactly one SHA-256 row")
  writeLines(rep(paste0("| SHA-256 | `", strrep("a", 64), "` |"), 2), md)
  expect_error(recorded_sha256(md), "exactly one SHA-256 row")
})

test("the flag-year helper stays inside the window", {
  raw <- raw_fixture
  raw$obs_status[raw$year_agr_agr_003 == "1994"][1] <- "c"
  stopifnot(!1994L %in% all_suppression_years("c", raw))
  raw$year_agr_agr_003[which(raw$obs_status == "c")[1]] <- "20x2"
  expect_error(all_suppression_years("c", raw), "invalid YEAR")
})

# The real hash gate still rejects changed bytes; the parser is then checked
# on its own so a malformed CSV reaches readr's problem check.
test("hash gate and CSV parser", {
  csv <- tempfile(fileext = ".csv")
  on.exit(unlink(csv))
  writeLines(c(
    "LIVESTOCK_AGR_AGR_003,AREA_AGR_AGR_003,YEAR_AGR_AGR_003,OBS_VALUE,OBS_STATUS",
    "6731,1,2025,100,,unexpected-field"
  ), csv)
  expect_error(read_raw(csv), "does not match the hash")
  expect_error(suppressWarnings(parse_raw(csv)), "parsing failure")

  # Exercise the real CSV parser: readr's default missing-value tokens would
  # otherwise erase a literal "NA" before the ingestion contracts see it.
  raw <- raw_fixture
  raw$obs_value[suppressed_row] <- "NA"
  write_csv(raw, csv, na = "")
  expect_error(load_livestock(raw = parse_raw(csv)), "not a non-negative whole number")

  raw <- raw_fixture
  raw$obs_status[regional_row] <- "NA"
  write_csv(raw, csv, na = "")
  expect_error(parse_raw(csv), "unknown OBS_STATUS")
})

# Successful ingestion must preserve the committed analysis table byte-for-byte.
test("committed analysis table unchanged", {
  csv <- tempfile(fileext = ".csv")
  on.exit(unlink(csv))
  write_csv(load_livestock(), csv)
  stopifnot(identical(digest::digest(file = csv, algo = "sha256"),
                      digest::digest(file = "outputs/livestock_regional.csv",
                                     algo = "sha256")))
})

if (length(failures)) {
  cat("FAILED", length(failures), "ingestion contract test(s):\n",
      paste0("  - ", failures, collapse = "\n"), "\n")
  quit(status = 1)
}
cat("R ingestion contracts passed; committed analysis table is unchanged.\n")
