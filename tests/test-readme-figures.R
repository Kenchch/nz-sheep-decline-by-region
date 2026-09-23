# Run from the repository root, after `quarto render`:
#   Rscript tests/test-readme-figures.R
# The README quotes numbers from the report. quarto render writes each of them,
# with the exact phrase the README uses, to outputs/key-figures.csv; this fails
# if the README no longer contains any one of those phrases. That is how a
# README transcribed by hand drifted from the report before: the report was
# corrected and the README was not.
figures <- read.csv("outputs/key-figures.csv", encoding = "UTF-8",
                    colClasses = "character")
readme <- paste(readLines("README.md", encoding = "UTF-8"), collapse = "\n")

missing <- figures[!vapply(figures$readme, grepl, logical(1), x = readme,
                           fixed = TRUE), ]
if (nrow(missing)) {
  cat("README.md does not quote", nrow(missing), "figure(s) as rendered:\n",
      paste0("  - ", missing$name, ": expected \"", missing$readme, "\"",
             collapse = "\n"), "\n")
  quit(status = 1)
}
cat("README quotes all", nrow(figures), "key figures as rendered.\n")
