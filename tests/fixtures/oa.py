"""Builders for OpenAlex work records used by the offline tests."""


def oa_work(wid="W1", doi="10.1000/a", title="Deep Things", year=2020, surname="Smith", **kw):
    d = {
        "id": f"https://openalex.org/{wid}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "publication_year": year,
        "authorships": [{"author": {"display_name": f"Ann {surname}"}}],
        "ids": {},
        "language": "en",
        "is_retracted": False,
        "primary_location": {"landing_page_url": f"https://pub.example/{wid}"},
        "best_oa_location": None,
        "locations": [],
        "has_content": {"pdf": False, "grobid_xml": False},
        "abstract_inverted_index": {"We": [0], "study": [1], "things": [2]},
    }
    d.update(kw)
    return d
