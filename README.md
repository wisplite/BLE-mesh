This is the working repository for my custom Bluetooth mesh protocol.

This protocol is completely bespoke and does not adhere to any existing standards. It is designed to send messages over an arbitrarily large BLE mesh network via ~BLE 5.0 extended advertising~ GATT.

I am building this because I have yet to see any simple BLE Mesh SDK other than Bridgefy, which is proprietary, has a terrible licensing scheme, and completely opaque pricing. This project is open-source, and will always be open-source. I see no reason to make a communication protocol proprietary.

Current state:
Basic communication between two devices is working. You can run proto-send.py and proto-receiver.py to see it in action.
Theoretically this could work with more than two devices, as long as they are all within range, but I don't have enough devices to test it yet.
Currently this only works on Linux, as it communicates directly with the bluetooth stack via dbus. To my understanding, this will not work on Windows due to it's somewhat limited bluetooth API. iOS/macOS may be possible, but I don't have access to any Apple devices to test with at this moment.

TODO:
- Update the data transport to use GATT rather than extended advertising, because despite extended advertising being part of the BLE 5.0 specification, some devices do not support it for some unknown reason.
- Update the linux adapter to manage neighbor tables and handle routing on it's own, rather than relying on the client to do so.
- Make a simpler API for sending messages over the mesh, so applications built on top of it don't have to worry about the details of the protocol.
- Add support for Android devices.
- Add support for ESP32s (both as BLE mesh nodes and as WiFi/USB-based access points for unsupported devices to connect to the mesh with).
- Add routing support for handling larger meshes (currently the protocol is using flood-based message delivery).
- Once routing is implemented, add support for routing Bluetooth Classic over the mesh for high-bandwidth data transfer (sending files, streaming audio, etc.)

Potential future features (currently out of scope):
- Crypto support for secure communication
- Rely on service UUID for identifying the protocol, rather than prototype manufacturer data (0xFFFF)
