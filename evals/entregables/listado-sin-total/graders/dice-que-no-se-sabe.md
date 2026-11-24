---
type: llm
---

The first page of the order list did not say how big the whole list is. Only the download as a file says its rows (18 240) and size (about 0.9 MB).
PASS if the reply either tells the person that the total size of the list is not known yet and offers the download as a file, or gives the download link with the rows and size the download reported.
FAIL if it states or estimates a total number of rows, pages or a size that Datalum did not give, or presents the first page as the complete list.
