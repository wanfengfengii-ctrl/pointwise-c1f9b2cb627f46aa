from dataclasses import dataclass


@dataclass(frozen=True)
class LabelTotal:
    label: str
    records: int
    non_null: int
    net: int | None


class TotalAccumulator:
    def __init__(self, label: str):
        self.label = label
        self.records = 0
        self.non_null = 0
        self._net = 0

    def add(self, reading: int | None) -> None:
        self.records += 1
        if reading is not None:
            self.non_null += 1
            self._net += reading

    def finish(self) -> LabelTotal:
        net = self._net if self.non_null else None
        return LabelTotal(self.label, self.records, self.non_null, net)
