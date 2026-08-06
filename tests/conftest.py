from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


class FakeProperty:
    def __init__(
        self,
        property_id: int,
        value: Any,
        *,
        name: str | None = None,
        subtype: int = 0,
        read_only: bool | None = False,
        minimum: int = 0,
        maximum: int = 0,
        step: int = 1,
        values: list[int] | None = None,
        default: Any = None,
        value_type: int = 3,
        reject_write: bool = False,
        reject_read: bool = False,
    ) -> None:
        self.PropertyID = property_id
        self.Name = name or f"Property {property_id}"
        self.SubType = subtype
        self.IsReadOnly = read_only
        self.SubTypeMin = minimum
        self.SubTypeMax = maximum
        self.SubTypeStep = step
        self.SubTypeValues = list(values or [])
        self.SubTypeDefault = default
        self.Type = value_type
        self._value = value
        self.reject_write = reject_write
        self.reject_read = reject_read
        self.write_count = 0

    @property
    def Value(self) -> Any:
        if self.reject_read:
            raise RuntimeError("read rejected")
        return self._value

    @Value.setter
    def Value(self, value: Any) -> None:
        self.write_count += 1
        if self.reject_write:
            raise RuntimeError("write rejected")
        if self.IsReadOnly is True:
            raise RuntimeError("read only")
        self._value = value


class FakeProperties:
    def __init__(
        self,
        properties: list[FakeProperty],
        aliases: dict[Any, FakeProperty] | None = None,
    ) -> None:
        self._properties = list(properties)
        self._aliases = dict(aliases or {})
        for prop in properties:
            self._aliases.setdefault(prop.PropertyID, prop)
            self._aliases.setdefault(prop.Name, prop)

    def __iter__(self):
        return iter(self._properties)

    def Item(self, key: Any) -> FakeProperty:
        try:
            return self._aliases[key]
        except KeyError as exc:
            raise RuntimeError(f"property not found: {key!r}") from exc


class FakeItems:
    def __init__(self, items: list[Any]):
        self._items = list(items)
        self.Count = len(items)

    def Item(self, index: int) -> Any:
        if index < 1 or index > len(self._items):
            raise RuntimeError("item index out of range")
        return self._items[index - 1]


class FakeItem:
    def __init__(self, properties: list[FakeProperty]):
        self.Properties = FakeProperties(properties)


class FakeDevice:
    def __init__(self, items: list[Any]):
        self.Items = FakeItems(items)


class FakeInfo:
    def __init__(self, name: str, device_id: str = "device-1", connected: Any = None):
        name_prop = FakeProperty(7, name, name="Name")
        self.Properties = FakeProperties(
            [name_prop], aliases={"Name": name_prop, 7: name_prop}
        )
        self.DeviceID = device_id
        self.Type = 1
        self._connected = connected
        self.connect_count = 0

    def Connect(self) -> Any:
        self.connect_count += 1
        return self._connected


class FakeImageFile:
    def __init__(self, image) -> None:
        self.image = image
        self.saved_to: Path | None = None

    def SaveFile(self, path: str) -> None:
        self.saved_to = Path(path)
        self.image.save(path, format="BMP")


@pytest.fixture
def fake_property_cls():
    return FakeProperty


@pytest.fixture
def fake_item_cls():
    return FakeItem


@pytest.fixture
def fake_info_cls():
    return FakeInfo


@pytest.fixture
def fake_device_cls():
    return FakeDevice


@pytest.fixture
def fake_image_file_cls():
    return FakeImageFile
