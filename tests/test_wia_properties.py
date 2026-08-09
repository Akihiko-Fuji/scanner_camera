from __future__ import annotations

import logging

import pytest

import scanner_capture as target


def test_property_subtype_name_maps_known_and_unknown_values() -> None:
    assert target.property_subtype_name(target.WIA_PROP_NONE) == "NONE"
    assert target.property_subtype_name(target.WIA_PROP_RANGE) == "RANGE"
    assert target.property_subtype_name(target.WIA_PROP_LIST) == "LIST"
    assert target.property_subtype_name(target.WIA_PROP_FLAG) == "FLAG"
    assert target.property_subtype_name(99) == "UNKNOWN_99"


def test_property_constraints_reports_range(fake_property_cls) -> None:
    prop = fake_property_cls(
        1,
        10,
        subtype=target.WIA_PROP_RANGE,
        minimum=-1000,
        maximum=1000,
        step=10,
        default=0,
    )

    assert target.property_constraints(prop) == {
        "kind": "range",
        "default": 0,
        "min": -1000,
        "max": 1000,
        "step": 10,
    }


@pytest.mark.parametrize(
    ("subtype", "kind"),
    [(target.WIA_PROP_LIST, "list"), (target.WIA_PROP_FLAG, "flag")],
)
def test_property_constraints_reports_discrete_values(
    fake_property_cls, subtype: int, kind: str
) -> None:
    prop = fake_property_cls(
        1, 300, subtype=subtype, values=[150, 300, 600], default=300
    )

    assert target.property_constraints(prop) == {
        "kind": kind,
        "default": 300,
        "values": [150, 300, 600],
    }


def test_property_constraints_reports_driver_defined(fake_property_cls) -> None:
    prop = fake_property_cls(1, "vendor", subtype=target.WIA_PROP_NONE)
    assert target.property_constraints(prop) == {"kind": "driver-defined"}


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(-2000, -1000), (-994, -990), (6, 10), (9999, 1000)],
)
def test_normalize_property_value_clamps_and_steps_range(
    fake_property_cls, requested: int, expected: int
) -> None:
    prop = fake_property_cls(
        1,
        0,
        subtype=target.WIA_PROP_RANGE,
        minimum=-1000,
        maximum=1000,
        step=10,
    )
    assert target.normalize_property_value(prop, requested) == expected


def test_normalize_property_value_chooses_nearest_list_value(fake_property_cls) -> None:
    prop = fake_property_cls(
        1, 300, subtype=target.WIA_PROP_LIST, values=[75, 150, 300, 600]
    )

    assert target.normalize_property_value(prop, 300) == 300
    assert target.normalize_property_value(prop, 510) == 600
    assert target.normalize_property_value(prop, 200) == 150


def test_normalize_property_value_passes_driver_defined_integer(fake_property_cls) -> None:
    prop = fake_property_cls(1, 0, subtype=target.WIA_PROP_NONE)
    assert target.normalize_property_value(prop, "42") == 42


def test_probe_property_write_detects_read_only(fake_property_cls) -> None:
    prop = fake_property_cls(1, 10, read_only=True)
    assert target.probe_property_write(prop, True) == ("READ_ONLY", None)
    assert prop.write_count == 0


def test_probe_property_write_can_be_disabled(fake_property_cls) -> None:
    prop = fake_property_cls(1, 10)
    status, detail = target.probe_property_write(prop, False)
    assert status == "NOT_PROBED"
    assert detail == "write probing disabled"
    assert prop.write_count == 0


def test_probe_property_write_round_trips_current_value(fake_property_cls) -> None:
    prop = fake_property_cls(1, 10)
    status, detail = target.probe_property_write(prop, True)
    assert status == "WRITE_PROBE_OK"
    assert detail == "readback=10"
    assert prop.write_count == 1


def test_probe_property_write_reports_read_and_write_failures(fake_property_cls) -> None:
    unreadable = fake_property_cls(1, 10, reject_read=True)
    assert target.probe_property_write(unreadable, True)[0] == "PROBE_NOT_POSSIBLE"

    unwritable = fake_property_cls(2, 10, reject_write=True)
    status, detail = target.probe_property_write(unwritable, True)
    assert status == "WRITE_PROBE_FAILED"
    assert "write rejected" in detail


def test_inspect_property_collects_driver_metadata(fake_property_cls) -> None:
    prop = fake_property_cls(
        target.WIA_IPS_BRIGHTNESS,
        100,
        name="Brightness",
        subtype=target.WIA_PROP_RANGE,
        minimum=-1000,
        maximum=1000,
        step=1,
        default=0,
    )

    report = target.inspect_property(prop, True)

    assert report.property_id == target.WIA_IPS_BRIGHTNESS
    assert report.name == "WIA_IPS_BRIGHTNESS"
    assert report.driver_name == "Brightness"
    assert report.current_value == 100
    assert report.read_only is False
    assert report.write_probe == "WRITE_PROBE_OK"


