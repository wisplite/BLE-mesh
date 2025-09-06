import asyncio
from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Variant
from dbus_fast.service import ServiceInterface, dbus_property, method, PropertyAccess
import os
import uuid
import time

devices = {}
VERSION = 0x01
ORIGIN_ID_FILE = "origin_id.bin"
SEQNUM_FILE = "seqnum.bin"

async def init_bus_and_manager():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    print("Connected to system bus")

    root_introspection = await bus.introspect("org.bluez", "/")
    root_obj = bus.get_proxy_object("org.bluez", "/", root_introspection)
    obj_manager = root_obj.get_interface("org.freedesktop.DBus.ObjectManager")
    return bus, obj_manager

async def get_adapter_path(obj_manager):
    managed_initial = await obj_manager.call_get_managed_objects()
    adapter_paths = [p for p, ifaces in managed_initial.items() if "org.bluez.Adapter1" in ifaces]
    if not adapter_paths:
        print("No Bluetooth adapter found. Is bluetoothd running and hardware present?")
        return None
    return adapter_paths[0]

async def scan_for_mesh(on_device):
    bus, obj_manager = await init_bus_and_manager()

    adapter_path = await get_adapter_path(obj_manager)
    if not adapter_path:
        return None

    introspection = await bus.introspect("org.bluez", adapter_path)
    obj = bus.get_proxy_object("org.bluez", adapter_path, introspection)
    adapter = obj.get_interface("org.bluez.Adapter1")
    adapter_props = obj.get_interface("org.freedesktop.DBus.Properties")

    await adapter_props.call_set("org.bluez.Adapter1", "Powered", Variant("b", True))
    try:
        await adapter.call_set_discovery_filter({"Transport": Variant("s", "le")})
    except Exception:
        pass

    await adapter.call_start_discovery()

    last_payload_by_addr = {}

    def emit_if_payload(props):
        mfg_data = props.get("ManufacturerData")
        if not (mfg_data and 0xFFFF in mfg_data.value):
            return
        data_value = mfg_data.value
        mfg_bytes = bytes(data_value[0xFFFF].value)
        addr_v = props.get("Address")
        name_v = props.get("Name")
        rssi_v = props.get("RSSI")
        addr = addr_v.value if addr_v is not None else "<unknown>"
        name = name_v.value if name_v is not None else "<unknown>"
        rssi = rssi_v.value if rssi_v is not None else 0

        # Only emit when payload changes to avoid duplicates
        previous = last_payload_by_addr.get(addr)
        if previous is not None and previous == mfg_bytes:
            return
        last_payload_by_addr[addr] = mfg_bytes

        info = {
            "address": addr,
            "name": name,
            "rssi": rssi,
            "manufacturer_data_bytes": mfg_bytes,
            "manufacturer_data_str": None,
        }
        try:
            info["manufacturer_data_str"] = mfg_bytes.decode("utf-8")
        except Exception:
            info["manufacturer_data_str"] = None

        try:
            result = on_device(info)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:
            pass

    async def register_device_listener(path):
        try:
            dev_intro = await bus.introspect("org.bluez", path)
            dev_obj = bus.get_proxy_object("org.bluez", path, dev_intro)
            dev_props = dev_obj.get_interface("org.freedesktop.DBus.Properties")

            def on_props_changed(interface, changed, invalidated):
                if interface == "org.bluez.Device1" and "ManufacturerData" in changed:
                    try:
                        # Merge changed over current props-like dict shape
                        merged = {**changed}
                        # Include Address/Name/RSSI if available to build info
                        # We cannot easily fetch synchronously here; best effort using changed
                        emit_if_payload(merged)
                    except Exception:
                        pass

            dev_props.on_properties_changed(on_props_changed)
        except Exception:
            pass

    def on_iface_added(path, interfaces):
        if "org.bluez.Device1" in interfaces:
            props = interfaces["org.bluez.Device1"]
            emit_if_payload(props)
            asyncio.create_task(register_device_listener(path))

    obj_manager.on_interfaces_added(on_iface_added)

    managed = await obj_manager.call_get_managed_objects()
    for path, ifaces in managed.items():
        if "org.bluez.Device1" in ifaces:
            on_iface_added(path, ifaces)

    class ScanHandle:
        def __init__(self, bus, adapter):
            self._bus = bus
            self._adapter = adapter
            self._stopped = False

        async def stop(self):
            if self._stopped:
                return
            try:
                await self._adapter.call_stop_discovery()
            except Exception:
                pass
            try:
                self._bus.disconnect()
            except Exception:
                pass
            self._stopped = True

    return ScanHandle(bus, adapter)

