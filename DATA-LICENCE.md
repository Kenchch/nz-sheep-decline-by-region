# Licensing

Two different licences apply to this repository, because it contains two
different kinds of thing.

## Code: MIT

Everything in `R/`, `tests/`, `databricks/*.py`, `_quarto.yml`, `DESCRIPTION`,
`renv.lock`, `renv/` and the workflow and configuration under `.github/` is
licensed under the MIT Licence. See [`LICENSE`](LICENSE).

## Data, outputs and the report: CC BY 4.0

The extract in `data-raw/` is published by Stats NZ and is redistributed here
unchanged under the [Creative Commons Attribution 4.0 International licence
(CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/), which is the
licence Stats NZ applies to it. It is not covered by the MIT licence above.

Attribution:

> This work is based on Stats NZ's data (Agricultural production statistics,
> AGR_AGR_003), licensed by Stats NZ for re-use under the [Creative Commons
> Attribution 4.0 International licence](https://creativecommons.org/licenses/by/4.0/).

Full provenance — dataflow, vintage, retrieval date and SHA-256 — is recorded in
[`data-raw/SOURCE.md`](data-raw/SOURCE.md).

Files in `outputs/` and the text and figures of the report (`index.qmd` as
rendered) are adapted from that extract: three livestock codes are selected,
cells are relabelled, reshaped, aggregated, differenced and reconciled, and
charted. They are released under CC BY 4.0 as well. Reuse them with the Stats NZ
attribution above and a note of the changes, for example "calculations by Feng
Jiang".

The screenshots in `databricks/screenshots/` show the Databricks user interface,
which belongs to Databricks, displaying values derived from the same extract.
They are included as documentation only and are not offered under either
licence.
