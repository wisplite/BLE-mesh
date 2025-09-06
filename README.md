This is the working repository for my custom Bluetooth mesh protocol.

This protocol is completely bespoke and does not adhere to any existing standards. It is designed to send messages over an arbitrarily large BLE mesh network via BLE 5.0 extended advertising.

Current state:
Basic communication between two devices is working. You can run proto-send.py and proto-receiver.py to see it in action.
Theoretically this could work with more than two devices, as long as they are all within range, but I don't have enough devices to test it yet.
Currently this only works on Linux, as it communicates directly with the bluetooth stack via dbus. From my limited research, this will not work on Windows due to it's somewhat limited bluetooth API. iOS/macOS may be possible, but I don't have access to any Apple devices to test with.

TODO:
- Add protocol headers so the devices can identify each other (BLE has rolling mac addresses now), can identify the number of hops remaining, message type, order, etc.
- Make a simpler API for sending messages over the mesh, so applications built on top of it don't have to worry about the details of the protocol.
- Add support for Android devices.
- Add support for ESP32s (both as BLE mesh nodes and as access points for Windows devices to connect with).
- Add routing support for handling larger meshes (currently the protocol is using flood-based message delivery).
- Once routing is implemented, add support for routing Bluetooth Classic over the mesh for high-bandwidth data transfer (sending files, streaming audio, etc.)

Potential future features (currently out of scope):
- Crypto support for secure communication
- Rely on service UUID for identifying the protocol, rather than prototype manufacturer data (0xFFFF)
