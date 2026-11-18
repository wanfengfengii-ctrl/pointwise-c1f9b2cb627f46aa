from dataclasses import dataclass

SLOT_COUNT = 256
_MAX_WORD = 2 ** 32 - 1
_MAGIC = b'IPG1'
_MISSING = 0
_INTEGER = 1
_EXTENSION = 2


class FixedPageError(ValueError):
    """The fixed page cannot be exchanged or interpreted according to V1."""


@dataclass(frozen=True)
class EncodedObservation:
    slot: int
    reading: int | None


@dataclass(frozen=True)
class EncodedExtension:
    raw: bytes
    references: tuple[int, ...]


@dataclass(frozen=True)
class FixedPage:
    page_number: int
    dictionary: tuple[tuple[int, str], ...]
    rows: tuple[EncodedObservation | EncodedExtension, ...]


def valid_page_number(value) -> bool:
    return type(value) is int and 1 <= value <= _MAX_WORD


def valid_slot(value) -> bool:
    return type(value) is int and 0 <= value < SLOT_COUNT


def valid_text(value) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def _word(value: int) -> bytes:
    if not 0 <= value <= _MAX_WORD:
        raise FixedPageError('fixed page exceeds its framing range')
    return value.to_bytes(4, 'big')


def _field(payload: bytes) -> bytes:
    return _word(len(payload)) + payload


def _byte_slot(slot: int) -> int:
    if not valid_slot(slot):
        raise FixedPageError('invalid single-byte slot')
    return slot


def _encode_observation(row: EncodedObservation, result: bytearray) -> None:
    slot = _byte_slot(row.slot)
    reading = row.reading
    if reading is None:
        result.extend((_MISSING, slot))
        return
    if type(reading) is not int:
        raise FixedPageError('ordinary reading must be an integer or missing')
    bits = (reading if reading >= 0 else ~reading).bit_length()
    width = (bits + 8) // 8
    result.extend((_INTEGER, slot))
    result.extend(_field(reading.to_bytes(width, 'big', signed=True)))


def encode_fixed_page(page: FixedPage) -> bytes:
    if not valid_page_number(page.page_number):
        raise FixedPageError('invalid fixed page number')
    if len(page.dictionary) > SLOT_COUNT:
        raise FixedPageError('too many fixed dictionary entries')
    result = bytearray(_MAGIC)
    result.extend(_word(page.page_number))
    result.extend(len(page.dictionary).to_bytes(2, 'big'))
    seen = set()
    for slot, label in page.dictionary:
        _byte_slot(slot)
        if slot in seen or not valid_text(label):
            raise FixedPageError('duplicate dictionary slot or invalid label')
        seen.add(slot)
        result.append(slot)
        result.extend(_field(label.encode('utf-8')))

    result.extend(_word(len(page.rows)))
    for row in page.rows:
        if isinstance(row, EncodedObservation):
            _encode_observation(row, result)
        elif isinstance(row, EncodedExtension) and isinstance(row.raw, bytes):
            result.append(_EXTENSION)
            result.extend(_field(row.raw))
            result.extend(_field(bytes(_byte_slot(slot) for slot in row.references)))
        else:
            raise FixedPageError('invalid fixed row')
    return bytes(result)


class _Reader:
    def __init__(self, content: bytes):
        self.content = content
        self.offset = 0

    def take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.content):
            raise FixedPageError('truncated fixed page')
        segment = self.content[self.offset:end]
        self.offset = end
        return segment

    def unsigned(self, size: int) -> int:
        return int.from_bytes(self.take(size), 'big')

    def field(self) -> bytes:
        return self.take(self.unsigned(4))


def _decode_dictionary(reader: _Reader) -> tuple[tuple[int, str], ...]:
    count = reader.unsigned(2)
    if count > SLOT_COUNT:
        raise FixedPageError('invalid fixed dictionary size')
    entries = {}
    for _ in range(count):
        slot = reader.unsigned(1)
        try:
            label = reader.field().decode('utf-8')
        except UnicodeDecodeError as error:
            raise FixedPageError('invalid UTF-8 in fixed dictionary') from error
        if slot in entries or not label:
            raise FixedPageError('duplicate fixed dictionary slot or empty label')
        entries[slot] = label
    return tuple(entries.items())


def _decode_row(reader: _Reader) -> EncodedObservation | EncodedExtension:
    kind = reader.unsigned(1)
    if kind == _EXTENSION:
        return EncodedExtension(reader.field(), tuple(reader.field()))
    if kind == _MISSING:
        return EncodedObservation(reader.unsigned(1), None)
    if kind == _INTEGER:
        slot = reader.unsigned(1)
        reading = reader.field()
        if not reading:
            raise FixedPageError('empty integer field')
        return EncodedObservation(slot, int.from_bytes(reading, 'big', signed=True))
    raise FixedPageError('unknown fixed row kind')


def decode_fixed_page_fields(content: bytes) -> FixedPage:
    if not isinstance(content, bytes):
        raise FixedPageError('fixed page requires bytes')
    reader = _Reader(content)
    if reader.take(len(_MAGIC)) != _MAGIC:
        raise FixedPageError('unsupported fixed page header')
    page_number = reader.unsigned(4)
    if not valid_page_number(page_number):
        raise FixedPageError('invalid fixed page number')
    dictionary = _decode_dictionary(reader)
    rows = tuple(_decode_row(reader) for _ in range(reader.unsigned(4)))
    if reader.offset != len(content):
        raise FixedPageError('unexpected bytes after fixed page')
    return FixedPage(page_number, dictionary, rows)
