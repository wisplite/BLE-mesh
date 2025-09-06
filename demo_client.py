import asyncio
import linux_adapter

async def on_device(device):
    print("Message from device: ", device)
    print("Parsed payload:", linux_adapter.parse_packet(device["manufacturer_data_bytes"]))

async def main():
    handle = await linux_adapter.scan_for_mesh(on_device)
    if not handle:
        print("No handle found")
        return
    
    while True:
        input_data = input("Enter data to send: ")
        packet = linux_adapter.make_chat_packet(seqnum=linux_adapter.get_seqnum(), origin_id=linux_adapter.get_origin_id(), msg=input_data)
        await linux_adapter.send_packet(packet)

asyncio.run(main())