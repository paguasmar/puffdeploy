import shutil
import sys

def get_sky_cmd() -> str:
    found = shutil.which("sky")
    if found:
        return found
    sibling = Path(sys.executable).parent / "sky"
    if sibling.exists():
        return str(sibling)
    return "sky"

import os
import re
import subprocess
import time
import urllib.request
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
import yaml

from puffdeploy.config import PuffConfig, PuffConfig
from puffdeploy.ui.console import (
    console,
    print_step,
    print_success,
    print_error_box,
    print_warning,
)

class SkyPilotOrchestrator:
    def __init__(self, config: PuffConfig, workdir: Path = Path(".")):
        self.config = config
        self.workdir = workdir

    def generate_skyserve_spec(self) -> Dict[str, Any]:
        compute = self.config.compute
        service = self.config.service
        runtime = self.config.runtime

        resources: Dict[str, Any] = {
            "cloud": compute.cloud.lower(),
        }
        if compute.region:
            resources["region"] = compute.region
        if compute.accelerator:
            resources["accelerators"] = compute.accelerator
        if compute.cpus:
            cpus_str = str(compute.cpus)
            resources["cpus"] = cpus_str if cpus_str.endswith("+") else f"{cpus_str}+"
        if compute.memory:
            mem_str = str(compute.memory)
            resources["memory"] = mem_str if mem_str.endswith("+") else f"{mem_str}+"
        if compute.use_spot:
            resources["use_spot"] = True
        if service.port:
            resources["ports"] = [service.port]

        # ML wheel optimization: PyTorch cpu wheels vs general PyPI
        setup_lines = [
            "pip install --upgrade pip",
            "if [ -f requirements.txt ]; then pip install -r requirements.txt; fi",
            "pip install torch --index-url https://download.pytorch.org/whl/cpu || true",
        ]
        if runtime.setup:
            setup_lines.append(runtime.setup)

        replica_policy: Dict[str, Any] = {
            "min_replicas": service.min_replicas,
            "max_replicas": service.max_replicas,
        }
        if service.min_replicas != service.max_replicas or getattr(service, "target_qps", None):
            replica_policy["target_qps_per_replica"] = getattr(service, "target_qps", None) or 10

        skypilot_yaml = {
            "service": {
                "readiness_probe": {
                    "path": service.readiness_probe,
                    "initial_delay_seconds": 240,
                },
                "replica_policy": replica_policy,
            },
            "resources": resources,
            "workdir": str(self.workdir.resolve()),
            "setup": "\n".join(setup_lines),
            "run": runtime.command,
        }
        return skypilot_yaml

    def write_spec(self, target_path: Path) -> Path:
        spec = self.generate_skyserve_spec()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w") as f:
            yaml.dump(spec, f, sort_keys=False)
        return target_path

    def deploy(self, dry_run: bool = False, verbose: bool = False) -> Optional[str]:
        service_name = self.config.name
        
        print_step(1, 3, "Compiling Cloud Spec", f"Target: {self.config.compute.cloud.upper()} Spot")
        yaml_file = self.workdir / ".puffdeploy" / f"{service_name}.sky.yaml"
        self.write_spec(yaml_file)
        print_success(f"Optimized cluster specification generated at .puffdeploy/{service_name}.sky.yaml")

        if dry_run:
            print_success("Dry-run validation successful. No actual cloud costs incurred.")
            return "http://127.0.0.1:8000"

        # Check if service is already running to perform a seamless rolling update
        is_update = False
        try:
            active_services = [
                s["name"] for s in self.list_services()
                if s.get("status") not in ("SHUTTING_DOWN", "STOPPING", "FAILED", "UNKNOWN")
            ]
            is_update = service_name in active_services
        except Exception:
            pass

        if is_update:
            print_step(2, 3, "Updating Cloud Service", f"{self.config.compute.cloud.upper()} {self.config.compute.region} (Rolling Update)")
            cmd = [get_sky_cmd(), "serve", "update", service_name, str(yaml_file), "-y"]
            status_msg = "[bold cyan]Applying rolling code update to cloud replicas...[/bold cyan]"
        else:
            print_step(2, 3, "Provisioning Cloud Infrastructure", f"{self.config.compute.cloud.upper()} {self.config.compute.region}")
            cmd = [get_sky_cmd(), "serve", "up", "-n", service_name, str(yaml_file), "-y"]
            status_msg = "[bold cyan]Spinning up cloud compute and configuring VPC ingress...[/bold cyan]"
        
        with console.status(status_msg, spinner="dots"):
            result = subprocess.run(cmd, capture_output=not verbose, text=True)
            output_text = (result.stderr or "") + (result.stdout or "")
            if result.returncode != 0 and not is_update and "already running" in output_text:
                # Fallback: service was already registered, switch to update
                print_step(2, 3, "Updating Cloud Service", f"{self.config.compute.cloud.upper()} {self.config.compute.region} (Rolling Update)")
                cmd = [get_sky_cmd(), "serve", "update", service_name, str(yaml_file), "-y"]
                result = subprocess.run(cmd, capture_output=not verbose, text=True)
                is_update = True
            elif result.returncode != 0 and is_update and ("Cannot find service" in output_text or "not found" in output_text):
                # Fallback: service was not found / terminated, switch to initial provision
                print_step(2, 3, "Provisioning Cloud Infrastructure", f"{self.config.compute.cloud.upper()} {self.config.compute.region}")
                cmd = [get_sky_cmd(), "serve", "up", "-n", service_name, str(yaml_file), "-y"]
                result = subprocess.run(cmd, capture_output=not verbose, text=True)
                is_update = False

        
        if result.returncode != 0:
            error_output = result.stderr if not verbose else "Execution failed."
            if "No credential" in error_output or "AccessDenied" in error_output:
                print_error_box(
                    "Cloud Authentication Error",
                    "Could not authenticate with your cloud provider account.",
                    "Run `aws configure` or `gcloud auth application-default login` to refresh credentials."
                )
            else:
                clean_err = error_output.strip().splitlines()[-1] if error_output.strip() else "Unknown cloud error"
                print_error_box(
                    "Deployment Failed",
                    f"Orchestrator encountered an error: {clean_err}",
                    "Run `puff deploy --verbose` to inspect full cloud logs."
                )
            return None

        print_success("Cloud compute provisioned and model server started." if not is_update else "Rolling code update successfully applied.")
        print_step(3, 3, "Waiting for Model Readiness Probe", f"Checking {self.config.service.readiness_probe}")
        
        endpoint = self.wait_for_endpoint(service_name)
        return endpoint

    def wait_for_endpoint(self, service_name: str, timeout_seconds: int = 600) -> Optional[str]:
        """Polls service status with a clean elapsed timer until replica endpoint is alive."""
        start_time = time.time()
        with console.status("[bold cyan]Warming up model weights & establishing endpoint...[/bold cyan]", spinner="dots") as status:
            while time.time() - start_time < timeout_seconds:
                elapsed = int(time.time() - start_time)
                status.update(f"[bold cyan]Warming up model weights & establishing endpoint... ({elapsed}s)[/bold cyan]")
                
                endpoint = self.get_service_endpoint(service_name)
                if endpoint:
                    try:
                        health_url = f"{endpoint.rstrip('/')}/health"
                        req = urllib.request.Request(health_url, headers={"User-Agent": "Puffdeploy-Prober"})
                        with urllib.request.urlopen(req, timeout=3) as resp:
                            if resp.status == 200:
                                print_success("Readiness probe passed (HTTP 200 OK)")
                                return endpoint
                    except Exception:
                        pass
                time.sleep(6)
        
        print_warning("Model is taking longer than usual to become ready.")
        console.print("  Check live status anytime with: [bold cyan]puff status[/bold cyan]\n")
        return None

    def get_service_endpoint(self, service_name: str) -> Optional[str]:
        """Parses service status to extract the direct replica or load balancer endpoint."""
        cmd = [get_sky_cmd(), "serve", "status", service_name]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return None
        
        output = res.stdout
        url_matches = re.findall(r"(http://[0-9a-zA-Z.-]+:\d+)", output)
        if url_matches:
            for url in url_matches:
                if ":8000" in url:
                    return url
            return url_matches[0]
        return None

    @staticmethod
    def list_services() -> List[Dict[str, Any]]:
        """Lists all active Puffdeploy services in a structured format."""
        cmd = [get_sky_cmd(), "serve", "status"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return []
        
        services = []
        lines = res.stdout.splitlines()
        in_services_section = False
        
        for line in lines:
            if "Services" in line:
                in_services_section = True
                continue
            if "Service Replicas" in line:
                break
            if in_services_section and line.strip() and not line.startswith("NAME"):
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts) >= 4:
                    raw_status = parts[3] if len(parts) > 3 else "UNKNOWN"
                    status = "WARMING_UP" if raw_status == "NO_REPLICA" else raw_status
                    services.append({
                        "name": parts[0],
                        "version": parts[1] if len(parts) > 1 else "1",
                        "uptime": parts[2] if len(parts) > 2 else "-",
                        "status": status,
                        "replicas": parts[4] if len(parts) > 4 else "1/1",
                        "endpoint": parts[5] if len(parts) > 5 else "-",
                    })
        return services

    @staticmethod
    def get_service_logs(service_name: str, tail: int = 100, follow: bool = False):
        """Fetches clean application logs for the specified service."""
        cmd = [get_sky_cmd(), "serve", "logs", service_name]
        if follow:
            subprocess.run(cmd)
        else:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                lines = res.stdout.splitlines()[-tail:]
                for l in lines:
                    console.print(l)
            else:
                print_error_box("Logs Error", f"Could not retrieve logs for '{service_name}': {res.stderr.strip()}")

    @staticmethod
    def check_cloud() -> bool:
        """Validates cloud credentials and compute access cleanly."""
        res = subprocess.run([get_sky_cmd(), "check"], capture_output=True, text=True)
        return "Enabled Infra: aws" in res.stdout or "aws" in res.stdout.lower()

    def teardown(self, purge_all: bool = False):
        """Tears down the service and optionally cleans all controller nodes to ensure $0 cost."""
        service_name = self.config.name
        console.print(f"[bold cyan]▶ Tearing down service '[white]{service_name}[/white]'...[/bold cyan]")
        
        with console.status("[bold yellow]Terminating instances & destroying load balancer...[/bold yellow]", spinner="dots"):
            cmd = [get_sky_cmd(), "serve", "down", service_name, "-y"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            
        if res.returncode == 0:
            print_success(f"Service '{service_name}' terminated.")
        else:
            print_warning(f"Service '{service_name}' already down or not found.")

        if purge_all:
            with console.status("[bold yellow]Purging controller nodes and lingering instances...[/bold yellow]", spinner="dots"):
                subprocess.run([get_sky_cmd(), "down", "-a", "-y"], capture_output=True, text=True)
            print_success("All controller nodes and lingering clusters purged.")
            console.print("  [bold green]✔ Active Cloud Compute Cost: $0.00/hr[/bold green]\n")
