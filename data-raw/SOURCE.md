# Data source

| Field | Value |
|---|---|
| Table | AGR_AGR_003 — Livestock Numbers by Regional Council |
| Publisher | Stats NZ |
| Dataflow | `STATSNZ:AGR_AGR_003(1.0)` |
| Retrieved from | `https://api.data.stats.govt.nz/rest/data/STATSNZ,AGR_AGR_003,1.0/all?format=csv` |
| Interactive equivalent | <https://explore.data.stats.govt.nz> → AGR_AGR_003 |
| Vintage | Final (year to June 2025 release) |
| Downloaded | 2026-09-04 |
| Licence | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| File | `agr_agr_003_2026-09-04.csv` |
| SHA-256 | `e9d82621c2db8517dbf906a8b952d462a360cd2adcc351eb107e187afbe03a4c` |

Attribution, verbatim as required by the licensor:

> Source data: Stats NZ, Agricultural production statistics, licensed by Stats NZ
> for re-use under the Creative Commons Attribution 4.0 International licence.

## Why a committed CSV rather than a live API call

The extract is committed to this repository, with its hash recorded above, as a
deliberate design decision. A pipeline that re-queries the API on every run is
*less* reproducible, not more: the endpoint serves the current vintage, so a
re-run after the next release would silently produce different numbers under the
same commit. Pinning the extract makes the analysis reproducible byte-for-byte,
and makes any change of vintage a visible commit rather than an invisible drift.

## Verification performed before any analysis code was written

| Check | Expected | Result |
|---|---|---|
| Total sheep, Total New Zealand, June 2024 | 23,583,001 | matched |
| Total dairy cattle, Total New Zealand, June 2024 | 5,836,845 | matched |
| Total beef cattle, Total New Zealand, June 2024 | 3,679,443 | matched |
| AREA aggregate codes | 10 = North Island, 19 = South Island, 20 = New Zealand | confirmed |
| AREA regional codes sum to their island total (sheep, 2017) | exact | confirmed |
| YEAR coverage | 1994, then 2002–2025 continuous | confirmed |

`OBS_STATUS` takes two non-empty values in this extract: `s` (suppressed) and
`c` (confidential). Every cell with an empty `OBS_VALUE` carries one of the two;
there are no unexplained blanks.
