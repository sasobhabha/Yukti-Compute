import asyncio
import websockets
import json
import uuid
import docker
import sys

GPU_ID = "gpu-" + str(uuid.uuid4())[:8]

# Setup docker client
client = None
try:
    client = docker.from_env()
    client.ping() # test connection
except Exception as e:
    print("\n[WARNING] Failed to connect to Docker daemon. Is Docker running?")
    print("The agent will continue to run and register on the network, but cannot launch real containers until Docker is started.\n")

def start_docker_container(image, port):
    print(f"Starting container {image} on port {port}...")
    if not client:
        print("[ERROR] Cannot start container. Docker is not running.")
        print("Please start Docker Desktop and restart this agent to enable real container deployments.")
        return "MOCK_CONTAINER_ID_BECAUSE_DOCKER_IS_DOWN", 8888
        
    try:
        mem_limit = f"{SHARED_RAM_GB}g" if SHARED_RAM_GB else "2g"
        print(f"Enforcing hard memory limit of: {mem_limit}")
        
        container = client.containers.run(
            image,
            detach=True,
            ports={'8888/tcp': None}, # Auto-assign random available host port
            environment={
                "JUPYTER_ENABLE_LAB": "yes", 
                "JUPYTER_TOKEN": "gpushare123",
                "JUPYTER_SERVER_APP_ALLOW_ORIGIN": "*",
                "JUPYTER_SERVER_APP_DISABLE_CHECK_XSRF": "True",
                "JUPYTER_SERVER_APP_ALLOW_REMOTE_ACCESS": "True"
            },
            mem_limit=mem_limit,
            remove=True
        )
        
        # Refresh container object to get the assigned port
        container.reload()
        host_port = container.attrs['NetworkSettings']['Ports']['8888/tcp'][0]['HostPort']
        
        print(f"Container started: {container.id[:10]} on Port {host_port}")
        return container, host_port
    except Exception as e:
        print(f"Failed to start container: {e}")
        return None, None

import platform
from aiohttp import web

# Global state to track how much hardware the user has agreed to share
SHARED_RAM_GB = None
SHARED_CORES = None
SHARED_VRAM_GB = None
ws_connection = None

def detect_gpus():
    import subprocess
    import platform
    import re
    gpus = []
    sys_os = platform.system()
    if sys_os == "Darwin":
        try:
            out = subprocess.check_output(["system_profiler", "SPDisplaysDataType"]).decode("utf-8")
            if "Apple M" in out or "Apple Silicon" in out or "Apple A" in out or "Apple M" in platform.processor():
                import psutil
                ram_gb = round(psutil.virtual_memory().total / (1024.**3))
                match = re.search(r'Chipset Model:\s*(.+)', out)
                name = match.group(1).strip() if match else "Apple Silicon GPU"
                return [{"name": name, "vram_gb": ram_gb, "type": "unified"}]
            else:
                match = re.search(r'Chipset Model:\s*(.+)', out)
                name = match.group(1).strip() if match else "Mac GPU"
                vram_gb = 0
                vram_match = re.search(r'VRAM[^\:]*:\s*(\d+)\s*GB', out)
                if vram_match:
                    vram_gb = int(vram_match.group(1))
                else:
                    vram_match_mb = re.search(r'VRAM[^\:]*:\s*(\d+)\s*MB', out)
                    if vram_match_mb:
                        vram_gb = int(vram_match_mb.group(1)) // 1024
                return [{"name": name, "vram_gb": vram_gb, "type": "discrete"}]
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]).decode("utf-8")
            for line in out.strip().split('\n'):
                parts = line.split(',')
                if len(parts) >= 2:
                    name = parts[0].strip()
                    vram_str = parts[1].strip()
                    vram_gb = int(vram_str.replace(" MiB", "")) // 1024
                    gpus.append({"name": name, "vram_gb": vram_gb, "type": "discrete"})
            if gpus:
                return gpus
        except Exception:
            pass
    return [{"name": "No discrete GPU", "vram_gb": 0, "type": "none"}]

