import sys
import os
import subprocess
from pathlib import Path

# This script generates a .reg file to register a custom URL protocol handler
# for ec2menu:// on Windows.

def is_running_in_wsl():
    """Checks if the script is running in a WSL environment."""
    return 'WSL_DISTRO_NAME' in os.environ or (
        os.path.exists('/proc/version') and 'microsoft' in open('/proc/version').read().lower()
    )

def wsl_path_to_win(wsl_path):
    """Converts a WSL path like /mnt/d/folder to D:\folder"""
    wsl_path = str(wsl_path)
    if wsl_path.startswith('/mnt/'):
        try:
            # Use wslpath utility for the most reliable conversion
            result = subprocess.run(['wslpath', '-w', wsl_path], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to manual conversion if wslpath isn't available
            parts = wsl_path.split('/')
            drive = parts[2].upper()
            path = '\\'.join(parts[3:])
            return f"{drive}:\\{path}"
    return wsl_path

def generate_reg_file():
    """Generates the .reg file with the correct Python path for Windows."""
    handler_script_path_obj = Path(__file__).parent.resolve() / 'protocol_handler.py'

    if is_running_in_wsl():
        print("WSL environment detected. Generating Windows-compatible paths.")
        # In WSL, use the py.exe launcher which is standard on Windows.
        # This is more reliable than assuming pyw.exe is on the PATH.
        python_executable_path = "py.exe"
        handler_script_path = wsl_path_to_win(handler_script_path_obj)
        print(f"Python executable set to: {python_executable_path}")
        print(f"Converted handler script path to: {handler_script_path}")
    else:
        # Running on native Windows, find pythonw.exe relative to python.exe.
        python_exe_path = Path(sys.executable)
        pythonw_exe_path = python_exe_path.parent / 'pythonw.exe'
        if not pythonw_exe_path.exists():
            print(f"Warning: pythonw.exe not found at {pythonw_exe_path}. Falling back to python.exe.")
            print("A console window may briefly appear when you click a connection link.")
            python_executable_path = str(python_exe_path)
        else:
            python_executable_path = str(pythonw_exe_path)
        handler_script_path = str(handler_script_path_obj)

    # Escape backslashes for the .reg file format
    python_path_reg = python_executable_path.replace('\\', '\\\\')
    script_path_reg = handler_script_path.replace('\\', '\\\\')

    reg_content = f"""Windows Registry Editor Version 5.00

[HKEY_CLASSES_ROOT\\ec2menu]
@=\"URL:ec2menu Protocol\"
\"URL Protocol\"=\"\"

[HKEY_CLASSES_ROOT\\ec2menu\\shell]

[HKEY_CLASSES_ROOT\\ec2menu\\shell\\open]

[HKEY_CLASSES_ROOT\\ec2menu\\shell\\open\\command]
@=\"\\\"{python_path_reg}\\\" \\\"{script_path_reg}\\\" \\\"%1\\\"\""
"""

    reg_file_path = Path(__file__).parent / 'register_protocol.reg'
    try:
        with open(reg_file_path, 'w', encoding='utf-8') as f:
            f.write(reg_content)
        print(f"\nSuccessfully created '{reg_file_path}'.")
        print("From Windows File Explorer, please double-click this file to register the protocol.")
    except IOError as e:
        print(f"Error: Failed to write to {reg_file_path}. {e}")

if __name__ == '__main__':
    generate_reg_file()