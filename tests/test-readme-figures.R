# Run from the repository root, after `quarto render`:
#   Rscript tests/test-readme-figures.R
# The README quotes numbers from the report, in its text and in its image alt
# text. quarto render writes each of them to outputs/key-figures.csv with the
# exact phrase the README uses and how many times it uses it; this fails if
# any count differs. "At least once" was not enough: a phrase quoted twice
# could be corrected in one place and left stale in the other.
if (!file.exists("renv.lock")) {
  stop("Run from the repository root: Rscript tests/test-readme-figures.R", call. = FALSE)
}
figures <- read.csv("outputs/key-figures.csv", encoding = "UTF-8",
                    colClasses = "character")
readme <- paste(readLines("README.md", encoding = "UTF-8"), collapse = "\n")

occurrences <- function(phrase) {
  hits <- gregexpr(phrase, readme, fixed = TRUE)[[1]]
  if (hits[1] == -1L) 0L else length(hits)
}
found <- vapply(figures$readme, occurrences, integer(1), USE.NAMES = FALSE)
bad <- found != as.integer(figures$count)
if (any(bad)) {
  cat("README.md does not quote", sum(bad), "figure(s) as rendered:\n",
      paste0("  - ", figures$name[bad], ": expected \"", figures$readme[bad], "\" ",
             figures$count[bad], " time(s), found ", found[bad], collapse = "\n"), "\n")
  quit(status = 1)
}
cat("README quotes all", nrow(figures), "key figures as rendered, as often as expected.\n")
