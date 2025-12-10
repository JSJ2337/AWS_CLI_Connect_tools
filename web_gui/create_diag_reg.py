

# This script generates a diagnostic .reg file to test the protocol handler.
# It associates the ec2menu:// protocol with opening notepad.exe.

reg_content = r"""Windows Registry Editor Version 5.00

[HKEY_CLASSES_ROOT\ec2menu]
@="URL:ec2menu Protocol (Diagnostic)"
"URL Protocol"=""

[HKEY_CLASSES_ROOT\ec2menu\shell]

[HKEY_CLASSES_ROOT\ec2menu\shell\open]

[HKEY_CLASSES_ROOT\ec2menu\shell\open\command]
@=""C:\\Windows\\System32\\notepad.exe\" "%1"""

reg_file_path = 'diag_protocol.reg'

try:
    with open(reg_file_path, 'w', encoding='utf-8') as f:
        f.write(reg_content)
    print(f"Successfully created '{reg_file_path}'.")
    print("Please double-click this file to run it and update the registry for diagnostics.")
except IOError as e:
    print(f"Error: Failed to write to {reg_file_path}. {e}")

