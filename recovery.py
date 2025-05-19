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

def find_initial_settings(content):
    end_of_settings = content.find(';flag')
    if end_of_settings == -1:
        return ""
    return content[:end_of_settings + len(';flag')]

def find_last_z_position(content, up_to_position):
    last_position = content.rfind('\nG1 Z', 0, up_to_position)
    if last_position == -1:
        return None
    end_of_line = content.find('\n', last_position + 1)
    if end_of_line == -1:
        end_of_line = len(content)
    return content[last_position:end_of_line]

def find_last_two_gcode_commands(content, up_to_position):
    # Finds the last two G-code commands before the specified position
    last_position = content.rfind('\n', 0, up_to_position)
    if last_position == -1:
        return None
    second_last_position = content.rfind('\n', 0, last_position - 1)
    if second_last_position == -1:
        return content[:last_position]  # Return the only line if only one exists
    return content[second_last_position+1:last_position]

async def monitor_virtual_sdcard(uri, moonraker_http_url):
    details = fetch_file_details(f"{moonraker_http_url}/printer/objects/query?virtual_sdcard")
    if not details:
        print("Failed to fetch printer details.")
        return

    progress_file = "progress.txt"
    # Read last file_position from progress file if it exists and is not 0
    resume_position = None
    if os.path.exists(progress_file):
        with open(progress_file, 'r') as pf:
            try:
                val = int(pf.read().strip())
                if val > 0:
                    resume_position = val
            except Exception:
                pass

    last_speed = 0  # Variable to store the last known speed
    async with websockets.connect(uri) as websocket:
        # Subscribe to virtual_sdcard and gcode_move objects
        subscribe_message = {
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": {
                "objects": {
                    "virtual_sdcard": None,
                    "gcode_move": None
                }
            },
            "id": 1
        }
        await websocket.send(json.dumps(subscribe_message))

        # Listen for updates
        while True:
            response = await websocket.recv()
            response_data = json.loads(response)
            if 'method' in response_data and response_data.get('method') == 'notify_status_update':
                params = response_data.get('params', [])
                if 'gcode_move' in params[0]:
                    last_speed = params[0]['gcode_move'].get('speed', last_speed)
                if 'virtual_sdcard' in params[0]:
                    virtual_sdcard = params[0]['virtual_sdcard']
                    is_active = virtual_sdcard.get('is_active', True)
                    file_position = virtual_sdcard.get('file_position')

                    # Write file_position to progress file if not 0
                    if file_position and file_position > 0:
                        with open(progress_file, 'w') as pf:
                            pf.write(str(file_position))

                    if not is_active:
                        original_file_path = details["file_path"]
                        file_name = os.path.basename(original_file_path)
                        new_file_name = f"reCover_{file_name}"
                        new_file_path = os.path.join(os.path.dirname(original_file_path), new_file_name)

                        shutil.copy2(original_file_path, original_file_path + ".backup")
                        print("Backup created.")
                        print("Print is no longer active, trimming file...")

                        with open(original_file_path, 'r', encoding='utf-8') as file:
                            buffer = file.read()
                        initial_settings = find_initial_settings(buffer)
                        # Use resume_position if available, else use file_position
                        trim_position = resume_position if resume_position is not None else file_position
                        last_z_position_line = find_last_z_position(buffer, trim_position)
                        last_two_commands = find_last_two_gcode_commands(buffer, trim_position)

                        with open(new_file_path, 'w', encoding='utf-8') as new_file:
                            new_file.write(initial_settings + '\n')
                            if last_z_position_line:
                                new_file.write(last_z_position_line + '\n')
                            if last_two_commands:
                                new_file.write(last_two_commands + '\n')
                            new_file.write(f'G1 F{last_speed}\n')  # Append the last known speed
                            new_file.write(buffer[trim_position:])
                        print(f"New file created: {new_file_path}")

                        # Clear the progress file
                        with open(progress_file, 'w') as pf:
                            pf.write("")
                        break  # Exit after trimming

# Moonraker HTTP API URL and WebSocket URI for localhost
moonraker_http_url = "http://localhost"
uri = "ws://localhost/websocket"
asyncio.run(monitor_virtual_sdcard(uri, moonraker_http_url))