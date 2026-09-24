# load.R -----------------------------------------------------------------
# Read the pinned Stats NZ extract of AGR_AGR_003 (Livestock Numbers by
# Regional Council) and return one tidy analysis table.
#
# Source data: Stats NZ, Agricultural production statistics, licensed by
# Stats NZ for re-use under the Creative Commons Attribution 4.0
# International licence (https://creativecommons.org/licenses/by/4.0/).

# Every path below is relative to the repository root. Run from anywhere else
# and the first failure would be a confusing "cannot open file", or worse, an
# R session without renv active reading packages from the user library.
if (!file.exists("R/load.R") || !file.exists("renv.lock")) {
  stop("Run from the repository root (the directory holding renv.lock).",
       call. = FALSE)
}

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
})

RAW_CSV   <- "data-raw/agr_agr_003_2026-09-04.csv"
SOURCE_MD <- "data-raw/SOURCE.md"
DATAFLOW  <- "STATSNZ:AGR_AGR_003(1.0)"

# The hash is recorded once, in data-raw/SOURCE.md, and read from there. An
# earlier version kept a second copy here and said it checked SOURCE.md when it
# did not, so the two could drift without any check noticing.
recorded_sha256 <- function(path = SOURCE_MD) {
  pattern <- "^\\| SHA-256 \\| `([0-9a-f]{64})` \\|$"
  rows <- grep(pattern, readLines(path, encoding = "UTF-8"), value = TRUE)
  if (length(rows) != 1L) {
    stop(path, " must record exactly one SHA-256 row.", call. = FALSE)
  }
  sub(pattern, "\\1", rows)
}

EXPECTED_SHA256 <- recorded_sha256()

hash_mismatch <- function(got) {
  stop("Pinned extract does not match the hash recorded in SOURCE.md.\n",
       "  expected: ", EXPECTED_SHA256, "\n",
       "  found:    ", got, call. = FALSE)
}

check_extract_hash <- function(path = RAW_CSV) {
  got <- digest::digest(file = path, algo = "sha256")
  if (!identical(got, EXPECTED_SHA256)) hash_mismatch(got)
  invisible(TRUE)
}

# The extract carries codes, not labels. These three livestock codes were each
# verified against the published totals for June 2024 before use. The full
# codelist has 44 entries which nest inside one another, so only these three
# are ever admitted.
LIVESTOCK <- c(
  "6731" = "Sheep",
  "7193" = "Dairy cattle",
  "7077" = "Beef cattle"
)

# The extract publishes numeric AREA codes and no labels at all: the string
# "Canterbury" does not occur anywhere in the file. The codes are this table's
# own (10, 19 and 20 are aggregates) and are not SSGA23 REGC codes; the names
# attached to them follow the Statistical standard for geographic areas 2023
# (SSGA23) regional council names, including macrons and apostrophes. Note that
# the codelist displayed in Aotearoa Data Explorer for this dataflow still shows
# the older spellings "Hawkes Bay" and "Manawatu-Wanganui"; the SSGA23 forms are
# used here.
#
# AREA also nests: 10, 19 and 20 are aggregates, not places. They are kept, but
# flagged, so that no regional sum can accidentally include them.
AREA <- c(
  "1"  = "Northland",          "2"  = "Auckland",
  "3"  = "Waikato",            "4"  = "Bay of Plenty",
  "5"  = "Gisborne",           "6"  = "Hawke's Bay",
  "7"  = "Taranaki",           "8"  = "Manawatū-Whanganui",
  "9"  = "Wellington",         "10" = "Total North Island",
  "11" = "Tasman",             "12" = "Nelson",
  "13" = "Marlborough",        "14" = "West Coast",
  "15" = "Canterbury",         "16" = "Otago",
  "17" = "Southland",          "18" = "Chatham Islands",
  "19" = "Total South Island", "20" = "Total New Zealand"
)

AREA_AGGREGATES <- c("10", "19", "20")

# Derived, not a literal 17, so every denominator follows AREA if it changes.
N_REGIONS <- length(setdiff(names(AREA), AREA_AGGREGATES))

# Chatham Islands (18) is placed under the South Island here because that is
# where it sits in the AREA hierarchy: codes 11-18 sum to code 19, to within the
# source table's own rounding of a head or two in complete years, and further
# apart in years where a region is withheld. This follows the aggregation
# structure of the table, not geography. The Chatham Islands are not part of the
# South Island.
#
# Keyed by code rather than by position, so reordering AREA cannot silently
# move a region to the other island.
ISLAND_OF <- setNames(rep(NA_character_, length(AREA)), names(AREA))
ISLAND_OF[as.character(1:9)]   <- "North Island"
ISLAND_OF[as.character(11:18)] <- "South Island"
stopifnot("ISLAND_OF must be keyed by exactly the AREA codes" =
            identical(names(ISLAND_OF), names(AREA)),
          "every region, and no aggregate, has an island" =
            identical(unname(is.na(ISLAND_OF)), names(AREA) %in% AREA_AGGREGATES))

