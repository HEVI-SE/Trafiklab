# Trafiklab — flyttad till linjelogg

**Datapipelinen för det här projektet bor numera i
[hevi-se/linjelogg](https://github.com/hevi-se/linjelogg).**

Där finns allt samlat:

- samma Python-pipeline (`fetcher.py`, `analysis.py`, `report.py`, …),
- **all historisk data** (`data/*.csv`), överflyttad intakt,
- en schemalagd GitHub Action som hämtar nya dygn, bygger om `index.html`
  och publicerar sajten (linjelogg.se).

## Varför det inte finns några workflows här

`daily-fetch.yml` och `historical-fetch.yml` är **borttagna**. De körde
fortfarande varje dag och hämtade exakt samma KoDa-data som linjelogg
hämtar — alltså ungefär dubbla Actions-minuter för duplicerad data. Enbart
`Daily Data Fetch` tog ~72 minuter den 2026-10-29.

Återaktivera dem inte. Ska något hämtas eller byggas om är det linjelogg
som gäller.

Repot ligger kvar som referens och historik.
