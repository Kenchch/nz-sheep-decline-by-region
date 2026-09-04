# load.R -----------------------------------------------------------------
# Read the pinned Stats NZ extract of AGR_AGR_003 (Livestock Numbers by
# Regional Council) and return one tidy analysis table.
#
# Source data: Stats NZ, Agricultural production statistics, licensed by
# Stats NZ for re-use under the Creative Commons Attribution 4.0
# International licence.

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(janitor)
})

RAW_CSV <- "data-raw/agr_agr_003_2026-09-04.csv"

# The hash recorded in data-raw/SOURCE.md. Checking it turns "the data version
# is pinned" from a claim in a markdown file into a gate that fails loudly.
EXPECTED_SHA256 <- "e9d82621c2db8517dbf906a8b952d462a360cd2adcc351eb107e187afbe03a4c"

check_extract_hash <- function(path = RAW_CSV) {
  got <- digest::digest(file = path, algo = "sha256")
  if (!identical(got, EXPECTED_SHA256)) {
    stop("Pinned extract does not match the hash recorded in SOURCE.md.\n",
         "  expected: ", EXPECTED_SHA256, "\n",
         "  found:    ", got, call. = FALSE)
  }
  invisible(TRUE)
}

# The extract carries codes, not labels. These four livestock codes were each
# verified against the published totals for June 2024 before use; the full
# codelist has 44 entries which nest inside one another (adding all 44 for 2024
# gives 115.7 million against a published 33.8 million), so only these are ever
# admitted.
LIVESTOCK <- c(
  "6731" = "Sheep",
  "7193" = "Dairy cattle",
  "7077" = "Beef cattle"
)

# The extract publishes numeric AREA codes and no labels at all: the string
# "Canterbury" does not occur anywhere in the file. These names follow the
# Statistical standard for geographic areas 2023 (SSGA23) regional council
# names, including macrons and apostrophes. Note that the codelist displayed in
# Aotearoa Data Explorer for this dataflow still shows the older spellings
# "Hawkes Bay" and "Manawatu-Wanganui"; the SSGA23 forms are used here.
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

# Chatham Islands (18) is placed under the South Island here because that is
# where it sits in the AREA hierarchy: codes 11-18 sum exactly to code 19. This
# follows the aggregation structure of the table, not geography. The Chatham
# Islands are not part of the South Island.
ISLAND_OF <- c(rep("North Island", 9), NA,
               rep("South Island", 8), NA, NA)
names(ISLAND_OF) <- names(AREA)

# Census years; every other year in the series is a sample survey. The two
# designs are not interchangeable, so the flag travels with the data rather
# than living in a comment.
CENSUS_YEARS <- c(2002, 2007, 2012, 2017, 2022)

read_raw <- function(path = RAW_CSV) {
  check_extract_hash(path)
  read_csv(path, col_types = cols(.default = col_character())) |>
    clean_names()
}

load_livestock <- function(path = RAW_CSV) {
  raw <- read_raw(path)

  stopifnot(nrow(raw) > 0)

  out <- raw |>
    rename(
      livestock_code = livestock_agr_agr_003,
      area_code      = area_agr_agr_003,
      year           = year_agr_agr_003
    ) |>
    filter(livestock_code %in% names(LIVESTOCK)) |>
    mutate(year = as.integer(year)) |>
    # 1994 sits before the 2002 population change and is dropped explicitly
    # here rather than silently, so the exclusion is visible in the code.
    filter(year >= 2002) |>
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
      head             = suppressWarnings(as.numeric(obs_value)),
      suppressed       = !is.na(obs_status) & obs_status %in% c("s", "c"),
      suppression_code = ifelse(suppressed, obs_status, NA_character_),
      is_census_year   = year %in% CENSUS_YEARS
    ) |>
    arrange(livestock_class, area_code, year)

  # Any cell without a value must carry a suppression flag, and vice versa.
  stopifnot(all(is.na(out$head) == out$suppressed))
  stopifnot(!any(is.na(out$region)))

  out
}

# Years in which a given suppression flag occurs, across every one of the 44
# livestock codes in the raw extract rather than only the three used in the
# analysis. This is the widest test available for the claim that the "c" flag
# stops when the confidentiality method changed in 2017.
all_suppression_years <- function(code, path = RAW_CSV) {
  read_raw(path) |>
    filter(obs_status == code) |>
    pull(year_agr_agr_003) |>
    as.integer() |>
    unique() |>
    sort()
}

# Regions only, aggregates excluded. Use this for anything that sums.
regions_only <- function(x) filter(x, !is_aggregate)

# The national aggregate as published, which is not the same as the sum of the
# regions whenever any region is suppressed.
national <- function(x) filter(x, area_code == "20")