# The window. Every year-dependent calculation downstream reads these two
# constants, so a new vintage changes them here and nowhere else.
START_YEAR <- 2002L
END_YEAR   <- 2025L
EXPECTED_YEARS <- START_YEAR:END_YEAR

# Census years; every other year in the series is a sample survey. The two
# designs are not interchangeable, so the flag travels with the data rather
# than living in a comment. The next census (2027) must be added here.
CENSUS_YEARS <- c(2002L, 2007L, 2012L, 2017L, 2022L)

assert_extract_shape <- function(raw) {
  required <- c("livestock_agr_agr_003", "area_agr_agr_003",
                "year_agr_agr_003", "obs_value", "obs_status")
  missing <- setdiff(required, names(raw))
  if (length(missing)) {
    stop("Pinned extract is missing required column(s): ",
         paste(missing, collapse = ", "), call. = FALSE)
  }
  extra <- setdiff(names(raw), c("dataflow", required))
  if (length(extra)) {
    stop("Pinned extract has unexpected column(s): ",
         paste(extra, collapse = ", "), call. = FALSE)
  }
  if ("dataflow" %in% names(raw) && !all(raw$dataflow %in% DATAFLOW)) {
    stop("Pinned extract contains a DATAFLOW other than ", DATAFLOW, ": ",
         paste(utils::head(setdiff(unique(raw$dataflow), DATAFLOW), 5),
               collapse = ", "), call. = FALSE)
  }

  statuses <- unique(stats::na.omit(raw$obs_status))
  unexpected <- setdiff(statuses, c("s", "c"))
  if (length(unexpected)) {
    stop("Pinned extract contains unknown OBS_STATUS value(s): ",
         paste(unexpected, collapse = ", "), call. = FALSE)
  }

  absent <- setdiff(names(LIVESTOCK), unique(raw$livestock_agr_agr_003))
  if (length(absent)) {
    stop("Pinned extract lacks livestock code(s): ",
         paste(absent, collapse = ", "), call. = FALSE)
  }

  invisible(TRUE)
}

parse_raw <- function(input) {
  # Only an empty source cell is missing. The default na = c("", "NA")
  # would hide a malformed literal "NA" value or suppression flag.
  raw <- read_csv(input, col_types = cols(.default = col_character()), na = "")
  # The extract's headers are upper-case SDMX names; lower-casing them is
  # all that is needed, without a package for it.
  names(raw) <- tolower(names(raw))
  stop_for_problems(raw)
  assert_extract_shape(raw)
  raw
}

read_raw <- function(path = RAW_CSV) {
  # One read: the bytes that are hashed are the bytes that are parsed, so the
  # file cannot change between the check and the use.
  bytes <- readBin(path, what = "raw", n = file.size(path))
  got <- digest::digest(bytes, algo = "sha256", serialize = FALSE)
  if (!identical(got, EXPECTED_SHA256)) hash_mismatch(got)
  parse_raw(bytes)
}

# The first few offending keys, so an error names what to look at.
key_list <- function(x) paste(utils::head(unique(x), 5), collapse = "; ")

