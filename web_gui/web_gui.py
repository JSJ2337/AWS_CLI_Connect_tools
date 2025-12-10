
import os
import sys
from flask import Flask, render_template, request, session, redirect, url_for
from pathlib import Path

# Add the parent directory to the Python path to find the ec2menu module
script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parent))

# Now, import the functions from the ec2menu script
try:
    import ec2menu_v4_41 as ec2menu
except ImportError:
    print("Error: Could not import ec2menu_v4_41.py. Make sure the file exists and is in the same directory.")
    sys.exit(1)

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route('/')
def index():
    """Home page, shows AWS profiles."""
    profiles = ec2menu.list_profiles()
    return render_template('index.html', profiles=profiles)

@app.route('/select_profile/<profile_name>')
def select_profile(profile_name):
    """Store profile in session and show region list."""
    session['profile'] = profile_name
    manager = ec2menu.AWSManager(profile=profile_name)
    
    # This can be slow, so we're doing it directly.
    # In a real application, this should be done asynchronously.
    regions = manager.list_regions()
    
    # For simplicity, we list all regions. The original script filters them.
    # We can add the filtering logic later if needed.
    return render_template('select_region.html', regions=regions, profile=profile_name)

@app.route('/main_menu/<region_name>')
def main_menu(region_name):
    """Store region in session and show the main menu."""
    session['region'] = region_name
    return render_template('main_menu.html', profile=session['profile'], region=session['region'])

@app.route('/list_ec2')
def list_ec2():
    """List EC2 instances for the selected profile and region."""
    if 'profile' not in session or 'region' not in session:
        return redirect(url_for('index'))

    manager = ec2menu.AWSManager(profile=session['profile'])
    instances_raw = manager.list_instances(session['region'])
    
    instances_display = []
    for i in instances_raw:
        name = next((t['Value'] for t in i.get('Tags', []) if t['Key'] == 'Name'), '')
        instances_display.append({
            'raw': i, 'Name': name,
            'PublicIp': i.get('PublicIpAddress', '-'),
            'PrivateIp': i.get('PrivateIpAddress', '-'),
            'InstanceId': i['InstanceId'],
            'InstanceType': i.get('InstanceType', '-'),
            'State': i['State']['Name'],
            'Platform': i.get('PlatformDetails', 'Linux/UNIX'),
        })
    
    instances = sorted(instances_display, key=lambda x: x['Name'])
    
    return render_template('ec2_list.html', 
                           instances=instances, 
                           profile=session['profile'], 
                           region=session['region'])

@app.route('/connect_ec2', methods=['POST'])
def connect_ec2():
    """Generate connection command for a specific EC2 instance."""
    if 'profile' not in session or 'region' not in session:
        return redirect(url_for('index'))

    instance_id = request.form['instance_id']
    platform = request.form['platform']
    profile = session['profile']
    region = session['region']

    connection_info = {}

    if 'windows' in platform.lower():
        local_port = 10000 + (int(instance_id[-3:], 16) % 1000)
        command_list = ec2menu.create_ssm_forward_command(
            profile, region, instance_id, 'AWS-StartPortForwardingSession',
            f'{{"portNumber":["3389"],"localPortNumber":["{local_port}"]}}'
        )
        connection_info['type'] = 'Windows RDP'
        connection_info['command'] = ' '.join(command_list)
        connection_info['rdp_address'] = f'localhost:{local_port}'
        connection_info['message'] = "1. 아래 명령어를 터미널에서 실행하여 포트 포워딩을 시작하세요.\n2. 포워딩이 시작되면, 아래 RDP 주소로 원격 데스크톱 연결을 실행하세요."

    else:
        command_list = ec2menu.ssm_cmd(profile, region, instance_id)
        connection_info['type'] = 'Linux Shell (SSM)'
        connection_info['command'] = ' '.join(command_list)
        connection_info['message'] = "아래 명령어를 복사하여 터미널에 붙여넣으면 SSM 세션이 시작됩니다."

    return render_template('ec2_connect.html', info=connection_info, region=region)

if __name__ == '__main__':
    # Ensure the templates directory exists
    if not os.path.exists(os.path.join(script_dir, 'templates')):
        os.makedirs(os.path.join(script_dir, 'templates'))
    
    # For development, we can run it this way.
    # For production, a proper WSGI server should be used.
    app.run(debug=True, port=5000)
