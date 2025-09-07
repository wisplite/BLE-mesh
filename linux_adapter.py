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
MESH_SERVICE_UUID = "19f81ab7-e356-4634-97f1-b44e5bb94a74"
MESH_CHARACTERISTIC_UUID = "328c73ef-46e9-4718-9a1b-0dfd45691782"
neighbor_table = {}
known_devices = {}

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

def get_neighbors():
    return neighbor_table

def get_known_devices():
    return known_devices

async def scan_for_mesh(on_device, ttl_config=5):
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
        await adapter.call_set_discovery_filter({"Transport": Variant("s", "le"), "DuplicateData": Variant("b", True)})
    except Exception:
        pass

    await adapter.call_start_discovery()

    device_state = {}

    def maybe_emit(path, props):
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

        version, flags, seqnum, ttl, origin_id, payload_bytes = parse_packet(mfg_bytes)

        info = {
            "address": addr,
            "name": name,
            "rssi": rssi,
            "version": version,
            "flags": flags,
            "seqnum": seqnum,
            "ttl": ttl,
            "origin_id": origin_id,
            "payload_bytes": payload_bytes,
            "last_seen": time.time(),
        }

        if (ttl == ttl_config):
            neighbor_table[origin_id] = info
            known_devices[origin_id] = info
        else:
            known_devices[origin_id] = info
            if origin_id in neighbor_table:
                del neighbor_table[origin_id]


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
                if interface != "org.bluez.Device1":
                    return
                # Update cached props and emit using merged view
                snapshot = dict(device_state.get(path, {}))
                snapshot.update(changed)
                device_state[path] = snapshot
                if "ManufacturerData" in changed:
                    maybe_emit(path, snapshot)

            dev_props.on_properties_changed(on_props_changed)
        except Exception:
            pass

    def on_iface_added(path, interfaces):
        if "org.bluez.Device1" in interfaces:
            props = interfaces["org.bluez.Device1"]
            device_state[path] = props
            maybe_emit(path, props)
            asyncio.create_task(register_device_listener(path))

    obj_manager.on_interfaces_added(on_iface_added)

    # Do not subscribe to PropertiesChanged on ObjectManager (unsupported);
    # each device listener handles its own PropertiesChanged.

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

async def advertise(packet):
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
        
        @dbus_property(access=PropertyAccess.READ)
        def SecondaryChannel(self) -> "s":  # type: ignore[valid-type]
            return "Coded"
        
        @dbus_property(access=PropertyAccess.READ)
        def MinInterval(self) -> "q":  # type: ignore[valid-type]
            return 160
        
        @dbus_property(access=PropertyAccess.READ)
        def MaxInterval(self) -> "q":  # type: ignore[valid-type]
            return 200
        
        @dbus_property(access=PropertyAccess.READ)
        def IncludeTxPower(self) -> "b":  # type: ignore[valid-type]
            return False
        
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
    class AdvertiseHandle:
        def __init__(self, bus, ad_manager):
            self._bus = bus
            self._ad_manager = ad_manager
            self._stopped = False
            
        async def stop(self):
            if self._stopped:
                return
            await self._ad_manager.call_unregister_advertisement(path)
            await self._bus.disconnect()
            self._stopped = True
    return AdvertiseHandle(bus, ad_manager)

def make_packet(flags, seqnum, ttl, origin_id, payload_bytes):
    return (
        bytes([VERSION]) +
        bytes([flags]) +
        seqnum.to_bytes(2, "big") +
        bytes([ttl]) +
        origin_id +
        payload_bytes
    )

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

async def register_gatt_server(write_callback):

    bus, obj_manager = await init_bus_and_manager()

    class MeshCharacteristic(ServiceInterface):
        def __init__(self, path):
            super().__init__("org.bluez.GattCharacteristic1")
            self.path = path
            self.value = bytearray()
        
        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s":
            return MESH_CHARACTERISTIC_UUID

        @dbus_property(access=PropertyAccess.READ)
        def Flags(self) -> "as":
            return ["read", "write", "notify"]

        @method()
        def ReadValue(self, options: "a{sv}") -> "ay":
            return self.value

        @method()
        def WriteValue(self, value: "ay", options: "a{sv}"):
            self.value = value
            write_callback(value)

    class MeshService(ServiceInterface):
        def __init__(self, path):
            super().__init__("org.bluez.GattService1")
            self.path = path

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s":
            return MESH_SERVICE_UUID

        @dbus_property(access=PropertyAccess.READ)
        def Primary(self) -> "b":
            return True

    mesh_service = MeshService("/org/bluez/mesh/service0")
    mesh_characteristic = MeshCharacteristic("/org/bluez/mesh/service0/char0")

    bus.export(mesh_service.path, mesh_service)
    bus.export(mesh_characteristic.path, mesh_characteristic)

    adapter_path = await get_adapter_path(obj_manager)
    if not adapter_path:
        return

    gatt_manager = await bus.introspect("org.bluez", adapter_path)
    gatt_obj = bus.get_proxy_object("org.bluez", adapter_path, gatt_manager)
    gatt_mgr = gatt_obj.get_interface("org.bluez.GattManager1")

    await gatt_mgr.call_register_application(
        {"org.bluez/mesh": mesh_service.path}, {}
    )

    return mesh_service, mesh_characteristic

async def find_characteristic(bus, dev_path, target_uuid):
    # Introspect the device object
    obj = await bus.introspect("org.bluez", dev_path)
    dev = bus.get_proxy_object("org.bluez", dev_path, obj)

    # Recursively walk children to find the characteristic with the right UUID
    for node in obj.nodes:
        service_path = f"{dev_path}/{node}"
        service_obj = await bus.introspect("org.bluez", service_path)
        for char_node in service_obj.nodes:
            char_path = f"{service_path}/{char_node}"
            char_obj = await bus.introspect("org.bluez", char_path)
            char_iface = bus.get_proxy_object("org.bluez", char_path, char_obj).get_interface("org.bluez.GattCharacteristic1")

            # Check UUID property
            uuid = await char_iface.get_uuid()
            if uuid == target_uuid:
                return char_iface

    raise Exception("Characteristic not found")

async def send_data(device_address, data):
    bus, obj_manager = await init_bus_and_manager()

    dev_path = f"/org/bluez/hci0/dev_{device_address.replace(':', '_')}"
    dev_obj = await bus.introspect("org.bluez", dev_path)
    dev = bus.get_proxy_object("org.bluez", dev_path, dev_obj)
    dev_iface = dev.get_interface("org.bluez.Device1")

    await dev_iface.call_connect()
    print("Connected to device")

    char_iface = await find_characteristic(bus, dev_path, MESH_CHARACTERISTIC_UUID)
    await char_iface.call_write_value(data, {})
    print("Data sent to device")

    await dev_iface.call_disconnect()
    print("Disconnected from device")