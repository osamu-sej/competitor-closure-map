from abc import ABC, abstractmethod

from collector.model import RawStore


class StoreSource(ABC):
    @abstractmethod
    def fetch_stores(self, prefecture: str, brand_family: str) -> list[RawStore]:
        raise NotImplementedError
