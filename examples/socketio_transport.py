import socketio
import linux_adapter
import asyncio
import json

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

app = socketio.ASGIApp(
    sio,
    on_startup=lambda: asyncio.create_task(bluetooth_setup()),
    on_shutdown=lambda: asyncio.create_task(bluetooth_cleanup()),
)

scan_handle = None
advertise_handle = None

async def bluetooth_setup():
    global scan_handle, advertise_handle
    scan_handle = await linux_adapter.scan_for_mesh(on_device)
    advertise_handle = await linux_adapter.advertise(linux_adapter.make_packet(0x01, linux_adapter.get_seqnum(), 5, linux_adapter.get_origin_id(), b""))
    # Ensure async callback is scheduled properly even though register_gatt_server expects a sync callback
    gatt_service, gatt_characteristic = await linux_adapter.register_gatt_server(lambda data: asyncio.create_task(forward_message(data)))

async def bluetooth_cleanup():
    global scan_handle, advertise_handle
    try:
        if scan_handle is not None:
            await scan_handle.stop()
    except Exception:
        pass
    try:
        if advertise_handle is not None:
            await advertise_handle.stop()
    except Exception:
        pass

async def format_devices(devices):
    formatted_devices = []
    for device in devices.values():
        formatted_devices.append({"user": device["origin_id"].hex(), "rssi": f"{device['rssi']}dBm"})
    return formatted_devices

async def on_device(device):
    devices = linux_adapter.get_neighbors()
    await sio.emit("connected_devices", json.dumps(await format_devices(devices)))
    return

async def forward_message(message):
    message_decoded = message.decode("utf-8")
    message_sender = message_decoded[:16]
    message_data = message_decoded[16:]
    await sio.emit("message", json.dumps({"message": message_data, "sender": message_sender, "isMe": False}))

@sio.event
async def connect(sid, environ, auth):
    print("connected to server")
    devices = linux_adapter.get_neighbors()
    await sio.emit("connected_devices", json.dumps(await format_devices(devices)))
    #debug
    await sio.emit("message", json.dumps({"message": "connected to server", "sender": "server", "isMe": False}))

@sio.event
async def send_message(sid, data):
    print(f"Received message: {data}")
    data = json.loads(data)
    neighbors = linux_adapter.get_neighbors()
    for neighbor in neighbors.values():
        await linux_adapter.send_data(neighbor["address"], [f"{linux_adapter.get_origin_id().hex()}{data['message']}".encode("utf-8")])

@sio.event
async def disconnect(sid):
    print("disconnected from server")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)