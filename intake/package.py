from dataclasses import dataclass
from json import loads

from intake.pages import SourcePage, parse_source_pages
from publication.artifact import encode_original_pages
from publication.commit import publish_original
from publication.page_format import valid_text


class PackageError(ValueError):
    """The submitted bytes or batch number do not describe a V1 package."""


@dataclass(frozen=True)
class SourcePackage:
    batch_no: str
    raw: bytes
    pages: tuple[SourcePage, ...]


def _unique_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError(f'duplicate JSON field {key!r}')
        fields[key] = value
    return fields


def _decimal_integer(token: str) -> int:
    # Chunking keeps exact readings independent of the interpreter's decimal digit limit.
    negative = token.startswith('-')
    digits = token[1:] if negative else token
    value = 0
    for offset in range(0, len(digits), 9):
        chunk = digits[offset:offset + 9]
        value = value * 10 ** len(chunk) + int(chunk)
    return -value if negative else value


def _invalid_constant(token: str):
    raise ValueError(f'invalid JSON constant {token}')


def parse_package(batch_no: str, raw: bytes) -> SourcePackage:
    if not valid_text(batch_no) or not isinstance(raw, bytes):
        raise PackageError('a nonempty UTF-8 batch number and package bytes are required')
    try:
        fields = loads(
            raw.decode('utf-8'),
            object_pairs_hook=_unique_fields,
            parse_int=_decimal_integer,
            parse_constant=_invalid_constant,
        )
        if not isinstance(fields, dict) or fields.keys() != {'version', 'pages'}:
            raise ValueError('package must declare version and pages')
        if type(fields['version']) is not int or fields['version'] != 1:
            raise ValueError('unsupported source package version')
        pages = parse_source_pages(fields['pages'])
    except (ValueError, RecursionError) as error:
        raise PackageError(str(error)) from error
    return SourcePackage(batch_no, raw, pages)


def accept_package(database, batch_no: str, raw: bytes, *, before_commit=None) -> int:
    package = parse_package(batch_no, raw)
    fixed_pages = encode_original_pages(package.pages)
    return publish_original(
        database, package.batch_no, package.raw, fixed_pages, before_commit=before_commit
    )
