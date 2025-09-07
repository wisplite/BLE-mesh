import socketio
import linux_adapter
import asyncio
import json

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

app = socketio.ASGIApp(sio)

scan_handle = None
advertise_handle = None

async def bluetooth_setup():
    global scan_handle, advertise_handle
    scan_handle = await linux_adapter.scan_for_mesh(on_device)
    advertise_handle = await linux_adapter.advertise(linux_adapter.make_packet(0x01, linux_adapter.get_seqnum(), 5, linux_adapter.get_origin_id(), b""))
    gatt_service, gatt_characteristic = await linux_adapter.register_gatt_server(forward_message)
    asyncio.get_running_loop().create_future()

async def on_device(device):
    devices = linux_adapter.get_neighbors()
    await sio.emit("connected_devices", json.dumps(devices))
    return

async def forward_message(message):
    message_decoded = message.decode("utf-8")
    message_sender = message_decoded[:8]
    message_data = message_decoded[8:]
    await sio.emit("message", json.dumps({"message": message_data, "sender": message_sender, "isMe": False}))

@sio.event
async def connect(sid, environ, auth):
    print("connected to server")
    devices = linux_adapter.get_neighbors()
    await sio.emit("connected_devices", json.dumps(devices))
    #debug
    await sio.emit("message", json.dumps({"message": "connected to server", "sender": "server", "isMe": False}))

@sio.event
async def send_message(sid, data):
    print(f"Received message: {data}")
    data = json.loads(data)
    neighbors = linux_adapter.get_neighbors()
    for neighbor in neighbors:
        linux_adapter.send_data(neighbor["address"], [f"{linux_adapter.get_origin_id()}{data['message']}".encode("utf-8")])

@sio.event
async def disconnect(sid):
    print("disconnected from server")

if __name__ == "__main__":
    import uvicorn
    asyncio.run(bluetooth_setup())
    uvicorn.run(app, host="0.0.0.0", port=8000)