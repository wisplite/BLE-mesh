import asyncio
import linux_adapter
import os
import base64
import json
import time

selectable_devices = {}
file_data = b""
file_metadata = {}
num_packets_received = 0
start_time = None

async def on_device(device):
    selectable_devices[device["address"]] = device
    return

async def on_data(data):
    global file_data, file_metadata, num_packets_received, start_time
    json_data = None
    try:
        json_data = json.loads(data.decode("utf-8"))
    except Exception:
        pass # non-json data is the raw file data, no need to decode it
    if json_data and json_data['t'] == 'b64data':
        start_time = time.time()
        num_packets_received = 0
        file_data = b""
        file_metadata = json_data
    elif json_data and json_data['t'] == 'end':
        print(f"File received in {time.time() - start_time} seconds")
        with open(f"received_file.{file_metadata['e']}", "wb") as f:
            f.write(base64.b64decode(file_data))
        file_data = b""
    else:
        os.system("clear")
        num_packets_received += 1
        print(f"Packets received: {num_packets_received}/{file_metadata['c']}, {num_packets_received/file_metadata['c']*100}% complete, {((file_metadata['c'] - num_packets_received)/num_packets_received)*(time.time() - start_time)} seconds remaining")
        file_data += data

async def main():
    await linux_adapter.scan_for_mesh(on_device)
    await linux_adapter.advertise(linux_adapter.make_packet(0x01, linux_adapter.get_seqnum(), 5, linux_adapter.get_origin_id(), b""))
    gatt_service, gatt_characteristic = await linux_adapter.register_gatt_server(lambda data: asyncio.create_task(on_data(data)))

    while True:
        os.system("clear")
        print("Selectable devices:")
        print("--------------------------------")
        device_num = 1
        selectable_devices_list = {}
        for device in selectable_devices.values():
            print(f"Device {device_num}: {device['address']} ({device['origin_id']})")
            selectable_devices_list[device_num] = device
            device_num += 1
        print("--------------------------------")
        print("Enter the number of the device you want to select (0 to refresh):")
        device_num = int(await asyncio.to_thread(input, ""))
        if device_num == 0:
            continue
        if device_num in selectable_devices_list:
            print(f"Selected device: {selectable_devices_list[device_num]['address']} ({selectable_devices_list[device_num]['name']})")
            print("Enter the path of the file you want to send:")
            file_path = await asyncio.to_thread(input, "")
            if os.path.exists(file_path):
                print(f"File {file_path} exists")
                with open(file_path, "rb") as f:
                    file_data = f.read()
                    base64_data = base64.b64encode(file_data)
                    packets = [{'t':'b64data','e': file_path.split(".")[-1],'c':0}]
                    packet_length_bytes = 192
                    for i in range(0, len(base64_data), packet_length_bytes):
                        packets.append(base64_data[i:i+packet_length_bytes])
                    packets.append({'t':'end'})
                    packets[0]['c'] = len(packets) - 2 # remove protocol packets from count
                    packets[0] = json.dumps(packets[0]).encode("utf-8")
                    packets[-1] = json.dumps(packets[-1]).encode("utf-8")
                    await linux_adapter.send_data(selectable_devices_list[device_num]["address"], packets)
            else:
                print("File does not exist")
                continue
        else:
            print("Invalid device number")
            continue
        await asyncio.sleep(1)

    await asyncio.get_running_loop().create_future()

asyncio.run(main())