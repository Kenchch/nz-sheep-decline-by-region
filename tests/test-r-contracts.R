# Run from the repository root: Rscript tests/test-r-contracts.R
# Base-R assertions keep these ingestion regression tests dependency-free.
source("R/load.R")

expect_error <- function(expr, message) {
  error <- tryCatch({ force(expr); NULL }, error = identity)
  if (!inherits(error, "error") ||
      !grepl(message, conditionMessage(error), fixed = TRUE)) {
    stop("Expected an error containing: ", message, call. = FALSE)
  }
}

raw_fixture <- read_raw()

# Replace only the file-read boundary for a single call: these tests exercise
# the shape contract independently of the hash that protects the real extract.
load_fixture <- function(raw) {
  loader <- load_livestock
  environment(loader) <- list2env(
    list(read_raw = function(path) { assert_extract_shape(raw); raw }),
    parent = environment(load_livestock)
  )
  loader()
}

regional_row <- which(raw_fixture$livestock_agr_agr_003 == "6731" &
                        raw_fixture$area_agr_agr_003 == "1" &
                        raw_fixture$year_agr_agr_003 == "2025")
island_row <- which(raw_fixture$livestock_agr_agr_003 == "6731" &
                      raw_fixture$area_agr_agr_003 == "10" &
                      raw_fixture$year_agr_agr_003 == "2025")
national_row <- which(raw_fixture$livestock_agr_agr_003 == "6731" &
                        raw_fixture$area_agr_agr_003 == "20" &
                        raw_fixture$year_agr_agr_003 == "2025")
suppressed_row <- which(raw_fixture$livestock_agr_agr_003 == "6731" &
                          raw_fixture$year_agr_agr_003 == "2025" &
                          !is.na(raw_fixture$obs_status))[1]
stopifnot(length(regional_row) == 1L, length(island_row) == 1L,
          length(national_row) == 1L, !is.na(suppressed_row))

for (year in c("2025.9", "not-a-year", NA_character_)) {
  raw <- raw_fixture
  raw$year_agr_agr_003[regional_row] <- year
  expect_error(load_fixture(raw), "missing or invalid YEAR")
}

for (value in c("Inf", "-Inf", "NaN", "1e999", "not-a-number")) {
  raw <- raw_fixture
  raw$obs_value[regional_row] <- value
  expect_error(load_fixture(raw), "non-numeric or non-finite OBS_VALUE")
}

# A malformed token must not masquerade as a legitimate suppressed blank.
raw <- raw_fixture
raw$obs_value[suppressed_row] <- "withheld"
expect_error(load_fixture(raw), "non-numeric or non-finite OBS_VALUE")

expect_error(load_fixture(raw_fixture[-island_row, ]), "published island total")
raw <- raw_fixture
raw$obs_value[island_row] <- NA_character_
raw$obs_status[island_row] <- "s"
expect_error(load_fixture(raw), "published island total")

# Existing contracts remain active alongside the stricter parsing checks.
expect_error(load_fixture(raw_fixture[-national_row, ]), "published national total")
expect_error(load_fixture(rbind(raw_fixture, raw_fixture[regional_row, ])),
             "duplicate cells")
raw <- raw_fixture
raw$area_agr_agr_003[regional_row] <- "999"
expect_error(load_fixture(raw), "unmapped AREA code")
raw <- raw_fixture
raw$obs_status[regional_row] <- "unknown"
expect_error(load_fixture(raw), "unknown OBS_STATUS")
raw <- raw_fixture
raw$obs_status[regional_row] <- "s"
expect_error(load_fixture(raw), "every suppressed cell must be missing")
expect_error(load_fixture(raw_fixture[, names(raw_fixture) != "obs_value"]),
             "missing required column")
expect_error(load_fixture(raw_fixture[raw_fixture$year_agr_agr_003 != "2010", ]),
             "every year from 2002 to 2025")

# The real hash gate still rejects changed bytes. For the parser-only test,
# bypass the hash locally so a malformed CSV reaches readr's problem check.
local({
  csv <- tempfile(fileext = ".csv")
  on.exit(unlink(csv))
  writeLines(c(
    "LIVESTOCK_AGR_AGR_003,AREA_AGR_AGR_003,YEAR_AGR_AGR_003,OBS_VALUE,OBS_STATUS",
    "6731,1,2025,100,,unexpected-field"
  ), csv)
  expect_error(read_raw(csv), "does not match the hash")
  reader <- read_raw
  environment(reader) <- list2env(
    list(check_extract_hash = function(path) invisible(TRUE)),
    parent = environment(read_raw)
  )
  expect_error(suppressWarnings(reader(csv)), "parsing failure")

  # Exercise the real CSV parser: readr's default missing-value tokens would
  # otherwise erase a literal "NA" before the ingestion contracts see it.
  loader <- load_livestock
  environment(loader) <- list2env(
    list(read_raw = reader), parent = environment(load_livestock)
  )
  raw <- raw_fixture
  raw$obs_value[suppressed_row] <- "NA"
  write_csv(raw, csv, na = "")
  expect_error(loader(csv), "non-numeric or non-finite OBS_VALUE")

  raw <- raw_fixture
  raw$obs_status[regional_row] <- "NA"
  write_csv(raw, csv, na = "")
  expect_error(loader(csv), "unknown OBS_STATUS")
})

# Successful ingestion must preserve the committed analysis table byte-for-byte.
local({
  csv <- tempfile(fileext = ".csv")
  on.exit(unlink(csv))
  write_csv(load_livestock(), csv)
  stopifnot(identical(digest::digest(file = csv, algo = "sha256"),
                      digest::digest(file = "outputs/livestock_regional.csv",
                                     algo = "sha256")))
})

cat("R ingestion contracts passed; committed analysis table is unchanged.\n")
