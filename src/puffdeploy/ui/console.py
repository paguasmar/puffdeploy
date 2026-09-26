import sys
from typing import Optional, List, Dict, Any
import rich
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.theme import Theme

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "dim": "dim white",
    "highlight": "bold cyan",
})

console = Console(theme=custom_theme)

LOGO = """[bold cyan]
  🐡 Puffdeploy[/bold cyan] [dim]v0.1.1[/dim]  [dim italic]Push to API in one command (AWS / GCP)[/dim italic]
"""

def print_banner():
    console.print(LOGO)

def print_step(step_num: int, total_steps: int, title: str, details: str = ""):
    step_indicator = f"[bold cyan][{step_num}/{total_steps}][/bold cyan]"
    msg = f"{step_indicator} [bold white]{title}[/bold white]"
    if details:
        msg += f" [dim]({details})[/dim]"
    console.print(msg)

def print_success(message: str):
    console.print(f"  [bold green]✔[/bold green] {message}")

def print_warning(message: str):
    console.print(f"  [bold yellow]⚠[/bold yellow] {message}")

def print_error_box(title: str, reason: str, suggestion: Optional[str] = None):
    content = f"[bold red]{reason}[/bold red]"
    if suggestion:
        content += f"\n\n[bold yellow]💡 How to fix:[/bold yellow]\n[white]{suggestion}[/white]"
        
    console.print()
    console.print(Panel(
        content,
        title=f"[bold red]✖ {title}[/bold red]",
        border_style="red",
        padding=(1, 2),
        expand=False
    ))
    console.print()

def print_curl_box(service_name: str, endpoint_url: str, sample_payload: str = '{"prompt": "Hello Puffdeploy"}'):
    predict_url = f"{endpoint_url.rstrip('/')}/predict"
    health_url = f"{endpoint_url.rstrip('/')}/health"
    
    curl_command = (
        f"curl -X POST {predict_url} \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f"  -d '{sample_payload}'"
    )
    
    body = (
        f"[bold green]✨ Endpoint is LIVE in your private cloud VPC![/bold green]\n\n"
        f"  [bold white]Service:[/bold white]      [cyan]{service_name}[/cyan]\n"
        f"  [bold white]Predict API:[/bold white]  [underline blue]{predict_url}[/underline blue]\n"
        f"  [bold white]Health:[/bold white]       [dim]{health_url}[/dim]\n\n"
        f"[bold yellow]👉 Test your inference instantly:[/bold yellow]\n\n"
        f"[bold white]{curl_command}[/bold white]"
    )
    
    console.print()
    console.print(Panel(
        body,
        title="[bold green]🐡 Puffdeploy Deployment Success 🐡[/bold green]",
        border_style="green",
        padding=(1, 2),
        expand=False
    ))
    console.print()

def print_services_table(services: List[Dict[str, Any]]):
    """Prints a polished table of active Puffdeploy services."""
    if not services:
        console.print("[dim]No active Puffdeploy services running on your cloud account.[/dim]\n")
        console.print("Deploy a model with: [bold cyan]puff deploy[/bold cyan]\n")
        return

    table = Table(
        title="🐡 Active Puffdeploy Services",
        header_style="bold cyan",
        border_style="dim",
        expand=True,
    )
    table.add_column("Service Name", style="bold white")
    table.add_column("Status", justify="center")
    table.add_column("Replicas", justify="center")
    table.add_column("Endpoint (Predict URL)", style="blue underline")
    table.add_column("Uptime", style="dim")

    for s in services:
        status = s.get("status", "UNKNOWN")
        if status == "READY":
            status_badge = "[bold green]● READY[/bold green]"
        elif status in ("WARMING_UP", "NO_REPLICA"):
            status_badge = "[bold yellow]○ WARMING_UP[/bold yellow]"
        elif status in ("STARTING", "PROVISIONING", "INITIALIZING"):
            status_badge = "[bold yellow]○ STARTING[/bold yellow]"
        elif status in ("SHUTTING_DOWN", "STOPPING"):
            status_badge = "[bold red]◌ STOPPING[/bold red]"
        elif status == "FAILED":
            status_badge = "[bold red]✖ FAILED[/bold red]"
        else:
            status_badge = f"[dim]{status}[/dim]"

        table.add_row(
            s.get("name", "N/A"),
            status_badge,
            s.get("replicas", "1/1"),
            s.get("endpoint", "N/A"),
            s.get("uptime", "N/A"),
        )

    console.print()
    console.print(table)
    console.print()
