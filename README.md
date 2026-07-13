# Yukti Compute Provider Setup Guide

Welcome to the Yukti Compute network! As a provider, you are offering your compute resources to the network. This guide will walk you through setting up the supply agent from scratch on any machine (Mac, Windows, or Linux).

## Prerequisites

Before running the agent, you must install the following core dependencies on your machine:

### 1. Python 3.x
You need Python installed to run the agent script.
* **Download:** [python.org/downloads](https://www.python.org/downloads/)
* Ensure you check **"Add Python to PATH"** during installation (especially on Windows).

### 2. Docker Desktop
The agent uses Docker to securely containerize and isolate workloads (like Jupyter Notebooks) running on your machine.
* **Download:** [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
* **Important:** After installing, you **must open Docker Desktop** and leave it running in the background. The agent cannot start workloads if the Docker Engine is stopped.

### 3. Zrok (Tunneling)
The agent uses Zrok to securely expose the containers to the renter without requiring you to open ports on your home router.
* **Mac (Homebrew):** `brew install zrok`
* **Windows (Winget):** `winget install zrok`
* **Linux / Manual:** Follow the [official Zrok installation guide](https://docs.zrok.io/docs/guides/install).

**Important:** Before running the agent, you must enable your Zrok environment.
Sign up for a free account at `zrok.io`, and then run the enable command provided to you in your terminal:
`zrok enable <your-token>`

---

## Installation

Once the prerequisites are installed and running, open your terminal/command prompt and follow these steps:

1. **Navigate to the agent directory:**
   ```bash
   cd path/to/supply-agent
   ```

2. **Install the required Python packages:**
   ```bash
   pip install -r requirements.txt
   ```
   *(Note: If you get a "command not found" error, try using `pip3` instead of `pip`)*

---

## Running the Agent

1. Make sure **Docker Desktop is open and running**.
2. Start the agent:
   ```bash
   python agent.py
   ```
   *(Note: Again, try `python3 agent.py` if `python` doesn't work)*

### What happens next?
* The agent will automatically detect your hardware (CPU cores, Total RAM).
* It will connect to the Yukti Compute network and register your machine as available.
* When a renter leases your hardware, the agent will automatically spin up a secure Docker container and provision a zrok Tunnel for them. You don't need to do anything manually!
* After you register, go to https://compute.yukticompute.educhange.app/ and adjust your settings 
  * **Note for renters:** When connecting to the Jupyter Notebook interface, the password is `gpushare123`.

## Troubleshooting

* **`[SSL: CERTIFICATE_VERIFY_FAILED]` Error on start:**
  This is a common issue with Python on Macs. We have patched the agent to use `certifi` automatically, so simply ensure you have run `pip install -r requirements.txt` recently.
  
* **"Failed to connect to Docker daemon" Warning:**
  This means Docker Desktop isn't running. Open the Docker Desktop app, wait for the engine to start (the icon stops animating), and restart the agent.
  
* **`[TUNNEL] zrok process exited` or Zrok Tunnel fails to start:**
  If you see `zrok process exited` immediately after provisioning a tunnel, it usually means `zrok` is not authenticated on this machine.
  1. Ensure `zrok` is installed (`zrok version`).
  2. Run `zrok enable <your-token>` in the terminal to authenticate this machine.
  3. If you are unsure, run `zrok status` to verify your environment is enabled.
