import asyncio
import linux_adapter
import os

async def on_device(device):
    return
    os.system("clear")
    print("Neighbors: ", linux_adapter.get_neighbors())
    print("Known devices: ", linux_adapter.get_known_devices())

async def main():
    handle = await linux_adapter.scan_for_mesh(on_device)
    
    advertise_handle = await linux_adapter.advertise(linux_adapter.make_packet(0x01, linux_adapter.get_seqnum(), 5, linux_adapter.get_origin_id(), b""))
    
    gatt_service, gatt_characteristic = await linux_adapter.register_gatt_server(lambda data: print(f"Data received: {data.decode('utf-8')}"))

    while True:
        input_data = await asyncio.to_thread(input, "Enter data to send: ") 
        for neighbor in linux_adapter.get_neighbors().values():
            await linux_adapter.send_data(neighbor["address"], input_data.encode("utf-8"))

    await asyncio.get_running_loop().create_future()

asyncio.run(main())