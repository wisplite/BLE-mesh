import asyncio
from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Variant

devices = {}

async def main():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    print("Connected to system bus")

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
    adapter = obj.get_interface("org.bluez.Adapter1")
    adapter_props = obj.get_interface("org.freedesktop.DBus.Properties")

    # Ensure adapter is powered and scanning LE transport
    await adapter_props.call_set("org.bluez.Adapter1", "Powered", Variant("b", True))
    try:
        await adapter.call_set_discovery_filter({"Transport": Variant("s", "le")})
    except Exception:
        # Ignore if unsupported on this BlueZ version
        pass

    await adapter.call_start_discovery()
    print("Started discovery. Scanning for mesh devices (manufacturer data 0xFFFF).")

    def on_iface_added(path, interfaces):
        if "org.bluez.Device1" in interfaces:
            props = interfaces["org.bluez.Device1"]
            mfg_data = props.get("ManufacturerData")
            if mfg_data and 0xFFFF in mfg_data.value:
                data_value = mfg_data.value
                data = bytes(data_value[0xFFFF].value)
                string_data = data.decode("utf-8")
                print(f"Manufacturer data: {string_data}")
                addr_v = props.get("Address")
                name_v = props.get("Name")
                rssi_v = props.get("RSSI")
                addr = addr_v.value if addr_v is not None else "<unknown>"
                name = name_v.value if name_v is not None else "<unknown>"
                rssi = rssi_v.value if rssi_v is not None else 0
                if addr in devices:
                    print(f"Device {name} ({addr}) already known")
                    return
                print(f"Device {name} ({addr}) found with RSSI {rssi}")
                devices[addr] = {
                    "name": name,
                    "rssi": rssi,
                }
                print(len(devices))

    # Subscribe to InterfacesAdded via typed signal (installs match rule)
    obj_manager.on_interfaces_added(on_iface_added)

    # Print already known devices immediately
    managed = await obj_manager.call_get_managed_objects()
    for path, ifaces in managed.items():
        if "org.bluez.Device1" in ifaces:
            on_iface_added(path, ifaces)

    await asyncio.get_event_loop().create_future()

asyncio.run(main())