import asyncio
from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Variant
from dbus_fast.service import ServiceInterface, dbus_property, method, PropertyAccess
import time

devices = {}

async def advertise():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    print("Connected to system bus")

    path = "/com/example/advertisement0"

    # Build manufacturer data payload (4-byte Unix timestamp)
    timestamp = int(time.time())
    mfg_payload = "Hello, World!"

    class LEAdvertisement(ServiceInterface):
        def __init__(self):
            super().__init__("org.bluez.LEAdvertisement1")

        @dbus_property(access=PropertyAccess.READ)
        def Type(self) -> "s":  # type: ignore[valid-type]
            return "broadcast"

        @dbus_property(access=PropertyAccess.READ)
        def ManufacturerData(self) -> "a{qv}":  # type: ignore[valid-type]
            return {0xFFFF: Variant("ay", mfg_payload.encode("utf-8"))}

        @method()
        def Release(self) -> None:
            print("Advertisement released")

    # Export our LEAdvertisement implementation on the bus
    advertisement = LEAdvertisement()
    bus.export(path, advertisement)

    # Root object manager (for signals and enumerating existing devices)
    root_introspection = await bus.introspect("org.bluez", "/")
    root_obj = bus.get_proxy_object("org.bluez", "/", root_introspection)
    obj_manager = root_obj.get_interface("org.freedesktop.DBus.ObjectManager")

    # Determine adapter path dynamically (fallback if none)
    managed_initial = await obj_manager.call_get_managed_objects()
    adapter_paths = [p for p, ifaces in managed_initial.items() if "org.bluez.Adapter1" in ifaces]
    if not adapter_paths:
        print("No Bluetooth adapter found. Is bluetoothd running and hardware present?")
        return
    adapter_path = adapter_paths[0]

    # Adapter interface
    introspection = await bus.introspect("org.bluez", adapter_path)
    obj = bus.get_proxy_object("org.bluez", adapter_path, introspection)
    ad_manager = obj.get_interface("org.bluez.LEAdvertisingManager1")
    adapter_props = obj.get_interface("org.freedesktop.DBus.Properties")

    # Ensure adapter is powered
    await adapter_props.call_set("org.bluez.Adapter1", "Powered", Variant("b", True))

    # Register advertisement: signature is (object path, a{sv})
    await ad_manager.call_register_advertisement(path, {})

    print("Advertisement started; running...")

    # Keep process alive so the exported object stays available
    await asyncio.get_running_loop().create_future()

asyncio.run(advertise())