import asyncio
import websockets
import json
import requests
import os
import shutil

def fetch_file_details(url):
    try:
        response = requests.get(url)
        data = response.json()
        details = data["result"]["status"]["virtual_sdcard"]
        print(f"File details fetched: {details}")
        return details
    except Exception as e:
        print(f"Error fetching file details: {e}")
        return None

def find_last_z_position(content, up_to_position):
    last_position = content.rfind('\nG1 Z', 0, up_to_position)
    if last_position == -1:
        return None
    end_of_line = content.find('\n', last_position + 1)
    if end_of_line == -1:
        end_of_line = len(content)
    return content[last_position:end_of_line]

def trim_gcode_file_streaming(original_file_path, current_byte_position, new_file_path):
    try:
        with open(original_file_path, 'r', encoding='utf-8') as file:
            buffer = file.read()

        # Find the start of the line after the current byte position
        cut_position = buffer.rfind('\n', 0, current_byte_position) + 1

        # Find the last G1 Z position line before the cut
        last_z_position_line = find_last_z_position(buffer, cut_position)
        if last_z_position_line:
            print(f"Last Z position line to include: {last_z_position_line.strip()}")

        # Write the remaining lines to a new file
        if cut_position < len(buffer):
            with open(new_file_path, 'w', encoding='utf-8') as new_file:
                if last_z_position_line:
                    new_file.write(last_z_position_line + '\n')  # Add the last Z position at the start
                new_file.write(buffer[cut_position:])
            print(f"New file created: {new_file_path}")
        else:
            print("No content to write to the new file.")
    except Exception as e:
        print(f"Error during file trimming: {e}")

async def monitor_virtual_sdcard(uri, moonraker_http_url):
    details = fetch_file_details(f"{moonraker_http_url}/printer/objects/query?virtual_sdcard")
    file_size = details["file_size"]
    original_file_path = details["file_path"]
    file_name = os.path.basename(original_file_path)
    new_file_name = f"reCover_{file_name}"
    new_file_path = os.path.join(os.path.dirname(original_file_path), new_file_name)

    shutil.copy2(original_file_path, original_file_path + ".backup")
    print("Backup created.")

    async with websockets.connect(uri) as websocket:
        subscribe_message = {
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": {"objects": {"virtual_sdcard": None}},
            "id": 1
        }
        await websocket.send(json.dumps(subscribe_message))

        print("Subscribed to virtual_sdcard updates.")
        while True:
            response = await websocket.recv()
            response_data = json.loads(response)
            if 'method' in response_data and response_data.get('method') == 'notify_status_update':
                params = response_data.get('params', [])
                if params and isinstance(params[0], dict):
                    virtual_sdcard = params[0].get('virtual_sdcard', {})
                    is_active = virtual_sdcard.get('is_active', True)  # Default to True if not present
                    file_position = virtual_sdcard.get('file_position')
                    progress = virtual_sdcard.get('progress', 0) * 100  # Convert progress to percentage
                    print(f"Progress: {progress:.2f}%, File Position: {file_position} bytes, Active: {is_active}")

                    if not is_active:
                        print("Print is no longer active, trimming file...")
                        trim_gcode_file_streaming(original_file_path, file_position, new_file_path)
                        break  # Exit after trimming

# Moonraker HTTP API URL and WebSocket URI for localhost
moonraker_http_url = "http://localhost"
uri = "ws://localhost/websocket"

asyncio.run(monitor_virtual_sdcard(uri, moonraker_http_url))