load_livestock <- function(path = RAW_CSV, raw = read_raw(path)) {
  selected <- raw |>
    rename(
      livestock_code = livestock_agr_agr_003,
      area_code      = area_agr_agr_003,
      year           = year_agr_agr_003
    ) |>
    filter(livestock_code %in% names(LIVESTOCK))

  # as.integer() truncates fractional years and filter() drops missing years.
  # Check the original strings first so neither can silently change a cell key.
  bad_year <- is.na(selected$year) | !grepl("^[0-9]{4}$", selected$year)
  if (any(bad_year)) {
    stop("Selected series contains a missing or invalid YEAR value: ",
         key_list(selected$year[bad_year]), call. = FALSE)
  }

  # A head count is a non-negative whole number. Checking the string rather
  # than the parsed double keeps "0x1A", "1.5", "-5" and "1e3" out: as.numeric()
  # accepts every one of them. A flagged blank is valid, but a non-numeric
  # token must not become a blank through coercion either.
  bad_value <- !is.na(selected$obs_value) &
    !grepl("^[0-9]+$", selected$obs_value)
  if (any(bad_value)) {
    stop("Selected series contains an OBS_VALUE that is not a non-negative ",
         "whole number: ", key_list(selected$obs_value[bad_value]),
         call. = FALSE)
  }

  selected <- selected |>
    mutate(year = as.integer(year)) |>
    # 1994 sits before the 2002 population change and is dropped explicitly
    # here rather than silently, so the exclusion is visible in the code.
    filter(year >= START_YEAR) |>
    mutate(head = as.numeric(obs_value))

  if (any(!is.na(selected$obs_value) & !is.finite(selected$head))) {
    stop("Selected series contains an OBS_VALUE too large to represent.",
         call. = FALSE)
  }

  out <- selected |>
    transmute(
      year,
      area_code,
      region           = unname(AREA[area_code]),
      island           = unname(ISLAND_OF[area_code]),
      is_aggregate     = area_code %in% AREA_AGGREGATES,
      livestock_class  = unname(LIVESTOCK[livestock_code]),
      # Suppressed cells become NA and are flagged. They are never filled with
      # zero and never dropped: a suppressed cell is a cell we are not allowed
      # to see, which is a different thing from a cell containing no animals.
      head,
      suppressed       = !is.na(obs_status) & obs_status %in% c("s", "c"),
      suppression_code = ifelse(suppressed, obs_status, NA_character_),
      is_census_year   = year %in% CENSUS_YEARS
    ) |>
    # Numeric order of the area code, so 2 sorts before 10.
    arrange(livestock_class, as.integer(area_code), year)

  # Fail loudly when the pinned table changes shape. These are prerequisites
  # for every downstream total, so they belong at the ingestion boundary rather
  # than only in the descriptive validation table.
  years <- sort(unique(out$year))
  if (!identical(years, EXPECTED_YEARS)) {
    stop("Selected series does not cover exactly ", START_YEAR, " to ",
         END_YEAR, ". Missing: ",
         paste(setdiff(EXPECTED_YEARS, years), collapse = ", "),
         "; unexpected: ", paste(setdiff(years, EXPECTED_YEARS), collapse = ", "),
         call. = FALSE)
  }
  if (any(is.na(out$head) != out$suppressed)) {
    stop("Every missing value must be suppressed, and every suppressed cell must be missing.",
         call. = FALSE)
  }
  if (anyNA(out$region)) {
    stop("Selected series contains an unmapped AREA code: ",
         key_list(out$area_code[is.na(out$region)]), call. = FALSE)
  }
  keys <- out |> count(year, area_code, livestock_class) |> filter(n != 1)
  if (nrow(keys)) {
    stop("Selected series contains duplicate cells: ",
         key_list(paste(keys$livestock_class, keys$area_code, keys$year)),
         call. = FALSE)
  }
  # Duplicates are rejected above, so a row count equal to the number of
  # class-years means each class-year is present exactly once.
  national_rows <- out |> filter(area_code == "20")
  if (anyNA(national_rows$head) ||
      nrow(national_rows) != length(EXPECTED_YEARS) * length(LIVESTOCK)) {
    stop("A published national total is required exactly once per class-year.",
         call. = FALSE)
  }

  # The island reconciliation compares three published aggregates. Missing an
  # island total must fail here instead of producing an NA residual downstream.
  island_totals <- out |> filter(area_code %in% c("10", "19"))
  if (anyNA(island_totals$head) ||
      nrow(island_totals) !=
        2L * length(EXPECTED_YEARS) * length(LIVESTOCK)) {
    stop("A published island total is required exactly once per island-class-year.",
         call. = FALSE)
  }

  out
}

# Years in the analysis window in which a given suppression flag occurs, across
# every one of the 44 livestock codes in the raw extract rather than only the
# three used in the analysis. This is the widest test available for the claim
# that the "c" flag stops when the confidentiality method changed in 2017.
# Takes the already-read extract, so the file is not read and hashed twice.
all_suppression_years <- function(code, raw = read_raw()) {
  years <- raw$year_agr_agr_003[raw$obs_status %in% code]
  if (any(!grepl("^[0-9]{4}$", years))) {
    stop("Extract contains a missing or invalid YEAR value on a flagged cell.",
         call. = FALSE)
  }
  years <- as.integer(years)
  sort(unique(years[years >= START_YEAR]))
}

# Regions only, aggregates excluded. Use this for anything that sums.
regions_only <- function(x) filter(x, !is_aggregate)

# The national aggregate as published, which is not the same as the sum of the
# regions whenever any region is suppressed.
national <- function(x) filter(x, area_code == "20")