async def handle_status(request):
    import psutil
    ram_gb = round(psutil.virtual_memory().total / (1024.**3))
    cpu_name = platform.processor() or "Apple Silicon / Intel"
    cores = psutil.cpu_count(logical=True) or 1
    gpus = detect_gpus()
    gpu = gpus[0]
    
    global SHARED_RAM_GB, SHARED_CORES, SHARED_VRAM_GB
    if SHARED_RAM_GB is None:
        SHARED_RAM_GB = ram_gb // 2 # Default to half
    if SHARED_CORES is None:
        SHARED_CORES = cores // 2
    if SHARED_VRAM_GB is None:
        SHARED_VRAM_GB = gpu['vram_gb'] // 2 if gpu['vram_gb'] > 0 else 0
        
    return web.json_response({
        "hardware": f"{cpu_name}",
        "cores": cores,
        "ram_gb": ram_gb,
        "gpu_name": gpu['name'],
        "vram_gb": gpu['vram_gb'],
        "gpu_type": gpu['type'],
        "shared_ram_gb": SHARED_RAM_GB,
        "shared_cores": SHARED_CORES,
        "shared_vram_gb": SHARED_VRAM_GB,
        "earnings": 0.00,
        "uptime_hrs": 0,
        "active_workloads": 0
    }, headers={"Access-Control-Allow-Origin": "*"})

async def handle_config(request):
    global SHARED_RAM_GB, SHARED_CORES, SHARED_VRAM_GB, ws_connection
    try:
        data = await request.json()
        if 'shared_ram' in data:
            SHARED_RAM_GB = int(data['shared_ram'])
        if 'shared_cores' in data:
            SHARED_CORES = int(data['shared_cores'])
        if 'shared_vram' in data:
            SHARED_VRAM_GB = int(data['shared_vram'])
            
        print(f"[CONFIG] Provider allocated {SHARED_CORES} cores, {SHARED_RAM_GB}GB RAM, {SHARED_VRAM_GB}GB VRAM.")
        
        if ws_connection:
            cpu_name = platform.processor() or "Apple Silicon / Intel"
            gpu = detect_gpus()[0]
            await ws_connection.send(json.dumps({
                "type": "update",
                "gpu_info": {
                    "id": GPU_ID,
                    "name": f"{cpu_name} + {gpu['name']} (Shared RAM: {SHARED_RAM_GB}GB, VRAM: {SHARED_VRAM_GB}GB)",
                    "ram": SHARED_RAM_GB,
                    "cores": SHARED_CORES,
                    "vram": SHARED_VRAM_GB
                }
            }))
            print("[SYNC] Broadcasted new hardware allocation to the Cloudflare Edge.")
            
        return web.json_response({"status": "success"}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400, headers={"Access-Control-Allow-Origin": "*"})
    
async def handle_options(request):
    return web.Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    })

