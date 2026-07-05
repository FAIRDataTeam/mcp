"""Unit tests for the RFC 8288 Link-header parser and LinkSet (task 1.2)."""

from __future__ import annotations

from fdp_mcp.fdp.links import LinkSet, parse_link_header


def test_preserves_repeated_rels() -> None:
    header = (
        '<http://www.w3.org/ns/ldp#Resource>; rel="type", '
        '<http://www.w3.org/ns/ldp#Container>; rel="type", '
        '<https://fdp.example.org/dataset/1>; rel="item", '
        '<https://fdp.example.org/dataset/2>; rel="item"'
    )
    links = parse_link_header(header)
    assert len(links) == 4
    ls = LinkSet(tuple(links))
    assert ls.targets("type") == [
        "http://www.w3.org/ns/ldp#Resource",
        "http://www.w3.org/ns/ldp#Container",
    ]
    assert ls.items == [
        "https://fdp.example.org/dataset/1",
        "https://fdp.example.org/dataset/2",
    ]


def test_named_relations() -> None:
    header = (
        '<https://fdp.example.org/schema/dataset>; rel="http://www.w3.org/ns/ldp#constrainedBy", '
        '<https://doi.org/10.1234/x>; rel="cite-as", '
        '<https://creativecommons.org/licenses/by/4.0/>; rel="license", '
        '<https://orcid.org/0000-0002-1825-0097>; rel="author", '
        '<https://fdp.example.org/catalog/1>; rel="collection"'
    )
    ls = LinkSet.from_header(header)
    assert ls.constrained_by == "https://fdp.example.org/schema/dataset"
    assert ls.cite_as == "https://doi.org/10.1234/x"
    assert ls.license == "https://creativecommons.org/licenses/by/4.0/"
    assert ls.authors == ["https://orcid.org/0000-0002-1825-0097"]
    assert ls.collections == ["https://fdp.example.org/catalog/1"]


def test_describedby_carries_type_param() -> None:
    header = (
        '<https://fdp.example.org/d/1>; rel="describedby"; type="text/turtle", '
        '<https://fdp.example.org/d/1>; rel="describedby"; type="application/ld+json"'
    )
    ls = LinkSet.from_header(header)
    assert ls.described_by == [
        {"href": "https://fdp.example.org/d/1", "type": "text/turtle"},
        {"href": "https://fdp.example.org/d/1", "type": "application/ld+json"},
    ]


def test_quoted_value_with_comma_does_not_split() -> None:
    header = '<https://fdp.example.org/x>; rel="type"; title="A, B and C"'
    links = parse_link_header(header)
    assert len(links) == 1
    assert links[0].params["title"] == "A, B and C"


def test_type_iris_split_ldp_vs_rdf() -> None:
    header = (
        '<http://www.w3.org/ns/ldp#Resource>; rel="type", '
        '<http://www.w3.org/ns/dcat#Dataset>; rel="type"'
    )
    ls = LinkSet.from_header(header)
    assert ls.ldp_type_iris == ["http://www.w3.org/ns/ldp#Resource"]
    assert ls.rdf_type_iris == ["http://www.w3.org/ns/dcat#Dataset"]
    assert ls.is_ldp_container is False


def test_direct_container_counts_as_container() -> None:
    # FDPneo types containers ldp:DirectContainer only, not the bare ldp:Container.
    header = (
        '<http://www.w3.org/ns/ldp#Resource>; rel="type", '
        '<http://www.w3.org/ns/ldp#DirectContainer>; rel="type"'
    )
    assert LinkSet.from_header(header).is_ldp_container is True


def test_empty_and_none() -> None:
    assert parse_link_header(None) == []
    assert parse_link_header("") == []
    assert LinkSet.from_header(None).constrained_by is None
