import os
import sys
from pathlib import Path
from typing import Optional
import typer

from puffdeploy import __version__
from puffdeploy.config import PuffConfig, PuffConfig
from puffdeploy.orchestrator.skypilot import SkyPilotOrchestrator
from puffdeploy.packager.truss_driver import Packager
from puffdeploy.ui.console import (
    console,
    print_banner,
    print_step,
    print_success,
    print_error_box,
    print_warning,
    print_curl_box,
    print_services_table,
)

app = typer.Typer(
    name="puff",
    help="Puffdeploy 🐡 - Push to API in one command. Serverless ML deployment in your AWS/GCP account.",
    no_args_is_help=True,
    add_completion=False,
)

@app.command()
def init(
    name: str = typer.Argument("my-model-service", help="Name of your model service"),
    gpu: str = typer.Option(None, "--gpu", "-g", help="GPU accelerator type (e.g. T4:1, A10G:1, L4:1)"),
):
    """Initialize a lightweight, production-ready Puffdeploy model project."""
    print_banner()
    workdir = Path(".")
    
    print_step(1, 2, "Scaffolding model service", name)
    Packager.scaffold_starter_project(workdir, name)
    print_success("Created app.py (FastAPI inference template) & requirements.txt")
    
    print_step(2, 2, "Writing cloud configuration", "puff.yaml")
    config = PuffConfig(name=name)
    if gpu:
        config.compute.accelerator = gpu
    config.save(workdir / "puff.yaml")
    print_success("Configuration saved to puffdeploy.yaml")
    
    console.print("\n[bold green]🚀 Ready to build and deploy:[/bold green]")
    console.print("  • Test locally:  [cyan]uvicorn app:app --reload --port 8000[/cyan]")
    console.print("  • Deploy to AWS: [bold cyan]puff deploy[/bold cyan]\n")

@app.command()
def check():
    """Verify cloud provider credentials, VPC ingress, and compute quota."""
    print_banner()
    console.print("[bold cyan]▶ Verifying cloud credentials and compute access...[/bold cyan]\n")
    
    with console.status("[bold cyan]Checking AWS/GCP cloud configurations...[/bold cyan]", spinner="dots"):
        is_ok = SkyPilotOrchestrator.check_cloud()
    
    if is_ok:
        print_success("Cloud Provider: [bold green]AWS Connected & Verified[/bold green]")
        print_success("Compute Access: [bold green]EC2 On-Demand & Spot Quotas Available[/bold green]")
        console.print("\n[bold green]✔ All systems operational. Ready to deploy with `puff deploy`![/bold green]\n")
    else:
        print_error_box(
            "Cloud Credentials Not Found",
            "Could not verify access to AWS or GCP.",
            "Run `aws configure` to set your AWS Access Key, Secret, and default region."
        )

@app.command()
def deploy(
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and generate cloud specs without launching EC2 instances"),
    cloud: Optional[str] = typer.Option(None, "--cloud", help="Target cloud provider (aws/gcp)"),
    region: Optional[str] = typer.Option(None, "--region", help="Cloud region"),
    gpu: Optional[str] = typer.Option(None, "--gpu", "-g", help="Override GPU accelerator (e.g. T4:1, A10G:1)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed verbose logs"),
):
    """Deploy your model service to AWS/GCP and get an instant, production-ready cURL endpoint."""
    print_banner()
    workdir = Path(".")
    
    config_file = PuffConfig.find_config_file(workdir)
    if not config_file and not (workdir / "app.py").exists():
        print_error_box(
            "Project Not Found",
            "No 'puff.yaml' or 'app.py' found in the current directory.",
            "Run `puff init` to create a starter project or add `app.py`."
        )
        raise typer.Exit(code=1)
        
    config = PuffConfig.load_or_default(config_file, workdir=workdir)
    
    if cloud:
        config.compute.cloud = cloud
    if region:
        config.compute.region = region
    if gpu:
        config.compute.accelerator = gpu
        
    orchestrator = SkyPilotOrchestrator(config, workdir)
    
    try:
        endpoint = orchestrator.deploy(dry_run=dry_run, verbose=verbose)
        if endpoint:
            print_curl_box(
                service_name=config.name,
                endpoint_url=endpoint,
                sample_payload='{"prompt": "Deploying LLMs without DevOps friction!"}'
            )
    except Exception as e:
        if verbose:
            raise e
        print_error_box("Unexpected Error", str(e), "Use `puff deploy --verbose` to view stack trace.")
        raise typer.Exit(code=1)

@app.command()
def status():
    """Check the status of all active Puffdeploy services in your cloud account."""
    print_banner()
    services = SkyPilotOrchestrator.list_services()
    print_services_table(services)

@app.command()
def logs(
    name: str = typer.Argument(None, help="Service name to view logs for"),
    tail: int = typer.Option(100, "--tail", "-t", help="Number of trailing log lines to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow live log output stream"),
    replica: str = typer.Option("1", "--replica", "-r", help="Replica ID to view logs from"),
):
    """View application logs for a running Puffdeploy service."""
    print_banner()
    workdir = Path(".")
    config = PuffConfig.load_or_default(workdir / "puff.yaml")
    service_name = name or config.name
    
    console.print(f"[bold cyan]▶ Fetching logs for service '[white]{service_name}[/white]' (replica {replica})...[/bold cyan]\n")
    SkyPilotOrchestrator.get_service_logs(service_name, tail=tail, follow=follow, replica=replica)

@app.command()
def down(
    name: str = typer.Option(None, "--name", "-n", help="Service name to teardown"),
    purge_all: bool = typer.Option(False, "--all", "-a", help="Purge all controller nodes and lingering clusters to ensure $0 cost"),
):
    """Tear down cloud resources cleanly to stop incurring costs."""
    print_banner()
    workdir = Path(".")
    config = PuffConfig.load_or_default(workdir / "puff.yaml")
    if name:
        config.name = name
        
    orchestrator = SkyPilotOrchestrator(config, workdir)
    orchestrator.teardown(purge_all=purge_all)

@app.command()
def version():
    """Display the Puffdeploy CLI version."""
    console.print(f"[bold cyan]Puffdeploy CLI[/bold cyan] version [bold green]{__version__}[/bold green]")

if __name__ == "__main__":
    app()
