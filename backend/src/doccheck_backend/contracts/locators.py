"""Addresses within the saved version of a source document."""

import re
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strict=True, min_length=1)]
Index = Annotated[int, Field(strict=True, ge=1)]
Coordinate = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Box = tuple[Coordinate, Coordinate, Coordinate, Coordinate]
IsoDate = Annotated[
    str,
    StringConstraints(strict=True, pattern=re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])")),
    Field(json_schema_extra={"format": "date"}),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def check_period(start: str | None, end: str | None) -> None:
    first = date.fromisoformat(start) if start is not None else None
    last = date.fromisoformat(end) if end is not None else None
    if first is not None and last is not None and first > last:
        raise ValueError("period start must precede or equal its end")


class PageLocator(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "anyOf": [
                {"required": ["bbox"], "properties": {"bbox": {"type": "array"}}},
                {"required": ["line"], "properties": {"line": {"type": "integer"}}},
                {
                    "required": ["table_row", "table_column"],
                    "properties": {
                        "table_row": {"type": "integer"},
                        "table_column": {"type": "integer"},
                    },
                },
                {"required": ["fragment_id"], "properties": {"fragment_id": {"type": "string"}}},
            ],
            "allOf": [
                {
                    "if": {
                        "required": ["table_row"],
                        "properties": {"table_row": {"type": "integer"}},
                    },
                    "then": {
                        "required": ["table_column"],
                        "properties": {"table_column": {"type": "integer"}},
                    },
                },
                {
                    "if": {
                        "required": ["table_column"],
                        "properties": {"table_column": {"type": "integer"}},
                    },
                    "then": {
                        "required": ["table_row"],
                        "properties": {"table_row": {"type": "integer"}},
                    },
                },
            ],
        }
    )

    kind: Literal["page"]
    page: Index
    bbox: Box | None = None
    line: Index | None = None
    table_row: Index | None = None
    table_column: Index | None = None
    fragment_id: Text | None = None

    @model_validator(mode="after")
    def check_fragment(self) -> Self:
        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if x0 >= x1 or y0 >= y1:
                raise ValueError("bbox must have positive width and height")
        if (self.table_row is None) != (self.table_column is None):
            raise ValueError("a table cell needs both row and column")
        if all(value is None for value in (self.bbox, self.line, self.table_row, self.fragment_id)):
            raise ValueError("a page number alone does not identify evidence")
        return self


_CELL = r"[A-Z]{1,3}[1-9][0-9]{0,6}"
_RANGE = re.compile(rf"^{_CELL}(?::{_CELL})?(?![\s\S])")


def _cell_position(cell: str) -> tuple[int, int]:
    column = 0
    for index, char in enumerate(cell):
        if char.isdigit():
            return column, int(cell[index:])
        column = column * 26 + ord(char) - ord("A") + 1
    raise ValueError("cell must contain a row number")


class SheetLocator(ContractModel):
    kind: Literal["sheet"]
    sheet: Text
    range: Annotated[str, StringConstraints(strict=True, pattern=_RANGE)]

    @model_validator(mode="after")
    def check_range(self) -> Self:
        first, _, last = self.range.partition(":")
        left, top = _cell_position(first)
        right, bottom = _cell_position(last or first)
        if not (left <= right <= 16_384 and top <= bottom <= 1_048_576):
            raise ValueError("range must be ordered and within XLSX bounds")
        return self


class ParagraphLocator(ContractModel):
    kind: Literal["paragraph"]
    paragraph: Index


class TableCellLocator(ContractModel):
    kind: Literal["table_cell"]
    table: Index
    row: Index
    cell: Index


Locator = Annotated[
    PageLocator | SheetLocator | ParagraphLocator | TableCellLocator, Field(discriminator="kind")
]