@pytest.mark.parametrize(
    ("read_only", "probe", "expected"),
    [
        (True, "READ_ONLY", "EXPOSED_READ_ONLY"),
        (False, "WRITE_PROBE_OK", "EXPOSED_AND_SETTABLE"),
        (False, "NOT_PROBED", "EXPOSED_WRITABLE_NOT_PROBED"),
        (False, "WRITE_PROBE_FAILED", "EXPOSED_BUT_WRITE_REJECTED"),
        (None, "PROBE_NOT_POSSIBLE", "EXPOSED_SUPPORT_UNCERTAIN"),
    ],
)
def test_support_from_property_maps_probe_status(
    read_only, probe: str, expected: str
) -> None:
    report = target.PropertyReport(
        property_id=target.WIA_IPS_BRIGHTNESS,
        name="WIA_IPS_BRIGHTNESS",
        driver_name="Brightness",
        current_value=0,
        value_type=3,
        subtype=target.WIA_PROP_RANGE,
        subtype_name="RANGE",
        read_only=read_only,
        allowed={"kind": "range"},
        write_probe=probe,
        write_probe_detail=None,
    )

    support = target.support_from_property(
        "brightness", target.WIA_IPS_BRIGHTNESS, report
    )

    assert support.exposed is True
    assert support.support == expected


def test_support_from_property_reports_not_exposed() -> None:
    support = target.support_from_property(
        "brightness", target.WIA_IPS_BRIGHTNESS, None
    )
    assert support.exposed is False
    assert support.support == "NOT_EXPOSED_BY_WIA"
    assert "does not publish" in support.detail


def test_set_property_skips_none_request(fake_item_cls) -> None:
    item = fake_item_cls([])
    target.set_property(item, target.WIA_IPS_BRIGHTNESS, None, strict=True)


def test_set_property_missing_property_respects_strict_mode(
    fake_item_cls, caplog: pytest.LogCaptureFixture
) -> None:
    item = fake_item_cls([])

    with pytest.raises(RuntimeError, match="not exposed"):
        target.set_property(item, target.WIA_IPS_BRIGHTNESS, 0, strict=True)

    with caplog.at_level(logging.WARNING):
        target.set_property(item, target.WIA_IPS_BRIGHTNESS, 0, strict=False)
    assert "not exposed" in caplog.text


def test_set_property_read_only_respects_strict_mode(
    fake_property_cls, fake_item_cls, caplog: pytest.LogCaptureFixture
) -> None:
    prop = fake_property_cls(target.WIA_IPS_BRIGHTNESS, 0, read_only=True)
    item = fake_item_cls([prop])

    with pytest.raises(RuntimeError, match="read-only"):
        target.set_property(item, target.WIA_IPS_BRIGHTNESS, 100, strict=True)

    with caplog.at_level(logging.WARNING):
        target.set_property(item, target.WIA_IPS_BRIGHTNESS, 100, strict=False)
    assert "read-only" in caplog.text
    assert prop.Value == 0


def test_set_property_normalizes_value_and_reads_back(
    fake_property_cls, fake_item_cls, caplog: pytest.LogCaptureFixture
) -> None:
    prop = fake_property_cls(
        target.WIA_IPS_BRIGHTNESS,
        0,
        subtype=target.WIA_PROP_RANGE,
        minimum=-1000,
        maximum=1000,
        step=100,
    )
    item = fake_item_cls([prop])

    with caplog.at_level(logging.INFO):
        target.set_property(item, target.WIA_IPS_BRIGHTNESS, 955, strict=True)

    assert prop.Value == 1000
    assert "requested=955 applied=1000" in caplog.text


def test_set_property_write_failure_respects_strict_mode(
    fake_property_cls, fake_item_cls, caplog: pytest.LogCaptureFixture
) -> None:
    strict_prop = fake_property_cls(
        target.WIA_IPS_BRIGHTNESS,
        0,
        subtype=target.WIA_PROP_RANGE,
        minimum=-1000,
        maximum=1000,
        step=1,
        reject_write=True,
    )
    strict_item = fake_item_cls([strict_prop])
    with pytest.raises(RuntimeError, match="Could not set WIA_IPS_BRIGHTNESS"):
        target.set_property(strict_item, target.WIA_IPS_BRIGHTNESS, 100, strict=True)

    non_strict_prop = fake_property_cls(
        target.WIA_IPS_BRIGHTNESS,
        0,
        subtype=target.WIA_PROP_RANGE,
        minimum=-1000,
        maximum=1000,
        step=1,
        reject_write=True,
    )
    non_strict_item = fake_item_cls([non_strict_prop])
    with caplog.at_level(logging.WARNING):
        target.set_property(
            non_strict_item, target.WIA_IPS_BRIGHTNESS, 100, strict=False
        )
    assert "Could not set WIA_IPS_BRIGHTNESS" in caplog.text
    assert non_strict_prop.Value == 0
