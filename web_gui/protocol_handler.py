

import sys
import subprocess
import urllib.parse
from pathlib import Path

# Add the parent directory to the Python path to find the ec2menu module
script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parent))

try:
    import ec2menu_v4_41 as ec2menu
except ImportError:
    # In a real app, you'd want more robust error handling, maybe a message box.
    print("Fatal: Could not import ec2menu_v4_41.py.")
    sys.exit(1)

def log_error(message):
    """A simple logger for debugging."""
    log_file = script_dir / "protocol_handler.log"
    with open(log_file, "a") as f:
        f.write(f"{message}\n")

def main():
    """Parses the protocol URL and launches the connection."""
    log_error(f"Handler started with args: {sys.argv}")

    if len(sys.argv) < 2:
        log_error("Error: No URL provided.")
        return

    url = sys.argv[1]
    if not url.startswith("ec2menu://"):
        log_error(f"Error: Invalid URL scheme: {url}")
        return

    try:
        parsed_url = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed_url.query)

        # Extract parameters, providing None as a default
        conn_type = params.get('type', [None])[0]
        instance_id = params.get('instance_id', [None])[0]
        profile = params.get('profile', [None])[0]
        region = params.get('region', [None])[0]
        platform = params.get('platform', ["linux"])[0] # Default to linux if not specified

        if not all([conn_type, instance_id, profile, region]):
            log_error(f"Error: Missing required parameters in URL: {url}")
            return

        log_error(f"Executing: type={conn_type}, iid={instance_id}, prof={profile}, reg={region}, plat={platform}")

        # Based on the connection type, execute the command
        if conn_type == 'ec2':
            if 'windows' in platform.lower():
                # For Windows, start port forwarding and launch RDP
                local_port = 10000 + (int(instance_id[-3:], 16) % 1000)
                # The original script returns a Popen object. We just need to run it.
                proc = ec2menu.start_port_forward(profile, region, instance_id, local_port)
                # Give it a moment to establish the connection
                import time
                time.sleep(3)
                ec2menu.launch_rdp(local_port)
                log_error(f"Started RDP forwarding for {instance_id} on localhost:{local_port}")
            else:
                # For Linux, launch in Windows Terminal
                ec2menu.launch_linux_wt(profile, region, instance_id)
                log_error(f"Started SSM session for {instance_id}")
        else:
            log_error(f"Error: Unsupported connection type '{conn_type}'")

    except Exception as e:
        log_error(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()

