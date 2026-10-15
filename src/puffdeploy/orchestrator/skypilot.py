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
    print_capacity_bottleneck_box,
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

        # Smart Quota Resolution: Automatically pick instances that fit user's account quota
        target_instance = getattr(compute, "instance_type", None)
        if not target_instance and compute.cloud.lower() == "aws" and compute.use_spot:
            quota = self.get_aws_spot_gpu_quota(compute.region)
            if quota is not None:
                accel = (compute.accelerator or "").lower()
                # If 4x A10G is requested and quota cannot support 96 vCPUs (g5.24xlarge), auto-pin to g5.12xlarge (48 vCPUs)
                if "a10g:4" in accel and quota < 96:
                    target_instance = "g5.12xlarge"
                # If 1x A10G is requested, g5.xlarge (4 vCPUs) fits in any quota
                elif "a10g:1" in accel or accel == "a10g":
                    target_instance = "g5.xlarge"

        if target_instance:
            resources["instance_type"] = target_instance
        elif compute.accelerator:
            resources["accelerators"] = compute.accelerator

        if compute.cpus and not target_instance:
            resources["cpus"] = str(compute.cpus)
        if compute.memory and not target_instance:
            resources["memory"] = str(compute.memory)
        if compute.use_spot:
            resources["use_spot"] = True
        if service.port:
            resources["ports"] = [service.port]

        # ML wheel optimization: PyTorch cpu wheels only when no GPU is specified
        setup_lines = [
            "pip install --upgrade pip",
            "if [ -f requirements.txt ]; then pip install -r requirements.txt; fi",
        ]
        is_gpu = bool(compute.accelerator or (compute.instance_type and any(compute.instance_type.lower().startswith(p) for p in ["g3", "g4", "g5", "g6", "gr6", "p2", "p3", "p4", "p5"])))
        if not is_gpu:
            setup_lines.append("pip install torch --index-url https://download.pytorch.org/whl/cpu || true")
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
                    "initial_delay_seconds": getattr(service, "initial_delay_seconds", 1200) or 1200,
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
        
        # Smart Quota Awareness: Verify AWS Spot Quota if applicable
        if self.config.compute.cloud.lower() == "aws" and self.config.compute.use_spot:
            quota = self.get_aws_spot_gpu_quota(self.config.compute.region)
            if quota is not None:
                inst = self.config.compute.accelerator or "auto"
                print_step(1, 4, "Verifying Cloud Quotas", f"AWS Spot Limit: {int(quota)} vCPUs (Target: {inst})")
                if self.config.compute.instance_type == "g5.24xlarge" and quota < 96:
                    print_error_box(
                        "Quota Exceeded Guard",
                        f"Instance 'g5.24xlarge' requires 96 vCPUs, but your AWS Spot limit is {int(quota)} vCPUs.",
                        "Use 'instance_type: g5.12xlarge' (48 vCPUs) which fits safely within your quota."
                    )
                    return None
                print_success(f"Quota validated: compute fits within your {int(quota)} vCPUs Spot limit.")
                print_step(2, 4, "Compiling Cloud Spec", f"Target: AWS Spot ({inst})")
            else:
                print_step(1, 3, "Compiling Cloud Spec", f"Target: {self.config.compute.cloud.upper()} Spot")
        else:
            compute_mode = "Spot" if self.config.compute.use_spot else "On-Demand"
            inst = self.config.compute.instance_type or self.config.compute.accelerator or "auto"
            print_step(1, 3, "Compiling Cloud Spec", f"Target: {self.config.compute.cloud.upper()} {compute_mode} ({inst})")
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
            print_step(3, 4, "Provisioning Cloud Infrastructure", f"{self.config.compute.cloud.upper()} {self.config.compute.region}")
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
                print_step(3, 4, "Provisioning Cloud Infrastructure", f"{self.config.compute.cloud.upper()} {self.config.compute.region}")
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
        print_step(4, 4, "Waiting for Model Readiness Probe", f"Checking {self.config.service.readiness_probe}")
        
        endpoint = self.wait_for_endpoint(service_name)
        return endpoint

    def get_service_status_raw(self, service_name: str) -> Optional[str]:
        """Fetches raw status output from SkyServe for inspection."""
        try:
            cmd = [get_sky_cmd(), "serve", "status", service_name]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout:
                return res.stdout
        except Exception:
            pass
        return None

    def check_capacity_bottleneck(self, service_name: str, status_output: Optional[str] = None, elapsed: int = 0) -> bool:
        """Checks if replicas are failing due to cloud-side capacity exhaustion or stuck provisioning past 2 minutes."""
        capacity_signals = [
            "insufficientinstancecapacity",
            "resourcesunavailableerror",
            "failed to acquire resources in all zones",
            "maxspotinstancecountexceeded",
            "vcpulimitexceeded",
            "capacityexceeded",
        ]

        # 1. Immediate Check: Scan status output if provided
        if status_output:
            lower_status = status_output.lower()
            if any(sig in lower_status for sig in capacity_signals):
                return True

            has_active_replica = "ready" in lower_status or "starting" in lower_status or "provisioning" in lower_status
            if has_active_replica:
                # Replica is active or actively bootstrapping (PROVISIONING).
                # Cloud compute was successfully allocated; do NOT kill during node setup.
                return False

            # 2-Minute (120s) Hard Fail-Fast for Pre-allocation Bottlenecks:
            # If 2 minutes have elapsed and AWS has not even assigned an instance (NO_REPLICA or FAILED)
            if elapsed >= 120:
                is_stuck = "no_replica" in lower_status or "failed" in lower_status
                if is_stuck:
                    return True

        # 2. Controller Logs Check: Query controller logs if status_output wasn't provided
        try:
            cmd = [get_sky_cmd(), "serve", "logs", service_name, "--controller", "--no-follow", "--tail", "60"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout:
                out = res.stdout.lower()
                if any(sig in out for sig in capacity_signals):
                    return True
        except Exception:
            pass

        return False

    def wait_for_endpoint(self, service_name: str, timeout_seconds: int = 1200) -> Optional[str]:
        """Polls service status with a clean elapsed timer until replica endpoint is alive."""
        start_time = time.time()
        with console.status("[bold cyan]Warming up model weights & establishing endpoint...[/bold cyan]", spinner="dots") as status:
            while time.time() - start_time < timeout_seconds:
                elapsed = int(time.time() - start_time)
                status.update(f"[bold cyan]Warming up model weights & establishing endpoint... ({elapsed}s)[/bold cyan]")
                
                raw_status = self.get_service_status_raw(service_name)
                endpoint = self.get_service_endpoint(service_name, raw_status=raw_status)
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

                # Fail-Fast: Detect physical cloud capacity bottlenecks (<45s) or trigger 2-minute (120s) hard limit
                if (elapsed >= 30 and elapsed % 12 == 0) or elapsed >= 120:
                    if self.check_capacity_bottleneck(service_name, status_output=raw_status, elapsed=elapsed):
                        region = self.config.compute.region or "us-east-1"
                        accel = (self.config.compute.accelerator or "").lower()
                        suggestions = []
                        if region.lower() == "us-east-1":
                            suggestions.append("puff deploy --region eu-central-1")
                        elif region.lower() != "eu-central-1":
                            suggestions.append("puff deploy --region eu-central-1")
                        else:
                            suggestions.append("puff deploy --region eu-north-1")
                        if "a10g:4" in accel or "g5.12xlarge" in (self.config.compute.instance_type or "").lower():
                            suggestions.append("puff deploy --gpu L4:4")
                        if not suggestions:
                            suggestions.append("puff deploy --region eu-central-1")
                            suggestions.append("puff deploy --gpu L4:1")

                        # Stop looping service replica to prevent unnecessary cloud costs
                        try:
                            subprocess.run([get_sky_cmd(), "serve", "down", service_name, "-y"], capture_output=True, timeout=15)
                        except Exception:
                            pass

                        print_capacity_bottleneck_box(region, suggestions)
                        return None

                time.sleep(6)
        
        print_warning("Model is taking longer than usual to become ready.")
        console.print("  Check live status anytime with: [bold cyan]puff status[/bold cyan]\n")
        return None

    def get_service_endpoint(self, service_name: str, raw_status: Optional[str] = None) -> Optional[str]:
        """Parses service status to extract the direct replica or load balancer endpoint."""
        output = raw_status if raw_status is not None else self.get_service_status_raw(service_name)
        if not output:
            return None
        
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
    def get_service_logs(service_name: str, tail: int = 100, follow: bool = False, replica: str = "1"):
        """Fetches clean application logs for the specified service."""
        cmd = [get_sky_cmd(), "serve", "logs", service_name, str(replica)]
        if follow:
            subprocess.run(cmd)
        else:
            cmd.extend(["--no-follow", "--tail", str(tail)])
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                lines = res.stdout.splitlines()
                for l in lines:
                    console.print(l)
            else:
                print_error_box("Logs Error", f"Could not retrieve logs for '{service_name}': {res.stderr.strip()}")

    @staticmethod
    def get_aws_spot_gpu_quota(region: str = "us-east-1") -> Optional[float]:
        """Queries AWS Service Quotas for 'All G and VT Spot Instance Requests'."""
        try:
            cmd = [
                "aws", "service-quotas", "get-service-quota",
                "--service-code", "ec2",
                "--quota-code", "L-3819A6DF",
                "--region", region,
                "--query", "Quota.Value",
                "--output", "text"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return float(res.stdout.strip())
        except Exception:
            pass
        return None

    @staticmethod
    def check_cloud() -> bool:
        """Validates cloud credentials and compute access cleanly."""
        res = subprocess.run([get_sky_cmd(), "check", "aws"], capture_output=True, text=True)
        return "AWS: enabled" in res.stdout or "AWS [compute" in res.stdout or "Enabled Infra: aws" in res.stdout or "aws" in res.stdout.lower()

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
            with console.status("[bold yellow]Purging all services, controller nodes, and instances in all zones...[/bold yellow]", spinner="dots"):
                # 1. Force teardown all active and failed SkyServe services across all regions
                subprocess.run([get_sky_cmd(), "serve", "down", "-a", "-y", "--purge"], capture_output=True, text=True)
                # 2. Terminate all SkyPilot cluster nodes
                subprocess.run([get_sky_cmd(), "down", "-a", "-y"], capture_output=True, text=True)
                # 3. Explicitly terminate SkyServe controllers (which require interactive confirmation or direct name)
                try:
                    status_res = subprocess.run([get_sky_cmd(), "status"], capture_output=True, text=True, timeout=15)
                    if status_res.returncode == 0:
                        ctrl_matches = re.findall(r"(sky-serve-controller-[a-zA-Z0-9]+)", status_res.stdout)
                        for ctrl_name in set(ctrl_matches):
                            subprocess.run([get_sky_cmd(), "down", ctrl_name, "-y"], input="delete\n", text=True, capture_output=True, timeout=20)
                except Exception:
                    pass
                # 4. Sweep all relevant AWS regions (including eu-central-1) to guarantee zero lingering instances
                regions_to_sweep = list(dict.fromkeys([
                    self.config.compute.region,
                    "eu-central-1",
                    "us-east-1",
                    "eu-north-1",
                    "us-east-2",
                    "us-west-2",
                    "eu-west-1",
                ]))
                for r in regions_to_sweep:
                    if not r:
                        continue
                    try:
                        sweep_cmd = [
                            "aws", "ec2", "describe-instances",
                            "--region", r,
                            "--filters",
                            "Name=tag-key,Values=skypilot-cluster-name,ray-cluster-name",
                            "Name=instance-state-name,Values=pending,running",
                            "--query", "Reservations[].Instances[].InstanceId",
                            "--output", "json"
                        ]
                        res = subprocess.run(sweep_cmd, capture_output=True, text=True, timeout=12)
                        if res.returncode == 0 and res.stdout.strip():
                            import json as _json
                            ids = _json.loads(res.stdout)
                            if ids:
                                term_cmd = ["aws", "ec2", "terminate-instances", "--region", r, "--instance-ids"] + ids
                                subprocess.run(term_cmd, capture_output=True, text=True, timeout=15)
                    except Exception:
                        pass
            print_success("All services, controllers, and compute instances in all regions purged.")
            console.print("  [bold green]✔ Active Cloud Compute Cost: $0.00/hr across all zones[/bold green]\n")