async def send_packet(packet):
    bus, obj_manager = await init_bus_and_manager()

    path = "/com/example/advertisement0"

    mfg_payload = packet

    class LEAdvertisement(ServiceInterface):
        def __init__(self):
            super().__init__("org.bluez.LEAdvertisement1")

        @dbus_property(access=PropertyAccess.READ)
        def Type(self) -> "s":  # type: ignore[valid-type]
            return "broadcast"

        @dbus_property(access=PropertyAccess.READ)
        def ManufacturerData(self) -> "a{qv}":  # type: ignore[valid-type]
            return {0xFFFF: Variant("ay", mfg_payload)}

        @method()
        def Release(self) -> None:
            print("Advertisement released")

    advertisement = LEAdvertisement()
    bus.export(path, advertisement)

    adapter_path = await get_adapter_path(obj_manager)
    if not adapter_path:
        return

    introspection = await bus.introspect("org.bluez", adapter_path)
    obj = bus.get_proxy_object("org.bluez", adapter_path, introspection)
    ad_manager = obj.get_interface("org.bluez.LEAdvertisingManager1")
    adapter_props = obj.get_interface("org.freedesktop.DBus.Properties")

    await adapter_props.call_set("org.bluez.Adapter1", "Powered", Variant("b", True))
    await ad_manager.call_register_advertisement(path, {})
    await asyncio.sleep(1)
    await ad_manager.call_unregister_advertisement(path)
    print("sending packet")

def make_packet(flags, seqnum, ttl, origin_id, payload_bytes):
    return (
        bytes([VERSION]) +
        bytes([flags]) +
        seqnum.to_bytes(2, "big") +
        bytes([ttl]) +
        origin_id +
        payload_bytes
    )

def make_chat_packet(seqnum, origin_id, msg, ttl=5):
    return make_packet(flags=0x01, seqnum=seqnum, ttl=ttl,
                       origin_id=origin_id,
                       payload_bytes=msg.encode("utf-8"))

def parse_packet(packet):
    if len(packet) < 6:
        return None
    version = packet[0]
    flags = packet[1]
    seqnum = int.from_bytes(packet[2:4], "big")
    ttl = packet[4]
    origin_id = packet[5:13]
    payload_bytes = packet[13:]
    return version, flags, seqnum, ttl, origin_id, payload_bytes

def get_origin_id():
    if os.path.exists(ORIGIN_ID_FILE):
        with open(ORIGIN_ID_FILE, "rb") as f:
            return f.read(8)

    new_id = uuid.uuid4().bytes[:8]
    with open(ORIGIN_ID_FILE, "wb") as f:
        f.write(new_id)
    return new_id

def get_seqnum():
    # If seqnum file exists, increment it and return it
    # Otherwise, return 0
    if os.path.exists(SEQNUM_FILE):
        with open(SEQNUM_FILE, "rb") as f:
            data = f.read()
            if len(data) >= 2:
                seqnum = int.from_bytes(data[:2], "big")
            else:
                seqnum = 0
    else:
        seqnum = 0
    
    # Increment and wrap around at 65535 (2^16 - 1)
    seqnum = (seqnum + 1) % 65536
    
    # Write back the incremented seqnum
    with open(SEQNUM_FILE, "wb") as f:
        f.write(seqnum.to_bytes(2, "big"))
    return seqnum