async def start_local_server():
    app = web.Application()
    app.add_routes([
        web.get('/api/status', handle_status),
        web.post('/api/config', handle_config),
        web.options('/api/config', handle_options)
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8282)
    await site.start()
    print("Local Dashboard API running on http://localhost:8282")

async def agent_loop():
    # Start the local API server for the dashboard
    await start_local_server()
    
    uri = f"wss://yukti-compute-backend.manjunath-shankar.workers.dev/ws/agent/{GPU_ID}"
    
    # Try connecting
    while True:
        try:
            print("Connecting to Yukti Compute network...")
            import ssl
            import certifi
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            async with websockets.connect(uri, ssl=ssl_context) as websocket:
                global ws_connection
                ws_connection = websocket
                
                print("Connected to GPU Share Network!")
                
                import platform
                import psutil
                
                # Setup initial info
                global SHARED_RAM_GB, SHARED_CORES, SHARED_VRAM_GB
                gpu = detect_gpus()[0]
                if SHARED_RAM_GB is None:
                    SHARED_RAM_GB = round(psutil.virtual_memory().total / (1024.**3)) // 2
                if SHARED_CORES is None:
                    SHARED_CORES = (psutil.cpu_count(logical=True) or 1) // 2
                if SHARED_VRAM_GB is None:
                    SHARED_VRAM_GB = gpu['vram_gb'] // 2 if gpu['vram_gb'] > 0 else 0
                
                cpu_name = platform.processor() or "Apple Silicon / Intel"
                
                # Register using REAL specs
                gpu_info = {
                    "id": GPU_ID,
                    "name": f"{cpu_name} + {gpu['name']} (Shared RAM: {SHARED_RAM_GB}GB, VRAM: {SHARED_VRAM_GB}GB)",
                    "ram": SHARED_RAM_GB,
                    "cores": SHARED_CORES,
                    "vram": SHARED_VRAM_GB
                }
                
                await websocket.send(json.dumps({
                    "type": "register",
                    "gpu_info": gpu_info
                }))
                
                # Listen for commands
                async for msg in websocket:
                    data = json.loads(msg)
                    
                    if data.get("type") == "start_container":
                        print(f"Received request to start {data['image']} for lease {data['lease_id']}")
                        container, assigned_port = start_docker_container(data['image'], 8888)
                        
                        if container and assigned_port:
                            print(f"Provisioning public zrok Tunnel for port {assigned_port}...")
                            # Start zrok process asynchronously
                            tunnel_proc = await asyncio.create_subprocess_exec(
                                'zrok', 'share', 'public', f'http://127.0.0.1:{assigned_port}', '--headless',
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.STDOUT
                            )
                            
                            tunnel_url = None
                            
                            async def scrape_stream(stream):
                                nonlocal tunnel_url
                                while True:
                                    line = await stream.readline()
                                    if not line:
                                        print("[TUNNEL] zrok process exited.")
                                        break
                                    line = line.decode('utf-8').strip()
                                    print(f"[TUNNEL] {line}")
                                    
                                    # Extract URL
                                    if not tunnel_url:
                                        import re
                                        match = re.search(r'(https?://[a-zA-Z0-9.-]+\.zrok\.io)', line)
                                        if match:
                                            url = match.group(1)
                                            
                                            # The zrok frontend may serve HTTP but output HTTPS in logs
                                            # We downgrade the link to HTTP to avoid ERR_SSL_PROTOCOL_ERROR if it's the case
                                            url = url.replace("https://", "http://")
                                            
                                            print(f"[TUNNEL] Provisioned! URL: {url}")
                                            
                                            # Send lease started event
                                            await websocket.send(json.dumps({
                                                "type": "lease_started",
                                                "lease_id": data['lease_id'],
                                                "connection_url": url
                                            }))
                                            tunnel_url = url
                                            break
                            
                            # Start a background task to constantly read stream
                            # We keep a strong reference to it so it doesn't get garbage collected
                            stream_task = asyncio.create_task(scrape_stream(tunnel_proc.stdout))
                            data["_stream_task"] = stream_task # Store in data dict to keep reference alive
                            
                            # Wait for URL
                            for _ in range(600): # Wait up to 60 seconds
                                if tunnel_url:
                                    break
                                await asyncio.sleep(0.1)
                                
                            if tunnel_url:
                                print(f"Waiting 5 seconds for zrok DNS to propagate...")
                                await asyncio.sleep(5)
                                connection_url = f"{tunnel_url}/?token=gpushare123"
                                print(f"[SUCCESS] Public environment ready at: {connection_url}")
                                
                                await websocket.send(json.dumps({
                                    "type": "lease_started",
                                    "lease_id": data["lease_id"],
                                    "connection_url": connection_url
                                }))
                            else:
                                print("[ERROR] Failed to get zrok tunnel URL within 60 seconds.")
                                await websocket.send(json.dumps({
                                    "type": "error",
                                    "lease_id": data["lease_id"],
                                    "message": "Failed to provision public tunnel."
                                }))
        except Exception as e:
            print(f"Connection error: {e}. Retrying in 5s...")
        finally:
            ws_connection = None
            
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(agent_loop())
